import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
import psycopg

from app.db.database import get_connection
from app.db import repository
from app import jobs
from app.ingestion import sources
from app import schemas
from app.schemas import DatasetCreate
from app.logging_config import configure_logging

from datetime import datetime
from typing import Any, List, Optional

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


logger = logging.getLogger("app.api")

# Probes call these every few seconds. At INFO they would drown everything
# else; they are still there at DEBUG for anyone chasing a probe problem.
QUIET_PATHS = frozenset({"/api/health", "/api/health/live"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging when the server starts, not when the module loads."""
    configure_logging()
    logger.info("api started")
    yield
    logger.info("api stopping")


app = FastAPI(
    title="Metheon API",
    description=(
        "Public datasets, ingested and queryable. Today: earthquakes from "
        "USGS and INGV.\n\n"
        "Every refusal carries a `detail` sentence saying why."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Readiness and liveness, for probes."},
        {"name": "sources", "description": "What a dataset can be created for."},
        {"name": "datasets", "description": "Datasets and their ingestion."},
        {"name": "earthquakes", "description": "The events stored for a dataset."},
    ],
)

# The refusals a client can meet, declared once and attached per route.
NOT_FOUND = {404: {"model": schemas.Problem, "description": "No such dataset."}}
INVALID = {422: {"model": schemas.Problem, "description": "The request was refused; `detail` says why."}}
UNAVAILABLE = {503: {"model": schemas.Problem, "description": "A dependency is down."}}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per request: method, path, status, duration.

    Written after the response so the status and the time are real. The
    exception handlers answer before this runs, so a 503 or a 500 shows up
    here with its true status too.
    """
    started = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - started) * 1000
    level = logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO
    logger.log(
        level,
        "%s %s %s %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, exc: psycopg.OperationalError):
    """An unreachable database is a 503, on every route.

    The service is running; a dependency is not. 503 tells the client to
    try again, which is the truth — a 500 would say the request itself is
    broken.
    """
    logger.warning("%s %s: database unavailable: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is unavailable"},
    )


@app.exception_handler(Exception)
def unexpected_failure(request: Request, exc: Exception):
    """Anything unforeseen is a 500 with a fixed body.

    The traceback goes to the log, where someone can act on it, and never to
    the client, where it would only leak internals.
    """
    # exc_info is passed explicitly: this handler runs outside the `except`
    # block that caught the error, so logger.exception() would find no
    # active exception and log "NoneType: None" instead of the traceback.
    logger.error(
        "%s %s: unhandled %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def _get_source_or_422(source: str) -> sources.Source:
    found = sources.get_source(source)
    if found is None:
        logger.warning("refused unknown source %r", source)
        raise HTTPException(
            status_code=422,
            detail="Unknown source {0!r}. Known sources: {1}".format(
                source, ", ".join(sources.known_sources())
            ),
        )
    return found


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


@app.get("/api/health/live", tags=["health"], response_model=schemas.Liveness)
def liveness():
    """Answer as long as the process is running.

    Touches no dependency on purpose: a liveness probe that failed because
    the database was down would get the process restarted, and restarting
    the process does not bring the database back.
    """
    return {"status": "alive", "service": "metheon"}


@app.get(
    "/api/health",
    tags=["health"],
    response_model=schemas.Readiness,
    responses={503: {"model": schemas.Readiness, "description": "A dependency is down; the body says which."}},
)
def readiness(response: Response):
    """Report whether the API can serve, and say so in the status code.

    Machines read the code, not the body: `degraded` in a 200 reads as
    healthy to a probe or a load balancer. A missing dependency is a 503,
    and never a 500 — an unreachable database is "not ready", not "broken".
    """
    database_ok = _database_answers()
    queue_ok = jobs.ping()
    ready = database_ok and queue_ok

    if not ready:
        response.status_code = 503

    return {
        "status": "ok" if ready else "degraded",
        "service": "metheon",
        "database": database_ok,
        "queue": queue_ok,
    }


def _database_answers() -> bool:
    try:
        with get_connection() as connection:
            return repository.ping(connection)
    except psycopg.OperationalError:
        return False


@app.get("/api/sources", tags=["sources"], response_model=List[schemas.SourceInfo])
def get_sources():
    """The sources a dataset can be created for."""
    return [
        {
            "key": source.key,
            "name": source.name,
            "default_feed_url": source.default_feed_url,
        }
        for source in sorted(sources.SOURCES.values(), key=lambda s: s.key)
    ]


@app.get(
    "/api/datasets",
    tags=["datasets"],
    response_model=List[schemas.Dataset],
    responses=UNAVAILABLE,
)
def get_datasets():
    with get_connection() as connection:
        return repository.list_datasets(connection)


@app.post(
    "/api/datasets",
    tags=["datasets"],
    response_model=schemas.Dataset,
    responses={**INVALID, **UNAVAILABLE},
)
def create_dataset(dataset: DatasetCreate):
    """Create a dataset. Its source must be one the platform can ingest.

    Refusing an unknown source here is kinder than accepting a dataset that
    can never be imported and letting the failure surface later.
    """
    source = _get_source_or_422(dataset.source)

    with get_connection() as connection:
        created = repository.create_dataset(
            connection,
            dataset.name,
            dataset.source,
            dataset.description,
        )

    logger.info("created dataset %s %r (%s)", created["id"], created["name"], source.key)
    return created


@app.get(
    "/api/datasets/{dataset_id}/earthquakes",
    tags=["earthquakes"],
    response_model=schemas.EarthquakePage,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
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


@app.get(
    "/api/datasets/{dataset_id}/earthquakes/summary",
    tags=["earthquakes"],
    response_model=schemas.Summary,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
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


@app.get(
    "/api/datasets/{dataset_id}/imports",
    tags=["datasets"],
    response_model=schemas.ImportPage,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
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


@app.post(
    "/api/datasets/{dataset_id}/ingest",
    tags=["datasets"],
    status_code=202,
    response_model=schemas.IngestAccepted,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
def ingest_dataset(dataset_id: int):
    """Queue an ingestion run for this dataset.

    The request returns as soon as the run is queued; a worker picks it up
    and does the work. Follow its progress through
    `GET /api/datasets/{id}/imports`, or the dataset status.
    """
    with get_connection() as connection:
        dataset = _get_dataset_or_404(connection, dataset_id)

    # A dataset created before sources were validated could name one the
    # registry does not know; that is reported here rather than left to
    # fail inside the worker.
    feed_url = _get_source_or_422(dataset["source"]).default_feed_url

    with get_connection() as connection:
        import_id = repository.create_import(connection, dataset_id, feed_url)

    try:
        jobs.enqueue_import(import_id)
    except jobs.QueueError as exc:
        # The run exists in the history, so a queue outage is visible there
        # rather than being silently swallowed.
        logger.warning("import %s: could not queue, %s", import_id, exc)
        with get_connection() as connection:
            repository.fail_import(connection, import_id, str(exc))
        _set_status(dataset_id, repository.STATUS_FAILED)
        raise HTTPException(status_code=503, detail=str(exc))

    _set_status(dataset_id, repository.STATUS_QUEUED)
    logger.info("import %s: queued for dataset %s", import_id, dataset_id)

    return {
        "import_id": import_id,
        "dataset_id": dataset_id,
        "status": repository.STATUS_QUEUED,
        "feed_url": feed_url,
    }
