"""Unit tests for the watch-loop durability layer (offline — pure filesystem).

These prove the two harness guarantees Phase A exists to provide: snapshots
round-trip, an absent vertical reads back as ``None`` ("first sight"), writes are
atomic (no ``.tmp`` residue, last write wins), and the alert audit is valid JSONL.
"""

from __future__ import annotations

from pathlib import Path

from neowatch.watch.models import Alert, WatchSnapshot
from neowatch.watch.store import WatchStore


def _snapshot(vertical: str = "space-weather", kp: float = 6.0) -> WatchSnapshot:
    signal = {"kp": kp, "g_scale": "G2", "is_storm": True}
    return WatchSnapshot(
        vertical=vertical,
        captured_at="2026-07-16T00:00:00+00:00",
        signal=signal,
        fingerprint=WatchSnapshot.fingerprint_of(signal),
    )


def test_load_absent_vertical_returns_none(tmp_path: Path) -> None:
    """A vertical never seen before reads back as None, not an error."""
    store = WatchStore(tmp_path)
    assert store.load("space-weather") is None


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    """A saved snapshot loads back field-for-field identical."""
    store = WatchStore(tmp_path)
    snap = _snapshot()
    store.save(snap)
    loaded = store.load("space-weather")
    assert loaded == snap


def test_construction_creates_no_directory(tmp_path: Path) -> None:
    """Building a store is side-effect free; the dir appears only on first write."""
    base = tmp_path / "state"
    WatchStore(base)
    assert not base.exists()


def test_save_leaves_no_tmp_and_last_write_wins(tmp_path: Path) -> None:
    """Atomic write: no .tmp residue, and a second save replaces the first."""
    store = WatchStore(tmp_path)
    store.save(_snapshot(kp=5.0))
    store.save(_snapshot(kp=7.0))
    # Exactly one JSON file for the vertical, no leftover temp files anywhere.
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob("space-weather*.json")) == [tmp_path / "space-weather.json"]
    loaded = store.load("space-weather")
    assert loaded is not None
    assert loaded.signal["kp"] == 7.0


def test_fingerprint_is_stable_and_order_independent() -> None:
    """The same signal hashes identically regardless of key insertion order."""
    a = WatchSnapshot.fingerprint_of({"kp": 6.0, "is_storm": True})
    b = WatchSnapshot.fingerprint_of({"is_storm": True, "kp": 6.0})
    assert a == b
    assert a != WatchSnapshot.fingerprint_of({"kp": 7.0, "is_storm": True})


def _alert(key: str) -> Alert:
    return Alert(
        vertical="space-weather",
        key=key,
        severity="warning",
        title="Storm onset",
        detail="Kp reached 6 (G2).",
        raised_at="2026-07-16T00:00:00+00:00",
        previous=None,
        current={"kp": 6.0},
    )


def test_append_alerts_writes_valid_jsonl(tmp_path: Path) -> None:
    """Alerts append as one JSON object per line and read back equal."""
    store = WatchStore(tmp_path)
    written = store.append_alerts([_alert("space-weather:storm-onset")])
    written += store.append_alerts([_alert("space-weather:storm-escalation")])
    assert written == 2
    # Two physical lines, each independently valid JSON.
    lines = store.alerts_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    read_back = store.read_alerts()
    assert [a.key for a in read_back] == [
        "space-weather:storm-onset",
        "space-weather:storm-escalation",
    ]


def test_append_empty_alerts_is_noop(tmp_path: Path) -> None:
    """An empty alert batch writes nothing and creates no audit file."""
    store = WatchStore(tmp_path)
    assert store.append_alerts([]) == 0
    assert not store.alerts_path.exists()
