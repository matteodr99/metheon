"""The Redis queue.

A fake client stands in for Redis, so the suite stays offline and does not
need a running server.
"""

import redis
import pytest

from app import jobs


class FakeRedis:
    """Just enough of the redis client for the queue to work against."""

    def __init__(self, error=None):
        self.items = []
        self.error = error

    def _maybe_fail(self):
        if self.error is not None:
            raise self.error

    def rpush(self, name, value):
        self._maybe_fail()
        self.items.append(value)
        return len(self.items)

    def blpop(self, name, timeout=None):
        self._maybe_fail()
        if not self.items:
            return None
        return (name, self.items.pop(0))

    def llen(self, name):
        self._maybe_fail()
        return len(self.items)

    def ping(self):
        self._maybe_fail()
        return True


class TestEnqueue:
    def test_an_import_id_is_pushed_as_a_string(self):
        client = FakeRedis()

        jobs.enqueue_import(7, client=client)

        assert client.items == ["7"]

    def test_ids_keep_their_order(self):
        client = FakeRedis()

        for import_id in (1, 2, 3):
            jobs.enqueue_import(import_id, client=client)

        assert client.items == ["1", "2", "3"]

    def test_a_redis_failure_becomes_a_queue_error(self):
        client = FakeRedis(error=redis.ConnectionError("refused"))

        with pytest.raises(jobs.QueueError) as exc_info:
            jobs.enqueue_import(1, client=client)

        assert "Could not enqueue" in str(exc_info.value)


class TestDequeue:
    def test_an_id_comes_back_as_an_integer(self):
        client = FakeRedis()
        client.items = ["42"]

        assert jobs.dequeue_import(client=client) == 42

    def test_the_queue_is_drained_in_order(self):
        client = FakeRedis()
        client.items = ["1", "2"]

        assert jobs.dequeue_import(client=client) == 1
        assert jobs.dequeue_import(client=client) == 2

    def test_an_empty_queue_returns_none(self):
        assert jobs.dequeue_import(client=FakeRedis()) is None

    def test_a_malformed_entry_is_dropped_and_logged(self, caplog):
        """A bad entry must not crash the worker, but must not vanish either."""
        client = FakeRedis()
        client.items = ["not-a-number"]

        assert jobs.dequeue_import(client=client) is None
        assert "malformed" in caplog.text

    def test_a_redis_failure_becomes_a_queue_error(self):
        client = FakeRedis(error=redis.ConnectionError("refused"))

        with pytest.raises(jobs.QueueError) as exc_info:
            jobs.dequeue_import(client=client)

        assert "Could not read from the queue" in str(exc_info.value)


class TestIntrospection:
    def test_queue_length_counts_waiting_jobs(self):
        client = FakeRedis()
        client.items = ["1", "2", "3"]

        assert jobs.queue_length(client=client) == 3

    def test_ping_is_true_when_redis_answers(self):
        assert jobs.ping(client=FakeRedis()) is True

    def test_ping_is_false_when_redis_does_not_answer(self):
        """Health must report a down queue, not raise."""
        client = FakeRedis(error=redis.ConnectionError("refused"))

        assert jobs.ping(client=client) is False
