"""Live integration test for the full RAG pipeline.

Runs a real arXiv ingest into a temporary ChromaDB and retrieves from it. Skipped
by default (downloads the ONNX model + hits arXiv). Run deliberately with:

    NEOWATCH_RUN_INTEGRATION=1 pytest tests/integration/test_rag_pipeline.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from neowatch.config import get_settings
from neowatch.rag.ingest import ingest_arxiv_papers
from neowatch.rag.retrieve import retrieve
from neowatch.rag.store import is_stale

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("NEOWATCH_RUN_INTEGRATION") != "1",
        reason="set NEOWATCH_RUN_INTEGRATION=1 to run the live RAG pipeline",
    ),
]


async def test_ingest_then_retrieve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate the vector store in a temp dir so we never touch the real .chroma.
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()

    # Build the knowledge base.
    count = await ingest_arxiv_papers(force=True)
    assert count > 0, "ingest should populate the collection"
    assert is_stale() is False, "marker should make a just-built collection fresh"

    # Idempotency: a non-forced re-run on a fresh collection is a no-op.
    assert await ingest_arxiv_papers(force=False) == count

    # Retrieve returns at most top_k, sorted by descending relevance.
    results = retrieve(["asteroid", "impact", "hazard"], top_k=5)
    assert 0 < len(results) <= 5
    assert results[0].arxiv_id
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)

    get_settings.cache_clear()  # don't leak the temp dir into other tests
