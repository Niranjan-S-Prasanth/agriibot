# Farm Rover — Full System README

## Correction from earlier: the ESP32 IS in the loop

Earlier I said your ESP32 wasn't part of the control path — that was
wrong for your setup. **The ESP32 is now the WiFi↔UART bridge between
Python and the Arduino Mega**, so Python doesn't need a USB cable
running to a moving rover. It has no decision logic on it — pumps,
irrigation, navigation are all still decided in Python — it just relays
lines back and forth. See `esp32_bridge.ino`.

`main.c` and `esp32_pump_controller.ino` (the earlier ESP-IDF/Arduino
pump-decision sketches) are **still not used** — those made pump
decisions on the ESP32 itself, which conflicts with Python owning that
logic now. `esp32_bridge.ino` is the one that's actually active. Still
kept `main.c`/`esp32_pump_controller.ino` around in case you want that
older design back someday.

---

## Architecture

```
                     USER
                      │
          Live Camera / Dashboard  (browser, served by Python itself)
                      │                    ▲
                      ▼                    │ camera stream (direct)
              PYTHON (Laptop)      Android Tablet (IP camera app)
       =========================
       • Plant Disease ML (your existing model — see farm_rover_python/README.md)
       • Navigation AI
       • Irrigation decision engine (water-level based, proportional)
       • Crop-climate outlook (Open-Meteo + DHT11)
       • GPS Logging
       • Hosts the web dashboard (Flask)
       =========================
             │
             │ Commands (F/B/L/R/S, PUMP,x, SCAN)  ▲ sensor lines
             │            over WiFi (TCP)          │
             ▼                                     │
                    ESP32 bridge (pure passthrough, no logic)
                              │  UART
                              ▼
                    Arduino Mega
                          │
                          ▼
        Motors, Pumps, Soil Servo, Soil Sensor,
        DHT11, Buzzer, GPS, GSM, Ultrasonic, Encoders
```

A direct-USB mode (skipping the ESP32 entirely) is still available —
set `config.CONNECTION_MODE = "usb"` in the Python project if you ever
want that instead.

## Who does what

- **Python (laptop)** — the only device that "thinks." Runs your ML
  model, decides irrigation/navigation, sends short text commands over
  WiFi through the ESP32 bridge, and hosts the live dashboard itself
  (Flask). Never touches hardware directly. Full detail:
  `farm_rover_python/README.md`.

- **ESP32** — a pure WiFi↔UART bridge (`esp32_bridge.ino`). Accepts one
  TCP connection from Python and relays every line to/from the Mega's
  UART, byte for byte. No parsing, no pump logic, no decisions — just
  the wire, minus the cable.

- **Arduino Mega** — executes commands and reports sensors only. Drives
  motors, fires pump relays (for exactly the duration Python tells it
  to), sweeps the soil-scan servo, reads the capacitive soil sensor,
  DHT11, GPS, ultrasonic, and encoders, and buzzes locally after every
  soil check. No decisions are made here either.

- **Android tablet** — the camera. Runs an IP-camera app (e.g. "IP
  Webcam") serving an MJPEG stream on your WiFi. Both the dashboard's
  `<img>` tag and Python's OpenCV capture point at that URL directly —
  video does not go through the ESP32 bridge.

---

## Everything that's been built, end to end

### 1. Soil moisture — not just present/absent, an actual water level
The capacitive sensor's raw reading is converted to a 0–100% moisture
value, then to a signed **water level** (`current% − target%`).
Negative means the soil is short by that many points; the pump only runs
long enough to cover exactly that deficit (clamped to a safe min/max), so
watering scales with how dry the soil actually is instead of a fixed
on/off blast. Lives in `farm_rover_python/irrigation.py`.

### 2. On-demand soil check
Python can send `SCAN` at any time; the Mega does **only** the soil
check (servo sweep → sensor read → buzz → reply) — no side effects on
driving or pumps. (Also still runs automatically every `SCAN_INTERVAL`
on the Mega.)

### 3. DHT11 temperature/humidity
Wired to Mega pin A1, read every 10s, sent as `DHT,<tempC>,<humidity>`.
Shown on the dashboard and fed into the crop-climate outlook as a local
sanity check against the forecast.

### 4. Buzzer feedback
A mini buzzer on Mega pin D8 beeps automatically right after every soil
scan — no command needed. Good soil = 2 short beeps. Dry soil = 1 long
warning beep.

### 5. Crop-climate outlook
`farm_rover_python/climate.py` pulls yesterday + a 7-day forecast from
**Open-Meteo** (free, no API key) at the rover's GPS location, combines
it with the DHT11 reading, and flags risks (heat stress, cold stress,
drought, excess rain/fungal risk) with a "Favorable"/"At risk" verdict.
This is a **rule-based heuristic**, not a trained model — there's no
labeled outcome data to train one on yet; swap it in later if you get
that data.

### 6. Your existing ML model, plugged in
`farm_rover_python/ml_model.py` is a pluggable loader — point
`config.MODEL_PATH` at your already-trained model (`.tflite`, `.h5`/
`.keras`, a SavedModel folder, or `.onnx`) and leave `MODEL_TYPE =
"auto"`; it detects the format and exposes the same `predict()` either
way. Nothing else in the pipeline needed to change.

### 7. WiFi bridge instead of a USB cable
`esp32_bridge.ino` + `wifi_manager.py` — Python opens a plain TCP socket
to the ESP32, which relays everything to/from the Mega's UART. Auto-
reconnects if the link drops. `serial_manager.py` (direct USB) is still
there as a fallback via `config.CONNECTION_MODE = "usb"`.

### 8. Live dashboard, hosted by Python
`farm_rover_python/dashboard.py` (Flask, port 5000) embeds the tablet's
live video, shows soil water levels, GPS, obstacle distance, encoder
count, DHT11 reading, the crop outlook card, and has a **photo upload
box** that runs any photo you upload through the same disease model and
shows the result, plus a gallery of saved/uploaded photos.

---

## Files in this delivery

| File | Runs on | Status |
|---|---|---|
| `arduino_soil_scanner.ino` | Arduino Mega | **active** — soil scan (on-demand + periodic), proportional pump relays, GPS, DHT11, buzzer |
| `esp32_bridge.ino` | ESP32 | **active** — WiFi↔UART passthrough bridge to the Mega |
| `farm_rover_python.zip` | Laptop | **active** — full decision engine + web dashboard, see its own README inside |
| `esp32_pump_controller.ino` | ESP32 (Arduino framework) | not used — made pump decisions on-device, superseded by Python + the bridge |
| `main.c` | ESP32 (ESP-IDF) | not used — same reason as above |
| `esp32cam_dashboard.ino` | ESP32-CAM | superseded — dashboard is hosted by Python now, camera is the tablet |
| `signals.md` | reference | original ESP32-decides-pumps protocol table, kept for history |

## Wiring summary

- **Mega ↔ ESP32:** UART2 — Mega TX2 (pin 16) → ESP32 GPIO16 (RX2), Mega
  RX2 (pin 17) ← ESP32 GPIO17 (TX2), common GND.
- **ESP32 ↔ Laptop:** WiFi, plain TCP on port `8888` — no physical
  wiring.
- **Tablet ↔ Laptop/browser:** same WiFi network — no physical wiring,
  just the IP-camera stream URL.
- **Mega pins:** soil sensor A0, DHT11 A1, buzzer D8, pump relays D5/D6,
  pan/tilt servos D9/D10, GPS on Serial1 (pins 18/19).

## Full command/event reference

**Python → Mega (relayed through the ESP32 bridge)**

| Command | Meaning |
|---|---|
| `F` / `B` / `L` / `R` / `S` | drive forward / back / turn left / turn right / stop |
| `PUMP,L,ON` / `OFF` | left pump |
| `PUMP,R,ON` / `OFF` | right pump |
| `PUMP,BOTH,ON` / `OFF` | both pumps |
| `SCAN` | on-demand soil moisture check ONLY — no driving/pump side effects |
| `HOME` | park pan/tilt servo |
| `PAN,<angle>` | move pan servo to a specific angle |

**Mega → Python (relayed through the bridge, also mirrored to the dashboard)**

| Line | Meaning |
|---|---|
| `SCAN,L,<raw>,C,<raw>,R,<raw>` | soil scan result (raw ADC 0–1023) |
| `GPS,<lat>,<lon>,<speed_kmh>,<sat>,<hh:mm:ss>` | current GPS fix |
| `DHT,<tempC>,<humidity>` | DHT11 reading |
| `OBSTACLE,<cm>` | ultrasonic distance |
| `ENCODER,<count>` | wheel encoder count |
| `STATUS,<text>` | free-form status message |

## What's not built yet

`F`/`B`/`L`/`R`/`S` driving, `OBSTACLE`/`ENCODER`/`STATUS` reporting, and
`HOME`/`PAN,<angle>` are all in Python's/the dashboard's expected
protocol but not yet implemented in the Mega sketch (only soil scan,
pumps, GPS, DHT11, and the buzzer are wired up so far). Say the word and
I'll bring the Mega sketch up to match.
