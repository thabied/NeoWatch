"""NOAA SWPC client.

Fetches the planetary K-index (Kp) — the standard global measure of geomagnetic
activity — from NOAA's Space Weather Prediction Center. Unlike the NASA-backed
clients this endpoint is **keyless** and not counted against the NASA rate limit,
so it takes no ``Settings`` and no ``NasaRateLimiter``.

Key concept: validate the untrusted feed once, here at the edge, into typed
:class:`KpReading` objects. The deterministic space-weather core
(``neowatch.calc.space_weather``) then works only with trustworthy numbers.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import retry_external
from .models import KpIndexReport, KpReading

# The 3-hourly planetary K-index product. Returns a JSON array of objects, oldest
# first, each ``{"time_tag", "Kp", "a_running", "station_count"}``.
_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"


def parse_kp(data: list[dict[str, Any]]) -> list[KpReading]:
    """Validate raw NOAA rows into typed readings, skipping any without a Kp value."""
    return [KpReading.model_validate(row) for row in data if row.get("Kp") is not None]


@retry_external
async def get_planetary_k_index(client: httpx.AsyncClient) -> KpIndexReport:
    """Fetch the recent planetary K-index series from NOAA SWPC (keyless)."""
    resp = await client.get(_KP_URL)
    resp.raise_for_status()
    return KpIndexReport(readings=parse_kp(resp.json()))
