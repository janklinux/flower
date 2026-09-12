"""flower — a small, hardware-agnostic controller for a Raspberry Pi plant rig.

Refactored from the PLANT_SOURCE prototype scripts into composable classes:

- :class:`~flower.config.Config`        — declarative rig description (pins, ports, retention)
- :class:`~flower.actuators.relay.Relay` / :class:`~flower.actuators.relay.RelayBank`
- :class:`~flower.sensors.bme280.BME280Sensor`   — air temperature / humidity / pressure (I2C)
- :class:`~flower.sensors.arduino.ArduinoSensorHub` — soil moisture + RHT over serial
- :func:`~flower.sensors.cpu.read_cpu_temperature`
- :class:`~flower.store.timeseries.TimeSeriesStore` — rolling-window JSON logging
- :class:`~flower.store.settings.SettingsStore`     — the flag-file command channel
- :class:`~flower.controller.Controller`            — the sense -> decide -> actuate loop

Every hardware dependency is optional and imported lazily, so importing this
package and running the controller works with *nothing* connected: unassigned
pins and absent libraries degrade to a logged dry-run instead of raising.
"""

from .config import ArduinoConfig, BME280Config, Config, RelayConfig, TimedActionConfig
from .actuators.relay import Relay, RelayBank
from .sensors.arduino import ArduinoSensorHub, SensorReading
from .sensors.bme280 import BME280Sensor
from .sensors.cpu import read_cpu_temperature
from .store.settings import SettingsStore
from .store.timeseries import TimeSeriesStore
from .controller import Controller

__version__ = "0.1.0"

__all__ = [
    "Config",
    "RelayConfig",
    "BME280Config",
    "ArduinoConfig",
    "TimedActionConfig",
    "Relay",
    "RelayBank",
    "BME280Sensor",
    "ArduinoSensorHub",
    "SensorReading",
    "read_cpu_temperature",
    "TimeSeriesStore",
    "SettingsStore",
    "Controller",
    "__version__",
]
