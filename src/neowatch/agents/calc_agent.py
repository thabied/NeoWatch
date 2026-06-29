"""Calc agent.

Produces orbital-mechanics and risk analysis. The maths is done in pure
numpy/scipy (deterministic, in ``neowatch.calc``); Haiku is used *only* to add
narrative framing and must never alter a computed number.

Key concept: separate deterministic computation from LLM prose. Numbers come
from code we can trust and test; the LLM just explains them. The fact-check
layer flags any LLM claim that drifts from the computed value.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from ..calc.models import OrbitalAnalysis, OrbitalReport, RiskAssessment
from ..calc.orbital import analyse_orbit, assess_risk, detect_anomaly
from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.models import NEOFeedItem
from ..llm import get_anthropic_client
from .base import BaseAgent
from .models import NEOData

_CALC_SYSTEM = (
    "You are a concise science writer. You are given asteroid figures that were "
    "already computed. Write 2-3 plain-English sentences summarising the overall "
    "picture (how close, how fast, how risky). Never invent or change any number; "
    "only describe the values given. No preamble, no lists."
)


class CalcAgent(BaseAgent):
    """Compute orbital/risk figures deterministically; Haiku narrates them."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self.client = client

    async def run(self, context: AgentContext) -> AgentResult:
        """Build ``OrbitalReport`` from the FetchAgent's ``NEOData`` in context."""
        neo_data = context.session_cache.get("neo_data")
        if not isinstance(neo_data, NEOData):
            return AgentResult(
                agent_name="CalcAgent", success=False, error="no NEOData found in context"
            )

        analyses: list[OrbitalAnalysis] = []
        risks: list[RiskAssessment] = []
        for item in neo_data.feed_items:
            analysis = _analyse_item(item)
            if analysis is None:
                continue
            analyses.append(analysis)
            risks.append(
                assess_risk(
                    analysis.object_id,
                    analysis.miss_distance_ld,
                    analysis.diameter_max_m,
                    analysis.is_potentially_hazardous,
                )
            )

        flags = detect_anomaly([a.velocity_km_s for a in analyses])
        anomalies = [a.object_id for a, flagged in zip(analyses, flags, strict=True) if flagged]

        narrative = await self._narrate(context, analyses, risks)
        report = OrbitalReport(
            analyses=analyses, risks=risks, anomalies=anomalies, narrative=narrative
        )
        self.logger.info("calc_agent.analysed", objects=len(analyses), anomalies=len(anomalies))
        return AgentResult(agent_name="CalcAgent", success=True, data=report)

    async def _narrate(
        self,
        context: AgentContext,
        analyses: list[OrbitalAnalysis],
        risks: list[RiskAssessment],
    ) -> str:
        """Ask Haiku to phrase the precomputed figures (numbers stay verbatim)."""
        if not analyses:
            return "No close-approach objects to summarise."
        figures = "\n".join(
            f"{a.name}: {a.miss_distance_ld:.1f} LD, {a.velocity_km_s:.1f} km/s "
            f"({a.velocity_class}), up to {a.diameter_max_m:.0f} m, risk {r.risk_band}"
            for a, r in zip(analyses, risks, strict=True)
        )
        client = self.client or get_anthropic_client(self.settings)
        resp = await client.messages.create(
            model=self.settings.haiku_model,
            max_tokens=600,
            system=_CALC_SYSTEM,
            messages=[{"role": "user", "content": figures}],
        )
        if resp.usage is not None:
            context.add_tokens(resp.usage.input_tokens, resp.usage.output_tokens)
        return "".join(block.text for block in resp.content if block.type == "text")


def _analyse_item(item: NEOFeedItem) -> OrbitalAnalysis | None:
    """Build an ``OrbitalAnalysis`` from an item's closest approach (None if absent)."""
    if not item.close_approach_data:
        return None
    closest = min(item.close_approach_data, key=lambda ca: ca.miss_distance.kilometers)
    meters = item.estimated_diameter.meters
    return analyse_orbit(
        object_id=item.id,
        name=item.name,
        miss_distance_km=closest.miss_distance.kilometers,
        velocity_km_s=closest.relative_velocity.kilometers_per_second,
        diameter_min_m=meters.estimated_diameter_min,
        diameter_max_m=meters.estimated_diameter_max,
        is_potentially_hazardous=item.is_potentially_hazardous_asteroid,
    )
