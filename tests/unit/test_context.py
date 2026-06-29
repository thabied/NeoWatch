"""Tests for the shared AgentContext / AgentResult models."""

from __future__ import annotations

from neowatch.context import AgentContext, AgentResult


def test_context_defaults() -> None:
    """A fresh context starts empty with zeroed counters."""
    ctx = AgentContext(query="any NEOs this week?")
    assert ctx.query == "any NEOs this week?"
    assert ctx.history == []
    assert ctx.cost_tokens == 0
    assert ctx.context_tokens == 0
    assert ctx.nasa_call_count == 0
    assert ctx.session_cache == {}


def test_add_tokens_splits_cost_and_footprint() -> None:
    """cost_tokens accumulates input+output (monotonic); context_tokens is the
    last call's input only (the live footprint)."""
    ctx = AgentContext(query="x")
    ctx.add_tokens(100, 20)
    ctx.add_tokens(50, 10)
    assert ctx.cost_tokens == 180  # (100+20) + (50+10) — keeps growing
    assert ctx.context_tokens == 50  # just the most recent input, not a sum


def test_compress_history_collapses_old_turns() -> None:
    """compress_history (Phase 5) replaces old turns with a summary, keeping the latest."""
    ctx = AgentContext(
        query="x",
        history=[{"role": "user", "content": f"turn {i}"} for i in range(5)],
    )
    collapsed = ctx.compress_history("a short summary", keep_last=2)
    assert collapsed == 3
    assert len(ctx.history) == 3  # 1 summary + last 2
    assert ctx.history[0]["role"] == "system"
    assert "a short summary" in ctx.history[0]["content"]
    assert ctx.history[-1]["content"] == "turn 4"


def test_agent_result_shape() -> None:
    """AgentResult carries name, success flag, payload, and optional error."""
    ok = AgentResult(agent_name="FetchAgent", success=True, data={"count": 3})
    assert ok.success is True
    assert ok.error is None

    failed = AgentResult(agent_name="FetchAgent", success=False, error="boom")
    assert failed.success is False
    assert failed.data is None
