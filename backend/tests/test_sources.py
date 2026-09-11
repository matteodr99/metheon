"""The source registry, and how the pipeline dispatches through it."""

import types

import pytest

from app.db import repository
from app.ingestion import IngestionError, runner, sources
from tests.conftest import make_feature, requires_postgres


def fake_source_module(features=None, error=None, feed_url="https://fake.invalid/feed"):
    """A module-shaped object honouring the source contract."""
    calls = {"fetch": [], "normalize": 0}

    def fetch_feed(url=None, timeout=None):
        calls["fetch"].append(url)
        if error is not None:
            raise error
        return {"type": "FeatureCollection", "features": features or []}

    def normalize_feed(payload):
        calls["normalize"] += 1
        # Reuse the USGS normalizer: the contract is about shape, not origin.
        from app.ingestion import usgs

        return usgs.normalize_feed(payload)

    module = types.SimpleNamespace(
        DEFAULT_FEED_URL=feed_url,
        fetch_feed=fetch_feed,
        normalize_feed=normalize_feed,
    )
    return module, calls


@pytest.fixture
def registered(monkeypatch):
    """Register a fake source under the key 'fake' for the test's duration."""

    def register(**kwargs):
        module, calls = fake_source_module(**kwargs)
        monkeypatch.setitem(
            sources.SOURCES, "fake", sources.Source("fake", "A fake source", module)
        )
        return calls

    return register


class TestRegistry:
    def test_the_usgs_source_is_known(self):
        assert sources.get_source("usgs") is not None

    @pytest.mark.parametrize("spelling", ["USGS", "Usgs", " usgs ", "usgs"])
    def test_lookup_ignores_case_and_whitespace(self, spelling):
        """Datasets created before the registry say 'USGS'."""
        assert sources.get_source(spelling).key == "usgs"

    def test_an_unknown_source_is_none(self):
        assert sources.get_source("meteorites") is None

    def test_known_sources_are_listed_in_order(self, registered):
        registered()

        listed = sources.known_sources()
        assert listed == sorted(listed)
        assert "fake" in listed
        assert "usgs" in listed

    def test_functions_are_resolved_at_call_time(self, monkeypatch):
        """Replacing a function on the module must reach the pipeline."""
        from app.ingestion import usgs

        seen = {}
        monkeypatch.setattr(
            usgs, "fetch_feed", lambda url=None, timeout=None: seen.setdefault("url", url) or {}
        )

        sources.get_source("usgs").fetch_feed(url="https://x.invalid")

        assert seen["url"] == "https://x.invalid"

    def test_default_feed_url_comes_from_the_module(self):
        from app.ingestion import usgs

        assert sources.get_source("usgs").default_feed_url == usgs.DEFAULT_FEED_URL


@requires_postgres
class TestCreatingDatasets:
    def test_a_known_source_is_accepted(self, client):
        response = client.post(
            "/api/datasets", json={"name": "Quakes", "source": "usgs"}
        )

        assert response.status_code == 200

    def test_the_historical_spelling_is_accepted(self, client):
        response = client.post(
            "/api/datasets", json={"name": "Quakes", "source": "USGS"}
        )

        assert response.status_code == 200

    def test_an_unknown_source_is_refused_with_the_known_ones(self, client):
        """Refusing here beats accepting a dataset that can never import."""
        response = client.post(
            "/api/datasets", json={"name": "Rocks", "source": "meteorites"}
        )

        assert response.status_code == 422
        assert "meteorites" in response.json()["detail"]
        assert "usgs" in response.json()["detail"]

    def test_the_sources_endpoint_lists_what_can_be_created(self, client):
        body = client.get("/api/sources").json()

        keys = [entry["key"] for entry in body]
        assert "usgs" in keys
        usgs_entry = next(entry for entry in body if entry["key"] == "usgs")
        assert usgs_entry["default_feed_url"].startswith("https://")
        assert usgs_entry["name"]


@requires_postgres
class TestDispatch:
    def test_the_runner_uses_the_dataset_source(self, db, registered):
        calls = registered(features=[make_feature(id="from-fake")])
        with db() as connection:
            dataset = repository.create_dataset(connection, "Fake", "fake", None)
            import_id = repository.create_import(
                connection, dataset["id"], "https://fake.invalid/feed"
            )

        result = runner.run_import(import_id)

        assert calls["fetch"] == ["https://fake.invalid/feed"]
        assert calls["normalize"] == 1
        assert result["inserted"] == 1

    def test_the_ingest_endpoint_queues_the_source_default_feed(
        self, client, registered
    ):
        registered(feed_url="https://fake.invalid/default.geojson")
        dataset = client.post(
            "/api/datasets", json={"name": "Fake", "source": "fake"}
        ).json()

        body = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()

        assert body["feed_url"] == "https://fake.invalid/default.geojson"

    def test_a_source_error_is_recorded_whichever_source_raised_it(
        self, db, registered
    ):
        registered(error=IngestionError("fake feed down"))
        with db() as connection:
            dataset = repository.create_dataset(connection, "Fake", "fake", None)
            import_id = repository.create_import(connection, dataset["id"], "url")

        with pytest.raises(IngestionError):
            runner.run_import(import_id)

        with db() as connection:
            run = repository.list_imports(connection, dataset["id"], 10, 0)[0]
        assert run["status"] == "failed"
        assert run["error"] == "fake feed down"


@requires_postgres
class TestUnknownSourceAtRunTime:
    """A dataset can predate validation, or a source can be removed."""

    def _dataset_with_unknown_source(self, db):
        with db() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO datasets (name, source) VALUES ('Old', 'gone') RETURNING id"
                )
                dataset_id = cursor.fetchone()[0]
        return dataset_id

    def test_the_runner_records_the_failure(self, db):
        dataset_id = self._dataset_with_unknown_source(db)
        with db() as connection:
            import_id = repository.create_import(connection, dataset_id, "url")

        with pytest.raises(runner.UnknownSource):
            runner.run_import(import_id)

        with db() as connection:
            run = repository.list_imports(connection, dataset_id, 10, 0)[0]
            dataset = repository.get_dataset(connection, dataset_id)
        assert run["status"] == "failed"
        assert "gone" in run["error"]
        assert dataset["status"] == "failed"

    def test_the_ingest_endpoint_refuses_before_queueing(self, client, db, fake_queue):
        dataset_id = self._dataset_with_unknown_source(db)

        response = client.post("/api/datasets/{0}/ingest".format(dataset_id))

        assert response.status_code == 422
        assert fake_queue.enqueued == []
