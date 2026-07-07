"""Unit tests for the domain (vertical) registry.

These pin the framework-generalisation contract: the orchestrator's tools and
dispatch table, and the guardrail's allow-list, all derive from the registry. If
the registry shape drifts, these fail before the pipeline does.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.config import get_settings
from neowatch.domains.registry import (
    REGISTRY,
    all_capabilities,
    capability_map,
    contributions,
    domain_topics,
    orchestrator_tools,
)


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def test_orchestrator_tools_match_the_neo_capabilities() -> None:
    """The advertised tool names are exactly the registered capabilities' names."""
    names = [t["name"] for t in orchestrator_tools()]
    assert names == [
        "fetch_neo_data",
        "analyze_orbits",
        "search_literature",
        "fetch_images",
        "assess_space_weather",
    ]
    # Every tool carries a description and an object input schema (Claude contract).
    for tool in orchestrator_tools():
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_capability_map_keys_and_cache_keys() -> None:
    """Each tool name maps to a capability whose blackboard key synthesis reads."""
    caps = capability_map()
    assert set(caps) == {
        "fetch_neo_data",
        "analyze_orbits",
        "search_literature",
        "fetch_images",
        "assess_space_weather",
    }
    assert caps["fetch_neo_data"].cache_key == "neo_data"
    assert caps["analyze_orbits"].cache_key == "orbital_report"
    assert caps["search_literature"].cache_key == "papers"
    assert caps["fetch_images"].cache_key == "images"
    assert caps["assess_space_weather"].cache_key == "space_weather"


def test_summaries_are_defensive_on_unexpected_data() -> None:
    """A capability's summariser tolerates missing/odd data without raising."""
    caps = capability_map()
    assert "0" in caps["fetch_neo_data"].summarise(None)
    assert "0" in caps["analyze_orbits"].summarise(None)
    assert "0" in caps["search_literature"].summarise(None)
    assert "0" in caps["fetch_images"].summarise(None)


def test_build_agent_constructs_the_right_specialist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each capability's factory builds its concrete agent from settings."""
    from neowatch.agents.calc_agent import CalcAgent
    from neowatch.agents.fetch_agent import FetchAgent
    from neowatch.agents.image_agent import ImageAgent
    from neowatch.agents.rag_agent import RAGAgent

    settings = _settings(monkeypatch)
    caps = capability_map()
    assert isinstance(caps["fetch_neo_data"].build_agent(settings, None), FetchAgent)
    assert isinstance(caps["analyze_orbits"].build_agent(settings, None), CalcAgent)
    assert isinstance(caps["search_literature"].build_agent(settings, None), RAGAgent)
    assert isinstance(caps["fetch_images"].build_agent(settings, None), ImageAgent)
    get_settings.cache_clear()


def test_domain_topics_are_deduped_and_include_neo_terms() -> None:
    """The guardrail allow-list contains the NEO topics, with no duplicates."""
    topics = domain_topics()
    assert "asteroids" in topics
    assert "space weather" in topics
    assert len(topics) == len(set(topics))  # de-duplicated


def test_registry_holds_neo_and_space_weather() -> None:
    """NEO renders bespoke (contribute=None); space weather uses the generic hook."""
    names = {v.name for v in REGISTRY}
    assert names == {"near-earth-objects", "space-weather"}
    assert len(REGISTRY) == 2
    assert len(all_capabilities()) == 5
    # NEO opts out of the generic section path; space weather opts in — so exactly
    # one contribution function is registered (proving the hook is wired, not empty).
    assert len(contributions()) == 1
