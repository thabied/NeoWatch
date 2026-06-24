"""Minimal end-to-end smoke test (offline).

Unlike ``test_end_to_end.py`` (live, gated), this proves the whole stack is wired
and importable without any API key: it drives ``run_query`` down the guardrail
rejection path with a ``FakeAnthropic``, then renders the resulting report through
the UI renderers. If imports or wiring break, this fails fast and cheaply.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.agents.models import FinalReport
from neowatch.config import get_settings
from neowatch.pipeline import run_query
from neowatch.ui.render import gallery_items, report_to_markdown, risk_table_dataframe
from tests.unit.fakes import FakeAnthropic, FakeResponse, FakeTextBlock


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


async def test_query_to_render_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_query -> FinalReport -> renderers all execute end to end, offline."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("NO")], "end_turn")])  # off-topic

    report = await run_query("best tacos in town?", settings=settings, client=fake)
    assert isinstance(report, FinalReport)

    # The renderers must accept a real pipeline output without error.
    markdown = report_to_markdown(report)
    table = risk_table_dataframe(report)
    gallery = gallery_items(report)

    assert "best tacos in town?" in markdown
    assert list(table.columns) == ["Object", "Miss (LD)", "Velocity (km/s)", "Max size (m)", "Risk"]
    assert gallery == []
    get_settings.cache_clear()
