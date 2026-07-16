"""Alert sinks — pluggable destinations for the alerts a tick produces.

A *sink* is the seam between the loop's deterministic decision (which alerts
fired) and what the outside world does about them. Decoupling them means the same
``tick()`` can log, audit, and (later) send a digest without knowing about any of
those channels — new destinations are added, not wired into the loop.

Phase C ships two: ``LogSink`` (structured log line per alert, always on) and
``JsonlSink`` (append to the durable ``alerts.jsonl`` audit via the store). A
Phase-D LLM digest sink would slot in the same way — and, notably, *downstream*
of the decision, never in it (same anti-hallucination stance as synthesis).

Design note: ``emit`` is synchronous. Both concrete sinks do only cheap local
I/O (a log call, a file append), so async would be ceremony. An async sink (e.g.
an LLM digest) is a Phase-D concern; when one arrives, either widen the protocol
to allow awaitables or run the sync emit in a thread — deferred until needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import structlog
from structlog.typing import FilteringBoundLogger

from .models import Alert
from .store import WatchStore


@runtime_checkable
class AlertSink(Protocol):
    """A destination alerts are routed to. Implementations must be side-effect only."""

    def emit(self, alerts: Sequence[Alert]) -> None:
        """Handle a batch of alerts from one tick (empty batches are allowed)."""
        ...


class LogSink:
    """Emit one structured log line per alert. Always safe, always on."""

    def __init__(self, logger: FilteringBoundLogger | None = None) -> None:
        self._logger: FilteringBoundLogger = logger or structlog.get_logger("neowatch.watch.alert")

    def emit(self, alerts: Sequence[Alert]) -> None:
        """Log each alert at a level matched to its severity."""
        for alert in alerts:
            log = (
                self._logger.warning
                if alert.severity in ("warning", "severe")
                else self._logger.info
            )
            log(
                "watch.alert",
                vertical=alert.vertical,
                key=alert.key,
                severity=alert.severity,
                title=alert.title,
                detail=alert.detail,
            )


class JsonlSink:
    """Append alerts to the durable ``alerts.jsonl`` audit trail via the store."""

    def __init__(self, store: WatchStore) -> None:
        self._store = store

    def emit(self, alerts: Sequence[Alert]) -> None:
        """Persist the batch (a no-op for an empty batch — no file is created)."""
        self._store.append_alerts(alerts)
