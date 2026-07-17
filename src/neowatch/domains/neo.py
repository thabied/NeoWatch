"""Near-Earth-object vertical.

The original NeoWatch domain, expressed as a registry :class:`Vertical`. Its four
capabilities map one-to-one to the specialist agents that already existed
(FetchAgent, CalcAgent, RAGAgent, ImageAgent); the tool schemas here are the ones
previously hard-coded inside the orchestrator.

Key concept: this is the reference vertical — the shape every later domain copies.
It keeps ``contribute=None`` because the NEO results still render through the
SynthesisAgent's bespoke ``neo_events`` / risk-table path; new verticals use the
generic section hook instead. Extracting NEO to a descriptor (rather than
rewriting synthesis around sections too) is the deliberate low-risk trade-off:
the anti-hallucination synthesis path is left untouched.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from ..agents.base import BaseAgent
from ..agents.calc_agent import CalcAgent
from ..agents.fetch_agent import FetchAgent
from ..agents.image_agent import ImageAgent
from ..agents.models import NEOData
from ..agents.rag_agent import RAGAgent
from ..config import Settings
from ..watch.rules_neo import RULES as _WATCH_RULES
from ..watch.rules_neo import neo_extract as _watch_extract
from ..watch.rules_neo import neo_sense as _watch_sense
from ..watch.spec import WatchSpec
from .base import Capability, Vertical

# Each specialist is surfaced to the planner as a tool with an empty input schema:
# Sonnet decides *whether* to call it, not low-level arguments (the agents read
# what they need from the query/context themselves).
_FETCH_TOOL: dict[str, Any] = {
    "name": "fetch_neo_data",
    "description": "Fetch near-Earth objects approaching Earth from NASA (call first).",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
_CALC_TOOL: dict[str, Any] = {
    "name": "analyze_orbits",
    "description": "Compute miss distance, velocity, size and risk bands for fetched objects.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
_RAG_TOOL: dict[str, Any] = {
    "name": "search_literature",
    "description": "Retrieve relevant scientific papers for the query's topic.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
_IMAGE_TOOL: dict[str, Any] = {
    "name": "fetch_images",
    "description": "Fetch NASA astronomy images for the relevant period.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}


# --- agent factories (share the run's Anthropic client where the agent uses one) --


def _build_fetch(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    return FetchAgent(settings, client=client)


def _build_calc(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    return CalcAgent(settings, client=client)


def _build_rag(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    return RAGAgent(settings)


def _build_image(settings: Settings, client: AsyncAnthropic | None) -> BaseAgent:
    return ImageAgent(settings)


# --- post-dispatch status strings (what the planner sees on its next turn) --------


def _fetch_summary(data: Any) -> str:
    count = len(data.feed_items) if isinstance(data, NEOData) else 0
    return f"Fetched {count} close-approach objects."


def _calc_summary(data: Any) -> str:
    count = len(data.analyses) if data is not None and hasattr(data, "analyses") else 0
    return f"Analysed {count} objects with risk bands."


def _papers_summary(data: Any) -> str:
    count = len(data) if isinstance(data, list) else 0
    return f"Found {count} relevant papers."


def _images_summary(data: Any) -> str:
    count = len(data) if isinstance(data, list) else 0
    return f"Prepared {count} images."


NEO_VERTICAL = Vertical(
    name="near-earth-objects",
    # The guardrail's allow-list phrases for this domain. "space weather" is here
    # because DONKI is one of the NEO fetch tools; a dedicated space-weather
    # vertical later will add its own phrases (the registry de-duplicates).
    topics=(
        "asteroids",
        "comets",
        "near-Earth objects",
        "meteors",
        "space weather",
        "orbital mechanics",
        "planetary defence",
    ),
    capabilities=(
        Capability(
            tool=_FETCH_TOOL,
            build_agent=_build_fetch,
            cache_key="neo_data",
            summarise=_fetch_summary,
        ),
        Capability(
            tool=_CALC_TOOL,
            build_agent=_build_calc,
            cache_key="orbital_report",
            summarise=_calc_summary,
        ),
        Capability(
            tool=_RAG_TOOL,
            build_agent=_build_rag,
            cache_key="papers",
            summarise=_papers_summary,
        ),
        Capability(
            tool=_IMAGE_TOOL,
            build_agent=_build_image,
            cache_key="images",
            summarise=_images_summary,
        ),
    ),
    contribute=None,
    # The watcher does NOT reuse the LLM-driven fetch/calc agents above: it
    # declares a deterministic ``sense`` (NASA feed + pure calc cores, no model)
    # so the recurring loop stays cheap and diffs a stable object set. NeoWs
    # publishes new close approaches ~daily, so a daily re-check cadence fits.
    watch=WatchSpec(
        extract=_watch_extract,
        rules=_WATCH_RULES,
        cadence_seconds=86_400,
        sense=_watch_sense,
    ),
)
