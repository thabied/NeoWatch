"""Input sanitisation.

Regex-based prompt-injection detection: ``detect_injection(query)`` looks for
patterns like ``ignore previous``, ``system:``, ``<|``, ``HUMAN:``.

Key concept: a cheap, deterministic first line of defence against prompt
injection — runs before the LLM-based domain check so obvious attacks never
reach the model.

Implemented in Phase 5.
"""
