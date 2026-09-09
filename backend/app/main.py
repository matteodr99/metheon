from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.db.database import get_connection
from app.db import repository
from app.ingestion import usgs

from typing import Optional

# An ingestion run can report many invalid features; only the first few are
# returned, so a broken feed cannot produce an unbounded response.
MAX_REPORTED_ERRORS = 10


class DatasetCreate(BaseModel):
    name: str
    source: str
    description: Optional[str] = None


app = FastAPI(title="Metheon API")


@app.get("/api/health")
def health_check():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    return {
        "status": "ok",
        "service": "metheon",
        "database": result[0] == 1
    }


@app.get("/api/datasets")
def get_datasets():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, source, description, created_at, status
                FROM datasets
                ORDER BY id
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "source": row[2],
            "description": row[3],
            "created_at": row[4],
            "status": row[5],
        }
        for row in rows
    ]


@app.post("/api/datasets")
def create_dataset(dataset: DatasetCreate):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO datasets (name, source, description)
                VALUES (%s, %s, %s)
                RETURNING id, name, source, description, created_at, status
                """,
                (dataset.name, dataset.source, dataset.description),
            )
            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "description": row[3],
        "created_at": row[4],
        "status": row[5],
    }


def _set_status(dataset_id: int, status: str) -> None:
    """Persist a status change in its own transaction.

    The ingestion status must survive a failure of the ingestion itself, so
    each transition is committed separately from the work it describes.
    """
    with get_connection() as connection:
        repository.set_dataset_status(connection, dataset_id, status)


@app.post("/api/datasets/{dataset_id}/ingest")
def ingest_dataset(dataset_id: int):
    """Fetch the USGS feed and store its earthquakes for this dataset.

    The run is synchronous: the request stays open until the feed has been
    downloaded and written. Moving this onto a background worker is part of
    a later step.
    """
    with get_connection() as connection:
        dataset = repository.get_dataset(connection, dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="Dataset {0} not found".format(dataset_id),
        )

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
