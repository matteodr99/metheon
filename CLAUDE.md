# CLAUDE.md — Metheon

## Project

**Metheon** is a cloud-native platform for ingesting, processing, and analyzing public datasets.

Core idea:

Public Data → Ingestion → Processing → PostgreSQL → API → Analytics → AI Insights

The project is a personal portfolio/open-source project. It must not use personal or sensitive user data.

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

- Python 3.9
- FastAPI
- Uvicorn
- psycopg 3
- httpx
- redis-py
- PostgreSQL 16
- Redis 7
- Docker / Docker Compose
- React 19 + TypeScript, built with Vite
- Pytest, Vitest and Testing Library
- GitHub Actions
- Git

### Planned / intended

- Kubernetes locally via Kind or Minikube
- Gemini API for optional AI insights
- Public frontend deployment, potentially Cloudflare Pages
- Public backend deployment, potentially Render
- Supabase PostgreSQL may be used for a public demo

Deployment and hosting are decided separately and are not to be implemented
without being asked.

Do not treat planned technologies as already implemented.

## Repository structure

Current structure:

```text
metheon/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── jobs.py
│   │   ├── worker.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py
│   │   │   ├── repository.py
│   │   │   └── init.sql
│   │   └── ingestion/
│   │       ├── __init__.py
│   │       ├── usgs.py
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
│   │   ├── api.ts
│   │   ├── App.tsx
│   │   ├── EarthquakeBrowser.tsx
│   │   ├── Summary.tsx
│   │   ├── BarChart.tsx
│   │   ├── index.css
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── .env.example
├── .gitignore
├── .nvmrc
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

The backend uses a Python 3.9 virtual environment:

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

## Current API

### GET /api/health

Checks that FastAPI can connect to PostgreSQL and execute a simple query.

Expected response:

```json
{
  "status": "ok",
  "service": "metheon",
  "database": true
}
```

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

### GET /api/datasets/{id}/earthquakes

Returns a page of the earthquakes stored for a dataset, ordered by event time,
most recent first.

Query parameters: `limit` (default 50, between 1 and 500), `offset`
(default 0), and the optional filters `min_magnitude`, `max_magnitude`,
`start_time`, `end_time` and `event_type`. Bounds are inclusive and filters
combine with `AND`.

`total` counts the matching events, not the whole dataset: the count and the
listing share one `WHERE` clause, built in `repository._earthquake_where`. A
total that ignored the filters would make the reported page count wrong.

That clause is assembled only from constant strings, and every value travels
as a query parameter. Keep it that way if you add a filter.

An inverted range returns `422` instead of an empty page. Out-of-range values
return `422`, an unknown dataset `404`.

Aggregations and charts remain part of Phase 3.

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

Records a queued run in `imports`, pushes its id onto the Redis queue and
returns `202`. A worker performs the ingestion.

Writes use `ON CONFLICT (external_id) DO UPDATE`, so re-running an ingestion
refreshes existing events rather than duplicating them.

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
    external_id VARCHAR(64) NOT NULL UNIQUE,
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
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Timestamps are stored as naive UTC, converted from the epoch milliseconds the
feed provides. `magnitude` is nullable because the feed legitimately omits it.

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
- `Worker image` — builds `backend/Dockerfile` and imports the worker inside
  it. The image installs `requirements.txt` while the tests run with
  `requirements-dev.txt`, so this is what catches a runtime dependency that
  only exists in the development set. Worker behaviour belongs in pytest.

Keep the workflow honest: a check that cannot fail is not a check.

## Important Python compatibility rule

The current project uses **Python 3.9**.

Do not use Python 3.10+ syntax unless the Python version is intentionally upgraded.

For example, avoid:

```python
str | None
```

Use:

```python
Optional[str]
```

when compatibility with Python 3.9 is required.

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

## Asynchronous processing

The queue is a Redis list holding nothing but import ids; all state about a run
lives in the `imports` table, so there is a single source of truth.

- `app/jobs.py` — enqueue, dequeue, queue length, ping
- `app/worker.py` — the loop, run with `python -m app.worker`
- `app/ingestion/runner.py` — executes one run

Redis and the worker run in Docker Compose. The worker image is built from
`backend/Dockerfile`; rebuild it after code changes with
`docker compose up -d --build worker`. The API is not containerized yet.

A Redis outage does not kill the worker: it logs the failure and retries
after `QUEUE_RETRY_DELAY_SECONDS`. Retrying without that pause spins the loop
at full speed — it produced over 110,000 log lines in five seconds before the
backoff was added.

Known limitation: a worker killed mid-run leaves its import row at
`processing`. There is no reaper for stale runs.

## Frontend

React 19 and TypeScript, built with Vite, in `frontend/`. Node 20.19.5 is
pinned in `.nvmrc`; run `nvm use` before `npm` commands.

The dev server proxies `/api` to `http://127.0.0.1:8000`, configured in
`vite.config.ts`. This is deliberate: the browser sees one origin, so the
backend needs no CORS middleware. CORS would be configuration existing only
for a deployment that has not been designed yet.

Node is a local development tool. It does not go in Docker Compose, and the
frontend is not containerized.

Implemented so far: the dataset list, and a browser for one dataset's events
with the five API filters and paging.

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

Charts are hand-written SVG in `BarChart.tsx`, not a charting library: the
API returns the numbers already aggregated, and one bar chart does not pay
for a dependency tree. Only the bars are drawn in the SVG, whose viewBox is
stretched to the container; text inside it gets distorted by that stretch, so
the labels are HTML underneath. Reconsider the choice if several chart types
with axes and tooltips are ever needed.

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
- [ ] Gemini integration
- [ ] Data summaries
- [ ] Trend analysis
- [ ] Anomaly analysis
- [ ] Structured responses

### Phase 5 — Engineering quality
- [x] Automated tests
- [~] Logging (the worker logs; the API does not yet)
- [ ] Error handling
- [ ] Health/readiness checks
- [ ] Docker optimization
- [x] GitHub Actions
- [ ] Documentation

### Phase 6 — Kubernetes
- [ ] Local Kubernetes setup
- [ ] Deployments
- [ ] Services
- [ ] Config / secrets
- [ ] Health checks

## Working rule for Claude Code

Before implementing a new feature:

1. Inspect the existing code and current architecture.
2. Preserve working behavior.
3. Make the smallest coherent change.
4. Run an appropriate verification/test.
5. Report what changed and what was verified.
6. Do not silently introduce new infrastructure or dependencies without explaining why.

When a requirement is ambiguous, prefer asking rather than inventing behavior.

