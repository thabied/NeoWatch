"""The vertical registry and the read helpers the pipeline consumes.

``REGISTRY`` is the single list of science domains the system serves. Everything
that used to hard-code near-Earth-object specifics — the orchestrator's tool list
and dispatch table, the input guardrail's allow-list, the synthesis report's
sections — now derives from here through the small accessor functions below.

Key concept: one source of truth for "what domains exist". Adding a vertical means
appending it to ``REGISTRY`` (and writing its data client + agent + core); the
orchestrator, guardrail, and synthesis pick it up with no edits of their own.
"""

from __future__ import annotations

from typing import Any

from .base import Capability, ContributeFn, DomainContribution, Vertical
from .earth_events import EARTH_EVENTS_VERTICAL
from .neo import NEO_VERTICAL
from .space_weather import SPACE_WEATHER_VERTICAL

# The registered science domains, in priority order. New verticals are appended
# here — that single edit is what makes them "config, not surgery".
REGISTRY: tuple[Vertical, ...] = (
    NEO_VERTICAL,
    SPACE_WEATHER_VERTICAL,
    EARTH_EVENTS_VERTICAL,
)


def all_capabilities() -> list[Capability]:
    """Flatten every vertical's capabilities into one list (registry order)."""
    return [cap for vertical in REGISTRY for cap in vertical.capabilities]


def capability_map() -> dict[str, Capability]:
    """Map each tool name to its capability (the orchestrator's dispatch table)."""
    return {cap.name: cap for cap in all_capabilities()}


def orchestrator_tools() -> list[dict[str, Any]]:
    """The tool schemas to advertise to the planner, across all verticals."""
    return [cap.tool for cap in all_capabilities()]


def domain_topics() -> list[str]:
    """The de-duplicated allow-list of topics the input guardrail should accept."""
    seen: list[str] = []
    for vertical in REGISTRY:
        for topic in vertical.topics:
            if topic not in seen:
                seen.append(topic)
    return seen


def contributions() -> list[ContributeFn]:
    """The report-contribution functions of verticals that opt into the generic path."""
    return [v.contribute for v in REGISTRY if v.contribute is not None]


__all__ = [
    "REGISTRY",
    "Capability",
    "DomainContribution",
    "Vertical",
    "all_capabilities",
    "capability_map",
    "contributions",
    "domain_topics",
    "orchestrator_tools",
]
