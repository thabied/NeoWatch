"""Live end-to-end test for the full pipeline.

Runs a real query through the orchestrator (Sonnet) -> specialist agents (real
NASA + arXiv calls, Haiku) -> synthesis (Sonnet) -> fact-check, and asserts a
well-formed, cited ``FinalReport`` comes back. Skipped by default — it spends
real API tokens and hits external services. Run deliberately with:

    NEOWATCH_RUN_INTEGRATION=1 pytest tests/integration/test_end_to_end.py -v
"""

from __future__ import annotations

import os

import pytest

from neowatch.agents.models import FinalReport
from neowatch.pipeline import run_query

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("NEOWATCH_RUN_INTEGRATION") != "1",
        reason="set NEOWATCH_RUN_INTEGRATION=1 to run the live end-to-end pipeline",
    ),
]


async def test_run_query_produces_grounded_report() -> None:
    """The spec example query returns a report with risk rows and citations."""
    report = await run_query(
        "Which near-Earth asteroids approach Earth this week, and how risky are they?"
    )

    assert isinstance(report, FinalReport)
    assert report.executive_summary.strip()  # non-empty narrative
    assert len(report.orbital_risk_table) >= 1  # at least one analysed object
    assert len(report.data_sources) >= 1  # at least one citation
    # The fact-check always leaves at least a confidence note.
    assert any("confidence" in note.lower() for note in report.confidence_notes)


async def test_off_topic_query_is_rejected_end_to_end() -> None:
    """An off-topic query is rejected and returns a valid (empty) report."""
    report = await run_query("What is the best pizza topping?")
    assert isinstance(report, FinalReport)
    assert report.orbital_risk_table == []
    assert "not processed" in report.executive_summary.lower()
