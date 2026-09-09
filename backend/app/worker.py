"""Background worker: drains the import queue.

Run it with:

    python -m app.worker

It blocks on Redis, runs one import at a time, and stops cleanly on SIGINT
or SIGTERM so `docker compose down` does not cut a run in half.
"""

import logging
import os
import signal
import sys

from app import jobs
from app.ingestion.runner import UnknownImport, run_import

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logger = logging.getLogger("app.worker")


class Worker:
    def __init__(self, client=None):
        self.client = client or jobs.get_client()
        self.running = True

    def request_stop(self, signum=None, frame=None) -> None:
        """Ask the loop to finish the current job and exit."""
        logger.info("shutdown requested, finishing the current job")
        self.running = False

    def run_once(self) -> bool:
        """Wait for one job and run it. Returns False on timeout."""
        import_id = jobs.dequeue_import(client=self.client)
        if import_id is None:
            return False

        try:
            run_import(import_id)
        except UnknownImport:
            # The row is gone: nothing to record, nothing to retry.
            logger.warning("import %s: no matching row, skipped", import_id)
        except Exception:
            # run_import has already marked the run as failed. The worker
            # must survive a bad job, so the loop keeps going.
            logger.error("import %s: run failed", import_id)

        return True

    def run(self) -> None:
        logger.info(
            "worker started, queue %s on %s:%s",
            jobs.QUEUE_NAME,
            jobs.REDIS_HOST,
            jobs.REDIS_PORT,
        )
        while self.running:
            try:
                self.run_once()
            except jobs.QueueError as exc:
                # Redis being briefly unavailable must not kill the worker.
                logger.error("queue unavailable: %s", exc)
        logger.info("worker stopped")


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    worker = Worker()
    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)
    worker.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
