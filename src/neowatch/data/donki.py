"""NASA DONKI client.

Space-weather events that can affect observing conditions: solar flares (FLR),
coronal mass ejections (CME), and geomagnetic storms (GST). Each raw event shape
is normalized onto the common ``SpaceWeatherEvent`` model.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from .http import NasaRateLimiter, retry_external
from .models import SpaceWeatherEvent, SpaceWeatherReport

_BASE = "https://api.nasa.gov/DONKI"


# --- Pure parsers -------------------------------------------------------------


def parse_flares(data: list[dict[str, Any]]) -> list[SpaceWeatherEvent]:
    """Normalize FLR (solar flare) records."""
    return [
        SpaceWeatherEvent(
            event_id=str(e.get("flrID", "")),
            event_type="FLR",
            start_time=str(e.get("beginTime", "")),
            detail=e.get("classType"),
        )
        for e in data
    ]


def parse_cmes(data: list[dict[str, Any]]) -> list[SpaceWeatherEvent]:
    """Normalize CME (coronal mass ejection) records."""
    return [
        SpaceWeatherEvent(
            event_id=str(e.get("activityID", "")),
            event_type="CME",
            start_time=str(e.get("startTime", "")),
            detail=e.get("note"),
        )
        for e in data
    ]


def parse_storms(data: list[dict[str, Any]]) -> list[SpaceWeatherEvent]:
    """Normalize GST (geomagnetic storm) records."""
    return [
        SpaceWeatherEvent(
            event_id=str(e.get("gstID", "")),
            event_type="GST",
            start_time=str(e.get("startTime", "")),
            detail=_max_kp(e.get("allKpIndex", [])),
        )
        for e in data
    ]


def _max_kp(kp_index: list[dict[str, Any]]) -> str | None:
    """Summarize a storm by its strongest Kp reading, if any."""
    values: list[float] = []
    for k in kp_index:
        raw = k.get("kpIndex")
        if raw is not None:
            values.append(float(raw))
    return f"max Kp {max(values)}" if values else None


# --- Network fetchers ---------------------------------------------------------


async def _get_events(
    client: httpx.AsyncClient,
    settings: Settings,
    endpoint: str,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None,
) -> list[dict[str, Any]]:
    resp = await client.get(
        f"{_BASE}/{endpoint}",
        params={
            "startDate": start_date,
            "endDate": end_date,
            "api_key": settings.nasa_api_key.get_secret_value(),
        },
    )
    resp.raise_for_status()
    if rate_limiter is not None:
        rate_limiter.record()
    result: list[dict[str, Any]] = resp.json()
    return result


@retry_external
async def get_flares(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[SpaceWeatherEvent]:
    """Fetch solar flares in the date range."""
    raw = await _get_events(client, settings, "FLR", start_date, end_date, rate_limiter)
    return parse_flares(raw)


@retry_external
async def get_cmes(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[SpaceWeatherEvent]:
    """Fetch coronal mass ejections in the date range."""
    raw = await _get_events(client, settings, "CME", start_date, end_date, rate_limiter)
    return parse_cmes(raw)


@retry_external
async def get_storms(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> list[SpaceWeatherEvent]:
    """Fetch geomagnetic storms in the date range."""
    raw = await _get_events(client, settings, "GST", start_date, end_date, rate_limiter)
    return parse_storms(raw)


async def get_space_weather(
    client: httpx.AsyncClient,
    settings: Settings,
    start_date: str,
    end_date: str,
    rate_limiter: NasaRateLimiter | None = None,
) -> SpaceWeatherReport:
    """Aggregate flares, CMEs, and storms into one report."""
    return SpaceWeatherReport(
        start_date=start_date,
        end_date=end_date,
        flares=await get_flares(client, settings, start_date, end_date, rate_limiter),
        cmes=await get_cmes(client, settings, start_date, end_date, rate_limiter),
        storms=await get_storms(client, settings, start_date, end_date, rate_limiter),
    )
