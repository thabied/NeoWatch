"""Unit tests for the synthesis agent (offline).

Sonnet's prose JSON is served by ``FakeAnthropic``. We assert the assembled
report validates as a ``FinalReport``, that numbers/tables/citations come from
the (deterministic) grounding, and that a wrong figure in the prose is surfaced
in ``confidence_notes`` by the fact-check layer.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from neowatch.agents.models import FinalReport, NEOData
from neowatch.agents.synthesis_agent import SynthesisAgent
from neowatch.calc.models import OrbitalAnalysis, OrbitalReport, RiskAssessment
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.prompts.system_prompts import SYNTHESIS_VERSION
from neowatch.rag.models import RetrievedPaper
from tests.unit.fakes import FakeAnthropic, FakeResponse, FakeTextBlock


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def _orbital() -> OrbitalReport:
    analysis = OrbitalAnalysis(
        object_id="X1",
        name="(2024 X1)",
        miss_distance_km=4_612_800.0,
        miss_distance_ld=12.0,
        miss_distance_au=0.0308,
        velocity_km_s=18.1,
        velocity_class="moderate",
        diameter_min_m=120.0,
        diameter_max_m=480.0,
        is_potentially_hazardous=True,
    )
    risk = RiskAssessment(
        object_id="X1", risk_band="low", risk_score=2, rationale="moderate distance"
    )
    return OrbitalReport(analyses=[analysis], risks=[risk])


def _context(monkeypatch: pytest.MonkeyPatch, event_summary: str) -> AgentContext:
    context = AgentContext(query="Any close asteroids this week?")
    context.session_cache["orbital_report"] = _orbital()
    context.session_cache["neo_data"] = NEOData(remainder_count=3)
    context.session_cache["papers"] = [
        RetrievedPaper(
            arxiv_id="2401.00001",
            title="Detecting small near-Earth asteroids",
            abstract="A method...",
            published="2024-01-01",
            url="https://arxiv.org/abs/2401.00001",
            relevance_score=0.9,
        )
    ]
    return context


def _prose_response(event_summary: str) -> FakeAnthropic:
    payload = {
        "executive_summary": "One object makes a close pass at 12 LD.",
        "literature_insights": "Recent work focuses on detecting small asteroids.",
        "event_summaries": [{"object_id": "X1", "summary": event_summary}],
    }
    return FakeAnthropic([FakeResponse([FakeTextBlock(json.dumps(payload))], "end_turn")])


async def test_synthesis_builds_valid_final_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent assembles a well-formed FinalReport with deterministic numbers."""
    settings = _settings(monkeypatch)
    context = _context(monkeypatch, "Object X1 passes at 12 LD, a routine flyby.")
    agent = SynthesisAgent(settings, client=_prose_response("Object X1 passes at 12 LD."))

    result = await agent.run(context)
    report = result.data

    assert isinstance(report, FinalReport)
    assert report.prompt_version == SYNTHESIS_VERSION
    # Numbers come from the computed grounding, not the prose.
    assert len(report.orbital_risk_table) == 1
    assert report.orbital_risk_table[0].miss_distance_ld == 12.0
    assert report.orbital_risk_table[0].risk_band == "low"
    assert len(report.neo_events) == 1
    assert report.neo_events[0].velocity_km_s == 18.1
    # Citations: NASA (data present) + the one arXiv paper.
    source_types = {c.source_type for c in report.data_sources}
    assert "nasa_neows" in source_types
    assert "arxiv" in source_types
    get_settings.cache_clear()


async def test_wrong_number_surfaces_in_confidence_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fabricated figure in the prose is flagged, not silently kept."""
    settings = _settings(monkeypatch)
    context = _context(monkeypatch, "wrong")
    # The model claims 99 LD; grounding says 12 LD -> must be flagged.
    agent = SynthesisAgent(settings, client=_prose_response("Object X1 races past at 99 LD."))

    result = await agent.run(context)
    report = result.data
    notes = " ".join(report.confidence_notes)

    assert "99 LD" in notes
    assert "caution" in notes.lower()
    # The remainder summary note is also present.
    assert any("further objects" in n for n in report.confidence_notes)
    get_settings.cache_clear()


async def test_malformed_prose_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the model returns non-JSON, the report is still well-formed (empty prose)."""
    settings = _settings(monkeypatch)
    context = _context(monkeypatch, "n/a")
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("sorry, no JSON here")], "end_turn")])
    agent = SynthesisAgent(settings, client=fake)

    result = await agent.run(context)
    report = result.data
    assert isinstance(report, FinalReport)
    assert report.executive_summary == ""  # parse failed -> empty, not a crash
    assert len(report.orbital_risk_table) == 1  # deterministic parts still built
    get_settings.cache_clear()
