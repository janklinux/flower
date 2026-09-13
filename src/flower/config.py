"""Declarative configuration for a flower rig.

A YAML file fully describes the hardware. **GPIO pins default to ``None`` —
i.e. unassigned** — because nothing is wired to the Pi yet. With the default
config the whole controller runs in dry-run/simulation mode (it logs what it
*would* switch), which is exactly what we want during bring-up. When you wire a
relay, set its ``pin`` in the config; nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Named channels for the 8-relay bank, mapped to their intended plant-rig role.
# Pins are deliberately left unassigned (None) until the hardware is connected.
DEFAULT_RELAYS: list[tuple[str, str]] = [
    ("heat", "heater / heat mat"),
    ("water_pump", "main watering pump"),
    ("fill_valve", "tank fill valve"),
    ("transfer_pump", "reservoir transfer pump"),
    ("plug", "switched mains plug"),
    ("pc_power", "PC power relay"),
    ("steppers", "stepper / CNC power"),
    ("fan", "circulation / exhaust fan"),
]


@dataclass
class RelayConfig:
    """One relay channel. ``pin`` is a BCM number or ``'GPIOxx'`` string;
    ``None`` means unassigned → the channel runs dry (state tracked, no GPIO).
    The relay boards in the kit are active-low, so ``active_low`` defaults True."""

    name: str
    pin: int | str | None = None
    active_low: bool = True
    description: str = ""


@dataclass
class BME280Config:
    """Air temperature / humidity / pressure sensor on I2C."""

    enabled: bool = True
    address: int = 0x76


@dataclass
class ArduinoConfig:
    """Serial sensor hub (Mega/Nano running flower_sensors.ino).

    ``port`` None = not connected. Prefer a stable ``/dev/serial/by-id/...``
    path over ttyACM0/ttyUSB0, which renumber."""

    port: str | None = None
    baud: int = 9600
    n_moisture: int = 5
    timeout: float = 1.0


@dataclass
class TimedActionConfig:
    """A momentary actuation: when ``settings[key]`` is truthy, energise
    ``relay`` for ``duration_s`` then release it (e.g. run a pump for 75 s)."""

    key: str
    relay: str
    duration_s: float


@dataclass
class ApiConfig:
    """HTTP control API (served by ``flower serve`` / ``flower.server``).

    Cleartext on a trusted LAN. ``token`` is the shared bearer token the phone
    app sends; None here means take it from ``FLOWER_API_TOKEN`` or generate a
    throwaway one at serve time."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    token: str | None = None


@dataclass
class Config:
    """Full rig configuration."""

    data_dir: Path = Path("data")
    retention_days: int = 7
    sample_interval_s: float = 10.0
    #: below this air temperature (deg C) the 'heat' relay auto-engages; None disables
    auto_heat_below_c: float | None = None
    bme280: BME280Config = field(default_factory=BME280Config)
    arduino: ArduinoConfig = field(default_factory=ArduinoConfig)
    relays: list[RelayConfig] = field(
        default_factory=lambda: [RelayConfig(name=n, description=d) for n, d in DEFAULT_RELAYS]
    )
    timed_actions: list[TimedActionConfig] = field(default_factory=list)
    api: ApiConfig = field(default_factory=ApiConfig)

    @property
    def retention_points(self) -> int:
        """Number of samples kept = retention_days at sample_interval_s spacing."""
        return int(self.retention_days * 24 * 3600 / max(self.sample_interval_s, 1e-6))

    # -- serialisation --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.data_dir),
            "retention_days": self.retention_days,
            "sample_interval_s": self.sample_interval_s,
            "auto_heat_below_c": self.auto_heat_below_c,
            "bme280": {"enabled": self.bme280.enabled, "address": self.bme280.address},
            "arduino": {
                "port": self.arduino.port,
                "baud": self.arduino.baud,
                "n_moisture": self.arduino.n_moisture,
                "timeout": self.arduino.timeout,
            },
            "relays": [
                {"name": r.name, "pin": r.pin, "active_low": r.active_low,
                 "description": r.description}
                for r in self.relays
            ],
            "timed_actions": [
                {"key": t.key, "relay": t.relay, "duration_s": t.duration_s}
                for t in self.timed_actions
            ],
            "api": {"enabled": self.api.enabled, "host": self.api.host,
                    "port": self.api.port, "token": self.api.token},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Config":
        d = dict(d or {})
        bme = d.get("bme280") or {}
        ard = d.get("arduino") or {}
        return cls(
            data_dir=Path(d.get("data_dir", "data")),
            retention_days=int(d.get("retention_days", 7)),
            sample_interval_s=float(d.get("sample_interval_s", 10.0)),
            auto_heat_below_c=d.get("auto_heat_below_c"),
            bme280=BME280Config(enabled=bool(bme.get("enabled", True)),
                                address=int(bme.get("address", 0x76))),
            arduino=ArduinoConfig(port=ard.get("port"), baud=int(ard.get("baud", 9600)),
                                  n_moisture=int(ard.get("n_moisture", 5)),
                                  timeout=float(ard.get("timeout", 1.0))),
            relays=[RelayConfig(name=r["name"], pin=r.get("pin"),
                                active_low=bool(r.get("active_low", True)),
                                description=r.get("description", ""))
                    for r in (d.get("relays") or [])] or
                   [RelayConfig(name=n, description=desc) for n, desc in DEFAULT_RELAYS],
            timed_actions=[TimedActionConfig(key=t["key"], relay=t["relay"],
                                             duration_s=float(t["duration_s"]))
                           for t in (d.get("timed_actions") or [])],
            api=ApiConfig(enabled=bool((d.get("api") or {}).get("enabled", False)),
                          host=(d.get("api") or {}).get("host", "0.0.0.0"),
                          port=int((d.get("api") or {}).get("port", 8080)),
                          token=(d.get("api") or {}).get("token")),
        )

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with open(path, "r") as f:
            return cls.from_dict(yaml.safe_load(f) or {})

    def save(self, path: str | Path) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)
