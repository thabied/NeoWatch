"""Unit tests for the alert sinks (offline: structlog capture + tmp_path store)."""

from __future__ import annotations

from pathlib import Path

import structlog

from neowatch.watch.models import Alert
from neowatch.watch.sinks import AlertSink, JsonlSink, LogSink
from neowatch.watch.store import WatchStore


def _alert(key: str, severity: str = "warning") -> Alert:
    return Alert(
        vertical="space-weather",
        key=key,
        severity=severity,
        title="Geomagnetic storm onset",
        detail="Kp reached 6.0 (G2).",
        raised_at="2026-07-16T00:00:00+00:00",
        current={"kp": 6.0},
    )


def test_concrete_sinks_satisfy_the_protocol(tmp_path: Path) -> None:
    """LogSink and JsonlSink are structural AlertSinks (runtime_checkable)."""
    assert isinstance(LogSink(), AlertSink)
    assert isinstance(JsonlSink(WatchStore(tmp_path)), AlertSink)


def test_log_sink_emits_one_event_per_alert() -> None:
    """LogSink logs each alert; severity picks the log level."""
    with structlog.testing.capture_logs() as logs:
        LogSink().emit([_alert("space-weather:storm-onset"), _alert("x", severity="info")])
    events = [e for e in logs if e["event"] == "watch.alert"]
    assert len(events) == 2
    assert events[0]["log_level"] == "warning"  # severe/warning -> warning
    assert events[1]["log_level"] == "info"  # anything else -> info


def test_jsonl_sink_appends_to_audit(tmp_path: Path) -> None:
    """JsonlSink persists the batch through the store's append-only audit."""
    store = WatchStore(tmp_path)
    JsonlSink(store).emit([_alert("space-weather:storm-onset")])
    JsonlSink(store).emit([_alert("space-weather:storm-cleared", severity="info")])
    keys = [a.key for a in store.read_alerts()]
    assert keys == ["space-weather:storm-onset", "space-weather:storm-cleared"]


def test_jsonl_sink_empty_batch_writes_nothing(tmp_path: Path) -> None:
    """An empty batch is a no-op — no audit file is created."""
    store = WatchStore(tmp_path)
    JsonlSink(store).emit([])
    assert not store.alerts_path.exists()
