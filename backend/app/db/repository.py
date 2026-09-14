"""Database access for datasets and events.

Route handlers should call these helpers instead of writing SQL inline, so
queries stay in one place as the project grows.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from psycopg.types.json import Jsonb

STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_UPSERT_EVENT = """
    INSERT INTO events (
        dataset_id, external_id, title, event_type, occurred_at, ended_at,
        source_updated_at, longitude, latitude, geometry, magnitude,
        magnitude_unit, attributes, url
    )
    VALUES (
        %(dataset_id)s, %(external_id)s, %(title)s, %(event_type)s,
        %(occurred_at)s, %(ended_at)s, %(source_updated_at)s,
        %(longitude)s, %(latitude)s, %(geometry)s, %(magnitude)s,
        %(magnitude_unit)s, %(attributes)s, %(url)s
    )
    ON CONFLICT (dataset_id, external_id) DO UPDATE SET
        title = EXCLUDED.title,
        event_type = EXCLUDED.event_type,
        occurred_at = EXCLUDED.occurred_at,
        ended_at = EXCLUDED.ended_at,
        source_updated_at = EXCLUDED.source_updated_at,
        longitude = EXCLUDED.longitude,
        latitude = EXCLUDED.latitude,
        geometry = EXCLUDED.geometry,
        magnitude = EXCLUDED.magnitude,
        magnitude_unit = EXCLUDED.magnitude_unit,
        attributes = EXCLUDED.attributes,
        url = EXCLUDED.url,
        ingested_at = CURRENT_TIMESTAMP
    RETURNING (xmax = 0) AS inserted
"""

# What a record may leave out. A source that has no duration, no shape
# beyond the point and nothing kind-specific need not say so.
_EVENT_DEFAULTS = {"ended_at": None, "geometry": None, "attributes": {}}


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
            SELECT id, name, source, description, created_at, status, kind
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
            RETURNING id, name, source, description, created_at, status, kind
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
        "kind": row[6],
    }


def get_dataset(connection, dataset_id: int) -> Optional[Dict[str, Any]]:
    """Return a single dataset, or None when it does not exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, name, source, description, created_at, status, kind
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


def upsert_events(
    connection,
    dataset_id: int,
    records: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """Insert or update events, keyed by dataset and source id.

    Returns the `(inserted, updated)` counts. Re-running an ingestion is
    therefore idempotent: an event already stored is refreshed in place
    rather than duplicated. The key includes the dataset, so two sources
    reporting the same id do not collide.

    One `executemany` rather than one `execute` per record: psycopg sends
    the whole batch in pipeline mode, so the cost is one round-trip to the
    database rather than one per event. Against a database in another
    region a week of USGS data took three minutes row by row.
    """
    inserted = 0
    updated = 0
    if not records:
        return inserted, updated

    parameters = []
    for record in records:
        row = dict(_EVENT_DEFAULTS, **record, dataset_id=dataset_id)
        row["attributes"] = Jsonb(row["attributes"] or {})
        row["geometry"] = None if row["geometry"] is None else Jsonb(row["geometry"])
        parameters.append(row)
    with connection.cursor() as cursor:
        cursor.executemany(_UPSERT_EVENT, parameters, returning=True)
        while True:
            row = cursor.fetchone()
            if row is not None and row[0]:
                inserted += 1
            else:
                updated += 1
            if not cursor.nextset():
                break

    return inserted, updated


# Filters accepted by the event queries, mapped to their SQL condition.
# An event with a NULL magnitude cannot satisfy a magnitude bound, and SQL
# already drops it: NULL >= 2 is NULL, not true.
EVENT_FILTERS = (
    ("min_magnitude", "magnitude >= %(min_magnitude)s"),
    ("max_magnitude", "magnitude <= %(max_magnitude)s"),
    ("start_time", "occurred_at >= %(start_time)s"),
    ("end_time", "occurred_at <= %(end_time)s"),
    ("event_type", "event_type = %(event_type)s"),
    ("min_latitude", "latitude >= %(min_latitude)s"),
    ("max_latitude", "latitude <= %(max_latitude)s"),
    ("min_longitude", "longitude >= %(min_longitude)s"),
    ("max_longitude", "longitude <= %(max_longitude)s"),
)


def _event_where(dataset_id: int, filters: Optional[Dict[str, Any]]):
    """Build the WHERE clause shared by the count and the listing.

    Both must use the same conditions: a total that ignored the filters
    would make the reported page count wrong.

    The returned clause is assembled from the constant strings in
    EVENT_FILTERS and never from user input; every value travels as a
    query parameter. The string formatting at the call sites is therefore
    safe, and must stay that way.
    """
    conditions = ["dataset_id = %(dataset_id)s"]
    parameters = {"dataset_id": dataset_id}

    for name, condition in EVENT_FILTERS:
        value = (filters or {}).get(name)
        if value is not None:
            conditions.append(condition)
            parameters[name] = value

    return " AND ".join(conditions), parameters


def count_events(
    connection,
    dataset_id: int,
    filters: Optional[Dict[str, Any]] = None,
) -> int:
    """Return how many events match, for a dataset."""
    where, parameters = _event_where(dataset_id, filters)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM events WHERE {0}".format(where),
            parameters,
        )
        row = cursor.fetchone()

    return row[0] if row is not None else 0


