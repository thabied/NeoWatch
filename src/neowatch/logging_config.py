"""Structured logging setup.

Configures ``structlog`` so every log line is machine-readable (JSON) and
carries consistent fields (timestamp, level, event). Includes a ``strip_secrets``
processor that redacts API-key- and email-like substrings before anything is
written — defence in depth so credentials can't leak into logs.

Key concept: structured logging > ``print()`` because logs become queryable
data, not just text. The whole app logs through this single configuration.
"""

from __future__ import annotations

import logging
import re

import structlog
from structlog.typing import EventDict, WrappedLogger

# Patterns we never want to appear in a log line, even by accident.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),  # Anthropic API keys
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # emails
]

_REDACTED = "[REDACTED]"


def strip_secrets(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor that redacts secret-like substrings from every field.

    Runs on each log event before rendering. Any string value matching a known
    secret pattern (API key, email) is masked, so secrets cannot leak via logs
    even if some other code accidentally logs them.

    Args:
        logger: The wrapped logger (unused; required by the structlog signature).
        method_name: The log method called, e.g. ``"info"`` (unused).
        event_dict: The mutable mapping of fields for this log event.

    Returns:
        The same ``event_dict`` with secret-like substrings replaced.
    """
    for key, value in event_dict.items():
        if isinstance(value, str):
            for pattern in _SECRET_PATTERNS:
                value = pattern.sub(_REDACTED, value)
            event_dict[key] = value
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure ``structlog`` for the whole process.

    Call once at startup. Sets up an ISO timestamp, a level field, the
    ``strip_secrets`` redaction processor, and a JSON renderer.

    Args:
        level: Minimum level to emit, e.g. ``"INFO"`` or ``"DEBUG"``.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            strip_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )
