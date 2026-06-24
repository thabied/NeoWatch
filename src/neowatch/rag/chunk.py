"""Text chunking.

Splits paper text into ~512-token windows with 50-token overlap, breaking on
sentence boundaries with ``nltk`` so chunks never split mid-sentence.

Key concept: chunking keeps each embedded unit small enough to be semantically
focused (a giant chunk averages many ideas into one blurry vector); the overlap
stops us losing meaning that straddles a boundary.

Token counting note: we approximate "tokens" by whitespace-separated words. The
real model tokenizer would differ slightly, but for *sizing* chunks a word count
is a fine, dependency-free proxy.
"""

from __future__ import annotations

import nltk

from .models import Chunk

_MAX_TOKENS = 512
_OVERLAP_TOKENS = 50


def _ensure_punkt() -> None:
    """Download the sentence tokenizer on first use, then cache it locally."""
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)


def _tokens(text: str) -> int:
    return len(text.split())


def _overlap_tail(sentences: list[str], overlap: int) -> tuple[list[str], int]:
    """Return the trailing sentences whose combined size is ~``overlap`` tokens."""
    tail: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        n = _tokens(sentence)
        if total + n > overlap and tail:
            break
        tail.insert(0, sentence)
        total += n
    return tail, total


def chunk_text(
    text: str,
    paper_id: str,
    *,
    max_tokens: int = _MAX_TOKENS,
    overlap: int = _OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split ``text`` into overlapping, sentence-aligned ``Chunk`` windows."""
    _ensure_punkt()
    sentences = nltk.sent_tokenize(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    window: list[str] = []
    window_tokens = 0
    index = 0

    for sentence in sentences:
        n = _tokens(sentence)
        # Close the current window before it would exceed the budget.
        if window and window_tokens + n > max_tokens:
            chunks.append(
                Chunk(text=" ".join(window), paper_id=paper_id, chunk_index=index)
            )
            index += 1
            window, window_tokens = _overlap_tail(window, overlap)
        window.append(sentence)
        window_tokens += n

    if window:
        chunks.append(Chunk(text=" ".join(window), paper_id=paper_id, chunk_index=index))
    return chunks
