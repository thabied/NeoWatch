"""Token-budget guardrail (context window).

``TokenBudgetGuardrail.enforce(context)`` compares cumulative tokens against a
per-agent budget and acts at three thresholds:

* **70% — warn:** log that we're approaching the budget, but proceed.
* **85% — compress:** Haiku summarises the older turns; the context keeps the
  summary plus the last few turns, shrinking its footprint.
* **95% — stop:** signal a hard stop so the orchestrator returns partial results
  instead of blowing the budget (and the bill).

Key concept: practical context-window management. LLM context is finite and
priced per token, so we actively prune/summarise rather than letting history grow
unbounded. Compression itself costs a small summary call, but it buys back far
more headroom than it spends — a net win whenever history is long.

Division of labour: this guardrail owns the (paid) Haiku summary call;
:meth:`AgentContext.compress_history` does the pure structural rewrite. That
keeps the LLM dependency out of the data model.
"""

from __future__ import annotations

from typing import Literal

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext
from ..llm import get_anthropic_client

# Thresholds as fractions of the budget.
_WARN_AT = 0.70
_COMPRESS_AT = 0.85
_STOP_AT = 0.95

# Rough bytes-per-token for the cheap local estimate (~4 chars/token for English).
_CHARS_PER_TOKEN = 4

_KEEP_LAST = 3

_SUMMARY_SYSTEM = (
    "Summarise the following conversation turns in 2-3 terse sentences, capturing "
    "key facts, decisions, and any object names. Preserve every number exactly as "
    "written. No preamble."
)

BudgetAction = Literal["ok", "warn", "compressed", "stop"]


class TokenBudgetGuardrail:
    """Watch the token budget and warn / compress / stop as it fills."""

    def __init__(
        self,
        settings: Settings,
        client: AsyncAnthropic | None = None,
        logger: FilteringBoundLogger | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """Initialise the guardrail.

        Args:
            settings: Shared settings (Haiku model id; default budget).
            client: Optional injected Anthropic client (a fake in tests).
            logger: Optional structlog logger.
            max_tokens: Per-agent budget; defaults to
                ``settings.max_tokens_per_agent``.
        """
        self.settings = settings
        self.client = client
        self.logger = logger
        self.max_tokens = max_tokens or settings.max_tokens_per_agent

    def ratio(self, context: AgentContext) -> float:
        """Return tokens used as a fraction of the budget."""
        return context.tokens_used / self.max_tokens

    async def enforce(self, context: AgentContext) -> BudgetAction:
        """Check the budget and take the action for the current threshold.

        Args:
            context: The run context whose ``tokens_used`` is being watched.

        Returns:
            ``"stop"`` at/above 95% (caller should halt with partial results),
            ``"compressed"`` at/above 85% (history was summarised),
            ``"warn"`` at/above 70%, otherwise ``"ok"``.
        """
        ratio = self.ratio(context)
        if ratio >= _STOP_AT:
            self._log("token_budget.hard_stop", context, ratio)
            return "stop"
        if ratio >= _COMPRESS_AT:
            await self._compress(context)
            self._log("token_budget.compressed", context, self.ratio(context))
            return "compressed"
        if ratio >= _WARN_AT:
            self._log("token_budget.warn", context, ratio)
            return "warn"
        return "ok"

    async def _compress(self, context: AgentContext) -> None:
        """Summarise older turns via Haiku, then shrink the context in place."""
        keep_last = _KEEP_LAST
        if len(context.history) <= keep_last:
            return
        old_turns = context.history[:-keep_last]
        transcript = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in old_turns
        )

        client = self.client or get_anthropic_client(self.settings)
        resp = await client.messages.create(
            model=self.settings.haiku_model,
            max_tokens=300,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        if resp.usage is not None:
            context.add_tokens(resp.usage.input_tokens + resp.usage.output_tokens)
        summary = "".join(block.text for block in resp.content if block.type == "text")

        context.compress_history(summary, keep_last=keep_last)
        # Re-baseline the running counter to the compressed footprint: the next
        # model call will carry this smaller history, so this is what now "costs".
        context.tokens_used = _estimate_tokens(context.history)

    def _log(self, event: str, context: AgentContext, ratio: float) -> None:
        if self.logger is not None:
            self.logger.info(
                event,
                tokens_used=context.tokens_used,
                budget=self.max_tokens,
                ratio=round(ratio, 3),
            )


def _estimate_tokens(history: list[dict[str, object]]) -> int:
    """Cheap local token estimate (~4 chars/token) over a history list."""
    chars = sum(len(str(turn.get("content", ""))) for turn in history)
    return chars // _CHARS_PER_TOKEN
