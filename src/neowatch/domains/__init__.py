"""Domain (vertical) registry package.

Re-exports the registry accessors so callers can ``from ..domains import
orchestrator_tools`` without knowing whether a symbol lives in ``base`` or
``registry``.
"""

from __future__ import annotations

from .base import Capability, DomainContribution, Vertical
from .registry import (
    REGISTRY,
    all_capabilities,
    capability_map,
    contributions,
    domain_topics,
    orchestrator_tools,
)

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
