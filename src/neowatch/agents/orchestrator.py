"""Orchestrator agent.

The planner/coordinator (Claude Sonnet). Validates the query through the domain
guardrail, then runs a tool-use loop where each specialist agent is exposed as a
tool, deciding which to invoke and in what order. Manages the token budget and
retries failed agents.

Key concept: this is the "agentic" core — the LLM plans and dispatches work
rather than following a fixed script.

Implemented in Phase 6.
"""
