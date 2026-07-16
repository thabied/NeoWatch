"""``WatchStore`` — the durable, crash-safe home for watch state.

This is the harness-durability layer. Two guarantees are taught here explicitly,
because they are what let the *mechanism* of the loop be swapped freely (an
in-process sleeper, cron, a cloud routine) without changing its *policy*:

1. **Atomic writes.** A baseline is written to a sibling ``*.tmp`` file and then
   ``os.replace``\\d onto the real path. ``os.replace`` is atomic on POSIX, so a
   crash mid-write can never leave a torn JSON file that corrupts the next diff —
   a reader sees either the whole old file or the whole new one.
2. **A missing baseline is not an error — it's "first sight".** ``load`` returns
   ``None`` for a vertical never seen before, and the rules layer treats that as
   "below threshold" so a condition already active on the very first run still
   alerts exactly once.

Layout on disk (all under ``base_dir``, git-ignored)::

    .watch_state/
      space-weather.json     # one WatchSnapshot per vertical
      earth-events.json
      alerts.jsonl           # append-only audit of every raised Alert
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import Alert, WatchSnapshot

# Verticals are kebab-case today, but we sanitise defensively so a domain name
# can never escape ``base_dir`` or produce an unusable filename.
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

_ALERTS_FILENAME = "alerts.jsonl"


class WatchStore:
    """Load and persist watch snapshots and the alert audit trail.

    One instance points at one ``base_dir``. The directory is created lazily on
    first write, so merely constructing a store (e.g. in a dry run) touches no
    filesystem state.
    """

    def __init__(self, base_dir: str | os.PathLike[str]) -> None:
        """Bind the store to ``base_dir`` (created on first write, not here)."""
        self._base_dir = Path(base_dir)

    # -- paths -----------------------------------------------------------------

    def _snapshot_path(self, vertical: str) -> Path:
        """Return the JSON path for one vertical's snapshot (name sanitised)."""
        safe = _SAFE_NAME.sub("_", vertical).strip("._-") or "unnamed"
        return self._base_dir / f"{safe}.json"

    @property
    def alerts_path(self) -> Path:
        """Path to the append-only ``alerts.jsonl`` audit file."""
        return self._base_dir / _ALERTS_FILENAME

    # -- snapshots -------------------------------------------------------------

    def load(self, vertical: str) -> WatchSnapshot | None:
        """Return the persisted snapshot for ``vertical``, or ``None`` if absent.

        ``None`` is the deliberate "first sight" signal — never an exception — so
        callers uniformly handle "no baseline yet" as part of normal flow.
        """
        path = self._snapshot_path(vertical)
        if not path.exists():
            return None
        return WatchSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, snapshot: WatchSnapshot) -> None:
        """Persist ``snapshot`` atomically (write ``*.tmp`` then ``os.replace``).

        Creating ``base_dir`` is done here, lazily, so construction stays
        side-effect free. The temp file is a *sibling* of the target (same
        directory / filesystem), which is what makes ``os.replace`` a true atomic
        rename rather than a cross-device copy.
        """
        self._base_dir.mkdir(parents=True, exist_ok=True)
        target = self._snapshot_path(snapshot.vertical)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)  # atomic on POSIX: no torn reads

    # -- alert audit -----------------------------------------------------------

    def append_alerts(self, alerts: Iterable[Alert] | Sequence[Alert]) -> int:
        """Append alerts to ``alerts.jsonl`` (one compact JSON object per line).

        JSONL (not one big JSON array) is chosen so the audit is append-only:
        each alert is an independent line, so a crash between writes can at worst
        drop the last line, never corrupt the earlier history. Returns the number
        of lines written (0 for an empty input, without creating the file).
        """
        alerts = list(alerts)
        if not alerts:
            return 0
        self._base_dir.mkdir(parents=True, exist_ok=True)
        with self.alerts_path.open("a", encoding="utf-8") as fh:
            for alert in alerts:
                fh.write(alert.model_dump_json() + "\n")
        return len(alerts)

    def read_alerts(self) -> list[Alert]:
        """Read back every audited alert (convenience for tests / a future UI)."""
        if not self.alerts_path.exists():
            return []
        lines = self.alerts_path.read_text(encoding="utf-8").splitlines()
        return [Alert.model_validate(json.loads(line)) for line in lines if line.strip()]
