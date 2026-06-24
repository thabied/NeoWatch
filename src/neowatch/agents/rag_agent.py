"""RAG agent.

Retrieves relevant scientific literature from the local vector store. Takes
keywords from the orchestrator, runs the RAG retrieve pipeline (cosine search +
BM25 re-rank), and returns ``RetrievedPaper`` objects with citations. Triggers
arXiv ingestion first if the collection is empty or stale.

Key concept: this agent does *no* LLM work — it is a thin, typed adapter over
the Phase 3 pipeline, so the orchestrator can treat literature lookup like any
other agent call.
"""

from __future__ import annotations

from ..context import AgentContext, AgentResult
from ..rag.ingest import ingest_arxiv_papers
from ..rag.retrieve import retrieve
from ..rag.store import is_stale
from .base import BaseAgent

# Tiny stopword set for the fallback keyword extractor (kept deliberately small).
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is", "are",
    "what", "which", "any", "about", "with", "this", "that", "me", "show", "tell",
}


class RAGAgent(BaseAgent):
    """Return ranked arXiv papers relevant to the query's keywords."""

    async def run(self, context: AgentContext) -> AgentResult:
        """Ingest if the store is stale, then retrieve the top papers.

        Keywords come from ``context.session_cache['keywords']`` when the
        orchestrator has set them; otherwise they are derived from the raw query.
        """
        keywords = self._keywords(context)
        try:
            if is_stale():
                await ingest_arxiv_papers()
            papers = retrieve(keywords, top_k=5)
        except Exception as exc:  # noqa: BLE001 — surface any failure as a typed result
            self.logger.warning("rag_agent.failed", error=str(exc))
            return AgentResult(agent_name="RAGAgent", success=False, error=str(exc))

        self.logger.info("rag_agent.retrieved", keywords=keywords, count=len(papers))
        return AgentResult(agent_name="RAGAgent", success=True, data=papers)

    def _keywords(self, context: AgentContext) -> list[str]:
        cached = context.session_cache.get("keywords")
        if isinstance(cached, list) and cached:
            return [str(k) for k in cached]
        tokens = (context.query or "").lower().split()
        return [t for t in tokens if t not in _STOPWORDS and len(t) > 2] or tokens
