"""Watch sense + signal + rules for the near-Earth-object vertical.

Unlike the two keyless verticals, NEO's *report* path is an LLM-driven
``FetchAgent -> CalcAgent`` chain. The watcher does not want that: an unattended
loop should be **deterministic and cheap**, and — crucially — it should sense the
*same* set of objects run-to-run so the diff is meaningful. So this module
supplies a bespoke :data:`~neowatch.watch.spec.SenseFn` that talks to the NASA
feed client and the pure calc cores directly, with **no model call** anywhere.
That is the "second consumer of the deterministic core" idea taken to its
conclusion: :func:`neo_sense` reuses the exact ``analyse_feed_item`` /
``assess_risk`` functions the report pipeline uses, minus the narration.

**The moving-window trap (the NEO-specific loop lesson).** We scan a rolling
"today .. today + N days" window, so as real time advances the window slides:
objects naturally enter at the far edge and fall off the near edge every day.
A naive "alert on every object in the feed" would therefore flap constantly on
window mechanics, not on anything astronomical. The rules below are written to be
*window-robust* by being **selective** and **edge-triggered**:

- :func:`notable_appeared` fires only for objects that are newly present *and*
  notable — an **elevated or high computed risk band**. Note it keys on the risk
  band, *not* the raw "potentially hazardous" (PHA) flag: PHA is a permanent
  orbital *designation*, so the same catalog PHAs slide in and out of the window
  every day (and "new to the window" is not "newly discovered"), which would make
  a PHA trigger recurringly noisy even for objects passing at 80+ LD. The risk
  band already folds the PHA flag together with *this pass's* distance and size,
  so it fires on things that are actually concerning now, not routine churn.
- :func:`closest_tightened` fires when the single nearest approach in the whole
  feed crosses *inside* the ``watch_neo_close_ld`` threshold, and not again while
  it stays inside — hysteresis from the discrete threshold, exactly as the
  space-weather rules get it free from the discrete G-scale bands.

Both treat ``prev=None`` (first sight) as "below threshold / empty set", so an
object already close or already hazardous on the very first run still alerts once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..calc.models import OrbitalAnalysis, OrbitalReport, RiskAssessment
from ..calc.orbital import analyse_feed_item, assess_risk
from ..config import Settings
from ..data.http import get_async_client
from ..data.neows import get_neo_feed
from .models import Alert
from .spec import AlertRule, Signal, utc_now_iso

# Risk bands that count as "notable" on their own (independently of the PHA flag).
_NOTABLE_RISK: frozenset[str] = frozenset({"elevated", "high"})


async def neo_sense(settings: Settings) -> OrbitalReport:
    """Deterministically sense current close approaches — no LLM, NASA feed only.

    Scans the ``watch_neo_horizon_days``-day window from today, then runs the pure
    calc cores over every returned object. Returns an ``OrbitalReport`` with an
    empty ``narrative`` (the watcher never needs prose), so the whole sense is
    reproducible and free of model cost.

    Requires ``NASA_API_KEY``; if it is missing or the fetch fails, the exception
    propagates and the runner's per-vertical isolation skips NEO for this tick
    without touching its baseline or the other domains.
    """
    today = datetime.now(UTC).date()
    horizon = max(1, settings.watch_neo_horizon_days)
    start = today.isoformat()
    end = (today + timedelta(days=horizon - 1)).isoformat()

    async with get_async_client() as http:
        feed = await get_neo_feed(http, settings, start, end)

    analyses: list[OrbitalAnalysis] = []
    risks: list[RiskAssessment] = []
    for item in feed:
        analysis = analyse_feed_item(item)
        if analysis is None:  # no approach data on this item — skip it
            continue
        analyses.append(analysis)
        risks.append(
            assess_risk(
                analysis.object_id,
                analysis.miss_distance_ld,
                analysis.diameter_max_m,
                analysis.is_potentially_hazardous,
            )
        )
    return OrbitalReport(analyses=analyses, risks=risks)


def neo_extract(report: OrbitalReport) -> Signal:
    """Reduce an ``OrbitalReport`` to the small signal the NEO rules diff over.

    The signal is keyed by object id so set-diffing "which objects are new" is a
    plain dict-key comparison. Miss distances are rounded to milli-LD so that
    imperceptible float wobble can never change the fingerprint or flip a rule.
    """
    risk_by_id = {r.object_id: r.risk_band for r in report.risks}
    objects: dict[str, Any] = {}
    closest_ld: float | None = None
    closest_id: str | None = None
    for a in report.analyses:
        miss_ld = round(a.miss_distance_ld, 3)
        objects[a.object_id] = {
            "name": a.name,
            "miss_ld": miss_ld,
            "risk": risk_by_id.get(a.object_id, "negligible"),
            "pha": a.is_potentially_hazardous,
        }
        if closest_ld is None or miss_ld < closest_ld:
            closest_ld = miss_ld
            closest_id = a.object_id
    return {
        "objects": objects,
        "count": len(objects),
        "closest_ld": closest_ld,
        "closest_id": closest_id,
    }


def _is_notable(obj: dict[str, Any]) -> bool:
    """Whether one signal object warrants an appearance alert.

    Keys on the *computed risk band*, which already integrates the PHA flag with
    this pass's distance and size — deliberately not the raw PHA flag alone, which
    would fire on distant catalog PHAs merely re-entering the sliding window.
    """
    return str(obj.get("risk")) in _NOTABLE_RISK


def notable_appeared(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when a *notable* object is present now that was not present before.

    "Present before" is judged by object id, so an object merely shifting its
    miss distance within the window does not re-trigger — only a genuinely new
    entrant does. Non-notable newcomers (negligible/low risk band) are ignored so
    routine window churn stays quiet. One alert summarises the whole batch,
    headlined by the closest newcomer, rather than spamming one alert per object.
    """
    prev_ids = set(prev.get("objects", {})) if prev else set()
    cur_objects: dict[str, Any] = cur.get("objects", {})
    newly = {
        oid: obj
        for oid, obj in cur_objects.items()
        if oid not in prev_ids and _is_notable(obj)
    }
    if not newly:
        return None

    standout_id = min(newly, key=lambda oid: newly[oid]["miss_ld"])
    standout = newly[standout_id]
    severity = "severe" if any(o.get("risk") == "high" for o in newly.values()) else "warning"
    plural = "s" if len(newly) > 1 else ""
    return Alert(
        vertical="near-earth-objects",
        key="near-earth-objects:notable-appeared",
        severity=severity,
        title="Notable near-Earth object approaching",
        detail=(
            f"{len(newly)} notable near-Earth object{plural} entered the "
            f"{settings.watch_neo_horizon_days}-day window; closest is "
            f"{standout['name']} at {standout['miss_ld']:.3f} LD "
            f"(risk {standout['risk']}, PHA={standout['pha']})."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


def closest_tightened(prev: Signal | None, cur: Signal, settings: Settings) -> Alert | None:
    """Fire when the nearest approach crosses *inside* the close-distance threshold.

    Edge: previously the nearest approach was beyond ``watch_neo_close_ld`` (or
    first sight) -> now it is at/within it. While the sky's nearest object stays
    inside the threshold the rule does not re-fire (hysteresis from the discrete
    threshold), and it stays quiet whenever nothing is that close.
    """
    threshold = settings.watch_neo_close_ld
    cur_closest = cur.get("closest_ld")
    if cur_closest is None or cur_closest > threshold:
        return None
    prev_closest = prev.get("closest_ld") if prev else None
    if prev_closest is not None and prev_closest <= threshold:
        return None  # already inside last tick — edge already reported

    closest_id = cur.get("closest_id")
    objects: dict[str, Any] = cur.get("objects", {})
    name = objects.get(closest_id, {}).get("name", closest_id) if closest_id else "an object"
    return Alert(
        vertical="near-earth-objects",
        key="near-earth-objects:close-approach",
        severity="warning",
        title="Close approach inside threshold",
        detail=(
            f"Nearest close approach is now within {threshold:.2f} LD: "
            f"{name} at {cur_closest:.3f} LD."
        ),
        raised_at=utc_now_iso(),
        previous=prev,
        current=cur,
    )


# Evaluated in order; each may raise at most one alert per tick.
RULES: tuple[AlertRule, ...] = (notable_appeared, closest_tightened)
