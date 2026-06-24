"""Guardrails package.

The safety layers: input validation (domain + injection checks), output
fact-checking against source data, and token-budget control. These are what make
the system trustworthy — refusing off-topic/malicious input and catching
hallucinated numbers before the user sees them.
"""
