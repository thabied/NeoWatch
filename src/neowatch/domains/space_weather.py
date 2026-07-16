"""Space-weather vertical.

The first domain added *after* the registry refactor, and the first to use the
generic report hook rather than NEO's bespoke synthesis path. It exposes one
capability — ``assess_space_weather`` — backed by the LLM-free SpaceWeatherAgent,
and contributes a deterministic report section, grounding block, and citation via
``contribute``.

Key concept: this is the payoff of Phase 0. Adding a whole science domain is now
"declare a Vertical" — a tool schema, an agent factory, and a pure ``contribute``
function — with no edits to the orchestrator's dispatch loop or synthesis's
assembly. ``contribute`` reads the agent's typed output off the blackboard and
returns Python-assembled facts (never LLM prose), keeping the anti-hallucination
discipline the rest of the report follows.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from ..agents.base import BaseAgent
from ..agents.models import Citation, ReportSection
from ..agents.space_weather_agent import SpaceWeatherAgent
from ..calc.models import SpaceWeatherAssessment
from ..config import Settings
from ..context import AgentContext
from ..watch.rules_space_weather import RULES as _WATCH_RULES
from ..watch.rules_space_weather import extract as _watch_extract
from ..watch.spec import WatchSpec
from .base import Capability, DomainContribution, Vertical

_ASSESS_TOOL: dict[str, Any] = {
    "name": "assess_space_weather",
    "description": (
        "Get current geomagnetic activity (NOAA planetary Kp index) and derive the "
        "NOAA G-scale storm level and how far toward the equator aurora may be "
        "visible. Call for queries about space weather, geomagnetic storms, aurora, "
        "or solar activity."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _build_space_weather(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    # No client is passed on: the space-weather agent makes no model call.
    return SpaceWeatherAgent(settings)


def _summary(data: Any) -> str:
    """One-line status for the planner's next turn (defensive on odd data)."""
    if isinstance(data, SpaceWeatherAssessment):
        return f"Assessed space weather: Kp {data.kp:.2f} ({data.g_scale})."
    return "Assessed space weather: no reading available."


def _contribute(context: AgentContext) -> DomainContribution | None:
    """Assemble the space-weather report section from the blackboard (pure Python).

    Returns ``None`` when the vertical was not invoked this run (no assessment on
    the blackboard), so a pure-NEO query contributes nothing.
    """
    data = context.session_cache.get("space_weather")
    if not isinstance(data, SpaceWeatherAssessment):
        return None

    rows: list[dict[str, Any]] = [
        {"Metric": "Planetary Kp index", "Value": f"{data.kp:.2f}"},
        {"Metric": "Storm level", "Value": f"{data.g_scale} ({data.storm_level})"},
        {"Metric": "Aurora visible to", "Value": f"~{data.aurora_latitude_deg:.1f}° geomag. lat"},
        {"Metric": "Observed at", "Value": data.time_tag},
    ]
    section = ReportSection(title="Space weather", body_markdown=data.summary, rows=rows)

    grounding = (
        "SPACE WEATHER (computed from NOAA SWPC planetary K-index):\n"
        f"- Kp index: {data.kp:.2f} at {data.time_tag}\n"
        f"- NOAA storm scale: {data.g_scale} ({data.storm_level})\n"
        f"- Aurora may be visible down to ~{data.aurora_latitude_deg:.1f}° "
        "geomagnetic latitude"
    )

    citation = Citation(
        source_type="noaa_swpc",
        title="NOAA SWPC planetary K-index",
        identifier=data.time_tag,
        url="https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
    )
    return DomainContribution(section=section, grounding=grounding, citations=[citation])


SPACE_WEATHER_VERTICAL = Vertical(
    name="space-weather",
    topics=(
        "space weather",
        "geomagnetic storms",
        "solar flares",
        "solar activity",
        "aurora",
        "Kp index",
    ),
    capabilities=(
        Capability(
            tool=_ASSESS_TOOL,
            build_agent=_build_space_weather,
            cache_key="space_weather",
            summarise=_summary,
        ),
    ),
    contribute=_contribute,
    # NOAA publishes Kp roughly every 3 hours, so that is the natural re-check cadence.
    watch=WatchSpec(extract=_watch_extract, rules=_WATCH_RULES, cadence_seconds=10_800),
)
