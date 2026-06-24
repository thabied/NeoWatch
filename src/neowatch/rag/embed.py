"""Embeddings.

Turns text into 384-dimensional vectors using ChromaDB's built-in ONNX build of
``all-MiniLM-L6-v2`` (via ``onnxruntime``) — the same model the spec calls for,
without the ``torch``/``sentence-transformers`` stack that has no Intel-Mac wheel.

THIS MODULE IS THE SINGLE SWAP POINT. To move to sentence-transformers (or a paid
embedding API) later, change only ``get_embedding_function`` — nothing downstream
(store, ingest, retrieve) needs to know which backend produced the vectors.

Key concept: embeddings map text to points in a vector space where "close" means
"similar in meaning" — the basis for semantic search. Running locally on CPU means
each embedding is free and private (trade-off: lower ceiling than a paid API, but
zero cost and no data leaves the machine).
"""

from __future__ import annotations

from chromadb.api.types import EmbeddingFunction
from chromadb.utils import embedding_functions

# The embedding model is heavy to load, so we build it once and cache it.
_embedding_function: EmbeddingFunction[list[str]] | None = None


def get_embedding_function() -> EmbeddingFunction[list[str]]:
    """Return the process-wide embedding function (lazily constructed once).

    Chroma collections take an ``EmbeddingFunction`` directly, so the vector store
    uses this object to embed both documents (at ingest) and queries (at search) —
    guaranteeing both sides use the *same* model, which is essential: vectors from
    different models are not comparable.
    """
    global _embedding_function
    if _embedding_function is None:
        # Downloads the ONNX model (~80MB) into a local cache on first use.
        _embedding_function = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_function


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed raw texts to vectors (for tests and any direct embedding needs)."""
    embed = get_embedding_function()
    return [[float(x) for x in vector] for vector in embed(texts)]
