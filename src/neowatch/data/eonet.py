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
    client: httpx.AsyncClient, *, status: str = "open", limit: int = 200
) -> EonetEventReport:
    """Fetch active natural events from NASA EONET (keyless).

    ``status="open"`` asks EONET for currently-active events; the deterministic
    core still filters defensively on ``closed`` so it never depends on the query
    parameter being honoured.
    """
    resp = await client.get(_EONET_URL, params={"status": status, "limit": limit})
    resp.raise_for_status()
    return EonetEventReport(events=parse_events(resp.json()))
