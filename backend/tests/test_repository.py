"""Repository queries, against a real database."""

from datetime import datetime

import pytest

from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def make_record(external_id="eq1", **overrides):
    record = {
        "external_id": external_id,
        "magnitude": 1.4,
        "magnitude_type": "ml",
        "place": "somewhere",
        "event_type": "earthquake",
        "occurred_at": datetime(2026, 9, 9, 8, 0, 0),
        "source_updated_at": None,
        "longitude": -101.696,
        "latitude": 31.715,
        "depth_km": 2.5,
        "tsunami": False,
        "significance": 30,
        "url": "https://example.invalid/eq1",
    }
    record.update(overrides)
    return record


class TestUpsertEarthquakes:
    def test_new_events_are_counted_as_inserted(self, db, dataset):
        with db() as connection:
            inserted, updated = repository.upsert_earthquakes(
                connection, dataset["id"], [make_record("a"), make_record("b")]
            )

        assert (inserted, updated) == (2, 0)

    def test_re_running_updates_instead_of_duplicating(self, db, dataset):
        """This is what makes an ingestion safe to repeat."""
        records = [make_record("a"), make_record("b")]
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], records)
        with db() as connection:
            inserted, updated = repository.upsert_earthquakes(
                connection, dataset["id"], records
            )

        assert (inserted, updated) == (0, 2)
        with db() as connection:
            assert repository.count_earthquakes(connection, dataset["id"]) == 2

    def test_changed_values_are_refreshed(self, db, dataset):
        with db() as connection:
            repository.upsert_earthquakes(
                connection, dataset["id"], [make_record("a", magnitude=1.4)]
            )
        with db() as connection:
            repository.upsert_earthquakes(
                connection, dataset["id"], [make_record("a", magnitude=5.9)]
            )
        with db() as connection:
            stored = repository.list_earthquakes(connection, dataset["id"], 10, 0)

        assert stored[0]["magnitude"] == 5.9

    def test_an_empty_batch_writes_nothing(self, db, dataset):
        with db() as connection:
            assert repository.upsert_earthquakes(connection, dataset["id"], []) == (
                0,
                0,
            )

    def test_a_null_magnitude_is_stored(self, db, dataset):
        with db() as connection:
            repository.upsert_earthquakes(
                connection, dataset["id"], [make_record("a", magnitude=None)]
            )
        with db() as connection:
            assert (
                repository.list_earthquakes(connection, dataset["id"], 10, 0)[0][
                    "magnitude"
                ]
                is None
            )

    def test_numeric_columns_come_back_as_floats(self, db, dataset):
        """Decimal would leak the database type into the API response."""
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], [make_record()])
        with db() as connection:
            stored = repository.list_earthquakes(connection, dataset["id"], 10, 0)[0]

        for field in ("magnitude", "longitude", "latitude", "depth_km"):
            assert isinstance(stored[field], float)


class TestListEarthquakes:
    def _seed(self, db, dataset, count):
        records = [
            make_record(
                "eq{0}".format(index),
                occurred_at=datetime(2026, 9, 9, 8, index, 0),
            )
            for index in range(count)
        ]
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], records)

    def test_most_recent_first(self, db, dataset):
        self._seed(db, dataset, 3)

        with db() as connection:
            stored = repository.list_earthquakes(connection, dataset["id"], 10, 0)

        times = [row["occurred_at"] for row in stored]
        assert times == sorted(times, reverse=True)

    def test_limit_and_offset_walk_the_table(self, db, dataset):
        self._seed(db, dataset, 5)

        with db() as connection:
            first = repository.list_earthquakes(connection, dataset["id"], 2, 0)
            second = repository.list_earthquakes(connection, dataset["id"], 2, 2)

        assert len(first) == len(second) == 2
        assert not {r["external_id"] for r in first} & {
            r["external_id"] for r in second
        }

    def test_another_dataset_does_not_leak_in(self, db, dataset):
        self._seed(db, dataset, 2)
        with db() as connection:
            other = repository.create_dataset(connection, "Other", "USGS", None)

        with db() as connection:
            assert repository.list_earthquakes(connection, other["id"], 10, 0) == []


class TestImportLifecycle:
    def test_a_new_run_starts_queued(self, db, dataset):
        with db() as connection:
            import_id = repository.create_import(
                connection, dataset["id"], "https://example.invalid/feed"
            )
        with db() as connection:
            run = repository.get_import(connection, import_id)

        assert run["status"] == "queued"
        assert run["feed_url"] == "https://example.invalid/feed"

    def test_starting_a_run_stamps_started_at(self, db, dataset):
        with db() as connection:
            import_id = repository.create_import(connection, dataset["id"], "url")
        with db() as connection:
            repository.start_import(connection, import_id)
        with db() as connection:
            run = repository.list_imports(connection, dataset["id"], 10, 0)[0]

        assert run["status"] == "processing"
        assert run["started_at"] is not None
        assert run["finished_at"] is None

    def test_completing_a_run_records_the_counts(self, db, dataset):
        with db() as connection:
            import_id = repository.create_import(connection, dataset["id"], "url")
        with db() as connection:
            repository.complete_import(
                connection,
                import_id,
                fetched=10,
                valid=9,
                invalid=1,
                inserted=7,
                updated=2,
                invalid_sample="eq1: bad",
            )
        with db() as connection:
            run = repository.list_imports(connection, dataset["id"], 10, 0)[0]

        assert run["status"] == "completed"
        assert (run["fetched"], run["valid"], run["invalid"]) == (10, 9, 1)
        assert (run["inserted"], run["updated"]) == (7, 2)
        assert run["invalid_sample"] == "eq1: bad"
        assert run["finished_at"] is not None

    def test_failing_a_run_records_the_reason(self, db, dataset):
        with db() as connection:
            import_id = repository.create_import(connection, dataset["id"], "url")
        with db() as connection:
            repository.fail_import(connection, import_id, "feed unreachable")
        with db() as connection:
            run = repository.list_imports(connection, dataset["id"], 10, 0)[0]

        assert run["status"] == "failed"
        assert run["error"] == "feed unreachable"
        assert run["finished_at"] is not None

    def test_an_unknown_run_is_none(self, db):
        with db() as connection:
            assert repository.get_import(connection, 999) is None


class TestCascade:
    def test_deleting_a_dataset_removes_its_rows(self, db, dataset):
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], [make_record()])
            repository.create_import(connection, dataset["id"], "url")

        with db() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM datasets WHERE id = %s", (dataset["id"],))

        with db() as connection:
            assert repository.count_earthquakes(connection, dataset["id"]) == 0
            assert repository.count_imports(connection, dataset["id"]) == 0
