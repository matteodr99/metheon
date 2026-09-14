# Design: measurements over time

Status: **proposal, parked**, 2026-09-15. Nothing here is implemented, and
nothing is scheduled: the decision on 2026-09-15 was to add no further data
for now. The three open questions at the end are still open.

## Why

Metheon ingests *events*: things that happen at a point, at a moment,
with a size — a quake, a fire, a storm. It cannot ingest *measurements*: a
value that a fixed station reads again and again — the height of a river
every fifteen minutes, the PM2.5 at a street corner every hour, the tide at
a harbour. That is the other half of public environmental data, and it
does not fit `events`: a reading has no title, no end, no magnitude of its
own kind; it has a station, a quantity, a time and a number, and it comes
ten thousand at a time.

The pipeline around the table — sources, runs, the import history, the
cooldown, retention, the dashboard's filters and map — carries over. The
table, the queries and the charts do not.

## The decision in one line

**A dataset is either events or series, never both.** A series dataset
holds stations; each station holds series, one per measured quantity;
each series holds readings. Three tables, the bulk one as narrow as it can
be.

## Why three tables, not one

- *One `readings` table with station and quantity columns on every row*
  was considered and set aside: a station's name, position and metadata
  would repeat on every reading, the bulk table would carry text, and the
  map would have to `DISTINCT` its way to the stations.
- *Two tables, stations and readings, with the quantity on the reading*
  puts the unit on every row and makes "which quantities does this station
  measure" a scan.
- *Three tables* keep every reading to `(series_id, observed_at, value)`:
  about 50 bytes with its index, against 660 for an event. A gauge that
  reports every fifteen minutes writes 35,000 readings a year; at that
  width it is under 2 MB a series.

## Schema

### `datasets`

```sql
ALTER TABLE datasets ADD COLUMN shape  VARCHAR(10) NOT NULL DEFAULT 'events';  -- 'events' | 'series'
ALTER TABLE datasets ADD COLUMN config JSONB NOT NULL DEFAULT '{}';
```

`shape` is what the source declares (`SHAPE = "series"` on the module) and
what the API and the dashboard branch on. `kind` keeps naming what is
measured — `river`, `air_quality`, `tide`, `weather` join the vocabulary —
so the map colours, the words and the comparison rule stay per kind.

`config` is what a series source needs to know which stations and
quantities to ask for: a river source wants site codes and parameter
codes, an air-quality source wants a bounding box or a city. It is the
source module's business; the module declares the keys it reads, the
create form shows a field per key, and creation refuses a dataset whose
config the source cannot use (`422`). Event sources leave it empty.

### `stations`

```sql
CREATE TABLE IF NOT EXISTS stations (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,      -- the code the agency uses
    name TEXT,
    longitude NUMERIC(9, 4) NOT NULL,
    latitude NUMERIC(8, 4) NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}', -- elevation, basin, operator, whatever the source says
    UNIQUE (dataset_id, external_id)
);
```

A station is what the map draws for a series dataset: one marker,
coloured by kind, sized by the latest reading of the quantity the reader
picked.

### `series`

```sql
CREATE TABLE IF NOT EXISTS series (
    id SERIAL PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    quantity VARCHAR(50) NOT NULL,   -- from a vocabulary owned by the code: gage_height, discharge, pm25, no2, water_level, temperature
    unit VARCHAR(20) NOT NULL,       -- one unit per quantity, converted at ingestion: m, m3/s, µg/m3, °C
    attributes JSONB NOT NULL DEFAULT '{}',   -- the source's own code and name for the quantity, its data quality flag
    UNIQUE (station_id, quantity)
);
```

The quantity vocabulary is owned by the code, like the kinds: `gage_height`
means the same thing whichever agency's gauge measured it, and a source
converts (feet to metres, ppb to µg/m³) on the way in. That is what will
make two agencies' stations comparable later.

### `readings`

```sql
CREATE TABLE IF NOT EXISTS readings (
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    observed_at TIMESTAMP NOT NULL,   -- naive UTC, like everything else
    value NUMERIC(12, 4),             -- null when the agency reports a gap
    PRIMARY KEY (series_id, observed_at)
);
```

No surrogate key, no JSONB, no text: the primary key is the index the
queries need (one series, a time range), and it is the upsert's conflict
target — an agency that revises a provisional reading overwrites the old
value, the way a revised magnitude overwrites an event. Quality flags, when
a source has them (USGS marks provisional data `P`), go on the series
rather than the reading; a per-reading flag can be added as a column the
day a source revises readings one at a time.

### Migration

`002_series.sql`: the two columns on `datasets` and the three tables.
Additive only, nothing to move, a no-op on a fresh database; `init.sql`
rewritten to the final schema, as before. Applied to Neon before the push.

### Retention

The same `RETENTION_DAYS`, applied to `readings` by `observed_at` at the
end of each run, for that dataset's series. Readings are the one table
that could grow fast — a dozen fifteen-minute gauges write half a million
rows a year — so the default may need to be lower for series datasets
than for events; the setting can gain a per-shape variant if a real
dataset shows the need. Stations and series are not swept.

## Sources

