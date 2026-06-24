"""Vector store.

Manages the ChromaDB ``neowatch_papers`` collection: get/create the persistent
collection, upsert chunks, count, and check staleness.

Key concept: ChromaDB is a local vector database — it stores embeddings and does
fast approximate nearest-neighbour search (HNSW) so we don't hand-roll similarity
maths. We configure cosine distance explicitly (``hnsw:space``), because Chroma's
default is squared-L2 and the spec/retrieval reason in cosine terms.

Ingest-timestamp note: the spec suggests storing this in the collection metadata,
but Chroma bundles HNSW config into that same metadata and resists mutating it
post-creation. A small sidecar file is simpler, robust, and trivially testable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection

from ..config import get_settings
from .embed import get_embedding_function
from .models import Chunk

_COLLECTION_NAME = "neowatch_papers"
_INGEST_MARKER = "neowatch_ingest.json"


def _persist_dir() -> Path:
    return Path(get_settings().chroma_persist_dir)


def get_collection() -> Collection:
    """Return the persistent ``neowatch_papers`` collection (cosine distance)."""
    client = chromadb.PersistentClient(path=str(_persist_dir()))
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        # chromadb's EmbeddingFunction generic is contravariant over an
        # Embeddable (docs|images) input; our docs-only function is narrower, so
        # mypy flags the variance. Functionally correct — accept the boundary.
        embedding_function=get_embedding_function(),  # type: ignore[arg-type]
        metadata={"hnsw:space": "cosine"},
    )


def upsert_chunks(chunks: list[Chunk]) -> None:
    """Insert/update chunks. Chroma embeds the ``documents`` via the collection's
    embedding function. Chunk metadata must be scalar (str/int/float/bool)."""
    if not chunks:
        return
    collection = get_collection()
    collection.upsert(
        ids=[f"{c.paper_id}::{c.chunk_index}" for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[{k: v for k, v in c.metadata.items() if v is not None} for c in chunks],
    )


def count() -> int:
    """Number of chunks currently stored."""
    return get_collection().count()


def _marker_path() -> Path:
    return _persist_dir() / _INGEST_MARKER


def mark_ingested() -> None:
    """Record 'now' as the last successful ingest time."""
    _persist_dir().mkdir(parents=True, exist_ok=True)
    _marker_path().write_text(json.dumps({"last_ingest": datetime.now(UTC).isoformat()}))


def is_stale(max_age_days: int = 7) -> bool:
    """True if the knowledge base has never been built or is older than the limit."""
    marker = _marker_path()
    if not marker.exists():
        return True
    try:
        last = datetime.fromisoformat(json.loads(marker.read_text())["last_ingest"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return True
    return datetime.now(UTC) - last > timedelta(days=max_age_days)
