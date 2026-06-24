"""Versioned system prompts.

Named, version-tagged prompt constants (e.g. ``ORCHESTRATOR_V1``,
``SYNTHESIS_V1``) defining each agent's role, output-format constraints, and
domain boundaries.

Key concept: treating prompts as versioned artifacts (not magic strings) lets us
track which prompt produced which behaviour and roll changes back if quality drops.

Implemented in Phase 6.
"""
