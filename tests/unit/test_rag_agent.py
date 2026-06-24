"""Unit tests for RAGAgent (offline).

RAGAgent is a thin adapter over the Phase 3 pipeline, so here we stub ``is_stale``
and ``retrieve`` to confirm the agent extracts keywords and passes typed
``RetrievedPaper`` objects straight through — the live retrieval itself is covered
by the Phase 3 integration test.
"""

from __future__ import annotations

from typing import Any

import pytest

from neowatch.agents import rag_agent as rag_agent_module
from neowatch.agents.rag_agent import RAGAgent
from neowatch.config import get_settings
from neowatch.context import AgentContext
from neowatch.rag.models import RetrievedPaper


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


async def test_rag_agent_returns_typed_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh store skips ingest; retrieve's papers pass straight through."""
    settings = _settings(monkeypatch)
    captured: dict[str, Any] = {}

    paper = RetrievedPaper(
        arxiv_id="1234.5678",
        title="Asteroid impact risk",
        abstract="...",
        published="2024-01-01",
        url="https://arxiv.org/abs/1234.5678",
        relevance_score=1.0,
    )

    monkeypatch.setattr(rag_agent_module, "is_stale", lambda: False)

    def fake_retrieve(keywords: list[str], top_k: int = 5) -> list[RetrievedPaper]:
        captured["keywords"] = keywords
        return [paper]

    monkeypatch.setattr(rag_agent_module, "retrieve", fake_retrieve)

    agent = RAGAgent(settings)
    context = AgentContext(query="what is the Torino impact probability")
    result = await agent.run(context)

    assert result.success is True
    assert result.data == [paper]
    # Stopwords ("what", "is", "the") are stripped from the derived keywords.
    assert "torino" in captured["keywords"]
    assert "the" not in captured["keywords"]
    get_settings.cache_clear()


async def test_rag_agent_prefers_cached_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator-supplied keywords in session_cache win over the raw query."""
    settings = _settings(monkeypatch)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(rag_agent_module, "is_stale", lambda: False)
    monkeypatch.setattr(
        rag_agent_module,
        "retrieve",
        lambda keywords, top_k=5: captured.setdefault("keywords", keywords) and [],
    )

    agent = RAGAgent(settings)
    context = AgentContext(query="ignored", session_cache={"keywords": ["palermo", "scale"]})
    await agent.run(context)
    assert captured["keywords"] == ["palermo", "scale"]
    get_settings.cache_clear()
