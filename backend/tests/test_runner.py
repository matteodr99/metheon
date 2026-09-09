"""The worker's job: one import run, end to end.

The feed is replaced, so this exercises the whole path — status transitions,
storage, counts, failure recording — without the network.
"""

import pytest

from app.db import repository
from app.ingestion import runner, usgs
from tests.conftest import make_feature, requires_postgres

pytestmark = requires_postgres


@pytest.fixture
def queued_run(db, dataset):
    """A dataset with one queued import, ready to be executed."""
    with db() as connection:
        import_id = repository.create_import(
            connection, dataset["id"], "https://example.invalid/feed.geojson"
        )
    return {"import_id": import_id, "dataset_id": dataset["id"]}


@pytest.fixture
def feed(monkeypatch):
    """Install a payload for fetch_feed to return, or an error to raise."""

    def install(features=None, error=None):
        def _fetch(url=None, timeout=None):
            if error is not None:
                raise error
            return {"type": "FeatureCollection", "features": features or []}

        monkeypatch.setattr(usgs, "fetch_feed", _fetch)

    return install


class TestSuccessfulRun:
    def test_events_are_stored_and_counted(self, db, queued_run, feed):
        feed([make_feature(id="a"), make_feature(id="b")])

        result = runner.run_import(queued_run["import_id"])

        assert (result["fetched"], result["valid"]) == (2, 2)
        assert (result["inserted"], result["updated"]) == (2, 0)
        with db() as connection:
            assert repository.count_earthquakes(connection, queued_run["dataset_id"]) == 2

    def test_the_run_is_marked_completed(self, db, queued_run, feed):
        feed([make_feature(id="a")])

        runner.run_import(queued_run["import_id"])

        with db() as connection:
            run = repository.list_imports(connection, queued_run["dataset_id"], 10, 0)[0]
        assert run["status"] == "completed"
        assert run["started_at"] is not None
        assert run["finished_at"] is not None

    def test_the_dataset_is_marked_completed(self, db, queued_run, feed):
        feed([make_feature(id="a")])

        runner.run_import(queued_run["import_id"])

        with db() as connection:
            dataset = repository.get_dataset(connection, queued_run["dataset_id"])
        assert dataset["status"] == "completed"

    def test_running_twice_updates_rather_than_duplicates(self, db, queued_run, feed):
        feed([make_feature(id="a")])
        runner.run_import(queued_run["import_id"])

        with db() as connection:
            second = repository.create_import(
                connection, queued_run["dataset_id"], "url"
            )
        result = runner.run_import(second)

        assert (result["inserted"], result["updated"]) == (0, 1)
        with db() as connection:
            assert repository.count_earthquakes(connection, queued_run["dataset_id"]) == 1

    def test_invalid_features_are_counted_and_sampled(self, db, queued_run, feed):
        """A completed run with rejections must still say why."""
        feed([make_feature(id="good"), {"id": "bad", "properties": {}, "geometry": {}}])

        result = runner.run_import(queued_run["import_id"])

        assert (result["valid"], result["invalid"]) == (1, 1)
        with db() as connection:
            run = repository.list_imports(connection, queued_run["dataset_id"], 10, 0)[0]
        assert run["status"] == "completed"
        assert "bad" in run["invalid_sample"]

    def test_an_empty_feed_completes_with_zero_counts(self, db, queued_run, feed):
        feed([])

        result = runner.run_import(queued_run["import_id"])

        assert (result["fetched"], result["inserted"]) == (0, 0)
        with db() as connection:
            run = repository.list_imports(connection, queued_run["dataset_id"], 10, 0)[0]
        assert run["status"] == "completed"


class TestFailedRun:
    def test_a_feed_error_marks_the_run_failed(self, db, queued_run, feed):
        feed(error=usgs.IngestionError("feed unreachable"))

        with pytest.raises(usgs.IngestionError):
            runner.run_import(queued_run["import_id"])

        with db() as connection:
            run = repository.list_imports(connection, queued_run["dataset_id"], 10, 0)[0]
        assert run["status"] == "failed"
        assert run["error"] == "feed unreachable"

    def test_a_feed_error_marks_the_dataset_failed(self, db, queued_run, feed):
        feed(error=usgs.IngestionError("feed unreachable"))

        with pytest.raises(usgs.IngestionError):
            runner.run_import(queued_run["import_id"])

        with db() as connection:
            dataset = repository.get_dataset(connection, queued_run["dataset_id"])
        assert dataset["status"] == "failed"

    def test_a_failed_run_stores_nothing(self, db, queued_run, feed):
        feed(error=usgs.IngestionError("feed unreachable"))

        with pytest.raises(usgs.IngestionError):
            runner.run_import(queued_run["import_id"])

        with db() as connection:
            assert repository.count_earthquakes(connection, queued_run["dataset_id"]) == 0

    def test_an_unexpected_error_is_also_recorded(self, db, queued_run, feed):
        feed(error=ValueError("something else"))

        with pytest.raises(ValueError):
            runner.run_import(queued_run["import_id"])

        with db() as connection:
            run = repository.list_imports(connection, queued_run["dataset_id"], 10, 0)[0]
        assert run["status"] == "failed"
        assert "something else" in run["error"]

    def test_an_unknown_import_id_raises(self, db):
        with pytest.raises(runner.UnknownImport):
            runner.run_import(999)


class TestFeedUrlComesFromTheRun:
    def test_the_stored_url_is_used_not_the_default(self, db, dataset, monkeypatch):
        """Changing the default between queueing and running must not matter."""
        with db() as connection:
            import_id = repository.create_import(
                connection, dataset["id"], "https://recorded.invalid/feed.geojson"
            )

        used = {}

        def _fetch(url=None, timeout=None):
            used["url"] = url
            return {"type": "FeatureCollection", "features": []}

        monkeypatch.setattr(usgs, "fetch_feed", _fetch)
        runner.run_import(import_id)

        assert used["url"] == "https://recorded.invalid/feed.geojson"
