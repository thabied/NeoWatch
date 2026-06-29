"""Unit tests for the orchestrator (offline).

The orchestrator's own Sonnet planning loop and the domain guardrail share one
injected ``FakeAnthropic``; the specialist agents are replaced with stubs that
record whether they ran. So we can assert *which* agents were dispatched without
any real API call.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from neowatch.agents.base import BaseAgent
from neowatch.agents.models import NEOData
from neowatch.agents.orchestrator import OrchestratorAgent
from neowatch.config import get_settings
from neowatch.context import AgentContext, AgentResult
from tests.unit.fakes import FakeAnthropic, FakeResponse, FakeTextBlock, FakeToolUseBlock


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


class StubAgent(BaseAgent):
    """A specialist stand-in that records calls and returns canned data."""

    def __init__(self, settings: Any, name: str, data: Any) -> None:
        super().__init__(settings)
        self._name = name
        self._data = data
        self.calls = 0

    async def run(self, context: AgentContext) -> AgentResult:
        self.calls += 1
        return AgentResult(agent_name=self._name, success=True, data=self._data)


def _stubs(settings: Any) -> dict[str, StubAgent]:
    return {
        "fetch": StubAgent(settings, "FetchAgent", NEOData(remainder_count=0)),
        "calc": StubAgent(settings, "CalcAgent", None),
        "rag": StubAgent(settings, "RAGAgent", []),
        "image": StubAgent(settings, "ImageAgent", []),
    }


async def test_rejects_off_topic_before_any_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-domain query is rejected by the guardrail; no agent and no planner run."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic([FakeResponse([FakeTextBlock("NO")], "end_turn")])  # domain says NO
    stubs = _stubs(settings)
    orch = OrchestratorAgent(
        settings,
        client=fake,
        fetch_agent=stubs["fetch"],
        calc_agent=stubs["calc"],
        rag_agent=stubs["rag"],
        image_agent=stubs["image"],
    )

    result = await orch.run(AgentContext(query="What is the best lasagna recipe?"))

    assert result.success is False
    assert all(stub.calls == 0 for stub in stubs.values())  # nothing dispatched
    assert fake.messages.calls == 1  # only the guardrail classification ran
    get_settings.cache_clear()


async def test_invokes_only_needed_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the plan calls only fetch, the other three specialists stay idle."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic(
        [
            FakeResponse([FakeTextBlock("YES")], "end_turn"),  # domain check
            FakeResponse([FakeToolUseBlock("fetch_neo_data", {}, "t1")], "tool_use"),  # plan
            FakeResponse([FakeTextBlock("Done — fetched data.")], "end_turn"),  # stop
        ]
    )
    stubs = _stubs(settings)
    orch = OrchestratorAgent(
        settings,
        client=fake,
        fetch_agent=stubs["fetch"],
        calc_agent=stubs["calc"],
        rag_agent=stubs["rag"],
        image_agent=stubs["image"],
    )

    context = AgentContext(query="Which asteroids approach Earth this week?")
    result = await orch.run(context)

    assert result.success is True
    assert result.data == ["fetch_neo_data"]
    assert stubs["fetch"].calls == 1
    assert stubs["calc"].calls == 0
    assert stubs["rag"].calls == 0
    assert stubs["image"].calls == 0
    assert isinstance(context.session_cache["neo_data"], NEOData)  # parked for synthesis
    get_settings.cache_clear()


async def test_orchestrator_logs_early_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A planner cut off by max_tokens is logged, not swallowed (Tier 3 #5)."""
    settings = _settings(monkeypatch)
    fake = FakeAnthropic(
        [
            FakeResponse([FakeTextBlock("YES")], "end_turn"),  # domain check passes
            FakeResponse([FakeTextBlock("partial plan")], "max_tokens"),  # planner cut off
        ]
    )
    stubs = _stubs(settings)
    orch = OrchestratorAgent(
        settings,
        client=fake,
        fetch_agent=stubs["fetch"],
        calc_agent=stubs["calc"],
        rag_agent=stubs["rag"],
        image_agent=stubs["image"],
    )

    with structlog.testing.capture_logs() as logs:
        result = await orch.run(AgentContext(query="Which asteroids approach Earth this week?"))

    assert result.success is True
    assert all(stub.calls == 0 for stub in stubs.values())  # cut off before dispatching
    assert any(
        e["event"] == "orchestrator.early_stop" and e.get("stop_reason") == "max_tokens"
        for e in logs
    )
    get_settings.cache_clear()


def test_orchestrator_watches_session_budget_not_per_agent_cap(test_settings: Any) -> None:
    """Regression: the loop budget must be the whole-session total, not 4096.

    A live run showed FetchAgent alone spends ~4.8k tokens, which tripped the
    per-agent cap (4096) and hard-stopped the orchestrator after one agent. The
    guardrail must watch ``token_budget_per_session`` instead.
    """
    orch = OrchestratorAgent(test_settings)
    assert orch.budget.max_tokens == test_settings.token_budget_per_session
    assert test_settings.token_budget_per_session > test_settings.max_tokens_per_agent
