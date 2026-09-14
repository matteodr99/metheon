"""The settings a deployment turns on, and that development leaves off.

Every default here reproduces the behaviour the project had before these
settings existed; each test that flips one checks both sides.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import settings
from app.db import repository
from app.db.database import get_database_url
from app.ingestion import usgs
from tests.conftest import make_feature, requires_postgres


class TestIngestionMode:
    def test_the_default_is_queue(self, monkeypatch):
        monkeypatch.delenv("INGESTION_MODE", raising=False)

        assert settings.ingestion_mode() == "queue"

    @pytest.mark.parametrize("raw", ["inline", "INLINE", " inline "])
    def test_inline_is_read_forgivingly(self, monkeypatch, raw):
        monkeypatch.setenv("INGESTION_MODE", raw)

        assert settings.ingestion_mode() == "inline"

    def test_a_typo_is_an_error_not_a_fallback(self, monkeypatch):
        """Silently running queued when the operator meant inline — or the
        reverse — would be the worst outcome; a crash at startup is not."""
        monkeypatch.setenv("INGESTION_MODE", "inlne")

        with pytest.raises(RuntimeError) as exc_info:
            settings.ingestion_mode()

        assert "inlne" in str(exc_info.value)


class TestCorsOrigins:
    def test_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)

        assert settings.cors_origins() == []

    def test_a_comma_separated_list_is_split_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://a.pages.dev, https://b.example ,,")

        assert settings.cors_origins() == ["https://a.pages.dev", "https://b.example"]

    def test_an_empty_list_installs_nothing(self):
        """Development must be untouched: not a permissive middleware, not a
        restrictive one — no middleware. A preflight then reaches the app
        itself, which has no OPTIONS route, rather than a CORS layer that
        would answer 400 for every origin."""
        from app.main import configure_cors

        app = FastAPI()
        app.get("/x")(lambda: {"ok": True})
        configure_cors(app, [])

        assert app.user_middleware == []
        response = TestClient(app).get("/x", headers={"Origin": "https://a.pages.dev"})
        assert "access-control-allow-origin" not in response.headers
        preflight = TestClient(app).options(
            "/x",
            headers={"Origin": "https://a.pages.dev", "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code == 405

    def test_a_listed_origin_is_allowed_and_an_unlisted_one_is_not(self):
        from app.main import configure_cors

        app = FastAPI()
        app.get("/x")(lambda: {"ok": True})
        configure_cors(app, ["https://a.pages.dev"])
        client = TestClient(app)

        allowed = client.get("/x", headers={"Origin": "https://a.pages.dev"})
        other = client.get("/x", headers={"Origin": "https://evil.example"})

        assert allowed.headers.get("access-control-allow-origin") == "https://a.pages.dev"
        assert "access-control-allow-origin" not in other.headers

    def test_preflight_for_a_post_is_answered(self):
        from app.main import configure_cors

        app = FastAPI()
        app.post("/x")(lambda: {"ok": True})
        configure_cors(app, ["https://a.pages.dev"])

        response = TestClient(app).options(
            "/x",
            headers={
                "Origin": "https://a.pages.dev",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert "POST" in response.headers.get("access-control-allow-methods", "")


class TestSslMode:
    def test_absent_locally(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)

        assert "sslmode" not in get_database_url()

    def test_appended_when_set(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_SSLMODE", "require")

        assert get_database_url().endswith(" sslmode=require")

    def test_blank_counts_as_absent(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_SSLMODE", "  ")

        assert "sslmode" not in get_database_url()


@requires_postgres
class TestApplySchema:
    def test_it_is_idempotent_against_a_database_that_has_the_schema(self, db):
        """The test database was built from init.sql; applying it again must
        change nothing and fail nothing."""
        from app.db.apply_schema import apply_schema

        apply_schema()
        apply_schema()

        with db() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT string_agg(tablename, ',' ORDER BY tablename) "
                    "FROM pg_tables WHERE schemaname = 'public'"
                )
                assert cursor.fetchone()[0] == "datasets,events,imports,schema_migrations"

    def test_the_entrypoint_does_not_print_the_password(self, capsys):
        from app.db.apply_schema import main

        main()

        out = capsys.readouterr().out
        assert "applying init.sql to host=" in out
        assert "password" not in out


@requires_postgres
class TestReadinessInInlineMode:
    def test_inline_does_not_ask_the_queue(self, client, fake_queue, monkeypatch):
        """Without a worker there is no queue; a deployment must not sit at
        503 forever because Redis is absent."""
        monkeypatch.setenv("INGESTION_MODE", "inline")
        fake_queue.fail_with = RuntimeError("no redis here")

        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["queue"] is None

    def test_queue_mode_still_asks(self, client, fake_queue, monkeypatch):
        monkeypatch.setenv("INGESTION_MODE", "queue")
        fake_queue.fail_with = RuntimeError("redis down")

        assert client.get("/api/health").status_code == 503


@requires_postgres
class TestInlineIngestion:
    @pytest.fixture
    def feed(self, monkeypatch):
        def install(features=None, error=None):
            def _fetch(url=None, timeout=None, kind=None):
                if error is not None:
                    raise error
                return {"type": "FeatureCollection", "features": features or []}

            monkeypatch.setattr(usgs, "fetch_feed", _fetch)

        return install

    def test_the_run_happens_in_the_request_and_comes_back_finished(
        self, client, dataset, fake_queue, feed, monkeypatch
    ):
        monkeypatch.setenv("INGESTION_MODE", "inline")
        feed([make_feature(id="a"), make_feature(id="b")])

        response = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["inserted"] == 2
        assert body["finished_at"] is not None
        assert fake_queue.enqueued == []

    def test_the_data_is_there_when_the_response_arrives(
        self, client, dataset, feed, monkeypatch
    ):
        """That is the whole point of inline: no "check back later"."""
        monkeypatch.setenv("INGESTION_MODE", "inline")
        feed([make_feature(id="a")])

        client.post("/api/datasets/{0}/ingest".format(dataset["id"]))
        page = client.get("/api/datasets/{0}/events".format(dataset["id"])).json()

        assert page["total"] == 1

    def test_a_feed_failure_is_a_502_with_the_run_recorded(
        self, client, dataset, feed, monkeypatch
    ):
        from app.ingestion import IngestionError

        monkeypatch.setenv("INGESTION_MODE", "inline")
        feed(error=IngestionError("feed unreachable"))

        response = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert response.status_code == 502
        assert "feed unreachable" in response.json()["detail"]
        run = client.get("/api/datasets/{0}/imports".format(dataset["id"])).json()["items"][0]
        assert run["status"] == "failed"

    def test_queue_mode_still_answers_202_with_the_queued_run(
        self, client, dataset, fake_queue, monkeypatch
    ):
        monkeypatch.setenv("INGESTION_MODE", "queue")

        response = client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert fake_queue.enqueued == [body["id"]]

    def test_both_modes_return_the_same_shape(self, client, dataset, feed, monkeypatch):
        """A client must not have to know which mode the server runs."""
        feed([make_feature(id="a")])
        # Two datasets: a dataset with a run in flight refuses another.
        other = client.post("/api/datasets", json={"name": "Other", "source": "usgs"}).json()
        monkeypatch.setenv("INGESTION_MODE", "queue")
        queued = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()
        monkeypatch.setenv("INGESTION_MODE", "inline")
        finished = client.post("/api/datasets/{0}/ingest".format(other["id"])).json()

        assert set(queued) == set(finished)
