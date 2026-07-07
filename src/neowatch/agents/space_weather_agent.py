"""Space-weather agent.

Fetches the current planetary K-index from NOAA SWPC and runs the deterministic
space-weather core over the latest reading. Unlike FetchAgent/CalcAgent this agent
makes **no LLM call at all**: the whole vertical is fetch-then-compute, and its
report prose is assembled in Python by the vertical's ``contribute`` function.

Key concept: not every specialist needs a model. When a domain has a real
deterministic core and no per-object narration to write, an LLM-free agent is
cheaper, faster, and impossible to hallucinate through. It still implements the
same ``BaseAgent`` contract, so the orchestrator dispatches it identically.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic
from structlog.typing import FilteringBoundLogger

from ..calc.space_weather import assess_space_weather
from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.http import get_async_client
from ..data.noaa_swpc import get_planetary_k_index
from .base import BaseAgent


class SpaceWeatherAgent(BaseAgent):
    """Fetch the planetary Kp index and compute a deterministic assessment."""

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
        """Fetch Kp, assess the latest reading, return a ``SpaceWeatherAssessment``."""
        try:
            async with get_async_client() as http:
                report = await get_planetary_k_index(http)
        except Exception as exc:  # noqa: BLE001 — surface as a typed failure
            self.logger.warning("space_weather_agent.failed", error=str(exc))
            return AgentResult(agent_name="SpaceWeatherAgent", success=False, error=str(exc))

        latest = report.latest
        if latest is None:
            return AgentResult(
                agent_name="SpaceWeatherAgent", success=False, error="no Kp readings returned"
            )

        assessment = assess_space_weather(latest)
        self.logger.info(
            "space_weather_agent.done", kp=assessment.kp, g_scale=assessment.g_scale
        )
        return AgentResult(agent_name="SpaceWeatherAgent", success=True, data=assessment)
