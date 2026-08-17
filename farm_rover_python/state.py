"""Thread-safe shared telemetry snapshot.

main.py (the mission loop) writes to this as data arrives from the Mega.
dashboard.py (the Flask app, running in its own thread) reads from it to
answer /telemetry requests. A single lock keeps the two threads from
tearing each other's reads/writes.
"""
import threading
import time

class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self.soil = {
            "L": {"pct": None, "water_level": None, "duration_sec": None},
            "C": {"pct": None, "water_level": None, "duration_sec": None},
            "R": {"pct": None, "water_level": None, "duration_sec": None},
        }
        self.gps = {"lat": 0.0, "lon": 0.0, "speed_kmh": 0.0, "sats": 0, "time": "--:--:--"}
        self.obstacle_cm = -1
        self.encoder = 0
        self.status = "BOOT"
        self.driving = False
        self.last_disease = None       # {"label":..,"confidence":..,"ts":..}
        self.last_disease_diagnostic = None  # full diagnostic dictionary
        self.dht = {"temp_c": None, "humidity": None, "connected": False, "status": "DISCONNECTED", "ts": 0}
        import config
        self.wifi = {
            "connected": False,
            "mode": getattr(config, "CONNECTION_MODE", "wifi"),
            "ip": getattr(config, "ESP32_BRIDGE_IP", "192.168.31.18"),
            "port": getattr(config, "ESP32_BRIDGE_PORT", 8888),
            "status": "DISCONNECTED"
        }
        self.climate_sim = {"enabled": False, "temp_c": 28.5, "humidity": 75.0}
        self.climate_outlook = None    # set by climate.py, see get_crop_outlook()
        self.sensor_logs = []          # recorded telemetry snapshots
        self.pump_logs = []            # recorded irrigation pump events
        self._last_update = time.time()

        # Seed initial sample log
        self._add_initial_logs()

    def _add_initial_logs(self):
        import time
        now = time.time()
        t_str = time.strftime("%H:%M:%S", time.localtime(now))
        self.sensor_logs.append({
            "ts": now, "time_str": t_str,
            "temp": 28.5, "humidity": 75.0,
            "soil_L": 68, "soil_C": 62, "soil_R": 54,
            "gps": "10.762800, 76.654800", "obstacle": 120, "status": "BOOT OK"
        })
        self.pump_logs.append({
            "ts": now - 300, "time_str": time.strftime("%H:%M:%S", time.localtime(now - 300)),
            "side": "L", "duration_sec": 3.4, "deficit_pct": 17.0,
            "trigger": "AUTOMATIC_SOIL_DEFICIT", "status": "COMPLETED"
        })

    def log_sensor_snapshot(self):
        with self._lock:
            now = time.time()
            t_str = time.strftime("%H:%M:%S", time.localtime(now))
            dht = self.climate_sim.get("temp_c") if self.climate_sim.get("enabled") else self.dht.get("temp_c")
            hum = self.climate_sim.get("humidity") if self.climate_sim.get("enabled") else self.dht.get("humidity")
            entry = {
                "ts": now, "time_str": t_str,
                "temp": dht, "humidity": hum,
                "soil_L": self.soil.get("L", {}).get("pct"),
                "soil_C": self.soil.get("C", {}).get("pct"),
                "soil_R": self.soil.get("R", {}).get("pct"),
                "gps": f"{self.gps.get('lat', 0.0):.6f}, {self.gps.get('lon', 0.0):.6f}",
                "obstacle": self.obstacle_cm,
                "status": self.status
            }
            self.sensor_logs.insert(0, entry)
            if len(self.sensor_logs) > 100:
                self.sensor_logs = self.sensor_logs[:100]

    def log_pump_event(self, side: str, duration_sec: float, trigger: str = "AUTOMATIC_SOIL_DEFICIT", deficit_pct: float = 0.0):
        with self._lock:
            now = time.time()
            t_str = time.strftime("%H:%M:%S", time.localtime(now))
            entry = {
                "ts": now, "time_str": t_str,
                "side": side, "duration_sec": round(duration_sec, 1),
                "deficit_pct": round(deficit_pct, 1),
                "trigger": trigger, "status": "COMPLETED"
            }
            self.pump_logs.insert(0, entry)
            if len(self.pump_logs) > 100:
                self.pump_logs = self.pump_logs[:100]

    def update_soil(self, data):
        with self._lock:
            self.soil = data
            self._last_update = time.time()
            self.log_sensor_snapshot()

    def update_gps(self, data):
        with self._lock:
            self.gps = data
            self._last_update = time.time()

    def update_obstacle(self, cm):
        with self._lock:
            self.obstacle_cm = cm
            self._last_update = time.time()

    def update_encoder(self, count):
        with self._lock:
            self.encoder = count
            self._last_update = time.time()

    def update_status(self, text):
        with self._lock:
            self.status = text
            self._last_update = time.time()

    def update_dht(self, data):
        with self._lock:
            data["ts"] = time.time()
            if "connected" not in data:
                data["connected"] = (data.get("temp_c") is not None and data.get("humidity") is not None)
            if "status" not in data:
                data["status"] = "CONNECTED" if data["connected"] else "DISCONNECTED"
            self.dht = data
            self._last_update = time.time()

    def update_wifi(self, connected: bool, status_msg: str = None):
        with self._lock:
            self.wifi["connected"] = connected
            self.wifi["status"] = status_msg if status_msg else ("CONNECTED" if connected else "DISCONNECTED")
            self._last_update = time.time()

    def update_climate(self, outlook):
        with self._lock:
            self.climate_outlook = outlook

    def set_driving(self, driving: bool):
        with self._lock:
            self.driving = driving

    def set_disease(self, label, confidence):
        with self._lock:
            self.last_disease = {"label": label, "confidence": confidence, "ts": time.time()}

    def set_disease_diagnostic(self, diagnostic):
        with self._lock:
            diagnostic["ts"] = time.time()
            self.last_disease_diagnostic = diagnostic
            self.last_disease = {"label": diagnostic.get("label"), "confidence": diagnostic.get("confidence_ratio"), "ts": time.time()}

    def set_climate_sim(self, temp, humidity, enabled=True):
        with self._lock:
            self.climate_sim = {"enabled": enabled, "temp_c": temp, "humidity": humidity}

    def snapshot(self):
        with self._lock:
            dht_snap = dict(self.dht)
            # If climate sim enabled, present simulated values as connected
            if self.climate_sim.get("enabled"):
                dht_snap["temp_c"] = self.climate_sim.get("temp_c", 28.5)
                dht_snap["humidity"] = self.climate_sim.get("humidity", 75.0)
                dht_snap["connected"] = True
                dht_snap["status"] = "SIMULATED"
            else:
                # If no telemetry arrived or ts is 0, mark DHT as disconnected
                if dht_snap.get("ts", 0) == 0 or (time.time() - dht_snap.get("ts", 0) > 15.0):
                    dht_snap["connected"] = False
                    dht_snap["status"] = "DISCONNECTED"

            return {
                "soil": dict(self.soil),
                "gps": dict(self.gps),
                "obstacle_cm": self.obstacle_cm,
                "encoder": self.encoder,
                "status": self.status,
                "driving": self.driving,
                "last_disease": self.last_disease,
                "last_disease_diagnostic": self.last_disease_diagnostic,
                "dht": dht_snap,
                "wifi": dict(self.wifi),
                "climate_sim": dict(self.climate_sim),
                "climate_outlook": self.climate_outlook,
                "sensor_logs": list(self.sensor_logs),
                "pump_logs": list(self.pump_logs),
                "age_ms": int((time.time() - self._last_update) * 1000),
            }

