"""The worker loop.

The queue and the job are both replaced, so these tests exercise the loop
itself: what it does with an empty queue, a bad job, an outage, and a
shutdown signal.
"""

import pytest

from app import jobs, worker


@pytest.fixture
def loop(monkeypatch):
    """A worker whose queue and job runner are under the test's control."""
    state = {"queue": [], "ran": [], "raise_on_run": None, "queue_error": False}

    def fake_dequeue(client=None, timeout=None):
        if state["queue_error"]:
            raise jobs.QueueError("redis down")
        return state["queue"].pop(0) if state["queue"] else None

    def fake_run_import(import_id):
        state["ran"].append(import_id)
        if state["raise_on_run"] is not None:
            raise state["raise_on_run"]
        return {}

    monkeypatch.setattr(jobs, "dequeue_import", fake_dequeue)
    monkeypatch.setattr(worker, "run_import", fake_run_import)

    # The startup sweep for abandoned runs opens a database connection. The
    # loop tests are about the loop, so the sweep is recorded, not run.
    state["reaped"] = 0
    monkeypatch.setattr(
        worker.Worker, "reap_stale_runs", lambda self: state.__setitem__("reaped", state["reaped"] + 1)
    )

    instance = worker.Worker(client=object())
    return instance, state


class TestRunOnce:
    def test_an_empty_queue_reports_no_work(self, loop):
        instance, _ = loop

        assert instance.run_once() is False

    def test_a_queued_job_is_run(self, loop):
        instance, state = loop
        state["queue"] = [7]

        assert instance.run_once() is True
        assert state["ran"] == [7]

    def test_an_unknown_import_does_not_stop_the_worker(self, loop):
        from app.ingestion.runner import UnknownImport

        instance, state = loop
        state["queue"] = [7]
        state["raise_on_run"] = UnknownImport("gone")

        assert instance.run_once() is True
        assert instance.running is True

    def test_a_failing_job_does_not_stop_the_worker(self, loop):
        """run_import has already recorded the failure; the loop must go on."""
        instance, state = loop
        state["queue"] = [7]
        state["raise_on_run"] = ValueError("boom")

        assert instance.run_once() is True
        assert instance.running is True


class TestShutdown:
    def test_request_stop_clears_the_running_flag(self, loop):
        instance, _ = loop

        instance.request_stop()

        assert instance.running is False

    def test_the_loop_exits_after_a_stop_request(self, loop, monkeypatch):
        instance, state = loop
        state["queue"] = [1, 2]

        def stop_after_two(import_id):
            state["ran"].append(import_id)
            if len(state["ran"]) == 2:
                instance.request_stop()

        monkeypatch.setattr(worker, "run_import", stop_after_two)
        instance.run()

        assert state["ran"] == [1, 2]

    def test_wait_returns_early_once_stopped(self, loop):
        """A shutdown must not have to sit through the whole backoff."""
        import time

        instance, _ = loop
        instance.running = False

        started = time.monotonic()
        instance.wait(30)

        assert time.monotonic() - started < 1


class TestQueueOutage:
    def test_an_outage_is_retried_with_a_pause(self, loop, monkeypatch):
        """Without the pause the loop would spin as fast as Redis refuses."""
        instance, state = loop
        state["queue_error"] = True
        waits = []

        def fake_wait(seconds):
            waits.append(seconds)
            instance.running = False

        monkeypatch.setattr(instance, "wait", fake_wait)
        instance.run()

        assert waits == [worker.RETRY_DELAY_SECONDS]
        assert worker.RETRY_DELAY_SECONDS > 0

    def test_an_outage_does_not_crash_the_worker(self, loop, monkeypatch):
        instance, state = loop
        state["queue_error"] = True
        monkeypatch.setattr(instance, "wait", lambda s: instance.request_stop())

        instance.run()  # must return rather than raise


class TestStartupSweep:
    def test_the_sweep_runs_once_at_startup(self, loop):
        instance, state = loop
        instance.request_stop()

        instance.run()

        assert state["reaped"] == 1

    def test_abandoned_runs_are_reported(self, monkeypatch, caplog):
        instance = worker.Worker(client=object())
        stale = [{"id": 7, "dataset_id": 1}, {"id": 9, "dataset_id": 2}]

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(worker, "get_connection", lambda: Connection())
        monkeypatch.setattr(
            worker.repository, "fail_stale_imports", lambda connection, minutes: stale
        )

        instance.reap_stale_runs()

        assert "import 7: abandoned" in caplog.text
        assert "import 9: abandoned" in caplog.text

    def test_the_threshold_is_passed_through(self, monkeypatch):
        instance = worker.Worker(client=object())
        seen = {}

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(worker, "get_connection", lambda: Connection())
        monkeypatch.setattr(
            worker.repository,
            "fail_stale_imports",
            lambda connection, minutes: seen.setdefault("minutes", minutes) and [],
        )

        instance.reap_stale_runs()

        assert seen["minutes"] == worker.STALE_RUN_MINUTES

    def test_a_failing_sweep_does_not_stop_the_worker(self, monkeypatch, caplog):
        """The queue can still be served without it."""
        instance = worker.Worker(client=object())

        def refuse():
            raise RuntimeError("database down")

        monkeypatch.setattr(worker, "get_connection", refuse)

        instance.reap_stale_runs()  # must return, not raise

        assert "could not check for abandoned runs" in caplog.text
