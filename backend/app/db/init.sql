CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- What kind of thing the events of this dataset are, one kind per
    -- dataset: "earthquake", "wildfire", "storm"... Fixed by the source at
    -- creation; every view of a dataset can then assume one scale.
    kind VARCHAR(50) NOT NULL DEFAULT 'earthquake'
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    title TEXT,
    -- The source's own finer classification: "earthquake", "quarry blast",
    -- "suspected earthquake". The dataset says what kind of thing its
    -- events are; this says what the source called this one.
    event_type VARCHAR(50),
    occurred_at TIMESTAMP NOT NULL,
    -- Set for events with a duration; null for an instant such as a quake.
    ended_at TIMESTAMP,
    source_updated_at TIMESTAMP,
    -- A representative point, always present, so every event can be
    -- filtered by a box and drawn on a map. When the source gives more —
    -- a storm track, a burnt-area polygon — the full GeoJSON is kept too.
    longitude NUMERIC(9, 4) NOT NULL,
    latitude NUMERIC(8, 4) NOT NULL,
    geometry JSONB,
    -- The number this kind of event is measured by: moment magnitude for
    -- a quake, hectares for a fire, knots for a storm. Compared only within
    -- a dataset, which holds one kind; the unit says which it is.
    magnitude NUMERIC(10, 2),
    magnitude_unit VARCHAR(20),
    -- What only this kind or this source has: depth_km, tsunami and
    -- significance for quakes, the reporting network, and so on. Shown and
    -- compared, never filtered on; a key that needs an index becomes a column.
    attributes JSONB NOT NULL DEFAULT '{}',
    url TEXT,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- An id is unique within its source, not across sources: two agencies
    -- can use the same id for different events, and the same event carries
    -- a different id at each agency. Scoping by dataset makes the upsert
    -- idempotent per dataset and lets sources coexist.
    UNIQUE (dataset_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_events_occurred_at
    ON events (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_dataset_id
    ON events (dataset_id);

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

CREATE INDEX IF NOT EXISTS idx_imports_dataset_queued
    ON imports (dataset_id, queued_at DESC);

-- Which numbered files under migrations/ have been applied. init.sql
-- describes the final schema, for a fresh database; a migration brings an
-- existing one up to it, and records itself here so it runs once.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
