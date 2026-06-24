"""Retrieval.

``retrieve(keywords, top_k=5)``: Chroma embeds the query and does a cosine search
(recall-oriented, top-20), then BM25 re-ranks those candidates down to the best
``top_k`` ``RetrievedPaper`` (precision-oriented), de-duplicated by arXiv id.

Key concept: two-stage retrieval. Dense vector search captures *semantic*
similarity; BM25 (lexical keyword overlap) sharpens on the *exact* scientific terms
an embedding can blur (object designations, "Torino scale"). Combining them beats
either alone. See docs/RETRIEVAL_CONCEPTS.md for the full reasoning.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rank_bm25 import BM25Okapi

from .models import RetrievedPaper
from .store import get_collection

_RECALL_K = 20  # how many dense candidates to fetch before re-ranking


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def bm25_scores(documents: list[str], keywords: list[str]) -> list[float]:
    """Pure BM25 scoring: one relevance score per document for the keyword query.

    Kept separate from the Chroma I/O so the ranking logic is unit-testable with a
    tiny in-memory corpus and no network or vector store.
    """
    if not documents:
        return []
    corpus = [_tokenize(doc) for doc in documents]
    query = [token for kw in keywords for token in _tokenize(kw)]
    return [float(s) for s in BM25Okapi(corpus).get_scores(query)]


def _to_paper(metadata: Mapping[str, Any], score: float) -> RetrievedPaper:
    authors = str(metadata.get("authors", ""))
    return RetrievedPaper(
        arxiv_id=str(metadata.get("arxiv_id", "")),
        title=str(metadata.get("title", "")),
        authors=[a for a in authors.split("; ") if a],
        abstract=str(metadata.get("abstract", "")),
        published=str(metadata.get("published", "")),
        url=str(metadata.get("url", "")),
        relevance_score=score,
    )


def retrieve(keywords: list[str], top_k: int = 5) -> list[RetrievedPaper]:
    """Return up to ``top_k`` papers most relevant to ``keywords``."""
    result = get_collection().query(query_texts=[" ".join(keywords)], n_results=_RECALL_K)

    documents: list[str] = (result.get("documents") or [[]])[0]
    metadatas: list[Mapping[str, Any]] = (result.get("metadatas") or [[]])[0]
    if not documents:
        return []

    scores = bm25_scores(documents, keywords)
    ranked = sorted(zip(metadatas, scores, strict=True), key=lambda pair: pair[1], reverse=True)

    # De-duplicate by arXiv id, keeping each paper's best-scoring chunk.
    seen: set[str] = set()
    papers: list[RetrievedPaper] = []
    for metadata, score in ranked:
        arxiv_id = str(metadata.get("arxiv_id", ""))
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        papers.append(_to_paper(metadata, score))
        if len(papers) >= top_k:
            break
    return papers
