/*
  ARDUINO MEGA — Soil Moisture Scanner + Pump Relay + GPS + DHT11 + Buzzer
  ---------------------------------------------------------------------
  HARDWARE:
    - Capacitive soil moisture sensor  -> A0
    - DHT11 temperature/humidity       -> A1   (digital read via DHT lib)
    - Mini buzzer                      -> D8
    - Pan servo (left/right)           -> D9
    - Tilt servo (up/down)             -> D10
    - Relay 1 (Pump LEFT)              -> D5   (active LOW module)
    - Relay 2 (Pump RIGHT)             -> D6   (active LOW module)
    - GPS module (NEO-6M)              -> Serial1 (RX1=19, TX1=18)
    - Link to ESP32 / Python           -> Serial2 (RX2=17, TX2=16)
                                           GND <-> GND (common ground, mandatory)

  LIBRARIES NEEDED (Library Manager):
    - TinyGPS++        ("TinyGPSPlus")
    - DHT sensor library (Adafruit) + Adafruit Unified Sensor (dependency)

  BUZZER BEHAVIOR (after every soil scan):
    - Soil OK (avg moisture >= SOIL_GOOD_THRESHOLD)  -> 2 short happy beeps
    - Soil dry (avg moisture <  SOIL_GOOD_THRESHOLD)  -> 1 long warning beep

  PROTOCOL (line-based, ends with \n):
    Arduino -> ESP32/Python :  SCAN,L,<raw>,C,<raw>,R,<raw>
    Arduino -> ESP32/Python :  GPS,<lat>,<lon>,<speed_kmh>,<sat>,<hh:mm:ss>
    Arduino -> ESP32/Python :  DHT,<tempC>,<humidity>
    ESP32/Python -> Arduino :  SCAN                       (on-demand ONLY —
                                there is no automatic periodic scan anymore.
                                Does a soil moisture check — moves the pan/
                                tilt servo, reads the capacitive sensor,
                                buzzes, replies with the SCAN,... line above,
                                and if dry, runs the 15s pump fallback below.)
    ESP32/Python -> Arduino :  PUMP,L,ON | PUMP,L,OFF
                                PUMP,R,ON | PUMP,R,OFF
                                PUMP,BOTH,ON | PUMP,BOTH,OFF

  FIXES APPLIED (vs previous version):
    1. BUZZER_PIN was #define'd as 4 but wired/documented as D8 -> fixed to 8.
    2. Added SOIL_SETTLE_MS dwell: after the servo drops the probe into soil
       at each of the 3 positions, it now PARKS there for 8s before reading,
       instead of reading ~1.2s after arrival. Capacitive sensors need time
       to stabilize once seated in soil — reading too early gives a noisy/
       inflated value. Read happens only after the settle period.
    NOTE: this makes runScanCycle() take ~3 x (travel + 8s settle + read)
    ≈ 27-28s total, fully blocking (GPS/DHT sends and incoming commands are
    not processed while a scan is running). That's inherent to a blocking
    servo-sweep design — say the word if you want it converted to a
    non-blocking state machine instead.
*/
#include <Servo.h>
#include <TinyGPS++.h>
#include <DHT.h>

// ---- PIN CONNECTIONS (wire each of these exactly here) ----
#define PAN_PIN     9    // Pan servo signal wire (left/right sweep)
#define TILT_PIN    10   // Tilt servo signal wire (up/down sweep)
#define MOIST_PIN   A0   // Capacitive soil moisture sensor: OUT/AOUT pin here
#define DHT_PIN     A1   // DHT11 data pin (used as a plain digital pin by the DHT lib)
#define DHT_TYPE    DHT11
#define BUZZER_PIN  8    // FIXED: was 4, header/README say D8 — mini buzzer: + lead here, - lead to GND
#define RELAY_L     5    // Relay module IN1 -> controls LEFT pump
#define RELAY_R     6    // Relay module IN2 -> controls RIGHT pump
// GPS (NEO-6M) module: TX -> Mega pin 19 (RX1), RX -> Mega pin 18 (TX1), VCC/GND as usual
// ESP32 / Python link: Mega pin 16 (TX2) -> receiver's RX, Mega pin 17 (RX2) <- receiver's TX, common GND

// ---- CALIBRATION (raw analogRead 0-1023) ----
// NOTE: these two numbers are placeholders. Calibrate for YOUR sensor:
//   dry in air  -> note raw value -> AIR_VALUE
//   fully in water -> note raw value -> WATER_VALUE
const int AIR_VALUE   = 600;   // reading in dry air (0% moisture)
const int WATER_VALUE = 280;   // reading fully in water (100% moisture)
const int SOIL_GOOD_THRESHOLD = 35; // avg % at/above this = buzz "good" — tune to your crop

