"""Agent-level Pydantic models.

Shared data structures that flow between agents and into the final report:
``NEOData`` (FetchAgent output), ``ImageAsset`` (ImageAgent output), and the
report schema ``FinalReport`` with ``NEOEventReport`` and ``Citation``.

Key concept: typed contracts between agents — never bare dicts — so bad data
fails fast at the boundary instead of deep inside synthesis.

Implemented across Phase 4 (NEOData, ImageAsset) and Phase 6 (FinalReport).
"""

from __future__ import annotations

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
