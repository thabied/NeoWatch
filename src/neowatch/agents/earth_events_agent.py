"""Earth-events agent.

Fetches the current active-natural-event feed from NASA EONET and runs the
deterministic geospatial core over it. Like SpaceWeatherAgent — and unlike
FetchAgent/CalcAgent — this agent makes **no LLM call at all**: the whole vertical
is fetch-then-compute, and its report prose is assembled in Python by the
vertical's ``contribute`` function.

Key concept: the only failure here is not being able to *fetch* the feed. An empty
feed is a valid answer ("nothing significant is active right now"), so — unlike the
space-weather agent, which fails when there is no Kp reading to assess — this agent
returns a successful, zero-count assessment rather than an error.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from ..calc.geo import assess_earth_events
from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.eonet import get_earth_events
from ..data.http import get_async_client
from .base import BaseAgent


class EarthEventsAgent(BaseAgent):
    """Fetch active natural events and compute a deterministic assessment."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        # ``client`` is accepted to match the registry's agent-factory signature,
        # but never used — this agent makes no model call.
        super().__init__(settings, logger)

    async def run(self, context: AgentContext) -> AgentResult:
        """Fetch EONET events, assess them, return an ``EarthEventsAssessment``."""
        try:
            async with get_async_client() as http:
                report = await get_earth_events(http)
        except Exception as exc:  # noqa: BLE001 — surface as a typed failure
            self.logger.warning("earth_events_agent.failed", error=str(exc))
            return AgentResult(agent_name="EarthEventsAgent", success=False, error=str(exc))

        assessment = assess_earth_events(report.events)
        self.logger.info(
            "earth_events_agent.done",
            active=assessment.total_active,
            categories=len(assessment.categories),
        )
        return AgentResult(agent_name="EarthEventsAgent", success=True, data=assessment)
