"""Earth-events vertical.

The second domain added through the registry, and the third pluggable vertical
overall. It exposes one capability — ``find_earth_events`` — backed by the LLM-free
EarthEventsAgent, and contributes a deterministic report section, grounding block,
and citation via ``contribute``.

Key concept: this vertical is almost a carbon copy of the space-weather one — a
tool schema, an LLM-free agent factory, a one-line summariser, and a pure
``contribute`` that reads the typed assessment off the blackboard and assembles
Python-only facts. That the two look nearly identical is the point: the registry
seam turned "add a science domain" into filling in a small, fixed template with no
edits to the orchestrator dispatch loop or synthesis assembly.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from ..agents.base import BaseAgent
from ..agents.earth_events_agent import EarthEventsAgent
from ..agents.models import Citation, ReportSection
from ..calc.models import EarthEventsAssessment
from ..config import Settings
from ..context import AgentContext
from .base import Capability, DomainContribution, Vertical

_FIND_TOOL: dict[str, Any] = {
    "name": "find_earth_events",
    "description": (
        "List current natural events on Earth (wildfires, severe storms, volcanoes, "
        "floods, and more) from NASA EONET, and summarise how many are active, their "
        "breakdown by category, and where activity is most concentrated. Call for "
        "queries about natural disasters, wildfires, volcanoes, floods, or other "
        "ongoing Earth hazards. It stands alone — it does not need fetch_neo_data first."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _build_earth_events(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    # No client is passed on: the Earth-events agent makes no model call.
    return EarthEventsAgent(settings)


def _summary(data: Any) -> str:
    """One-line status for the planner's next turn (defensive on odd data)."""
    if isinstance(data, EarthEventsAssessment):
        return f"Assessed Earth events: {data.total_active} active natural events."
    return "Assessed Earth events: no data available."


def _hotspot_value(data: EarthEventsAssessment) -> str:
    """Render the hotspot as a compact table value (or an em dash if none)."""
    if data.hotspot is None:
        return "—"
    h = data.hotspot
    return f"~{h.latitude:.1f}, {h.longitude:.1f} ({h.event_count} events)"


def _contribute(context: AgentContext) -> DomainContribution | None:
    """Assemble the Earth-events report section from the blackboard (pure Python).

    Returns ``None`` when the vertical was not invoked this run (no assessment on
    the blackboard), so a query that never triggered it contributes nothing.
    """
    data = context.session_cache.get("earth_events")
    if not isinstance(data, EarthEventsAssessment):
        return None

    top_category = (
        f"{data.categories[0].category} ({data.categories[0].count})"
        if data.categories
        else "—"
    )
    rows: list[dict[str, Any]] = [
        {"Metric": "Active natural events", "Value": str(data.total_active)},
        {"Metric": "Most common category", "Value": top_category},
        {"Metric": "Activity concentrated near", "Value": _hotspot_value(data)},
    ]
    section = ReportSection(title="Earth events", body_markdown=data.summary, rows=rows)

    breakdown = ", ".join(f"{c.category} {c.count}" for c in data.categories) or "none"
    grounding_lines = [
        "EARTH EVENTS (computed from the NASA EONET active natural-event feed):",
        f"- Active events tracked: {data.total_active}",
        f"- By category: {breakdown}",
    ]
    if data.hotspot is not None:
        h = data.hotspot
        grounding_lines.append(
            f"- Activity concentrated near {h.latitude:.1f}, {h.longitude:.1f}: "
            f"{h.event_count} events ({h.dominant_category}) within {h.radius_km:.0f} km"
        )
    grounding = "\n".join(grounding_lines)

    citation = Citation(
        source_type="nasa_eonet",
        title="NASA EONET natural-event feed",
        url="https://eonet.gsfc.nasa.gov/api/v3/events",
    )
    return DomainContribution(section=section, grounding=grounding, citations=[citation])


EARTH_EVENTS_VERTICAL = Vertical(
    name="earth-events",
    topics=(
        "natural disasters",
        "natural hazards",
        "wildfires",
        "volcanoes",
        "severe storms",
        "floods",
        "earthquakes",
        "Earth events",
    ),
    capabilities=(
        Capability(
            tool=_FIND_TOOL,
            build_agent=_build_earth_events,
            cache_key="earth_events",
            summarise=_summary,
        ),
    ),
    contribute=_contribute,
)
