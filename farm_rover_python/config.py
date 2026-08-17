import os

"""Central config for the farm rover Python brain."""

# ---- Link to Arduino Mega ----
# "usb"  -> direct USB-serial cable, laptop to Mega (SERIAL_PORT/SERIAL_BAUD)
# "wifi" -> through the ESP32 bridge over WiFi (ESP32_BRIDGE_IP/_PORT)
#           see esp32_bridge.ino — it's a pure passthrough, no logic on it
CONNECTION_MODE = os.getenv("CONNECTION_MODE", "wifi")

# ---- USB serial (used when CONNECTION_MODE == "usb") ----
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyACM0")     # change to your Mega's port (Windows: "COM5")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", 9600))

# ---- ESP32 WiFi bridge (used when CONNECTION_MODE == "wifi") ----
ESP32_BRIDGE_IP = os.getenv("ESP32_BRIDGE_IP", os.getenv("ESP32_IP", "10.86.205.93"))   # printed by esp32_bridge on boot
ESP32_BRIDGE_PORT = int(os.getenv("ESP32_BRIDGE_PORT", 8888))

# ---- Camera stream: Android tablet acting as IP camera ----
# Use an app like "IP Webcam" (Android) — it exposes an MJPEG stream at
# http://<tablet-ip>:8080/video by default. Point this at that URL.
CAMERA_STREAM_URL = "http://192.168.1.60:8080/video"

# ---- Dashboard (hosted by Python itself, not the ESP32) ----
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")   # 0.0.0.0 = reachable from other devices on your LAN
DASHBOARD_PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", 5000)))
# Browse to http://<laptop-ip>:5000/ from your phone/tablet/any browser

# ---- Soil moisture calibration (must match Arduino) ----
AIR_VALUE = 600
WATER_VALUE = 280

# ---- Water level / proportional irrigation ----
# "water level" = current moisture% - MOISTURE_TARGET_PCT.
#   0 or positive -> soil has enough water, no action.
#   negative       -> soil is short by that many percentage points;
#                     the pump runs longer the bigger that deficit is,
#                     so it waters exactly what's needed instead of a
#                     fixed blast (avoids overwatering/flooding a side
#                     that's only slightly dry).
MOISTURE_TARGET_PCT = 65          # ideal soil moisture %
WATER_SEC_PER_DEFICIT_PCT = 0.3   # pump seconds per 1% short of target
MIN_PUMP_SEC = 2                  # floor — skip pointless micro-bursts
MAX_PUMP_SEC = 15                 # ceiling — hard safety cap, never exceeded

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
local_model = os.path.join(BASE_DIR, "model.pth")
plantdoc_model = os.path.abspath(os.path.join(BASE_DIR, "../PlantDoc/Model_assest/model.pth"))
MODEL_PATH = local_model if os.path.exists(local_model) else plantdoc_model
MODEL_TYPE = "pytorch"  # "pytorch" | "tflite" | "keras" | "savedmodel" | "onnx" | "auto"

MODEL_INPUT_SIZE = (224, 224)
CLASS_NAMES = [
    'Apple : Scab', 'Apple : Black Rot', 'Apple : Cedar rust', 'Apple : Healthy',
    'Blueberry : Healthy', 'Cherry : Powdery Mildew', 'Cherry : Healthy',
    'Corn : Cercospora Leaf Spot | Gray Leaf Spot', 'Corn : Common Rust',
    'Corn : Northern Leaf Blight', 'Corn : Healthy', 'Grape : Black Rot',
    'Grape : Esca | Black Measles', 'Grape : Leaf Blight | Isariopsis Leaf Spot',
    'Grape : Healthy', 'Orange : Haunglongbing | Citrus Greening',
    'Peach : Bacterial Spot', 'Peach : Healthy', 'Pepper bell : Bacterial Spot',
    'Pepper bell : Healthy', 'Potato : Early Blight', 'Potato : Late Blight',
    'Potato : Healthy', 'Raspberry : Healthy', 'Soybean : Healthy',
    'Squash : Powdery Mildew', 'Strawberry : Leaf Scorch', 'Strawberry : Healthy',
    'Tomato : Bacterial Spot', 'Tomato : Early Blight', 'Tomato : Late Blight',
    'Tomato : Leaf Mold', 'Tomato : Septoria Leaf Spot',
    'Tomato : Spider Mites | Two-Spotted Spider Mite', 'Tomato : Target Spot',
    'Tomato : Yellow Leaf Curl Virus', 'Tomato : Mosaic Virus', 'Tomato : Healthy'
]
CONFIDENCE_THRESHOLD = 0.50
INFERENCE_INTERVAL_SEC = 1.0   # run ML at most this often


# ---- Navigation ----
OBSTACLE_STOP_CM = 25

# ---- Climate / crop outlook (free Open-Meteo API, no key needed) ----
# Falls back to this location until the rover gets its first real GPS fix.
DEFAULT_LAT = 10.7628
DEFAULT_LON = 76.6548
CLIMATE_CHECK_INTERVAL_SEC = 1800   # re-fetch weather every 30 min
CLIMATE_FORECAST_DAYS = 7           # how many upcoming days to pull

# ---- Logging ----
LOG_DIR = "logs"
IMAGE_DIR = "images"

# ---- Hack Club Qwen-32B AI API (Replaces local Ollama) ----
HACKCLUB_AI_URL = "https://ai.hackclub.com/proxy/v1/chat/completions"
HACKCLUB_AI_KEY = os.getenv("HACKCLUB_AI_KEY", "")
HACKCLUB_AI_MODEL = "qwen/qwen3-32b"

