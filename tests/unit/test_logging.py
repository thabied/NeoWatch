"""Tests for the structured-logging secret redaction."""

from __future__ import annotations

from neowatch.logging_config import strip_secrets


def test_strip_secrets_redacts_api_key() -> None:
    """An Anthropic-style key in a log field is masked, not emitted."""
    event = {"event": "calling api", "auth": "sk-ant-abc123XYZ"}
    out = strip_secrets(None, "info", event)  # logger arg unused by the processor
    assert "sk-ant-abc123XYZ" not in str(out)
    assert "[REDACTED]" in out["auth"]


def test_strip_secrets_redacts_email() -> None:
    """Email addresses are masked too."""
    event = {"event": "user", "contact": "person@example.com"}
    out = strip_secrets(None, "info", event)
    assert "person@example.com" not in str(out)


def test_strip_secrets_leaves_clean_text() -> None:
    """Non-secret fields pass through unchanged."""
    event = {"event": "startup", "version": "0.1.0"}
    out = strip_secrets(None, "info", event)
    assert out["version"] == "0.1.0"
