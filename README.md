# Metheon

A cloud-native platform for ingesting, processing, and analyzing public datasets.

```text
Public Data → Ingestion → Processing → PostgreSQL → API → Analytics → AI Insights
```

Metheon is a personal portfolio / open-source project. It works exclusively with
public datasets and does not handle personal or sensitive user data.

> **Project status: Phase 1 complete, Phase 2 in progress.**
> A FastAPI backend, a PostgreSQL database, a reproducible local setup and a
> working synchronous ingestion of USGS earthquake data are in place. Background
> processing (Redis, worker), the frontend and the AI layer are not implemented
> yet — see [Roadmap](#roadmap).

## Tech stack

Currently implemented:

- Python 3.9
- FastAPI + Uvicorn
- psycopg 3
- httpx
- PostgreSQL 16
- Docker / Docker Compose

Planned technologies (React, Redis, background workers, Kubernetes, Gemini) are
listed in the roadmap and are **not** part of the current codebase.

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

## Getting started

### 1. Clone the repository

```bash
git clone git@github.com:matteodr99/metheon.git
cd metheon
```

### 2. Start PostgreSQL

```bash
docker compose up -d
```

On the very first start, the container automatically executes
`backend/app/db/init.sql` and creates the `datasets` table. No manual SQL is
required.

Check that the service is running:

```bash
docker compose ps
```

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

### 5. Verify the setup

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response:

```json
{"status": "ok", "service": "metheon", "database": true}
```

A `"database": true` value confirms that FastAPI successfully connected to
PostgreSQL and executed a query.

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
{"status": "ok", "service": "metheon", "database": true}
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

| Parameter | Default | Range | Meaning |
| --- | --- | --- | --- |
| `limit` | `50` | 1–500 | Events per page |
| `offset` | `0` | ≥ 0 | Events to skip |

Out-of-range values return `422`. Filtering and richer pagination belong to
Phase 3; this endpoint is deliberately minimal.

Requesting an unknown dataset returns `404`.

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
      "id": 2,
      "dataset_id": 1,
      "status": "failed",
      "feed_url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/nope.geojson",
      "started_at": "2026-09-09T10:18:46.495936",
      "finished_at": "2026-09-09T10:18:46.865259",
      "fetched": 0,
      "valid": 0,
      "invalid": 0,
      "inserted": 0,
      "updated": 0,
      "error": "The USGS feed is not valid JSON: Extra data: line 1 column 5 (char 4)"
    }
  ]
}
```

`limit` and `offset` behave as on the earthquakes endpoint. The `feed_url` is
recorded per run, so changing `USGS_FEED_URL` between runs stays visible in the
history.

### `POST /api/datasets/{id}/ingest`

Downloads the USGS feed and stores its earthquakes for the given dataset. The
run is **synchronous**: the request stays open until the feed has been fetched,
validated and written, which usually takes a few seconds.

```bash
curl -X POST http://127.0.0.1:8000/api/datasets/1/ingest
```

```json
{
  "import_id": 3,
  "dataset_id": 1,
  "status": "completed",
  "feed_url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
  "fetched": 254,
  "valid": 254,
  "invalid": 0,
  "inserted": 254,
  "updated": 0,
  "errors": []
}
```

Response fields:

| Field | Meaning |
| --- | --- |
| `fetched` | Features returned by the feed |
| `valid` | Features that passed validation |
| `invalid` | Features rejected, with the reason listed in `errors` |
| `inserted` | Events stored for the first time |
| `updated` | Events already present and refreshed |

`errors` is capped at the first 10 entries, so a broken feed cannot produce an
unbounded response.

The dataset `status` follows the run: `processing` while it is in flight, then
`completed`, or `failed` if the feed cannot be retrieved or parsed. A failure
returns `502` and leaves the stored data untouched.

Each run is also recorded in the `imports` table and can be read back through
`GET /api/datasets/{id}/imports`; the returned `import_id` identifies it.

Requesting an unknown dataset returns `404`.

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
| `pending` | Import requested, not started |
| `processing` | Import in progress |
| `completed` | Import completed |
| `failed` | Import failed |

All four values are set by the ingestion endpoint. Datasets that have never been
ingested stay at `pending`.

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
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    feed_url TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    fetched INTEGER NOT NULL DEFAULT 0,
    valid INTEGER NOT NULL DEFAULT 0,
    invalid INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
```

The row is written before the work starts, so a run that dies halfway still
leaves a trace at `processing`. `finished_at` and the counts are filled in when
the run ends; `error` carries the reason when it failed. Deleting a dataset
cascades to both its earthquakes and its import history.

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
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py      # Connection helper, env-based configuration
│   │   │   ├── repository.py    # All SQL, kept out of route handlers
│   │   │   └── init.sql         # Schema, executed on first container start
│   │   └── ingestion/
│   │       ├── __init__.py
│   │       └── usgs.py          # Feed fetching, validation, normalization
│   ├── tests/
│   │   ├── conftest.py          # Shared fixtures and feature builder
│   │   ├── fixtures/            # A real feed response, captured once
│   │   ├── test_usgs_fetch.py
│   │   └── test_usgs_normalization.py
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── .env.example
├── .gitignore
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

The suite covers the ingestion logic — feed retrieval error handling,
validation and normalization — and needs neither the network nor a running
database: `httpx.get` is replaced in the fetch tests, and the rest exercise pure
functions. It runs in well under a second.

Alongside the handwritten cases, a real feed response captured on 2026-09-09 is
kept in `tests/fixtures/` and normalized in full, so the tests stay honest about
the shape the feed actually has.

The API endpoints are not covered yet: those need a database, and wiring that up
is a separate step.

### Inspecting the database directly

```bash
docker exec -it metheon-postgres psql -U metheon -d metheon
```

## Roadmap

- [x] **Phase 1 — Foundation:** FastAPI application, PostgreSQL via Docker
  Compose, `datasets` table, dataset GET/POST API, reproducible local setup
- [ ] **Phase 2 — Data pipeline:** USGS source selected, synchronous ingestion,
  validation, normalization, status transitions and the import/job model are
  done; Redis and the background worker are still open
- [ ] **Phase 3 — Analytics:** React + TypeScript dashboard, filters, pagination,
  aggregations, charts
- [ ] **Phase 4 — AI:** Gemini integration for summaries, trend and anomaly
  analysis, with structured responses
- [ ] **Phase 5 — Engineering quality:** the ingestion logic is covered by
  tests; logging, error handling, readiness checks, API tests and GitHub
  Actions are still open
- [ ] **Phase 6 — Kubernetes:** local cluster, deployments, services, config and
  secrets

See [CLAUDE.md](CLAUDE.md) for the detailed architecture and design principles.
