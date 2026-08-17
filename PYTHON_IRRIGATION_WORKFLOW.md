# Python Automated Irrigation Workflow (Simple Terms)

This document explains how the Python brain (`irrigation.py` & `config.py`) automatically decides when, where, and how long to turn on the water pumps for the Farm Rover.

---

## 1. How Automated Irrigation Works in 5 Simple Steps

```text
[ Arduino Scan ] ---> [ Raw Value to % ] ---> [ Check Moisture Deficit ] ---> [ Calculate Pump Time ] ---> [ Trigger Relay Pump ]
```

### Step 1: Read Sensor Data
The Arduino Mega sweeps the pan/tilt servo arm, reads the capacitive soil sensor at **Left (L)**, **Center (C)**, and **Right (R)** positions, and sends the raw values over Serial link to Python:
- `SCAN,L,450,C,380,R,510`

### Step 2: Convert Raw Values to Moisture %
Python converts raw analog readings into an actual moisture percentage:
$$\text{Moisture \%} = \frac{\text{Raw Reading} - \text{AIR\_VALUE (600)}}{\text{WATER\_VALUE (280)} - \text{AIR\_VALUE (600)}} \times 100$$
- `AIR_VALUE = 600` (Dry soil = 0%)
- `WATER_VALUE = 280` (Wet soil / water = 100%)

### Step 3: Compare Against Target Moisture
Python compares current moisture against the ideal target:
$$\text{Water Level} = \text{Current Moisture \%} - \text{Target (65\%)}$$
- If **Water Level $\ge$ 0**: Soil is healthy! No watering needed.
- If **Water Level < 0**: Soil is dry! The negative amount is the **Deficit %** (how much water is missing).

### Step 4: Calculate Smart Pump Run Time (Proportional Irrigation)
Instead of pumping a fixed amount of water every time, Python calculates **exact seconds** based on how dry the soil is:
$$\text{Pump Duration (seconds)} = \text{Deficit \%} \times 0.3\text{ sec/1\%}$$
- **Minimum Floor Cap (`MIN_PUMP_SEC = 2s`)**: Ignores tiny micro-bursts if deficit is negligible.
- **Maximum Safety Cap (`MAX_PUMP_SEC = 15s`)**: Prevents flooding or overwatering even if soil is bone dry.

### Step 5: Execute Pump Command & Log Event
Python sends line commands to Arduino over Serial/WiFi link to open the active-low relay:
1. Send `PUMP,L,ON` (or `PUMP,R,ON`).
2. Record irrigation log event in `SharedState` (Zone, duration, deficit %, trigger source).
3. Sleep for calculated duration (e.g. 5.1 seconds).
4. Send `PUMP,L,OFF` (or `PUMP,R,OFF`).

---

## 2. Text Logic Block Diagram

[ignoring loop detection]

```text
+---------------------------------------------------------------------------------------------------+
|                           PYTHON AUTOMATED IRRIGATION LOGIC WORKFLOW                              |
+---------------------------------------------------------------------------------------------------+

                               +----------------------------------+
                               | RECEIVE SCAN DATA FROM ARDUINO   |
                               |  Example: SCAN,L,450,C,380,R,510  |
                               +----------------+-----------------+
                                                |
                                                v
                               +----------------------------------+
                               | CONVERT RAW ANALOG TO MOISTURE % |
                               |  L% = 40%,  C% = 62%,  R% = 25%   |
                               +----------------+-----------------+
                                                |
                                                v
                               +----------------------------------+
                               | CHECK WATER LEVEL VS TARGET 65%  |
                               |  L Level: 40 - 65 = -25% (Dry!)   |
                               |  R Level: 25 - 65 = -40% (Dry!)   |
                               +----------------+-----------------+
                                                |
              +---------------------------------+---------------------------------+
              |                                                                   |
              v                                                                   v
   +-----------------------+                                           +-----------------------+
   |   EVALUATE LEFT SIDE  |                                           |  EVALUATE RIGHT SIDE  |
   | Deficit = 25%         |                                           | Deficit = 40%         |
   +----------+------------+                                           +----------+------------+
              |                                                                   |
              v                                                                   v
   +-----------------------+                                           +-----------------------+
   | CALCULATE PUMP TIME   |                                           | CALCULATE PUMP TIME   |
   | 25% * 0.3s = 7.5 sec  |                                           | 40% * 0.3s = 12.0 sec |
   | (Bounded 2s to 15s)   |                                           | (Bounded 2s to 15s)   |
   +----------+------------+                                           +----------+------------+
              |                                                                   |
              v                                                                   v
   +-----------------------+                                           +-----------------------+
   |   PUMP LEFT CYCLE     |                                           |   PUMP RIGHT CYCLE    |
   | 1. Send PUMP,L,ON     |                                           | 1. Send PUMP,R,ON     |
   | 2. Log event in State |                                           | 2. Log event in State |
   | 3. Wait 7.5 seconds   |                                           | 3. Wait 12.0 seconds  |
   | 4. Send PUMP,L,OFF    |                                           | 4. Send PUMP,R,OFF    |
   +----------+------------+                                           +----------+------------+
              |                                                                   |
              +---------------------------------+---------------------------------+
                                                |
                                                v
                               +----------------------------------+
                               |   IRRIGATION CYCLE COMPLETED     |
                               |  Update UI Dashboard & Logs      |
                               +----------------------------------+
```

---

## 3. Configuration Parameters Quick Summary

| Configuration Setting | Value | Meaning / Purpose |
| :--- | :--- | :--- |
| `MOISTURE_TARGET_PCT` | **65%** | Ideal soil moisture goal for crops. |
| `WATER_SEC_PER_DEFICIT_PCT` | **0.3s** | Seconds pump runs for every 1% of missing moisture. |
| `MIN_PUMP_SEC` | **2.0s** | Minimum run time to prevent motor jitter. |
| `MAX_PUMP_SEC` | **15.0s** | Hard safety cap to prevent crop flooding. |
| `AIR_VALUE` | **600** | Raw analog sensor value in completely dry air. |
| `WATER_VALUE` | **280** | Raw analog sensor value in pure water. |
