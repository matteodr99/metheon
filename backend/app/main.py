import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg

from app.db.database import get_connection
from app.db import repository
from app import jobs
from app import settings
from app.ingestion import IngestionError, runner, sources
from app import schemas
from app.ai import AIError, gemini, insights
from app.schemas import DatasetCreate
from app.logging_config import configure_logging

from datetime import datetime
from typing import Any, List, Optional

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
# Markers a map is asked to draw at most; a week of USGS data is about 2,200.
MAX_POINTS = 5000


logger = logging.getLogger("app.api")

# Probes call these every few seconds. At INFO they would drown everything
# else; they are still there at DEBUG for anyone chasing a probe problem.
QUIET_PATHS = frozenset({"/api/health", "/api/health/live"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging when the server starts, not when the module loads."""
    configure_logging()
    # A typo here should stop the process now, not fail the first ingest.
    logger.info("api started, ingestion mode %s", settings.ingestion_mode())
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
        {"name": "insights", "description": "What Gemini makes of a dataset. Off until a key is set."},
    ],
)

def configure_cors(application: FastAPI, origins: list) -> None:
    """Allow browsers on `origins` to call the API. Nothing is added for an
    empty list, so development — one origin through the Vite proxy — is
    untouched."""
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )


configure_cors(app, settings.cors_origins())


# The refusals a client can meet, declared once and attached per route.
NOT_FOUND = {404: {"model": schemas.Problem, "description": "No such dataset."}}
UPSTREAM = {502: {"model": schemas.Problem, "description": "Gemini failed or answered in the wrong shape."}}
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
        # A bounding box, in degrees. A box that crosses the antimeridian
        # would need min_longitude > max_longitude, which is refused as
        # inverted: not supported, and the bounds say so instead of
        # matching nothing.
        min_latitude: Optional[float] = Query(None, ge=-90, le=90),
        max_latitude: Optional[float] = Query(None, ge=-90, le=90),
        min_longitude: Optional[float] = Query(None, ge=-180, le=180),
        max_longitude: Optional[float] = Query(None, ge=-180, le=180),
    ):
        self._reject_inverted(min_magnitude, max_magnitude, "magnitude")
        self._reject_inverted(start_time, end_time, "time")
        self._reject_inverted(min_latitude, max_latitude, "latitude")
        self._reject_inverted(min_longitude, max_longitude, "longitude")

        self.values = {
            "min_magnitude": min_magnitude,
            "max_magnitude": max_magnitude,
            "start_time": start_time,
            "end_time": end_time,
            "event_type": event_type,
            "min_latitude": min_latitude,
            "max_latitude": max_latitude,
            "min_longitude": min_longitude,
            "max_longitude": max_longitude,
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
    # With no worker there is no queue to be ready; asking would keep a
    # deployment marked unhealthy forever. Reported as null, not false.
    queue_ok = jobs.ping() if settings.ingestion_mode() == "queue" else None
    ready = database_ok and queue_ok is not False

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
    "/api/datasets/{dataset_id}/earthquakes/points",
    tags=["earthquakes"],
    response_model=schemas.EarthquakePoints,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
def get_dataset_earthquake_points(
    dataset_id: int,
    limit: int = Query(MAX_POINTS, ge=1, le=MAX_POINTS),
    filters: EarthquakeFilters = Depends(),
):
    """Return the matching events as bare coordinates, for a map.

    Same filters as the listing, but no paging and only what a marker
    needs: `[longitude, latitude, magnitude, id]` per event. The limit
    exists because a map wants every matching event and a dataset can
    outgrow what a browser should draw; when it applies, the strongest
    events are the ones kept, and `total` says how many matched in all.
    """
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        total = repository.count_earthquakes(connection, dataset_id, filters.values)
        points = repository.earthquake_points(
            connection, dataset_id, limit, filters.values
        )

    return {
        "dataset_id": dataset_id,
        "total": total,
        "limit": limit,
        "filters": filters.applied(),
        "points": points,
    }


@app.get(
    "/api/datasets/{dataset_id}/earthquakes/matches",
    tags=["earthquakes"],
    response_model=schemas.Matches,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE},
)
def get_dataset_earthquake_matches(
    dataset_id: int,
    other: int = Query(description="The dataset to compare with."),
    window_seconds: float = Query(60, gt=0, le=3600),
    radius_km: float = Query(100, gt=0, le=1000),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    filters: EarthquakeFilters = Depends(),
):
    """Pair this dataset's events with another dataset's reports of them.

    Two agencies observe the same earthquake with different networks and
    report a different origin time, epicentre, depth and magnitude. A pair
    is an event of this dataset and the other dataset's report nearest in
    time within `window_seconds`, no farther than `radius_km`. The filters
    apply to this dataset's side, so the comparison covers what a reader
    is looking at.
    """
    if other == dataset_id:
        raise HTTPException(
            status_code=422, detail="A dataset cannot be compared with itself"
        )
    with get_connection() as connection:
        _get_dataset_or_404(connection, dataset_id)
        _get_dataset_or_404(connection, other)
        events = repository.count_earthquakes(connection, dataset_id, filters.values)
        matches = repository.match_earthquakes(
            connection, dataset_id, other, window_seconds, radius_km, limit, filters.values
        )

    return {
        "dataset_id": dataset_id,
        "other_id": other,
        "window_seconds": window_seconds,
        "radius_km": radius_km,
        "limit": limit,
        "filters": filters.applied(),
        "events": events,
        "unmatched": events - matches["matched"],
        **matches,
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


@app.get("/api/ai", tags=["insights"], response_model=schemas.AIStatus)
def ai_status():
    """Whether insights are available, so a client can show or hide them."""
    return {"configured": gemini.is_configured(), "model": gemini.DEFAULT_MODEL}


@app.get(
    "/api/datasets/{dataset_id}/insights",
    tags=["insights"],
    response_model=schemas.Insights,
    responses={**NOT_FOUND, **INVALID, **UNAVAILABLE, **UPSTREAM},
)
def get_dataset_insights(
    dataset_id: int,
    filters: EarthquakeFilters = Depends(),
):
    """Ask Gemini what the filtered data shows.

    The model is given the same summary the summary endpoint returns, plus
    the strongest events — never the rows. Same filters, so the reader and
    the model are looking at the same thing.

    503 when no key is configured: the feature is off, the rest of the API
    is not. 502 when Gemini fails or answers outside its schema.
    """
    with get_connection() as connection:
        dataset = _get_dataset_or_404(connection, dataset_id)
        summary = repository.summarize_earthquakes(connection, dataset_id, filters.values)
        strongest = repository.strongest_earthquakes(
            connection, dataset_id, insights.STRONGEST_EVENTS, filters.values
        )
    summary["filters"] = filters.applied()

    try:
        answer = insights.generate_insights(dataset, summary, strongest)
    except AIError as exc:
        if not exc.configured:
            logger.info("insights requested for dataset %s but AI is not configured", dataset_id)
            raise HTTPException(status_code=503, detail=str(exc))
        logger.warning("insights for dataset %s failed: %s", dataset_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    logger.info("insights produced for dataset %s (%s)", dataset_id, gemini.DEFAULT_MODEL)
    return {
        "dataset_id": dataset_id,
        "filters": filters.applied(),
        "model": gemini.DEFAULT_MODEL,
        **answer,
    }


@app.post(
    "/api/datasets/{dataset_id}/ingest",
    tags=["datasets"],
    response_model=schemas.ImportRun,
    responses={
        202: {"model": schemas.ImportRun, "description": "Queued; a worker will run it."},
        **NOT_FOUND,
        **INVALID,
        **UNAVAILABLE,
        **UPSTREAM,
    },
)
def ingest_dataset(dataset_id: int, response: Response):
    """Ingest the dataset's source feed, and answer with the run.

    In `queue` mode the run is handed to Redis and a worker, and this
    answers 202 with the run still queued; follow it through
    `GET /api/datasets/{id}/imports`. In `inline` mode there is no worker,
    the run happens inside this request, and the answer is 200 with the run
    finished. Same body either way: the row from the import history.
    """
    with get_connection() as connection:
        dataset = _get_dataset_or_404(connection, dataset_id)

    feed_url = _get_source_or_422(dataset["source"]).default_feed_url

    with get_connection() as connection:
        import_id = repository.create_import(connection, dataset_id, feed_url)

    if settings.ingestion_mode() == "inline":
        try:
            runner.run_import(import_id)
        except IngestionError as exc:
            # The runner has already recorded the failure on the run.
            logger.warning("import %s: failed inline, %s", import_id, exc)
            raise HTTPException(status_code=502, detail=str(exc))
        logger.info("import %s: completed inline for dataset %s", import_id, dataset_id)
        response.status_code = 200
    else:
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
        response.status_code = 202

    with get_connection() as connection:
        return repository.get_import_row(connection, import_id)
