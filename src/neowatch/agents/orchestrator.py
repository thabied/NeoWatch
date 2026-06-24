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
from ..guardrails.domain import DomainGuardrail
from ..guardrails.token_budget import TokenBudgetGuardrail
from ..llm import get_anthropic_client
from ..prompts.system_prompts import ORCHESTRATOR_V1
from .base import BaseAgent
from .calc_agent import CalcAgent
from .fetch_agent import FetchAgent
from .image_agent import ImageAgent
from .models import NEOData
from .rag_agent import RAGAgent

_MAX_ITERATIONS = 6

# Each specialist agent is surfaced to Sonnet as a tool. Inputs are intentionally
# minimal — Sonnet decides *whether* to call, not low-level arguments (the agents
# read what they need from the query/context themselves).
ORCHESTRATOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "fetch_neo_data",
        "description": "Fetch near-Earth objects approaching Earth from NASA (call first).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "analyze_orbits",
        "description": "Compute miss distance, velocity, size and risk bands for fetched objects.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search_literature",
        "description": "Retrieve relevant scientific papers for the query's topic.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "fetch_images",
        "description": "Fetch NASA astronomy images for the relevant period.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


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
        # Agents are injectable so tests can supply offline stubs; otherwise the
        # real specialists are built (sharing the injected client where they use
        # one, so a test's FakeAnthropic flows all the way down).
        self.agents: dict[str, BaseAgent] = {
            "fetch_neo_data": fetch_agent or FetchAgent(settings, client=client),
            "analyze_orbits": calc_agent or CalcAgent(settings, client=client),
            "search_literature": rag_agent or RAGAgent(settings),
            "fetch_images": image_agent or ImageAgent(settings),
        }
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
                system=ORCHESTRATOR_V1,
                tools=cast("list[ToolParam]", ORCHESTRATOR_TOOLS),
                messages=cast("list[MessageParam]", messages),
            )
            if resp.usage is not None:
                context.add_tokens(resp.usage.input_tokens + resp.usage.output_tokens)
            if resp.stop_reason != "tool_use":
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

        # Park each agent's typed output on the shared blackboard for synthesis.
        if tool_name == "fetch_neo_data":
            context.session_cache["neo_data"] = result.data
            count = len(result.data.feed_items) if isinstance(result.data, NEOData) else 0
            return f"Fetched {count} close-approach objects."
        if tool_name == "analyze_orbits":
            context.session_cache["orbital_report"] = result.data
            return f"Analysed {len(result.data.analyses)} objects with risk bands."
        if tool_name == "search_literature":
            context.session_cache["papers"] = result.data
            return f"Found {len(result.data)} relevant papers."
        if tool_name == "fetch_images":
            context.session_cache["images"] = result.data
            return f"Prepared {len(result.data)} images."
        return "Done."

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
