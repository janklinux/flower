"""The controller: one clean sense -> decide -> actuate loop.

This is the refactor of ``manage-flower.py`` / ``manage-8relay.py``. Instead of
a 280-line ``while True`` with copy-pasted valve blocks, it composes the sensor,
store and relay classes and expresses the three behaviours generically:

* **direct flags** — ``settings[<relay-name>]`` (bool) holds that relay on/off;
* **timed actions** — ``settings[<key>]`` truthy pulses a relay for N seconds
  (the water-pump-runs-75s / fill-runs-600s pattern);
* **auto-heat** — engage the ``heat`` relay below a configured temperature.

With the default config (all pins ``None``) every actuation is a logged dry run,
so ``Controller(Config.default()).run()`` is safe to start with nothing wired.

It is also thread-safe: :meth:`snapshot`, :meth:`apply_settings` and
:meth:`timeseries` take a lock shared with :meth:`step`, so the HTTP API
(``flower.server``) can read status and push commands while the loop runs.
"""

from __future__ import annotations

import logging
import threading
import time

from .config import Config
from .actuators.relay import RelayBank
from .sensors.arduino import ArduinoSensorHub
from .sensors.bme280 import BME280Sensor
from .sensors.cpu import read_cpu_temperature
from .store.settings import SettingsStore
from .store.timeseries import TimeSeriesStore

log = logging.getLogger("flower.controller")


class TimedAction:
    """Energise a relay, then release it after ``duration_s`` (non-blocking)."""

    def __init__(self, relay, duration_s: float) -> None:
        self.relay = relay
        self.duration_s = float(duration_s)
        self._start: float | None = None

    @property
    def active(self) -> bool:
        return self._start is not None

    def trigger(self) -> None:
        self.relay.on()
        self._start = time.monotonic()

    def update(self) -> None:
        if self._start is not None and time.monotonic() - self._start >= self.duration_s:
            self.relay.off()
            self._start = None


