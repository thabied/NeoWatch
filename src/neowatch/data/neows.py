"""NASA NeoWs client.

Near-Earth Object Web Service: close approaches by date range (``feed``), a
single object (``neo detail``), and the catalogue (``browse``).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from .http import NasaRateLimiter, retry_external
from .models import NEODetail, NEOFeedItem

_BASE = "https://api.nasa.gov/neo/rest/v1"


# --- Pure parsers (unit-testable, no network) --------------------------------


def parse_neo_feed(data: dict[str, Any]) -> list[NEOFeedItem]:
    """Flatten the date-keyed ``near_earth_objects`` map into a flat list."""
    by_day: dict[str, list[dict[str, Any]]] = data.get("near_earth_objects", {})
    return [NEOFeedItem.model_validate(raw) for day in by_day.values() for raw in day]


def parse_neo_detail(data: dict[str, Any]) -> NEODetail:
    """Parse a single ``/neo/{id}`` response."""
    return NEODetail.model_validate(data)


# --- Network fetchers ---------------------------------------------------------


@retry_external
async def get_neo_feed(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[NEOFeedItem]:
    """Fetch all NEO close approaches between ``start_date`` and ``end_date``."""
    resp = await client.get(
        f"{_BASE}/feed",
        params={
            "start_date": start_date,
            "end_date": end_date,
            "api_key": settings.nasa_api_key.get_secret_value(),
        },
    )
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    return parse_neo_feed(resp.json())


@retry_external
async def get_neo_detail(
    client: httpx.AsyncClient,
    settings: Settings,
    neo_id: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> NEODetail:
    """Fetch one NEO's full record by its reference id."""
    resp = await client.get(
        f"{_BASE}/neo/{neo_id}",
        params={"api_key": settings.nasa_api_key.get_secret_value()},
    )
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    return parse_neo_detail(resp.json())


@retry_external
async def browse(
    client: httpx.AsyncClient,
    settings: Settings,
    page: int = 0,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[NEOFeedItem]:
    """Page through the full NEO catalogue."""
    resp = await client.get(
        f"{_BASE}/neo/browse",
        params={"page": str(page), "api_key": settings.nasa_api_key.get_secret_value()},
    )
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    objects: list[dict[str, Any]] = resp.json().get("near_earth_objects", [])
    return [NEOFeedItem.model_validate(raw) for raw in objects]
