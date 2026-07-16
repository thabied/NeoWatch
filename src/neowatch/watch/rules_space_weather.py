"""Watch signal + rules for the space-weather vertical.

This is the loop-engineering heart for one domain. The rules are **edge-triggered**:
each fires only on a *transition* between the previous signal and the current one,
which is what makes the tick idempotent — replay the same reading and no edge
exists, so nothing re-fires.

Hysteresis (flap avoidance) comes for free from the **discrete NOAA G-scale**:
Kp is quantised into bands (G0..G5), so small numeric wobble within a band never
changes ``g_scale`` or ``is_storm`` and therefore never flips an alert on and off.

The "first sight" convention: a domain's very first tick has no previous snapshot,
so rules receive ``prev=None``. Onset/surge rules treat ``None`` as "below
threshold", so a storm already raging on first run still alerts exactly once.
"""

from __future__ import annotations

from ..calc.models import SpaceWeatherAssessment
from ..config import Settings
from .models import Alert
from .spec import AlertRule, Signal, utc_now_iso

# NOAA storm bands in ascending order; index gives a comparable severity rank.
_G_ORDER: tuple[str, ...] = ("G0", "G1", "G2", "G3", "G4", "G5")


def _g_index(code: str) -> int:
    """Rank a G-scale code (``"G0"``..``"G5"``); unknown codes rank as 0 (quiet)."""
    return _G_ORDER.index(code) if code in _G_ORDER else 0


def extract(assessment: SpaceWeatherAssessment) -> Signal:
    """Reduce a full space-weather assessment to the fields alerts depend on."""
    return {
        "kp": assessment.kp,
        "g_scale": assessment.g_scale,
        "storm_level": assessment.storm_level,
        "is_storm": assessment.is_storm,
    }


def _was_storm(prev: Signal | None) -> bool:
    """Whether the previous signal was a storm (``None`` = first sight = not storm)."""
    return bool(prev.get("is_storm")) if prev else False


def storm_onset(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when conditions cross *into* a storm at/above the configured G-scale.

    Edge: previous was not a storm (or first sight) -> current is a storm whose
    band is at least ``settings.watch_kp_alert_gscale``. Raising that setting above
    ``G1`` lets an operator ignore minor storms and alert only on stronger ones.
    """
    if _was_storm(prev):
        return None
    if not cur.get("is_storm"):
        return None
    threshold = _g_index(settings.watch_kp_alert_gscale)
    if _g_index(str(cur.get("g_scale", "G0"))) < threshold:
        return None
    return Alert(
        vertical="space-weather",
        key="space-weather:storm-onset",
        severity="warning",
        title="Geomagnetic storm onset",
        detail=(
            f"Geomagnetic storm began: Kp {cur['kp']:.2f} "
            f"({cur['g_scale']}, {cur['storm_level']})."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


def storm_escalation(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when an already-active storm strengthens to a higher G band."""
    if not _was_storm(prev) or not cur.get("is_storm"):
        return None
    prev_rank = _g_index(str(prev.get("g_scale", "G0"))) if prev else 0
    cur_rank = _g_index(str(cur.get("g_scale", "G0")))
    if cur_rank <= prev_rank:
        return None
    severity = "severe" if cur_rank >= _g_index("G4") else "warning"
    return Alert(
        vertical="space-weather",
        key="space-weather:storm-escalation",
        severity=severity,
        title="Geomagnetic storm intensified",
        detail=(
            f"Storm intensified to {cur['g_scale']} ({cur['storm_level']}), "
            f"Kp {cur['kp']:.2f}."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


def storm_cleared(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when a previously-active storm subsides below storm level."""
    if not _was_storm(prev) or cur.get("is_storm"):
        return None
    return Alert(
        vertical="space-weather",
        key="space-weather:storm-cleared",
        severity="info",
        title="Geomagnetic storm cleared",
        detail=f"Geomagnetic storm subsided: Kp {cur['kp']:.2f}, back below storm level.",
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


# The rule set attached to the vertical, in the order they are evaluated.
RULES: tuple[AlertRule, ...] = (storm_onset, storm_escalation, storm_cleared)
