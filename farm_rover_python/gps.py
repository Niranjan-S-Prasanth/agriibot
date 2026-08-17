"""Tracks and logs the rover's latest GPS fix."""
import csv
import os
import time
import config

class GpsTracker:
    def __init__(self):
        self.last_fix = None
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self.csv_path = os.path.join(config.LOG_DIR, "gps_log.csv")
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["ts", "lat", "lon", "speed_kmh", "sats", "gps_time", "tag"]
                )

    def update(self, gps_data: dict, tag: str = ""):
        self.last_fix = gps_data
        with open(self.csv_path, "a", newline="") as f:
            csv.writer(f).writerow([
                time.time(), gps_data["lat"], gps_data["lon"],
                gps_data["speed_kmh"], gps_data["sats"], gps_data["time"], tag
            ])

    def save_event(self, tag: str):
        """Log the current fix tagged with an event, e.g. 'disease_found'."""
        if self.last_fix:
            self.update(self.last_fix, tag=tag)
