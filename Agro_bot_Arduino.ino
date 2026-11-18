#include <Servo.h>

// --- Pin Definitions ---
// Ultrasonic Sensors (Trig, Echo)
const int trigF = 22, echoF = 23; // Front
const int trigL = 24, echoL = 25; // Left
const int trigR = 26, echoR = 27; // Right

// Motor Driver (L298N)
const int enA = 5;  
const int in1 = 2;  
const int in2 = 3;  
const int enB = 6;  
const int in3 = 4;  
const int in4 = 7;  

// Servos
Servo ploughServo; // Big high-torque servo for plough
Servo seedServo;   // Servo for seed dispenser

const int ploughPin = 11;
const int seedPin = 12;

// Sensors, Pumps, Fan & Buzzer
const int moisturePin = A0;           
const int waterPumpFanRelay = 8;      // Water Pump 1 + PC Cooling Fan
const int neemPumpRelay = 9;          // Water Pump 2 (Neem pesticide)
const int buzzerPin = 10;             

const int MOISTURE_THRESHOLD = 600;   

void setup() {
  Serial.begin(115200); 

  pinMode(trigF, OUTPUT); pinMode(echoF, INPUT);
  pinMode(trigL, OUTPUT); pinMode(echoL, INPUT);
  pinMode(trigR, OUTPUT); pinMode(echoR, INPUT);

  pinMode(enA, OUTPUT); pinMode(in1, OUTPUT); pinMode(in2, OUTPUT);
  pinMode(enB, OUTPUT); pinMode(in3, OUTPUT); pinMode(in4, OUTPUT);

  pinMode(waterPumpFanRelay, OUTPUT);
  pinMode(neemPumpRelay, OUTPUT);
  pinMode(buzzerPin, OUTPUT);

  digitalWrite(waterPumpFanRelay, LOW);
  digitalWrite(neemPumpRelay, LOW);

  ploughServo.attach(ploughPin);
  seedServo.attach(seedPin);

  ploughServo.write(90); // Raised
  seedServo.write(0);    // Closed

  playBootMelody();
}

void loop() {
  // Listen for Python / ESP32 Webcam Commands
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    
    if (cmd == 'P') { // Plant stress detected -> Spray Neem
      stopMotors();
      playBeep(900, 150);
      digitalWrite(neemPumpRelay, HIGH);
      delay(2500); 
      digitalWrite(neemPumpRelay, LOW);
    }
    else if (cmd == 'W') { // Force watering command
      triggerWateringSystem();
    }
  }

  // 3 Ultrasonic Sensors for Obstacle Avoidance
  long distF = getDistance(trigF, echoF);
  long distL = getDistance(trigL, echoL);
  long distR = getDistance(trigR, echoR);

  if (distF < 25 && distF > 0) { 
    stopMotors();
    ploughServo.write(90); 
    playBeep(400, 200);    
    
    if (distL > distR) {
      turnLeft(150);
    } else {
      turnRight(150);
    }
    delay(700);
    stopMotors();
    return;
  }

  // Autonomous Field Routine: Plough & Seed
  ploughServo.write(160); // Lower plough
  moveForward(130);       
  delay(1000);

  dispenseSeed();

  // Soil Moisture Check
  int moistureVal = analogRead(moisturePin);
  if (moistureVal > MOISTURE_THRESHOLD) { 
    stopMotors();
    triggerWateringSystem();
  }
}

long getDistance(int trig, int echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);
  long duration = pulseIn(echo, HIGH, 25000);
  if (duration == 0) return 999;
  return duration * 0.034 / 2;
}

void moveForward(int speed) {
  analogWrite(enA, speed); analogWrite(enB, speed);
  digitalWrite(in1, HIGH); digitalWrite(in2, LOW);
  digitalWrite(in3, HIGH); digitalWrite(in4, LOW);
}

void turnLeft(int speed) {
  analogWrite(enA, speed); analogWrite(enB, speed);
  digitalWrite(in1, LOW);  digitalWrite(in2, HIGH);
  digitalWrite(in3, HIGH); digitalWrite(in4, LOW);
}

void turnRight(int speed) {
  analogWrite(enA, speed); analogWrite(enB, speed);
  digitalWrite(in1, HIGH); digitalWrite(in2, LOW);
  digitalWrite(in3, LOW);  digitalWrite(in4, HIGH);
}

void stopMotors() {
  analogWrite(enA, 0); analogWrite(enB, 0);
  digitalWrite(in1, LOW); digitalWrite(in2, LOW);
  digitalWrite(in3, LOW); digitalWrite(in4, LOW);
}

void dispenseSeed() {
  playBeep(1200, 50);
  seedServo.write(65); 
  delay(300);
  seedServo.write(0);  
  delay(200);
}

void triggerWateringSystem() {
  playBeep(700, 100);
  playBeep(850, 100);
  digitalWrite(waterPumpFanRelay, HIGH); // Water pump + PC fan misting
  delay(3000);                          
  digitalWrite(waterPumpFanRelay, LOW);
}

void playBeep(int freq, int durationMs) {
  tone(buzzerPin, freq, durationMs);
  delay(durationMs + 20);
}

void playBootMelody() {
  tone(buzzerPin, 523, 100); delay(120);
  tone(buzzerPin, 659, 100); delay(120);
  tone(buzzerPin, 784, 150); delay(180);
}