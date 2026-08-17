"""
Farm Rover — Decision Engine (runs on the laptop)

Loop:
  Capture frame from ESP32-CAM stream
  -> Run disease detection
  -> Healthy?  yes: keep patrolling
              no : stop, save GPS+image, request soil scan, irrigate if needed, resume
  Meanwhile: continuously drain Arduino Mega serial lines for
             OBSTACLE / GPS / ENCODER / STATUS and react to them.

Python NEVER drives motors/pumps directly — it only sends high-level
commands (F/B/L/R/S, PUMP,x,ON/OFF, SCAN) over serial_manager.
"""
import time
import os
import threading
import cv2

import config
from logger import get_logger
from serial_manager import SerialManager
from wifi_manager import WifiManager
from command_sender import CommandSender
import command_receiver
from disease_detector import DiseaseDetector
from gps import GpsTracker
import irrigation
from navigation import handle_obstacle, resume_patrol
from state import SharedState
from dashboard import create_app
import climate


def climate_loop(state, gps_tracker, logger):
    """Runs forever in a background thread: periodically fetches the
    weather-based crop outlook and stores it in SharedState."""
    while True:
        fix = gps_tracker.last_fix
        lat = fix["lat"] if fix else None
        lon = fix["lon"] if fix else None
        dht_reading = state.snapshot().get("dht")
        outlook = climate.get_crop_outlook(lat, lon, dht_reading)
        state.update_climate(outlook)
        logger.info(f"Climate outlook: {outlook.get('verdict')} — {outlook.get('flags')}")
        time.sleep(config.CLIMATE_CHECK_INTERVAL_SEC)


def open_link(logger):
    """Returns a SerialManager or WifiManager depending on
    config.CONNECTION_MODE — both expose the same .send()/.get_line()/
    .close() interface, so nothing downstream needs to know which one
    it got."""
    if config.CONNECTION_MODE == "wifi":
        logger.info(f"Connecting to ESP32 bridge at {config.ESP32_BRIDGE_IP}:{config.ESP32_BRIDGE_PORT} ...")
        return WifiManager(config.ESP32_BRIDGE_IP, config.ESP32_BRIDGE_PORT, logger)
    elif config.CONNECTION_MODE == "usb":
        logger.info(f"Opening USB serial on {config.SERIAL_PORT} ...")
        return SerialManager(config.SERIAL_PORT, config.SERIAL_BAUD, logger)
    else:
        raise ValueError(f"Unknown CONNECTION_MODE: {config.CONNECTION_MODE!r} (use 'usb' or 'wifi')")


def run_soil_scan_and_irrigation(sender, ser, state, logger, trigger_reason="STARTUP"):
    """Performs soil probe scan. Arduino hardware handles on-board 15s relay watering if dry/missing signal."""
    logger.info(f"--- Starting Soil Scan & Irrigation Cycle ({trigger_reason}) ---")
    state.update_status(f"SCANNING & IRRIGATING ({trigger_reason})")
    sender.request_scan()
    pending_scan = None
    deadline = time.time() + 4.0
    while pending_scan is None and time.time() < deadline:
        line = ser.get_line(timeout=0.2)
        if line:
            ev, d = command_receiver.parse_line(line)
            if ev == "SCAN":
                pending_scan = d
                state.update_soil(irrigation.decide_pumps(d))
            elif ev == "STATUS":
                logger.info(f"Arduino status: {d.get('text')}")
                state.update_status(d.get("text", ""))
    if pending_scan:
        logger.info(f"Soil scan complete: {pending_scan}")
    else:
        logger.info("No live hardware scan reply received; scan request logged.")


