import threading
import time
import requests
import logging

logger = logging.getLogger(__name__)

WEATHER_API_KEY = "b21af92dd0ef45ae86d53224251708"

class WeatherService:
    def __init__(self, state, location="10.7628,76.6548", poll_interval=60):
        self.state = state
        self.location = location
        self.poll_interval = poll_interval
        self._running = False
        self._thread = None
        self.last_weather = None

    def fetch_weather(self):
        try:
            # Use state GPS if available, else default location
            loc = self.location
            with self.state._lock:
                lat = self.state.gps.get("lat")
                lon = self.state.gps.get("lon")
                if lat and lon and lat != 0.0 and lon != 0.0:
                    loc = f"{lat},{lon}"

            url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={loc}&aqi=no"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                current = data.get("current", {})
                location_info = data.get("location", {})

                temp_c = current.get("temp_c", 28.2)
                humidity = current.get("humidity", 69)
                condition = current.get("condition", {}).get("text", "Clear")
                location_name = location_info.get("name", "Palakkad")

                with self.state._lock:
                    self.state.dht["temp_c"] = temp_c
                    self.state.dht["humidity"] = humidity
                    self.state.dht["connected"] = True
                    self.state.dht["status"] = "WEATHER_API"
                    self.state.dht["location_name"] = location_name
                    self.state.dht["condition"] = condition
                    self.state.dht["ts"] = time.time()

                self.last_weather = {
                    "temp_c": temp_c,
                    "humidity": humidity,
                    "condition": condition,
                    "location": location_name,
                    "ts": time.time()
                }
                logger.info(f"WeatherAPI updated: {temp_c}°C, {humidity}% RH ({location_name})")
                return self.last_weather
        except Exception as e:
            logger.error(f"WeatherAPI fetch error: {e}")
            return None

    def _loop(self):
        while self._running:
            self.fetch_weather()
            time.sleep(self.poll_interval)

    def start(self):
        if self._running:
            return
        self._running = True
        # Fetch initial reading immediately synchronously
        self.fetch_weather()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
