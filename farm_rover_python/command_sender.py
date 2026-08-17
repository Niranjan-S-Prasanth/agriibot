"""High-level command senders -> Arduino Mega.
Arduino only executes; all decisions are made in Python.
"""

# Movement single-letter commands (match Arduino's command switch)
FORWARD = "F"
BACKWARD = "B"
LEFT = "L"
RIGHT = "R"
STOP = "S"

class CommandSender:
    def __init__(self, serial_manager):
        self.ser = serial_manager

    # ---- movement ----
    def forward(self):  self.ser.send(FORWARD)
    def backward(self): self.ser.send(BACKWARD)
    def turn_left(self):  self.ser.send(LEFT)
    def turn_right(self): self.ser.send(RIGHT)
    def stop(self):     self.ser.send(STOP)

    # ---- pump ----
    def pump_on(self, side):   # side: "L" | "R" | "BOTH"
        self.ser.send(f"PUMP,{side},ON")
    def pump_off(self, side):
        self.ser.send(f"PUMP,{side},OFF")

    # ---- soil servo ----
    def request_scan(self):
        self.ser.send("SCAN")
    def servo_home(self):
        self.ser.send("HOME")
    def servo_pan(self, angle):
        self.ser.send(f"PAN,{angle}")
