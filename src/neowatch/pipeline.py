"""Top-level orchestration pipeline.

Exposes ``run_query(query) -> FinalReport``: the single high-level entry the UI
calls. It chains the stages together — input guardrail -> orchestrator (which
dispatches the specialist agents) -> synthesis -> fact-check — and returns a
validated report.

Key concept: one thin coordinator so the UI never talks to agents directly.

Implemented in Phase 6.
"""
