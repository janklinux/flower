"""Rolling-window JSON time-series store.

Replaces the copy-pasted moisture/rht/room load-trim-dumpfn blocks. Each store
holds several named channels (lists of samples), keeps only the most recent
``max_points`` per channel, and writes **atomically** (temp file + rename) with a
``.save`` backup — so a crash mid-write can't corrupt the live file, which the
prototype's ``dumpfn`` did not guarantee. A corrupt primary file falls back to
the backup, mirroring the original ``_save.json`` recovery.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger("flower.timeseries")


class TimeSeriesStore:
    """A set of named channels persisted to one JSON file."""

    def __init__(self, path: str | Path, channels: Iterable[str], max_points: int) -> None:
        self.path = Path(path)
        self.channels = list(channels)
        self.max_points = int(max_points)
        self.data: dict[str, list] = {c: [] for c in self.channels}
        self.load()

    @property
    def _backup(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".save")

    # -- io -------------------------------------------------------------------
    def load(self) -> None:
        """Load the primary file, falling back to the backup, else start empty."""
        for candidate in (self.path, self._backup):
            if not candidate.is_file():
                continue
            try:
                with open(candidate) as f:
                    loaded = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("time-series %s unreadable (%s)", candidate, exc)
                continue
            for c in self.channels:
                self.data[c] = list(loaded.get(c, []))
            self.trim()
            return
        # no file yet: keep the empty channels initialised in __init__

    def save(self) -> None:
        """Atomically write the current data plus a backup copy."""
        self.trim()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)               # atomic on POSIX
        with open(self._backup, "w") as f:       # best-effort recovery copy
            f.write(payload)

    # -- mutation -------------------------------------------------------------
    def append(self, channel: str, value) -> None:
        self.data.setdefault(channel, []).append(value)

    def append_many(self, values: dict[str, object]) -> None:
        for channel, value in values.items():
            self.append(channel, value)

    def trim(self) -> None:
        for channel, series in self.data.items():
            if len(series) > self.max_points:
                self.data[channel] = series[-self.max_points:]

    def latest(self, channel: str):
        series = self.data.get(channel) or []
        return series[-1] if series else None

    def reset(self) -> None:
        """Clear every channel (the prototype's ``reset`` flag)."""
        for channel in self.data:
            self.data[channel] = []
