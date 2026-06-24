"""Domain guardrail (input).

``DomainGuardrail.validate(query)`` runs before any API calls: checks length
(10-500 chars), scans for prompt-injection patterns, uses Haiku to classify
whether the query is in the space-science/NEO domain, and screens for harmful
requests. Off-topic or unsafe queries are rejected up front.

Key concept: fail fast and cheap — reject bad input before spending money on the
expensive multi-agent pipeline.

Implemented in Phase 5.
"""
