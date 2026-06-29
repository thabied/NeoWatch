"""Unit tests for the token-budget guardrail (offline).

The Haiku summary call is served by ``FakeAnthropic``, so compression runs with
no paid call. We assert each threshold maps to the right action, that the right
counter drives each decision (cost for warn/stop, footprint for compress), and —
the regression that motivated the two-counter split — that compression lowers the
context footprint **without rolling back the cumulative bill**.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.guardrails.token_budget import TokenBudgetGuardrail
from tests.unit.fakes import FakeAnthropic, FakeResponse, FakeTextBlock


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def _fake_summary() -> FakeAnthropic:
    block = FakeTextBlock("Earlier turns discussed Apophis.")
    return FakeAnthropic([FakeResponse([block], "end_turn")])


def _context(turns: int, cost_tokens: int, context_tokens: int) -> AgentContext:
    history = [
        {"role": "user", "content": f"turn number {i} about asteroids"} for i in range(turns)
    ]
    return AgentContext(
        query="q", history=history, cost_tokens=cost_tokens, context_tokens=context_tokens
    )


async def test_below_warn_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under 70% of cost and 85% of footprint, no action is taken."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context(turns=8, cost_tokens=50, context_tokens=50)  # 50% / 50%
    assert await guard.enforce(context) == "ok"
    get_settings.cache_clear()


async def test_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Between 70% and 95% of cost (footprint still low), warn but leave history intact."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context(turns=8, cost_tokens=75, context_tokens=50)  # cost 75%, footprint 50%
    assert await guard.enforce(context) == "warn"
    assert len(context.history) == 8  # untouched
    get_settings.cache_clear()


async def test_compress_is_driven_by_footprint_not_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """At/above 85% of the *footprint*, history is summarised — even when cost is low."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context(turns=8, cost_tokens=50, context_tokens=90)  # cost 50%, footprint 90%

    action = await guard.enforce(context)

    assert action == "compressed"
    assert len(context.history) == 4  # 1 summary + last 3
    assert context.history[0]["role"] == "system"
    assert "Summary of 5 earlier turns" in context.history[0]["content"]
    get_settings.cache_clear()


async def test_compression_lowers_footprint_not_the_bill(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression behind the two-counter split.

    Compression must shrink ``context_tokens`` (the live footprint) while
    ``cost_tokens`` (the cumulative bill) only ever grows — here by the summary
    call's own usage. The old single counter was re-baselined to the footprint
    estimate on compress, silently un-billing real spend.
    """
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context(turns=8, cost_tokens=50, context_tokens=90)

    assert await guard.enforce(context) == "compressed"

    # Footprint dropped (history was summarised); bill grew by the summary call
    # (FakeUsage = 10 in + 5 out) and was NOT rolled back to the estimate.
    assert context.context_tokens < 90
    assert context.cost_tokens == 65  # 50 + 15, never reset downward
    get_settings.cache_clear()


async def test_hard_stop_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """At/above 95% of cost, signal a hard stop without compressing."""
    settings = _settings(monkeypatch)
    fake = _fake_summary()
    guard = TokenBudgetGuardrail(settings, client=fake, max_tokens=100)
    context = _context(turns=8, cost_tokens=96, context_tokens=90)  # cost 96%
    assert await guard.enforce(context) == "stop"
    assert fake.messages.calls == 0  # no summary call on a hard stop
    assert len(context.history) == 8  # untouched
    get_settings.cache_clear()


def test_compress_history_is_pure() -> None:
    """compress_history collapses old turns and keeps the latest, no LLM involved."""
    context = _context(turns=6, cost_tokens=0, context_tokens=0)
    collapsed = context.compress_history("a summary", keep_last=3)
    assert collapsed == 3
    assert len(context.history) == 4
    assert context.history[0]["content"] == "[Summary of 3 earlier turns] a summary"
    # Short history is left untouched.
    short = _context(turns=2, cost_tokens=0, context_tokens=0)
    assert short.compress_history("x", keep_last=3) == 0
    assert len(short.history) == 2
