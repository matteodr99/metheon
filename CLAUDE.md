# CLAUDE.md — Metheon

## Project

**Metheon** is a cloud-native platform for ingesting, processing, and
analyzing public seismic data: earthquake catalogues from several agencies,
stored in one schema so they can be filtered, aggregated and compared alike.
The pipeline is generic, the schema is not; a non-seismic source would need a
wider event model, and that is not to be built without a concrete dataset
asking for it.

Core idea:

Public Data → Ingestion → Processing → PostgreSQL → API → Analytics → AI Insights

The project is a personal portfolio/open-source project under the MIT
licence (`LICENSE`, copyright Matteo De Ronzis). It must not use personal or
sensitive user data.

## Development approach

- Work incrementally, one small step at a time.
- Keep the implementation simple and working before adding complexity.
- Do not invent functionality that has not been implemented.
- Prefer clear, production-oriented structure over premature abstraction.
- Keep technologies correctly attributed to their actual project/module; do not mix unrelated concerns.
- Do not introduce paid cloud infrastructure during the local-development phase.
- Do not add AWS just for the sake of using AWS.

## Current stack

### Already implemented

- Python 3.12
- FastAPI
- Uvicorn
- psycopg 3
- httpx
- redis-py
- PostgreSQL 16
- Redis 7
- Gemini API, optional, over HTTP
- Docker / Docker Compose
- Kubernetes, locally, via Kind
- React 19 + TypeScript, built with Vite
- Leaflet 1.9, for the map, with OpenStreetMap tiles
- Pytest, Vitest and Testing Library
- GitHub Actions
- Git

### Planned / intended

- Public deployment, per the table below

Deployment and hosting are decided separately and are not to be implemented
without being asked.

Do not treat planned technologies as already implemented.

### Hosting decisions

Decided on 2026-09-11 under one constraint: **nothing is paid for**. Every
row is a free plan, with the limit that plan imposes.

| Component | Choice | Free-plan limit |
| --- | --- | --- |
| Frontend hosting | Cloudflare Pages | 500 builds/month; now the "legacy" flow, see below |
| Backend hosting | Render (Koyeb was the first choice, see below) | 750 instance-hours a month; sleeps after 15 min idle and takes about a minute to wake; no free worker |
| Production database | Neon PostgreSQL | 0.5 GB; suspends after 5 min idle and **resumes on its own** at the next connection |
| Worker in production | none | see below |
| Redis in production | none | see below |
| AI | Gemini API | free tier rate limits |
| Kubernetes | Kind / Minikube | local only; no production role in this stack |
| CI/CD | GitHub Actions | free for public repositories |

Neon was chosen over Supabase because Supabase's free project pauses after a
week without traffic and must be restored by hand; Neon's resumes itself.
Metheon uses none of Supabase's extras around Postgres.

Koyeb was chosen first, with Render as the fallback. On 2026-09-14 the
fallback became the choice: Koyeb was acquired by Mistral in February 2026
and no longer opens free accounts — a new sign-up lands on a notice page
with nothing to deploy. Nothing in the code cared; the switch cost one
environment variable, `PORT=8000`, because Render tells a service which
port to bind through `PORT` and the Dockerfile binds 8000.

**No free PaaS runs a background worker.** Render, like Koyeb, charges for
worker services. The queue and the worker therefore stay the local
development and Kind architecture, and production ingests inline: `INGESTION_MODE`, `queue` by default and
`inline` when deployed, makes `POST /ingest` call the runner directly and
answer with the finished run instead of queueing it. A week's USGS feed
ingests in under a second, so it fits in a request. The `imports` history,
the status transitions and the response shape are unchanged in both
modes.

The code side of this is done (2026-09-14), all of it inert locally:

- `INGESTION_MODE` in `app/settings.py`: `queue` by default, `inline` runs
  the ingestion inside the request and answers 200 with the finished run.
  A value that is neither stops the process at startup
- CORS from `CORS_ORIGINS`, empty by default, in which case no middleware
  is installed at all — a test asserts `app.user_middleware == []`
- `POSTGRES_SSLMODE`, appended to the connection string only when set
- `VITE_API_URL`, read at build time in `frontend/src/api/index.ts`
- `python -m app.db.apply_schema` applies `init.sql` to whatever database
  the environment names, for a host with no `docker-entrypoint-initdb.d`
