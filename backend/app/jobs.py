"""The Redis job queue.

The queue carries nothing but import ids. Everything else about a run — the
feed url, the counts, the outcome — lives in the `imports` table, so there is
a single source of truth about what happened.
"""

import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
QUEUE_NAME = os.getenv("QUEUE_NAME", "metheon:imports")

# How long the worker blocks on the queue before looping again. It only
# controls how quickly the worker notices a shutdown signal.
BLOCK_TIMEOUT_SECONDS = int(os.getenv("QUEUE_BLOCK_TIMEOUT_SECONDS", "5"))


class QueueError(Exception):
    """Raised when the queue cannot be reached."""


def get_client() -> "redis.Redis":
    """Return a Redis client. Decoding is on, so values come back as str."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
    )


def enqueue_import(import_id: int, client: Optional["redis.Redis"] = None) -> None:
    """Append an import id to the queue."""
    client = client or get_client()
    try:
        client.rpush(QUEUE_NAME, str(import_id))
    except redis.RedisError as exc:
        raise QueueError("Could not enqueue the import: {0}".format(exc))


def dequeue_import(
    client: Optional["redis.Redis"] = None,
    timeout: Optional[int] = None,
) -> Optional[int]:
    """Block until an import id is available, or until the timeout expires.

    Returns None on timeout, so the caller can check whether it should keep
    running. A malformed entry is dropped rather than crashing the worker,
    but it is logged: silently discarding a job would hide a producer bug.
    """
    client = client or get_client()
    timeout = BLOCK_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        message = client.blpop(QUEUE_NAME, timeout=timeout)
    except redis.RedisError as exc:
        raise QueueError("Could not read from the queue: {0}".format(exc))

    if message is None:
        return None

    _, value = message
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("dropped a malformed queue entry: %r", value)
        return None


def queue_length(client: Optional["redis.Redis"] = None) -> int:
    """Return how many imports are waiting to be picked up."""
    client = client or get_client()
    try:
        return client.llen(QUEUE_NAME)
    except redis.RedisError as exc:
        raise QueueError("Could not read the queue length: {0}".format(exc))


def ping(client: Optional["redis.Redis"] = None) -> bool:
    """Return whether Redis answers."""
    client = client or get_client()
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
