"""Request and response models.

These are what `/docs` shows and what FastAPI validates on the way out. A
handler that returned the wrong shape would fail loudly here rather than
hand a client something subtly off.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class Liveness(BaseModel):
    status: str = Field(examples=["alive"])
    service: str = Field(examples=["metheon"])


class Readiness(BaseModel):
    status: str = Field(
        description="`ok` when every dependency answers, `degraded` otherwise.",
        examples=["ok"],
    )
    service: str = Field(examples=["metheon"])
    database: bool = Field(description="PostgreSQL answered a query.")
    queue: Optional[bool] = Field(
        description="Redis answered a ping; null when INGESTION_MODE is inline "
        "and there is no queue to ask."
    )


# ---------------------------------------------------------------------------
# Sources and datasets
# ---------------------------------------------------------------------------


class SourceInfo(BaseModel):
    key: str = Field(description="What a dataset's `source` must be.", examples=["usgs"])
    name: str = Field(examples=["USGS Earthquake Hazards Program"])
    default_feed_url: str
    kinds: List[str] = Field(
        description="The kinds of event this source serves; a dataset gets one of them.",
        examples=[["earthquake"]],
    )
    homepage: str = Field(description="The agency's site, to link to.", examples=["https://earthquake.usgs.gov"])
    licence: str = Field(
        description="The terms the data comes under.",
        examples=["U.S. government work, public domain", "CC BY 4.0"],
    )
    credit: Optional[str] = Field(
        description="The line the licence asks to be shown; null where none is required.",
        examples=["INGV (Istituto Nazionale di Geofisica e Vulcanologia)"],
    )


class DatasetCreate(BaseModel):
    name: str = Field(examples=["Global Earthquakes"])
    source: str = Field(
        description="A key from `GET /api/sources`, matched case-insensitively.",
        examples=["usgs"],
    )
    description: Optional[str] = None
    kind: Optional[str] = Field(
        default=None,
        description="Which of the source's kinds this dataset holds. May be left out "
        "when the source serves one kind; must be given when it serves several.",
        examples=["earthquake"],
    )


class Dataset(BaseModel):
    id: int
    name: str
    source: str
    description: Optional[str]
    created_at: datetime
    status: str = Field(
        description="Mirrors the latest run: `pending`, `queued`, `processing`, "
        "`completed` or `failed`.",
        examples=["completed"],
    )
    kind: str = Field(
        description="What kind of thing its events are; one kind per dataset.",
        examples=["earthquake"],
    )
    last_ingested_at: Optional[datetime] = Field(
        description="When its latest completed run finished; null before the first."
    )


# ---------------------------------------------------------------------------
# Earthquakes
# ---------------------------------------------------------------------------


class Event(BaseModel):
    id: int
    external_id: str = Field(description="The id the source gave the event.")
    title: Optional[str] = Field(description="What the source calls it: a place for a quake, a name for a storm.")
    event_type: Optional[str] = Field(
        description="The source's finer class: `earthquake` for most seismic rows, but quarry blasts and explosions are kept too.",
        examples=["earthquake"],
    )
    occurred_at: datetime = Field(description="Origin or start, naive UTC.")
    ended_at: Optional[datetime] = Field(description="Set for events with a duration.")
    source_updated_at: Optional[datetime]
    longitude: float = Field(description="A representative point; always present.")
    latitude: float
    geometry: Optional[Dict[str, Any]] = Field(description="The full GeoJSON geometry when it is more than a point.")
    magnitude: Optional[float] = Field(description="The number this kind of event is measured by; null when the source omitted it.")
    magnitude_unit: Optional[str] = Field(description="What `magnitude` is: a seismic scale, hectares, knots.", examples=["ml"])
    attributes: Dict[str, Any] = Field(
        description="What only this kind or source has. Earthquakes: `depth_km`, `tsunami`, `significance`, `network`."
    )
    url: Optional[str]


class EventPage(BaseModel):
    dataset_id: int
    total: int = Field(description="Events matching the filters, not the whole dataset.")
    limit: int
    offset: int
    filters: Dict[str, Any] = Field(description="Only the filters that were set.")
    items: List[Event]


class EventPoints(BaseModel):
    dataset_id: int
    total: int = Field(description="Events matching the filters; may exceed the points returned.")
    limit: int
    filters: Dict[str, Any] = Field(description="Only the filters that were set.")
    points: List[Tuple[float, float, Optional[float], int]] = Field(
        description="[longitude, latitude, magnitude, id] per event, strongest first."
    )


class MatchedEvent(BaseModel):
    id: int
    external_id: str
    title: Optional[str]
    occurred_at: datetime
    longitude: float
    latitude: float
    magnitude: Optional[float]
    magnitude_unit: Optional[str]
    attributes: Dict[str, Any]


class Match(BaseModel):
    event: MatchedEvent = Field(description="The event in the dataset being compared.")
    other: MatchedEvent = Field(description="Its nearest report in the other dataset.")
    delta_seconds: float = Field(description="Other minus event; negative when the other agency dates it earlier.")
    distance_km: float = Field(description="Between the two epicentres, great-circle.")
    delta_magnitude: Optional[float] = Field(description="Other minus event; null when either lacks a magnitude.")


class Matches(BaseModel):
    dataset_id: int
    other_id: int
    window_seconds: float
    radius_km: float
    limit: int
    filters: Dict[str, Any] = Field(description="Only the filters that were set; they apply to `dataset_id`.")
    events: int = Field(description="Events of `dataset_id` matching the filters.")
    matched: int = Field(description="Of those, how many have a partner in `other_id`.")
    unmatched: int
    mean_abs_delta_seconds: Optional[float] = Field(description="Over every pair; null with no pairs.")
    mean_distance_km: Optional[float]
    mean_abs_delta_magnitude: Optional[float] = Field(description="Over the pairs where both have a magnitude.")
    pairs: List[Match] = Field(description="At most `limit`, strongest first.")


class MagnitudeSummary(BaseModel):
    min: Optional[float]
    max: Optional[float]
    average: Optional[float] = Field(description="Over the events that have a magnitude.")
    unknown: int = Field(description="Matching events with no magnitude.")


class TimeSpan(BaseModel):
    first: Optional[datetime]
    last: Optional[datetime]


class EventTypeCount(BaseModel):
    event_type: Optional[str]
    count: int


class DayCount(BaseModel):
    day: date
    count: int


class Summary(BaseModel):
    dataset_id: int
    filters: Dict[str, Any]
    total: int
    magnitude: MagnitudeSummary
    occurred_at: TimeSpan
    by_event_type: List[EventTypeCount] = Field(description="Largest first.")
    by_day: List[DayCount] = Field(description="UTC calendar days, chronological.")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class ImportRun(BaseModel):
    id: int
    dataset_id: int
    status: str = Field(examples=["completed"])
    feed_url: str
    queued_at: datetime = Field(description="When the API accepted the run.")
    started_at: Optional[datetime] = Field(description="When a worker picked it up.")
    finished_at: Optional[datetime]
    fetched: int
    valid: int
    invalid: int
    inserted: int
    updated: int
    invalid_sample: Optional[str] = Field(
        description="The first few validation errors, newline-separated."
    )
    error: Optional[str] = Field(description="Why the run failed, when it did.")


class ImportPage(BaseModel):
    dataset_id: int
    total: int
    limit: int
    offset: int
    items: List[ImportRun]


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


class Insights(BaseModel):
    """What the model answered, in the structure it was asked for."""

    dataset_id: int
    filters: Dict[str, Any]
    model: str = Field(description="The Gemini model that produced this.")
    summary: str
    key_trends: List[str]
    anomalies: List[str]
    recommendations: List[str]
    agency_comparison: str = Field(
        description="How another agency's reports of the same events compare; empty unless `other` was given."
    )
    other_id: Optional[int] = Field(description="The dataset compared with, when one was.")


class AIStatus(BaseModel):
    configured: bool = Field(description="Whether GEMINI_API_KEY is set.")
    model: str


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Problem(BaseModel):
    """The body of every refusal: FastAPI's `detail`, as a sentence."""

    detail: str = Field(examples=["Dataset 999 not found"])
