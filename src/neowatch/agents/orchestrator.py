"""Orchestrator agent.

The planner/coordinator (Claude Sonnet). It first runs the ``DomainGuardrail``,
then drives a tool-use loop in which each specialist agent is exposed as a Claude
*tool*. Sonnet decides which agents to invoke and in what order; Python executes
them, stores their typed outputs on the shared context, checks the token budget
between steps, and retries an agent once if it fails.

Key concept: this is the "agentic" core — the LLM *plans and dispatches* work
rather than following a fixed script. The trade-off is cost: a genuine tool-use
loop spends Sonnet tokens on planning that a hard-coded sequence would not. We
accept that here because dynamic planning ("call literature search only when the
query is about research") is the whole point; we bound the cost with a hard
iteration cap and a budget check between every step.

Outputs are written to ``context.session_cache`` (the shared blackboard) under
known keys, where the SynthesisAgent reads them:
``neo_data``, ``orbital_report``, ``papers``, ``images``.
"""

from __future__ import annotations

from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext, AgentResult, ProgressCallback
from ..domains.registry import capability_map, orchestrator_tools
from ..guardrails.domain import DomainGuardrail
from ..guardrails.token_budget import TokenBudgetGuardrail
from ..llm import get_anthropic_client
from ..prompts.system_prompts import ORCHESTRATOR_V2
from .base import BaseAgent

_MAX_ITERATIONS = 6

# Which constructor override maps to which registered tool name. This keeps the
# old ``fetch_agent=/calc_agent=/…`` injection API (used by tests to supply
# offline stubs) working after the default agent set moved into the registry.
_OVERRIDE_TOOLS = {
    "fetch_agent": "fetch_neo_data",
    "calc_agent": "analyze_orbits",
    "rag_agent": "search_literature",
    "image_agent": "fetch_images",
}


class OrchestratorAgent(BaseAgent):
    """Guardrail the query, then let Sonnet dispatch specialist agents as tools."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        client: AsyncAnthropic | None = None,
        fetch_agent: BaseAgent | None = None,
        calc_agent: BaseAgent | None = None,
        rag_agent: BaseAgent | None = None,
        image_agent: BaseAgent | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self.client = client
        self.progress = progress
        # The registry is the source of truth for which tools exist and which
        # agent runs each. Build the default specialist set from it (sharing the
        # injected client where an agent uses one, so a test's FakeAnthropic flows
        # all the way down), then let any explicit override replace an agent by
        # tool name — preserving the old injection API for offline stubs.
        self._capabilities = capability_map()
        self._tools = orchestrator_tools()
        self.agents: dict[str, BaseAgent] = {
            name: cap.build_agent(settings, client)
            for name, cap in self._capabilities.items()
        }
        overrides = {
            "fetch_agent": fetch_agent,
            "calc_agent": calc_agent,
            "rag_agent": rag_agent,
            "image_agent": image_agent,
        }
        for arg, tool_name in _OVERRIDE_TOOLS.items():
            override = overrides[arg]
            if override is not None:
                self.agents[tool_name] = override
        self.domain_guardrail = DomainGuardrail(settings, client=client)
        # Watch the *whole-session* budget here, not the per-single-call cap: this
        # guardrail tracks the orchestrator's cumulative context across every agent
        # (fetch alone can spend several thousand tokens carrying NEO data), which
        # is far larger than any one agent's per-call allowance.
        self.budget = TokenBudgetGuardrail(
            settings,
            client=client,
            logger=self.logger,
            max_tokens=settings.token_budget_per_session,
        )

    async def run(self, context: AgentContext) -> AgentResult:
        """Validate input, then plan-and-dispatch via a Sonnet tool-use loop.

        Returns an ``AgentResult`` whose ``data`` is the ordered list of agent
        tool-names that were invoked (useful for assertions and logging). On a
        guardrail rejection, ``success`` is False and ``error`` holds the reason.
        """
        self._emit("Validating query…")
        verdict = await self.domain_guardrail.validate(context.query, context)
        if not verdict.allowed:
            self.logger.info("orchestrator.rejected", reason=verdict.reason)
            self._emit("Query rejected by guardrail.")
            return AgentResult(agent_name="OrchestratorAgent", success=False, error=verdict.reason)

        anthropic = self.client or get_anthropic_client(self.settings)
        invoked: list[str] = []
        messages: list[dict[str, Any]] = [{"role": "user", "content": context.query}]

        for _ in range(_MAX_ITERATIONS):
            resp = await anthropic.messages.create(
                model=self.settings.sonnet_model,
                max_tokens=2048,
                temperature=0.2,  # low: planning should be near-deterministic
                system=ORCHESTRATOR_V2,
                tools=cast("list[ToolParam]", self._tools),
                messages=cast("list[MessageParam]", messages),
            )
            if resp.usage is not None:
                context.add_tokens(resp.usage.input_tokens, resp.usage.output_tokens)
            if resp.stop_reason != "tool_use":
                # end_turn is the normal exit. max_tokens/refusal mean Sonnet was
                # cut off or declined mid-plan, so we may be dispatching on partial
                # planning — log it rather than swallowing it silently.
                if resp.stop_reason in ("max_tokens", "refusal"):
                    self.logger.warning("orchestrator.early_stop", stop_reason=resp.stop_reason)
                break

            messages.append({"role": "assistant", "content": resp.content})
            tool_results: list[dict[str, Any]] = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                text = await self._dispatch(block.name, context, invoked)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": text}
                )
            messages.append({"role": "user", "content": tool_results})

            # Budget check between steps; a hard stop ends planning with partial data.
            if await self.budget.enforce(context) == "stop":
                self.logger.warning("orchestrator.budget_stop", invoked=invoked)
                break

        self.logger.info("orchestrator.done", invoked=invoked)
        return AgentResult(agent_name="OrchestratorAgent", success=True, data=invoked)

    async def _dispatch(self, tool_name: str, context: AgentContext, invoked: list[str]) -> str:
        """Run one specialist agent, store its output, and return a short status string."""
        agent = self.agents.get(tool_name)
        if agent is None:
            return f"Unknown tool {tool_name}."

        self._emit(f"Running {tool_name}…")
        result = await self._run_with_retry(agent, context)
        invoked.append(tool_name)
        if not result.success:
            return f"{tool_name} failed: {result.error}"

        # Park the agent's typed output on the shared blackboard under the
        # capability's key (where synthesis reads it), then summarise it for the
        # planner — both come from the registry descriptor, no per-tool branches.
        capability = self._capabilities[tool_name]
        context.session_cache[capability.cache_key] = result.data
        return capability.summarise(result.data)

    def _emit(self, message: str) -> None:
        """Send a progress update to the UI hook, if one is attached."""
        if self.progress is not None:
            self.progress(message)

    async def _run_with_retry(
        self, agent: BaseAgent, context: AgentContext, attempts: int = 2
    ) -> AgentResult:
        """Run an agent, retrying once if it returns a failed (typed) result.

        Note: this is an *agent-level* retry on the returned ``AgentResult.success``
        flag — distinct from the HTTP-level ``tenacity`` retries inside the data
        clients (Phase 2). Agents catch their own exceptions and report failure as
        data, so retrying here means re-running on a soft failure.
        """
        result = await agent.run(context)
        for _ in range(attempts - 1):
            if result.success:
                break
            self.logger.info("orchestrator.retry", agent=agent.__class__.__name__)
            result = await agent.run(context)
        return result
