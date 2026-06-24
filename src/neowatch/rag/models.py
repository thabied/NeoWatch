"""RAG data models.

``Chunk`` is the unit we embed and store (a slice of a paper's text plus the
metadata needed to reconstruct its parent). ``RetrievedPaper`` is a ranked search
result handed to synthesis.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """One embeddable slice of a paper's text."""

    text: str
    paper_id: str
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedPaper(BaseModel):
    """A paper returned by retrieval, with its relevance score (higher = better)."""

    arxiv_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str
    published: str
    url: str
    relevance_score: float
