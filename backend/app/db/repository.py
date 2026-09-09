"""Database access for datasets and earthquakes.

Route handlers should call these helpers instead of writing SQL inline, so
queries stay in one place as the project grows.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
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


def _to_float(value: Any) -> Optional[float]:
    """Turn a NUMERIC column into a plain float.

    psycopg returns Decimal for NUMERIC. Converting here keeps the shape of
    the API responses independent of how the serializer treats Decimal.
    """
    if isinstance(value, Decimal):
        return float(value)
    return value


def ping(connection) -> bool:
    """Run a trivial query to prove the database answers."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()

    return row is not None and row[0] == 1


def list_datasets(connection) -> List[Dict[str, Any]]:
    """Return every dataset, ordered by id."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, source, description, created_at, status
            FROM datasets
            ORDER BY id
            """
        )
        rows = cursor.fetchall()

    return [_dataset_from_row(row) for row in rows]


def create_dataset(
    connection,
    name: str,
    source: str,
    description: Optional[str],
) -> Dict[str, Any]:
    """Insert a dataset and return it as stored.

    `status` is deliberately left to the column default, so the client
    cannot choose the initial state of an import.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO datasets (name, source, description)
            VALUES (%s, %s, %s)
            RETURNING id, name, source, description, created_at, status
            """,
            (name, source, description),
        )
        row = cursor.fetchone()

    return _dataset_from_row(row)


def _dataset_from_row(row) -> Dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "description": row[3],
        "created_at": row[4],
        "status": row[5],
    }


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

    return _dataset_from_row(row)


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


# Filters accepted by the earthquake queries, mapped to their SQL condition.
# An event with a NULL magnitude cannot satisfy a magnitude bound, and SQL
# already drops it: NULL >= 2 is NULL, not true.
EARTHQUAKE_FILTERS = (
    ("min_magnitude", "magnitude >= %(min_magnitude)s"),
    ("max_magnitude", "magnitude <= %(max_magnitude)s"),
    ("start_time", "occurred_at >= %(start_time)s"),
    ("end_time", "occurred_at <= %(end_time)s"),
    ("event_type", "event_type = %(event_type)s"),
)


def _earthquake_where(dataset_id: int, filters: Optional[Dict[str, Any]]):
    """Build the WHERE clause shared by the count and the listing.

    Both must use the same conditions: a total that ignored the filters
    would make the reported page count wrong.

    The returned clause is assembled from the constant strings in
    EARTHQUAKE_FILTERS and never from user input; every value travels as a
    query parameter. The string formatting at the call sites is therefore
    safe, and must stay that way.
    """
    conditions = ["dataset_id = %(dataset_id)s"]
    parameters = {"dataset_id": dataset_id}

    for name, condition in EARTHQUAKE_FILTERS:
        value = (filters or {}).get(name)
        if value is not None:
            conditions.append(condition)
            parameters[name] = value

    return " AND ".join(conditions), parameters


def count_earthquakes(
    connection,
    dataset_id: int,
    filters: Optional[Dict[str, Any]] = None,
) -> int:
    """Return how many earthquakes match, for a dataset."""
    where, parameters = _earthquake_where(dataset_id, filters)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM earthquakes WHERE {0}".format(where),
            parameters,
        )
        row = cursor.fetchone()

    return row[0] if row is not None else 0


def list_earthquakes(
    connection,
    dataset_id: int,
    limit: int,
    offset: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a page of matching earthquakes, most recent first."""
    where, parameters = _earthquake_where(dataset_id, filters)
    parameters["limit"] = limit
    parameters["offset"] = offset

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, external_id, magnitude, magnitude_type, place,
                   event_type, occurred_at, longitude, latitude, depth_km,
                   tsunami, significance, url
            FROM earthquakes
            WHERE {0}
            ORDER BY occurred_at DESC, id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """.format(where),
            parameters,
        )
        rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "external_id": row[1],
            "magnitude": _to_float(row[2]),
            "magnitude_type": row[3],
            "place": row[4],
            "event_type": row[5],
            "occurred_at": row[6],
            "longitude": _to_float(row[7]),
            "latitude": _to_float(row[8]),
            "depth_km": _to_float(row[9]),
            "tsunami": row[10],
            "significance": row[11],
            "url": row[12],
        }
        for row in rows
    ]


