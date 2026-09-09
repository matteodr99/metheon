from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from app.db.database import get_connection
from app.db import repository
from app import jobs
from app.ingestion import usgs

from typing import Optional

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
):
    """Return a page of the earthquakes stored for a dataset.

    Results are ordered by event time, most recent first. `limit` is capped
    so a single request cannot pull the whole table.
    """
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        total = repository.count_earthquakes(connection, dataset_id)
        items = repository.list_earthquakes(connection, dataset_id, limit, offset)

    return {
        "dataset_id": dataset_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
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
