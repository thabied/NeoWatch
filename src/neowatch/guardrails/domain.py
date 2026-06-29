"""Domain guardrail (input).

``DomainGuardrail.validate(query)`` runs before any pipeline work and applies
four checks, cheapest first:

1. **Length** (10-500 chars) — pure Python, no cost.
2. **Injection** — deterministic regex (:mod:`sanitise`), no cost.
3. **Harm** — deterministic keyword screen, no cost.
4. **Domain** — a single Haiku YES/NO classification, the only paid call.

Key concept: *fail fast and cheap*. The three free checks gate the one paid
check, and the whole guardrail gates the expensive multi-agent pipeline. An
off-topic or malicious query is rejected for a fraction of a cent (or for free).
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext
from ..llm import get_anthropic_client
from .models import GuardrailResult
from .sanitise import detect_injection

_MIN_LEN = 10
_MAX_LEN = 500

# Deterministic harm screen. A teaching heuristic, not a full safety classifier:
# it catches a few obviously-malicious intents (including the domain-specific one
# of weaponising an asteroid's trajectory) before the query reaches any model.
_HARM_PATTERNS: tuple[str, ...] = (
    "build a bomb",
    "make a weapon",
    "how to kill",
    "redirect an asteroid",
    "steer an asteroid",
    "aim an asteroid",
    "deorbit on",
)

_DOMAIN_SYSTEM = (
    "You are a strict topic classifier for a near-Earth-object research tool. "
    "Answer with exactly one word, YES or NO, and nothing else. "
    "Answer YES only if the message is about asteroids, comets, near-Earth "
    "objects, meteors, space weather, orbital mechanics, planetary defence, or "
    "closely related space science. Answer NO for everything else (recipes, "
    "coding help, politics, general chit-chat, etc.)."
)


class DomainGuardrail:
    """Validate a user query before the pipeline spends money on it."""

    def __init__(
        self,
        settings: Settings,
        client: AsyncAnthropic | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        """Initialise the guardrail.

        Args:
            settings: Shared settings (for the Haiku model id / API key).
            client: Optional injected Anthropic client (a fake in tests).
            logger: Optional structlog logger.
        """
        self.settings = settings
        self.client = client
        self.logger = logger

    async def validate(
        self, query: str, context: AgentContext | None = None
    ) -> GuardrailResult:
        """Run the four checks; the first failure short-circuits the rest.

        Args:
            query: The raw user input.
            context: Optional run context; if given, tokens spent on the domain
                classification are recorded against its budget.

        Returns:
            A :class:`GuardrailResult`; ``allowed`` is False on the first failed
            check, with a user-facing ``reason``.
        """
        stripped = query.strip()

        # 1. Length — reject empty/trivial and abusively long inputs.
        if len(stripped) < _MIN_LEN:
            return GuardrailResult(allowed=False, reason="Query is too short to act on.")
        if len(stripped) > _MAX_LEN:
            return GuardrailResult(
                allowed=False, reason=f"Query exceeds the {_MAX_LEN}-character limit."
            )

        # 2. Injection — deterministic, runs before the model sees the text.
        if detect_injection(query):
            return GuardrailResult(
                allowed=False, reason="Query looks like a prompt-injection attempt."
            )

        # 3. Harm — deterministic keyword screen.
        lowered = stripped.lower()
        if any(phrase in lowered for phrase in _HARM_PATTERNS):
            return GuardrailResult(
                allowed=False, reason="Query requests potentially harmful information."
            )

        # 4. Domain — the only paid check, gated behind the three free ones.
        if not await self._in_domain(query, context):
            return GuardrailResult(
                allowed=False,
                reason="Query is outside this tool's domain (near-Earth-object science).",
            )

        return GuardrailResult(allowed=True, reason="ok")

    async def _in_domain(self, query: str, context: AgentContext | None) -> bool:
        """Ask Haiku a single YES/NO: is this query in the NEO/space-science domain?"""
        client = self.client or get_anthropic_client(self.settings)
        resp = await client.messages.create(
            model=self.settings.haiku_model,
            max_tokens=5,  # one word; keep the paid call tiny
            system=_DOMAIN_SYSTEM,
            messages=[{"role": "user", "content": query}],
        )
        if context is not None and resp.usage is not None:
            context.add_tokens(resp.usage.input_tokens, resp.usage.output_tokens)
        answer = "".join(block.text for block in resp.content if block.type == "text")
        return answer.strip().upper().startswith("YES")
