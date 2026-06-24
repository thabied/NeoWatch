"""Shared agent context.

Defines ``AgentContext`` (the mutable state passed between agents during a run:
the user query, conversation history, token usage, NASA call count, and a
session cache) and ``AgentResult`` (the typed envelope every agent returns).

Key concept: agents communicate through one explicit, typed object instead of
loose globals or bare dicts. This makes the data flow auditable and is where
token-budget tracking and history compression hook in.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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

    Attributes:
        query: The original user query.
        history: Running list of conversation turns (for the LLM context).
        tokens_used: Cumulative token count, watched by the budget guardrail.
        nasa_call_count: NASA API calls made this session (for rate limiting).
        session_cache: In-memory cache keyed by request, to dedupe API calls.
    """

    query: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    nasa_call_count: int = 0
    session_cache: dict[str, Any] = Field(default_factory=dict)

    def add_tokens(self, count: int) -> None:
        """Add to the running token total.

        Args:
            count: Number of tokens to add (input + output of a model call).
        """
        self.tokens_used += count

    def compress_history(self) -> None:
        """Summarise older turns to free up context budget.

        Real summarisation (via Haiku) lands in Phase 5 alongside the
        ``TokenBudgetGuardrail``; defined here so the contract exists from the
        start.

        Raises:
            NotImplementedError: Until Phase 5 implements compression.
        """
        raise NotImplementedError("History compression is implemented in Phase 5.")
