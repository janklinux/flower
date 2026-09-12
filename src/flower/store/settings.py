"""Settings / command file — the flag-based control channel.

In the prototype every ``*_on.py`` / ``*_off.py`` script just set a key in
``settings.json`` and the main loop read it back and acted. This keeps that
simple, file-based IPC (any process can drop a command; the controller consumes
it) but makes it atomic and gives it one class instead of a dozen scripts.

The controller reads flags with :meth:`get`; external commands set them with
:meth:`set` (or ``flower set KEY VALUE`` on the CLI). :meth:`reset_to_initial`
restores a known baseline, as the prototype did by copying ``settings_initial``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("flower.settings")


class SettingsStore:
    """Atomic JSON key/value store used as a command channel."""

    def __init__(self, path: str | Path, initial: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.initial = dict(initial or {})
        if not self.path.exists():
            self.write(self.initial)

    # -- io -------------------------------------------------------------------
    def load(self) -> dict[str, Any]:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("settings %s unreadable (%s); using initial", self.path, exc)
            return dict(self.initial)

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # -- convenience ----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.load()
        data[key] = value
        self.write(data)

    def pop(self, key: str, default: Any = None) -> Any:
        """Read and clear a one-shot command flag."""
        data = self.load()
        value = data.pop(key, default)
        self.write(data)
        return value

    def reset_to_initial(self) -> None:
        self.write(dict(self.initial))
