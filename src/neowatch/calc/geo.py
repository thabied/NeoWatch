"""Earth-events geospatial calculations.

Deterministic pure functions that turn NASA EONET's raw natural-event feed into a
situational summary: which events are active, how they break down by category, and
— via great-circle (haversine) distance — where activity is most concentrated.
This is the "deterministic core" of the Earth-events vertical, the same discipline
as ``neowatch.calc.orbital`` and ``neowatch.calc.space_weather``: EONET supplies
the geometry, and every derived figure here is computed in plain code the LLM only
narrates, never edits.

Key concept: the vertical takes no user coordinates (the orchestrator dispatch
loop passes tool *arguments* to no agent, and inventing a reference latitude would
put an LLM-produced number into a "deterministic" core). So instead of "events
near <place>", the honest fully-computed product is a *global* summary plus a
hotspot found by comparing the events to each other with haversine — no external
reference point required.
"""

from __future__ import annotations

import math
from collections import Counter

from ..data.models import EonetEvent
from .models import CategoryCount, EarthEventsAssessment, EventHotspot

_EARTH_RADIUS_KM = 6371.0

# Two active events are "in the same hotspot" when within this great-circle
# distance. ~500 km groups, say, the wildfires of one region without merging
# separate continents into one blob.
_HOTSPOT_RADIUS_KM = 500.0

_UNCATEGORIZED = "Uncategorized"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometres.

    Uses the haversine formula on a spherical Earth — accurate to a few tenths of
    a percent, which is far finer than the ``_HOTSPOT_RADIUS_KM`` bucketing needs.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def is_active(event: EonetEvent) -> bool:
    """An event is active while EONET reports no close date (``closed`` is null)."""
    return event.closed is None


def active_events(events: list[EonetEvent]) -> list[EonetEvent]:
    """Keep only the events EONET still considers open."""
    return [event for event in events if is_active(event)]


def event_point(event: EonetEvent) -> tuple[float, float] | None:
    """The event's current representative ``(lat, lon)``, or ``None`` if unlocated.

    EONET geometry is time-ordered, so the *last* entry is the current position of
    a moving event (e.g. a storm). Coordinates are GeoJSON ``[lon, lat]``; for a
    ``Polygon`` we take the first vertex as a representative point rather than a
    true centroid — enough to place the event on the map for hotspot bucketing.
    """
    if not event.geometry:
        return None
    pair = _first_coord_pair(event.geometry[-1].coordinates)
    if pair is None:
        return None
    lon, lat = pair  # GeoJSON order is [lon, lat]; we return (lat, lon)
    return lat, lon


def assess_earth_events(
    events: list[EonetEvent], radius_km: float = _HOTSPOT_RADIUS_KM
) -> EarthEventsAssessment:
    """Summarise the active-event picture: totals, category mix, and a hotspot.

    An *empty* result is legitimate ("no significant active events"), not a
    failure — unlike a missing space-weather reading — so this always returns a
    valid assessment (``total_active`` may be 0).
    """
    active = active_events(events)
    counts = Counter(_primary_category(event) for event in active)
    categories = [CategoryCount(category=name, count=n) for name, n in counts.most_common()]
    hotspot = _densest_hotspot(active, radius_km)
    return EarthEventsAssessment(
        total_active=len(active),
        categories=categories,
        hotspot=hotspot,
        summary=_summarise(len(active), categories, hotspot),
    )


# --- helpers ------------------------------------------------------------------


def _primary_category(event: EonetEvent) -> str:
    """The event's first category title (events usually have exactly one).

    Counting only the primary category keeps the per-category totals summing to
    ``total_active``, rather than double-counting multi-category events.
    """
    return event.categories[0].title if event.categories else _UNCATEGORIZED


def _first_coord_pair(coords: object) -> tuple[float, float] | None:
    """Descend nested GeoJSON coordinate lists to the first ``[number, number]``."""
    if (
        isinstance(coords, (list, tuple))
        and len(coords) >= 2
        and all(isinstance(x, (int, float)) for x in coords[:2])
    ):
        return float(coords[0]), float(coords[1])
    if isinstance(coords, (list, tuple)):
        for item in coords:
            pair = _first_coord_pair(item)
            if pair is not None:
                return pair
    return None


def _densest_hotspot(events: list[EonetEvent], radius_km: float) -> EventHotspot | None:
    """Find the located event with the most active neighbours within ``radius_km``.

    A simple O(n²) sweep: for each located event, count how many active events
    (itself included) lie within the radius, and keep the densest. EONET's active
    feed is a few hundred events at most, so the quadratic pass is trivial.
    """
    located = [(point, _primary_category(e)) for e in events if (point := event_point(e))]
    if not located:
        return None

    best: EventHotspot | None = None
    for (lat, lon), _ in located:
        members = [
            category
            for (plat, plon), category in located
            if haversine_km(lat, lon, plat, plon) <= radius_km
        ]
        if best is None or len(members) > best.event_count:
            dominant = Counter(members).most_common(1)[0][0]
            best = EventHotspot(
                latitude=round(lat, 2),
                longitude=round(lon, 2),
                radius_km=radius_km,
                event_count=len(members),
                dominant_category=dominant,
            )
    return best


def _summarise(
    total: int, categories: list[CategoryCount], hotspot: EventHotspot | None
) -> str:
    """Assemble the one-line plain-English summary (pure Python, no LLM)."""
    if total == 0:
        return "No significant active natural events are currently reported by NASA EONET."

    plural = "s" if total != 1 else ""
    text = f"{total} active natural event{plural} are currently tracked"
    if categories:
        top = categories[0]
        text += f", most commonly {top.category.lower()} ({top.count})"
    text += "."
    if hotspot is not None and hotspot.event_count > 1:
        text += (
            f" Activity is most concentrated near {hotspot.latitude:.1f}, "
            f"{hotspot.longitude:.1f} — {hotspot.event_count} events "
            f"({hotspot.dominant_category.lower()}) within {hotspot.radius_km:.0f} km."
        )
    return text
