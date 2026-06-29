"""Unit tests for the top-level pipeline (offline).

We cover the fully-offline path: a guardrail rejection. ``run_query`` must turn it
into a well-formed ``FinalReport`` (never an exception), so the UI can render the
reason like any other report. The happy path (which dispatches real agents) is
covered by the live ``tests/integration/test_end_to_end.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.agents.models import FinalReport
from neowatch.config import get_settings
from neowatch.pipeline import run_query
from tests.unit.fakes import FakeAnthropic, FakeResponse, FakeTextBlock


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


async def test_run_query_rejection_returns_final_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """An off-topic query yields a valid (empty) FinalReport carrying the reason."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("NO")], "end_turn")])  # domain says NO

    report = await run_query("How do I bake sourdough bread?", settings=settings, client=fake)

    assert isinstance(report, FinalReport)
    assert report.query == "How do I bake sourdough bread?"
    assert "not processed" in report.executive_summary.lower()
    assert report.confidence_notes  # carries the rejection reason
    assert report.neo_events == []
    assert report.orbital_risk_table == []
    get_settings.cache_clear()


async def test_run_query_closes_a_client_it_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no client is injected, run_query builds one and closes it (no leak)."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("NO")], "end_turn")])
    # Force the pipeline's internally-built client to be our fake, so the run
    # stays offline and we can observe close().
    monkeypatch.setattr("neowatch.pipeline.get_anthropic_client", lambda _settings: fake)

    await run_query("How do I bake sourdough bread?", settings=settings)  # no client=

    assert fake.closed is True  # the client it owns was closed
    get_settings.cache_clear()


async def test_run_query_does_not_close_an_injected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected client is the caller's to manage — run_query must not close it."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("NO")], "end_turn")])

    await run_query("How do I bake sourdough bread?", settings=settings, client=fake)

    assert fake.closed is False  # caller owns the lifecycle
    get_settings.cache_clear()
