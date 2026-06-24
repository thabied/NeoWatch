"""Unit tests for the deterministic orbital/risk maths.

These are the trustworthy numerical core: pure functions with known inputs and
known outputs, so a regression in the maths is caught here with no LLM involved.
"""

from __future__ import annotations

import pytest

from neowatch.calc.orbital import (
    AU_KM,
    LUNAR_DISTANCE_KM,
    analyse_orbit,
    assess_risk,
    classify_velocity,
    cross_check_torino,
    detect_anomaly,
    km_to_au,
    km_to_lunar_distance,
    observation_window,
)


def test_unit_conversions() -> None:
    """km -> LD and km -> AU divide by the right constants."""
    assert km_to_lunar_distance(LUNAR_DISTANCE_KM) == pytest.approx(1.0)
    assert km_to_au(AU_KM) == pytest.approx(1.0)
    assert km_to_lunar_distance(384_400.0) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(2.0, "slow"), (10.0, "moderate"), (30.0, "fast"), (50.0, "very fast")],
)
def test_classify_velocity_bands(speed: float, expected: str) -> None:
    """Each band maps to its label at representative speeds."""
    assert classify_velocity(speed) == expected


def test_assess_risk_close_large_hazardous_is_high() -> None:
    """A close (<1 LD), >1 km, PHA object lands in the highest band."""
    risk = assess_risk(
        "x", miss_distance_ld=0.5, diameter_max_m=1200.0, is_potentially_hazardous=True
    )
    assert risk.risk_band == "high"
    assert risk.risk_score == 7  # 3 (close) + 3 (large) + 1 (PHA)


def test_assess_risk_far_small_is_negligible() -> None:
    """A distant, small, non-hazardous object scores negligible."""
    risk = assess_risk(
        "y", miss_distance_ld=50.0, diameter_max_m=10.0, is_potentially_hazardous=False
    )
    assert risk.risk_band == "negligible"
    assert risk.risk_score == 0


def test_cross_check_torino_consistency() -> None:
    """Heuristic band is cross-checked against an official Torino rating."""
    # Torino 8 -> expected "high"; our "high" is consistent.
    assert cross_check_torino(8, "high") is True
    # Torino 0 -> expected "negligible"; "high" is two bands away -> inconsistent.
    assert cross_check_torino(0, "high") is False
    # Off-by-one is tolerated: Torino 0 expects negligible, "low" is adjacent.
    assert cross_check_torino(0, "low") is True


def test_assess_risk_records_torino_crosscheck() -> None:
    """Passing a Torino rating populates the consistency flag."""
    risk = assess_risk(
        "z", miss_distance_ld=0.5, diameter_max_m=1200.0, is_potentially_hazardous=True, torino=9
    )
    assert risk.torino == 9
    assert risk.torino_consistent is True


def test_detect_anomaly_flags_outlier() -> None:
    """A value far from a tight cluster is flagged; the cluster members are not.

    The cluster is kept large and tight so the lone outlier doesn't inflate the
    standard deviation enough to mask itself (the classic small-sample z-score trap).
    """
    flags = detect_anomaly([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 20.0])
    assert flags[-1] is True
    assert not any(flags[:-1])


def test_detect_anomaly_handles_degenerate_input() -> None:
    """Fewer than two values, or zero variance, flags nothing."""
    assert detect_anomaly([5.0]) == [False]
    assert detect_anomaly([7.0, 7.0, 7.0]) == [False, False, False]


def test_observation_window() -> None:
    """The window spans the requested days before/after the approach date."""
    start, end = observation_window("2024-06-15", days_before=3, days_after=3)
    assert start == "2024-06-12"
    assert end == "2024-06-18"


def test_analyse_orbit_derives_all_fields() -> None:
    """analyse_orbit fills every derived field from raw inputs."""
    analysis = analyse_orbit(
        object_id="2465633",
        name="465633 (2009 JR5)",
        miss_distance_km=45_285_000.0,
        velocity_km_s=18.1335,
        diameter_min_m=213.8,
        diameter_max_m=478.3,
        is_potentially_hazardous=True,
    )
    assert analysis.miss_distance_ld == pytest.approx(45_285_000.0 / LUNAR_DISTANCE_KM)
    assert analysis.miss_distance_au == pytest.approx(45_285_000.0 / AU_KM)
    assert analysis.velocity_class == "moderate"
