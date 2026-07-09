"""External-data Pydantic models.

Typed representations of every API response. Field aliases map raw API JSON keys
onto clean Python names, and ``extra="ignore"`` lets an API *add* a field without
breaking us, while a *missing required* field still fails loudly here — at the
boundary — instead of mysteriously three layers deep.

Key concept: validate untrusted external data once, at the edge, then the rest
of the app works with trustworthy typed objects.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class _ApiModel(BaseModel):
    """Shared base for every external model.

    ``populate_by_name`` lets us construct by either the Python name or the raw
    API alias; ``extra="ignore"`` drops unknown keys (forward-compatibility).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# --- NASA NeoWs (Near-Earth Object Web Service) ------------------------------


class DiameterRange(_ApiModel):
    """Min/max estimated diameter in a single unit."""

    estimated_diameter_min: float
    estimated_diameter_max: float


class EstimatedDiameter(_ApiModel):
    """Diameter estimates; NASA also returns miles/feet, which we ignore."""

    kilometers: DiameterRange
    meters: DiameterRange


class RelativeVelocity(_ApiModel):
    """Approach speed. NASA returns these as numeric *strings*; Pydantic coerces."""

    kilometers_per_second: float
    kilometers_per_hour: float


class MissDistance(_ApiModel):
    """How close the object passes, in several units (also numeric strings)."""

    astronomical: float
    lunar: float
    kilometers: float


class CloseApproach(_ApiModel):
    """One close-approach event for a NEO."""

    close_approach_date: str
    close_approach_date_full: str | None = None
    epoch_date_close_approach: int | None = None
    relative_velocity: RelativeVelocity
    miss_distance: MissDistance
    orbiting_body: str


class NEOFeedItem(_ApiModel):
    """A near-Earth object as returned by the ``/feed`` and ``/browse`` endpoints."""

    id: str
    neo_reference_id: str
    name: str
    nasa_jpl_url: HttpUrl
    absolute_magnitude_h: float
    estimated_diameter: EstimatedDiameter
    is_potentially_hazardous_asteroid: bool
    close_approach_data: list[CloseApproach]
    is_sentry_object: bool


class NEODetail(NEOFeedItem):
    """A single NEO's full record (feed fields plus orbital elements)."""

    designation: str | None = None
    orbital_data: dict[str, Any] | None = None


# --- JPL Horizons -------------------------------------------------------------


class EphemerisData(_ApiModel):
    """Horizons ephemeris result.

    Horizons returns a free-form text block under ``result``; we keep it raw
    rather than over-fitting a parser to its column layout. Downstream code (or
    a later phase) can extract specific quantities as needed.
    """

    target: str
    date: str
    raw_result: str


# --- NASA APOD (Astronomy Picture of the Day) --------------------------------


class APODImage(_ApiModel):
    """APOD metadata. ``hdurl`` is absent for videos; ``url`` may be a video link."""

    date: str
    title: str
    explanation: str
    media_type: str
    url: HttpUrl
    hdurl: HttpUrl | None = None
    copyright: str | None = None
    service_version: str | None = None


class NASAImage(_ApiModel):
    """One result from the NASA Image & Video Library search API.

    Unlike APOD (keyed by date), this comes from a topic search. The search
    response is deeply nested (``collection.items[].data[0]`` for metadata,
    ``.links[0].href`` for the preview URL); the client flattens it onto this
    model rather than relying on field aliases.
    """

    nasa_id: str
    title: str
    date_created: str
    media_type: str
    preview_url: HttpUrl
    description: str = ""
    center: str | None = None
    photographer: str | None = None


# --- JPL Small Body Database (SBDB) ------------------------------------------


class SBDBPhysPar(_ApiModel):
    """One physical parameter row (e.g. absolute magnitude, albedo, diameter)."""

    name: str
    value: str | None = None
    title: str | None = None
    units: str | None = None


class SBDBRecord(_ApiModel):
    """Flattened SBDB record. The client maps SBDB's nested JSON onto this."""

    fullname: str
    neo: bool | None = None
    pha: bool | None = None  # potentially hazardous asteroid
    designation: str | None = None
    orbit_class: str | None = None
    phys_par: list[SBDBPhysPar] = Field(default_factory=list)


# --- arXiv --------------------------------------------------------------------


class ArxivPaper(_ApiModel):
    """One arXiv paper; the raw material for the RAG knowledge base (Phase 3)."""

    id: str
    title: str
    summary: str
    authors: list[str] = Field(default_factory=list)
    published: str
    link: HttpUrl
    categories: list[str] = Field(default_factory=list)


# --- NASA DONKI (space weather) ----------------------------------------------


class SpaceWeatherEvent(_ApiModel):
    """A normalized space-weather event (flare, CME, or geomagnetic storm)."""

    event_id: str
    event_type: str  # "FLR" | "CME" | "GST"
    start_time: str
    detail: str | None = None


class SpaceWeatherReport(_ApiModel):
    """Aggregated space weather over a date range."""

    start_date: str
    end_date: str
    flares: list[SpaceWeatherEvent] = Field(default_factory=list)
    cmes: list[SpaceWeatherEvent] = Field(default_factory=list)
    storms: list[SpaceWeatherEvent] = Field(default_factory=list)


# --- NOAA SWPC (planetary K-index) -------------------------------------------


class KpReading(_ApiModel):
    """One planetary K-index observation from NOAA SWPC.

    ``kp`` reads NOAA's ``Kp`` JSON key (aliased). The raw feed also carries
    ``a_running`` and ``station_count``, which ``extra="ignore"`` drops — we keep
    only the fields the deterministic core consumes.
    """

    time_tag: str
    kp: float = Field(alias="Kp")


class KpIndexReport(_ApiModel):
    """A time-ordered series of Kp readings (oldest first, as NOAA returns them)."""

    readings: list[KpReading] = Field(default_factory=list)

    @property
    def latest(self) -> KpReading | None:
        """The most recent reading — NOAA appends newest last, so it's the tail."""
        return self.readings[-1] if self.readings else None


# --- NASA EONET (Earth Observatory Natural Event Tracker) --------------------


class EonetCategory(_ApiModel):
    """One event category (e.g. ``{"id": "wildfires", "title": "Wildfires"}``)."""

    id: str
    title: str


class EonetGeometry(_ApiModel):
    """One position (and optional magnitude) of an event at a point in time.

    ``coordinates`` is kept as raw JSON because its shape depends on ``type``: a
    ``Point`` is ``[lon, lat]`` while a ``Polygon`` nests coordinate rings. The
    deterministic core (``neowatch.calc.geo``) extracts a representative point,
    so we do not over-fit a schema to every GeoJSON variant here. ``magnitude_*``
    is often absent (e.g. severe storms carry no magnitude), hence nullable.
    """

    date: str
    type: str
    coordinates: list[Any] = Field(default_factory=list)
    magnitude_value: float | None = Field(default=None, alias="magnitudeValue")
    magnitude_unit: str | None = Field(default=None, alias="magnitudeUnit")


class EonetEvent(_ApiModel):
    """One natural event. ``closed`` is ``None`` while the event is still active."""

    id: str
    title: str
    description: str | None = None
    link: str
    closed: str | None = None
    categories: list[EonetCategory] = Field(default_factory=list)
    geometry: list[EonetGeometry] = Field(default_factory=list)


class EonetEventReport(_ApiModel):
    """The EONET ``/events`` payload: a list of events under the ``events`` key."""

    events: list[EonetEvent] = Field(default_factory=list)
