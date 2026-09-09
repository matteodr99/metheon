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
- PostgreSQL 16
- Docker / Docker Compose
- Git

### Planned / intended

- React + TypeScript
- Redis for asynchronous jobs
- Background worker for ingestion
- Docker Compose for local multi-service development
- Kubernetes locally via Kind or Minikube
- GitHub Actions
- Gemini API for optional AI insights
- Pytest / frontend tests
- Public frontend deployment, potentially Cloudflare Pages
- Public backend deployment, potentially Render
- Supabase PostgreSQL may be used for a public demo

Do not treat planned technologies as already implemented.

## Repository structure

Current structure:

```text
metheon/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py
│   │   │   ├── repository.py
│   │   │   └── init.sql
│   │   └── ingestion/
│   │       ├── __init__.py
│   │       └── usgs.py
│   └── requirements.txt
├── .env.example
├── .gitignore
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

Query parameters: `limit` (default 50, between 1 and 500) and `offset`
(default 0). Out-of-range values return `422`, an unknown dataset `404`.

Filtering and richer pagination belong to Phase 3.

### POST /api/datasets/{id}/ingest

Downloads the USGS GeoJSON feed, validates and normalizes it, and stores the
events in the `earthquakes` table. The run is synchronous and drives the dataset
status: `processing`, then `completed` or `failed`.

Writes use `ON CONFLICT (external_id) DO UPDATE`, so re-running an ingestion
refreshes existing events rather than duplicating them.

Returns `404` for an unknown dataset and `502` when the feed cannot be retrieved
or parsed; a failure leaves the stored data untouched.

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

The ingestion endpoint drives these transitions. Datasets that have never been
ingested stay at `pending`.

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
- [ ] Import/job model
- [ ] Redis
- [ ] Background worker
- [x] Proper status transitions

### Phase 3 — Analytics
- [ ] Dashboard
- [ ] Filters
- [ ] Pagination
- [ ] Aggregations
- [ ] Charts

### Phase 4 — AI
- [ ] Gemini integration
- [ ] Data summaries
- [ ] Trend analysis
- [ ] Anomaly analysis
- [ ] Structured responses

### Phase 5 — Engineering quality
- [ ] Automated tests
- [ ] Logging
- [ ] Error handling
- [ ] Health/readiness checks
- [ ] Docker optimization
- [ ] GitHub Actions
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

