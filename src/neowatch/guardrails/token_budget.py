"""Token-budget guardrail (context window).

``TokenBudgetGuardrail`` tracks tokens used against a per-agent budget: warn at
70%, compress history at 85% (Haiku summarises old turns into a compact summary +
the last 3 turns), hard-stop with partial results at 95%.

Key concept: practical context-window management. LLM context is finite and
priced per token, so we actively prune/summarise rather than letting history grow
unbounded.

Implemented in Phase 5.
"""
