# Farm Rover — Python Brain

Camera comes from an **Android tablet** running an IP-camera app (e.g.
"IP Webcam"), not an ESP32-CAM. The **dashboard is hosted by this Python
code itself** (Flask) — it embeds the tablet's live stream, shows live
telemetry from the Arduino Mega, and lets you upload a photo straight
from the browser to run through the same disease model.

The **ESP32 is used as a pure WiFi↔UART bridge** between this Python
code and the Arduino Mega (see `esp32_bridge.ino`) — it has no decision
logic on it, it just relays lines back and forth so you don't need a USB
cable running to a moving rover. A direct-USB mode is still available
(`config.CONNECTION_MODE = "usb"`) if you ever want to skip the ESP32.

```
Tablet camera (browser hits it directly)

Mega  <--UART-->  ESP32 bridge  <--WiFi(TCP)-->  Python (this code)  -->  Flask dashboard (port 5000)
```

---

## 1. What each file does

### `config.py`
Every tunable value lives here so you never have to hunt through logic
code to change a number.

| Setting | What it controls |
|---|---|
| `CONNECTION_MODE` | `"wifi"` (through the ESP32 bridge) or `"usb"` (direct cable to the Mega). Picks which link `main.py` opens — see `wifi_manager.py`/`serial_manager.py`. |
| `ESP32_BRIDGE_IP` / `ESP32_BRIDGE_PORT` | used when `CONNECTION_MODE == "wifi"` — the IP `esp32_bridge.ino` prints on boot, and its TCP port (default `8888`). |
| `SERIAL_PORT` / `SERIAL_BAUD` | used when `CONNECTION_MODE == "usb"` — which port the Mega is on (e.g. `COM5` on Windows, `/dev/ttyACM0` on Linux, `/dev/tty.usbmodemXXXX` on Mac), and its baud rate. |
| `CAMERA_STREAM_URL` | the MJPEG URL your Android tablet's IP-camera app serves (e.g. `http://<tablet-ip>:8080/video` for the "IP Webcam" app). The dashboard's `<img>` tag points straight at this; OpenCV also reads frames from it for ML. |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | where Python's own dashboard listens. `0.0.0.0` makes it reachable from other devices on your WiFi at `http://<laptop-ip>:5000/`. |
| `AIR_VALUE` / `WATER_VALUE` | soil sensor calibration — **must match the numbers burned into the Arduino sketch**, or the moisture percentages will be wrong. |
| `MOISTURE_TARGET_PCT` | the ideal soil moisture %. Water level = current% − this. Negative means the soil is short by that many points. |
| `WATER_SEC_PER_DEFICIT_PCT` | how many pump-seconds to run per 1% of deficit — this is what makes watering proportional instead of a fixed blast. |
| `MIN_PUMP_SEC` / `MAX_PUMP_SEC` | safety floor/ceiling on any single pump run, so it never skips a tiny deficit or overwaters/floods a side. |
| `MODEL_PATH` / `MODEL_TYPE` | where your already-trained plant-disease model lives, and its format. `"auto"` picks the loader from the file extension (`.tflite`/`.h5`/`.keras`/`.onnx`/a folder) — see `ml_model.py`. |
| `CLASS_NAMES` | the label list your model outputs, in the same order as its output layer. |
| `CONFIDENCE_THRESHOLD` | a prediction below this confidence is ignored (treated as "not sure", robot keeps driving). |
| `DEFAULT_LAT` / `DEFAULT_LON` | fallback location for the weather/crop-outlook lookup until the rover has a real GPS fix — set to your farm's coordinates. |
| `CLIMATE_CHECK_INTERVAL_SEC` / `CLIMATE_FORECAST_DAYS` | how often the crop-climate outlook refreshes, and how many upcoming days it looks at. |
| `INFERENCE_INTERVAL_SEC` | minimum time between ML runs, so you don't run inference on every single frame and choke the CPU. |
| `OBSTACLE_STOP_CM` | ultrasonic distance below which the rover stops and turns. |
| `LOG_DIR` / `IMAGE_DIR` | where logs and saved disease-photos are written. |

### `serial_manager.py` / `wifi_manager.py`
Two interchangeable ways to reach the Mega — `main.py` opens whichever
one `config.CONNECTION_MODE` says, via the `open_link()` factory, and
nothing else in the codebase needs to know which one it got. Both expose
the exact same interface:

- `.send(cmd)` — writes one line to the Mega.
- `.get_line(timeout)` — pulls the next received line off a queue, or
  `None` if nothing arrived within `timeout` seconds.
