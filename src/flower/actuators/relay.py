"""Relay abstraction with a sane ``on = load energised`` API.

The kit's relay boards are **active-low**: driving the GPIO low energises the
coil. The original scripts exposed that inversion everywhere (``relay.off()``
turned a load *on*), which was a constant foot-gun. Here ``Relay.on()`` always
means "load on" regardless of wiring; the ``active_low`` flag hides the polarity.

An **unassigned pin** (``pin is None``) or a missing ``gpiozero`` degrades to a
**dry run**: the logical state is tracked and logged, but no GPIO is touched.
That is the default until hardware is wired, so the whole controller can run and
be tested on a bare machine.
"""

from __future__ import annotations

import logging
from typing import Iterable, Iterator

log = logging.getLogger("flower.relay")


class Relay:
    """A single relay channel.

    Parameters
    ----------
    name : str
        Logical name (e.g. ``"water_pump"``).
    pin : int | str | None
        BCM number or ``'GPIOxx'``. ``None`` = unassigned → dry run.
    active_low : bool
        True (default) when a LOW GPIO energises the relay.
    description : str
        Human note, carried through to status output.
    """

    def __init__(self, name: str, pin: int | str | None = None,
                 active_low: bool = True, description: str = "") -> None:
        self.name = name
        self.pin = pin
        self.active_low = active_low
        self.description = description
        self._state = False          # False = load off (de-energised)
        self._dev = None             # lazily-acquired gpiozero device
        self._dry = pin is None

    # -- hardware acquisition -------------------------------------------------
    def _device(self):
        """Return the gpiozero device, or None if we are (or must be) dry-run."""
        if self._dry:
            return None
        if self._dev is None:
            try:
                from gpiozero import LED
            except Exception as exc:  # library absent (dev machine) -> dry run
                log.warning("relay %s: gpiozero unavailable (%s); running dry", self.name, exc)
                self._dry = True
                return None
            # Start de-energised: for an active-low board that is a HIGH output.
            self._dev = LED(self.pin, initial_value=self.active_low)
        return self._dev

    # -- control --------------------------------------------------------------
    def on(self) -> None:
        """Energise the relay (turn the load ON)."""
        self._apply(True)

    def off(self) -> None:
        """De-energise the relay (turn the load OFF)."""
        self._apply(False)

    def set(self, energised: bool) -> None:
        self._apply(bool(energised))

    def _apply(self, energised: bool) -> None:
        self._state = energised
        dev = self._device()
        if dev is None:
            log.info("relay %s -> %s (dry-run, pin=%s)", self.name,
                     "ON" if energised else "off", self.pin)
            return
        # active-low: energised load = drive LOW = LED.off()
        if self.active_low:
            dev.off() if energised else dev.on()
        else:
            dev.on() if energised else dev.off()

    @property
    def is_on(self) -> bool:
        return self._state

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Relay(name={self.name!r}, pin={self.pin}, on={self._state})"


class RelayBank:
    """A named collection of :class:`Relay`, built from a config list."""

    def __init__(self, relays: Iterable[Relay]) -> None:
        self._relays: dict[str, Relay] = {r.name: r for r in relays}

    @classmethod
    def from_config(cls, relay_configs) -> "RelayBank":
        return cls(Relay(name=c.name, pin=c.pin, active_low=c.active_low,
                         description=c.description) for c in relay_configs)

    def __getitem__(self, name: str) -> Relay:
        return self._relays[name]

    def __contains__(self, name: str) -> bool:
        return name in self._relays

    def __iter__(self) -> Iterator[Relay]:
        return iter(self._relays.values())

    def get(self, name: str) -> Relay | None:
        return self._relays.get(name)

    def names(self) -> list[str]:
        return list(self._relays)

    def all_off(self) -> None:
        """Safe default: de-energise every relay (fail-closed on shutdown/fault)."""
        for r in self._relays.values():
            r.off()

    def state(self) -> dict[str, bool]:
        return {name: r.is_on for name, r in self._relays.items()}

    def close(self) -> None:
        for r in self._relays.values():
            r.close()

    def __enter__(self) -> "RelayBank":
        return self

    def __exit__(self, *exc) -> None:
        self.all_off()
        self.close()
