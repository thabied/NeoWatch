"""Unit tests for the space-weather vertical.

Covers all four layers it adds, each offline: the deterministic core
(Kp -> G-scale / aurora latitude), the NOAA client parser + fetch (httpx
``MockTransport``), the LLM-free agent end-to-end, and the vertical's pure
``contribute`` hook that assembles the report section.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from neowatch.agents.space_weather_agent import SpaceWeatherAgent
from neowatch.calc.models import SpaceWeatherAssessment
from neowatch.calc.space_weather import (
    assess_space_weather,
    aurora_view_latitude,
    g_scale,
)
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.data.models import KpReading
from neowatch.data.noaa_swpc import get_planetary_k_index, parse_kp
from neowatch.domains.space_weather import _contribute

# Two rows from the real NOAA product shape (array of objects, oldest first).
_KP_FEED = [
    {"time_tag": "2026-06-30T00:00:00", "Kp": 0.33, "a_running": 2, "station_count": 8},
    {"time_tag": "2026-06-30T15:00:00", "Kp": 5.67, "a_running": 39, "station_count": 8},
]


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


# --- deterministic core -------------------------------------------------------


@pytest.mark.parametrize(
    ("kp", "code", "label"),
    [
        (4.99, "G0", "none"),
        (5.0, "G1", "minor"),
        (6.0, "G2", "moderate"),
        (7.0, "G3", "strong"),
        (8.67, "G4", "severe"),
        (9.0, "G5", "extreme"),
    ],
)
def test_g_scale_bands(kp: float, code: str, label: str) -> None:
    """Kp maps to the NOAA G-scale at the documented integer thresholds."""
    assert g_scale(kp) == (code, label)


@pytest.mark.parametrize(
    ("kp", "latitude"),
    [(0.0, 66.5), (3.0, 60.4), (5.0, 56.3), (9.0, 48.1)],
)
def test_aurora_view_latitude_matches_noaa_table(kp: float, latitude: float) -> None:
    """The linear fit reproduces the classic SWPC aurora view-line table."""
    assert aurora_view_latitude(kp) == latitude


def test_aurora_latitude_clamps_out_of_range_kp() -> None:
    """Kp outside 0-9 is clamped to the scale's defined ends."""
    assert aurora_view_latitude(-1.0) == 66.5
    assert aurora_view_latitude(12.0) == 48.1


def test_assess_storm_reading() -> None:
    """A Kp of 5.67 is a G1 storm; the summary names the storm and aurora line."""
    result = assess_space_weather(KpReading(time_tag="2026-06-30T15:00:00", kp=5.67))
    assert isinstance(result, SpaceWeatherAssessment)
    assert result.g_scale == "G1"
    assert result.storm_level == "minor"
    assert result.is_storm is True
    assert result.aurora_latitude_deg == 54.9
    assert "storm" in result.summary.lower()


def test_assess_quiet_reading() -> None:
    """A low Kp is no storm and the summary says conditions are quiet."""
    result = assess_space_weather(KpReading(time_tag="2026-06-30T00:00:00", kp=0.33))
    assert result.g_scale == "G0"
    assert result.is_storm is False
    assert "quiet" in result.summary.lower()


# --- NOAA client --------------------------------------------------------------


def test_parse_kp_validates_and_aliases() -> None:
    """Raw NOAA rows validate onto typed readings via the ``Kp`` alias."""
    readings = parse_kp(_KP_FEED)
    assert [r.kp for r in readings] == [0.33, 5.67]
    assert readings[0].time_tag == "2026-06-30T00:00:00"


def test_parse_kp_skips_null_values() -> None:
    """Rows without a Kp value are dropped rather than raising."""
    assert parse_kp([{"time_tag": "t", "Kp": None}]) == []


async def test_get_planetary_k_index_offline() -> None:
    """The client fetches, parses, and exposes the most recent reading as ``latest``."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_KP_FEED))
    )
    async with client:
        report = await get_planetary_k_index(client)
    assert len(report.readings) == 2
    assert report.latest is not None
    assert report.latest.kp == 5.67  # newest (last) row


# --- LLM-free agent -----------------------------------------------------------


async def test_agent_returns_assessment(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end offline: the agent fetches Kp and returns a typed assessment."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.space_weather_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_KP_FEED))
        ),
    )
    result = await SpaceWeatherAgent(settings).run(AgentContext(query="aurora tonight?"))
    assert result.success is True
    assert isinstance(result.data, SpaceWeatherAssessment)
    assert result.data.kp == 5.67


async def test_agent_reports_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport/HTTP error surfaces as a typed failure, not an exception."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.space_weather_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(500))
        ),
    )
    result = await SpaceWeatherAgent(settings).run(AgentContext(query="aurora?"))
    assert result.success is False
    assert result.error


async def test_agent_handles_empty_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty NOAA feed is a clean failure (no latest reading to assess)."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.space_weather_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
        ),
    )
    result = await SpaceWeatherAgent(settings).run(AgentContext(query="aurora?"))
    assert result.success is False


# --- vertical contribution hook ----------------------------------------------


def test_contribute_builds_section_grounding_and_citation() -> None:
    """With an assessment on the blackboard, ``contribute`` assembles a full block."""
    assessment = assess_space_weather(KpReading(time_tag="2026-06-30T15:00:00", kp=5.67))
    context = AgentContext(query="space weather now")
    context.session_cache["space_weather"] = assessment

    contribution = _contribute(context)
    assert contribution is not None
    assert contribution.section is not None
    assert contribution.section.title == "Space weather"
    # The Kp row is present and carries the computed value.
    kp_row = next(r for r in contribution.section.rows if r["Metric"] == "Planetary Kp index")
    assert kp_row["Value"] == "5.67"
    # Grounding names the storm scale; one NOAA citation is attached.
    assert "G1" in contribution.grounding
    assert len(contribution.citations) == 1
    assert contribution.citations[0].source_type == "noaa_swpc"


def test_contribute_returns_none_when_not_invoked() -> None:
    """A run that never called the space-weather agent contributes nothing."""
    assert _contribute(AgentContext(query="asteroids this week")) is None