- `.close()` — stops the background thread and closes the connection.

**`serial_manager.py` (`CONNECTION_MODE = "usb"`)** — opens the USB
serial port directly, waits 2s for the Mega to reset after the port
opens, then runs a background thread continuously reading lines into a
queue so Python is never blocked waiting on the Mega.

**`wifi_manager.py` (`CONNECTION_MODE = "wifi"`, the default)** — opens
a plain TCP socket to the ESP32 bridge (`esp32_bridge.ino`), which
relays every line to/from the Mega's UART. Same background-thread/queue
design, plus auto-reconnect: if the WiFi link drops (rover moves out of
range, ESP32 reboots, etc.) it keeps retrying in the background instead
of crashing the mission loop.

### `command_sender.py`
Turns intentions into the exact text commands the Mega expects. This is
the **only place command strings are written** — if you ever change the
Mega's command format, you only edit here.

| Method | Sends | Meaning |
|---|---|---|
| `forward()` | `F` | drive forward |
| `backward()` | `B` | drive backward |
| `turn_left()` | `L` | turn left |
| `turn_right()` | `R` | turn right |
| `stop()` | `S` | stop motors |
| `pump_on(side)` / `pump_off(side)` | `PUMP,<side>,ON/OFF` | `side` is `"L"`, `"R"`, or `"BOTH"` |
| `request_scan()` | `SCAN` | on-demand soil moisture check — this is the ONLY thing it does: servo sweep, sensor read, buzz, reply. No driving, no pumps. |
| `servo_home()` | `HOME` | park the pan/tilt servo |
| `servo_pan(angle)` | `PAN,<angle>` | move the pan servo to a specific angle |

### `command_receiver.py`
The mirror image of `command_sender.py` — turns raw lines **from** the
Mega into structured Python dicts. One function, `parse_line(line)`,
returns `(event_type, data)`:

| Incoming line | event_type | data dict |
|---|---|---|
| `SCAN,L,410,C,395,R,602` | `"SCAN"` | `{"L":410,"C":395,"R":602}` (raw ADC values) |
| `GPS,10.762345,76.654321,0.8,10,09:35:22` | `"GPS"` | `{"lat":..,"lon":..,"speed_kmh":..,"sats":..,"time":..}` |
| `OBSTACLE,25` | `"OBSTACLE"` | `{"cm":25}` |
| `ENCODER,1234` | `"ENCODER"` | `{"count":1234}` |
| `STATUS,READY` | `"STATUS"` | `{"text":"READY"}` |

If the line doesn't match anything known, it returns `(None, None)` so the
caller can safely ignore it instead of crashing.

### `navigation.py`
Obstacle-avoidance decision. `handle_obstacle(sender, obstacle_cm, logger)`
checks the latest ultrasonic reading against `OBSTACLE_STOP_CM`; if too
close, it tells the Mega to stop and turn, and returns `True` so the main
loop knows driving was interrupted. `resume_patrol(sender)` just sends
`forward()` again once the path is clear.

### `irrigation.py`
Doesn't just check "is there water or not" — it converts the raw
capacitive sensor reading into an actual **moisture %**, then into a
**water level** relative to a target (`water_level = current% −
MOISTURE_TARGET_PCT`). Zero or positive means the soil has enough;
negative means it's short by that many percentage points — and the pump
runs only long enough to cover exactly that deficit, so a side that's
barely dry gets a light watering and a very dry side gets more, without
ever exceeding `MAX_PUMP_SEC`.

- `raw_to_pct(raw)` — raw ADC value (0–1023) → 0–100% moisture, using the
  same `AIR_VALUE`/`WATER_VALUE` calibration as the Arduino.
- `water_level(pct)` — `pct - MOISTURE_TARGET_PCT`, signed. Negative =
  needs water; the magnitude is the deficit.
- `pump_duration_for_deficit(deficit_pct)` — turns a deficit into a pump
  runtime: `deficit * WATER_SEC_PER_DEFICIT_PCT`, clamped between
  `MIN_PUMP_SEC` and `MAX_PUMP_SEC`. Returns `0` if there's no deficit.
- `decide_pumps(scan_data)` — runs the above for L, C, and R and returns
  `{"L": {"pct":.., "water_level":.., "duration_sec":..}, "C": {...}, "R": {...}}`.
  Center has no pump, so its `duration_sec` is always `None` — it's
  included only so the dashboard can show all three readings.
- `run_irrigation_cycle(sender, scan_data, logger)` — the actual action:
  logs each side's %/water level, then waters **L and R independently**,
  each for its own computed duration (not a shared fixed blast), skipping
  a side entirely if its `duration_sec` is `0`.

