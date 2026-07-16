"""Watch signal + rules for the Earth-events vertical.

Same edge-triggered discipline as the space-weather rules: alerts fire on a
*transition*, not while a condition merely holds, so replaying a reading raises
nothing. First cut (per the plan) is two rules — an activity **surge** and a
**new hotspot** — with escalation/category rules deferred.

The threshold-crossing rule (``event_surge``) is the clearest example of why
edge-triggering matters: a level-triggered "there are ≥50 events" would re-fire
every single tick for as long as the surge lasts. Firing only on the upward
crossing means one alert per surge, and the "first sight" convention (``prev``
total treated as 0) still catches a surge already underway on the first run.
"""

from __future__ import annotations

from ..calc.models import EarthEventsAssessment
from ..config import Settings
from .models import Alert
from .spec import AlertRule, Signal, utc_now_iso


def extract(assessment: EarthEventsAssessment) -> Signal:
    """Reduce a full Earth-events assessment to the fields alerts depend on."""
    top_category = assessment.categories[0].category if assessment.categories else None
    return {
        "total_active": assessment.total_active,
        "top_category": top_category,
        "hotspot_present": assessment.hotspot is not None,
        "hotspot_count": assessment.hotspot.event_count if assessment.hotspot else 0,
    }


def event_surge(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when the active-event count crosses the surge threshold *upward*.

    Edge: previous total below ``settings.watch_events_active_threshold`` (or first
    sight, treated as 0) -> current total at/above it. Only the crossing fires, so
    a sustained surge alerts once, not every tick.
    """
    threshold = settings.watch_events_active_threshold
    prev_total = int(prev.get("total_active", 0)) if prev else 0
    cur_total = int(cur.get("total_active", 0))
    if prev_total >= threshold or cur_total < threshold:
        return None
    return Alert(
        vertical="earth-events",
        key="earth-events:surge",
        severity="watch",
        title="Surge in active natural events",
        detail=(
            f"Active natural events rose to {cur_total} "
            f"(crossed the alert threshold of {threshold})."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


def new_hotspot(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when a spatial cluster of events appears where there was none before."""
    prev_present = bool(prev.get("hotspot_present")) if prev else False
    if prev_present or not cur.get("hotspot_present"):
        return None
    return Alert(
        vertical="earth-events",
        key="earth-events:hotspot-onset",
        severity="watch",
        title="New natural-event hotspot",
        detail=(
            f"A new activity cluster formed: {int(cur.get('hotspot_count', 0))} "
            "events concentrated in one region."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


# The rule set attached to the vertical, in the order they are evaluated.
RULES: tuple[AlertRule, ...] = (event_surge, new_hotspot)
