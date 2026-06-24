"""Orbital and risk calculations.

Deterministic pure functions: miss-distance normalisation (km -> lunar distances
-> AU), relative-velocity classification, a heuristic risk band, a Torino-scale
cross-check, statistical anomaly detection, and observation-window calculation.

Key concept: keeping these as plain, side-effect-free functions means we can test
them against known values and the LLM can never silently change a result. This is
the "deterministic core" that the CalcAgent's LLM only narrates, never edits.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from .models import OrbitalAnalysis, RiskAssessment

# --- Physical constants -------------------------------------------------------

LUNAR_DISTANCE_KM = 384_400.0  # mean Earth-Moon distance (1 LD)
AU_KM = 149_597_870.7  # one astronomical unit
PHA_DIAMETER_M = 140.0  # the ~140 m "potentially hazardous" size threshold

# Risk-band ordering, weakest to strongest, used for the Torino cross-check.
_RISK_ORDER = ("negligible", "low", "elevated", "high")


# --- Unit conversions ---------------------------------------------------------


def km_to_lunar_distance(km: float) -> float:
    """Convert a distance in kilometres to lunar distances (LD)."""
    return km / LUNAR_DISTANCE_KM


def km_to_au(km: float) -> float:
    """Convert a distance in kilometres to astronomical units (AU)."""
    return km / AU_KM


def classify_velocity(km_s: float) -> str:
    """Bucket a relative approach speed into a human-readable class.

    Bands (km/s): <5 slow, 5-20 moderate, 20-40 fast, >=40 very fast. These are
    rough descriptive bins for the report, not formal categories.
    """
    if km_s < 5:
        return "slow"
    if km_s < 20:
        return "moderate"
    if km_s < 40:
        return "fast"
    return "very fast"


# --- Risk heuristic -----------------------------------------------------------


def assess_risk(
    object_id: str,
    miss_distance_ld: float,
    diameter_max_m: float,
    is_potentially_hazardous: bool,
    torino: int | None = None,
) -> RiskAssessment:
    """Score a single object into a heuristic risk band.

    Teaching heuristic only: closeness + size + the PHA flag are summed into a
    small score, then bucketed. Real impact assessment (Torino/Palermo scales,
    Sentry) integrates the actual orbit over decades — far beyond this. When a
    real ``torino`` rating is supplied we cross-check our band against it.
    """
    score = 0
    if miss_distance_ld < 1:
        score += 3
    elif miss_distance_ld < 5:
        score += 2
    elif miss_distance_ld < 20:
        score += 1

    if diameter_max_m >= 1000:
        score += 3
    elif diameter_max_m >= PHA_DIAMETER_M:
        score += 2
    elif diameter_max_m >= 30:
        score += 1

    if is_potentially_hazardous:
        score += 1

    if score >= 6:
        band = "high"
    elif score >= 4:
        band = "elevated"
    elif score >= 2:
        band = "low"
    else:
        band = "negligible"

    rationale = (
        f"miss distance {miss_distance_ld:.1f} LD, max diameter {diameter_max_m:.0f} m, "
        f"PHA={is_potentially_hazardous} -> score {score} -> {band}"
    )

    consistent: bool | None = None
    if torino is not None:
        consistent = cross_check_torino(torino, band)

    return RiskAssessment(
        object_id=object_id,
        risk_band=band,
        risk_score=score,
        rationale=rationale,
        torino=torino,
        torino_consistent=consistent,
    )


def cross_check_torino(torino: int, computed_band: str) -> bool:
    """Check our heuristic band against an official Torino rating (0-10).

    Maps Torino to an expected band and returns True when our computed band is
    equal or adjacent to it (off-by-one is tolerated — the heuristic is coarse).
    """
    if torino <= 0:
        expected = "negligible"
    elif torino == 1:
        expected = "low"
    elif torino <= 4:
        expected = "elevated"
    else:
        expected = "high"

    return abs(_RISK_ORDER.index(computed_band) - _RISK_ORDER.index(expected)) <= 1


# --- Statistics & scheduling --------------------------------------------------


def detect_anomaly(values: list[float], z: float = 2.0) -> list[bool]:
    """Flag values more than ``z`` standard deviations from the mean.

    A simple z-score outlier test (numpy). With fewer than two values, or zero
    variance, nothing is flagged. Used to surface a NEO whose speed or size is a
    statistical outlier against the rest of the batch.
    """
    if len(values) < 2:
        return [False] * len(values)
    arr = np.asarray(values, dtype=float)
    std = float(arr.std())
    if std == 0.0:
        return [False] * len(values)
    mean = float(arr.mean())
    return [abs(float(v) - mean) > z * std for v in values]


def observation_window(
    close_approach_date: str, days_before: int = 3, days_after: int = 3
) -> tuple[str, str]:
    """Return an inclusive ``(start, end)`` viewing window around an approach.

    Deterministic date arithmetic: ``days_before`` before and ``days_after``
    after the close-approach date (YYYY-MM-DD), as ISO date strings.
    """
    centre = datetime.strptime(close_approach_date, "%Y-%m-%d")
    start = (centre - timedelta(days=days_before)).strftime("%Y-%m-%d")
    end = (centre + timedelta(days=days_after)).strftime("%Y-%m-%d")
    return start, end


# --- Builder ------------------------------------------------------------------


def analyse_orbit(
    object_id: str,
    name: str,
    miss_distance_km: float,
    velocity_km_s: float,
    diameter_min_m: float,
    diameter_max_m: float,
    is_potentially_hazardous: bool,
) -> OrbitalAnalysis:
    """Assemble one ``OrbitalAnalysis`` from raw NEO fields (all derived purely)."""
    return OrbitalAnalysis(
        object_id=object_id,
        name=name,
        miss_distance_km=miss_distance_km,
        miss_distance_ld=km_to_lunar_distance(miss_distance_km),
        miss_distance_au=km_to_au(miss_distance_km),
        velocity_km_s=velocity_km_s,
        velocity_class=classify_velocity(velocity_km_s),
        diameter_min_m=diameter_min_m,
        diameter_max_m=diameter_max_m,
        is_potentially_hazardous=is_potentially_hazardous,
    )
