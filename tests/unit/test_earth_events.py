"""Unit tests for the Earth-events vertical.

Covers all four layers it adds, each offline: the deterministic geospatial core
(haversine / point extraction / active filtering / assessment), the EONET client
parser + fetch (httpx ``MockTransport``), the LLM-free agent end-to-end, and the
vertical's pure ``contribute`` hook that assembles the report section.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from neowatch.agents.earth_events_agent import EarthEventsAgent
from neowatch.calc.geo import (
    active_events,
    assess_earth_events,
    event_point,
    haversine_km,
)
from neowatch.calc.models import EarthEventsAssessment
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.data.eonet import get_earth_events, parse_events
from neowatch.data.models import EonetEvent
from neowatch.domains.earth_events import _contribute


def _event(
    event_id: str,
    category: str,
    *,
    coordinates: list[Any],
    geom_type: str = "Point",
    closed: str | None = None,
) -> dict[str, Any]:
    """Build one raw EONET event dict in the live feed's shape."""
    return {
        "id": event_id,
        "title": f"{category} {event_id}",
        "description": None,
        "link": f"https://eonet.gsfc.nasa.gov/api/v3/events/{event_id}",
        "closed": closed,
        "categories": [{"id": category.lower(), "title": category}],
        "geometry": [
            {
                "magnitudeValue": None,
                "magnitudeUnit": None,
                "date": "2026-07-06T17:58:00Z",
                "type": geom_type,
                "coordinates": coordinates,
            }
        ],
    }


# Two wildfires ~335 km apart (Idaho/Nevada) cluster; a volcano in Indonesia and a
# storm polygon in the Atlantic sit alone; one closed wildfire must be filtered.
_EONET_PAYLOAD: dict[str, Any] = {
    "title": "EONET Events",
    "events": [
        _event("A", "Wildfires", coordinates=[-111.96, 43.83]),
        _event("B", "Wildfires", coordinates=[-116.18, 43.63]),
        _event("C", "Volcanoes", coordinates=[105.42, -6.10]),
        _event(
            "D",
            "Severe Storms",
            geom_type="Polygon",
            coordinates=[[[-71.0, 24.0], [-69.0, 24.0], [-69.0, 26.0], [-71.0, 26.0]]],
        ),
        _event("E", "Wildfires", coordinates=[-100.0, 40.0], closed="2026-07-01T00:00:00Z"),
    ],
}


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


# --- deterministic core -------------------------------------------------------


def test_haversine_matches_known_distance() -> None:
    """London->Paris is ~343 km by great circle; identical points are 0."""
    assert haversine_km(51.5074, -0.1278, 51.5074, -0.1278) == 0.0
    assert abs(haversine_km(51.5074, -0.1278, 48.8566, 2.3522) - 343.0) < 5.0


def test_event_point_reads_point_as_lat_lon() -> None:
    """A GeoJSON ``[lon, lat]`` Point is returned swapped as ``(lat, lon)``."""
    event = EonetEvent.model_validate(_event("A", "Wildfires", coordinates=[-111.96, 43.83]))
    assert event_point(event) == (43.83, -111.96)


def test_event_point_uses_first_vertex_of_polygon() -> None:
    """A Polygon collapses to its first vertex (a representative point)."""
    event = EonetEvent.model_validate(
        _event(
            "D",
            "Severe Storms",
            geom_type="Polygon",
            coordinates=[[[-71.0, 24.0], [-69.0, 26.0]]],
        )
    )
    assert event_point(event) == (24.0, -71.0)


def test_event_point_none_without_geometry() -> None:
    """An event with no geometry has no locatable point."""
    event = EonetEvent(id="x", title="t", link="http://e", geometry=[])
    assert event_point(event) is None


def test_active_events_drops_closed() -> None:
    """Only events with a null ``closed`` are active."""
    events = parse_events(_EONET_PAYLOAD)
    active = active_events(events)
    assert {e.id for e in active} == {"A", "B", "C", "D"}  # E is closed


def test_assess_counts_categories_and_finds_hotspot() -> None:
    """The assessment tallies active events by category and locates the cluster."""
    result = assess_earth_events(parse_events(_EONET_PAYLOAD))
    assert isinstance(result, EarthEventsAssessment)
    assert result.total_active == 4
    assert result.categories[0].category == "Wildfires"
    assert result.categories[0].count == 2
    assert result.hotspot is not None
    assert result.hotspot.event_count == 2  # the two nearby wildfires
    assert result.hotspot.dominant_category == "Wildfires"
    assert "active natural event" in result.summary


def test_assess_empty_feed_is_quiet_not_failure() -> None:
    """No events is a valid 'all quiet' assessment, not an error."""
    result = assess_earth_events([])
    assert result.total_active == 0
    assert result.hotspot is None
    assert "No significant" in result.summary


# --- EONET client -------------------------------------------------------------


def test_parse_events_validates_the_events_key() -> None:
    """Raw EONET payload validates onto typed events (all five, closed included)."""
    events = parse_events(_EONET_PAYLOAD)
    assert [e.id for e in events] == ["A", "B", "C", "D", "E"]
    assert events[0].categories[0].title == "Wildfires"


def test_parse_events_tolerates_missing_events_key() -> None:
    """A payload without an ``events`` key yields an empty list, not a raise."""
    assert parse_events({"title": "EONET Events"}) == []


async def test_get_earth_events_offline() -> None:
    """The client fetches and parses the EONET feed into typed events."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_EONET_PAYLOAD))
    )
    async with client:
        report = await get_earth_events(client)
    assert len(report.events) == 5


# --- LLM-free agent -----------------------------------------------------------


async def test_agent_returns_assessment(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end offline: the agent fetches events and returns a typed assessment."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.earth_events_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_EONET_PAYLOAD))
        ),
    )
    result = await EarthEventsAgent(settings).run(AgentContext(query="any wildfires now?"))
    assert result.success is True
    assert isinstance(result.data, EarthEventsAssessment)
    assert result.data.total_active == 4


async def test_agent_reports_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport/HTTP error surfaces as a typed failure, not an exception."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.earth_events_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(500))
        ),
    )
    result = await EarthEventsAgent(settings).run(AgentContext(query="disasters?"))
    assert result.success is False
    assert result.error


async def test_agent_empty_feed_still_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike space weather, an empty feed is success with a zero-count assessment."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.earth_events_agent.get_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"events": []}))
        ),
    )
    result = await EarthEventsAgent(settings).run(AgentContext(query="disasters?"))
    assert result.success is True
    assert result.data.total_active == 0


# --- vertical contribution hook ----------------------------------------------


def test_contribute_builds_section_grounding_and_citation() -> None:
    """With an assessment on the blackboard, ``contribute`` assembles a full block."""
    assessment = assess_earth_events(parse_events(_EONET_PAYLOAD))
    context = AgentContext(query="natural disasters now")
    context.session_cache["earth_events"] = assessment

    contribution = _contribute(context)
    assert contribution is not None
    assert contribution.section is not None
    assert contribution.section.title == "Earth events"
    active_row = next(
        r for r in contribution.section.rows if r["Metric"] == "Active natural events"
    )
    assert active_row["Value"] == "4"
    assert "EARTH EVENTS" in contribution.grounding
    assert len(contribution.citations) == 1
    assert contribution.citations[0].source_type == "nasa_eonet"


def test_contribute_returns_none_when_not_invoked() -> None:
    """A run that never called the Earth-events agent contributes nothing."""
    assert _contribute(AgentContext(query="asteroids this week")) is None
