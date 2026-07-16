"""Persisted shapes for the watch loop: ``WatchSnapshot`` and ``Alert``.

These two Pydantic models are the *only* things that cross the process boundary
onto disk. Keeping them small and explicit is a harness-engineering choice: the
baseline the loop diffs against must be cheap to serialise, stable across
restarts, and decoupled from the full assessment models (a later field addition
to ``SpaceWeatherAssessment`` must not silently change what we persist or diff).

Key concept: a snapshot is *derived* state (recomputed every tick), but it is
still persisted, because the whole point of a watcher is to compare *this* run
against the *previous* run — and the previous run's process is long gone.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class WatchSnapshot(BaseModel):
    """One persisted baseline per watched vertical — the "last known state".

    Attributes:
        vertical: The domain name (e.g. ``"space-weather"``). Also the store key,
            so exactly one snapshot exists per vertical at any time.
        captured_at: ISO-8601 UTC timestamp of when the signal was sensed. Purely
            informational / for audit; the diff never depends on wall-clock time.
        signal: The small JSON-able dict produced by ``WatchSpec.extract`` — the
            handful of fields that alerts are actually decided from. Deliberately
            a plain dict, not the full typed assessment, so persistence stays tiny
            and insulated from unrelated model changes.
        fingerprint: A stable hash over ``signal``. A cheap first-line "did
            anything change at all?" check: equal fingerprints mean the rules can
            be skipped entirely. Computed with :meth:`fingerprint_of` so producer
            and store agree on exactly one canonicalisation.
    """

    vertical: str
    captured_at: str
    signal: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str

    @staticmethod
    def fingerprint_of(signal: dict[str, Any]) -> str:
        """Return a stable SHA-256 hex digest over a signal dict.

        Stability is the whole requirement: the same signal must hash to the same
        string on any machine, any run, any Python hash-seed. We therefore
        serialise with ``sort_keys=True`` and a canonical separator rather than
        relying on dict order or ``hash()`` (which is salted per process).

        Args:
            signal: The extracted, JSON-able watch signal.

        Returns:
            A 64-char hex digest usable as an equality token for the signal.
        """
        canonical = json.dumps(signal, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Alert(BaseModel):
    """One raised alert — the loop's actual output, and an append-only audit row.

    An alert is only ever created by a *rule* observing an edge (a transition
    between the previous signal and the current one), so by construction it
    records both sides of that edge for later inspection.

    Attributes:
        vertical: The domain that raised it (e.g. ``"space-weather"``).
        key: A stable identifier for *this kind* of alert, e.g.
            ``"space-weather:storm-onset"``. Stable across runs so the audit trail
            (and any future cooldown/dedup logic) can group re-occurrences.
        severity: Coarse band — ``info | watch | warning | severe`` — for sink
            filtering and display ordering.
        title: One-line human headline.
        detail: A short human sentence with the concrete numbers.
        raised_at: ISO-8601 UTC timestamp of the tick that raised it.
        previous: The signal values on the *from* side of the edge, or ``None``
            when this is the domain's first-ever sighting.
        current: The signal values on the *to* side of the edge (what is true now).
    """

    vertical: str
    key: str
    severity: str = Field(description="info | watch | warning | severe")
    title: str
    detail: str
    raised_at: str
    previous: dict[str, Any] | None = None
    current: dict[str, Any] = Field(default_factory=dict)
