"""Unit tests for the BM25 re-ranking logic.

These hit the *pure* ``bm25_scores`` function — no Chroma, no network — so the
ranking behaviour is verified in isolation from the vector store.
"""

from __future__ import annotations

from neowatch.rag.retrieve import bm25_scores


def test_bm25_ranks_keyword_matches_higher() -> None:
    """A doc matching both query terms outranks a partial match, which outranks none."""
    docs = [
        "the torino scale rates asteroid impact hazard levels",  # both terms
        "a recipe for chocolate cake with sugar and flour",      # neither term
        "near earth asteroid orbit determination techniques",    # one term
    ]
    scores = bm25_scores(docs, ["asteroid", "impact"])

    assert len(scores) == 3
    assert scores[0] == max(scores)  # most relevant
    assert scores[1] == min(scores)  # irrelevant cake doc scores lowest
    assert scores[0] > scores[2] > scores[1]


def test_bm25_empty_corpus() -> None:
    """An empty candidate list returns no scores (guard against BM25 crashing)."""
    assert bm25_scores([], ["asteroid"]) == []
