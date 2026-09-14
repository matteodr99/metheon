# Design: from earthquakes to events

Status: **in progress**, 2026-09-14. Steps 1 (migration mechanism, `events`
table, API and dashboard renamed) and 2 (kinds: vocabulary, per-source
declaration, resolution at creation, re-check at each run, the form) are
built; steps 3 and 4 are not.

## Why

Metheon's pipeline — fetch, validate, normalize, upsert, record the run,
filter, aggregate, map, compare — has nothing seismic in it. Its schema
does: the one table is `earthquakes`, with `magnitude_type`, `depth_km` and
`tsunami` as columns, and every route says so in its path. The goal is to
ingest public data of other kinds — wildfires, storms, volcanic activity,
floods — without a second pipeline, and without turning the schema into a
bag of nullable columns that mean something different per row.

## The decision in one line

**A dataset holds events of one kind.** The kind is a property of the
dataset, chosen when it is created and fixed by the source; the events
table is generic; what only one kind needs lives in a JSON column.

## Why the kind belongs to the dataset, not the event

The alternative — a `kind` column per event, datasets free to mix — was
considered and set aside:

- Every view in the dashboard assumes one kind. A summary's "magnitude
  range" over earthquakes and hectares mixed is nonsense; a map needs one
  scale; the comparison pairs like with like. With one kind per dataset
  all of that stays true by construction instead of by a filter the reader
  must remember to apply.
- The one source that mixes kinds in a single feed, NASA EONET, also
  accepts `?category=` and answers one kind at a time. Creating "EONET
  wildfires" and "EONET storms" as two datasets costs nothing and reads
  better than one dataset with a kind selector.
- It is the smaller change: one column on `datasets`, none on the events
  beyond what generalizing already needs.

If a mixed dataset is ever wanted, adding `kind` to the events table then
is additive; going the other way would not be.

## Schema

### `datasets`

```sql
ALTER TABLE datasets ADD COLUMN kind VARCHAR(50) NOT NULL DEFAULT 'earthquake';
```

`kind` is one of a short vocabulary owned by the code, not by any source:
`earthquake`, `wildfire`, `storm`, `volcano`, `flood`, `landslide`,
`sea_ice`, `drought`, `dust`, `temperature`, `manmade`. A source module
declares which kinds it can serve; the ingest run passes the dataset's
kind to the module so a multi-kind source knows what to ask for.

### `events` (replaces `earthquakes`)

```sql
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    title TEXT,                             -- was `place`
    event_type VARCHAR(50),                 -- the source's finer class, unchanged
    occurred_at TIMESTAMP NOT NULL,         -- origin or start
    ended_at TIMESTAMP,                     -- for events with a duration
    source_updated_at TIMESTAMP,
    longitude NUMERIC(9, 4) NOT NULL,       -- a representative point, always
    latitude NUMERIC(8, 4) NOT NULL,
    geometry JSONB,                         -- the full GeoJSON geometry when it is more than a point
    magnitude NUMERIC(10, 2),               -- the kind's principal measure
    magnitude_unit VARCHAR(20),             -- was `magnitude_type`: "mww", "ml", "hectares", "kts"
    attributes JSONB NOT NULL DEFAULT '{}', -- what only this kind or source has
    url TEXT,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (dataset_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_events_dataset_id ON events (dataset_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events (occurred_at);
```

What moves where, for the existing seismic rows:

