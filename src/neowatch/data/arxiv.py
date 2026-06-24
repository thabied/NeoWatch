"""arXiv client.

Searches arXiv's Atom feed and parses entries into ``ArxivPaper`` objects. No
API key. This is the source the RAG knowledge base is built from (Phase 3).
"""

from __future__ import annotations

import feedparser
import httpx

from .http import retry_external
from .models import ArxivPaper

_BASE = "https://export.arxiv.org/api/query"


def parse_arxiv(feed_text: str) -> list[ArxivPaper]:
    """Parse an arXiv Atom feed (XML string) into typed papers.

    arXiv prefers ``link`` for the abstract page but always provides ``id`` (also
    a URL), so we fall back to it. Categories come from the entry ``tags``.
    """
    parsed = feedparser.parse(feed_text)
    papers: list[ArxivPaper] = []
    for entry in parsed.entries:
        papers.append(
            ArxivPaper(
                id=entry.get("id", ""),
                title=" ".join(entry.get("title", "").split()),
                summary=entry.get("summary", "").strip(),
                authors=[a.get("name", "") for a in entry.get("authors", [])],
                published=entry.get("published", ""),
                link=entry.get("link") or entry.get("id", ""),
                categories=[t.get("term", "") for t in entry.get("tags", [])],
            )
        )
    return papers


@retry_external
async def search_arxiv(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 20,
) -> list[ArxivPaper]:
    """Search arXiv (e.g. ``"all:near earth asteroid"``) and return papers."""
    resp = await client.get(
        _BASE,
        params={"search_query": query, "start": "0", "max_results": str(max_results)},
    )
    resp.raise_for_status()
    return parse_arxiv(resp.text)
