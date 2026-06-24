"""arXiv ingestion.

``ingest_arxiv_papers()`` runs the seed queries against the arXiv client, chunks
the abstracts, attaches each parent paper's metadata to every chunk, and upserts
them into ChromaDB. Idempotent: skips when the collection is already fresh unless
``force=True``.

Key concept: this is the one-time / weekly "build the knowledge base" step, kept
separate from per-query retrieval so retrieval stays fast and read-only.
"""

from __future__ import annotations

import structlog

from ..data.arxiv import search_arxiv
from ..data.http import get_async_client
from ..data.models import ArxivPaper
from .chunk import chunk_text
from .models import Chunk
from .store import count, is_stale, mark_ingested, upsert_chunks

logger = structlog.get_logger(__name__)

# Seed queries that define the knowledge base's subject area.
_SEED_QUERIES = [
    "all:near earth object hazard",
    "all:asteroid impact risk assessment",
    "all:planetary defense asteroid deflection",
    "all:Torino scale Palermo scale impact probability",
]
_RESULTS_PER_QUERY = 20


def _paper_metadata(paper: ArxivPaper) -> dict[str, str]:
    """Flatten a paper's fields into Chroma-safe scalar metadata."""
    return {
        "arxiv_id": paper.id,
        "title": paper.title,
        "authors": "; ".join(paper.authors),  # Chroma metadata can't hold lists
        "published": paper.published,
        "url": str(paper.link),
        "abstract": paper.summary,
    }


async def ingest_arxiv_papers(force: bool = False) -> int:
    """Build/refresh the knowledge base. Returns the resulting chunk count."""
    if not force and not is_stale():
        existing = count()
        logger.info("rag.ingest.skipped_fresh", chunks=existing)
        return existing

    # Fetch all seed queries, de-duplicating papers by arXiv id.
    papers: dict[str, ArxivPaper] = {}
    async with get_async_client() as client:
        for query in _SEED_QUERIES:
            for paper in await search_arxiv(client, query, max_results=_RESULTS_PER_QUERY):
                papers.setdefault(paper.id, paper)

    # Chunk each abstract and tag every chunk with its parent's metadata.
    all_chunks: list[Chunk] = []
    for paper in papers.values():
        meta = _paper_metadata(paper)
        for chunk in chunk_text(paper.summary, paper_id=paper.id):
            chunk.metadata = meta
            all_chunks.append(chunk)

    upsert_chunks(all_chunks)
    mark_ingested()
    total = count()
    logger.info("rag.ingest.complete", papers=len(papers), chunks=total)
    return total
