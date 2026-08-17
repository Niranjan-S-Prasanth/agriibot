"""Python-hosted Flask Web Dashboard for Farm Rover.

Provides:
  - Renders modern mobile-first all-in-one HTML dashboard (templates/index.html)
  - Telemetry streaming API (/telemetry)
  - Camera frame plant disease diagnosis (/api/diagnose_frame)
  - 25+ Crop microclimate risk evaluation & simulation (/api/crop_climate, /api/update_climate_sim)
  - Agronomist Chatbot Assistant Q&A (/api/ask_assistant)
  - Manual Rover driving & irrigation pump control (/cmd/<command>)
"""
import base64
import os
import time
import cv2
import numpy as np
try:
    import pandas as pd
except ImportError:
    pd = None
from flask import Flask, request, jsonify, render_template, send_from_directory

import config
import climate
from disease_detector import DiseaseDetector

from weather_service import WeatherService

UPLOAD_DIR = os.path.join(config.IMAGE_DIR, "uploads")


def create_app(state, detector=None, sender=None):
    """state: state.SharedState instance.
    detector: disease_detector.DiseaseDetector instance.
    sender: command_sender.CommandSender instance for live hardware control."""
    os.makedirs(config.IMAGE_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Start WeatherAPI background service
    try:
        ws = WeatherService(state)
        ws.start()
    except Exception as e:
        print(f"Warning: Could not start WeatherService: {e}")

    if detector is None:
        try:
            detector = DiseaseDetector()
        except Exception as e:
            print(f"Warning: Could not initialize DiseaseDetector in dashboard: {e}")

    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Load Chatbot Dataset if available
    chatbot_df = None
    cb_csv = os.path.abspath(os.path.join(os.path.dirname(__file__), "../PlantDoc/Model_assest/DiseaseChatbotData.csv"))
    if os.path.exists(cb_csv):
        try:
            chatbot_df = pd.read_csv(cb_csv)
        except Exception as e:
            print(f"Warning: Could not read Chatbot dataset: {e}")

    @app.route("/")
    def index():
        return render_template("index.html", stream_url=config.CAMERA_STREAM_URL)

    @app.route("/telemetry")
    def telemetry():
        return jsonify(state.snapshot())

    @app.route("/images/<path:filename>")
    def serve_image(filename):
        return send_from_directory(config.IMAGE_DIR, filename)

    @app.route("/gallery")
    def gallery():
        files = []
        for root, _, names in os.walk(config.IMAGE_DIR):
            for n in names:
                if n.lower().endswith((".jpg", ".jpeg", ".png")):
                    rel = os.path.relpath(os.path.join(root, n), config.IMAGE_DIR)
                    files.append(rel.replace(os.sep, "/"))
        files.sort(reverse=True)
        return jsonify(files[:60])

    @app.route("/api/diagnose_frame", methods=["POST"])
    def diagnose_frame():
        if detector is None:
            return jsonify({"status": "error", "message": "Disease detector model not loaded"}), 500

        data = request.get_json(silent=True) or {}
        frame = None

        if "image" in data and data["image"].startswith("data:image"):
            try:
                header, encoded = data["image"].split(",", 1)
                img_bytes = base64.b64decode(encoded)
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                return jsonify({"status": "error", "message": f"Failed to decode base64 image: {e}"}), 400
        elif "photo" in request.files:
            f = request.files["photo"]
            if f.filename != "":
                ts = int(time.time())
                save_path = os.path.join(UPLOAD_DIR, f"upload_{ts}_{f.filename}")
                f.save(save_path)
                frame = cv2.imread(save_path)

        target_crop = (data.get("target_crop") if isinstance(data, dict) else None) or request.form.get("target_crop")
        if target_crop == "AUTO":
            target_crop = None

        diag = detector.diagnose(frame, target_crop=target_crop)
        state.set_disease_diagnostic(diag)

        # If uploaded/captured photo shows a valid plant leaf, trigger soil moisture scan & check
        if diag.get("is_plant"):
            plant_tag = "HEALTHY" if diag.get("is_healthy") else "STRESSED"
            state.update_status(f"PLANT CHECK VIA UPLOAD ({plant_tag}): {diag.get('label')}")
            state.log_pump_event("BOTH", 3.0, trigger=f"UPLOADED_PHOTO_{plant_tag}", deficit_pct=15.0)
            if sender:
                sender.request_scan()

        return jsonify({"status": "success", "diagnosis": diag})

    @app.route("/api/crop_climate")
    def crop_climate():
        snap = state.snapshot()
        dht = snap.get("dht", {})
        sim = snap.get("climate_sim", {})

        if sim.get("enabled"):
            dht = {"temp_c": sim.get("temp_c"), "humidity": sim.get("humidity")}

        outlook = climate.get_crop_outlook(dht_reading=dht)
        return jsonify(outlook)

    @app.route("/api/update_climate_sim", methods=["POST"])
    def update_climate_sim():
        data = request.get_json(silent=True) or {}
        temp = float(data.get("temp", 28.5))
        hum = float(data.get("humidity", 75.0))
        enabled = bool(data.get("enabled", True))
        state.set_climate_sim(temp, hum, enabled)
        return jsonify({"status": "success", "temp": temp, "humidity": hum, "enabled": enabled})

    @app.route("/api/reset_climate_sim", methods=["POST"])
    def reset_climate_sim():
        state.set_climate_sim(28.5, 75.0, False)
        return jsonify({"status": "success", "mode": "live"})

    @app.route("/api/ask_assistant", methods=["POST"])
    def ask_assistant():
        data = request.get_json(silent=True) or {}
        q = data.get("question", "").strip()

        if not q:
            return jsonify({"answer": "Please ask a farming or crop disease question!"})

        snap = state.snapshot()

        # Try Hack Club Qwen 32B AI API first
        try:
            import ai_assistant
            ai_ans = ai_assistant.answer_farmer_question(q, state_snapshot=snap)
            if ai_ans:
                return jsonify({"answer": ai_ans})
        except Exception as e:
            print(f"AI Assistant API fallback triggered: {e}")

        # Local Dataset Fallback
        q_lower = q.lower()
        if chatbot_df is not None:
            for idx, row in chatbot_df.iterrows():
                dname = str(row.get("disease_name", "")).lower()
                if dname and any(term in q_lower for term in dname.split()):
                    ans = f"🌱 **{row.get('disease_name')}**:\n\n"
                    ans += f"**Description**: {row.get('description')}\n\n"
                    ans += f"**Remedy Steps**: {row.get('Possible Steps')}\n\n"
                    if row.get("supplement_name"):
                        ans += f"**Recommended Supplement**: {row.get('supplement_name')}"
                    return jsonify({"answer": ans})

        for cat, plants in climate.ALL_PLANTS.items():
            for plant, info in plants.items():
                if plant.lower() in q_lower:
                    ans = f"🌾 **{plant} ({cat})**:\n\n"
                    ans += f"• **Ideal Microclimate**: Temp {info['min_t']}°C–{info['max_t']}°C | Humidity {info['min_h']}%–{info['max_h']}%\n"
                    ans += f"• **Diseases**: {info['diseases']}\n"
                    ans += f"• **Microclimate Risk**: {info['risk']}\n\n"
                    ans += f"• **Agronomist Solution**:\n{info['solution']}"
                    return jsonify({"answer": ans})

        return jsonify({"answer": "I recommend inspecting crop foliage using the **Plant Scanner** or maintaining soil moisture between 60% and 80%. For severe leaf discoloration, apply organic neem oil spray or 1% Bordeaux mixture."})

        return jsonify({"answer": "I recommend inspecting the crop foliage using the live **Plant Scanner** tab or maintaining soil moisture between 60% and 80%. For severe leaf discoloration, apply organic neem oil spray or 1% Bordeaux mixture preventative."})

    @app.route("/cmd/<command>", methods=["POST"])
    def handle_cmd(command):
        cmd = command.upper()
        if cmd in ["FORWARD", "F"]:
            state.set_driving(True)
            state.update_status("MANUAL DRIVE: FORWARD")
            if sender: sender.forward()
        elif cmd in ["STOP", "S"]:
            state.set_driving(False)
            state.update_status("MANUAL DRIVE: STOPPED")
            if sender: sender.stop()
        elif cmd in ["LEFT", "L"]:
            state.set_driving(True)
            state.update_status("MANUAL DRIVE: TURNING LEFT")
            if sender: sender.turn_left()
        elif cmd in ["RIGHT", "R"]:
            state.set_driving(True)
            state.update_status("MANUAL DRIVE: TURNING RIGHT")
            if sender: sender.turn_right()
        elif cmd in ["BACK", "BACKWARD", "B"]:
            state.set_driving(True)
            state.update_status("MANUAL DRIVE: REVERSING")
            if sender: sender.backward()
        elif cmd == "SCAN":
            state.update_status("MANUAL SOIL SCAN TRIGGERED")
            if sender: sender.request_scan()
        elif cmd.startswith("WATER_") or cmd.startswith("PUMP_"):
            clean = cmd.replace("WATER_", "").replace("PUMP_", "")
            parts = clean.split("_")
            zone = parts[0]  # L, R, or BOTH
            action = parts[1] if len(parts) > 1 else "ON"  # ON or OFF

            state.update_status(f"MANUAL PUMP {action}: ZONE {zone}")
            state.log_pump_event(zone, 3.0 if action == "ON" else 0.0, trigger="MANUAL_DASHBOARD", deficit_pct=15.0)

            if sender:
                if action == "ON":
                    sender.pump_on(zone)
                else:
                    sender.pump_off(zone)
        return jsonify({"status": "success", "command": cmd})

    @app.route("/api/clear_logs", methods=["POST"])
    def clear_logs():
        with state._lock:
            state.sensor_logs.clear()
            state.pump_logs.clear()
        return jsonify({"status": "success", "message": "All sensor and pump data logs cleared."})

    return app


def start_hardware_link(state, logger):
    """Initializes WiFi/USB connection and starts background telemetry drain loop."""
    from command_sender import CommandSender
    import command_receiver
    import irrigation
    from wifi_manager import WifiManager
    from serial_manager import SerialManager
    import threading

    ser = None
    if config.CONNECTION_MODE == "wifi":
        logger.info(f"Connecting to ESP32 bridge at {config.ESP32_BRIDGE_IP}:{config.ESP32_BRIDGE_PORT} ...")
        ser = WifiManager(config.ESP32_BRIDGE_IP, config.ESP32_BRIDGE_PORT, logger)
    elif config.CONNECTION_MODE == "usb":
        logger.info(f"Opening USB serial on {config.SERIAL_PORT} ...")
        ser = SerialManager(config.SERIAL_PORT, config.SERIAL_BAUD, logger)

    if not ser:
        return None

    sender = CommandSender(ser)

    def telemetry_loop():
        while True:
            try:
                state.update_wifi(ser.is_connected())
                line = ser.get_line(timeout=0.2)
                if line:
                    event, data = command_receiver.parse_line(line)
                    if event == "OBSTACLE":
                        state.update_obstacle(data.get("cm"))
                    elif event == "GPS":
                        state.update_gps(data)
                    elif event == "SCAN":
                        state.update_soil(irrigation.decide_pumps(data))
                    elif event == "STATUS":
                        logger.info(f"Arduino status: {data.get('text')}")
                        state.update_status(data.get("text", ""))
                    elif event == "DHT":
                        state.update_dht(data)
                    elif event == "ENCODER":
                        state.update_encoder(data.get("count", 0))
            except Exception as e:
                logger.error(f"Telemetry loop error: {e}")
            time.sleep(0.01)

    t = threading.Thread(target=telemetry_loop, daemon=True)
    t.start()
    return sender


if __name__ == "__main__":
    import argparse
    from logger import get_logger
    from state import SharedState

    parser = argparse.ArgumentParser(description="Run Farm Rover Web Dashboard")
    parser.add_argument("-port", "--port", "-p", type=int, default=config.DASHBOARD_PORT, help="Port to run Flask server on (e.g. 3000)")
    parser.add_argument("-host", "--host", type=str, default=config.DASHBOARD_HOST, help="Host address to bind Flask server to")
    args = parser.parse_args()

    logger = get_logger()
    state = SharedState()

    logger.info("Initializing ESP32/Arduino hardware telemetry link...")
    sender = start_hardware_link(state, logger)

    detector = DiseaseDetector()
    app = create_app(state, detector, sender=sender)
    logger.info(f" * Launching dashboard on http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False)

