"""Shared agent context.

Defines ``AgentContext`` (the mutable state passed between agents during a run:
the user query, conversation history, token usage, NASA call count, and a
session cache) and ``AgentResult`` (the typed envelope every agent returns).

Key concept: agents communicate through one explicit, typed object instead of
loose globals or bare dicts. This makes the data flow auditable and is where
token-budget tracking and history compression hook in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

# A UI progress hook: agents call it with a short human status string as they
# complete work. Optional everywhere (None = headless), so it never couples the
# pipeline to the front-end.
ProgressCallback = Callable[[str], None]


class AgentResult(BaseModel):
    """The typed envelope every agent returns from ``run()``.

    Attributes:
        agent_name: Which agent produced this result.
        success: Whether the agent completed its task.
        data: The agent's payload (a typed model in later phases).
        error: Human-readable error message when ``success`` is False.
    """

    agent_name: str
    success: bool
    data: Any = None
    error: str | None = None


class AgentContext(BaseModel):
    """Mutable, shared state threaded through a single user query's run.

    Two token counters are tracked deliberately, because they measure two
    different things that an earlier single ``tokens_used`` counter conflated:

    Attributes:
        query: The original user query.
        history: Running list of conversation turns (for the LLM context).
        cost_tokens: Cumulative billed tokens (input + output) across the whole
            session. **Monotonic** — it only ever grows, because you can never
            un-spend money. The budget's hard stop watches this to protect the bill.
        context_tokens: Size of the *current* request context — the number of
            input tokens we last sent. Compression shrinks this (it does not
            shrink ``cost_tokens``), so the compress decision watches it.
        nasa_call_count: NASA API calls made this session (for rate limiting).
        session_cache: In-memory cache keyed by request, to dedupe API calls.
    """

    query: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    cost_tokens: int = 0
    context_tokens: int = 0
    nasa_call_count: int = 0
    session_cache: dict[str, Any] = Field(default_factory=dict)

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Record one model call's usage into the two counters.

        ``cost_tokens`` accumulates input + output (the running bill, monotonic).
        ``context_tokens`` is *set* to just this call's input tokens — the size
        of the conversation we just sent, i.e. the live context-window footprint.
        Keeping them apart is the whole point: compressing history later lowers
        ``context_tokens`` but must never roll back the bill.

        Args:
            input_tokens: Prompt tokens for this call (the current footprint).
            output_tokens: Completion tokens for this call.
        """
        self.cost_tokens += input_tokens + output_tokens
        self.context_tokens = input_tokens

    def compress_history(self, summary: str, keep_last: int = 3) -> int:
        """Replace older turns with a single summary turn, keeping the latest few.

        This is a *pure data operation*: it does not call any model. The summary
        text is produced by the ``TokenBudgetGuardrail`` (which owns the Haiku
        call) and handed in here, so the context model stays free of LLM
        dependencies and is trivial to unit-test.

        Args:
            summary: A short summary of the turns being compressed away.
            keep_last: How many of the most recent turns to retain verbatim.

        Returns:
            The number of turns that were collapsed into the summary (0 if the
            history was already short enough to leave untouched).
        """
        if len(self.history) <= keep_last:
            return 0
        old = self.history[:-keep_last] if keep_last else self.history
        recent = self.history[-keep_last:] if keep_last else []
        summary_turn: dict[str, Any] = {
            "role": "system",
            "content": f"[Summary of {len(old)} earlier turns] {summary}",
        }
        self.history = [summary_turn, *recent]
        return len(old)
