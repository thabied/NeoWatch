"""Tests for the configuration system."""

from __future__ import annotations

import pytest

from neowatch.config import Settings

# ``_env_file=None`` isolates these tests from the developer's real ``.env`` so
# they assert against code defaults, deterministically, on any machine.


def test_settings_accepts_explicit_values() -> None:
    """Settings can be constructed directly (handy for isolated tests)."""
    settings = Settings(
        anthropic_api_key="sk-ant-test", nasa_api_key="nasa-test", _env_file=None
    )
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test"
    assert settings.nasa_api_key.get_secret_value() == "nasa-test"


def test_settings_defaults() -> None:
    """Unset tunables fall back to their documented defaults."""
    settings = Settings(
        anthropic_api_key="sk-ant-test", nasa_api_key="nasa-test", _env_file=None
    )
    assert settings.haiku_model == "claude-haiku-4-5"
    assert settings.sonnet_model == "claude-sonnet-4-6"
    assert settings.max_tokens_per_agent == 4096
    assert settings.log_level == "INFO"
    assert settings.serp_api_key is None


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables take precedence and populate the model."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fromenv")
    monkeypatch.setenv("NASA_API_KEY", "nasa-fromenv")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-fromenv"
    assert settings.log_level == "DEBUG"


def test_secret_is_masked_in_repr() -> None:
    """SecretStr must not expose its value in string/repr output."""
    settings = Settings(anthropic_api_key="sk-ant-supersecret", nasa_api_key="x")
    assert "supersecret" not in repr(settings)
    assert "supersecret" not in str(settings.anthropic_api_key)
