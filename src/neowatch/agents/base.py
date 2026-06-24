"""Abstract base agent.

Defines ``BaseAgent``: the common interface every agent shares (constructed with
settings + a logger, exposing ``async def run(self, context) -> AgentResult``).

Key concept: programming to a shared abstract contract lets the orchestrator
treat all agents interchangeably and makes new agents easy to add.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog
from structlog.typing import FilteringBoundLogger

from neowatch.config import Settings
from neowatch.context import AgentContext, AgentResult


class BaseAgent(ABC):
    """Abstract base class all NeoWatch agents inherit.

    Subclasses implement :meth:`run`. The orchestrator can then treat any agent
    uniformly without knowing its concrete type (the Liskov substitution idea).
    """

    def __init__(
        self, settings: Settings, logger: FilteringBoundLogger | None = None
    ) -> None:
        """Initialise the agent.

        Args:
            settings: Shared application settings.
            logger: Optional structlog logger; one bound to the agent's class
                name is created if not supplied.
        """
        self.settings = settings
        self.logger: FilteringBoundLogger = logger or structlog.get_logger(
            self.__class__.__name__
        )

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent's task.

        Args:
            context: The shared, mutable run context.

        Returns:
            A typed :class:`AgentResult` describing success and payload.
        """
        ...
