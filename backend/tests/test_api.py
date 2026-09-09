"""The HTTP API, against a real database and a fake queue.

Skipped when PostgreSQL is not reachable.
"""

import pytest

from tests.conftest import requires_postgres

pytestmark = requires_postgres


class TestHealth:
    def test_health_reports_both_dependencies(self, client):
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "metheon",
            "database": True,
            "queue": True,
        }

    def test_health_is_degraded_when_the_queue_is_down(self, client, fake_queue):
        fake_queue.fail_with = RuntimeError("redis down")

        body = client.get("/api/health").json()

        assert body["status"] == "degraded"
        assert body["database"] is True
        assert body["queue"] is False


class TestListAndCreateDatasets:
    def test_an_empty_database_returns_an_empty_list(self, client):
        assert client.get("/api/datasets").json() == []

    def test_a_created_dataset_comes_back(self, client):
        created = client.post(
            "/api/datasets",
            json={"name": "Quakes", "source": "USGS", "description": "d"},
        ).json()

        assert created["id"] > 0
        assert created["name"] == "Quakes"
        assert client.get("/api/datasets").json() == [created]

    def test_a_new_dataset_starts_as_pending(self, client):
        created = client.post(
            "/api/datasets", json={"name": "Quakes", "source": "USGS"}
        ).json()

        assert created["status"] == "pending"

    def test_description_is_optional(self, client):
        response = client.post(
            "/api/datasets", json={"name": "Quakes", "source": "USGS"}
        )

        assert response.status_code == 200
        assert response.json()["description"] is None

    @pytest.mark.parametrize(
        "payload",
        [{}, {"name": "Quakes"}, {"source": "USGS"}],
    )
    def test_name_and_source_are_required(self, client, payload):
        assert client.post("/api/datasets", json=payload).status_code == 422

    def test_a_client_supplied_status_is_ignored(self, client):
        """The client must not be able to choose the initial import state."""
        created = client.post(
            "/api/datasets",
            json={"name": "Quakes", "source": "USGS", "status": "completed"},
        ).json()

        assert created["status"] == "pending"

    def test_datasets_are_ordered_by_id(self, client):
        for name in ("a", "b", "c"):
            client.post("/api/datasets", json={"name": name, "source": "USGS"})

        ids = [d["id"] for d in client.get("/api/datasets").json()]

        assert ids == sorted(ids)


class TestIngestEndpoint:
    def test_a_run_is_queued_and_returns_202(self, client, dataset, fake_queue):
        response = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["dataset_id"] == dataset["id"]
        assert fake_queue.enqueued == [body["import_id"]]

    def test_the_dataset_moves_to_queued(self, client, dataset):
        client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert client.get("/api/datasets").json()[0]["status"] == "queued"

    def test_the_run_appears_in_the_history(self, client, dataset):
        body = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()

        history = client.get(
            "/api/datasets/{0}/imports".format(dataset["id"])
        ).json()

        assert history["total"] == 1
        run = history["items"][0]
        assert run["id"] == body["import_id"]
        assert run["status"] == "queued"
        assert run["started_at"] is None

    def test_an_unknown_dataset_returns_404(self, client):
        assert client.post("/api/datasets/999/ingest").status_code == 404

    def test_a_queue_outage_returns_503(self, client, dataset, fake_queue):
        from app import jobs

        fake_queue.fail_with = jobs.QueueError("redis down")

        response = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert response.status_code == 503

    def test_a_queue_outage_is_still_recorded_in_the_history(
        self, client, dataset, fake_queue
    ):
        """An outage must be visible, not silently swallowed."""
        from app import jobs

        fake_queue.fail_with = jobs.QueueError("redis down")
        client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        fake_queue.fail_with = None
        run = client.get("/api/datasets/{0}/imports".format(dataset["id"])).json()[
            "items"
        ][0]

        assert run["status"] == "failed"
        assert "redis down" in run["error"]
        assert client.get("/api/datasets").json()[0]["status"] == "failed"


class TestEarthquakesEndpoint:
    def test_a_dataset_without_events_returns_an_empty_page(self, client, dataset):
        body = client.get(
            "/api/datasets/{0}/earthquakes".format(dataset["id"])
        ).json()

        assert body["total"] == 0
        assert body["items"] == []

    def test_an_unknown_dataset_returns_404(self, client):
        assert client.get("/api/datasets/999/earthquakes").status_code == 404

    @pytest.mark.parametrize(
        "query", ["limit=0", "limit=501", "offset=-1", "limit=abc"]
    )
    def test_out_of_range_parameters_are_rejected(self, client, dataset, query):
        response = client.get(
            "/api/datasets/{0}/earthquakes?{1}".format(dataset["id"], query)
        )

        assert response.status_code == 422

    def test_the_default_page_size_is_reported(self, client, dataset):
        body = client.get(
            "/api/datasets/{0}/earthquakes".format(dataset["id"])
        ).json()

        assert body["limit"] == 50
        assert body["offset"] == 0


class TestImportsEndpoint:
    def test_a_dataset_without_runs_returns_an_empty_page(self, client, dataset):
        body = client.get("/api/datasets/{0}/imports".format(dataset["id"])).json()

        assert body["total"] == 0
        assert body["items"] == []

    def test_an_unknown_dataset_returns_404(self, client):
        assert client.get("/api/datasets/999/imports").status_code == 404

    def test_runs_are_returned_most_recent_first(self, client, dataset):
        for _ in range(3):
            client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        ids = [
            run["id"]
            for run in client.get(
                "/api/datasets/{0}/imports".format(dataset["id"])
            ).json()["items"]
        ]

        assert ids == sorted(ids, reverse=True)

    def test_pages_do_not_overlap(self, client, dataset):
        for _ in range(4):
            client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        url = "/api/datasets/{0}/imports".format(dataset["id"])
        first = client.get(url + "?limit=2&offset=0").json()["items"]
        second = client.get(url + "?limit=2&offset=2").json()["items"]

        assert not {r["id"] for r in first} & {r["id"] for r in second}

    def test_an_offset_past_the_end_returns_an_empty_page(self, client, dataset):
        client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        body = client.get(
            "/api/datasets/{0}/imports?offset=99".format(dataset["id"])
        ).json()

        assert body["total"] == 1
        assert body["items"] == []
