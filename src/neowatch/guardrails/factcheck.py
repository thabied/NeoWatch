"""Fact-check guardrail (output).

Builds a ``GroundingContext`` (single source-of-truth dict from all agent
outputs), then ``FactCheckLayer.check`` extracts every number from the generated
report and compares it to grounding. Claims that deviate >5% are flagged in
``confidence_notes`` — surfaced to the user, never silently deleted.

Key concept: anti-hallucination by verification. We don't trust the LLM's
numbers; we check them against data we fetched ourselves.

Implemented in Phase 5.
"""
