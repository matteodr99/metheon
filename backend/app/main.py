from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from app.db.database import get_connection
from app.db import repository
from app.ingestion import usgs

from typing import Optional

# An ingestion run can report many invalid features; only the first few are
# returned, so a broken feed cannot produce an unbounded response.
MAX_REPORTED_ERRORS = 10

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
    with get_connection() as connection:
        database_ok = repository.ping(connection)

    return {
        "status": "ok",
        "service": "metheon",
        "database": database_ok,
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


@app.post("/api/datasets/{dataset_id}/ingest")
def ingest_dataset(dataset_id: int):
    """Fetch the USGS feed and store its earthquakes for this dataset.

    The run is synchronous: the request stays open until the feed has been
    downloaded and written. Moving this onto a background worker is part of
    a later step.
    """
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)

    _set_status(dataset_id, repository.STATUS_PROCESSING)

    try:
        payload = usgs.fetch_feed()
        records, errors = usgs.normalize_feed(payload)
        fetched = len(payload.get("features", []))

        with get_connection() as connection:
            inserted, updated = repository.upsert_earthquakes(
                connection, dataset_id, records
            )
    except usgs.IngestionError as exc:
        _set_status(dataset_id, repository.STATUS_FAILED)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        _set_status(dataset_id, repository.STATUS_FAILED)
        raise

    _set_status(dataset_id, repository.STATUS_COMPLETED)

    return {
        "dataset_id": dataset_id,
        "status": repository.STATUS_COMPLETED,
        "feed_url": usgs.DEFAULT_FEED_URL,
        "fetched": fetched,
        "valid": len(records),
        "invalid": len(errors),
        "inserted": inserted,
        "updated": updated,
        "errors": errors[:MAX_REPORTED_ERRORS],
    }
