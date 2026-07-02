"""Agent-level Pydantic models.

Shared data structures that flow between agents and into the final report:
``NEOData`` (FetchAgent output), ``ImageAsset`` (ImageAgent output), and the
report schema ``FinalReport`` with ``NEOEventReport``, ``RiskTableRow``, and
``Citation``.

Key concept: typed contracts between agents — never bare dicts — so bad data
fails fast at the boundary instead of deep inside synthesis. ``FinalReport`` is
the single validated artifact the UI renders; if synthesis produces something
off-shape, pydantic rejects it here rather than letting it reach the user.

Implemented across Phase 4 (NEOData, ImageAsset) and Phase 6 (FinalReport).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..data.models import EphemerisData, NEODetail, NEOFeedItem, SpaceWeatherReport


class NEOData(BaseModel):
    """Aggregated FetchAgent output for one query.

    ``feed_items`` is capped at the closest 10 approaches (spec chunking rule);
    ``remainder_count`` records how many further objects were folded into a
    statistical summary instead of enumerated, keeping the token cost bounded.
    """

    feed_items: list[NEOFeedItem] = Field(default_factory=list)
    remainder_count: int = 0
    details: list[NEODetail] = Field(default_factory=list)
    ephemerides: list[EphemerisData] = Field(default_factory=list)
    space_weather: SpaceWeatherReport | None = None


class ImageAsset(BaseModel):
    """One prepared APOD image, always carrying attribution.

    ``local_path`` points at the resized copy on disk (max 800 px wide) when one
    was written; ``credit`` is the attribution string that must accompany the
    image in the report.
    """

    title: str
    date: str
    url: str
    hd_url: str | None = None
    media_type: str
    credit: str
    explanation: str
    local_path: str | None = None
    width: int | None = None
    height: int | None = None


class Citation(BaseModel):
    """One source reference for the report's appendix.

    Attributes:
        source_type: Origin of the fact, e.g. ``"arxiv"``, ``"nasa_neows"``,
            ``"apod"``.
        title: Human-readable title.
        identifier: A stable id (arXiv id, object id, date) when available.
        url: Link to the source, when one exists.
    """

    source_type: str
    title: str
    identifier: str = ""
    url: str | None = None


class NEOEventReport(BaseModel):
    """One close-approach event: deterministic figures plus a one-line summary.

    Every numeric field is copied from CalcAgent's computed ``OrbitalAnalysis``;
    only ``summary`` is LLM-written prose (and it is fact-checked).
    """

    object_id: str
    name: str
    close_approach_date: str = ""
    miss_distance_ld: float
    velocity_km_s: float
    diameter_max_m: float
    risk_band: str
    summary: str = ""


class RiskTableRow(BaseModel):
    """A compact, tabular risk row (rendered as a dataframe in the UI)."""

    name: str
    miss_distance_ld: float
    velocity_km_s: float
    diameter_max_m: float
    risk_band: str


class ReportSection(BaseModel):
    """A generic, renderable report block contributed by a non-NEO vertical.

    The original NEO domain renders through the bespoke ``neo_events`` /
    ``orbital_risk_table`` fields. Verticals added later (space weather, Earth
    events…) render through this instead, so synthesis and the UI stay
    domain-agnostic. ``body_markdown`` and ``rows`` are built deterministically in
    Python from the vertical's computed core — the same "LLM writes prose, Python
    assembles facts" discipline the rest of the report follows.
    """

    title: str
    body_markdown: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)


class FinalReport(BaseModel):
    """The single validated artifact the pipeline returns and the UI renders.

    Prose fields (``executive_summary``, ``literature_insights``, each event's
    ``summary``) are LLM-written and fact-checked; tables, citations, and images
    are assembled deterministically from agent outputs.
    """

    query: str
    executive_summary: str = ""
    neo_events: list[NEOEventReport] = Field(default_factory=list)
    orbital_risk_table: list[RiskTableRow] = Field(default_factory=list)
    literature_insights: str = ""
    report_sections: list[ReportSection] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
    data_sources: list[Citation] = Field(default_factory=list)
    images: list[ImageAsset] = Field(default_factory=list)
    prompt_version: str = ""