A series source module declares `SHAPE = "series"`, its `KINDS`, the
`CONFIG` keys it reads, and provides `fetch_feed(url, timeout, kind,
config)` and `normalize_feed(payload, kind, config)` returning stations,
series and readings rather than events — the runner branches on the
dataset's shape and upserts each in turn, in one transaction.

### First source: USGS Water Services

`https://waterservices.usgs.gov/nwis/iv/?format=json&sites=01646500&parameterCd=00065,00060&period=P7D`

Probed on 2026-09-15: no key, JSON, one `timeSeries` per site and
parameter with the site's name and coordinates, the parameter's code, name
and unit (`ft`, `ft3/s`), a `noDataValue` sentinel, and a list of dated
values with qualifiers (`P`, provisional). Two sites over a day answered
283 fifteen-minute values per series. The dataset's `config` names
`sites` and `parameters`; the module maps parameter codes to the quantity
vocabulary (`00065` → `gage_height` in metres, `00060` → `discharge` in
m³/s) and drops the sentinel. Same agency as the first event source, which
says something about the pipeline: USGS publishes both kinds of thing.

### Second source: OpenAQ

Air quality from reference monitors worldwide, v3 API. Probed on
2026-09-15: needs a free API key (`401` without one), so like Gemini it
would be `OPENAQ_API_KEY` in the environment, and the source would be
listed but refuse to ingest until the key is set. Stations are `locations`
with coordinates and a list of `sensors`, one per quantity, each with
hourly measurements. `config`: a bounding box or a country.

### Alternative: Open-Meteo air quality

No key, any coordinates, hourly PM2.5, NO₂ and the rest — but from a
model (CAMS), not a station. Probed: 48 hourly values for Milan in one
call. It fits the schema (a "station" at the coordinates asked for, with
`attributes.model = true`) and would be the cheapest way to have air
quality at all; it is not an observation, and the dashboard would have to
say so. Second choice after OpenAQ, not instead of it.

## API

Series datasets get their own routes; the event routes answer `422` for
them, and vice versa, with `detail` naming the shape.

| Route | Answer |
| --- | --- |
| `GET /api/datasets/{id}/stations` | the stations with, per series, the quantity, the unit, the latest reading and its time; the map's data |
| `GET /api/datasets/{id}/series/{series_id}/readings?from=&to=&step=` | the readings in a range; `step` of `raw`, `hour` or `day` aggregates with `date_trunc` to min, max and mean per bucket — a week at fifteen minutes is 670 points, a year is 35,000, and a chart wants a few hundred |
| `GET /api/datasets/{id}/series/summary?quantity=&from=&to=` | per station: min, max, mean, latest, and the change over the range; the tiles and the table |
| `POST /api/datasets` | gains `config`; `GET /api/sources` says which keys a source reads |

Filters are a time range and a quantity; the bounding box applies to
stations. The matches endpoint has no series equivalent yet (see below).

## Dashboard

`EventBrowser` is for events; a series dataset opens a `SeriesBrowser`:

- a quantity selector (the dataset's series' quantities), a time range
- tiles: stations, readings in range, min / max / mean across stations
- the map, of stations, sized by the latest reading — the `EventMap`
  generalized to take markers, not points
- a line chart of the selected station's series over the range —
  hand-written SVG like `BarChart`, with a time axis; the first chart
  with an axis, which is the point at which `BarChart`'s comment said to
  reconsider a library. Reconsidered: one line chart with an axis is
  still a hundred lines, not a dependency
- a table of stations with their latest readings and the change over the
  range
- the insights, with a series digest: the summary per station and the
  extremes, the same pattern as for events

`kinds.ts` gains the series kinds and a `quantities.ts` the words and
decimals per quantity.

## What this does not do

- no comparison of two agencies' series (a station of one against a
  station of the other at the same place): the design leaves room for it —
  one quantity vocabulary, one unit — and a first version can be the
  correlation of two series over a range, later
- no forecasts, even where a source offers them (Open-Meteo): a forecast
  is a different thing from a reading and would need a column saying so
- no derived series (daily means stored): aggregation is on request,
  with `step`
- no alerts or thresholds

## Steps, each shippable alone

1. **Schema and API** — migration `002_series.sql`, the three tables,
   `datasets.shape` and `config`; repository functions; the three routes
   with `step` aggregation; the shape check on both route families. Tests
   on seeded series. *The largest step.*
2. **USGS Water Services** — the source module with its config, fixture
   and tests; the runner branching on shape; the create form's config
   fields. A river dataset ingests end to end.
3. **Dashboard** — `SeriesBrowser`, the station map, the line chart, the
   table; the words per quantity.
4. **OpenAQ** — the second source, behind its key; then Open-Meteo if a
   keyless air-quality option is wanted.
5. **Insights for series** — the digest and the prompt.

Estimated at two sessions for step 1, one each for 2 and 3, one for 4
and 5 together.

## Open questions, for the reader

1. **First source**: USGS water (no key, observations, US only) as
   proposed, or OpenAQ (key, observations, worldwide, air quality) first?
2. **Retention for readings**: the same 365 days as events, or shorter by
   default (90) given the volume?
3. **Config in the create form**: free text fields per key (a list of site
   codes) is the simplest; a station picker would need the source to list
   its stations first, which USGS can do by state and OpenAQ by box. Start
   with text?