### `gps.py`
Keeps track of the rover's last known GPS fix and writes every update to
`logs/gps_log.csv` (timestamp, lat, lon, speed, satellite count, GPS time,
and an optional event tag). `save_event(tag)` re-logs the *current* fix
with a tag like `"Early_Blight"` so you get a location stamp exactly when
something interesting happened (e.g. disease found), without needing a
fresh GPS read at that instant.

### `ml_model.py`
Thin wrapper around a TFLite interpreter.
- Loads `model.tflite` and reads its expected input size directly from
  the model file (so you don't have to hardcode 224×224 — it adapts to
  whatever your model actually wants).
- `preprocess(frame_bgr)` — resizes the OpenCV (BGR) frame, converts to
  RGB, normalizes pixel values to 0–1, and adds the batch dimension the
  model expects.
- `predict(frame_bgr)` — runs one inference and returns `(label,
  confidence)` using `CLASS_NAMES` from `config.py` to translate the
  output index into a readable label.

### `disease_detector.py`
Sits on top of `ml_model.py` and adds the accept/ignore rule from your
diagram: a prediction is only trusted if `confidence >= CONFIDENCE_THRESHOLD`
(default 90%). `.check(frame)` returns `(label, confidence, accepted)`.
`.is_healthy(label)` is just a readability helper for `label == "Healthy"`.

### `logger.py`
One shared logger used by every module (`get_logger()`). Writes to both
the console (INFO and above) and `logs/rover.log` (DEBUG and above, so
you get full detail on disk even if the terminal only shows a summary).
Safe to call from multiple files — it only configures itself once.

### `climate.py`
Free weather → crop-outlook module. Calls the **Open-Meteo** API
(`https://open-meteo.com`, no key/signup needed) for yesterday + the next
`CLIMATE_FORECAST_DAYS` days at the rover's GPS location (falls back to
`config.DEFAULT_LAT`/`DEFAULT_LON` until the first GPS fix arrives), pulls
daily max/min temp, rainfall, and humidity, and runs simple threshold
rules against them — heat stress, cold stress, drought, excess rain/fungal
risk — combined with the rover's own DHT11 reading for a local sanity
check. Returns a dict with an overall `verdict` ("Favorable"/"At risk"),
a list of plain-language `flags`, the averaged numbers, and the raw
per-day breakdown.

**This is a rule-based heuristic, not a trained ML model** — there's no
labeled "what actually happened to the crop" dataset available to train
one on. The thresholds (38°C heat, 10°C cold, 100mm rain, etc.) are
generic starting points for general field/vegetable crops — tune them in
`_score_crop_risk()` for your specific crop's tolerances. If you later
get real yield/health outcome data, this is the one function to swap for
a trained model — `main.py` and the dashboard don't need to change.

### `state.py`
A small thread-safe box (`SharedState`) holding the latest telemetry:
soil %, GPS fix, obstacle distance, encoder count, status text, DHT11
temp/humidity, the latest crop-climate outlook, whether the rover is
currently driving, and the last disease event. `main.py` (the
mission-loop thread) writes to it as data comes in; `dashboard.py` (the
Flask thread) and `climate_loop` (the weather thread) read/write it too.
A single lock protects all three threads.

### `dashboard.py`
The live web dashboard, hosted by Python itself (Flask) — this replaces
what would have been an ESP32-CAM's job. `create_app(state, detector)`
returns a Flask app with:

| Route | Purpose |
|---|---|
| `GET /` | the dashboard page — embeds the tablet's live stream directly (`<img src="CAMERA_STREAM_URL">`), plus a telemetry grid, a DHT11 reading, a crop-climate-outlook card, an upload box, and a photo gallery. |
| `GET /telemetry` | JSON snapshot of `state` — polled by the page every second. |
| `GET /gallery` | JSON list of saved photo filenames (from `images/`, newest-ish first). |
| `GET /images/<file>` | serves a saved/uploaded photo so the browser can display it. |
| `POST /upload` | accepts a photo (`multipart/form-data`, field name `photo`), saves it under `images/uploads/`, and — if a `DiseaseDetector` was passed in — runs it through the same model `main.py` uses, returning `{label, confidence, accepted}`. |

Video itself is **not proxied through Python** — the browser talks to the
tablet's stream URL directly, so Python only has to carry telemetry and
uploaded photos, not video frames.

You can also run it standalone for testing without the Mega/tablet
connected: `python dashboard.py` (opens on `DASHBOARD_PORT` with an empty
`SharedState`).

