"""Unit tests for the output fact-check layer (no LLM, fully deterministic)."""

from __future__ import annotations

import pytest

from neowatch.calc.models import OrbitalAnalysis, OrbitalReport
from neowatch.guardrails.factcheck import FactCheckLayer, build_grounding_context


def _report() -> OrbitalReport:
    """One object: 12 LD away, 18.1 km/s, up to 480 m across."""
    analysis = OrbitalAnalysis(
        object_id="2024 YR4",
        name="(2024 YR4)",
        miss_distance_km=4_612_800.0,
        miss_distance_ld=12.0,
        miss_distance_au=0.0308,
        velocity_km_s=18.1,
        velocity_class="moderate",
        diameter_min_m=120.0,
        diameter_max_m=480.0,
        is_potentially_hazardous=True,
    )
    return OrbitalReport(analyses=[analysis])


def test_grounding_context_collects_values_by_unit() -> None:
    """The grounding dict carries every trusted value under its unit key."""
    grounding = build_grounding_context(_report())
    assert grounding["ld"] == [12.0]
    assert grounding["km_s"] == [18.1]
    assert grounding["m"] == [120.0, 480.0]  # min and max diameter


def test_accurate_prose_is_high_confidence() -> None:
    """Prose that restates the computed figures raises no flags."""
    grounding = build_grounding_context(_report())
    text = "The object passes at 12 LD, travelling 18.1 km/s, up to 480 m wide."
    report = FactCheckLayer().check(text, grounding)
    assert report.flagged == []
    assert report.confidence == "high"


def test_inflated_number_is_flagged_with_pct_diff() -> None:
    """An exaggerated miss distance is flagged against the nearest source value."""
    grounding = build_grounding_context(_report())
    text = "Don't panic, but it screams past at just 18 LD."  # true value is 12 LD
    report = FactCheckLayer().check(text, grounding)

    assert len(report.flagged) == 1
    claim = report.flagged[0]
    assert claim.value == 18.0
    assert claim.source_value == 12.0
    assert claim.pct_diff == pytest.approx(50.0)  # (18-12)/12 * 100
    assert claim.location == "18 LD"
    assert report.confidence == "medium"


def test_claims_are_matched_by_unit_not_nearest_number() -> None:
    """A wrong LD value is not excused by a coincidentally-close km/s value.

    18 LD is wrong (true 12 LD) even though 18.1 km/s sits right next to it; unit
    matching keeps the two from being confused.
    """
    grounding = build_grounding_context(_report())
    report = FactCheckLayer().check("It is 18 LD away.", grounding)
    assert len(report.flagged) == 1
    assert report.flagged[0].source_value == 12.0  # matched LD, not the 18.1 km/s


def test_unknown_unit_is_not_flagged() -> None:
    """A number whose unit we don't ground (no values) is left unverified, not flagged."""
    grounding = build_grounding_context(_report())
    report = FactCheckLayer().check("The report spans 3 sections over 2 days.", grounding)
    assert report.flagged == []  # "sections"/"days" aren't grounded units
    assert report.confidence == "high"