- `backend/Dockerfile` already serves the API by default

Everything is up (2026-09-14):

- Neon, region `eu-central-1`, database `neondb`, schema applied with
  `apply_schema` from this machine. The first inline ingestion from here
  took three minutes and led to the batched upsert; see `POST /ingest`
- Render, region Frankfurt, one Free web service built from
  `backend/Dockerfile` with root directory `backend`. Its health check is
  `/api/health/live`, not `/api/health`: a failing check makes Render
  restart the instance, and a restart does not revive a suspended Neon —
  the same reason the two endpoints exist. `INGESTION_MODE=inline`; an
  ingestion of a week's USGS feed answers in under three seconds there.
  The API is at `https://metheon.onrender.com`
- Cloudflare Pages, project `metheon`, root directory `frontend`, preset
  React (Vite), built with `VITE_API_URL=https://metheon.onrender.com` and
  `NODE_VERSION=20.19.5` (the `.nvmrc` version; Cloudflare does not read
  the file). The bundle it builds is byte-identical to a local build with
  the same variable. `CORS_ORIGINS=https://metheon.pages.dev` is set on
  Render, and only that origin gets the headers. The dashboard is at
  `https://metheon.pages.dev`

  Cloudflare now labels the Pages Git workflow "legacy" and steers new
  projects to Workers with static assets. Pages still builds and serves;
  if it is ever closed, the move is one `frontend/wrangler.jsonc` naming
  `dist` as the assets directory and `npx wrangler deploy` as the deploy
  command, nothing in the code

- `.github/workflows/ingest.yml`, the stand-in for the worker: every six
  hours it lists the datasets on the deployed API and posts `/ingest` for
  each. It is a separate workflow from `ci.yml` because it verifies
  nothing about the code; it fails when a run does not complete, so the
  Actions tab is where a dead ingestion shows. `curl` retries the first
  request because Render may be asleep. `/ingest` stays unauthenticated,
  a known and accepted limit for public, idempotent, recorded runs

Deployment is complete. Nothing above changes how the project runs
locally, in CI or on Kind.

## Design documents

`docs/design/` holds proposals that are decided before they are built.
A document there is a plan, not a description: check its status line
before treating anything in it as implemented.

- `generic-events.md` — from an `earthquakes` table to an `events` table
  with a kind per dataset, so that non-seismic public data (NASA EONET,
  GDACS) can be ingested by the same pipeline. Status: proposal.

## Repository structure

Current structure:

```text
metheon/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── settings.py
│   │   ├── logging_config.py
│   │   ├── ai/
│   │   │   ├── __init__.py
│   │   │   ├── gemini.py
│   │   │   └── insights.py
│   │   ├── jobs.py
│   │   ├── worker.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py
│   │   │   ├── apply_schema.py
│   │   │   ├── repository.py
│   │   │   └── init.sql
│   │   └── ingestion/
│   │       ├── __init__.py
│   │       ├── sources.py
│   │       ├── geojson.py
│   │       ├── fdsn.py
│   │       ├── usgs.py
│   │       ├── ingv.py
│   │       ├── emsc.py
│   │       └── runner.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── fixtures/
│   │   ├── test_usgs_fetch.py
│   │   └── test_usgs_normalization.py
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── index.ts
│   │   ├── components/
│   │   │   ├── BarChart.tsx
│   │   │   ├── ComparePanel.tsx
│   │   │   ├── EarthquakeBrowser.tsx
│   │   │   ├── EarthquakeMap.tsx
│   │   │   ├── IngestionPanel.tsx
│   │   │   ├── InsightsPanel.tsx
│   │   │   ├── NewDatasetForm.tsx
│   │   │   └── Summary.tsx
│   │   ├── theme/
│   │   │   ├── theme.ts
│   │   │   └── ThemeToggle.tsx
│   │   ├── test/
│   │   ├── App.tsx
│   │   ├── index.css
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── k8s/
│   ├── kind-config.yaml
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── config.yaml
│   ├── postgres.yaml
│   ├── redis.yaml
│   ├── api.yaml
│   ├── worker.yaml
│   └── dev.sh
├── docs/
│   └── design/
│       └── generic-events.md
├── LICENSE
├── .env.example
├── .gitignore
├── .nvmrc
├── .python-version
├── README.md
└── docker-compose.yml
```

