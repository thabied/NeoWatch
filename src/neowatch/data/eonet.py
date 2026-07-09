"""NASA EONET client.

Fetches currently-active natural events (wildfires, severe storms, volcanoes,
floods…) from NASA's Earth Observatory Natural Event Tracker. Like the NOAA SWPC
client this endpoint is **keyless** and not counted against the NASA rate limit,
so it takes no ``Settings`` and no ``NasaRateLimiter``.

Key concept: validate the untrusted feed once, here at the edge, into typed
:class:`EonetEvent` objects. The events live under a top-level ``events`` key and
each carries GeoJSON ``geometry``; the deterministic core (``neowatch.calc.geo``)
then works only with trustworthy typed objects.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import retry_external
from .models import EonetEvent, EonetEventReport

_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


def parse_events(payload: dict[str, Any]) -> list[EonetEvent]:
    """Validate the raw EONET payload's ``events`` list into typed events."""
    raw = payload.get("events", []) if isinstance(payload, dict) else []
    return [EonetEvent.model_validate(event) for event in raw]


@retry_external
async def get_earth_events(
    client: httpx.AsyncClient, *, status: str = "open", days: int = 30, limit: int = 1000
) -> EonetEventReport:
    """Fetch *recently-active* natural events from NASA EONET (keyless).

    ``days`` is the important, semantic filter. EONET leaves an event "open" until
    a source explicitly closes it, so ``status=open`` alone returns thousands of
    stale events (a wildfire logged a year ago and never closed still counts). We
    want the *current* picture, so ``days=30`` keeps only events with activity in
    the last 30 days — a defensible definition of "happening now".

    ``limit`` is only a safety guard against a pathological spike (it sits well
    above the ~day-30 count so it never silently truncates and biases the counts /
    hotspot). Ordering matters here: EONET returns newest-first, so a *too-small*
    limit would keep only the most recent slice — which is exactly the bug this
    replaced. The core still filters defensively on ``closed`` regardless.
    """
    resp = await client.get(
        _EONET_URL, params={"status": status, "days": days, "limit": limit}
    )
    resp.raise_for_status()
    return EonetEventReport(events=parse_events(resp.json()))
