"""Database access for datasets and earthquakes.

Route handlers should call these helpers instead of writing SQL inline, so
queries stay in one place as the project grows.
"""

from typing import Any, Dict, List, Optional, Tuple

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_UPSERT_EARTHQUAKE = """
    INSERT INTO earthquakes (
        dataset_id, external_id, magnitude, magnitude_type, place, event_type,
        occurred_at, source_updated_at, longitude, latitude, depth_km,
        tsunami, significance, url
    )
    VALUES (
        %(dataset_id)s, %(external_id)s, %(magnitude)s, %(magnitude_type)s,
        %(place)s, %(event_type)s, %(occurred_at)s, %(source_updated_at)s,
        %(longitude)s, %(latitude)s, %(depth_km)s, %(tsunami)s,
        %(significance)s, %(url)s
    )
    ON CONFLICT (external_id) DO UPDATE SET
        dataset_id = EXCLUDED.dataset_id,
        magnitude = EXCLUDED.magnitude,
        magnitude_type = EXCLUDED.magnitude_type,
        place = EXCLUDED.place,
        event_type = EXCLUDED.event_type,
        occurred_at = EXCLUDED.occurred_at,
        source_updated_at = EXCLUDED.source_updated_at,
        longitude = EXCLUDED.longitude,
        latitude = EXCLUDED.latitude,
        depth_km = EXCLUDED.depth_km,
        tsunami = EXCLUDED.tsunami,
        significance = EXCLUDED.significance,
        url = EXCLUDED.url,
        ingested_at = CURRENT_TIMESTAMP
    RETURNING (xmax = 0) AS inserted
"""


def get_dataset(connection, dataset_id: int) -> Optional[Dict[str, Any]]:
    """Return a single dataset, or None when it does not exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, source, description, created_at, status
            FROM datasets
            WHERE id = %s
            """,
            (dataset_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "description": row[3],
        "created_at": row[4],
        "status": row[5],
    }


def set_dataset_status(connection, dataset_id: int, status: str) -> None:
    """Move a dataset to the given status."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE datasets SET status = %s WHERE id = %s",
            (status, dataset_id),
        )


def upsert_earthquakes(
    connection,
    dataset_id: int,
    records: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """Insert or update earthquakes, keyed by their USGS id.

    Returns the `(inserted, updated)` counts. Re-running an ingestion is
    therefore idempotent: an event already stored is refreshed in place
    rather than duplicated.
    """
    inserted = 0
    updated = 0

    with connection.cursor() as cursor:
        for record in records:
            parameters = dict(record)
            parameters["dataset_id"] = dataset_id
            cursor.execute(_UPSERT_EARTHQUAKE, parameters)
            row = cursor.fetchone()
            if row is not None and row[0]:
                inserted += 1
            else:
                updated += 1

    return inserted, updated


def count_earthquakes(connection, dataset_id: int) -> int:
    """Return how many earthquakes are stored for a dataset."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM earthquakes WHERE dataset_id = %s",
            (dataset_id,),
        )
        row = cursor.fetchone()

    return row[0] if row is not None else 0