The repository may evolve. Keep this document updated when the architecture changes materially.

## Local development

### PostgreSQL

PostgreSQL runs through Docker Compose.

Expected service:

- service: `postgres`
- container: `metheon-postgres`
- database: `metheon`
- user: `metheon`
- port: `5432`

Start PostgreSQL:

```bash
docker compose up -d
```

Check services:

```bash
docker compose ps
```

### Backend

The backend uses a Python 3.12 virtual environment (`.python-version`):

```text
.venv/
```

Install dependencies:

```bash
pip install -r backend/requirements.txt
```

Run FastAPI from `backend/`:

```bash
uvicorn app.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## API contract

`app/schemas.py` holds the Pydantic request and response models. Every route
declares a `response_model`, the error responses it can return (`404`,
`422`, `503`, all with the one-field `Problem` body) and a tag. That is what
`/docs` renders, and it is also enforced: FastAPI validates handler output
against the model, so a wrong shape becomes a 500 rather than JSON that
merely looks right. `tests/test_openapi.py` walks the generated spec and
fails if any route loses its model, its tag or a declared error.

Routes that never open a connection — the two health checks and `/sources`
— do not declare `503`; every other one does, because the handler for a dead
database applies to all of them.

## Current API

### GET /api/health

The readiness check. Reports whether PostgreSQL and Redis answer:

```json
{"status": "ok", "service": "metheon", "database": true, "queue": true}
```

A missing dependency makes the body `degraded` and the response a **503**,
never a 500: an unreachable database is caught and reported as
`database: false`. The status code is what probes and load balancers read;
`degraded` in a 200 would pass for healthy. In `inline` mode `queue` is
`null` and not consulted: there is no Redis on such a host, and asking
would keep the deployment unready forever.

### GET /api/health/live

The liveness check. `200` as long as the process runs, and it touches no
dependency: a liveness probe failing for a dead database would restart the
process, which does not revive the database. Keep the two separate.

### GET /api/sources

Lists the registered sources: key, name and default feed url.

### GET /api/datasets

Returns the datasets currently stored in PostgreSQL.

### POST /api/datasets

Creates a dataset.

Request model:

```json
{
  "name": "Global Earthquakes",
  "source": "USGS",
  "description": "Public earthquake data provided by the US Geological Survey."
}
```

`status` is assigned by the database and must not currently be supplied by the client.

`source` must match a key in the registry, case-insensitively; an unknown
source is refused with `422`.

### GET /api/datasets/{id}/earthquakes

Returns a page of the earthquakes stored for a dataset, ordered by event time,
most recent first.

Query parameters: `limit` (default 50, between 1 and 500), `offset`
(default 0), and the optional filters `min_magnitude`, `max_magnitude`,
`start_time`, `end_time`, `event_type`, and a bounding box in
`min_latitude`, `max_latitude`, `min_longitude`, `max_longitude`. Bounds
are inclusive and filters combine with `AND`. Latitude is validated to
−90…90 and longitude to −180…180 by FastAPI; a box crossing the
antimeridian would be an inverted longitude range and is refused rather
than supported.

`total` counts the matching events, not the whole dataset: the count and the
listing share one `WHERE` clause, built in `repository._earthquake_where`. A
total that ignored the filters would make the reported page count wrong.

That clause is assembled only from constant strings, and every value travels
as a query parameter. Keep it that way if you add a filter.

An inverted range returns `422` instead of an empty page. Out-of-range values
return `422`, an unknown dataset `404`.

Aggregations and charts remain part of Phase 3.

### GET /api/datasets/{id}/earthquakes/points

The matching events as `[longitude, latitude, magnitude, id]`, for the
map: the listing pages 25 at a time and a map wants every matching event.
Same `EarthquakeFilters` dependency and the same `WHERE` clause, so the map
and the table agree. `limit` defaults to and is capped at `MAX_POINTS`
(5000; a week of USGS is about 2,200), and the query orders by magnitude
descending with nulls last so that a cut drops the weakest events, never
the strongest; `total` is the full count regardless.

### GET /api/datasets/{id}/earthquakes/matches?other={id2}

Cross-agency reconciliation, as a query rather than stored data: at these
sizes it is a computation on request, and a table of pairs would be one
more thing to keep in step with two ingestions. `repository.match_earthquakes`
does it in one CTE chain — the filtered events of `{id}`, the candidates of
`other` within `window_seconds` (checked first, on the indexed
`occurred_at`) and within `radius_km / 111` degrees of latitude (cheap,
before the exact distance), then `DISTINCT ON (a_id)` ordered by `|Δt|` to
keep the nearest candidate per event. The distance is haversine in plain
SQL; PostGIS would be an extension the hosted database has to offer. The
filters go into the `mine` CTE, so `_earthquake_where` stays unqualified
and untouched. Two executions share the chain: one for the counts and
means over every pair, one for the strongest `limit` pairs.

The latitude pre-check is an optimisation and must stay looser than the
radius; a test seeds a candidate at the same latitude 180 km east, which
only the exact distance can reject, so the pre-check cannot quietly stand
in for it.

### GET /api/datasets/{id}/imports

Returns the import history of a dataset, most recent run first, with the same
`limit` and `offset` parameters as the earthquakes endpoint.

### GET /api/datasets/{id}/earthquakes/summary

Aggregates the matching events: totals, magnitude bounds and average, time
span, counts per event type and per UTC day.

Takes the same filters as the listing, through the shared `EarthquakeFilters`
dependency in `main.py`, and uses the same `WHERE` clause. The two endpoints
must never disagree about the same filter; a test asserts they do not.

`magnitude.average` covers only the events that have a magnitude, and
`magnitude.unknown` counts the ones left out. `by_day` is ordered by day
because a chart consumes it in that order.

### POST /api/datasets/{id}/ingest

Records a run in `imports` and answers with that row. In `queue` mode
(the default) the run is pushed onto Redis and the answer is `202` with the
run `queued`; a worker performs the ingestion. In `inline` mode
(`INGESTION_MODE=inline`, for a host with no worker) the runner is called
inside the request and the answer is `200` with the run `completed`. One
response shape for both, so a client need not know the mode.

Writes use `ON CONFLICT (dataset_id, external_id) DO UPDATE`, so re-running
an ingestion refreshes existing events rather than duplicating them. The
upsert is one pipelined `executemany`, not one `execute` per event: the
first inline run against Neon from this machine took 188 s for 2237 rows at
~110 ms a round-trip, and 3.4 s once batched. Keep it batched; a database
is rarely on localhost in production.

Returns `404` for an unknown dataset and `503` when Redis cannot be reached; in
the latter case the run is still recorded as `failed`. A feed that cannot be
retrieved fails inside the worker and leaves the stored data untouched.

## Current database schema

Table: `datasets`

```sql
CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
);
```

Current status values are conceptually:

- `pending` — import requested / not started
- `processing` — import in progress
- `completed` — import completed
- `failed` — import failed

A run also passes through `queued` between being accepted and being picked up
by a worker. Datasets that have never been ingested stay at `pending`.

Table: `earthquakes`

```sql
CREATE TABLE IF NOT EXISTS earthquakes (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    magnitude NUMERIC(5, 2),
    magnitude_type VARCHAR(20),
    place TEXT,
    event_type VARCHAR(50),
    occurred_at TIMESTAMP NOT NULL,
    source_updated_at TIMESTAMP,
    longitude NUMERIC(9, 4) NOT NULL,
    latitude NUMERIC(8, 4) NOT NULL,
    depth_km NUMERIC(8, 3),
    tsunami BOOLEAN NOT NULL DEFAULT FALSE,
    significance INTEGER,
    url TEXT,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (dataset_id, external_id)
);
```

Timestamps are stored as naive UTC. `magnitude` is nullable because a feed
can legitimately omit it. Uniqueness of `external_id` is per dataset, not
global: an id is only unique within its source, and the upsert conflicts on
`(dataset_id, external_id)`.

Table: `imports`

```sql
CREATE TABLE IF NOT EXISTS imports (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    feed_url TEXT NOT NULL,
    queued_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    fetched INTEGER NOT NULL DEFAULT 0,
    valid INTEGER NOT NULL DEFAULT 0,
    invalid INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    invalid_sample TEXT,
    error TEXT
);
```

One row per ingestion run, written before the job is enqueued. `queued_at` is
when the API accepted the run and `started_at` when a worker picked it up. The
dataset `status` mirrors the status of its latest run.

## Current local data

During development, dataset id `1` was created:

- name: `Global Earthquakes`
- source: `USGS`

This is development data only. Do not treat it as a required seed or hard-code it into the application.

## Database access

The connection string is built from environment variables, loaded via
`python-dotenv`. Each variable falls back to the local development default
used by `docker-compose.yml`:

```text
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=metheon
POSTGRES_USER=metheon
POSTGRES_PASSWORD=metheon
```

Copy `.env.example` to `.env` to override them. `.env` is git-ignored;
`.env.example` is committed.

The connection logic currently lives in:

```text
backend/app/db/database.py
```

All SQL lives in:

```text
backend/app/db/repository.py
```

Route handlers call these helpers and must not embed SQL of their own.

## Tests

Pytest lives in `backend/tests/` and runs from `backend/`:

```bash
pytest
```

Test dependencies are kept out of `requirements.txt` and listed in
`requirements-dev.txt`, so a deployment does not pull pytest.

Tests must never require the network. `httpx.get` is replaced where the feed
is fetched, and the Redis client is always faked.

Tests that need PostgreSQL use a dedicated `metheon_test` database, built from
`init.sql` once per session, truncated between tests and dropped at the end:
the development database is never touched. They are marked with
`requires_postgres` and are skipped, not failed, when PostgreSQL is down.

`get_database_url` is read per connection rather than at import time, which is
what lets the suite redirect the application to the test database.

When the `CI` environment variable is set, a missing database is a failure
rather than a skip: a pipeline that silently skipped half the suite would be
worse than a red one.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

- `Tests` — the full suite against a `postgres:16` service container
- `Frontend` — installs from the lockfile with `npm ci`, then lints, tests
  and builds
- `Backend image` — builds `backend/Dockerfile`, imports both entrypoints
  inside it, checks the process is not root, and starts the API from the
  default command until `/api/health/live` answers. The image installs
  `requirements.txt` while the tests run with `requirements-dev.txt`, so the
  import step is what catches a runtime dependency that only exists in the
  development set. Behaviour belongs in pytest; only what is specific to the
  image is checked here.

Keep the workflow honest: a check that cannot fail is not a check.

## Python version

The project runs on **Python 3.12**, pinned in `.python-version` — the one
place CI, the Dockerfile's base image and a developer's tooling all read.
It began on 3.9 and was upgraded on 2026-09-14, after 3.9 left security
support; no code changed, all pinned dependencies already had 3.12 wheels,
and the suite passed unmodified with deprecation warnings treated as errors.

Modern syntax (`str | None`, `match`, `dataclass(slots=True)`) is fine in new
code. The existing `Optional[...]` annotations are correct and stay; a
codebase-wide rewrite would be churn for no behaviour.

When upgrading again: change `.python-version`, the `FROM` line in
`backend/Dockerfile`, and rebuild the virtualenv **in place** — a venv is not
relocatable, its scripts carry the absolute path of the interpreter that
created it.

## Architecture direction

The intended architecture is:

```text
Public dataset / API
        ↓
   Ingestion service
        ↓
 Validation / normalization
        ↓
     PostgreSQL
        ↓
      FastAPI
        ↓
 React + TypeScript dashboard
        ↓
 Optional AI analysis
        ↓
 Gemini
