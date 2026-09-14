"""Request and response models.

These are what `/docs` shows and what FastAPI validates on the way out. A
handler that returned the wrong shape would fail loudly here rather than
hand a client something subtly off.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

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
    queue: bool = Field(description="Redis answered a ping.")


# ---------------------------------------------------------------------------
# Sources and datasets
# ---------------------------------------------------------------------------


class SourceInfo(BaseModel):
    key: str = Field(description="What a dataset's `source` must be.", examples=["usgs"])
    name: str = Field(examples=["USGS Earthquake Hazards Program"])
    default_feed_url: str


class DatasetCreate(BaseModel):
    name: str = Field(examples=["Global Earthquakes"])
    source: str = Field(
        description="A key from `GET /api/sources`, matched case-insensitively.",
        examples=["usgs"],
    )
    description: Optional[str] = None


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


# ---------------------------------------------------------------------------
# Earthquakes
# ---------------------------------------------------------------------------


class Earthquake(BaseModel):
    id: int
    external_id: str = Field(description="The id the source gave the event.")
    magnitude: Optional[float] = Field(description="Null when the source omitted it.")
    magnitude_type: Optional[str] = Field(examples=["ml"])
    place: Optional[str]
    event_type: Optional[str] = Field(
        description="`earthquake` for most rows; quarry blasts and explosions are kept too.",
        examples=["earthquake"],
    )
    occurred_at: datetime = Field(description="Naive UTC.")
    longitude: float
    latitude: float
    depth_km: Optional[float]
    tsunami: bool
    significance: Optional[int]
    url: Optional[str]


class EarthquakePage(BaseModel):
    dataset_id: int
    total: int = Field(description="Events matching the filters, not the whole dataset.")
    limit: int
    offset: int
    filters: Dict[str, Any] = Field(description="Only the filters that were set.")
    items: List[Earthquake]


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


class IngestAccepted(BaseModel):
    import_id: int
    dataset_id: int
    status: str = Field(examples=["queued"])
    feed_url: str


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Problem(BaseModel):
    """The body of every refusal: FastAPI's `detail`, as a sentence."""

    detail: str = Field(examples=["Dataset 999 not found"])
