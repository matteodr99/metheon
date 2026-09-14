-- From `earthquakes` to `events`: the same rows in the generic table, with
-- what only a quake has folded into `attributes`, and a kind on the dataset.
--
-- A fresh database built from init.sql has no `earthquakes` table, and
-- init.sql already adds `datasets.kind`; the whole block is then a no-op.
-- Runs in one transaction, so a failure part-way leaves the old table.

ALTER TABLE datasets ADD COLUMN IF NOT EXISTS kind VARCHAR(50) NOT NULL DEFAULT 'earthquake';

DO $$
BEGIN
    IF to_regclass('earthquakes') IS NULL THEN
        RETURN;
    END IF;

    INSERT INTO events (
        dataset_id, external_id, title, event_type, occurred_at, ended_at,
        source_updated_at, longitude, latitude, geometry, magnitude,
        magnitude_unit, attributes, url, ingested_at
    )
    SELECT
        dataset_id, external_id, place, event_type, occurred_at, NULL,
        source_updated_at, longitude, latitude, NULL, magnitude,
        magnitude_type,
        jsonb_strip_nulls(jsonb_build_object(
            'depth_km', depth_km,
            'tsunami', tsunami,
            'significance', significance
        )),
        url, ingested_at
    FROM earthquakes
    ORDER BY id;

    DROP TABLE earthquakes;
END
$$;
