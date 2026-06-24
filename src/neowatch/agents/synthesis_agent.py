"""Synthesis agent.

Combines all specialist outputs into one grounded, cited ``FinalReport`` (Claude
Sonnet). Before generating, it builds a single source-of-truth grounding context
the model is instructed to stay within; after generating, the fact-check layer
verifies every quantitative claim against that grounding.

Key concept: grounding + post-hoc fact-checking is the anti-hallucination
strategy — the model is fenced in before, and audited after.

Implemented in Phase 6.
"""
