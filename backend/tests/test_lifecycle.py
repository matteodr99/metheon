"""Deleting a dataset, the ingestion cooldown, and when data last arrived."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db import repository
from tests.conftest import make_feature, requires_postgres

pytestmark = requires_postgres


@pytest.fixture
def feed(monkeypatch):
    from app.ingestion import usgs

    monkeypatch.setattr(
        usgs, "fetch_feed",
        lambda url=None, timeout=None, kind=None: {"type": "FeatureCollection", "features": [make_feature(id="a")]},
    )


class TestDelete:
    def test_it_removes_the_dataset_its_events_and_its_history(self, client, db, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200

        response = client.delete("/api/datasets/{0}".format(dataset["id"]))

        assert response.status_code == 204
        assert response.content == b""
        assert client.get("/api/datasets/{0}".format(dataset["id"])).status_code in (404, 405)
        assert client.get("/api/datasets/{0}/events".format(dataset["id"])).status_code == 404
        assert client.get("/api/datasets/{0}/imports".format(dataset["id"])).status_code == 404
        with db() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM events WHERE dataset_id = %s", (dataset["id"],))
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM imports WHERE dataset_id = %s", (dataset["id"],))
            assert cursor.fetchone()[0] == 0

    def test_it_leaves_other_datasets_alone(self, client, db, dataset):
        with db() as connection:
            other = repository.create_dataset(connection, "Other", "ingv", None)
            repository.upsert_events(connection, other["id"], [{
                "external_id": "x", "title": "t", "event_type": "earthquake",
                "occurred_at": datetime(2026, 9, 1), "source_updated_at": None,
                "longitude": 0.0, "latitude": 0.0, "magnitude": 1.0, "magnitude_unit": "ml", "url": None,
            }])

        client.delete("/api/datasets/{0}".format(dataset["id"]))

        assert [d["id"] for d in client.get("/api/datasets").json()] == [other["id"]]
        with db() as connection:
            assert repository.count_events(connection, other["id"]) == 1

    def test_an_unknown_dataset_is_404(self, client):
        assert client.delete("/api/datasets/999999").status_code == 404

    def test_it_is_logged(self, client, dataset, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="app.api"):
            client.delete("/api/datasets/{0}".format(dataset["id"]))

        assert any("deleted dataset {0}".format(dataset["id"]) == r.getMessage() for r in caplog.records)


class TestCooldown:
    def test_a_second_ingestion_right_after_the_first_is_refused(self, client, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "10")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200

        refused = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert refused.status_code == 429
        assert "try again in" in refused.json()["detail"]
        assert 0 < int(refused.headers["Retry-After"]) <= 601

    def test_it_lifts_once_the_cooldown_has_passed(self, client, db, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "10")
        first = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()
        with db() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE imports SET finished_at = %s WHERE id = %s",
                (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=11), first["id"]),
            )

        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200

    def test_zero_disables_it(self, client, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "0")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200

    def test_a_failed_run_does_not_count(self, client, dataset, monkeypatch):
        """Retrying a failure is what a person does next; refusing it would
        only make them wait for nothing."""
        from app.ingestion import IngestionError, usgs

        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "10")

        def broken(url=None, timeout=None, kind=None):
            raise IngestionError("feed down")

        monkeypatch.setattr(usgs, "fetch_feed", broken)
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 502

        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 502

    def test_a_run_in_flight_is_refused_whatever_the_cooldown(self, client, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "queue")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "0")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 202

        refused = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert refused.status_code == 429
        assert "in flight" in refused.json()["detail"]
        assert refused.headers["Retry-After"] == "60"

    @pytest.mark.parametrize("raw", ["ten", "-1", "1.5"])
    def test_a_bad_setting_is_refused_loudly(self, raw, monkeypatch):
        from app import settings

        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", raw)
        with pytest.raises(RuntimeError):
            settings.ingest_cooldown_minutes()

    def test_the_setting_is_read_per_request(self, client, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "10")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 429

        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "0")
        assert client.post("/api/datasets/{0}/ingest".format(dataset["id"])).status_code == 200


class TestLastIngestedAt:
    def test_it_is_null_until_a_run_completes(self, client, dataset):
        listed = client.get("/api/datasets").json()[0]
        assert listed["last_ingested_at"] is None

    def test_it_is_the_finish_of_the_latest_completed_run(self, client, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "0")
        run = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()

        listed = client.get("/api/datasets").json()[0]

        assert listed["last_ingested_at"] == run["finished_at"]

    def test_a_failed_run_after_a_completed_one_does_not_move_it(self, client, db, dataset, feed, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        monkeypatch.setenv("INGEST_COOLDOWN_MINUTES", "0")
        run = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()
        with db() as connection:
            failed = repository.create_import(connection, dataset["id"], "https://x.invalid")
            repository.fail_import(connection, failed, "boom")

        listed = client.get("/api/datasets").json()[0]

        assert listed["last_ingested_at"] == run["finished_at"]