def create_import(connection, dataset_id: int, feed_url: str) -> int:
    """Record a queued import run and return its id.

    The row is written before the job is enqueued, so a run always exists in
    the history even if the queue rejects it.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO imports (dataset_id, status, feed_url)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (dataset_id, STATUS_QUEUED, feed_url),
        )
        row = cursor.fetchone()

    return row[0]


def complete_import(
    connection,
    import_id: int,
    fetched: int,
    valid: int,
    invalid: int,
    inserted: int,
    updated: int,
    invalid_sample: Optional[str] = None,
) -> None:
    """Close an import run that succeeded, recording its counts.

    `invalid_sample` keeps the first few validation errors: a run that
    completes with a non-zero `invalid` count is only useful if you can see
    why the features were rejected.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE imports
            SET status = %s,
                finished_at = CURRENT_TIMESTAMP,
                fetched = %s,
                valid = %s,
                invalid = %s,
                inserted = %s,
                updated = %s,
                invalid_sample = %s
            WHERE id = %s
            """,
            (
                STATUS_COMPLETED,
                fetched,
                valid,
                invalid,
                inserted,
                updated,
                invalid_sample,
                import_id,
            ),
        )


def fail_import(connection, import_id: int, error: str) -> None:
    """Close an import run that failed, recording why."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE imports
            SET status = %s,
                finished_at = CURRENT_TIMESTAMP,
                error = %s
            WHERE id = %s
            """,
            (STATUS_FAILED, error, import_id),
        )


def count_imports(connection, dataset_id: int) -> int:
    """Return how many import runs a dataset has."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM imports WHERE dataset_id = %s",
            (dataset_id,),
        )
        row = cursor.fetchone()

    return row[0] if row is not None else 0


def list_imports(
    connection,
    dataset_id: int,
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    """Return a page of import runs, most recent first."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, dataset_id, status, feed_url, queued_at, started_at,
                   finished_at, fetched, valid, invalid, inserted, updated,
                   invalid_sample, error
            FROM imports
            WHERE dataset_id = %s
            ORDER BY queued_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (dataset_id, limit, offset),
        )
        rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "dataset_id": row[1],
            "status": row[2],
            "feed_url": row[3],
            "queued_at": row[4],
            "started_at": row[5],
            "finished_at": row[6],
            "fetched": row[7],
            "valid": row[8],
            "invalid": row[9],
            "inserted": row[10],
            "updated": row[11],
            "invalid_sample": row[12],
            "error": row[13],
        }
        for row in rows
    ]


def get_import(connection, import_id: int) -> Optional[Dict[str, Any]]:
    """Return a single import run, or None when it does not exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, dataset_id, status, feed_url
            FROM imports
            WHERE id = %s
            """,
            (import_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "dataset_id": row[1],
        "status": row[2],
        "feed_url": row[3],
    }


def start_import(connection, import_id: int) -> None:
    """Mark an import run as picked up by a worker."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE imports
            SET status = %s, started_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (STATUS_PROCESSING, import_id),
        )


def summarize_earthquakes(
    connection,
    dataset_id: int,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate the matching earthquakes.

    Uses the same WHERE clause as the listing, so a summary always describes
    exactly the events the listing would return.

    Days are UTC calendar days: event times are stored as naive UTC, so no
    conversion is applied.
    """
    where, parameters = _earthquake_where(dataset_id, filters)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE magnitude IS NULL),
                   min(magnitude), max(magnitude), avg(magnitude),
                   min(occurred_at), max(occurred_at)
            FROM earthquakes
            WHERE {0}
            """.format(where),
            parameters,
        )
        totals = cursor.fetchone()

        cursor.execute(
            """
            SELECT event_type, count(*)
            FROM earthquakes
            WHERE {0}
            GROUP BY event_type
            ORDER BY count(*) DESC, event_type
            """.format(where),
            parameters,
        )
        by_event_type = cursor.fetchall()

        cursor.execute(
            """
            SELECT occurred_at::date AS day, count(*)
            FROM earthquakes
            WHERE {0}
            GROUP BY day
            ORDER BY day
            """.format(where),
            parameters,
        )
        by_day = cursor.fetchall()

    average = _to_float(totals[4])

    return {
        "total": totals[0],
        "magnitude": {
            "min": _to_float(totals[2]),
            "max": _to_float(totals[3]),
            "average": round(average, 2) if average is not None else None,
            "unknown": totals[1],
        },
        "occurred_at": {"first": totals[5], "last": totals[6]},
        "by_event_type": [
            {"event_type": row[0], "count": row[1]} for row in by_event_type
        ],
        "by_day": [{"day": row[0], "count": row[1]} for row in by_day],
    }
