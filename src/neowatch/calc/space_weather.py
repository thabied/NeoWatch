"""Space-weather calculations.

Deterministic pure functions turning one planetary K-index (Kp) reading into the
NOAA geomagnetic-storm G-scale and an aurora-visibility latitude. This is the
"deterministic core" of the space-weather vertical: NOAA gives us Kp, and every
derived figure here is computed in plain code the LLM only narrates, never edits
— the same discipline as ``neowatch.calc.orbital``.

References:
- NOAA G-scale thresholds (Kp 5..9 -> G1..G5): https://www.swpc.noaa.gov/noaa-scales-explanation
- Aurora "view line" (equatorward geomagnetic latitude vs Kp): the classic SWPC
  table, which is very nearly linear (66.5 deg at Kp0 down to 48.1 deg at Kp9).
"""

from __future__ import annotations

from ..data.models import KpReading
from .models import SpaceWeatherAssessment

# NOAA G-scale: integer Kp thresholds map to storm bands. Kp below 5 is "no storm".
_G_SCALE: tuple[tuple[float, str, str], ...] = (
    (9.0, "G5", "extreme"),
    (8.0, "G4", "severe"),
    (7.0, "G3", "strong"),
    (6.0, "G2", "moderate"),
    (5.0, "G1", "minor"),
)

# Aurora equatorward view line, in geomagnetic latitude, as a linear fit to the
# SWPC table: 66.5 deg at Kp0, falling ~2.044 deg per Kp unit to 48.1 deg at Kp9.
_AURORA_LAT_AT_KP0 = 66.5
_AURORA_LAT_SLOPE = (66.5 - 48.1) / 9.0  # ~2.0444 deg per Kp unit


def g_scale(kp: float) -> tuple[str, str]:
    """Map a Kp value to its NOAA (code, label): ``("G0", "none")`` below Kp 5."""
    for threshold, code, label in _G_SCALE:
        if kp >= threshold:
            return code, label
    return "G0", "none"


def aurora_view_latitude(kp: float) -> float:
    """Lowest geomagnetic latitude (deg) aurora may reach at this Kp (1 dp).

    A higher Kp pushes the aurora oval toward the equator (a smaller latitude).
    Clamped to Kp 0-9, the range NOAA's scale is defined over.
    """
    clamped = min(max(kp, 0.0), 9.0)
    return round(_AURORA_LAT_AT_KP0 - _AURORA_LAT_SLOPE * clamped, 1)


def assess_space_weather(reading: KpReading) -> SpaceWeatherAssessment:
    """Turn one Kp reading into a full, deterministic space-weather assessment."""
    code, label = g_scale(reading.kp)
    is_storm = code != "G0"
    latitude = aurora_view_latitude(reading.kp)

    if is_storm:
        summary = (
            f"A {label} geomagnetic storm ({code}) is underway (Kp {reading.kp:.2f}). "
            f"Aurora may be visible down to ~{latitude:.1f}° geomagnetic latitude."
        )
    else:
        summary = (
            f"Geomagnetic conditions are quiet (Kp {reading.kp:.2f}, below storm level). "
            f"Aurora is unlikely below ~{latitude:.1f}° geomagnetic latitude."
        )

    return SpaceWeatherAssessment(
        time_tag=reading.time_tag,
        kp=reading.kp,
        g_scale=code,
        storm_level=label,
        is_storm=is_storm,
        aurora_latitude_deg=latitude,
        summary=summary,
    )
