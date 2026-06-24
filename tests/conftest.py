"""Shared pytest fixtures.

Centralises the boilerplate that many tests repeat: test settings (with dummy
keys so nothing real is ever called) and a canned ``FinalReport`` so UI/render
tests are decoupled from the live pipeline.

Key concept: fixtures keep tests fast, offline, and free — a test that needs a
``Settings`` or a sample report asks for it as a parameter instead of rebuilding
it (and re-pasting the env-var dance) each time.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from neowatch.agents.models import (
    Citation,
    FinalReport,
    ImageAsset,
    NEOEventReport,
    RiskTableRow,
)
from neowatch.config import Settings, get_settings


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Yield a ``Settings`` populated with dummy keys; clear the cache around it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def sample_final_report() -> FinalReport:
    """A fully-populated report fixture for render/UI tests (no pipeline run)."""
    return FinalReport(
        query="Which asteroids approach Earth this week?",
        executive_summary="One notable close approach this week; nothing hazardous.",
        neo_events=[
            NEOEventReport(
                object_id="X1",
                name="(2024 X1)",
                close_approach_date="2026-06-25",
                miss_distance_ld=12.0,
                velocity_km_s=18.1,
                diameter_max_m=480.0,
                risk_band="low",
                summary="A routine, well-separated flyby.",
            )
        ],
        orbital_risk_table=[
            RiskTableRow(
                name="(2024 X1)",
                miss_distance_ld=12.0,
                velocity_km_s=18.1,
                diameter_max_m=480.0,
                risk_band="low",
            )
        ],
        literature_insights="Recent work focuses on detecting sub-100 m objects.",
        confidence_notes=["Fact-check confidence: high."],
        data_sources=[
            Citation(
                source_type="arxiv",
                title="Detecting small near-Earth asteroids",
                identifier="2401.00001",
                url="https://arxiv.org/abs/2401.00001",
            ),
            Citation(
                source_type="nasa_neows",
                title="NASA NeoWs close-approach data",
                url="https://api.nasa.gov/",
            ),
        ],
        images=[
            ImageAsset(
                title="Andromeda Galaxy",
                date="2026-06-24",
                url="https://apod.nasa.gov/apod/image/andromeda.jpg",
                media_type="image",
                credit="Andromeda Galaxy — credit: NASA / APOD",
                explanation="A neighbouring spiral galaxy.",
                local_path=None,
            )
        ],
        prompt_version="synthesis-v1",
    )
