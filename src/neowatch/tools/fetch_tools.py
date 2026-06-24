"""Fetch tool callables.

Thin async wrappers the tool dispatcher invokes when Claude requests a fetch
tool: ``get_neo_feed``, ``get_neo_detail``, ``get_space_weather``,
``get_ephemeris``. Each wraps a Phase 2 data client and returns Pydantic models.

Key concept: the model only ever sees a *compact text summary* of each result
(``to_tool_result_text``), which keeps tokens bounded, while the agent keeps the
full typed object internally to assemble its output. Two different consumers,
two different shapes.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..data.donki import get_space_weather
from ..data.horizons import get_ephemeris
from ..data.http import NasaRateLimiter
from ..data.models import EphemerisData, NEODetail, NEOFeedItem, SpaceWeatherReport
from ..data.neows import get_neo_detail, get_neo_feed

# The union of everything a fetch tool can return (always Pydantic, never a dict).
FetchResult = list[NEOFeedItem] | NEODetail | SpaceWeatherReport | EphemerisData


async def dispatch_fetch_tool(
    name: str,
    tool_input: dict[str, Any],
    client: httpx.AsyncClient,
    settings: Settings,
    rate_limiter: NasaRateLimiter | None = None,
) -> FetchResult:
    """Execute the named fetch tool with the model-supplied arguments.

    Raises:
        ValueError: if ``name`` is not a known fetch tool.
    """
    if name == "get_neo_feed":
        return await get_neo_feed(
            client, settings, tool_input["start_date"], tool_input["end_date"], rate_limiter
        )
    if name == "get_neo_detail":
        return await get_neo_detail(client, settings, tool_input["neo_id"], rate_limiter)
    if name == "get_space_weather":
        return await get_space_weather(
            client, settings, tool_input["start_date"], tool_input["end_date"], rate_limiter
        )
    if name == "get_ephemeris":
        return await get_ephemeris(client, tool_input["target"], tool_input["date"])
    raise ValueError(f"unknown fetch tool: {name}")


def to_tool_result_text(result: FetchResult) -> str:
    """Render a fetch result as a short text block for the model's tool_result.

    Deliberately lossy: the model only needs enough to decide its next move, so
    we summarise rather than dump full nested JSON (which would burn tokens).
    """
    if isinstance(result, list):
        lines = [
            f"- {item.name} (id={item.id}): "
            f"{_closest_miss_km(item):,.0f} km miss, "
            f"hazardous={item.is_potentially_hazardous_asteroid}"
            for item in result[:25]
        ]
        return f"{len(result)} near-earth objects found:\n" + "\n".join(lines)
    if isinstance(result, NEODetail):
        return (
            f"Detail for {result.name}: designation={result.designation}, "
            f"hazardous={result.is_potentially_hazardous_asteroid}"
        )
    if isinstance(result, SpaceWeatherReport):
        return (
            f"Space weather {result.start_date}..{result.end_date}: "
            f"{len(result.flares)} flares, {len(result.cmes)} CMEs, {len(result.storms)} storms"
        )
    # EphemerisData
    return (
        f"Ephemeris for {result.target} on {result.date} retrieved "
        f"({len(result.raw_result)} chars)."
    )


def _closest_miss_km(item: NEOFeedItem) -> float:
    """Smallest miss distance (km) across an object's close approaches."""
    return min(
        (ca.miss_distance.kilometers for ca in item.close_approach_data),
        default=float("inf"),
    )
