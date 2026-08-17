"""Owns the serial connection to the Arduino Mega.

Runs a background thread that continuously reads lines and pushes
them onto a queue for command_receiver.py to consume, and exposes a
thread-safe write() for command_sender.py.
"""
import serial
import threading
import queue
import time

class SerialManager:
    def __init__(self, port, baud, logger=None):
        self.logger = logger
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)  # let Mega reset after port opens
        self.incoming = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                if line:
                    self.incoming.put(line)
                    if self.logger:
                        self.logger.debug(f"RX <- {line}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Serial read error: {e}")

    def send(self, cmd: str):
        line = (cmd.strip() + "\n").encode()
        self.ser.write(line)
        if self.logger:
            self.logger.debug(f"TX -> {cmd}")

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def get_line(self, timeout=0.1):
        try:
            return self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self._stop.set()
        self.ser.close()
