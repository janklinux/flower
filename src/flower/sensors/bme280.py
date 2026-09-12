"""BME280 air sensor (I2C): temperature, humidity, pressure.

Thin wrapper over ``bme280pi`` (as used in the prototype). Import is lazy so the
package works without the library; if the sensor or library is unavailable,
:meth:`BME280Sensor.read` returns ``None`` rather than raising, so the control
loop keeps running.
"""

from __future__ import annotations

import logging

log = logging.getLogger("flower.bme280")


class BME280Sensor:
    """Read a BME280 on the I2C bus (default address 0x76)."""

    def __init__(self, address: int = 0x76, enabled: bool = True) -> None:
        self.address = address
        self.enabled = enabled
        self._sensor = None
        self._failed = False

    def _ensure(self):
        if not self.enabled or self._failed:
            return None
        if self._sensor is None:
            try:
                from bme280pi import Sensor
                self._sensor = Sensor(address=self.address)
            except Exception as exc:
                log.warning("BME280 unavailable at 0x%02x (%s)", self.address, exc)
                self._failed = True
                return None
        return self._sensor

    def read(self) -> dict[str, float] | None:
        """Return ``{'temperature', 'humidity', 'pressure'}`` or ``None``."""
        sensor = self._ensure()
        if sensor is None:
            return None
        try:
            data = sensor.get_data()
            return {
                "temperature": float(data["temperature"]),
                "humidity": float(data["humidity"]),
                "pressure": float(data["pressure"]),
            }
        except Exception as exc:  # transient I2C hiccup
            log.warning("BME280 read failed: %s", exc)
            return None
