"""Unit tests for the pure UI renderers (no Gradio, no server)."""

from __future__ import annotations

from neowatch.agents.models import (
    Citation,
    FinalReport,
    ImageAsset,
    NEOEventReport,
    ReportSection,
    RiskTableRow,
)
from neowatch.ui.render import gallery_items, report_to_markdown, risk_table_dataframe


def _report() -> FinalReport:
    return FinalReport(
        query="asteroids this week",
        executive_summary="One notable close approach this week.",
        neo_events=[
            NEOEventReport(
                object_id="X1",
                name="(2024 X1)",
                miss_distance_ld=12.0,
                velocity_km_s=18.1,
                diameter_max_m=480.0,
                risk_band="low",
                summary="A routine flyby.",
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
        literature_insights="Detection of small NEOs is an active area.",
        confidence_notes=["Fact-check confidence: high."],
        data_sources=[
            Citation(
                source_type="arxiv",
                title="Detecting small NEOs",
                identifier="2401.00001",
                url="https://arxiv.org/abs/2401.00001",
            )
        ],
        images=[
            ImageAsset(
                title="Andromeda",
                date="2024-01-01",
                url="https://apod.nasa.gov/img.jpg",
                media_type="image",
                credit="Andromeda — credit: NASA / APOD",
                explanation="A galaxy.",
                local_path="/tmp/andromeda.png",
            )
        ],
    )


def test_markdown_contains_all_sections() -> None:
    """The narrative pane includes summary, events, insights, notes, and sources."""
    md = report_to_markdown(_report())
    assert "asteroids this week" in md
    assert "One notable close approach" in md
    assert "(2024 X1)" in md
    assert "A routine flyby." in md
    assert "Literature insights" in md
    assert "Confidence notes" in md
    assert "Fact-check confidence: high." in md
    # Citation renders as a markdown link with its identifier.
    assert "[Detecting small NEOs (2401.00001)](https://arxiv.org/abs/2401.00001)" in md


def test_risk_dataframe_shape_and_values() -> None:
    """The risk table is a DataFrame with the expected columns and rounded values."""
    df = risk_table_dataframe(_report())
    assert list(df.columns) == ["Object", "Miss (LD)", "Velocity (km/s)", "Max size (m)", "Risk"]
    assert len(df) == 1
    assert df.iloc[0]["Object"] == "(2024 X1)"
    assert df.iloc[0]["Risk"] == "low"


def test_empty_report_yields_empty_but_columned_table() -> None:
    """A report with no objects still produces a stable, empty dataframe."""
    df = risk_table_dataframe(FinalReport(query="nothing"))
    assert len(df) == 0
    assert list(df.columns) == ["Object", "Miss (LD)", "Velocity (km/s)", "Max size (m)", "Risk"]


def test_gallery_items_prefer_local_path_and_carry_credit() -> None:
    """Gallery uses the cached local copy and pairs it with the attribution credit."""
    items = gallery_items(_report())
    assert items == [("/tmp/andromeda.png", "Andromeda — credit: NASA / APOD")]


def test_generic_report_section_renders_title_body_and_table() -> None:
    """A non-NEO vertical's section renders as a heading, prose, and a markdown table."""
    report = FinalReport(
        query="space weather now",
        report_sections=[
            ReportSection(
                title="Space weather",
                body_markdown="A minor geomagnetic storm is underway.",
                rows=[{"Metric": "Kp", "Value": "5"}, {"Metric": "Storm", "Value": "G1"}],
            )
        ],
    )
    md = report_to_markdown(report)
    assert "### Space weather" in md
    assert "A minor geomagnetic storm is underway." in md
    # Header row, separator, and both data rows of the markdown table.
    assert "| Metric | Value |" in md
    assert "| --- | --- |" in md
    assert "| Kp | 5 |" in md
    assert "| Storm | G1 |" in md


def test_section_without_rows_renders_no_table() -> None:
    """A section with no rows renders its prose but emits no empty table."""
    report = FinalReport(
        query="q",
        report_sections=[ReportSection(title="Notes", body_markdown="Just prose.")],
    )
    md = report_to_markdown(report)
    assert "### Notes" in md
    assert "Just prose." in md
    assert "|" not in md  # no table pipes at all
