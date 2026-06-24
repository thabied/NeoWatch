"""Unit tests for sentence-aware chunking.

First run downloads the ``punkt`` sentence tokenizer (small, cached thereafter),
per the Phase 3 verification checklist.
"""

from __future__ import annotations

import nltk

from neowatch.rag.chunk import chunk_text


def _make_text(n_sentences: int) -> str:
    return " ".join(
        f"Sentence number {i} is about near earth asteroids." for i in range(n_sentences)
    )


def test_chunk_text_windows_with_overlap() -> None:
    """Long text splits into multiple windows that overlap and index in order."""
    text = _make_text(12)
    chunks = chunk_text(text, "paper-1", max_tokens=20, overlap=6)

    assert len(chunks) >= 2
    # chunk_index is sequential from 0.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # All chunks belong to the same paper.
    assert all(c.paper_id == "paper-1" for c in chunks)
    # Size stays within the window budget plus the overlap headroom.
    assert all(len(c.text.split()) <= 20 + 6 for c in chunks)
    # Consecutive chunks share at least one sentence (the overlap). strict=False
    # is intentional: chunks[1:] is one shorter than chunks (pairwise iteration).
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert set(nltk.sent_tokenize(a.text)) & set(nltk.sent_tokenize(b.text))


def test_chunk_text_short_text_single_chunk() -> None:
    """Text under the budget yields exactly one chunk."""
    chunks = chunk_text("One short sentence about asteroids.", "paper-2")
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0


def test_chunk_text_empty() -> None:
    """Empty text yields no chunks (not an error)."""
    assert chunk_text("", "paper-3") == []
