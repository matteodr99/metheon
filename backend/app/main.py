from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from app.db.database import get_connection
from app.db import repository
from app import jobs
from app.ingestion import usgs

from datetime import datetime
from typing import Any, Optional

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class DatasetCreate(BaseModel):
    name: str
    source: str
    description: Optional[str] = None


app = FastAPI(title="Metheon API")


def _get_dataset_or_404(connection, dataset_id: int):
    dataset = repository.get_dataset(connection, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="Dataset {0} not found".format(dataset_id),
        )
    return dataset


class EarthquakeFilters:
    """The filters shared by the listing and the summary.

    Declared once so the two endpoints cannot drift apart: a summary that
    accepted different filters than the listing it describes would be
    misleading.
    """

    def __init__(
        self,
        min_magnitude: Optional[float] = Query(None),
        max_magnitude: Optional[float] = Query(None),
        start_time: Optional[datetime] = Query(None),
        end_time: Optional[datetime] = Query(None),
        event_type: Optional[str] = Query(None),
    ):
        self._reject_inverted(min_magnitude, max_magnitude, "magnitude")
        self._reject_inverted(start_time, end_time, "time")

        self.values = {
            "min_magnitude": min_magnitude,
            "max_magnitude": max_magnitude,
            "start_time": start_time,
            "end_time": end_time,
            "event_type": event_type,
        }

    @staticmethod
    def _reject_inverted(lower: Any, upper: Any, label: str) -> None:
        """Refuse a range whose bounds are the wrong way round.

        Such a range silently matches nothing, which reads as "no data"
        rather than as the mistake it is.
        """
        if lower is not None and upper is not None and lower > upper:
            raise HTTPException(
                status_code=422,
                detail="The {0} range is inverted: {1} is greater than {2}".format(
                    label, lower, upper
                ),
            )

    def applied(self):
        """Only the filters the caller actually set, for echoing back."""
        return {name: value for name, value in self.values.items() if value is not None}


def _set_status(dataset_id: int, status: str) -> None:
    """Persist a status change in its own transaction.

    The ingestion status must survive a failure of the ingestion itself, so
    each transition is committed separately from the work it describes.
    """
    with get_connection() as connection:
        repository.set_dataset_status(connection, dataset_id, status)


@app.get("/api/health")
def health_check():
    """Report whether the API can reach its two dependencies."""
    with get_connection() as connection:
        database_ok = repository.ping(connection)

    queue_ok = jobs.ping()

    return {
        "status": "ok" if database_ok and queue_ok else "degraded",
        "service": "metheon",
        "database": database_ok,
        "queue": queue_ok,
    }


@app.get("/api/datasets")
def get_datasets():
    with get_connection() as connection:
        return repository.list_datasets(connection)


@app.post("/api/datasets")
def create_dataset(dataset: DatasetCreate):
    with get_connection() as connection:
        return repository.create_dataset(
            connection,
            dataset.name,
            dataset.source,
            dataset.description,
        )


@app.get("/api/datasets/{dataset_id}/earthquakes")
def get_dataset_earthquakes(
    dataset_id: int,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    filters: EarthquakeFilters = Depends(),
):
    """Return a page of the earthquakes stored for a dataset.

    Results are ordered by event time, most recent first. `limit` is capped
    so a single request cannot pull the whole table. Every filter is
    optional, and the bounds are inclusive.

    `total` counts the events matching the filters, not the whole dataset,
    so a client can page through the filtered result.
    """
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        total = repository.count_earthquakes(connection, dataset_id, filters.values)
        items = repository.list_earthquakes(
            connection, dataset_id, limit, offset, filters.values
        )

    return {
        "dataset_id": dataset_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": filters.applied(),
        "items": items,
    }


@app.get("/api/datasets/{dataset_id}/earthquakes/summary")
def get_dataset_earthquake_summary(
    dataset_id: int,
    filters: EarthquakeFilters = Depends(),
):
    """Aggregate the matching earthquakes, without returning the events.

    Takes the same filters as the listing, so a client showing a filtered
    view can describe exactly what it is showing.

    Days are UTC calendar days, matching how event times are stored.
    """
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        summary = repository.summarize_earthquakes(
            connection, dataset_id, filters.values
        )

    return {
        "dataset_id": dataset_id,
        "filters": filters.applied(),
        **summary,
    }


@app.get("/api/datasets/{dataset_id}/imports")
def get_dataset_imports(
    dataset_id: int,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    """Return the import history of a dataset, most recent run first."""
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        total = repository.count_imports(connection, dataset_id)
        items = repository.list_imports(connection, dataset_id, limit, offset)

    return {
        "dataset_id": dataset_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@app.post("/api/datasets/{dataset_id}/ingest", status_code=202)
def ingest_dataset(dataset_id: int):
    """Queue an ingestion run for this dataset.

    The request returns as soon as the run is queued; a worker picks it up
    and does the work. Follow its progress through
    `GET /api/datasets/{id}/imports`, or the dataset status.
    """
    feed_url = usgs.DEFAULT_FEED_URL

    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        import_id = repository.create_import(connection, dataset_id, feed_url)

    try:
        jobs.enqueue_import(import_id)
    except jobs.QueueError as exc:
        # The run exists in the history, so a queue outage is visible there
        # rather than being silently swallowed.
        with get_connection() as connection:
            repository.fail_import(connection, import_id, str(exc))
        _set_status(dataset_id, repository.STATUS_FAILED)
        raise HTTPException(status_code=503, detail=str(exc))

    _set_status(dataset_id, repository.STATUS_QUEUED)

    return {
        "import_id": import_id,
        "dataset_id": dataset_id,
        "status": repository.STATUS_QUEUED,
        "feed_url": feed_url,
    }
