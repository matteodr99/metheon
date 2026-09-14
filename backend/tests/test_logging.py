"""What the API writes to its log, and what it deliberately does not."""

import logging

import pytest

from app.logging_config import FORMAT, configure_logging
from tests.conftest import requires_postgres


class TestConfiguration:
    def test_the_format_names_time_level_logger_and_message(self):
        for field in ("asctime", "levelname", "name", "message"):
            assert "%({0})s".format(field) in FORMAT

    def test_timestamps_are_utc(self):
        """Host and container clocks differ; the log must not."""
        import time

        configure_logging()

        assert logging.Formatter.converter is time.gmtime

    def test_configuring_twice_is_harmless(self):
        """basicConfig is a no-op once the root has a handler; a second call
        must not stack another handler and double every line."""
        root = logging.getLogger()
        before = list(root.handlers)

        configure_logging()
        configure_logging()

        assert root.handlers == before or len(root.handlers) == len(before) + 1


@requires_postgres
class TestRequestLine:
    def test_every_request_gets_one_line_with_status_and_duration(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="app.api"):
            client.get("/api/datasets")

        lines = [r.getMessage() for r in caplog.records if r.name == "app.api"]
        assert any(
            line.startswith("GET /api/datasets 200 ") and line.endswith("ms")
            for line in lines
        ), lines

    def test_a_refused_request_logs_its_true_status(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="app.api"):
            client.get("/api/datasets/999/events")

        assert any(
            "GET /api/datasets/999/events 404 " in r.getMessage()
            for r in caplog.records
        )

    def test_a_503_from_the_handler_is_logged_with_503(self, client, monkeypatch, caplog):
        """The handler answers before the middleware writes, so the line
        carries the real status, not the 500 the exception would imply."""
        import psycopg

        from app import main

        def refuse():
            raise psycopg.OperationalError("down")

        monkeypatch.setattr(main, "get_connection", refuse)
        with caplog.at_level(logging.INFO, logger="app.api"):
            client.get("/api/datasets")

        assert any("GET /api/datasets 503 " in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("path", ["/api/health", "/api/health/live"])
    def test_probes_are_quiet_at_info(self, client, caplog, path):
        """A probe every few seconds would drown everything else."""
        with caplog.at_level(logging.INFO, logger="app.api"):
            client.get(path)

        assert not any(
            r.getMessage().startswith("GET {0} ".format(path)) and r.levelno >= logging.INFO
            for r in caplog.records
        )

    @pytest.mark.parametrize("path", ["/api/health", "/api/health/live"])
    def test_probes_are_still_there_at_debug(self, client, caplog, path):
        with caplog.at_level(logging.DEBUG, logger="app.api"):
            client.get(path)

        assert any(
            r.getMessage().startswith("GET {0} 200 ".format(path)) and r.levelno == logging.DEBUG
            for r in caplog.records
        )


@requires_postgres
class TestWhatGetsLogged:
    def test_creating_a_dataset(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="app.api"):
            created = client.post(
                "/api/datasets", json={"name": "Quakes", "source": "ingv"}
            ).json()

        assert any(
            "created dataset {0} 'Quakes' (ingv)".format(created["id"]) == r.getMessage()
            for r in caplog.records
        )

    def test_refusing_an_unknown_source_is_a_warning(self, client, caplog):
        with caplog.at_level(logging.WARNING, logger="app.api"):
            client.post("/api/datasets", json={"name": "x", "source": "meteorites"})

        assert any(
            r.levelno == logging.WARNING and "refused unknown source 'meteorites'" in r.getMessage()
            for r in caplog.records
        )

    def test_queueing_a_run(self, client, dataset, caplog):
        with caplog.at_level(logging.INFO, logger="app.api"):
            body = client.post("/api/datasets/{0}/ingest".format(dataset["id"])).json()

        assert any(
            "import {0}: queued for dataset {1}".format(body["id"], dataset["id"])
            == r.getMessage()
            for r in caplog.records
        )

    def test_a_queue_outage_is_a_warning_with_the_reason(
        self, client, dataset, fake_queue, caplog
    ):
        from app import jobs

        fake_queue.fail_with = jobs.QueueError("redis down")
        with caplog.at_level(logging.WARNING, logger="app.api"):
            client.post("/api/datasets/{0}/ingest".format(dataset["id"]))

        assert any(
            r.levelno == logging.WARNING and "could not queue, redis down" in r.getMessage()
            for r in caplog.records
        )

    def test_startup_and_shutdown_are_announced(self, db, fake_queue, caplog):
        from fastapi.testclient import TestClient

        from app.main import app

        with caplog.at_level(logging.INFO, logger="app.api"):
            with TestClient(app):
                pass

        messages = [r.getMessage() for r in caplog.records if r.name == "app.api"]
        assert any(m.startswith("api started") for m in messages)
        assert "api stopping" in messages
