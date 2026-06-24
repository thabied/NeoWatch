"""Anthropic client helper.

One place to build the async Claude client from settings, so every agent shares
the same construction (and tests can inject a fake in its place).

Key concept: the API key is read from ``Settings`` (a ``SecretStr``) only at the
point of use via ``.get_secret_value()`` — it is never logged or hardcoded.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

from .config import Settings


def get_anthropic_client(settings: Settings) -> AsyncAnthropic:
    """Return an ``AsyncAnthropic`` client authenticated from settings."""
    return AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
