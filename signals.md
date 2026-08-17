# Signal Protocol — Soil Moisture Scanner ↔ Pump Controller

> **This file describes the original ESP32-only design.** In the current
> architecture, decisions (including the water-level/proportional pump
> timing) live in Python — see `irrigation.py` and the full protocol
> table in `farm_rover_python/README.md`. Kept here for historical
> reference.

Line-based ASCII over UART, each command ends with `\n`. Baud: 9600.

Link (Arduino Mega hardware Serial2 recommended):
- Arduino Serial2 TX (pin 16) → ESP32 GPIO16 (RX2)
- Arduino Serial2 RX (pin 17) ← ESP32 GPIO17 (TX2)
- Common GND required

GPS module (NEO-6M) wired separately to Arduino Serial1 (pins 18/19) — it does not talk to the ESP32 directly, only relayed through Arduino.

---

## 1. Arduino → ESP32

### `SCAN,L,<raw>,C,<raw>,R,<raw>`
Sent once per completed pan/tilt scan cycle (Center → Right → Left).

| Field | Meaning |
|---|---|
| `L` | raw analogRead (0–1023) at pan=45° (Left) |
| `C` | raw analogRead at pan=90° (Center) |
| `R` | raw analogRead at pan=135° (Right) |

**Use:** tells ESP32 the current soil moisture at all 3 scanned positions so it can decide which pump(s) to fire. ESP32 converts raw → % using the same `AIR_VALUE`/`WATER_VALUE` calibration as the Arduino.

**Example:** `SCAN,L,410,C,395,R,602`

### `GPS,<lat>,<lon>,<speed_kmh>,<sat>,<hh:mm:ss>`
Sent every `GPS_SEND_INTERVAL` (default 5s) — but only if the rover has actually moved past `GPS_MOVE_THRESHOLD_M` (default 1m) since the last send, per the compare-position logic.

| Field | Meaning |
|---|---|
| `lat` | latitude, decimal degrees, 6dp |
| `lon` | longitude, decimal degrees, 6dp |
| `speed_kmh` | current ground speed |
| `sat` | number of satellites in fix |
| `hh:mm:ss` | UTC time from GPS |

**Use:** tells ESP32 the rover's current location for logging/telemetry. ESP32 currently just logs it (`lastLat/lastLon/...` vars) — extend to push over WiFi/MQTT etc.

**Example:** `GPS,10.762345,76.654321,0.8,10,09:35:22`

---

## 2. ESP32 → Arduino

### `PUMP,L,ON` / `PUMP,L,OFF`
Turns the **left** relay (left water pump) on/off.
**Use:** sent when only the left-side reading is below `MOISTURE_THRESHOLD`.

### `PUMP,R,ON` / `PUMP,R,OFF`
Turns the **right** relay (right water pump) on/off.
**Use:** sent when only the right-side reading is below threshold.

### `PUMP,BOTH,ON` / `PUMP,BOTH,OFF`
Turns **both** relays on/off together.
**Use:** sent when both left and right readings are below threshold (both sides dry).

No command is sent if all readings are above threshold (soil OK) — Arduino relays simply stay off.

### Buzzer (local, not a serial command)
Right after every soil scan, the Arduino itself buzzes based on the
average moisture % — no command needed from Python/ESP32:
- Soil OK → 2 short happy beeps
- Soil dry → 1 long warning beep

---

## 3. Decision logic (lives on ESP32)

```
needL = L% < MOISTURE_THRESHOLD
needR = R% < MOISTURE_THRESHOLD

needL && needR  -> PUMP,BOTH,ON  ... wait PUMP_RUN_MS ... PUMP,BOTH,OFF
needL only      -> PUMP,L,ON     ... wait PUMP_RUN_MS ... PUMP,L,OFF
needR only      -> PUMP,R,ON     ... wait PUMP_RUN_MS ... PUMP,R,OFF
neither         -> no command (log "Soil OK")
```

`C` (center reading) is logged for reference but currently doesn't trigger a pump on its own — extend the logic here if you want a center pump/zone later.

---

## 4. Tunable constants (must match on both boards)

| Constant | Where | Purpose |
|---|---|---|
| `AIR_VALUE` | both | raw reading in dry air (0% moisture) |
| `WATER_VALUE` | both | raw reading fully in water (100% moisture) |
| `MOISTURE_THRESHOLD` | ESP32 only | % below which a side is "dry" |
| `PUMP_RUN_MS` | ESP32 only | how long a pump stays on per trigger |
| `SCAN_INTERVAL` | Arduino only | how often a full scan cycle runs |
| `GPS_SEND_INTERVAL` | Arduino only | how often GPS is checked/sent |
| `GPS_MOVE_THRESHOLD_M` | Arduino only | min distance (m) to count as "position changed" |

---

## 5. Full command list (quick reference)

| Command | Sender | Receiver | Action |
|---|---|---|---|
| `SCAN,L,<raw>,C,<raw>,R,<raw>` | Arduino | ESP32 | report scan results |
| `GPS,<lat>,<lon>,<speed>,<sat>,<time>` | Arduino | ESP32 | report GPS fix (only on movement) |
| `DHT,<tempC>,<humidity>` | Arduino | Python/ESP32 | DHT11 temp/humidity reading |
| `PUMP,L,ON` | ESP32 | Arduino | left pump on |
| `PUMP,L,OFF` | ESP32 | Arduino | left pump off |
| `PUMP,R,ON` | ESP32 | Arduino | right pump on |
| `PUMP,R,OFF` | ESP32 | Arduino | right pump off |
| `PUMP,BOTH,ON` | ESP32 | Arduino | both pumps on |
| `PUMP,BOTH,OFF` | ESP32 | Arduino | both pumps off |
