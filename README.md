# Metheon

[![CI](https://github.com/matteodr99/metheon/actions/workflows/ci.yml/badge.svg)](https://github.com/matteodr99/metheon/actions/workflows/ci.yml)
[![Ingest](https://github.com/matteodr99/metheon/actions/workflows/ingest.yml/badge.svg)](https://github.com/matteodr99/metheon/actions/workflows/ingest.yml)

A cloud-native platform for ingesting, processing, and analyzing public seismic
data — the earthquake catalogues of USGS, INGV and EMSC, which observe the
same earthquakes with different networks and report them differently, NASA
EONET's curated wildfires, storms, floods and other natural events, and the
graded disaster alerts of GDACS.

```text
Public Data → Ingestion → Processing → PostgreSQL → API → Analytics → AI Insights
```

Metheon is a personal portfolio / open-source project. It works exclusively with
public datasets and does not handle personal or sensitive user data. A
dataset holds events of one kind — earthquakes, wildfires, storms — and the
same pipeline, filters, map and comparison serve every kind; the design
behind that is in [docs/design/generic-events.md](docs/design/generic-events.md).
Measurements over time — river levels, air quality — are the next shape
of data, designed and not yet built in
[docs/design/time-series.md](docs/design/time-series.md).

It was built in pair with Claude Code, step by step: I decided what to
build and why, the assistant wrote and tested it, and every step was
verified before the next — the commits carry both names. The reasoning
behind each decision, including the ones reversed, is in the commit
messages, in `CLAUDE.md` and in `docs/design/`.

> **Project status: all six phases of the roadmap are complete.**
> A FastAPI backend, a PostgreSQL database, a Redis queue and a background
> worker ingest earthquakes from USGS, INGV and EMSC, natural events from
> NASA EONET and graded alerts from GDACS asynchronously, with every
> run recorded. The API supports filtering and aggregation; a React dashboard
> browses the events with filters, paging and charts, creates datasets, starts
> ingestions and follows them, and — with a Gemini key — asks the model what
> the filtered data shows. Nothing needs a terminal. The whole system also
> runs on a local Kind cluster, and it is live at
> [metheon.pages.dev](https://metheon.pages.dev) — the front page — with the
> dashboard at [metheon.pages.dev/app/](https://metheon.pages.dev/app/). See
> [Roadmap](#roadmap).

## Tech stack

Currently implemented:

- Python 3.12
- FastAPI + Uvicorn
- psycopg 3
- httpx
- PostgreSQL 16
- Redis 7
- Gemini API, over plain HTTP, optional
- Docker / Docker Compose; Kubernetes locally, via Kind
- React 19 + TypeScript, built with Vite
- Leaflet, with OpenStreetMap tiles, for the map
- GitHub Actions

Everything in the roadmap is implemented; see [Where it runs](#where-it-runs)
for the deployment.

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

## Data sources

Two sources are registered, both public, unauthenticated and free of personal
data. A dataset names one of them, and `GET /api/sources` lists what is
available.

**USGS** — the [USGS earthquake feeds][usgs], worldwide. The default is the
past week:

```text
https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson
```

The other windows share the same structure and can be set through
`USGS_FEED_URL`: `all_day` is a few hundred events, `all_month` over ten
thousand.

Each event carries a stable USGS id, so ingestion is idempotent: re-running it
refreshes existing events in place instead of duplicating them. Feeds also
include non-earthquake events such as quarry blasts and explosions; these are
stored as well and can be told apart through the `event_type` column.

**INGV** — the [FDSN event service][ingv] of Italy's national institute of
geophysics and volcanology. It answers a query rather than serving a feed, so
the ingestion asks for a window ending now, `INGV_DAYS` long (seven by
default). INGV writes ids as integers, times as ISO 8601 and magnitude types
in mixed case; all three are normalized to match USGS, so both sources share
one table and one set of filters.

**EMSC** — the [FDSN event service][emsc] of the Euro-Mediterranean
Seismological Centre, which aggregates the bulletins of dozens of national
networks (AFAD, BMKG, NEIC, OGS, …) into one catalogue. Same kind of query
as INGV, `EMSC_DAYS` long. Its event types are QuakeML codes (`ke`, `se`,
`qb`…), spelled out into the words USGS uses; its third coordinate is an
elevation, negative underground, so the depth is taken from the `depth`
property instead. Which network reported an event is not kept: the shared
schema has no column for it.

The same physical earthquake appears in several catalogues with different
ids, slightly different magnitudes and epicentres kilometres apart — in one
week's data, 219 USGS events had an EMSC counterpart within a minute and
100 km, on average 4 km and 0.12 magnitude apart. Each dataset keeps its own
copy: reconciling agencies is an analysis question, not something ingestion
should guess at, and the [matches endpoint](#get-apidatasetsideventsmatchesotherid2)
does it on request.

**NASA EONET** — the [Earth Observatory Natural Event Tracker][eonet], which
curates natural events of thirteen kinds from satellite imagery and partner
reports: wildfires, severe storms, volcanoes, floods, sea and lake ice,
landslides and more. One feed serves them all, so EONET is the first source
that offers several kinds: a dataset created for it names one, and each run
asks for that category over the last `EONET_DAYS`. An EONET event is a list
of dated geometries — one point for a fire, a track for a storm, polygons
for a flood — with an optional measurement on each; the record takes the
earliest date, the latest position, the peak measurement (a fire's final
area, a storm's strongest wind) and keeps the whole list as its geometry
when it is more than a point. Fires reported in acres are converted to
hectares so a dataset has one unit. EONET's polygons come with latitude
first, unlike its points; the marker is placed accordingly.

**GDACS** — the [Global Disaster Alert and Coordination System][gdacs] of
the UN and the European Commission, which grades earthquakes, tropical
cyclones, floods, volcanoes, wildfires and droughts by their expected
humanitarian impact: a Green, Orange or Red alert. It reports the same
storms and fires EONET does — EONET cites it as a source — so the two can
be compared outside seismology; and the alert level is the attribute no
other source has. The feed is the seven-day RSS rather than the JSON search
API, which answers at most a hundred events per query and cannot page; the
RSS carries every alert of every type and one request serves any kind.
Parsed with the standard library. Winds in km/h become knots and areas in
`ha` become hectares, so a storm or a fire dataset has the same unit whether
EONET or GDACS filled it; an earthquake's depth is read from the severity
text so it lines up with the seismic sources in a comparison.

`backend/app/ingestion/sources.py` maps a source name to the module that
fetches and normalizes it. Adding a source means writing such a module and
registering it there; the GeoJSON envelope checks are shared in
`geojson.py`.

[ingv]: https://webservices.ingv.it/
[emsc]: https://www.seismicportal.eu/fdsn-wsevent.html
[eonet]: https://eonet.gsfc.nasa.gov/docs/v3
[gdacs]: https://www.gdacs.org/

[usgs]: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php

## Prerequisites

- Python 3.12 — pinned in `.python-version`, which `pyenv`, `uv` and the CI
  all read
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
| `worker` | `metheon-worker` | Runs queued ingestions, from the backend image |

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
python3.12 -m venv .venv
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
Swagger UI at `http://127.0.0.1:8000/docs`. Every route there has a named
response model, its error responses declared, and a tag grouping it with its
kin — the reference below is the prose version of the same contract.

### 5. Run the frontend

In a third terminal, from `frontend/`:

```bash
nvm use
npm install
npm run dev
```

The site is then at `http://localhost:5173`: the landing page at the root
and the dashboard at `/app/` — two pages, no router, chosen from the path in
`src/routes.ts`. The dashboard shows each dataset's
events in a table, a summary with charts, a map and, with a second dataset
of the same kind, a comparison of how the two agencies reported the same
events; the filters — magnitude, time, type and a bounding box — apply to
all of them, and **Filter to this view** on the map turns the visible area
into the box. The words follow the dataset's kind: a wildfire dataset has an
*Area* column in hectares and no depth, a storm dataset *Wind* in knots, and
the map colours its markers by kind and sizes them within the dataset's own
range. A *Details* column shows what a source knew beyond the shared
columns — an alert level, the reporting network, the country.
Its dev server proxies
`/api` to the backend on port 8000, so the browser sees a single origin and
the API needs no CORS configuration. That proxy is a development arrangement
only. A deployed build sets `VITE_API_URL` to the API's origin at build
time, and the API lists the frontend's origin in `CORS_ORIGINS`; both are
empty locally and nothing changes.

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
`queue` that Redis answers — or `null` when `INGESTION_MODE` is `inline`
and there is no queue to ask, so a deployment without Redis is not marked
unready forever. If a required dependency is down the body says `degraded`
and names it, and the response is a **503** — never a 500. An unreachable
database is "not ready", not "broken".

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
| `USGS_FEED_URL` | `…/all_week.geojson` | GeoJSON feed used by the ingestion; `all_day` and `all_month` also work |
| `USGS_TIMEOUT_SECONDS` | `30` | HTTP timeout for the feed request |
| `INGV_FEED_URL` | `…/fdsnws/event/1/query?…` | INGV query; a `starttime` is added per run |
| `INGV_TIMEOUT_SECONDS` | `30` | HTTP timeout for the INGV request |
| `INGV_DAYS` | `7` | Length of the INGV window, in days |
| `EMSC_FEED_URL` | `…/fdsnws/event/1/query?…` | EMSC query; a `starttime` is added per run |
| `EMSC_TIMEOUT_SECONDS` | `30` | HTTP timeout for the EMSC request |
| `EMSC_DAYS` | `7` | Length of the EMSC window, in days |
| `EONET_FEED_URL` | `…/api/v3/events?status=all` | EONET query; `category` and `days` are added per run |
| `EONET_TIMEOUT_SECONDS` | `30` | HTTP timeout for the EONET request |
| `EONET_DAYS` | `7` | Length of the EONET window, in days |
| `GDACS_FEED_URL` | `…/xml/rss_7d.xml` | GDACS RSS; the feed is the window |
| `GDACS_TIMEOUT_SECONDS` | `30` | HTTP timeout for the GDACS request |
| `REDIS_HOST` | `localhost` | Redis host (`redis` inside Compose) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database number |
| `QUEUE_NAME` | `metheon:imports` | Redis list used as the queue |
| `QUEUE_BLOCK_TIMEOUT_SECONDS` | `5` | How long the worker blocks on the queue |
| `QUEUE_RETRY_DELAY_SECONDS` | `5` | Pause before retrying after a Redis outage |
| `STALE_RUN_MINUTES` | `15` | A run at `processing` longer than this is failed at worker startup |
| `LOG_LEVEL` | `INFO` | Log level for the API and the worker |
| `TEST_POSTGRES_DB` | `metheon_test` | Database created by the test suite |
| `INGESTION_MODE` | `queue` | `queue`: Redis + worker; `inline`: the run happens in the request |
| `CORS_ORIGINS` | — | Browser origins allowed to call the API; empty locally |
| `POSTGRES_SSLMODE` | — | `require` for a hosted database such as Neon |
| `INGEST_COOLDOWN_MINUTES` | `10` | Minutes a dataset refuses another ingestion after a completed run; `0` disables |
| `RETENTION_DAYS` | `365` | Days an event is kept after it happened, swept with each ingestion; `0` keeps everything |
| `VITE_API_URL` | — | Frontend build-time API origin; empty locally |
| `GEMINI_API_KEY` | — | Enables insights; absent means off |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model asked for insights |
| `GEMINI_TIMEOUT_SECONDS` | `45` | HTTP timeout for the Gemini call |

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

The readiness check: whether the API can serve.

```bash
curl -i http://127.0.0.1:8000/api/health
```

```json
{"status": "ok", "service": "metheon", "database": true, "queue": true}
```

`database` confirms that FastAPI connected to PostgreSQL and ran a query;
`queue` that Redis answers. If either is down the body says `degraded` and
names the missing one, and the response is a **503** — never a 500. An
unreachable database is "not ready", not "broken".

The status code is the point: a probe or a load balancer reads the code,
not the body, and `degraded` inside a 200 would look healthy to it.

### `GET /api/health/live`

The liveness check: whether the process is running. Always `200`, and it
touches no dependency on purpose — a liveness probe that failed because the
database was down would get the process restarted, and restarting the
process does not bring the database back.

```json
{"status": "alive", "service": "metheon"}
```

Kubernetes readiness and liveness probes, and platform health checks, map
onto these two endpoints directly.

### Logging

Both processes log to stdout in one format, configured in
`backend/app/logging_config.py`:

```text
2026-09-13 23:30:54,793 INFO app.api import 18: queued for dataset 3
2026-09-13 23:30:54,806 INFO app.ingestion.runner import 18: starting for dataset 3 (ingv) from …
2026-09-13 23:30:55,229 INFO app.ingestion.runner import 18: completed, 337 fetched, 0 inserted, 337 updated, 0 invalid
```

Timestamps are UTC in both, on purpose: the API runs on the host in local
time and the worker in a container in UTC, and each using its own clock put
the same run two hours apart in the two logs.

The API writes one line per request — method, path, status, duration — after
the response, so the status is the one actually sent. The health endpoints
are logged at `DEBUG` only: a probe every few seconds would drown everything
else. Refusals and outages are `WARNING`s with the reason; anything that
became a 500 is an `ERROR` with the traceback.

`LOG_LEVEL` sets the level for both processes. uvicorn's own access line
duplicates the API's and carries less; `--no-access-log` silences it.

### Errors

Every route answers the same way when things break:

| Situation | Status | Body |
| --- | --- | --- |
| Request refused (unknown dataset, bad filter, unknown source) | `404` / `422` | `detail` says why |
| Redis unreachable when queueing a run | `503` | `detail` says why; the run is recorded as `failed` |
| PostgreSQL unreachable, on any route | `503` | `{"detail": "The database is unavailable"}` |
| Anything unforeseen | `500` | `{"detail": "Internal server error"}` — the traceback goes to the log, never to the client |

A 503 means "try again"; a 500 means "this is a bug, and it has been
logged".

### `GET /api/sources`

Lists the sources a dataset can be created for, with the feed each one
ingests by default and the kinds of event it serves.

```bash
curl http://127.0.0.1:8000/api/sources
```

```json
[
  {
    "key": "usgs",
    "name": "USGS Earthquake Hazards Program",
    "default_feed_url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
    "kinds": ["earthquake"]
  }
]
```

The seismic sources serve one kind, `earthquake`; EONET lists thirteen and
GDACS six, and a dataset created for either must say which one it holds.

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
    "status": "pending",
    "kind": "earthquake",
    "last_ingested_at": null
  }
]
```

`last_ingested_at` is when the latest completed run finished — what the
dashboard's cards show as "ingested 2 h ago" — and null before the first.

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
| `kind` | string | only when the source serves several kinds |

`id`, `created_at` and `status` are assigned by the database and must not be
supplied by the client.

`source` must be one of the keys returned by `GET /api/sources`, matched
case-insensitively. An unknown source returns `422` listing the known ones:
refusing it here beats accepting a dataset that can never be imported.

`kind` is which of the source's kinds the dataset holds. A source with one
kind decides it, and a `kind` sent anyway must match; a source with several
must be told, and refuses with `422` naming its kinds otherwise. The
dashboard's **New dataset** form offers the same choices from menus, and
shows the kind menu only when there is a choice to make.

### `GET /api/datasets/{id}/events`

Returns a page of the earthquakes stored for a dataset, most recent first.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/events?limit=2"
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
      "title": "30 km SE of Pāhala, Hawaii",
      "event_type": "earthquake",
      "occurred_at": "2026-09-09T08:43:38",
      "ended_at": null,
      "source_updated_at": "2026-09-09T09:01:10",
      "longitude": -155.2855,
      "latitude": 18.9995,
      "geometry": null,
      "magnitude": 1.98,
      "magnitude_unit": "md",
      "attributes": {"depth_km": 49.0, "tsunami": false, "significance": 60},
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
| `min_latitude`, `max_latitude` | — | Bounding box, inclusive, degrees in −90…90 |
| `min_longitude`, `max_longitude` | — | Bounding box, inclusive, degrees in −180…180 |

Filters are optional and combine with `AND`:

```bash
curl "http://127.0.0.1:8000/api/datasets/1/events?event_type=earthquake&min_magnitude=4"
```

`total` counts the events matching the filters rather than the whole dataset,
so a client can page through a filtered result. The filters actually applied
are echoed back in the response under `filters`.

Two details worth knowing:

- An event whose `magnitude` is null is excluded by any magnitude bound. SQL
  drops it on its own — `NULL >= 2` is null, not true — and that is the
  intended behaviour: an unknown magnitude cannot be said to clear a threshold.
- A range whose bounds are the wrong way round returns `422` rather than an
  empty page, which would read as "no data" instead of as a mistake. That
  includes a bounding box: one crossing the antimeridian would need
  `min_longitude > max_longitude`, and is not supported.

Out-of-range or unparsable values return `422`. Requesting an unknown dataset
returns `404`. Aggregations and charts remain part of Phase 3.

### `GET /api/datasets/{id}/events/points`

The matching events as bare coordinates, for a map: no paging, and only
what a marker needs.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/events/points?min_magnitude=5"
```

```json
{
  "dataset_id": 1,
  "total": 3,
  "limit": 5000,
  "filters": {"min_magnitude": 5.0},
  "points": [
    [162.519, -11.0595, 5.6, 3628],
    [-70.4, -21.1, 5.2, 3311],
    [142.1, 38.6, 5.0, 2980]
  ]
}
```

Each point is `[longitude, latitude, magnitude, id]`. Takes the same filters
as the listing, plus `limit` (default and maximum 5000). Points come
strongest first, so when the limit cuts it cuts the smallest events and
`total` still says how many matched; events without a magnitude come last.

### `GET /api/datasets/{id}/events/matches?other={id2}`

Pairs this dataset's events with another dataset's reports of the same
earthquakes. Two agencies observe one quake with different networks and give
it a different origin time, epicentre, depth and magnitude; the pairs put
those differences side by side.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/events/matches?other=2&min_magnitude=5"
```

```json
{
  "dataset_id": 1,
  "other_id": 2,
  "window_seconds": 60.0,
  "radius_km": 100.0,
  "limit": 50,
  "filters": {"min_magnitude": 5.0},
  "events": 25,
  "matched": 5,
  "unmatched": 20,
  "mean_abs_delta_seconds": 3.8,
  "mean_distance_km": 33.9,
  "mean_abs_delta_magnitude": 0.32,
  "pairs": [
    {
      "event": {"id": 3628, "external_id": "us7000rp1k", "title": "96 km ESE of Isangel, Vanuatu",
                "occurred_at": "2026-09-10T03:11:52", "longitude": 169.98, "latitude": -19.85,
                "magnitude": 5.6, "magnitude_unit": "mww", "attributes": {"depth_km": 10.0, "tsunami": false}},
      "other": {"id": 4102, "external_id": "44012345", "title": "Vanuatu Islands [Sea: Vanuatu]",
                "occurred_at": "2026-09-10T03:11:59", "longitude": 170.27, "latitude": -19.7,
                "magnitude": 5.9, "magnitude_unit": "mwp", "attributes": {"depth_km": 68.0, "tsunami": false}},
      "delta_seconds": 6.7,
      "distance_km": 33.3,
      "delta_magnitude": 0.3
    }
  ]
}
```

A pair is an event of `{id}` and the report in `other` nearest in time
within `window_seconds` (default 60, up to a week) and no farther than
`radius_km` (default 100, up to 1000). A quake is an instant and a minute
is generous; a fire or a storm is reported over days, and two curators can
date its start a day apart, so the dashboard asks for days and tens of
kilometres for those kinds. Each event pairs at most once. The
deltas are *other minus event*; `delta_magnitude` is null when either side
has no magnitude, and the magnitude mean covers only the pairs where both
do. The listing filters apply to the `{id}` side, so `events` is the
filtered count and `matched` + `unmatched` add up to it. `pairs` holds at
most `limit` pairs (1–500), strongest first; the counts and means cover all
of them.

Distances are great-circle, computed in SQL by the haversine formula — no
PostGIS, so nothing to install on a hosted database. Comparing a dataset
with itself returns `422`; an unknown dataset on either side `404`.

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

### `GET /api/datasets/{id}/events/summary`

Aggregates the matching events without returning them. Takes the **same
filters** as the listing, so a filtered view can describe exactly what it
shows.

```bash
curl "http://127.0.0.1:8000/api/datasets/1/events/summary?min_magnitude=4"
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

### `GET /api/ai`

Whether insights are available, and which model would answer:

```json
{"configured": true, "model": "gemini-3.8-flash"}
```

`configured` is false until `GEMINI_API_KEY` is set; the dashboard reads
this to show or hide the insights panel.

### `GET /api/datasets/{id}/insights`

Asks Gemini what the filtered data shows. Takes the same filters as the
listing and the summary, so the model and the reader are looking at the
same thing.

```bash
curl "http://127.0.0.1:8000/api/datasets/3/insights?min_magnitude=2"
```

```json
{
  "dataset_id": 3,
  "filters": {"min_magnitude": 2.0},
  "model": "gemini-3.8-flash",
  "summary": "This INGV dataset contains 56 earthquake events recorded between September 4 and 13, 2026, with magnitudes from 2.0 to 6.3 …",
  "key_trends": ["Daily event counts varied from a low of 2 on September 7 to a peak of 11 on September 5."],
  "anomalies": ["A magnitude 6.3 earthquake at a depth of 318.8 km offshore Jawa, Indonesia, was far deeper and stronger than the 2.93 average."],
  "recommendations": ["Apply a regional bounding box to separate domestic Italian events from global detections catalogued by INGV."],
  "agency_comparison": "",
  "other_id": null
}
```

The model never sees the rows. It is given the same aggregate the summary
endpoint returns — totals, magnitude statistics, counts per day and per type
— plus the five strongest events, about 1.6 kB in all, with a system
instruction that forbids inventing anything not in that data. The answer is
constrained to a JSON Schema on Gemini's side and validated against the
response model on ours.

With `other={id2}` — and `window_seconds` / `radius_km` as for the matches
endpoint — the model is also given what that comparison would answer: the
counts, the mean differences in time, distance and measure, and the five
pairs where the two agencies disagree most. It is asked to describe the
agreement in `agency_comparison`, and told that different networks and
methods explain most differences, so it does not call either agency wrong.
The dashboard passes whatever the **Compare** panel is set to. A first real
run, GDACS wildfires against NASA EONET's:

> Out of 222 GDACS wildfire events, NASA EONET matched 45, leaving 177
> unmatched within the 50.0 km and 72-hour window. On average, the matched
> events were located 3.59 km apart, separated by 8.6 hours, with a mean
> absolute magnitude difference of 2,752.73 hectares. The most discordant
> match was a fire in Namibia where GDACS reported 61,629.0 hectares while
> EONET reported 10,146.0 hectares.

`other` must be another dataset of the same kind (`422` otherwise, `404` if
unknown).

| Status | Meaning |
| --- | --- |
| `503` | No `GEMINI_API_KEY`; the feature is off, the rest of the API is up |
| `502` | Gemini failed or answered outside its schema; `detail` carries Google's message |

The free tier of the model is sometimes overloaded — the first real run of
this endpoint answered in five seconds, the second met "currently
experiencing high demand" after forty. That surfaces as a `502` with the
reason, and the dashboard's button is the retry. There is no automatic
retry: on a metered tier it would double the wait and, if the problem were
quota, spend more of it.

Calls are not stored on Google's side (`store: false`). The key travels in a
header, never in a URL, and never reaches the log.

### `POST /api/datasets/{id}/ingest`

Ingests the dataset's source feed and answers with the run — the same row
`GET /api/datasets/{id}/imports` returns.

```bash
curl -X POST http://127.0.0.1:8000/api/datasets/1/ingest
```

How the work happens depends on `INGESTION_MODE`:

| Mode | Answer | Who does the work |
| --- | --- | --- |
| `queue` (default) | `202`, run `queued` | Redis and the worker; follow it through the history |
| `inline` | `200`, run `completed` | this request; the data is there when it returns |

`inline` exists for a deployment with no worker — no free platform runs
one. The same host sleeps after an hour without visitors and takes up to a
minute to wake; the dashboard says so after three seconds of waiting
rather than sitting on "Loading…". Ingestion is measured at under a second for a week of USGS data against a
local database, a few seconds against Neon in another region: the upsert
sends the whole batch in one pipelined round-trip, not one per event. Locally,
follow a queued run through `GET /api/datasets/{id}/imports`, watch the
worker with `docker compose logs -f worker`, or press **Ingest now** in the
dashboard. The dataset `status` mirrors the latest run: `queued`, then
`processing`, then `completed` or `failed`.

Requesting an unknown dataset returns `404`. In `queue` mode, if Redis cannot
be reached the call returns `503`, and the run is still recorded as `failed`
so the outage is visible in the history rather than silently swallowed. In
`inline` mode a feed that cannot be fetched returns `502`, with the run
recorded as `failed` the same way.

The endpoint is public — the dashboard's button needs it to be — and each
run fetches a feed from a public agency on this service's behalf, so a
dataset refuses another ingestion for `INGEST_COOLDOWN_MINUTES` (ten by
default) after a completed one, and while a run is in flight, with `429`
and a `Retry-After` header. A failed run does not count: retrying one is
what a person does next. Set the cooldown to `0` to switch it off locally.

### `DELETE /api/datasets/{id}`

Deletes a dataset with its events and its import history, and answers
`204`. The schema cascades, so nothing is left behind; a run in flight for
the dataset fails when it next writes and is recorded as such. `404` for an
unknown dataset. The dashboard's **Delete dataset** button asks first.

### Retention

Every feed is a rolling window of the recent past, so re-ingesting
refreshes recent events and older ones only ever accumulate: measured on
the hosted database on 2026-09-15, about 660 bytes per event with its
indexes and some 3,000 new events a week across six datasets — roughly
100 MB a year against a free plan's 500. Years, not months, but a database
that grows without a rule fails on a day nobody chose.

The rule is `RETENTION_DAYS`, 365 by default: at the end of each ingestion
the run deletes that dataset's events that *occurred* more than that many
days ago — by when they happened, not when they arrived, so an old event
re-sent by a feed is still old — and logs how many went. The sweep rides
on the ingestion so it needs no worker or schedule of its own, and a
dataset is only ever swept by its own runs. `0` keeps everything. The
import history is not swept: a run is a few hundred bytes and the
history is the record of what happened.

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

Each dataset also carries a `kind` — `earthquake` for every dataset today —
saying what kind of thing its events are. One kind per dataset, so every
view of a dataset can assume one scale.

Table `events`, one row per event, keyed by the id the source gave it:

```sql
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    title TEXT,
    event_type VARCHAR(50),
    occurred_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    source_updated_at TIMESTAMP,
    longitude NUMERIC(9, 4) NOT NULL,
    latitude NUMERIC(8, 4) NOT NULL,
    geometry JSONB,
    magnitude NUMERIC(10, 2),
    magnitude_unit VARCHAR(20),
    attributes JSONB NOT NULL DEFAULT '{}',
    url TEXT,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (dataset_id, external_id)
);
```

The table is generic on purpose: what every kind of event has — a title,
a time, a point, the number it is measured by — is a typed column, and what
only one kind or one source has lives in `attributes`. For earthquakes that
is `depth_km`, `tsunami`, `significance` and, where the source says which
network reported the event, `network`. `magnitude` is the kind's principal
measure and `magnitude_unit` says what it is (`mww`, `ml`; for other kinds,
hectares or knots); it is only ever compared within a dataset. `ended_at`
and `geometry` are for events with a duration or a shape and are null for
quakes. Attributes are shown and compared, never filtered on.

The table began life as `earthquakes`, with the seismic fields as columns;
`backend/app/db/migrations/001_events.sql` moved an existing database over.
`init.sql` always describes the final schema, and `python -m
app.db.apply_schema` applies it and then any migration a database has not
yet had, recording each in `schema_migrations` so it runs once.

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

The `UNIQUE (dataset_id, external_id)` constraint is what makes ingestion
idempotent: writes use `ON CONFLICT DO UPDATE`. It is scoped to the dataset
because an id is only unique within its source — two agencies can reuse one
for different events, and the same event carries a different id at each.
Timestamps are stored as naive UTC. `magnitude` is nullable — a feed can
legitimately omit it.

## Project structure

```text
metheon/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application and routes
│   │   ├── schemas.py           # Request and response models, what /docs shows
│   │   ├── settings.py          # Deployment switches, inert by default
│   │   ├── ai/
│   │   │   ├── gemini.py        # The one HTTP call, with a response schema
│   │   │   └── insights.py      # The digest the model sees, and the prompt
│   │   ├── logging_config.py    # One log format for the API and the worker
│   │   ├── jobs.py              # Redis queue: enqueue, dequeue, health
│   │   ├── worker.py            # Background worker loop
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py      # Connection helper, env-based configuration
│   │   │   ├── apply_schema.py  # init.sql for a database with no initdb.d
│   │   │   ├── repository.py    # All SQL, kept out of route handlers
│   │   │   └── init.sql         # Schema, executed on first container start
│   │   └── ingestion/
│   │       ├── __init__.py      # The shared IngestionError
│   │       ├── sources.py       # Registry: source key → module
│   │       ├── geojson.py       # Envelope checks shared by the sources
│   │       ├── usgs.py          # USGS: fetching and normalization
│   │       ├── ingv.py          # INGV: fetching and normalization
│   │       └── runner.py        # Executes one queued import
│   ├── tests/
│   │   ├── conftest.py          # Shared fixtures and feature builder
│   │   ├── fixtures/            # Real feed responses, captured once
│   │   ├── test_api.py
│   │   ├── test_filters.py
│   │   ├── test_ingv.py
│   │   ├── test_jobs.py
│   │   ├── test_repository.py
│   │   ├── test_summary.py
│   │   ├── test_runner.py
│   │   ├── test_sources.py
│   │   ├── test_usgs_fetch.py
│   │   ├── test_usgs_normalization.py
│   │   └── test_worker.py
│   ├── Dockerfile               # One image: API by default, worker by command
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── api/                 # Types and fetch helpers for the API
│   │   ├── components/          # Browser, ingestion panel, dataset form,
│   │   │                        #   summary, chart, insights — tests beside each
│   │   ├── theme/               # Light / dark / system
│   │   ├── test/                # Fixtures and the fetch stand-in
│   │   ├── App.tsx              # Dataset list, selection, refresh wiring
│   │   ├── index.css
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts           # Dev-only proxy to the API
├── k8s/                         # Kind cluster: manifests and dev.sh
├── .github/
│   └── workflows/
│       └── ci.yml               # Tests and worker image build
├── LICENSE                      # MIT
├── .env.example
├── .gitignore
├── .nvmrc                       # Node for the frontend
├── .python-version              # Python for the backend
├── CLAUDE.md                    # Detailed architecture and working notes
├── README.md
└── docker-compose.yml
```

## Development notes

### Python version

The project targets **Python 3.12**, pinned in `.python-version`. It started
on 3.9 and moved when 3.9 left security support in October 2025; the
upgrade needed no code change, and every pinned dependency already shipped
3.12 wheels. Modern syntax such as `str | None` is welcome in new code; the
`Optional[...]` already there is correct and not worth a churn commit.

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
| `Backend image` | Builds `backend/Dockerfile`, imports both entrypoints inside it, checks it runs unprivileged, and starts the API from the default command |

Alongside the handwritten cases, a real feed response captured on 2026-09-09 is
kept in `tests/fixtures/` and normalized in full, so the tests stay honest about
the shape the feed actually has.

The worker loop is covered too: an empty queue, a job that raises, a shutdown
request and a Redis outage each have a test, with the queue and the job both
replaced.

The frontend has its own suite, run from `frontend/` with `npm test`. It uses
Vitest and Testing Library in jsdom, with `fetch` replaced, so it needs
nothing running either.

### Scheduled ingestion

Production has no worker, so `.github/workflows/ingest.yml` keeps the data
fresh instead: every six hours (and on demand from the Actions tab) it lists
the deployed API's datasets and calls `POST /ingest` on each, inline. The
feeds cover the last seven days, so a late run leaves no gap. The job fails
when a run does not complete, which makes a broken ingestion visible under
Actions rather than as data that quietly stops moving. It retries the first
request, since the API may be asleep and take a minute to wake.

`POST /ingest` needs no authentication, on the deployed API as much as
locally: anyone can trigger a run, including the dashboard's button, which
is the reason there is no token. What keeps that from being abused is the
per-dataset cooldown (`429` for ten minutes after a completed run); the
schedule's six hours clear it by a wide margin.

### The backend image

`backend/Dockerfile` builds one image for the whole backend. It starts the
API by default; Compose runs the worker from the same image with a different
command, since the two share every line of code and every dependency.

```bash
docker build -t metheon-backend ./backend
docker run --rm -p 8000:8000 -e POSTGRES_HOST=host.docker.internal metheon-backend
```

The process runs as an unprivileged user, `app`. There is no `HEALTHCHECK`
in the image: probes belong to whatever runs the container, and the worker
serves no HTTP. The endpoints are `/api/health/live` and `/api/health`.

The image is 296 MB, of which about 240 MB is `python:3.12-slim` itself,
57 MB the dependencies and 200 kB the code. No compiler is installed, so a
multi-stage build would have nothing to strip; it was measured and skipped.

For day-to-day development the API still runs in the virtualenv, as above.
The image exists for CI, for Kubernetes and for deployment.

The worker runs from this image, so code changes need a rebuild:

```bash
docker compose up -d --build worker
```

It stops cleanly on `docker compose stop`: the current job finishes before the
process exits.

If it is killed instead — `docker kill`, a crash, a lost host — the run it
was processing stays at `processing`. On its next start the worker fails any
run that has been at `processing` for longer than `STALE_RUN_MINUTES`, with
"Abandoned" as the reason, and corrects the dataset's status if that run was
its latest. The threshold matters once there is more than one worker: a run
another worker is genuinely processing must not be failed under it.

### Running on Kubernetes, locally

The whole system runs on a [Kind](https://kind.sigs.k8s.io/) cluster —
Kubernetes in Docker, on this machine, nothing remote. The manifests are in
`k8s/` and `k8s/dev.sh` drives them:

```bash
brew install kind          # once; kubectl comes with Docker Desktop
k8s/dev.sh up              # create the cluster, build and load the image, deploy
k8s/dev.sh deploy          # after a code change: rebuild, reload, roll out
k8s/dev.sh status
k8s/dev.sh down
```

The API is then at `http://localhost:8080`, mapped from the cluster by the
Kind config. To point the dashboard at it instead of the virtualenv:

```bash
VITE_API_PROXY=http://localhost:8080 npm run dev
```

What runs: Postgres as a StatefulSet with a persistent volume and `init.sql`
mounted from a ConfigMap, Redis and the API as Deployments with Services,
and the worker as a Deployment from the same image with a different
command. The API's probes are the two health endpoints: liveness on
`/api/health/live`, readiness on `/api/health`.

That split is the point of the exercise, and it was checked by stopping
Postgres in the cluster: the API pod left the Service's endpoints within
fifteen seconds and was **not** restarted, `/api/health/live` kept
answering 200 inside it, and it rejoined the traffic four seconds after
Postgres came back — same pod, zero restarts, data intact on the volume.
With one probe for both, Kubernetes would have restarted the API for a
fault the API did not have.

`kustomize` refuses files outside `k8s/`, so `dev.sh` creates the
`init.sql` ConfigMap itself from `backend/app/db/init.sql`; copying the
schema into `k8s/` would have left two of them to keep in step.

The Gemini key is not in `k8s/config.yaml` and must never be: to enable
insights in the cluster, add it to the Secret out of band —
`kubectl -n metheon create secret generic metheon-ai --from-literal=GEMINI_API_KEY=…`
and reference it from the API Deployment — or leave it out and the panel
says so.

Kubernetes has no role in the deployment stack chosen for this project. This
is local study and demonstration: the manifests, the probes and the
config/secret split are what they would be anywhere.

### Preparing for a deployment

The code is ready to be deployed without further changes; four settings turn
the deployment behaviour on, and all of them are off locally:

| Setting | Where | Effect |
| --- | --- | --- |
| `INGESTION_MODE=inline` | API host | ingestion runs in the request; no Redis, no worker |
| `CORS_ORIGINS=https://…` | API host | the frontend's origin may call the API from a browser |
| `POSTGRES_SSLMODE=require` | API host | the connection to a hosted PostgreSQL is encrypted |
| `VITE_API_URL=https://…` | frontend build | the built dashboard calls the API on its own origin |

A hosted database has no `docker-entrypoint-initdb.d`; apply the schema
once with the environment pointed at it:

```bash
cd backend && python -m app.db.apply_schema
```

It reads `backend/app/db/init.sql`, so the schema keeps its single source,
and it is idempotent. The hosting decisions themselves — which platforms,
and why — are in `CLAUDE.md`.

### Where it runs

The API is deployed at `https://metheon.onrender.com`: a free Render web
service in Frankfurt, built from `backend/Dockerfile`, with
`INGESTION_MODE=inline` and a Neon PostgreSQL in the same region. Render
spins a free service down after fifteen minutes without traffic and takes
about a minute to wake it, so the first request after a pause is slow; the
ones after it are not. Render hands a service its port through `PORT`, set
to `8000` to match the Dockerfile.

The site is at `https://metheon.pages.dev` — the landing page, with the
dashboard at `/app/` (`public/_redirects` makes Pages serve `index.html`
there, and sends the bare `/app` to it) — a Cloudflare Pages project
built from `frontend/` on every push to `main` with
`VITE_API_URL=https://metheon.onrender.com`; the API allows that one origin
through `CORS_ORIGINS`. Pressing **Ingest now** there runs the ingestion
inline on Render against Neon and refreshes the page when it finishes;
between presses, the [scheduled ingestion](#scheduled-ingestion) does the
same every six hours.

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
- [x] **Phase 3 — Analytics:** pagination, filtering and aggregation in the
  API; a dashboard with filters, paging, summary tiles and charts
- [x] **Phase 4 — AI:** Gemini reads the filtered summary and answers with
  a structured summary, trends, anomalies and recommendations; off without
  a key
- [ ] **Phase 5 — Engineering quality:** backend and frontend are both
  covered by tests, CI runs everything on every push, the worker logs its
  work, the API exposes readiness and liveness checks and answers failures
  with the right status, both processes log in one format, abandoned runs
  are reaped, one unprivileged image serves both processes, and Swagger
  describes every response. Done, and the code is under the MIT licence —
  see [Licence](#licence)
- [x] **Phase 6 — Kubernetes:** the whole system on a local Kind cluster,
  with liveness and readiness probes shown to behave differently

See [CLAUDE.md](CLAUDE.md) for the detailed architecture and design principles.

## Licence

[MIT](LICENSE). Use it, change it, ship it; keep the copyright notice.

The licence covers the code, not the data the project ingests: USGS data is
in the public domain, and INGV data carries INGV's own terms.
