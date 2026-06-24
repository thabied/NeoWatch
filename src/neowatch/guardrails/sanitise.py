"""Input sanitisation.

Regex-based prompt-injection detection: ``detect_injection(query)`` looks for
patterns like ``ignore previous``, ``system:``, ``<|...|>``, ``HUMAN:``.

Key concept: a cheap, deterministic first line of defence against prompt
injection. It runs *before* the LLM-based domain check, so the most obvious
attacks are caught without spending a single token — and, crucially, the
attacker's text never reaches the model that they're trying to manipulate.

This is a heuristic, not a proof: it catches known phrasings, not every possible
attack. Layered with the domain classifier and the output fact-check, it raises
the cost of an attack without claiming to be airtight.
"""

from __future__ import annotations

import re

# Each pattern targets a known prompt-injection tactic. Case-insensitive so
# "Ignore Previous" and "IGNORE PREVIOUS" are caught the same way.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # "ignore/disregard/forget [the] previous/above/prior instructions"
    re.compile(r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|above|prior|earlier)\b", re.I),
    # Role-play / persona overrides: "you are now", "act as", "pretend to be"
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\b(act as|pretend to be|roleplay as)\b", re.I),
    # Fake conversation turns / role markers used to smuggle instructions
    re.compile(r"(^|\n)\s*(system|assistant|human|user)\s*:", re.I),
    # Chat-template special tokens, e.g. <|im_start|>, <|endoftext|>
    re.compile(r"<\|.*?\|>"),
    # Attempts to exfiltrate the system prompt
    re.compile(r"\b(reveal|show|print|repeat)\b.{0,30}\b(system )?prompt\b", re.I),
    # "new instructions:" style hijacks
    re.compile(r"\bnew instructions?\b", re.I),
]


def detect_injection(query: str) -> bool:
    """Return True if the query matches any known prompt-injection pattern.

    Args:
        query: The raw user input.

    Returns:
        True if a suspicious pattern is present (the caller should reject), else
        False. A False result is *not* a guarantee of safety — it only means no
        known pattern matched.
    """
    return any(pattern.search(query) for pattern in _INJECTION_PATTERNS)
