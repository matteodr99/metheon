"""The migration runner, and the one migration there is.

The suite's database is built from init.sql, the final schema, so the
migration is a no-op there. To test what it does to a database with data,
one test rebuilds the schema as it was and lets apply_schema bring it up.
"""

import os
from datetime import datetime

import pytest

from app.db import apply_schema as runner
from app.db.database import get_connection
from tests.conftest import FIXTURES_DIR, requires_postgres

pytestmark = requires_postgres

BEFORE = os.path.join(FIXTURES_DIR, "schema_before_events.sql")


def tables(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT string_agg(tablename, ',' ORDER BY tablename) "
            "FROM pg_tables WHERE schemaname = 'public'"
        )
        return cursor.fetchone()[0]


@pytest.fixture
def old_schema(db):
    """Tear the test database down to the schema before `events`, with rows."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS events, imports, datasets, schema_migrations CASCADE")
            with open(BEFORE, encoding="utf-8") as handle:
                cursor.execute(handle.read())
            cursor.execute(
                "INSERT INTO datasets (name, source) VALUES ('Global Earthquakes', 'USGS') RETURNING id"
            )
            dataset_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO earthquakes (dataset_id, external_id, magnitude, magnitude_type, place,
                    event_type, occurred_at, source_updated_at, longitude, latitude, depth_km,
                    tsunami, significance, url)
                VALUES
                    (%s, 'a', 5.6, 'mww', 'Isangel, Vanuatu', 'earthquake', %s, %s,
                     169.98, -19.85, 10.0, TRUE, 480, 'https://x.invalid/a'),
                    (%s, 'b', NULL, NULL, NULL, 'quarry blast', %s, NULL,
                     -117.5, 34.1, NULL, FALSE, NULL, NULL)
                """,
                (dataset_id, datetime(2026, 9, 10, 3, 11, 52), datetime(2026, 9, 10, 4, 0),
                 dataset_id, datetime(2026, 9, 11, 9, 0)),
            )
            cursor.execute("INSERT INTO imports (dataset_id, feed_url) VALUES (%s, 'https://x.invalid/feed')", (dataset_id,))
    yield dataset_id
    # Back to the final schema for whatever runs next: apply_schema does it.
    runner.apply_schema()


class TestTheEventsMigration:
    def test_it_moves_every_earthquake_into_events(self, old_schema):
        applied = runner.apply_schema()

        assert applied == [1]
        with get_connection() as connection:
            assert tables(connection) == "datasets,events,imports,schema_migrations"
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM events WHERE dataset_id = %s", (old_schema,))
                assert cursor.fetchone()[0] == 2

    def test_the_seismic_columns_become_attributes(self, old_schema):
        runner.apply_schema()

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT title, magnitude, magnitude_unit, attributes, url, event_type, source_updated_at "
                "FROM events WHERE external_id = 'a'"
            )
            title, magnitude, unit, attributes, url, event_type, updated = cursor.fetchone()

        assert title == "Isangel, Vanuatu"
        assert float(magnitude) == 5.6
        assert unit == "mww"
        assert attributes == {"depth_km": 10.0, "tsunami": True, "significance": 480}
        assert url == "https://x.invalid/a"
        assert event_type == "earthquake"
        assert updated == datetime(2026, 9, 10, 4, 0)

    def test_nulls_are_not_written_into_attributes(self, old_schema):
        """A key with a null value would show up as "depth: null" everywhere
        the attributes are displayed; absent is the honest shape."""
        runner.apply_schema()

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT attributes, magnitude_unit FROM events WHERE external_id = 'b'")
            attributes, unit = cursor.fetchone()

        assert attributes == {"tsunami": False}
        assert unit is None

    def test_the_dataset_gets_the_earthquake_kind(self, old_schema):
        runner.apply_schema()

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT kind FROM datasets WHERE id = %s", (old_schema,))
            assert cursor.fetchone()[0] == "earthquake"

    def test_the_import_history_survives(self, old_schema):
        runner.apply_schema()

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM imports WHERE dataset_id = %s", (old_schema,))
            assert cursor.fetchone()[0] == 1

    def test_it_runs_once(self, old_schema):
        assert runner.apply_schema() == [1]
        assert runner.apply_schema() == []

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations")
            assert [row[0] for row in cursor.fetchall()] == [1]


class TestTheRunner:
    def test_a_fresh_database_needs_no_migration_but_records_it(self, db):
        """The test database came from init.sql: the migration finds no
        `earthquakes` table, does nothing, and is still marked as applied so
        it never runs again."""
        runner.apply_schema()

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations")
            assert [row[0] for row in cursor.fetchall()] == [1]
            assert tables(connection) == "datasets,events,imports,schema_migrations"

    def test_migrations_are_listed_in_version_order(self, tmp_path):
        for name in ("010_late.sql", "002_second.sql", "notes.txt", "001_first.sql", "1_bad.sql"):
            (tmp_path / name).write_text("SELECT 1")

        listed = runner.list_migrations(str(tmp_path))

        assert [version for version, _ in listed] == [1, 2, 10]

    def test_a_failing_migration_is_not_recorded(self, db, tmp_path):
        (tmp_path / "099_broken.sql").write_text("SELECT * FROM no_such_table")

        with pytest.raises(Exception):
            runner.apply_schema(str(tmp_path))

        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM schema_migrations WHERE version = 99")
            assert cursor.fetchone()[0] == 0