class Controller:
    """Compose the rig and run its loop."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.default()
        d = self.config.data_dir
        n = self.config.arduino.n_moisture
        pts = self.config.retention_points

        self.bank = RelayBank.from_config(self.config.relays)
        self.bme = BME280Sensor(address=self.config.bme280.address,
                                enabled=self.config.bme280.enabled)
        self.hub = ArduinoSensorHub(port=self.config.arduino.port,
                                    baud=self.config.arduino.baud,
                                    n_moisture=n, timeout=self.config.arduino.timeout)

        self.moisture = TimeSeriesStore(d / "moisture.json", [str(i) for i in range(n)], pts)
        self.rht = TimeSeriesStore(d / "rht.json",
                                   ["humidity", "temperature", "pressure", "cpu"], pts)
        self.room = TimeSeriesStore(d / "room.json",
                                    ["temperature", "pressure", "humidity"], pts)
        self.settings = SettingsStore(d / "settings.json")

        # timed actions and the relays they own (so direct flags skip them)
        self._timed = {t.key: TimedAction(self.bank[t.relay], t.duration_s)
                       for t in self.config.timed_actions if t.relay in self.bank}
        self._timed_relays = {t.relay for t in self.config.timed_actions}

        self._lock = threading.RLock()   # guards store/relay state (loop vs API)
        self._stop = threading.Event()

    # -- one iteration --------------------------------------------------------
    def step(self) -> dict:
        """Run a single sense/decide/actuate cycle; return a status snapshot."""
        snapshot: dict = {"time": time.time()}

        # Sensor reads are slow (I2C, serial timeouts) -> do them OUTSIDE the
        # lock so API status requests aren't blocked while we poll hardware.
        room = self.bme.read()
        reading = self.hub.read()
        cpu = read_cpu_temperature()

        with self._lock:
            if room:
                self.room.append_many(room)
                snapshot["room"] = room
            if reading:
                for i, val in enumerate(reading.moisture):
                    self.moisture.append(str(i), val)
                if reading.humidity is not None:
                    self.rht.append("humidity", reading.humidity)
                if reading.temperature is not None:
                    self.rht.append("temperature", reading.temperature)
                if reading.pressure is not None:
                    self.rht.append("pressure", reading.pressure)
                snapshot["moisture"] = reading.moisture
                snapshot["rht"] = {"humidity": reading.humidity,
                                   "temperature": reading.temperature,
                                   "pressure": reading.pressure}
            if cpu is not None:
                self.rht.append("cpu", cpu)
                snapshot["cpu"] = cpu

            settings = self.settings.load()
            if settings.get("reset"):
                self.moisture.reset()
                settings["reset"] = False

            self._apply_direct_flags(settings)
            self._apply_auto_heat(settings)
            self._apply_timed_actions(settings)
            snapshot["relays"] = self.bank.state()

            self.settings.write(settings)
            self.moisture.save()
            self.rht.save()
            self.room.save()
        return snapshot

    # -- behaviours -----------------------------------------------------------
    def _apply_direct_flags(self, settings: dict) -> None:
        """``settings[<relay-name>]`` (bool) directly holds that relay."""
        for name in self.bank.names():
            if name in self._timed_relays:
                continue                        # owned by a timed action
            value = settings.get(name)
            if isinstance(value, bool):
                self.bank[name].set(value)

    def _apply_auto_heat(self, settings: dict) -> None:
        threshold = self.config.auto_heat_below_c
        heat = self.bank.get("heat")
        if threshold is None or heat is None:
            return
        temp = self.rht.latest("temperature")
        if temp is None:
            return
        want = temp < threshold
        heat.set(want)
        settings["heat"] = want
        settings["autoheat_status"] = True

    def _apply_timed_actions(self, settings: dict) -> None:
        for key, action in self._timed.items():
            if settings.get(key):
                action.trigger()
                settings[key] = False           # consume the one-shot command
            action.update()

    # -- read/command API (thread-safe; used by flower.server) ----------------
    def apply_settings(self) -> None:
        """Apply the current settings/command flags now (for instant response to
        an API command, without waiting for the next loop step)."""
        with self._lock:
            settings = self.settings.load()
            self._apply_direct_flags(settings)
            self._apply_auto_heat(settings)
            self._apply_timed_actions(settings)
            self.settings.write(settings)

    def snapshot(self) -> dict:
        """Live status: relay states + latest sensor values + settings."""
        with self._lock:
            return {
                "time": time.time(),
                "relays": self.bank.state(),
                "moisture": {c: self.moisture.latest(c) for c in self.moisture.channels},
                "rht": {c: self.rht.latest(c) for c in self.rht.channels},
                "room": {c: self.room.latest(c) for c in self.room.channels},
                "settings": self.settings.load(),
            }

    def timeseries(self, name: str, n: int = 200) -> dict | None:
        """Last ``n`` samples per channel for a store (moisture/rht/room)."""
        store = {"moisture": self.moisture, "rht": self.rht, "room": self.room}.get(name)
        if store is None:
            return None
        with self._lock:
            return {c: (store.data.get(c) or [])[-n:] for c in store.channels}

    # -- lifecycle ------------------------------------------------------------
    def run(self, once: bool = False) -> None:
        """Loop at ``sample_interval_s`` spacing until :meth:`stop` (or once)."""
        interval = self.config.sample_interval_s
        log.info("flower controller starting (interval=%ss, dry-run pins left unassigned)", interval)
        try:
            while not self._stop.is_set():
                self.step()
                if once:
                    return
                self._stop.wait(interval)       # interruptible sleep
        except KeyboardInterrupt:               # pragma: no cover
            log.info("interrupted")
        finally:
            self.shutdown()

    def stop(self) -> None:
        self._stop.set()

    def shutdown(self) -> None:
        """Fail-closed: de-energise everything and release the hardware."""
        self.bank.all_off()
        self.bank.close()
        self.hub.close()
