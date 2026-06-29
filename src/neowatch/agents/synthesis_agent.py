"""Synthesis agent.

Combines the specialist outputs into one grounded, cited ``FinalReport`` (Claude
Sonnet). Before generating, it builds a single GROUNDING block the model must
stay within; after generating, the ``FactCheckLayer`` verifies every numeric
claim in the prose against the computed figures and records any disagreement in
``confidence_notes``.

Key concept: grounding + post-hoc fact-checking is the anti-hallucination
strategy — the model is fenced in *before* generation and audited *after*. And,
as in CalcAgent, the LLM writes only prose: every number, table row, and citation
in the ``FinalReport`` is assembled deterministically in Python from the agent
outputs, so the model can describe the data but never fabricate it.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from structlog.typing import FilteringBoundLogger

from ..calc.models import OrbitalReport, RiskAssessment
from ..config import Settings
from ..context import AgentContext, AgentResult, ProgressCallback
from ..guardrails.factcheck import FactCheckLayer, build_grounding_context
from ..llm import get_anthropic_client
from ..prompts.system_prompts import SYNTHESIS_V2, SYNTHESIS_VERSION
from ..rag.models import RetrievedPaper
from .base import BaseAgent
from .models import (
    Citation,
    FinalReport,
    ImageAsset,
    NEOData,
    NEOEventReport,
    RiskTableRow,
)


class EventSummary(BaseModel):
    """One LLM-written sentence tied to a specific computed object by its id."""

    object_id: str
    summary: str


class ProseModel(BaseModel):
    """The exact prose shape Sonnet must return.

    Passing this to ``messages.parse(output_format=...)`` turns the shape into a
    JSON schema the API *enforces* — so we get a validated object back instead of
    free text we have to scrape. This replaces the old "ask for JSON, then match
    it with a greedy ``\\{.*\\}`` regex" approach, whose failure mode was silent:
    any stray braces in surrounding prose made the regex over-match, the parse
    returned ``{}``, and the report came back empty with no error.
    """

    executive_summary: str
    literature_insights: str
    event_summaries: list[EventSummary]


class SynthesisAgent(BaseAgent):
    """Write grounded prose, assemble the typed report, then fact-check it."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        client: AsyncAnthropic | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self.client = client
        self.progress = progress

    async def run(self, context: AgentContext) -> AgentResult:
        """Build a ``FinalReport`` from the blackboard, then verify its numbers."""
        if self.progress is not None:
            self.progress("Writing report…")
        orbital = context.session_cache.get("orbital_report")
        orbital = orbital if isinstance(orbital, OrbitalReport) else OrbitalReport()
        papers = _as_papers(context.session_cache.get("papers"))
        images = _as_images(context.session_cache.get("images"))
        neo_data = context.session_cache.get("neo_data")

        prose = await self._write_prose(context, orbital, papers)

        events = _build_events(orbital, prose.event_summaries)
        report = FinalReport(
            query=context.query,
            executive_summary=prose.executive_summary,
            neo_events=events,
            orbital_risk_table=_build_risk_table(orbital),
            literature_insights=prose.literature_insights,
            data_sources=_build_citations(neo_data, papers, images),
            images=images,
            prompt_version=SYNTHESIS_VERSION,
        )

        report.confidence_notes = self._fact_check(report, orbital, neo_data)
        self.logger.info(
            "synthesis.done", events=len(report.neo_events), notes=len(report.confidence_notes)
        )
        return AgentResult(agent_name="SynthesisAgent", success=True, data=report)

    async def _write_prose(
        self, context: AgentContext, orbital: OrbitalReport, papers: list[RetrievedPaper]
    ) -> ProseModel:
        """Ask Sonnet for the prose as a schema-validated object (structured outputs).

        ``messages.parse(output_format=ProseModel)`` constrains the model to our
        schema and hands back a validated ``ProseModel`` on ``parsed_output`` —
        no regex, no silent empty-report failure. ``temperature`` is still valid
        on Sonnet 4.6, so we keep a little warmth for readable prose.
        """
        grounding = _grounding_text(context.query, orbital, papers)
        client = self.client or get_anthropic_client(self.settings)
        empty = ProseModel(executive_summary="", literature_insights="", event_summaries=[])
        try:
            resp = await client.messages.parse(
                model=self.settings.sonnet_model,
                max_tokens=4096,
                temperature=0.4,  # a little warmth for readable prose, still grounded
                system=SYNTHESIS_V2,
                messages=[{"role": "user", "content": grounding}],
                output_format=ProseModel,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to a deterministic report
            # An SDK/validation/transport error must not sink the whole report:
            # synthesis is the last stage, so a raise here would break the
            # pipeline's "always return a FinalReport" contract. Fall back to
            # empty prose; the computed tables/citations still build.
            self.logger.warning("synthesis.parse_failed", error=str(exc))
            return empty
        if resp.usage is not None:
            context.add_tokens(resp.usage.input_tokens, resp.usage.output_tokens)
        # parsed_output is None only if the model refused or was cut off
        # (max_tokens) before producing a complete object — degrade to empty
        # prose so the deterministic tables/citations still build.
        return resp.parsed_output or empty

    def _fact_check(
        self, report: FinalReport, orbital: OrbitalReport, neo_data: Any
    ) -> list[str]:
        """Audit the LLM prose against the computed grounding; return human notes."""
        notes: list[str] = []
        grounding = build_grounding_context(orbital)
        prose_blob = " ".join(
            [
                report.executive_summary,
                report.literature_insights,
                *[e.summary for e in report.neo_events],
            ]
        )
        result = FactCheckLayer().check(prose_blob, grounding)
        notes.append(f"Fact-check confidence: {result.confidence}.")
        for claim in result.flagged:
            notes.append(
                f"Unverified figure '{claim.location}' differs from the computed "
                f"{claim.source_value:g} by {claim.pct_diff:.0f}% — treat with caution."
            )
        if isinstance(neo_data, NEOData) and neo_data.remainder_count:
            notes.append(
                f"{neo_data.remainder_count} further objects were summarised, not "
                "individually listed."
            )
        return notes


# --- deterministic assembly helpers (no LLM) -------------------------------


def _build_events(
    orbital: OrbitalReport, summaries: list[EventSummary]
) -> list[NEOEventReport]:
    """Pair each computed analysis/risk with its (optional) one-line LLM summary."""
    by_id: dict[str, str] = {s.object_id: s.summary for s in summaries}
    risks: dict[str, RiskAssessment] = {r.object_id: r for r in orbital.risks}
    events: list[NEOEventReport] = []
    for a in orbital.analyses:
        risk = risks.get(a.object_id)
        events.append(
            NEOEventReport(
                object_id=a.object_id,
                name=a.name,
                miss_distance_ld=a.miss_distance_ld,
                velocity_km_s=a.velocity_km_s,
                diameter_max_m=a.diameter_max_m,
                risk_band=risk.risk_band if risk else "unknown",
                summary=by_id.get(a.object_id, ""),
            )
        )
    return events


def _build_risk_table(orbital: OrbitalReport) -> list[RiskTableRow]:
    """Flatten the computed analyses/risks into compact table rows."""
    risks: dict[str, RiskAssessment] = {r.object_id: r for r in orbital.risks}
    return [
        RiskTableRow(
            name=a.name,
            miss_distance_ld=a.miss_distance_ld,
            velocity_km_s=a.velocity_km_s,
            diameter_max_m=a.diameter_max_m,
            risk_band=risks[a.object_id].risk_band if a.object_id in risks else "unknown",
        )
        for a in orbital.analyses
    ]


def _build_citations(
    neo_data: Any, papers: list[RetrievedPaper], images: list[ImageAsset]
) -> list[Citation]:
    """Build the source appendix from the data we actually fetched."""
    citations: list[Citation] = []
    if isinstance(neo_data, NEOData) and (neo_data.feed_items or neo_data.remainder_count):
        citations.append(
            Citation(
                source_type="nasa_neows",
                title="NASA NeoWs close-approach data",
                url="https://api.nasa.gov/",
            )
        )
    for paper in papers:
        citations.append(
            Citation(
                source_type="arxiv",
                title=paper.title,
                identifier=paper.arxiv_id,
                url=paper.url,
            )
        )
    for image in images:
        citations.append(
            Citation(source_type="apod", title=image.title, identifier=image.date, url=image.url)
        )
    return citations


def _grounding_text(
    query: str, orbital: OrbitalReport, papers: list[RetrievedPaper]
) -> str:
    """Render the grounding block the model must stay within."""
    lines = [f"USER QUERY: {query}", "", "OBJECTS (computed figures):"]
    if orbital.analyses:
        risks = {r.object_id: r for r in orbital.risks}
        for a in orbital.analyses:
            band = risks[a.object_id].risk_band if a.object_id in risks else "unknown"
            lines.append(
                f"- id={a.object_id} name={a.name}: {a.miss_distance_ld:.1f} LD, "
                f"{a.velocity_km_s:.1f} km/s ({a.velocity_class}), up to "
                f"{a.diameter_max_m:.0f} m, risk={band}"
            )
    else:
        lines.append("- (none)")
    lines += ["", "PAPERS:"]
    if papers:
        for p in papers:
            lines.append(f"- {p.arxiv_id}: {p.title} — {p.abstract[:200]}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _as_papers(value: Any) -> list[RetrievedPaper]:
    if isinstance(value, list):
        return [p for p in value if isinstance(p, RetrievedPaper)]
    return []


def _as_images(value: Any) -> list[ImageAsset]:
    if isinstance(value, list):
        return [i for i in value if isinstance(i, ImageAsset)]
    return []
