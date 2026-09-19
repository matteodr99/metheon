"""The same data as the REST routes, as a GraphQL schema at `/api/graphql`.

Read-only: datasets, their events with the REST filters and paging, the
summary and the import history. Every resolver calls the repository
function its REST counterpart calls, with the same filter dictionary, so
the two APIs cannot disagree about a filter — a test asks both and
compares.

Strawberry is the one dependency: a schema declared as typed Python
classes, served by a FastAPI router with GraphiQL on GET, the way `/docs`
serves the REST API. Field names come out camelCase, as GraphQL clients
expect: `external_id` is `externalId` here.

Errors follow GraphQL, not HTTP: a refused filter or an unknown dataset is
an `errors` entry with the same sentence the REST route puts in `detail`,
and the status stays 200. Anything unexpected is masked before it reaches
the client; the traceback goes to the log, as it does for a 500.
"""

import dataclasses
from datetime import date, datetime
from typing import List, Optional

import psycopg
import strawberry
from graphql import GraphQLError
from starlette.concurrency import run_in_threadpool
from strawberry.extensions import MaskErrors
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.scalars import JSON

from app.filters import DEFAULT_PAGE_SIZE, page_problem, problem
from app.db import repository
from app.db.database import get_connection

DATABASE_UNAVAILABLE = "The database is unavailable"


class Context(BaseContext):
    """One connection per request, opened on first use.

    Introspection — what GraphiQL asks for when it loads — touches no
    table and should wake no database.
    """

    def __init__(self):
        super().__init__()
        self._connection = None

    @property
    def connection(self):
        if self._connection is None:
            self._connection = get_connection()
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def get_context():
    context = Context()
    try:
        yield context
    finally:
        context.close()


async def query(info, function, *args):
    """Run a repository call off the event loop.

    Resolvers are async so that sibling fields resolve concurrently, but
    psycopg is synchronous; a query against a remote database would
    otherwise hold the loop for its round-trip. A database that cannot be
    reached answers with the same sentence the REST routes use.
    """
    try:
        return await run_in_threadpool(function, info.context.connection, *args)
    except psycopg.OperationalError as error:
        raise GraphQLError(DATABASE_UNAVAILABLE) from error


def refuse(message: Optional[str]) -> None:
    if message is not None:
        raise GraphQLError(message)


@strawberry.input(description="Every filter the REST listing takes; bounds are inclusive and combine with AND.")
class EventFilterInput:
    min_magnitude: Optional[float] = None
    max_magnitude: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    event_type: Optional[str] = None
    min_latitude: Optional[float] = None
    max_latitude: Optional[float] = None
    min_longitude: Optional[float] = None
    max_longitude: Optional[float] = None

    def values(self) -> dict:
        values = dataclasses.asdict(self)
        refuse(problem(values))
        return values


def _values(event_filters: Optional[EventFilterInput]) -> dict:
    return event_filters.values() if event_filters is not None else {}


@strawberry.type
class Event:
    id: int
    external_id: str
    title: Optional[str]
    event_type: Optional[str]
    occurred_at: datetime
    ended_at: Optional[datetime]
    source_updated_at: Optional[datetime]
    longitude: float
    latitude: float
    geometry: Optional[JSON]
    magnitude: Optional[float]
    magnitude_unit: Optional[str]
    attributes: JSON
    url: Optional[str]


@strawberry.type
class EventPage:
    total: int = strawberry.field(description="Events matching the filters, not the whole dataset.")
    limit: int
    offset: int
    items: List[Event]


@strawberry.type
class MagnitudeSummary:
    min: Optional[float]
    max: Optional[float]
    average: Optional[float]
    unknown: int


@strawberry.type
class TimeSpan:
    first: Optional[datetime]
    last: Optional[datetime]


@strawberry.type
class EventTypeCount:
    event_type: Optional[str]
    count: int


@strawberry.type
class DayCount:
    day: date
    count: int


@strawberry.type
class Summary:
    total: int
    magnitude: MagnitudeSummary
    occurred_at: TimeSpan
    by_event_type: List[EventTypeCount]
    by_day: List[DayCount]


@strawberry.type
class ImportRun:
    id: int
    dataset_id: int
    status: str
    feed_url: str
    queued_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    fetched: int
    valid: int
    invalid: int
    inserted: int
    updated: int
    invalid_sample: Optional[str]
    error: Optional[str]


# The three fields below are nullable so that a refusal stays where it
# happened: a non-null field that errors takes its parent down with it,
# and a bad `limit` on `events` would null the dataset's name too.
@strawberry.type
class Dataset:
    id: int
    name: str
    source: str
    description: Optional[str]
    created_at: datetime
    status: str
    kind: str
    last_ingested_at: Optional[datetime]

    @strawberry.field(description="A page of events, most recent first.")
    async def events(
        self,
        info: strawberry.Info,
        filters: Optional[EventFilterInput] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> Optional[EventPage]:
        values = _values(filters)
        refuse(page_problem(limit, offset))
        total = await query(info, repository.count_events, self.id, values)
        rows = await query(info, repository.list_events, self.id, limit, offset, values)
        return EventPage(total=total, limit=limit, offset=offset, items=[Event(**row) for row in rows])

    @strawberry.field(description="The matching events aggregated; days are UTC.")
    async def summary(
        self, info: strawberry.Info, filters: Optional[EventFilterInput] = None
    ) -> Optional[Summary]:
        values = _values(filters)
        summary = await query(info, repository.summarize_events, self.id, values)
        return Summary(
            total=summary["total"],
            magnitude=MagnitudeSummary(**summary["magnitude"]),
            occurred_at=TimeSpan(**summary["occurred_at"]),
            by_event_type=[EventTypeCount(**row) for row in summary["by_event_type"]],
            by_day=[DayCount(**row) for row in summary["by_day"]],
        )

    @strawberry.field(description="Ingestion runs, most recent first.")
    async def imports(
        self,
        info: strawberry.Info,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> Optional[List[ImportRun]]:
        refuse(page_problem(limit, offset))
        rows = await query(info, repository.list_imports, self.id, limit, offset)
        return [ImportRun(**row) for row in rows]


@strawberry.type
class Query:
    @strawberry.field(description="Every dataset, by id.")
    async def datasets(self, info: strawberry.Info) -> List[Dataset]:
        rows = await query(info, repository.list_datasets)
        return [Dataset(**row) for row in rows]

    @strawberry.field(description="One dataset, or null when there is none with that id.")
    async def dataset(self, info: strawberry.Info, id: int) -> Optional[Dataset]:
        row = await query(info, repository.get_dataset, id)
        return Dataset(**row) if row is not None else None


def _mask(error: GraphQLError) -> bool:
    """Mask what was not raised on purpose.

    A GraphQLError is ours — a refused filter, an unavailable database —
    and a syntax or validation error has no original at all; both carry
    sentences meant for the client. Anything else is an exception whose
    text was never meant to leave the process.
    """
    original = error.original_error
    return original is not None and not isinstance(original, GraphQLError)


schema = strawberry.Schema(
    query=Query,
    # A factory, not an instance: Strawberry wants a fresh extension per request.
    extensions=[lambda: MaskErrors(should_mask_error=_mask, error_message="Unexpected error")],
)

# Documented by itself, through introspection and GraphiQL; the OpenAPI
# document describes the REST routes, and a POST whose response shape is
# whatever the query asked for has nothing to say there.
router = GraphQLRouter(schema, context_getter=get_context, include_in_schema=False)
