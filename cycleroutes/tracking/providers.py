"""Server-side location sources (Qt-free port of gps-tracker/pyNav providers).

- SerialGPSProvider: USB/serial NMEA receiver (e.g. the Adafruit I2C GPS + Arduino
  sketch in hardware/), read on a background thread.
- IPLocationProvider: coarse position from ip-api.com (opt-in; it sends this
  machine's public IP address to that service).
- ManualProvider: a fixed position (testing, or a desk-bound demo).
- PushProvider: fixes pushed over HTTP (phone browser, Pythonista iPhone tracker).

Phones normally use the browser's own GPS directly in the web client; these
providers cover external GPS hardware plugged into the machine running the server.
"""

import glob
import logging
import platform
import re
import threading
import time
from abc import ABC, abstractmethod

import requests

from cycleroutes import config
from cycleroutes.tracking.nmea import Fix, NmeaParser

logger = logging.getLogger(__name__)

NMEA_PREFIX = re.compile(r"^\$G[PNLAB][A-Z]{3},")
SERIAL_PATTERNS = {
    "Darwin": ["/dev/tty.usbmodem*", "/dev/tty.usbserial*", "/dev/tty.SLAB_*", "/dev/tty.GPS*"],
    "Linux": ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/gps*"],
}


class LocationProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def latest(self) -> Fix | None:
        """Most recent fix, or None."""

    def close(self) -> None:
        pass


class SerialGPSProvider(LocationProvider):
    """Reads NMEA sentences from a serial port on a daemon thread."""

    def __init__(self, port: str, baudrate: int = config.GPS_BAUDRATE):
        import serial  # optional dependency: pip install -e '.[gps]'
        self._serial_mod = serial
        self.port, self.baudrate = port, baudrate
        self.name = f"Serial GPS ({port})"
        self.parser = NmeaParser(self.name)
        self._fix: Fix | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"gps-{port}")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._serial_mod.Serial(self.port, self.baudrate, timeout=1) as ser:
                    logger.info("Reading GPS on %s", self.port)
                    while not self._stop.is_set():
                        line = ser.readline().decode("ascii", errors="replace")
                        fix = self.parser.feed(line)
                        if fix:
                            self._fix = fix
            except (self._serial_mod.SerialException, OSError) as exc:
                logger.warning("GPS %s unavailable (%s); retrying in 3 s", self.port, exc)
                self._stop.wait(3)

    def latest(self) -> Fix | None:
        return self._fix

    def close(self) -> None:
        self._stop.set()


class IPLocationProvider(LocationProvider):
    """City-level position from ip-api.com, cached for a minute."""

    name = "IP geolocation (approximate)"
    cache_s = 60

    def __init__(self):
        self._fix: Fix | None = None
        self._at = 0.0

    def latest(self) -> Fix | None:
        if self._fix and time.time() - self._at < self.cache_s:
            return self._fix
        try:
            data = requests.get(config.IP_GEOLOCATION_URL, timeout=5).json()
            if data.get("status") == "success":
                self._fix = Fix(data["lat"], data["lon"], time.time(), accuracy_m=5000.0, source=self.name)
                self._at = time.time()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("IP geolocation failed: %s", exc)
        return self._fix


class ManualProvider(LocationProvider):
    name = "Manual position"

    def __init__(self, lat: float, lon: float):
        self.set(lat, lon)

    def set(self, lat: float, lon: float) -> None:
        self._fix = Fix(lat, lon, time.time(), accuracy_m=0.0, source=self.name)

    def latest(self) -> Fix | None:
        return self._fix


class PushProvider(LocationProvider):
    """Holds the newest fix pushed to the API (phone browser or iPhone tracker app)."""

    name = "Phone (pushed over HTTP)"

    def __init__(self):
        self._fix: Fix | None = None

    def push(self, fix: Fix) -> None:
        if self._fix is None or fix.timestamp >= self._fix.timestamp:
            self._fix = fix

    def latest(self) -> Fix | None:
        return self._fix


def _looks_like_gps(port: str, baudrate: int) -> bool:
    import serial
    try:
        with serial.Serial(port, baudrate, timeout=1) as ser:
            for _ in range(8):
                if NMEA_PREFIX.match(ser.readline().decode("ascii", errors="replace").strip()):
                    return True
    except (serial.SerialException, OSError):
        pass
    return False


def discover_serial_gps(baudrate: int = config.GPS_BAUDRATE) -> list[str]:
    """Serial ports that are currently emitting NMEA sentences."""
    try:
        import serial.tools.list_ports
    except ImportError:
        logger.info("pyserial not installed - serial GPS disabled (pip install -e '.[gps]')")
        return []
    system = platform.system()
    if system in SERIAL_PATTERNS:
        ports = sorted({p for pat in SERIAL_PATTERNS[system] for p in glob.glob(pat)})
    else:  # Windows: COM ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
    return [p for p in ports if _looks_like_gps(p, baudrate)]


class ProviderManager:
    """Registry of available sources with one active at a time."""

    def __init__(self, include_ip: bool = False, scan_serial: bool = False):
        self.providers: dict[str, LocationProvider] = {}
        self.push = PushProvider()
        self.add("phone", self.push)
        if include_ip:
            self.add("ip", IPLocationProvider())
        if scan_serial:
            self.scan()
        self.active_key = "phone"

    def add(self, key: str, provider: LocationProvider) -> None:
        self.providers[key] = provider

    def scan(self) -> list[str]:
        """Look for serial GPS receivers and register any that are new."""
        found = []
        for port in discover_serial_gps():
            key = f"serial:{port}"
            if key not in self.providers:
                self.add(key, SerialGPSProvider(port))
            found.append(key)
        return found

    def set_active(self, key: str) -> bool:
        if key not in self.providers:
            return False
        self.active_key = key
        return True

    def latest(self) -> Fix | None:
        return self.providers[self.active_key].latest()

    def describe(self) -> list[dict]:
        return [{"key": k, "name": p.name, "active": k == self.active_key,
                 "has_fix": p.latest() is not None if k != "ip" else None}
                for k, p in self.providers.items()]

    def close(self) -> None:
        for p in self.providers.values():
            p.close()
