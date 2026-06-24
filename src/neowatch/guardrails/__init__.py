"""Guardrails package.

The safety layers: input validation (domain + injection checks), output
fact-checking against source data, and token-budget control. These are what make
the system trustworthy — refusing off-topic/malicious input and catching
hallucinated numbers before the user sees them.
"""

from __future__ import annotations

from .domain import DomainGuardrail
from .factcheck import FactCheckLayer, build_grounding_context
from .models import FactCheckReport, FlaggedClaim, GuardrailResult
from .sanitise import detect_injection
from .token_budget import TokenBudgetGuardrail

__all__ = [
    "DomainGuardrail",
    "FactCheckLayer",
    "FactCheckReport",
    "FlaggedClaim",
    "GuardrailResult",
    "TokenBudgetGuardrail",
    "build_grounding_context",
    "detect_injection",
]