| Today | Tomorrow |
| --- | --- |
| `place` | `title` |
| `magnitude_type` | `magnitude_unit` |
| `depth_km`, `tsunami`, `significance` | `attributes.depth_km`, `attributes.tsunami`, `attributes.significance` |
| — | `attributes.network` (EMSC's `auth`, dropped today for lack of a column) |

Everything a filter, a sort, a chart or a join reads stays a typed column:
time, position, magnitude, event type. `attributes` is displayed and
compared, never filtered on; the day a JSON key needs an index is the day
it becomes a column.

`magnitude` keeps its name on purpose. It is "the number this kind is
measured by" — moment magnitude for a quake, burned area for a fire, wind
speed for a storm, VEI for an eruption when a source gives one — and it is
only ever compared within a dataset, which is of one kind. `magnitude_unit`
says what it is. Renaming it `measure` would be more honest and would
change every route, test and screen for a word.

### Migration

The project has no migrations: `init.sql` is idempotent `CREATE IF NOT
EXISTS`, applied once by Compose and by hand elsewhere. This change is the
first that alters existing tables with data in them, on Neon in particular,
so it introduces the mechanism it needs and no more:

- `backend/app/db/migrations/001_events.sql`: creates `events`, copies
  `earthquakes` into it (`INSERT … SELECT`, seismic columns folded into
  `attributes` with `jsonb_build_object`), adds `datasets.kind`, drops
  `earthquakes`. One transaction.
- `schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP)`;
  `apply_schema` runs `init.sql`, then every numbered file not yet
  recorded, in order, each in its own transaction, recording it after.
- `init.sql` is rewritten to describe the *final* schema, so a fresh
  database (Compose, the test database, Kind) gets it directly and the
  migration is a no-op there — it checks `to_regclass('earthquakes')` and
  does nothing when the old table is absent.

Order of application in production: deploy the code that reads `events`
only after the migration has run; the API is a single free instance, so
"run `apply_schema` against Neon from this machine, then push" is the
whole procedure, with a minute in which the old code sees no `earthquakes`
table and answers 503. Acceptable for a portfolio site; the alternative — a
compatibility view named `earthquakes` kept for one release — is noted and
not proposed.

## Sources

A module gains one declaration and one parameter:

```python
KINDS = ("earthquake",)                     # usgs, ingv, emsc
KINDS = ("wildfire", "storm", "volcano", …) # eonet

def fetch_feed(url=None, timeout=None, kind=None): …
def normalize_feed(payload, kind) -> (records, errors): …
```

The registry checks that a dataset's kind is one its source offers, at
creation (422 otherwise) and at each run. The three seismic modules return
the record they return today under the new names, with the seismic fields
under `attributes`. `geojson.parse_point_feature` is unchanged; a source
whose geometry is not a point (EONET storm tracks, GDACS polygons) computes
the representative point itself and stores the geometry alongside.

### First new source: NASA EONET v3

`https://eonet.gsfc.nasa.gov/api/v3/events?category=wildfires&days=7&status=all`

- one call per kind, selected by `category`; the category maps one-to-one
  onto the kind vocabulary above
- `id`, `title`, `link`, `closed` (→ `ended_at`), `categories`
- `geometry[]`: dated points or polygons — the latest one gives
  `occurred_at`'s counterpart for position, the first one the start time;
  the list goes to `geometry`
- `magnitudeValue` / `magnitudeUnit` where present (acres for fires, kts
  for storms) → `magnitude` / `magnitude_unit`, with acres converted to
  hectares so one kind has one unit
- no authentication, no rate limit worth noting, a few hundred open events

GDACS (severity-graded alerts for floods, cyclones, quakes, volcanoes) is
the natural second: it reports the same storms and floods as EONET, which
gives the comparison something beyond seismology.

## API

Routes rename from `earthquakes` to `events`; there is no external
consumer to keep compatible, and a path that lies is worse than a
changelog entry. Otherwise unchanged in shape:

| Today | Tomorrow |
| --- | --- |
| `GET /api/datasets/{id}/earthquakes` | `GET /api/datasets/{id}/events` |
| `…/earthquakes/summary`, `/points`, `/matches` | `…/events/summary`, `/points`, `/matches` |
| `POST /api/datasets` `{name, source}` | `{name, source, kind?}` — required when the source offers several kinds |
| `GET /api/sources` | adds `kinds` per source |
| `GET /api/datasets` | adds `kind` per dataset |

Filters stay the five plus the box; `min_magnitude` means "in this
dataset's unit". `matches` refuses two datasets of different kinds with
422. The summary adds nothing; its `magnitude` block is already nullable.

## Dashboard

- the dataset card shows the kind; the new-dataset form shows a kind
  selector only when the chosen source offers more than one
- the events table reads `title` and, for earthquakes, `attributes.depth_km`;
  column labels come from a small per-kind table in the frontend (`Magnitude`
  / `Area` / `Wind`, `Depth` shown for quakes only)
- the map colours markers by kind and sizes them by magnitude within the
  dataset's own range rather than by a seismic formula
- the comparison already speaks in deltas; only the depth column becomes
  kind-dependent
- the insights digest tells the model the kind and the unit

## What this does not do

- no cross-kind analysis ("fires after quakes"); datasets stay separate
- no time series (air quality, river levels): those are measurements, not
  events, and would be a different table with a different API
- no persistence of pairs; the comparison stays a query
- no attribute filtering; `attributes` is for display and comparison

## Steps, in order, each shippable alone

1. **Migration mechanism + schema** — `schema_migrations`, `001_events.sql`,
   `init.sql` rewritten, `apply_schema` extended; repository renamed to
   `events` with the seismic modules writing `attributes`. API paths
   renamed, frontend and docs updated in the same commit. All tests pass;
   run against Neon; push. *The biggest step and the only risky one.*
2. **Kinds** — `datasets.kind`, `KINDS` on the modules, the registry
   check, the create form. Small.
3. **EONET** — the source module, fixture, tests; the map and table learn
   their per-kind labels and colours.
4. **GDACS** — second non-seismic source; the comparison across kinds of
   agency.

Estimated at two working sessions for step 1 and one each for the rest.
