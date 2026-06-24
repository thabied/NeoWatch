"""Unit tests for the token-budget guardrail (offline).

The Haiku summary call is served by ``FakeAnthropic``, so compression runs with
no paid call. We assert each threshold maps to the right action and that
compression genuinely shrinks the running token count.
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


def _context_with_history(turns: int, tokens_used: int) -> AgentContext:
    history = [
        {"role": "user", "content": f"turn number {i} about asteroids"} for i in range(turns)
    ]
    return AgentContext(query="q", history=history, tokens_used=tokens_used)


async def test_below_warn_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under 70% of budget, no action is taken."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context_with_history(turns=8, tokens_used=50)  # 50%
    assert await guard.enforce(context) == "ok"
    get_settings.cache_clear()


async def test_warn_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Between 70% and 85%, warn but leave history intact."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context_with_history(turns=8, tokens_used=75)  # 75%
    assert await guard.enforce(context) == "warn"
    assert len(context.history) == 8  # untouched
    get_settings.cache_clear()


async def test_compress_threshold_reduces_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """At/above 85%, history is summarised and the token count drops."""
    settings = _settings(monkeypatch)
    guard = TokenBudgetGuardrail(settings, client=_fake_summary(), max_tokens=100)
    context = _context_with_history(turns=8, tokens_used=90)  # 90%

    before = context.tokens_used
    action = await guard.enforce(context)

    assert action == "compressed"
    assert context.tokens_used < before  # the whole point
    assert len(context.history) == 4  # 1 summary + last 3
    assert context.history[0]["role"] == "system"
    assert "Summary of 5 earlier turns" in context.history[0]["content"]
    get_settings.cache_clear()


async def test_hard_stop_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """At/above 95%, signal a hard stop without compressing."""
    settings = _settings(monkeypatch)
    fake = _fake_summary()
    guard = TokenBudgetGuardrail(settings, client=fake, max_tokens=100)
    context = _context_with_history(turns=8, tokens_used=96)  # 96%
    assert await guard.enforce(context) == "stop"
    assert fake.messages.calls == 0  # no summary call on a hard stop
    assert len(context.history) == 8  # untouched
    get_settings.cache_clear()


def test_compress_history_is_pure() -> None:
    """compress_history collapses old turns and keeps the latest, no LLM involved."""
    context = _context_with_history(turns=6, tokens_used=0)
    collapsed = context.compress_history("a summary", keep_last=3)
    assert collapsed == 3
    assert len(context.history) == 4
    assert context.history[0]["content"] == "[Summary of 3 earlier turns] a summary"
    # Short history is left untouched.
    short = _context_with_history(turns=2, tokens_used=0)
    assert short.compress_history("x", keep_last=3) == 0
    assert len(short.history) == 2