### `main.py`
The actual event loop tying everything above together, matching your
"Event Loop (High-Level)" diagram exactly:

1. **Init** — open serial to the Mega, load the ML model, create the
   shared telemetry state, start the dashboard in a background thread,
   open the tablet's camera stream, start driving forward.
2. **Every loop iteration:**
   - Drain *every* line currently waiting from the Mega (non-blocking),
     react immediately, and mirror the data into `state` so the dashboard
     stays live: `OBSTACLE` → avoid + update state, `GPS` → log + update
     state, `SCAN` → store for irrigation + update state, `STATUS` → log
     + update state, `ENCODER` → update state (placeholder for future
     odometry/farm-mapping).
   - If enough time has passed (`INFERENCE_INTERVAL_SEC`), grab a fresh
     camera frame and run disease detection.
     - **Healthy & accepted** → if the rover had stopped, resume driving.
     - **Diseased & accepted** → stop, save a GPS-tagged log entry, save
       the photo to `images/`, request a soil scan, wait (up to 3s) for
       the Mega's `SCAN` reply, run the irrigation decision if it needs
       water, then resume driving.
     - **Low confidence** → prediction is ignored entirely, robot keeps
       going.
3. **Ctrl+C** — cleanly stops the motors, closes the serial port, and
   releases the camera.

Python never touches a motor or relay pin directly — every action in
`main.py` goes through `command_sender.py`, which is the only file that
knows the Mega's command syntax.

---

## 2. Setup

```bash
pip install -r requirements.txt --break-system-packages
```

1. Edit `config.py`:
   - `CONNECTION_MODE` → `"wifi"` (default, through the ESP32 bridge) or
     `"usb"` (direct cable to the Mega).
   - If `"wifi"`: flash `esp32_bridge.ino` to your ESP32, put your WiFi
     credentials in it, and set `ESP32_BRIDGE_IP` to the IP it prints on
     boot.
   - If `"usb"`: set `SERIAL_PORT` to your Mega's actual port.
   - `CAMERA_STREAM_URL` → your Android tablet's IP-camera stream (open
     the IP Webcam app, it shows the URL on screen — usually
     `http://<tablet-ip>:8080/video`). Make sure the laptop and tablet
     are on the same WiFi network.
   - `DASHBOARD_PORT` → change if 5000 is taken by something else.
   - `AIR_VALUE` / `WATER_VALUE` → must match the Arduino sketch's
     calibration constants exactly.
2. Point it at your **already-trained** model: set `MODEL_PATH` in
   `config.py` to your model file (or folder, for a SavedModel), and leave
   `MODEL_TYPE = "auto"` unless you want to force it. Make sure
   `CLASS_NAMES` lists your classes in the exact order your model was
   trained with.
3. Set `DEFAULT_LAT`/`DEFAULT_LON` to your farm's coordinates (used for
   weather lookups before the first GPS fix comes in).
4. Run:
   ```bash
   python main.py
   ```
5. Open `http://<laptop-ip>:5000/` from any browser on the same WiFi
   (phone, tablet, another laptop) to see the live dashboard — video,
   telemetry, DHT11 reading, crop-climate outlook, and the photo
   upload/check box.

Logs land in `logs/rover.log` and `logs/gps_log.csv`. Disease photos land
in `images/`.

---

## 3. Full command/event reference

**Python → Arduino**

| Command | Meaning |
|---|---|
| `F` / `B` / `L` / `R` / `S` | drive forward / back / turn left / turn right / stop |
| `PUMP,L,ON` / `PUMP,L,OFF` | left pump |
| `PUMP,R,ON` / `PUMP,R,OFF` | right pump |
| `PUMP,BOTH,ON` / `PUMP,BOTH,OFF` | both pumps |
| `SCAN` | on-demand soil moisture check ONLY — no side effects on driving/pumps |
| `HOME` | park the pan/tilt servo |
| `PAN,<angle>` | move pan servo to a specific angle |

**Arduino → Python**

| Line | Meaning |
|---|---|
| `SCAN,L,<raw>,C,<raw>,R,<raw>` | soil scan result (raw ADC, 0–1023) |
| `GPS,<lat>,<lon>,<speed_kmh>,<sat>,<hh:mm:ss>` | current GPS fix |
| `DHT,<tempC>,<humidity>` | DHT11 temperature/humidity reading |
| `OBSTACLE,<cm>` | ultrasonic distance reading |
| `ENCODER,<count>` | wheel encoder count |
| `STATUS,<text>` | free-form status message |
