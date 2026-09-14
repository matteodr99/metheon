"""Old events are swept away with each ingestion, per RETENTION_DAYS."""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from app import settings
from app.db import repository
from app.ingestion import runner
from tests.conftest import make_feature, requires_postgres

pytestmark = requires_postgres

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def record(external_id, days_ago):
    return {
        "external_id": external_id, "title": external_id, "event_type": "earthquake",
        "occurred_at": NOW - timedelta(days=days_ago), "source_updated_at": None,
        "longitude": 0.0, "latitude": 0.0, "magnitude": 1.0, "magnitude_unit": "ml", "url": None,
    }


class TestTheSetting:
    def test_it_defaults_to_a_year(self, monkeypatch):
        monkeypatch.delenv("RETENTION_DAYS", raising=False)
        assert settings.retention_days() == 365

    @pytest.mark.parametrize("raw", ["forever", "-1", "1.5"])
    def test_a_bad_value_is_refused_loudly(self, raw, monkeypatch):
        monkeypatch.setenv("RETENTION_DAYS", raw)
        with pytest.raises(RuntimeError):
            settings.retention_days()


class TestPrune:
    def test_it_removes_only_what_is_older_and_only_in_that_dataset(self, db, dataset):
        with db() as connection:
            other = repository.create_dataset(connection, "Other", "ingv", None)
            repository.upsert_events(connection, dataset["id"], [record("old", 400), record("recent", 10)])
            repository.upsert_events(connection, other["id"], [record("old", 400)])

        with db() as connection:
            pruned = repository.prune_events(connection, dataset["id"], NOW - timedelta(days=365))

        assert pruned == 1
        with db() as connection:
            kept = [e["external_id"] for e in repository.list_events(connection, dataset["id"], 10, 0)]
            assert kept == ["recent"]
            assert repository.count_events(connection, other["id"]) == 1

    def test_it_goes_by_when_the_event_happened_not_when_it_arrived(self, db, dataset):
        """An old event re-sent by a feed is still old."""
        with db() as connection:
            repository.upsert_events(connection, dataset["id"], [record("old-but-fresh", 400)])

        with db() as connection:
            assert repository.prune_events(connection, dataset["id"], NOW - timedelta(days=365)) == 1


class TestWithTheIngestion:
    @pytest.fixture
    def feed(self, monkeypatch):
        from app.ingestion import usgs

        monkeypatch.setattr(
            usgs, "fetch_feed",
            lambda url=None, timeout=None, kind=None: {"type": "FeatureCollection", "features": [make_feature(id="fresh")]},
        )

    def test_a_run_sweeps_its_dataset_and_says_so(self, db, dataset, feed, monkeypatch, caplog):
        monkeypatch.setenv("RETENTION_DAYS", "30")
        with db() as connection:
            repository.upsert_events(connection, dataset["id"], [record("stale", 31), record("kept", 29)])
            import_id = repository.create_import(connection, dataset["id"], "https://x.invalid")

        with caplog.at_level(logging.INFO, logger="app.ingestion.runner"):
            result = runner.run_import(import_id)

        assert result["inserted"] == 1
        with db() as connection:
            ids = sorted(e["external_id"] for e in repository.list_events(connection, dataset["id"], 10, 0))
        assert ids == ["fresh", "kept"]
        assert any("pruned 1 events" in r.getMessage() for r in caplog.records)

    def test_zero_keeps_everything(self, db, dataset, feed, monkeypatch):
        monkeypatch.setenv("RETENTION_DAYS", "0")
        with db() as connection:
            repository.upsert_events(connection, dataset["id"], [record("ancient", 4000)])
            import_id = repository.create_import(connection, dataset["id"], "https://x.invalid")

        runner.run_import(import_id)

        with db() as connection:
            assert repository.count_events(connection, dataset["id"]) == 2

    def test_nothing_to_prune_is_not_logged(self, db, dataset, feed, monkeypatch, caplog):
        monkeypatch.setenv("RETENTION_DAYS", "365")
        with db() as connection:
            import_id = repository.create_import(connection, dataset["id"], "https://x.invalid")

        with caplog.at_level(logging.INFO, logger="app.ingestion.runner"):
            runner.run_import(import_id)

        assert not any("pruned" in r.getMessage() for r in caplog.records)
