"""Top-level orchestration pipeline.

Exposes ``run_query(query) -> FinalReport``: the single high-level entry the UI
calls. It chains the stages — input guardrail (inside the orchestrator) ->
orchestrator (which dispatches the specialist agents) -> synthesis (which builds
and fact-checks the report) — and always returns a validated ``FinalReport``,
even on rejection, so the UI never has to special-case errors.

Key concept: one thin coordinator so the UI never talks to agents directly. The
pipeline owns the single shared ``AgentContext`` for the run; everything else is
threaded through it.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from .agents.models import FinalReport
from .agents.orchestrator import OrchestratorAgent
from .agents.synthesis_agent import SynthesisAgent
from .config import Settings, get_settings
from .context import AgentContext, ProgressCallback


async def run_query(
    query: str,
    settings: Settings | None = None,
    client: AsyncAnthropic | None = None,
    logger: FilteringBoundLogger | None = None,
    progress: ProgressCallback | None = None,
) -> FinalReport:
    """Run one query end-to-end and return a validated ``FinalReport``.

    Args:
        query: The user's natural-language question.
        settings: Optional settings override (defaults to the cached singleton).
        client: Optional injected Anthropic client (a fake in tests).
        logger: Optional structlog logger.
        progress: Optional UI hook called with a status string as each stage
            completes (used by the Gradio front-end to stream progress).

    Returns:
        A ``FinalReport``. If the guardrail rejects the query, the report carries
        the rejection reason in ``executive_summary`` / ``confidence_notes`` and
        is otherwise empty — so callers always receive a well-formed object.
    """
    settings = settings or get_settings()
    context = AgentContext(query=query)

    orchestrator = OrchestratorAgent(settings, logger=logger, client=client, progress=progress)
    plan = await orchestrator.run(context)
    if not plan.success:
        return _rejection_report(query, plan.error or "Query was rejected.")

    synthesis = SynthesisAgent(settings, logger=logger, client=client, progress=progress)
    result = await synthesis.run(context)
    report = result.data
    assert isinstance(report, FinalReport)  # SynthesisAgent always returns one
    return report


def _rejection_report(query: str, reason: str) -> FinalReport:
    """Wrap a guardrail rejection as a (valid, empty) ``FinalReport``."""
    return FinalReport(
        query=query,
        executive_summary=f"This query was not processed: {reason}",
        confidence_notes=[reason],
    )