def main():
    logger = get_logger()
    os.makedirs(config.IMAGE_DIR, exist_ok=True)

    logger.info("Initializing link to Arduino Mega...")
    ser = open_link(logger)
    sender = CommandSender(ser)

    logger.info("Loading ML model...")
    detector = DiseaseDetector()

    state = SharedState()

    logger.info(f"Starting dashboard on http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}/")
    dash_app = create_app(state, detector, sender=sender)
    threading.Thread(
        target=lambda: dash_app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT,
                                     debug=False, use_reloader=False),
        daemon=True,
    ).start()

    logger.info(f"Opening camera stream: {config.CAMERA_STREAM_URL}")
    cap = cv2.VideoCapture(config.CAMERA_STREAM_URL)

    gps_tracker = GpsTracker()
    pending_scan = None  # holds SCAN data once Arduino replies
    last_infer = 0.0
    driving = True

    logger.info("Starting climate/crop-outlook background thread...")
    threading.Thread(target=climate_loop, args=(state, gps_tracker, logger), daemon=True).start()

    # === PROGRAM STARTUP: Execute Initial Baseline Irrigation Right Away ===
    logger.info("=== PROGRAM STARTUP: Executing Initial Irrigation Check ===")
    run_soil_scan_and_irrigation(sender, ser, state, logger, trigger_reason="PROGRAM_STARTUP")

    logger.info("Starting rover patrol...")
    sender.forward()
    state.set_driving(True)

    try:
        while True:
            # ---- 0) sync hardware link state ----
            state.update_wifi(ser.is_connected())

            # ---- 1) drain all pending Arduino lines ----
            while True:
                line = ser.get_line(timeout=0)
                if line is None:
                    break
                event, data = command_receiver.parse_line(line)
                if event == "OBSTACLE":
                    state.update_obstacle(data["cm"])
                    if handle_obstacle(sender, data["cm"], logger):
                        driving = False
                        state.set_driving(False)
                elif event == "GPS":
                    gps_tracker.update(data)
                    state.update_gps(data)
                elif event == "SCAN":
                    pending_scan = data  # raw values, used by irrigation.py
                    state.update_soil(irrigation.decide_pumps(data))  # readable pct/water_level for dashboard
                elif event == "STATUS":
                    logger.info(f"Arduino status: {data['text']}")
                    state.update_status(data["text"])
                elif event == "DHT":
                    state.update_dht(data)
                elif event == "ENCODER":
                    state.update_encoder(data["count"])

            # ---- 2) camera + ML (rate-limited) ----
            now = time.time()
            if now - last_infer >= config.INFERENCE_INTERVAL_SEC:
                last_infer = now
                ok, frame = cap.read()
                if ok:
                    label, conf, accepted = detector.check(frame)
                    if accepted:
                        is_healthy = detector.is_healthy(label)
                        status_str = "Healthy Plant" if is_healthy else f"Stress/Disease ({label})"
                        logger.info(f"Plant Detected: {status_str} (confidence: {conf:.2f})")
                        diag = detector.diagnose(frame)
                        state.set_disease_diagnostic(diag)

                        # 1. Stop & move closer to the plant for close inspection & probe scan
                        sender.stop()
                        driving = False
                        state.set_driving(False)
                        logger.info(f"Approaching plant ({status_str}) for soil moisture scan...")
                        sender.forward()
                        time.sleep(1.2)  # Move closer to plant
                        sender.stop()

                        # 2. Save diagnostic event & image
                        gps_tracker.save_event(tag=label)
                        ts = int(now)
                        img_path = os.path.join(config.IMAGE_DIR, f"{label}_{ts}.jpg")
                        cv2.imwrite(img_path, frame)
                        logger.info(f"Saved plant diagnostic image: {img_path}")

                        # 3. Perform Soil Probe Scan & Moisture-Based Irrigation Cycle
                        run_soil_scan_and_irrigation(sender, ser, state, logger, trigger_reason=f"PLANT_CHECK_{label}")

                        # 4. Resume patrol
                        logger.info("Soil check & irrigation complete. Resuming patrol...")
                        resume_patrol(sender)
                        driving = True
                        state.set_driving(True)

            time.sleep(0.02)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        sender.stop()
        ser.close()
        cap.release()


if __name__ == "__main__":
    main()
