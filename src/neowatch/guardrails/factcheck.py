"""Fact-check guardrail (output).

The anti-hallucination layer. ``build_grounding_context`` flattens the trusted,
deterministically-computed figures (from :class:`OrbitalReport`) into a
unit-keyed dict of valid values. ``FactCheckLayer.check`` then scans generated
prose for ``<number> <unit>`` claims and, for each, asks: does this match *any*
trusted value for that unit, within tolerance? Numbers that match nothing are
flagged — surfaced to the user, never deleted.

Key concept: anti-hallucination by verification. We don't trust the LLM's
numbers; we check them against data we fetched and computed ourselves.

Why match *by unit* rather than to the nearest number overall? A hallucinated
miss-distance like "18 LD" could sit coincidentally close to some unrelated
grounding number (a velocity of 18.1 km/s) and slip through. Pinning each claim
to its unit ("LD" vs "km/s") makes the check honest.
"""

from __future__ import annotations

import re

from ..calc.models import OrbitalReport
from .models import FactCheckReport, FlaggedClaim

# Relative tolerance: a claimed number within 5% of a trusted value is accepted
# (covers the LLM rounding "12.3 LD" to "12 LD").
_TOLERANCE = 0.05

# Map the unit text found in prose to a grounding key. Ordered longest-first in
# the regex below so "km/s" wins over "km" and "lunar distances" over "m".
_UNIT_TO_KEY: dict[str, str] = {
    "km/s": "km_s",
    "lunar distances": "ld",
    "lunar distance": "ld",
    "ld": "ld",
    "au": "au",
    "km": "km",
    "meters": "m",
    "metres": "m",
    "meter": "m",
    "metre": "m",
    "m": "m",
}

# A number (optional sign, optional thousands separators / decimal) followed by
# one of the known units. Longest unit alternatives first so the regex is greedy
# about the most specific unit.
_CLAIM_RE = re.compile(
    r"(?P<value>-?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>km/s|lunar distances|lunar distance|ld|au|km|meters|metres|meter|metre|m)\b",
    re.IGNORECASE,
)


def build_grounding_context(report: OrbitalReport) -> dict[str, list[float]]:
    """Flatten an ``OrbitalReport`` into a unit-keyed dict of trusted values.

    Args:
        report: The CalcAgent output whose ``analyses`` hold the computed figures.

    Returns:
        A dict mapping unit keys (``"ld"``, ``"au"``, ``"km_s"``, ``"km"``,
        ``"m"``) to every valid value for that unit across all analysed objects.
    """
    grounding: dict[str, list[float]] = {"ld": [], "au": [], "km_s": [], "km": [], "m": []}
    for analysis in report.analyses:
        grounding["ld"].append(analysis.miss_distance_ld)
        grounding["au"].append(analysis.miss_distance_au)
        grounding["km_s"].append(analysis.velocity_km_s)
        grounding["km"].append(analysis.miss_distance_km)
        grounding["m"].append(analysis.diameter_min_m)
        grounding["m"].append(analysis.diameter_max_m)
    return grounding


class FactCheckLayer:
    """Verify numeric claims in generated prose against a grounding context."""

    def check(self, text: str, grounding: dict[str, list[float]]) -> FactCheckReport:
        """Flag every numeric claim that matches no trusted value for its unit.

        Args:
            text: The generated prose to verify (e.g. an agent narrative).
            grounding: Unit-keyed trusted values from
                :func:`build_grounding_context`.

        Returns:
            A :class:`FactCheckReport`. ``confidence`` is ``"high"`` with no
            flags, ``"medium"`` with one, ``"low"`` with two or more.
        """
        flagged: list[FlaggedClaim] = []
        for match in _CLAIM_RE.finditer(text):
            value = float(match.group("value").replace(",", ""))
            key = _UNIT_TO_KEY[match.group("unit").lower()]
            sources = grounding.get(key, [])
            if not sources:
                # No trusted value for this unit — we can't verify it, so we
                # don't flag it (avoids false alarms on unrelated numbers).
                continue
            nearest, pct = _closest(value, sources)
            if pct > _TOLERANCE * 100:
                flagged.append(
                    FlaggedClaim(
                        value=value,
                        source_value=nearest,
                        pct_diff=pct,
                        location=match.group(0).strip(),
                    )
                )
        return FactCheckReport(flagged=flagged, confidence=_confidence(len(flagged)))


def _closest(value: float, sources: list[float]) -> tuple[float, float]:
    """Return the source value nearest to ``value`` and the % difference to it."""
    nearest = min(sources, key=lambda s: abs(s - value))
    if nearest == 0:
        pct = 0.0 if value == 0 else 100.0
    else:
        pct = abs(value - nearest) / abs(nearest) * 100
    return nearest, pct


def _confidence(flag_count: int) -> str:
    """Map a flag count to a confidence label."""
    if flag_count == 0:
        return "high"
    if flag_count == 1:
        return "medium"
    return "low"
