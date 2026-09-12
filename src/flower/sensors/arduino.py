"""Arduino serial sensor hub.

The Mega/Nano runs ``flower_sensors.ino``, which prints one whitespace-separated
line per sample::

    m0 m1 m2 m3 m4 humidity temperature pressure

i.e. ``n_moisture`` analog soil-moisture readings (ints) followed by the BME280
humidity, temperature and pressure (floats). The original loops tolerated a
``label:`` prefix and malformed lines; :meth:`ArduinoSensorHub.parse` keeps that
tolerance in one place and returns a structured :class:`SensorReading` (or
``None`` for an unusable line). The serial import is lazy so this module loads
without ``pyserial``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("flower.arduino")


@dataclass
class SensorReading:
    """One decoded line from the sensor hub."""

    moisture: list[int]
    humidity: float | None = None
    temperature: float | None = None
    pressure: float | None = None
    raw: str = ""


class ArduinoSensorHub:
    """Read and parse the serial sensor stream."""

    def __init__(self, port: str | None = None, baud: int = 9600,
                 n_moisture: int = 5, timeout: float = 1.0) -> None:
        self.port = port
        self.baud = baud
        self.n_moisture = n_moisture
        self.timeout = timeout
        self._serial = None

    # -- connection -----------------------------------------------------------
    def open(self) -> bool:
        """Open the serial port. Returns False if unconfigured/unavailable."""
        if self.port is None:
            return False
        if self._serial is not None:
            return True
        try:
            from serial import Serial
            self._serial = Serial(port=self.port, baudrate=self.baud, timeout=self.timeout)
            return True
        except Exception as exc:
            log.warning("serial port %s unavailable: %s", self.port, exc)
            return False

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def read(self) -> SensorReading | None:
        """Read one line and parse it; ``None`` if not connected or unparseable."""
        if not self.open():
            return None
        try:
            line = self._serial.readline().decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("serial read failed: %s", exc)
            return None
        return self.parse(line, self.n_moisture)

    # -- parsing (pure, testable) --------------------------------------------
    @staticmethod
    def parse(line: str, n_moisture: int = 5) -> SensorReading | None:
        """Parse a sensor line into a :class:`SensorReading`.

        Tolerant of an optional ``label:`` prefix and of trailing junk. Requires
        at least ``n_moisture`` integer tokens; humidity/temperature/pressure are
        filled from the next three float tokens when present.
        """
        if not line:
            return None
        if ":" in line:                       # drop an optional 'label:' prefix
            line = line.split(":", 1)[1]
        tokens = line.split()
        if len(tokens) < n_moisture:
            return None
        try:
            moisture = [int(float(t)) for t in tokens[:n_moisture]]
        except ValueError:
            return None
        rest = tokens[n_moisture:]

        def _f(i: int) -> float | None:
            try:
                return float(rest[i])
            except (IndexError, ValueError):
                return None

        return SensorReading(
            moisture=moisture,
            humidity=_f(0),
            temperature=_f(1),
            pressure=_f(2),
            raw=line.strip(),
        )

    def __enter__(self) -> "ArduinoSensorHub":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