```

For asynchronous processing:

```text
FastAPI
   ↓
Redis
   ↓
Worker
   ↓
PostgreSQL
```

Redis and the worker are planned, not yet implemented.

## Logging

`app/logging_config.py` holds the one format both processes use, and both
call `configure_logging()` at startup — the API from its lifespan, the
worker from `main()`. Timestamps are forced to UTC through
`logging.Formatter.converter`: the API runs on the host in local time and
the worker in a container in UTC, and the same run appeared two hours apart
until that was fixed.

The API logs to `app.api`. A middleware writes one line per request after
the response — method, path, status, duration — so exception handlers'
statuses show up as sent. `/api/health` and `/api/health/live` are logged
at `DEBUG` only; probes would flood `INFO`. Dataset creation and queued
runs are `INFO`; refusals are `WARNING` with the reason.

## Error handling

Two exception handlers in `main.py` cover every route:

- `psycopg.OperationalError` → **503** `{"detail": "The database is
  unavailable"}`. The service is up, a dependency is not; 503 says "try
  again", 500 would say the request is broken.
- `Exception` → **500** with a fixed body. The traceback goes to the
  `app.api` logger and never to the client.

The catch-all passes `exc_info=exc` explicitly. Starlette calls handlers
outside the `except` block that caught the error, so `logger.exception()`
finds no active exception and logs `NoneType: None` — the traceback would
be lost. A test asserts it is present in the log.

`HTTPException` keeps its own code past the catch-all; FastAPI handles it
first.

## Sources

`app/ingestion/sources.py` is the registry: it maps a source key to the module
that implements it. A source module provides `DEFAULT_FEED_URL`,
`fetch_feed(url, timeout)` and `normalize_feed(payload)`, and raises the
shared `app.ingestion.IngestionError` when its feed is unusable.

The registry resolves those functions on the module at call time rather than
capturing them. That keeps each module the one place its behaviour lives, and
it is what lets a test replace `usgs.fetch_feed` and have the runner honour
it — capturing the reference at import broke every runner test the first
time round.

`datasets.source` is the key. Existing rows say `USGS`; the lookup is
case-insensitive so they keep working. The runner reads the dataset's source
for each run and dispatches through the registry; a dataset whose source is
no longer registered fails its run with the reason recorded, and the ingest
endpoint refuses to queue one with `422`.

Nothing else in the pipeline knows which sources exist.

Registered: `usgs`, `ingv` and `emsc`. All publish GeoJSON point features,
so the envelope checks — id, geometry, coordinate ranges, duplicate ids in
one feed — live once in `geojson.py`; each module maps only its own
properties. INGV ids are integers, times ISO 8601 and magnitude types mixed
case, all normalized to match USGS so the sources share one table and one
set of filters.

INGV and EMSC are both FDSN event services: a query, not a feed. What they
share — adding a `starttime` for the last N days unless the url has one,
parsing ISO 8601 into naive UTC — lives in `fdsn.py`; each module keeps its
own window length (`INGV_DAYS`, `EMSC_DAYS`) and its own properties. The
base url is what `imports.feed_url` records.

EMSC has two traps. Its event types are QuakeML codes (`ke` known
earthquake, `se` suspected, `qb` quarry blast…), mapped in `emsc.EVENT_TYPES`
to the words USGS uses and passed through unchanged when unknown. And the
third coordinate of its geometry is an elevation — `-13.0` for 13 km down —
so `depth_km` comes from the `depth` property, not from `parse_point_feature`;
a test asserts every captured depth is non-negative. The reporting network
(`auth`) is dropped: the schema has no column for it, and that is the kind
of source-specific attribute the generic event model is for — proposed,
not built, in `docs/design/generic-events.md`.

The same earthquake appears in several sources with different ids,
magnitudes and epicentres. Datasets keep their own copies; reconciling
agencies is an analysis problem, done on request by the matches endpoint.

## Asynchronous processing

The queue is a Redis list holding nothing but import ids; all state about a run
lives in the `imports` table, so there is a single source of truth.

- `app/jobs.py` — enqueue, dequeue, queue length, ping
- `app/worker.py` — the loop, run with `python -m app.worker`
- `app/ingestion/runner.py` — executes one run

Redis and the worker run in Docker Compose. `backend/Dockerfile` builds
one image for the backend, `metheon-backend`: its default command starts
the API, and the Compose `worker` service overrides it with
`python -m app.worker`. Rebuild after code changes with
`docker compose up -d --build worker` — `--force-recreate` alone recreates
the container with the old image.

The image runs as user `app`, uid 1000. It carries no `HEALTHCHECK`: the
worker shares it and serves no HTTP, and probes are the orchestrator's job.
A multi-stage build was measured and skipped — the base image is most of
the size and no toolchain is installed.

The API is still run from the virtualenv in development; the image is for
CI, Kind and deployment.

A Redis outage does not kill the worker: it logs the failure and retries
after `QUEUE_RETRY_DELAY_SECONDS`. Retrying without that pause spins the loop
at full speed — it produced over 110,000 log lines in five seconds before the
backoff was added.

A worker killed mid-run leaves its import at `processing`. On startup the
worker fails any run at `processing` for longer than `STALE_RUN_MINUTES`
(`repository.fail_stale_imports`), with the reason recorded, and corrects
the dataset's status only when that run is its latest. The threshold is
there for a future with several workers, where a run at `processing` may
belong to another one. The sweep failing is logged, not fatal.

## Kubernetes

`k8s/` holds the manifests and `k8s/dev.sh` the four commands: `up`,
`deploy`, `status`, `down`. Kind runs the cluster in Docker on this machine;
it has no production role in the chosen stack and exists for study and
demonstration.

Postgres is a StatefulSet with a `volumeClaimTemplate`; Redis, the API and
the worker are Deployments. The worker is the backend image with
`command: [python, -m, app.worker]`, no Service, no liveness probe — it
serves no HTTP, and a stuck run is the reaper's job. The API Service is a
NodePort on 30080, mapped to host 8080 by `kind-config.yaml`.
`imagePullPolicy: Never` on both, because `kind load` puts the image on the
node and there is no registry.

The API's liveness probe is `/api/health/live`, its readiness probe
`/api/health`. Stopping Postgres was shown to take the pod out of the
Service without restarting it; that behaviour is why the two endpoints are
separate.

Non-secret configuration is a ConfigMap, the password a Secret. The Secret
is committed with the development password, the same one Compose and
`.env.example` carry; a real deployment creates it out of band.

`kustomize` will not read files outside its directory, so `dev.sh` builds
the `init.sql` ConfigMap from `backend/app/db/init.sql` with `kubectl`
rather than a generator. The schema keeps one source.

## Frontend

React 19 and TypeScript, built with Vite, in `frontend/`. Node 20.19.5 is
pinned in `.nvmrc`; run `nvm use` before `npm` commands.

The dev server proxies `/api` to `http://127.0.0.1:8000`, configured in
`vite.config.ts`. This is deliberate: the browser sees one origin, so the
backend needs no CORS middleware. CORS would be configuration existing only
for a deployment that has not been designed yet.

Node is a local development tool. It does not go in Docker Compose, and the
frontend is not containerized.

Implemented so far: the dataset list, a form that creates a dataset for a
registered source, a browser for one dataset's events with the API's
filters and paging, a map of the same events, a comparison with another
dataset's reports of them, and an ingestion panel that starts a run and
follows it. Every operation the API offers can be done from the browser.

`ComparePanel` gets the whole dataset list from `App` through the browser
and picks its own candidates: never the dataset itself, and by default one
from another agency, since two USGS datasets would agree with each other.
A choice that stops existing falls back to that default rather than
sticking to an id. Each pair is one table row with this dataset's report
above and the other's beneath, muted, so the eye compares down a column;
the deltas are the other agency minus this one, and the legend says so.

The panel polls `/imports` only while a run is in flight, and reports a run
finishing exactly once, through `onRunFinished`; `App` answers by bumping a
`dataVersion` that the browser and the summary carry in their query key, so
everything re-reads. The refresh wiring is covered by an App-level test:
the panel's own tests could not catch its absence.

Two details in `EarthquakeBrowser` are deliberate. Filters apply on submit,
not on every keystroke, so typing does not fire a request per character. And
the loading flag is derived by comparing the query a result answers with the
current one, rather than stored, so it cannot drift from what is on screen —
the caption always counts the rows actually rendered, not the page being
fetched.

Frontend tests use Vitest and Testing Library in jsdom, run from `frontend/`
with `npm test`. `fetch` is always replaced: like the backend suite they must
never reach the network, and unlike it they need no database either.

Fixtures and the fetch stand-in live in `src/test/helpers.ts`.

`src/` is split by responsibility: `api/` for the client and its types,
`components/` for the dashboard's pieces, `theme/` for the colour scheme.
Tests sit beside the code they cover. `App.tsx` stays at the root: it is
the composition, not a component among others.

Charts are hand-written SVG in `BarChart.tsx`, not a charting library: the
API returns the numbers already aggregated, and one bar chart does not pay
for a dependency tree. Only the bars are drawn in the SVG, whose viewBox is
stretched to the container; text inside it gets distorted by that stretch, so
the labels are HTML underneath. Reconsider the choice if several chart types
with axes and tooltips are ever needed.

The map is the one place that rule gave way. `EarthquakeMap.tsx` uses
Leaflet — zoom, pan and tiles are a project of their own — pinned to `~1.9`
so the 2.0 rewrite (ES modules, no `L` global) arrives only when chosen.
Leaflet is used directly, not through `react-leaflet`: one dependency, not
two. It owns the DOM inside its container, so the component creates the map
in an effect with a `ref`, keeps markers in a layer group it clears and
refills, and removes the map on unmount. Colours go through class names,
because Leaflet writes them as SVG attributes and those cannot read CSS
variables; in the dark theme the tiles are inverted with a CSS filter rather
than fetched from a second, dark tile set.

The map reads `/earthquakes/points` with the applied filters, so it shows
exactly what the table and the summary show; when the endpoint's limit cuts
it says "N strongest of M". A dashed rectangle outlines an applied box.
**Filter to this view** applies the visible bounds at once, clamped to
±90/±180 because a zoomed-out view runs past the globe and the API would
refuse it; it keeps whatever else is typed in the form, as Apply would.

Under test Leaflet is replaced by a recording stand-in (`vi.mock`): jsdom
has no layout, and what the component owns is which markers, bounds and
frames it asked for. The browser-level tests run the real library, which
works far enough in jsdom for `getBounds` to answer.

## AI insights

`app/ai/gemini.py` makes the one call: `POST /v1beta/interactions` on the
Gemini Interactions API, with a JSON Schema in `response_format` so the
answer is structured on Google's side, `store: false`, the key in the
`x-goog-api-key` header and never in a URL. No SDK — one endpoint does not
pay for a dependency tree, and httpx was already here. The key is read per
call, so adding it to `.env` needs no restart.

`app/ai/insights.py` decides what the model sees: the summary the API
already computes plus the five strongest events, about 1.6 kB, never the
rows. The system instruction forbids inventing anything not in the digest
and tells the model what each source covers. `RESPONSE_SCHEMA` mirrors
`schemas.Insights`.

`AIError.configured` distinguishes "no key" (503: the feature is off, the
API is up) from "the call failed" (502, with Google's message). The
endpoint takes the same `EarthquakeFilters` as the summary, so the model
describes exactly what the reader is looking at.

No automatic retry. The free tier of the model overloads at times — seen
live as a 500 "currently experiencing high demand" after forty seconds —
and on a metered tier a retry would double the wait and spend quota. The
dashboard's button is the retry. The 45-second timeout is there so an
overloaded upstream cannot hold a request open indefinitely.

The key never goes into `k8s/config.yaml`; `.env` is git-ignored and
`.env.example` carries the variable empty.

## AI principles

AI is an analytical layer, not the core ingestion mechanism.

The platform should first reliably:

1. ingest data,
2. validate it,
3. normalize it,
4. store it,
5. query/aggregate it,
6. visualize it.

Only then should AI be used for features such as:

- summaries,
- trend identification,
- anomaly explanations,
- comparisons,
- recommendations.

Prefer structured AI responses where practical, for example:

```json
{
  "summary": "...",
  "key_trends": [],
  "anomalies": [],
  "recommendations": []
}
```

## Roadmap

### Phase 1 — Foundation
- [x] Git repository
- [x] FastAPI application
- [x] PostgreSQL with Docker Compose
- [x] Database connectivity
- [x] `datasets` table
- [x] Dataset GET/POST API
- [x] Basic dataset status field

### Phase 2 — Data pipeline
- [x] Select first real public dataset source (USGS earthquake feeds)
- [x] Implement ingestion
- [x] Validation
- [x] Normalization
- [x] Import/job model
- [x] Redis
- [x] Background worker
- [x] Proper status transitions

### Phase 3 — Analytics
- [x] Dashboard
- [x] Filters
- [x] Pagination
- [x] Aggregations
- [x] Charts

### Phase 4 — AI
- [x] Gemini integration
- [x] Data summaries
- [x] Trend analysis
- [x] Anomaly analysis
- [x] Structured responses

### Phase 5 — Engineering quality
- [x] Automated tests
- [x] Logging
- [x] Error handling
- [x] Health/readiness checks
- [x] Docker optimization
- [x] GitHub Actions
- [x] Documentation

### Phase 6 — Kubernetes
- [x] Local Kubernetes setup
- [x] Deployments
- [x] Services
- [x] Config / secrets
- [x] Health checks

## Working rule for Claude Code

Before implementing a new feature:

1. Inspect the existing code and current architecture.
2. Preserve working behavior.
3. Make the smallest coherent change.
4. Run an appropriate verification/test.
5. Report what changed and what was verified.
6. Do not silently introduce new infrastructure or dependencies without explaining why.

When a requirement is ambiguous, prefer asking rather than inventing behavior.

