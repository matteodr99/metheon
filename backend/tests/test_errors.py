"""Error handling: the API's answers when things break, and the reaper."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _refuse():
    raise psycopg.OperationalError("connection refused")


class TestDatabaseDown:
    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", "/api/datasets"),
            ("get", "/api/datasets/1/earthquakes"),
            ("get", "/api/datasets/1/imports"),
            ("get", "/api/datasets/1/earthquakes/summary"),
            ("post", "/api/datasets/1/ingest"),
        ],
    )
    def test_every_route_answers_503_with_a_reason(self, client, monkeypatch, method, path):
        """The service is up, a dependency is not: 503 says "try again"."""
        from app import main

        monkeypatch.setattr(main, "get_connection", _refuse)

        response = getattr(client, method)(path)

        assert response.status_code == 503
        assert response.json() == {"detail": "The database is unavailable"}

    def test_creating_a_dataset_answers_503_too(self, client, monkeypatch):
        from app import main

        monkeypatch.setattr(main, "get_connection", _refuse)

        response = client.post("/api/datasets", json={"name": "x", "source": "usgs"})

        assert response.status_code == 503

    def test_the_outage_is_logged_as_a_warning(self, client, monkeypatch, caplog):
        from app import main

        monkeypatch.setattr(main, "get_connection", _refuse)
        with caplog.at_level("WARNING", logger="app.api"):
            client.get("/api/datasets")

        assert "database unavailable" in caplog.text
        assert "GET /api/datasets" in caplog.text


class TestUnexpectedFailure:
    def test_the_client_gets_a_fixed_body_and_no_traceback(
        self, lenient_client, monkeypatch
    ):
        from app import main

        def explode():
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(main, "get_connection", explode)

        response = lenient_client.get("/api/datasets")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert "secret internal detail" not in response.text
        assert "Traceback" not in response.text

    def test_the_traceback_goes_to_the_log(self, lenient_client, monkeypatch, caplog):
        """Where someone can act on it, not where it would leak."""
        from app import main

        def explode():
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(main, "get_connection", explode)
        with caplog.at_level("ERROR", logger="app.api"):
            lenient_client.get("/api/datasets")

        assert "unhandled RuntimeError" in caplog.text
        assert "secret internal detail" in caplog.text
        assert "Traceback" in caplog.text

    def test_a_known_refusal_is_not_turned_into_a_500(self, lenient_client):
        """HTTPException must keep its own code past the catch-all."""
        assert lenient_client.get("/api/datasets/999/earthquakes").status_code == 404


class TestStaleRunReaper:
    def _processing_run(self, db, dataset_id, minutes_ago):
        with db() as connection:
            import_id = repository.create_import(connection, dataset_id, "url")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE imports
                    SET status = 'processing',
                        started_at = CURRENT_TIMESTAMP - make_interval(mins => %s)
                    WHERE id = %s
                    """,
                    (minutes_ago, import_id),
                )
        return import_id

    def _status(self, db, import_id):
        with db() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status, error FROM imports WHERE id = %s", (import_id,))
                return cursor.fetchone()

    def test_an_old_processing_run_is_failed_with_a_reason(self, db, dataset):
        import_id = self._processing_run(db, dataset["id"], minutes_ago=60)

        with db() as connection:
            stale = repository.fail_stale_imports(connection, older_than_minutes=15)

        assert [run["id"] for run in stale] == [import_id]
        status, error = self._status(db, import_id)
        assert status == "failed"
        assert "Abandoned" in error

    def test_a_recent_processing_run_is_left_alone(self, db, dataset):
        """It may be a run another worker is actually working on."""
        import_id = self._processing_run(db, dataset["id"], minutes_ago=2)

        with db() as connection:
            stale = repository.fail_stale_imports(connection, older_than_minutes=15)

        assert stale == []
        assert self._status(db, import_id)[0] == "processing"

    def test_finished_runs_are_never_touched(self, db, dataset):
        with db() as connection:
            import_id = repository.create_import(connection, dataset["id"], "url")
            repository.complete_import(connection, import_id, 1, 1, 0, 1, 0)
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE imports SET started_at = CURRENT_TIMESTAMP - make_interval(mins => 999) WHERE id = %s",
                    (import_id,),
                )

        with db() as connection:
            assert repository.fail_stale_imports(connection, 15) == []
        assert self._status(db, import_id)[0] == "completed"

    def test_the_dataset_is_failed_when_the_stale_run_is_its_latest(self, db, dataset):
        self._processing_run(db, dataset["id"], minutes_ago=60)
        with db() as connection:
            repository.set_dataset_status(connection, dataset["id"], "processing")

        with db() as connection:
            repository.fail_stale_imports(connection, 15)
            assert repository.get_dataset(connection, dataset["id"])["status"] == "failed"

    def test_the_dataset_is_left_alone_when_a_newer_run_completed(self, db, dataset):
        """The newer run already tells the truth about the dataset."""
        self._processing_run(db, dataset["id"], minutes_ago=60)
        with db() as connection:
            newer = repository.create_import(connection, dataset["id"], "url")
            repository.complete_import(connection, newer, 1, 1, 0, 1, 0)
            repository.set_dataset_status(connection, dataset["id"], "completed")

        with db() as connection:
            stale = repository.fail_stale_imports(connection, 15)
            assert len(stale) == 1
            assert repository.get_dataset(connection, dataset["id"])["status"] == "completed"

    def test_the_reaped_run_shows_in_the_history_as_failed(self, client, db, dataset):
        """Visible to the dashboard, with the reason."""
        self._processing_run(db, dataset["id"], minutes_ago=60)
        with db() as connection:
            repository.fail_stale_imports(connection, 15)

        run = client.get("/api/datasets/{0}/imports".format(dataset["id"])).json()["items"][0]

        assert run["status"] == "failed"
        assert "Abandoned" in run["error"]
        assert run["finished_at"] is not None
