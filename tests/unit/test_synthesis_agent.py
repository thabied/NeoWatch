"""Unit tests for the synthesis agent (offline).

Sonnet's prose is served by ``FakeAnthropic`` as a schema-validated
``ProseModel`` on ``parsed_output`` — mirroring the real SDK's structured-output
``messages.parse``. We assert the assembled report validates as a ``FinalReport``,
that numbers/tables/citations come from the (deterministic) grounding, and that a
wrong figure in the prose is surfaced in ``confidence_notes`` by the fact-check
layer.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.agents.models import FinalReport, NEOData
from neowatch.agents.synthesis_agent import EventSummary, ProseModel, SynthesisAgent
from neowatch.calc.models import OrbitalAnalysis, OrbitalReport, RiskAssessment
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.prompts.system_prompts import SYNTHESIS_VERSION
from neowatch.rag.models import RetrievedPaper
from tests.unit.fakes import FakeAnthropic, FakeResponse


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
    parsed = ProseModel(
        executive_summary="One object makes a close pass at 12 LD.",
        literature_insights="Recent work focuses on detecting small asteroids.",
        event_summaries=[EventSummary(object_id="X1", summary=event_summary)],
    )
    return FakeAnthropic([FakeResponse([], "end_turn", parsed_output=parsed)])


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


async def test_missing_parsed_output_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal/truncation (no parsed object) degrades to empty prose, not a crash."""
    settings = _settings(monkeypatch)
    context = _context(monkeypatch, "n/a")
    # parsed_output=None mimics the API returning no validated object (refusal or
    # max_tokens cut-off mid-generation).
    fake = FakeAnthropic([FakeResponse([], "refusal", parsed_output=None)])
    agent = SynthesisAgent(settings, client=fake)

    result = await agent.run(context)
    report = result.data
    assert isinstance(report, FinalReport)
    assert report.executive_summary == ""  # no parsed object -> empty, not a crash
    assert len(report.orbital_risk_table) == 1  # deterministic parts still built
    get_settings.cache_clear()


async def test_brace_laden_prose_yields_populated_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prose full of literal braces — which broke the old greedy ``\\{.*\\}`` regex —
    now flows through structured outputs into a populated report.

    The previous ``_parse_prose`` searched the raw text for ``\\{.*\\}`` (greedy,
    DOTALL). A model reply like ``Sure: {...} hope that helps {note}`` made the
    regex over-match, ``json.loads`` failed, and the report came back silently
    empty. With ``messages.parse`` the validated object is returned directly, so
    braces in the prose are just text and are preserved verbatim.
    """
    settings = _settings(monkeypatch)
    context = _context(monkeypatch, "n/a")
    parsed = ProseModel(
        executive_summary="Risk set {Torino 0}; see paper {2401.00001} for context.",
        literature_insights="Methods weigh detection {recall vs. precision}.",
        event_summaries=[EventSummary(object_id="X1", summary="A routine flyby {low risk}.")],
    )
    agent = SynthesisAgent(
        settings, client=FakeAnthropic([FakeResponse([], "end_turn", parsed_output=parsed)])
    )

    result = await agent.run(context)
    report = result.data

    assert isinstance(report, FinalReport)
    # Brace-laden prose preserved exactly — no over-match, no empty report.
    assert report.executive_summary == "Risk set {Torino 0}; see paper {2401.00001} for context."
    assert report.neo_events[0].summary == "A routine flyby {low risk}."
    assert "{recall vs. precision}" in report.literature_insights
    get_settings.cache_clear()
