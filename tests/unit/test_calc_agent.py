"""Unit tests for CalcAgent.

The agent computes figures in pure code and uses a (faked) Haiku only for prose.
The key guarantee, asserted here: the returned numbers equal ``calc/orbital.py``
output exactly — the LLM never touches them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from neowatch.agents.calc_agent import CalcAgent
from neowatch.agents.models import NEOData
from neowatch.calc.orbital import analyse_orbit
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.data.neows import parse_neo_feed

from .fakes import FakeAnthropic, FakeResponse, FakeTextBlock

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


async def test_calc_agent_numbers_match_pure_calc(monkeypatch: pytest.MonkeyPatch) -> None:
    """CalcAgent's analysis equals analyse_orbit() exactly; LLM only adds prose."""
    settings = _settings(monkeypatch)
    feed = parse_neo_feed(json.loads((_FIXTURES / "neows_feed.json").read_text()))
    context = AgentContext(query="risk?", session_cache={"neo_data": NEOData(feed_items=feed)})

    fake = FakeAnthropic([FakeResponse([FakeTextBlock("A short, grounded summary.")], "end_turn")])
    agent = CalcAgent(settings, client=fake)  # type: ignore[arg-type]
    result = await agent.run(context)

    assert result.success is True
    report = result.data

    expected = analyse_orbit(
        object_id="2465633",
        name="465633 (2009 JR5)",
        miss_distance_km=45_285_000.0,
        velocity_km_s=18.1335,
        diameter_min_m=213.8,
        diameter_max_m=478.3,
        is_potentially_hazardous=True,
    )
    assert report.analyses[0] == expected  # exact, field-for-field
    assert report.narrative == "A short, grounded summary."
    assert report.risks[0].risk_band == "low"  # 117 LD, 478 m, PHA -> score 3
    assert context.tokens_used == 15  # one narration call (10 + 5)
    get_settings.cache_clear()


async def test_calc_agent_without_neo_data_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no NEOData in context, the agent returns a typed failure (no LLM call)."""
    settings = _settings(monkeypatch)
    agent = CalcAgent(settings, client=FakeAnthropic([]))  # type: ignore[arg-type]
    result = await agent.run(AgentContext(query="risk?"))
    assert result.success is False
    assert result.error is not None
    get_settings.cache_clear()
