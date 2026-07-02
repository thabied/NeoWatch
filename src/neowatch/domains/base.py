"""Domain-registry building blocks.

The small, dependency-light types the registry is made of. They live in their own
module (separate from ``registry.py``, which assembles the concrete verticals) so
a vertical definition can import these without a circular import back through the
registry.

Key concept: a *vertical* is a coherent science domain (near-Earth objects, space
weather, Earth events…) expressed as data, not code branches. Each one declares
the orchestrator tools it exposes, the agent behind each tool, where results are
parked, the topics it widens the input guardrail to accept, and — optionally — how
it contributes a section/grounding/citations to the final report. Routing the
orchestrator, guardrail, and synthesis through these descriptors is what makes
adding a new domain "declare a Vertical" instead of "edit three agents".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

from ..agents.base import BaseAgent
from ..agents.models import Citation, ReportSection
from ..config import Settings
from ..context import AgentContext

# Builds a vertical's specialist agent. It receives the run's shared Anthropic
# client so LLM-driven agents reuse one connection pool; agents that need no LLM
# simply ignore it. Injected overrides in the orchestrator still take precedence.
AgentFactory = Callable[[Settings, AsyncAnthropic | None], BaseAgent]


@dataclass(frozen=True)
class Capability:
    """One orchestrator tool plus everything needed to run and record it.

    ``tool`` is the Claude tool schema the model reads to decide *whether* to call
    the capability; ``build_agent`` constructs the specialist that does the work;
    ``cache_key`` is the blackboard slot its typed output is parked under (where
    synthesis later reads it); ``summarise`` turns that output into the one-line
    status string the planner sees on the next loop iteration.
    """

    tool: dict[str, Any]
    build_agent: AgentFactory
    cache_key: str
    summarise: Callable[[Any], str]

    @property
    def name(self) -> str:
        """The tool name Claude calls and the orchestrator dispatches on."""
        return str(self.tool["name"])


@dataclass
class DomainContribution:
    """What a vertical adds to the assembled report — all optional, all deterministic.

    ``section`` is a renderable block built in Python from the vertical's computed
    core (never LLM prose — same anti-hallucination discipline as the rest of the
    report). ``grounding`` is text merged into the block the synthesis model must
    stay within, so a purely-non-NEO query still gets a grounded executive summary.
    ``citations`` are appended to the report's source appendix.
    """

    section: ReportSection | None = None
    grounding: str = ""
    citations: list[Citation] = field(default_factory=list)


# A vertical's report contribution is a pure function of the run context: it reads
# the vertical's own agent output from ``session_cache`` and returns a contribution
# (or ``None`` to add nothing). ``None`` as the *vertical's* ``contribute`` means
# "renders through a bespoke path" — the NEO vertical does that, for now.
ContributeFn = Callable[[AgentContext], "DomainContribution | None"]


@dataclass(frozen=True)
class Vertical:
    """A coherent science domain plugged into the pipeline."""

    name: str
    topics: tuple[str, ...]
    capabilities: tuple[Capability, ...]
    contribute: ContributeFn | None = None
