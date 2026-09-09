# Metheon

[![CI](https://github.com/matteodr99/metheon/actions/workflows/ci.yml/badge.svg)](https://github.com/matteodr99/metheon/actions/workflows/ci.yml)

A cloud-native platform for ingesting, processing, and analyzing public datasets.

```text
Public Data → Ingestion → Processing → PostgreSQL → API → Analytics → AI Insights
```

Metheon is a personal portfolio / open-source project. It works exclusively with
public datasets and does not handle personal or sensitive user data.

> **Project status: Phases 1 and 2 complete, Phase 3 in progress.**
> A FastAPI backend, a PostgreSQL database, a Redis queue and a background
> worker ingest USGS earthquake data asynchronously, with every run recorded.
> The API supports filtering and aggregation, and a React frontend browses
> the events with filters and pagination. Charts and the AI layer are not
> implemented yet — see [Roadmap](#roadmap).

## Tech stack

Currently implemented:

- Python 3.9
- FastAPI + Uvicorn
- psycopg 3
- httpx
- PostgreSQL 16
- Redis 7
- Docker / Docker Compose
- React 19 + TypeScript, built with Vite

Planned technologies (React, Redis, background workers, Kubernetes, Gemini) are
listed in the roadmap and are **not** part of the current codebase.

## How it works

```text
POST /api/datasets/{id}/ingest
        ↓  writes a queued row in `imports`, pushes its id to Redis
     Redis list
        ↓  BLPOP
      worker
        ↓  fetch → validate → normalize → upsert
    PostgreSQL
```

The queue carries nothing but import ids: everything else about a run lives in
the `imports` table, so there is a single source of truth about what happened.
The endpoint returns as soon as the run is queued, and progress is followed
through `GET /api/datasets/{id}/imports`.

## Data source

Metheon ingests the public [USGS earthquake feeds][usgs], which require no
authentication and contain no personal data:

```text
https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
```

Each event carries a stable USGS id, so ingestion is idempotent: re-running it
refreshes existing events in place instead of duplicating them. Feeds also
include non-earthquake events such as quarry blasts and explosions; these are
stored as well and can be told apart through the `event_type` column.

[usgs]: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php

## Prerequisites

- Python 3.9
- Docker and Docker Compose
- Git
- Node 20.19.5, for the frontend only — pinned in `.nvmrc`, so with nvm
  installed `nvm use` picks it up

## Getting started

### 1. Clone the repository

```bash
git clone git@github.com:matteodr99/metheon.git
cd metheon
```

### 2. Start the services

```bash
docker compose up -d --build
```

This starts three containers:

| Service | Container | Role |
| --- | --- | --- |
| `postgres` | `metheon-postgres` | Database, port 5432 |
| `redis` | `metheon-redis` | Job queue, port 6379 |
| `worker` | `metheon-worker` | Runs queued ingestions |

On the very first start, PostgreSQL automatically executes
`backend/app/db/init.sql` and creates the schema. No manual SQL is required.

Check the services and follow the worker:

```bash
docker compose ps
docker compose logs -f worker
```

The API itself is not containerized yet and runs locally, as described below.

### 3. Create the virtual environment and install dependencies

```bash
python3.9 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

To also install the test dependencies:

```bash
pip install -r backend/requirements-dev.txt
```

### 4. Run the API

The application must be started from the `backend/` directory:

```bash
cd backend
uvicorn app.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`, and the interactive
Swagger UI at `http://127.0.0.1:8000/docs`.

### 5. Run the frontend

In a third terminal, from `frontend/`:

```bash
nvm use
npm install
npm run dev
```

The dashboard is then at `http://localhost:5173`. Its dev server proxies
`/api` to the backend on port 8000, so the browser sees a single origin and
the API needs no CORS configuration. That proxy is a development arrangement
only; how a built frontend would reach the API is a separate decision, not
made yet.

The frontend is optional — the API works on its own.

### 6. Verify the setup

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response:

```json
{"status": "ok", "service": "metheon", "database": true, "queue": true}
```

`database` confirms that FastAPI connected to PostgreSQL and ran a query;
`queue` that Redis answers. If either is down, `status` reads `degraded`.

## Configuration

Database credentials are read from environment variables. Every variable has a
fallback matching the local development defaults in `docker-compose.yml`, so the
project runs out of the box without any configuration.

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_DB` | `metheon` | Database name |
| `POSTGRES_USER` | `metheon` | Database user |
| `POSTGRES_PASSWORD` | `metheon` | Database password |
| `USGS_FEED_URL` | `…/all_day.geojson` | GeoJSON feed used by the ingestion |
| `USGS_TIMEOUT_SECONDS` | `30` | HTTP timeout for the feed request |
| `REDIS_HOST` | `localhost` | Redis host (`redis` inside Compose) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database number |
| `QUEUE_NAME` | `metheon:imports` | Redis list used as the queue |
| `QUEUE_BLOCK_TIMEOUT_SECONDS` | `5` | How long the worker blocks on the queue |
| `QUEUE_RETRY_DELAY_SECONDS` | `5` | Pause before retrying after a Redis outage |
| `LOG_LEVEL` | `INFO` | Worker log level |
| `TEST_POSTGRES_DB` | `metheon_test` | Database created by the test suite |

To override them, copy the example file and edit it:

```bash
cp .env.example .env
```

`.env` is git-ignored and is loaded automatically via `python-dotenv`. Since the
variable names match the ones used by `docker-compose.yml`, a single `.env` file
configures both the container and the application.

The default credentials are local development values only. They are not secrets
and must not be used in a deployed environment.

## API

### `GET /api/health`

Checks that the API can connect to PostgreSQL and run a query.

```bash
curl http://127.0.0.1:8000/api/health
```

```json
{"status": "ok", "service": "metheon", "database": true, "queue": true}
```

### `GET /api/datasets`

Returns all datasets stored in PostgreSQL, ordered by id.

```bash
curl http://127.0.0.1:8000/api/datasets
```

```json
[
  {
    "id": 1,
    "name": "Global Earthquakes",
    "source": "USGS",
    "description": "Public earthquake data provided by the US Geological Survey.",
    "created_at": "2026-09-09T08:08:12.648723",
    "status": "pending"
  }
]
```

### `POST /api/datasets`

Creates a dataset and returns the created record.

```bash
curl -X POST http://127.0.0.1:8000/api/datasets \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Global Earthquakes",
    "source": "USGS",
    "description": "Public earthquake data provided by the US Geological Survey."
  }'
```

Request fields:

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `source` | string | yes |
| `description` | string | no |

`id`, `created_at` and `status` are assigned by the database and must not be
supplied by the client.

### `GET /api/datasets/{id}/earthquakes`

Returns a page of the earthquakes stored for a dataset, most recent first.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/earthquakes?limit=2"
```

```json
{
  "dataset_id": 1,
  "total": 254,
  "limit": 2,
  "offset": 0,
  "filters": {},
  "items": [
    {
      "id": 254,
      "external_id": "hv75031332",
      "magnitude": 1.98,
      "magnitude_type": "md",
      "place": "30 km SE of Pāhala, Hawaii",
      "event_type": "earthquake",
      "occurred_at": "2026-09-09T08:43:38",
      "longitude": -155.2855,
      "latitude": 18.9995,
      "depth_km": 49.0,
      "tsunami": false,
      "significance": 60,
      "url": "https://earthquake.usgs.gov/earthquakes/eventpage/hv75031332"
    }
  ]
}
```

Query parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `limit` | `50` | Events per page, 1–500 |
| `offset` | `0` | Events to skip, ≥ 0 |
| `min_magnitude` | — | Lowest magnitude, inclusive |
| `max_magnitude` | — | Highest magnitude, inclusive |
| `start_time` | — | Earliest event time, inclusive, ISO 8601 |
| `end_time` | — | Latest event time, inclusive, ISO 8601 |
| `event_type` | — | Exact match, e.g. `earthquake`, `quarry blast` |

Filters are optional and combine with `AND`:

```bash
curl "http://127.0.0.1:8000/api/datasets/1/earthquakes?event_type=earthquake&min_magnitude=4"
```

`total` counts the events matching the filters rather than the whole dataset,
so a client can page through a filtered result. The filters actually applied
are echoed back in the response under `filters`.

Two details worth knowing:

- An event whose `magnitude` is null is excluded by any magnitude bound. SQL
  drops it on its own — `NULL >= 2` is null, not true — and that is the
  intended behaviour: an unknown magnitude cannot be said to clear a threshold.
- A range whose bounds are the wrong way round returns `422` rather than an
  empty page, which would read as "no data" instead of as a mistake.

Out-of-range or unparsable values return `422`. Requesting an unknown dataset
returns `404`. Aggregations and charts remain part of Phase 3.

### `GET /api/datasets/{id}/imports`

Returns the import history of a dataset, most recent run first. Every call to
the ingest endpoint leaves exactly one row here, whether it succeeded or not.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/imports?limit=1"
```

```json
{
  "dataset_id": 1,
  "total": 3,
  "limit": 1,
  "offset": 0,
  "items": [
    {
      "id": 6,
      "dataset_id": 1,
      "status": "failed",
      "feed_url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/nope.geojson",
      "queued_at": "2026-09-09T10:29:41.183020",
      "started_at": "2026-09-09T10:29:41.245512",
      "finished_at": "2026-09-09T10:18:46.865259",
      "fetched": 0,
      "valid": 0,
      "invalid": 0,
      "inserted": 0,
      "updated": 0,
      "invalid_sample": null,
      "error": "The USGS feed is not valid JSON: Extra data: line 1 column 5 (char 4)"
    }
  ]
}
```

`limit` and `offset` behave as on the earthquakes endpoint. The `feed_url` is
recorded per run, so changing `USGS_FEED_URL` between runs stays visible in the
history.

### `GET /api/datasets/{id}/earthquakes/summary`

Aggregates the matching events without returning them. Takes the **same
filters** as the listing, so a filtered view can describe exactly what it
shows.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/earthquakes/summary?min_magnitude=4"
```

```json
{
  "dataset_id": 1,
  "filters": {"min_magnitude": 4.0},
  "total": 17,
  "magnitude": {"min": 4.0, "max": 5.3, "average": 4.66, "unknown": 0},
  "occurred_at": {
    "first": "2026-09-08T09:12:44.310000",
    "last": "2026-09-09T10:31:02.980000"
  },
  "by_event_type": [{"event_type": "earthquake", "count": 17}],
  "by_day": [
    {"day": "2026-09-08", "count": 13},
    {"day": "2026-09-09", "count": 4}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `total` | Events matching the filters |
| `magnitude.unknown` | Matching events whose magnitude is null |
| `by_event_type` | Counts per type, largest first |
| `by_day` | Counts per UTC calendar day, chronological |

`magnitude.average` is the average over the events that have one, so
`unknown` says how many were left out rather than hiding them in the total.
`by_day` is ordered by day because that is how a chart consumes it.

On an empty result the totals are `null` and the groupings are empty lists.
`total` here always agrees with the `total` the listing reports for the same
filters — both are built from one shared `WHERE` clause.

### `POST /api/datasets/{id}/ingest`

Queues an ingestion run and returns `202` immediately. A worker picks the job
up and does the work.

```bash
curl -X POST http://127.0.0.1:8000/api/datasets/1/ingest
```

```json
{
  "import_id": 5,
  "dataset_id": 1,
  "status": "queued",
  "feed_url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
}
```

Follow the run through `GET /api/datasets/{id}/imports`, or watch the worker
with `docker compose logs -f worker`. The dataset `status` mirrors the latest
run: `queued`, then `processing`, then `completed` or `failed`.

Requesting an unknown dataset returns `404`. If Redis cannot be reached the
call returns `503`, and the run is still recorded as `failed` so the outage is
visible in the history rather than silently swallowed.

## Database schema

Table `datasets`, created by `backend/app/db/init.sql`:

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

The `status` column currently holds one of four conceptual values:

| Value | Meaning |
| --- | --- |
| `pending` | Never ingested |
| `queued` | Run accepted, waiting for a worker |
| `processing` | A worker is running it |
| `completed` | Import completed |
| `failed` | Import failed |

`queued` was added when ingestion became asynchronous: a run waiting in the
queue is not being processed yet, and saying otherwise would be untrue.
Datasets that have never been ingested stay at `pending`.

Table `earthquakes`, one row per event, keyed by the USGS id:

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

Table `imports`, one row per ingestion run:

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

The row is written before the job is enqueued, so a run always exists in the
history even if the queue rejects it. `queued_at` is when the API accepted the
run, `started_at` when a worker picked it up: the gap between the two is the
queue wait. `invalid_sample` keeps the first ten validation errors, so a run
that completes with a non-zero `invalid` count still says why. Deleting a
dataset cascades to both its earthquakes and its import history.

The `UNIQUE` constraint on `external_id` is what makes ingestion idempotent:
writes use `ON CONFLICT DO UPDATE`. Timestamps are stored as naive UTC, converted
from the epoch milliseconds the feed provides. `magnitude` is nullable — the feed
legitimately omits it for some events.

## Project structure

```text
metheon/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application and routes
│   │   ├── jobs.py              # Redis queue: enqueue, dequeue, health
│   │   ├── worker.py            # Background worker loop
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py      # Connection helper, env-based configuration
│   │   │   ├── repository.py    # All SQL, kept out of route handlers
│   │   │   └── init.sql         # Schema, executed on first container start
│   │   └── ingestion/
│   │       ├── __init__.py
│   │       ├── usgs.py          # Feed fetching, validation, normalization
│   │       └── runner.py        # Executes one queued import
│   ├── tests/
│   │   ├── conftest.py          # Shared fixtures and feature builder
│   │   ├── fixtures/            # A real feed response, captured once
│   │   ├── test_api.py
│   │   ├── test_filters.py
│   │   ├── test_jobs.py
│   │   ├── test_repository.py
│   │   ├── test_summary.py
│   │   ├── test_runner.py
│   │   ├── test_usgs_fetch.py
│   │   ├── test_usgs_normalization.py
│   │   └── test_worker.py
│   ├── Dockerfile               # Worker image
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── api.ts               # Types and fetch helpers for the API
│   │   ├── App.tsx              # Dataset list and selection
│   │   ├── EarthquakeBrowser.tsx # Filters, table and pagination
│   │   ├── index.css
│   │   └── main.tsx
│   │   └── test/                # Fixtures and the fetch stand-in
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts           # Dev-only proxy to the API
├── .github/
│   └── workflows/
│       └── ci.yml               # Tests and worker image build
├── .env.example
├── .gitignore
├── .nvmrc
├── CLAUDE.md                    # Detailed architecture and working notes
├── README.md
└── docker-compose.yml
```

## Development notes

### Python version

The project targets **Python 3.9**. Python 3.10+ syntax must not be used unless
the version is intentionally upgraded — for example, use `Optional[str]` rather
than `str | None`.

### Resetting the database

`init.sql` runs only when the PostgreSQL data directory is empty. To apply schema
changes from a clean state:

```bash
docker compose down -v && docker compose up -d
```

> **Warning:** `down -v` deletes the `postgres_data` volume and every row stored
> in it. Back up anything you want to keep first.

### Running the tests

From the `backend/` directory:

```bash
pytest
```

The suite has two halves.

The **pure tests** cover validation, normalization, feed-error handling and the
Redis queue. They need nothing running: `httpx.get` and the Redis client are
replaced by stand-ins.

The **database-backed tests** cover the HTTP API, the repository and the import
runner. They create a `metheon_test` database from `init.sql`, empty it between
tests and drop it at the end, so the development database is never touched. The
queue is still faked, so Redis is not required.

If PostgreSQL is not reachable, those tests are **skipped rather than failed**,
and the pure half still runs:

```bash
pytest -rs
```

In CI that leniency is switched off: when the `CI` environment variable is set
a missing database makes the tests fail, because a green pipeline that quietly
skipped half the suite would be worse than a red one.

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request against `main`:

| Job | What it does |
| --- | --- |
| `Tests` | Runs the full suite against a `postgres:16` service container |
| `Frontend` | Installs from the lockfile, then lints, tests and builds the frontend |
| `Worker image` | Builds `backend/Dockerfile` and imports the worker inside it, checking that `requirements.txt` alone is enough to run it |

Alongside the handwritten cases, a real feed response captured on 2026-09-09 is
kept in `tests/fixtures/` and normalized in full, so the tests stay honest about
the shape the feed actually has.

The worker loop is covered too: an empty queue, a job that raises, a shutdown
request and a Redis outage each have a test, with the queue and the job both
replaced.

The frontend has its own suite, run from `frontend/` with `npm test`. It uses
Vitest and Testing Library in jsdom, with `fetch` replaced, so it needs
nothing running either.

### Rebuilding the worker

The worker runs from an image, so code changes need a rebuild:

```bash
docker compose up -d --build worker
```

It stops cleanly on `docker compose stop`: the current job finishes before the
process exits.

### Inspecting the database directly

```bash
docker exec -it metheon-postgres psql -U metheon -d metheon
```

## Roadmap

- [x] **Phase 1 — Foundation:** FastAPI application, PostgreSQL via Docker
  Compose, `datasets` table, dataset GET/POST API, reproducible local setup
- [x] **Phase 2 — Data pipeline:** USGS source, asynchronous ingestion through
  a Redis queue and a background worker, with validation, normalization, status
  transitions and a recorded history of every run
- [ ] **Phase 3 — Analytics:** the API supports pagination, filtering and
  aggregation, and the frontend browses the events with filters and paging;
  the charts are still open
- [ ] **Phase 4 — AI:** Gemini integration for summaries, trend and anomaly
  analysis, with structured responses
- [ ] **Phase 5 — Engineering quality:** backend and frontend are both
  covered by tests, CI runs everything on every push, and the worker logs its
  work; structured logging and Docker optimization are still open
- [ ] **Phase 6 — Kubernetes:** local cluster, deployments, services, config and
  secrets

See [CLAUDE.md](CLAUDE.md) for the detailed architecture and design principles.
