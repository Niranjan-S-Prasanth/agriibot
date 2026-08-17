"""WiFi (TCP) link to the Arduino Mega, via the ESP32 bridge.

Same interface as serial_manager.SerialManager (send / get_line / close)
on purpose — main.py can use either one interchangeably depending on
config.CONNECTION_MODE, without any other code caring which link is
actually in use.
"""
import socket
import threading
import queue
import time


import concurrent.futures

class WifiManager:
    def __init__(self, host, port, logger=None, reconnect_delay=2.0):
        self.host = host
        self.port = port
        self.logger = logger
        self.reconnect_delay = reconnect_delay
        self.incoming = queue.Queue()
        self._stop = threading.Event()
        self._sock = None
        self._lock = threading.Lock()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _discover_ip(self):
        """Scans the local subnet rapidly for any device listening on self.port (8888)."""
        try:
            # Find local IP
            s_temp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_temp.connect(("8.8.8.8", 80))
            local_ip = s_temp.getsockname()[0]
            s_temp.close()
            
            subnet = ".".join(local_ip.split(".")[:3])
            if self.logger:
                self.logger.info(f"Scanning local network {subnet}.X for ESP32 bridge on port {self.port}...")

            def check_target(target_ip):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.8)
                    res = sock.connect_ex((target_ip, self.port))
                    sock.close()
                    if res == 0:
                        return target_ip
                except Exception:
                    pass
                return None

            ips = [f"{subnet}.{i}" for i in range(1, 255)]
            found_ip = None
            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                results = executor.map(check_target, ips)
                for res_ip in results:
                    if res_ip:
                        found_ip = res_ip
                        break

            if found_ip:
                if self.logger:
                    self.logger.info(f"Auto-discovered ESP32 bridge IP: {found_ip}")
                return found_ip
        except Exception as e:
            if self.logger:
                self.logger.debug(f"IP auto-discovery error: {e}")
        return None

    def _connect(self):
        attempts = 0
        while not self._stop.is_set():
            attempts += 1
            # Fast auto-discover if primary host fails on first attempt
            if attempts > 1 and attempts % 2 == 0:
                discovered = self._discover_ip()
                if discovered:
                    self.host = discovered
                    import config
                    config.ESP32_BRIDGE_IP = discovered

            try:
                s = socket.create_connection((self.host, self.port), timeout=2.0)
                s.settimeout(1.0)
                with self._lock:
                    self._sock = s
                if self.logger:
                    self.logger.info(f"Connected to ESP32 bridge at {self.host}:{self.port}")
                return
            except OSError as e:
                if self.logger:
                    self.logger.warning(f"ESP32 bridge connect to {self.host}:{self.port} failed ({e})")
                time.sleep(self.reconnect_delay)

    def _run_loop(self):
        self._connect()
        buf = b""
        while not self._stop.is_set():
            with self._lock:
                sock = self._sock
            if sock is None:
                time.sleep(0.2)
                continue
            try:
                chunk = sock.recv(256)
                if not chunk:
                    raise ConnectionError("ESP32 bridge closed the connection")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode(errors="ignore").strip()
                    if text:
                        self.incoming.put(text)
                        if self.logger:
                            self.logger.debug(f"RX <- {text}")
            except socket.timeout:
                continue
            except OSError as e:
                if self.logger:
                    self.logger.error(f"WiFi link dropped ({e}), reconnecting...")
                with self._lock:
                    self._sock = None
                self._connect()

    def send(self, cmd: str):
        line = (cmd.strip() + "\n").encode()
        with self._lock:
            sock = self._sock
        if sock is None:
            if self.logger:
                self.logger.error("Send failed: not connected to ESP32 bridge")
            return
        try:
            sock.sendall(line)
            if self.logger:
                self.logger.debug(f"TX -> {cmd}")
        except OSError as e:
            if self.logger:
                self.logger.error(f"Send failed ({e})")
            with self._lock:
                self._sock = None

    def is_connected(self):
        with self._lock:
            return self._sock is not None

    def get_line(self, timeout=0.1):
        try:
            return self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self._stop.set()
        with self._lock:
            if self._sock:
                self._sock.close()
