"""Application configuration.

Loads all settings and secrets from the environment (``.env``) via
``pydantic-settings``, so nothing is hardcoded and secrets never get committed.

Key concept: a single ``Settings`` object is the one place the rest of the app
reads configuration from. ``get_settings()`` is cached so we build it once per
process and reuse it everywhere (cheap, consistent, easy to mock in tests).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, populated from environment / ``.env``.

    Field names map case-insensitively to environment variables, so
    ``anthropic_api_key`` is filled from ``ANTHROPIC_API_KEY``.

    Secrets use ``SecretStr`` so their values are masked in logs and tracebacks;
    call ``.get_secret_value()`` only at the point of use (e.g. an API client).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unrelated env vars instead of erroring
    )

    # --- Required secrets ---
    anthropic_api_key: SecretStr
    nasa_api_key: SecretStr

    # --- Optional secrets ---
    serp_api_key: SecretStr | None = None

    # --- Model routing (cheap model for tool calls, capable model for reasoning) ---
    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"

    # --- Cost / context guardrails ---
    token_budget_per_session: int = 200_000
    max_tokens_per_agent: int = 4096

    # --- Local paths / logging ---
    chroma_persist_dir: str = ".chroma"
    # Where resized APOD images are written. The Gradio server must be told to
    # serve from here (via ``allowed_paths``), since Gradio 4+ refuses to serve
    # arbitrary local files for security — see ``main.py`` / root ``app.py``.
    image_cache_dir: str = ".image_cache"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached ``Settings`` instance.

    The ``lru_cache`` means construction (and ``.env`` parsing) happens once;
    every later call returns the same object. Tests can clear it with
    ``get_settings.cache_clear()`` when they need a fresh read.

    Returns:
        The singleton ``Settings`` for this process.
    """
    # The pydantic.mypy plugin understands that BaseSettings populates its
    # fields from the environment, so no-arg construction type-checks cleanly.
    return Settings()
