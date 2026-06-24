"""NASA APOD client.

Astronomy Picture of the Day metadata for a single date or a date range.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from .http import NasaRateLimiter, retry_external
from .models import APODImage

_BASE = "https://api.nasa.gov/planetary/apod"


def parse_apod(data: dict[str, Any]) -> APODImage:
    """Parse one APOD record."""
    return APODImage.model_validate(data)


@retry_external
async def get_apod(
    client: httpx.AsyncClient,
    settings: Settings,
    date: str | None = None,
    rate_limiter: NasaRateLimiter | None = None,
) -> APODImage:
    """Fetch APOD for ``date`` (YYYY-MM-DD), or today's if omitted."""
    params: dict[str, str] = {"api_key": settings.nasa_api_key.get_secret_value()}
    if date is not None:
        params["date"] = date
    resp = await client.get(_BASE, params=params)
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    return parse_apod(resp.json())


@retry_external
async def get_apod_range(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[APODImage]:
    """Fetch APOD entries for an inclusive date range (returns a JSON array)."""
    resp = await client.get(
        _BASE,
        params={
            "start_date": start_date,
            "end_date": end_date,
            "api_key": settings.nasa_api_key.get_secret_value(),
        },
    )
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    return [parse_apod(item) for item in resp.json()]