// ---- SERVO POSITIONS ----
const int TILT_UP     = 0;
const int TILT_DOWN   = 90;
const int PAN_CENTER  = 90;
const int PAN_RIGHT   = 135;
const int PAN_LEFT    = 45;

const unsigned long GPS_SEND_INTERVAL = 5000UL;  // check GPS every 5s
const unsigned long DHT_SEND_INTERVAL = 10000UL; // read/send DHT every 10s
const double GPS_MOVE_THRESHOLD_M = 1.0;         // meters before "position changed"

// NEW: how long to sit parked in the soil before trusting the reading
const unsigned long SOIL_SETTLE_MS = 8000UL;

unsigned long lastGpsSend = 0;
unsigned long lastDhtSend = 0;

Servo panServo, tiltServo;
TinyGPSPlus gps;
DHT dht(DHT_PIN, DHT_TYPE);

// GPS state
double prevLat = 0.0, prevLng = 0.0;
bool haveFirstFix = false;

void setup() {
  Serial.begin(9600);          // USB debug monitor
  Serial1.begin(9600);         // GPS module (NEO-6M default baud)
  Serial2.begin(9600);         // link to ESP32/Python

  dht.begin();

  panServo.attach(PAN_PIN);
  tiltServo.attach(TILT_PIN);

  pinMode(RELAY_L, OUTPUT);
  pinMode(RELAY_R, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(RELAY_L, HIGH);  // HIGH = OFF on active-low relay module
  digitalWrite(RELAY_R, HIGH);
  digitalWrite(BUZZER_PIN, LOW);

  tiltServo.write(TILT_UP);
  panServo.write(PAN_CENTER);
  delay(500);

  Serial.println(F("Arduino ready."));
}

void loop() {
  // keep feeding the GPS parser from the module continuously
  while (Serial1.available()) {
    gps.encode(Serial1.read());
  }

  // 1) periodic GPS read/compare/send
  if (millis() - lastGpsSend >= GPS_SEND_INTERVAL) {
    lastGpsSend = millis();
    handleGps();
  }

  // 2) periodic DHT11 read/send
  if (millis() - lastDhtSend >= DHT_SEND_INTERVAL) {
    lastDhtSend = millis();
    handleDht();
  }

  // 3) listen for commands from ESP32/Python (SCAN, PUMP,*, ...)
  if (Serial2.available()) {
    String cmd = Serial2.readStringUntil('\n');
    cmd.trim();
    handleIncomingCommand(cmd);
  }
}

// ---------------- MOISTURE / SERVO ----------------

int readMoistureRaw() {
  long sum = 0;
  for (int i = 0; i < 5; i++) { sum += analogRead(MOIST_PIN); delay(20); }
  return sum / 5;
}

int rawToPercent(int raw) {
  int pct = map(raw, AIR_VALUE, WATER_VALUE, 0, 100);
  return constrain(pct, 0, 100);
}

void moveTo(int panAngle, int tiltAngle) {
  tiltServo.write(TILT_UP);
  delay(300);
  panServo.write(panAngle);
  delay(400);
  tiltServo.write(tiltAngle);
  delay(300);
}

// NEW: probe is now down at (panAngle, TILT_DOWN) — sit for SOIL_SETTLE_MS
// before reading so the capacitive sensor stabilizes in the soil.
int scanAtPosition(int panAngle) {
  moveTo(panAngle, TILT_DOWN);
  delay(SOIL_SETTLE_MS);      // <-- the 8s wait you were asking for
  return readMoistureRaw();
}

void runScanCycle() {
  // Step sequence: Center -> Right -> Left -> back to Center
  // Each position: move -> settle 8s -> read (see scanAtPosition)
  int c = scanAtPosition(PAN_CENTER);
  int r = scanAtPosition(PAN_RIGHT);
  int l = scanAtPosition(PAN_LEFT);

  tiltServo.write(TILT_UP);
  delay(200);
  panServo.write(PAN_CENTER);
  delay(300);

  String msg = "SCAN,L," + String(l) + ",C," + String(c) + ",R," + String(r);
  Serial2.println(msg);
  Serial.println("SENT -> " + msg +
                  "  (L%=" + rawToPercent(l) +
                  " C%=" + rawToPercent(c) +
                  " R%=" + rawToPercent(r) + ")");

  int avgPct = (rawToPercent(l) + rawToPercent(c) + rawToPercent(r)) / 3;
  if (avgPct >= SOIL_GOOD_THRESHOLD) {
    buzzGood();
  } else {
    buzzBad();
    runDryPumpCycle();   // NEW: dry scan -> on-board fallback watering
  }
}

// NEW: on-board fallback. If a scan comes back dry, run BOTH pumps
// (relays D5/D6) for PUMP_ON_MS then shut off automatically — no
// round-trip to Python needed for this case. Also pushes a STATUS line
// so Python/the dashboard knows it happened.
// CONFLICT WARNING: Python's irrigation.py may ALSO send PUMP,* commands
// off the same SCAN reply. If both are active you can double-water —
// either disable that path in Python or make sure only one side owns it.
const unsigned long PUMP_ON_MS = 15000UL;

void runDryPumpCycle() {
  Serial.println(F("Soil dry -> running BOTH pumps 15s (on-board fallback)"));
  Serial2.println(F("STATUS,DRY_PUMP_FALLBACK_15S"));
  digitalWrite(RELAY_L, LOW);   // ON (active-low)
  digitalWrite(RELAY_R, LOW);
  delay(PUMP_ON_MS);
  digitalWrite(RELAY_L, HIGH);  // OFF
  digitalWrite(RELAY_R, HIGH);
  Serial.println(F("Pumps OFF (15s fallback complete)"));
}

// ---------------- BUZZER ----------------

void buzzGood() {
  // 2 short happy beeps
  for (int i = 0; i < 2; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(120);
    digitalWrite(BUZZER_PIN, LOW);
    delay(120);
  }
}

void buzzBad() {
  // 1 long warning beep
  digitalWrite(BUZZER_PIN, HIGH);
  delay(800);
  digitalWrite(BUZZER_PIN, LOW);
}

// ---------------- GPS ----------------

void handleGps() {
  if (!gps.location.isValid() || !gps.location.isUpdated()) {
    Serial.println(F("GPS: no valid fix yet."));
    return;
  }

  double lat = gps.location.lat();
  double lng = gps.location.lng();
  double speedKmh = gps.speed.isValid() ? gps.speed.kmph() : 0.0;
  int sats = gps.satellites.isValid() ? gps.satellites.value() : 0;

  char timeBuf[9] = "00:00:00";
  if (gps.time.isValid()) {
    snprintf(timeBuf, sizeof(timeBuf), "%02d:%02d:%02d",
              gps.time.hour(), gps.time.minute(), gps.time.second());
  }

  bool positionChanged = true;
  if (haveFirstFix) {
    double dist = TinyGPSPlus::distanceBetween(prevLat, prevLng, lat, lng);
    positionChanged = dist >= GPS_MOVE_THRESHOLD_M;
  }

  if (positionChanged) {
    prevLat = lat;
    prevLng = lng;
    haveFirstFix = true;

    String msg = "GPS," + String(lat, 6) + "," + String(lng, 6) + "," +
                 String(speedKmh, 1) + "," + String(sats) + "," + String(timeBuf);
    Serial2.println(msg);
    Serial.println("SENT -> " + msg);
  } else {
    Serial.println(F("GPS: position unchanged, skipping send."));
  }
}

// ---------------- DHT11 ----------------

void handleDht() {
  float tempC = dht.readTemperature();
  float hum = dht.readHumidity();

  if (isnan(tempC) || isnan(hum)) {
    Serial.println(F("DHT11: read failed, skipping."));
    return;
  }

  String msg = "DHT," + String(tempC, 1) + "," + String(hum, 1);
  Serial2.println(msg);
  Serial.println("SENT -> " + msg);
}

// ---------------- COMMAND DISPATCH ----------------
// SCAN does ONLY a soil moisture check (servo sweep + sensor read + buzz +
// reply) — it never touches pumps, driving, or anything else. PUMP,*
// commands ONLY touch the relays. Keeping them as separate branches (not
// one big combined action) is deliberate so each command does exactly
// one job.

void handleIncomingCommand(String cmd) {
  Serial.println("RX <- " + cmd);

  if (cmd == "SCAN") {
    runScanCycle();   // soil moisture check ONLY — see function below
    return;
  }

  handlePumpCommand(cmd);
}

// ---------------- RELAY / PUMP ----------------

void handlePumpCommand(String cmd) {
  if (cmd == "PUMP,L,ON")        digitalWrite(RELAY_L, LOW);
  else if (cmd == "PUMP,L,OFF")  digitalWrite(RELAY_L, HIGH);
  else if (cmd == "PUMP,R,ON")   digitalWrite(RELAY_R, LOW);
  else if (cmd == "PUMP,R,OFF")  digitalWrite(RELAY_R, HIGH);
  else if (cmd == "PUMP,BOTH,ON") {
    digitalWrite(RELAY_L, LOW);
    digitalWrite(RELAY_R, LOW);
  }
  else if (cmd == "PUMP,BOTH,OFF") {
    digitalWrite(RELAY_L, HIGH);
    digitalWrite(RELAY_R, HIGH);
  }
}