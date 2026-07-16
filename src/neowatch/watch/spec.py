"""``WatchSpec`` — how a vertical declares itself watchable.

This is the loop's *policy descriptor*, the watch-loop analogue of the report
``contribute`` hook: a vertical opts into watching by attaching one of these,
and a vertical without one is simply never watched. No second registry, no
framework surgery — the same "declare a Vertical, don't edit the framework"
ethos as the rest of NeoWatch.

A spec has three parts:

- ``extract`` — turn the vertical's full typed assessment into a tiny JSON-able
  *signal* (only the fields alerts are decided from). Keeping the persisted
  snapshot small and decoupled from the assessment model means a later field
  addition can't silently change what we diff.
- ``rules`` — a tuple of **pure** edge-detecting functions. Each looks at the
  previous signal (or ``None`` on first sight) and the current one and returns an
  ``Alert`` when a transition worth flagging occurred, else ``None``. No I/O, so
  each is a table-driven unit test.
- ``cadence_seconds`` — how often this domain is worth re-checking (advisory;
  Phase C decides whether to honour it per-vertical or run one global interval).

Note on the rule signature: rules also receive the run's ``Settings`` so a rule
can read its *policy threshold* (e.g. the Kp G-scale that counts as alertable)
without any module-level import-time coupling to the environment. ``Settings`` is
immutable data, so the rule stays pure and trivially testable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from .models import Alert

# The small JSON-able dict a WatchSpec.extract produces and rules diff over.
Signal = dict[str, Any]

# Turns a vertical's typed assessment into a Signal.
ExtractFn = Callable[[Any], Signal]

# A pure edge-detector: (previous signal | None, current signal, settings) -> Alert | None.
AlertRule = Callable[[Signal | None, Signal, Settings], Alert | None]


def utc_now_iso() -> str:
    """Return the current instant as an ISO-8601 UTC string (shared clock).

    One helper so snapshots' ``captured_at`` and alerts' ``raised_at`` use exactly
    the same timezone-aware format everywhere.
    """
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class WatchSpec:
    """A vertical's declaration of *what* to watch and *how* to decide alerts.

    Attributes:
        extract: Full typed assessment -> tiny JSON-able signal dict.
        rules: Pure edge-detecting rules; each may raise at most one alert.
        cadence_seconds: How often re-checking this domain is worthwhile.
    """

    extract: ExtractFn
    rules: tuple[AlertRule, ...]
    cadence_seconds: int
