"""Calculation result models.

Pydantic models for the calc outputs: ``OrbitalAnalysis`` (per-object computed
fields) and ``RiskAssessment`` (object id, Torino rating, computed risk band,
and rationale).

Key concept: the *numbers* live in typed models so downstream code (and the
Phase 5 fact-check layer) can compare an LLM's prose against the exact computed
value, field by field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OrbitalAnalysis(BaseModel):
    """Deterministic per-object orbital figures (all computed in pure code)."""

    object_id: str
    name: str
    miss_distance_km: float
    miss_distance_ld: float = Field(description="Miss distance in lunar distances (LD).")
    miss_distance_au: float = Field(description="Miss distance in astronomical units (AU).")
    velocity_km_s: float
    velocity_class: str = Field(description="slow | moderate | fast | very fast")
    diameter_min_m: float
    diameter_max_m: float
    is_potentially_hazardous: bool


class RiskAssessment(BaseModel):
    """Heuristic risk band for one object, plus an optional Torino cross-check.

    The band is a *teaching heuristic* over miss distance, size, and the PHA flag
    — not a real impact-probability calculation (that is what JPL's Sentry system
    and the official Torino scale do). ``torino`` carries an externally supplied
    Torino rating when one is known; ``torino_consistent`` records whether our
    heuristic broadly agrees with it.
    """

    object_id: str
    risk_band: str = Field(description="negligible | low | elevated | high")
    risk_score: int
    rationale: str
    torino: int | None = None
    torino_consistent: bool | None = None


class OrbitalReport(BaseModel):
    """CalcAgent output: deterministic figures plus an LLM narrative *around* them.

    ``narrative`` is the only field the LLM writes; every number is in
    ``analyses`` / ``risks`` and is computed in pure code, so the Phase 5
    fact-check layer can verify the prose against these values.
    """

    analyses: list[OrbitalAnalysis] = Field(default_factory=list)
    risks: list[RiskAssessment] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list, description="object_ids flagged as outliers")
    narrative: str = ""


class SpaceWeatherAssessment(BaseModel):
    """Deterministic space-weather reading, all fields derived from one Kp value.

    Like ``OrbitalAnalysis``, this is a pure-code product: the Kp comes from NOAA,
    and the NOAA G-scale band and aurora-visibility latitude are computed by
    ``neowatch.calc.space_weather``. ``summary`` is assembled in Python too (no
    LLM), so the space-weather vertical needs no model call at all.
    """

    time_tag: str
    kp: float = Field(description="Planetary K-index, 0-9.")
    g_scale: str = Field(description="NOAA geomagnetic storm scale: G0 (none) - G5 (extreme).")
    storm_level: str = Field(description="none | minor | moderate | strong | severe | extreme")
    is_storm: bool = Field(description="True when Kp >= 5 (G1 or stronger).")
    aurora_latitude_deg: float = Field(
        description="Equatorward geomagnetic latitude aurora may reach at this Kp."
    )
    summary: str = Field(description="Deterministic one-line plain-English summary.")


class CategoryCount(BaseModel):
    """How many active events fall under one EONET category."""

    category: str
    count: int


class EventHotspot(BaseModel):
    """The most concentrated region of active events, found via haversine distance.

    ``latitude``/``longitude`` are the coordinates of the event with the most
    neighbours within ``radius_km``; ``event_count`` includes that centre event.
    """

    latitude: float
    longitude: float
    radius_km: float
    event_count: int
    dominant_category: str


class EarthEventsAssessment(BaseModel):
    """Deterministic summary of the current active-natural-event picture.

    Like ``SpaceWeatherAssessment``, every field is computed in pure code from the
    EONET feed by ``neowatch.calc.geo`` — counts, the category breakdown, and the
    haversine-derived hotspot — and ``summary`` is assembled in Python, so the
    Earth-events vertical needs no model call.
    """

    total_active: int = Field(description="Number of currently-active events (closed is null).")
    categories: list[CategoryCount] = Field(
        default_factory=list, description="Active-event counts by category, most common first."
    )
    hotspot: EventHotspot | None = Field(
        default=None, description="Where active events cluster most tightly (None if none located)."
    )
    summary: str = Field(description="Deterministic one-line plain-English summary.")
