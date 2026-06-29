"""Unit tests for FetchAgent.

The Haiku tool-use loop is exercised with a fake Anthropic client (no paid calls)
and a mocked NASA endpoint (httpx ``MockTransport``), so the whole agent runs
offline. The chunking rule is tested directly against ``_assemble``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from neowatch.agents.fetch_agent import FetchAgent, _assemble
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.data.neows import parse_neo_feed

from .fakes import FakeAnthropic, FakeResponse, FakeTextBlock, FakeToolUseBlock

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _feed_fixture() -> dict[str, Any]:
    return json.loads((_FIXTURES / "neows_feed.json").read_text())


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def test_assemble_applies_chunking_rule() -> None:
    """The 10 closest objects are kept (sorted), the rest summed as a remainder."""
    base = parse_neo_feed(_feed_fixture())[0]
    items = []
    for i in range(12):
        item = base.model_copy(deep=True)
        item.id = str(i)
        item.close_approach_data[0].miss_distance.kilometers = float((12 - i) * 1_000_000)
        items.append(item)

    neo = _assemble(items, [], [], None)
    assert len(neo.feed_items) == 10
    assert neo.remainder_count == 2
    # i=11 has the smallest miss distance, so it sorts first.
    assert neo.feed_items[0].id == "11"


async def test_fetch_agent_runs_tool_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Haiku requests get_neo_feed; the agent dispatches it and assembles NEOData."""
    settings = _settings(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if "feed" in request.url.path:
            return httpx.Response(200, json=_feed_fixture())
        return httpx.Response(404)

    monkeypatch.setattr(
        "neowatch.agents.fetch_agent.get_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    fake = FakeAnthropic(
        [
            FakeResponse(
                [
                    FakeToolUseBlock(
                        "get_neo_feed",
                        {"start_date": "2024-01-01", "end_date": "2024-01-02"},
                        "tu1",
                    )
                ],
                "tool_use",
            ),
            FakeResponse([FakeTextBlock("done")], "end_turn"),
        ]
    )

    agent = FetchAgent(settings, client=fake)  # type: ignore[arg-type]
    context = AgentContext(query="asteroids approaching on 2024-01-01")
    result = await agent.run(context)

    assert result.success is True
    neo = result.data
    assert len(neo.feed_items) == 1
    assert neo.feed_items[0].name == "465633 (2009 JR5)"
    # Two model calls (tool_use, then end_turn) were token-counted.
    assert context.cost_tokens == 30
    get_settings.cache_clear()


async def test_fetch_agent_reports_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing tool call is fed back as an error, and the agent still finishes."""
    settings = _settings(monkeypatch)

    monkeypatch.setattr(
        "neowatch.agents.fetch_agent.get_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )

    # An unknown tool name makes the dispatcher raise immediately (no retry/backoff).
    fake = FakeAnthropic(
        [
            FakeResponse([FakeToolUseBlock("bogus_tool", {}, "tu1")], "tool_use"),
            FakeResponse([FakeTextBlock("giving up")], "end_turn"),
        ]
    )

    agent = FetchAgent(settings, client=fake)  # type: ignore[arg-type]
    result = await agent.run(AgentContext(query="x"))
    # The run completes (the error was handled), with no usable feed data.
    assert result.success is True
    assert result.data.feed_items == []
    get_settings.cache_clear()


async def test_fetch_agent_logs_early_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A max_tokens cut-off mid-gather is logged, not swallowed (Tier 3 #5)."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        "neowatch.agents.fetch_agent.get_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )
    # Haiku stops at its 1024-token cap before requesting any tool.
    fake = FakeAnthropic([FakeResponse([], "max_tokens")])

    agent = FetchAgent(settings, client=fake)  # type: ignore[arg-type]
    with structlog.testing.capture_logs() as logs:
        result = await agent.run(AgentContext(query="x"))

    assert result.success is True  # still assembles (empty) data, no crash
    assert any(
        e["event"] == "fetch_agent.early_stop" and e.get("stop_reason") == "max_tokens"
        for e in logs
    )
    get_settings.cache_clear()
