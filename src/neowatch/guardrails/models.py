"""Guardrail data models.

``GuardrailResult`` (allowed + reason), ``FlaggedClaim`` (a number that disagrees
with source data), and ``FactCheckReport`` (the collection of flags + overall
confidence).

Key concept: the guardrails speak in typed results, not bare booleans or dicts.
A rejected query carries *why* it was rejected; a flagged number carries the
source value and the size of the disagreement, so the verdict is auditable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GuardrailResult(BaseModel):
    """Outcome of an input check.

    Attributes:
        allowed: True if the query may proceed to the (expensive) pipeline.
        reason: Human-readable explanation, always set on rejection.
    """

    allowed: bool
    reason: str = ""


class FlaggedClaim(BaseModel):
    """One number in generated prose that does not match any source value.

    Attributes:
        value: The number the LLM wrote.
        source_value: The nearest trusted (computed) value for that unit.
        pct_diff: Percentage difference from ``source_value`` (absolute).
        location: The matched text snippet, e.g. ``"18 LD"`` (for the user).
    """

    value: float
    source_value: float
    pct_diff: float
    location: str


class FactCheckReport(BaseModel):
    """Result of checking generated prose against the grounding context.

    Claims are *flagged*, never deleted — the report surfaces low confidence so
    the user can judge, rather than silently rewriting the model's output.

    Attributes:
        flagged: Numbers that deviated from source data beyond tolerance.
        confidence: ``"high"`` (no flags), ``"medium"`` (one), or ``"low"``.
    """

    flagged: list[FlaggedClaim] = Field(default_factory=list)
    confidence: str = "high"
