"""Unit tests for vector-store staleness tracking (offline — no Chroma/network).

Only the sidecar ingest-marker logic is exercised here; it doesn't touch ChromaDB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from neowatch.config import get_settings
from neowatch.rag import store


def _use_tmp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()


def test_is_stale_true_when_never_ingested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_store(tmp_path, monkeypatch)
    assert store.is_stale() is True
    get_settings.cache_clear()


def test_mark_ingested_makes_collection_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_store(tmp_path, monkeypatch)
    store.mark_ingested()
    assert store.is_stale() is False
    get_settings.cache_clear()


def test_is_stale_true_when_timestamp_too_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_store(tmp_path, monkeypatch)
    store.mark_ingested()
    # Simulate an 8-day-old ingest (limit is 7).
    old = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    store._marker_path().write_text(json.dumps({"last_ingest": old}))
    assert store.is_stale(max_age_days=7) is True
    get_settings.cache_clear()
