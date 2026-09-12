"""Pi CPU temperature, with a pure-Python fallback.

Prefers ``gpiozero.CPUTemperature`` (as the prototype used) but falls back to
reading ``/sys/class/thermal/thermal_zone0/temp`` so it works with no extra
libraries. Returns ``None`` if neither path is available.
"""

from __future__ import annotations

import logging

log = logging.getLogger("flower.cpu")


def read_cpu_temperature() -> float | None:
    """Return the SoC temperature in deg C, or ``None`` if unavailable."""
    try:
        from gpiozero import CPUTemperature
        return float(CPUTemperature().temperature)
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception as exc:
        log.debug("CPU temperature unavailable: %s", exc)
        return None