def list_events(
    connection,
    dataset_id: int,
    limit: int,
    offset: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a page of matching events, most recent first."""
    where, parameters = _event_where(dataset_id, filters)
    parameters["limit"] = limit
    parameters["offset"] = offset

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, external_id, title, event_type, occurred_at, ended_at,
                   source_updated_at, longitude, latitude, geometry,
                   magnitude, magnitude_unit, attributes, url
            FROM events
            WHERE {0}
            ORDER BY occurred_at DESC, id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """.format(where),
            parameters,
        )
        rows = cursor.fetchall()

    return [_event_from_row(row) for row in rows]


def _event_from_row(row) -> Dict[str, Any]:
    return {
        "id": row[0],
        "external_id": row[1],
        "title": row[2],
        "event_type": row[3],
        "occurred_at": row[4],
        "ended_at": row[5],
        "source_updated_at": row[6],
        "longitude": _to_float(row[7]),
        "latitude": _to_float(row[8]),
        "geometry": row[9],
        "magnitude": _to_float(row[10]),
        "magnitude_unit": row[11],
        "attributes": row[12] or {},
        "url": row[13],
    }


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

    return [_import_from_row(row) for row in rows]


def _import_from_row(row) -> Dict[str, Any]:
    return {
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


def get_import_row(connection, import_id: int) -> Optional[Dict[str, Any]]:
    """One run in the same shape list_imports returns."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, dataset_id, status, feed_url, queued_at, started_at,
                   finished_at, fetched, valid, invalid, inserted, updated,
                   invalid_sample, error
            FROM imports
            WHERE id = %s
            """,
            (import_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return _import_from_row(row)


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


def event_points(
    connection,
    dataset_id: int,
    limit: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[List[Any]]:
    """The matching events as `[longitude, latitude, magnitude, id]`.

    Same WHERE clause as the listing, so a map and the table beside it
    agree. Ordered by magnitude so that, when the limit cuts, it cuts the
    smallest events: a map that dropped the strongest ones would mislead.
    Events without a magnitude come last for the same reason.
    """
    where, parameters = _event_where(dataset_id, filters)
    parameters["limit"] = limit

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT longitude, latitude, magnitude, id
            FROM events
            WHERE {0}
            ORDER BY magnitude DESC NULLS LAST, occurred_at DESC
            LIMIT %(limit)s
            """.format(where),
            parameters,
        )
        rows = cursor.fetchall()

    return [[_to_float(row[0]), _to_float(row[1]), _to_float(row[2]), row[3]] for row in rows]


# Great-circle distance in kilometres between the two sides of a join,
# by the haversine formula. Plain SQL on purpose: PostGIS would do it
# better, but it is an extension the hosted database would have to offer.
_DISTANCE_KM = """
    2 * 6371 * ASIN(SQRT(
        POWER(SIN(RADIANS(b.latitude - a.latitude) / 2), 2)
        + COS(RADIANS(a.latitude)) * COS(RADIANS(b.latitude))
          * POWER(SIN(RADIANS(b.longitude - a.longitude) / 2), 2)
    ))
"""

_MATCH_COLUMNS = (
    "id", "external_id", "title", "occurred_at", "longitude", "latitude",
    "magnitude", "magnitude_unit", "attributes",
)

# One row per event of the filtered dataset that has a partner in the other
# one: the partner is the candidate nearest in time within the window and
# the radius. The window is checked first, on the indexed column, and the
# latitude gap before the distance, so the exact formula runs on few rows.
_MATCH_PAIRS = """
    WITH mine AS (
        SELECT {columns} FROM events WHERE {where}
    ),
    candidates AS (
        SELECT {a_columns}, {b_columns},
               EXTRACT(EPOCH FROM (b.occurred_at - a.occurred_at)) AS delta_seconds,
               {distance} AS distance_km
        FROM mine a
        JOIN events b
          ON b.dataset_id = %(other_id)s
         AND b.occurred_at BETWEEN a.occurred_at - %(window_seconds)s * INTERVAL '1 second'
                               AND a.occurred_at + %(window_seconds)s * INTERVAL '1 second'
         AND ABS(b.latitude - a.latitude) <= %(radius_km)s / 111.0
    ),
    pairs AS (
        SELECT DISTINCT ON (a_id) *
        FROM candidates
        WHERE distance_km <= %(radius_km)s
        ORDER BY a_id, ABS(delta_seconds), b_id
    )
"""


def _match_query() -> str:
    return _MATCH_PAIRS.format(
        columns=", ".join(_MATCH_COLUMNS),
        a_columns=", ".join("a.{0} AS a_{0}".format(c) for c in _MATCH_COLUMNS),
        b_columns=", ".join("b.{0} AS b_{0}".format(c) for c in _MATCH_COLUMNS),
        distance=_DISTANCE_KM,
        where="{where}",
    )


def _matched_event(row, offset: int) -> Dict[str, Any]:
    values = row[offset : offset + len(_MATCH_COLUMNS)]
    event = dict(zip(_MATCH_COLUMNS, values))
    for column in ("magnitude", "longitude", "latitude"):
        event[column] = _to_float(event[column])
    event["attributes"] = event["attributes"] or {}
    return event


def match_events(
    connection,
    dataset_id: int,
    other_id: int,
    window_seconds: float,
    radius_km: float,
    limit: int,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pair the filtered events of one dataset with the other's reports.

    Two agencies describe the same earthquake with their own id, origin
    time, epicentre and magnitude; the pairing is by closeness in time and
    space, and the deltas are the point. Returns the pair count and the
    mean deltas over every pair, plus the strongest `limit` pairs.
    """
    where, parameters = _event_where(dataset_id, filters)
    parameters.update(
        other_id=other_id,
        window_seconds=window_seconds,
        radius_km=radius_km,
        limit=limit,
    )
    query = _match_query().format(where=where)

    with connection.cursor() as cursor:
        cursor.execute(
            query
            + """
            SELECT COUNT(*),
                   AVG(ABS(delta_seconds)),
                   AVG(distance_km),
                   AVG(ABS(a_magnitude - b_magnitude))
            FROM pairs
            """,
            parameters,
        )
        matched, mean_delta, mean_distance, mean_delta_magnitude = cursor.fetchone()

        cursor.execute(
            query
            + """
            SELECT * FROM pairs
            ORDER BY a_magnitude DESC NULLS LAST, a_occurred_at DESC
            LIMIT %(limit)s
            """,
            parameters,
        )
        rows = cursor.fetchall()

    width = len(_MATCH_COLUMNS)
    pairs = []
    for row in rows:
        event = _matched_event(row, 0)
        other = _matched_event(row, width)
        delta_magnitude = (
            None
            if event["magnitude"] is None or other["magnitude"] is None
            else round(other["magnitude"] - event["magnitude"], 2)
        )
        pairs.append(
            {
                "event": event,
                "other": other,
                "delta_seconds": _to_float(row[2 * width]),
                "distance_km": _to_float(row[2 * width + 1]),
                "delta_magnitude": delta_magnitude,
            }
        )

    return {
        "matched": matched,
        "mean_abs_delta_seconds": _to_float(mean_delta),
        "mean_distance_km": _to_float(mean_distance),
        "mean_abs_delta_magnitude": _to_float(mean_delta_magnitude),
        "pairs": pairs,
    }


def strongest_events(
    connection,
    dataset_id: int,
    limit: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The largest-magnitude matching events, for the insights digest.

    Same WHERE clause as the listing and the summary, so the model is told
    about the same events the reader is looking at. Events with no magnitude
    cannot rank and are left out.
    """
    where, parameters = _event_where(dataset_id, filters)
    parameters["limit"] = limit

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT external_id, magnitude, magnitude_unit, title, event_type,
                   occurred_at, attributes
            FROM events
            WHERE {0} AND magnitude IS NOT NULL
            ORDER BY magnitude DESC, occurred_at DESC
            LIMIT %(limit)s
            """.format(where),
            parameters,
        )
        rows = cursor.fetchall()

    return [
        {
            "external_id": row[0],
            "magnitude": _to_float(row[1]),
            "magnitude_unit": row[2],
            "title": row[3],
            "event_type": row[4],
            "occurred_at": row[5],
            "attributes": row[6] or {},
        }
        for row in rows
    ]


def summarize_events(
    connection,
    dataset_id: int,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate the matching events.

    Uses the same WHERE clause as the listing, so a summary always describes
    exactly the events the listing would return.

    Days are UTC calendar days: event times are stored as naive UTC, so no
    conversion is applied.
    """
    where, parameters = _event_where(dataset_id, filters)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE magnitude IS NULL),
                   min(magnitude), max(magnitude), avg(magnitude),
                   min(occurred_at), max(occurred_at)
            FROM events
            WHERE {0}
            """.format(where),
            parameters,
        )
        totals = cursor.fetchone()

        cursor.execute(
            """
            SELECT event_type, count(*)
            FROM events
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
            FROM events
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


def fail_stale_imports(connection, older_than_minutes: int) -> List[Dict[str, Any]]:
    """Mark runs stuck at `processing` as failed, and return them.

    A run is only ever `processing` while a worker holds it. One that has
    been there longer than any run takes was abandoned — the worker died
    mid-run — and would otherwise sit there forever. The dataset's status
    is corrected too, but only when the stale run is its latest: a newer
    run that completed since already says the truth.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE imports
            SET status = %s,
                finished_at = CURRENT_TIMESTAMP,
                error = %s
            WHERE status = %s
              AND started_at < CURRENT_TIMESTAMP - make_interval(mins => %s)
            RETURNING id, dataset_id
            """,
            (
                STATUS_FAILED,
                "Abandoned: the worker stopped before finishing this run",
                STATUS_PROCESSING,
                older_than_minutes,
            ),
        )
        stale = [{"id": row[0], "dataset_id": row[1]} for row in cursor.fetchall()]

        for run in stale:
            cursor.execute(
                """
                UPDATE datasets
                SET status = %s
                WHERE id = %s
                  AND (
                    SELECT id FROM imports
                    WHERE dataset_id = %s
                    ORDER BY queued_at DESC, id DESC
                    LIMIT 1
                  ) = %s
                """,
                (STATUS_FAILED, run["dataset_id"], run["dataset_id"], run["id"]),
            )

    return stale
