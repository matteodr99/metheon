"""Execution of a queued import run.

The endpoint only enqueues; this is where the work actually happens, called
by the worker. Keeping it here rather than in a route handler means the same
code would run unchanged if it were ever triggered from somewhere else.
"""

import logging
from typing import Any, Dict

from app.db import repository
from app.db.database import get_connection
from app.ingestion import usgs

logger = logging.getLogger(__name__)

# A broken feed can reject every feature; only the first few reasons are
# stored, so one bad run cannot bloat the imports table.
MAX_STORED_ERRORS = 10


class UnknownImport(Exception):
    """Raised when a queued id has no matching row."""


def _fail(import_id: int, dataset_id: int, error: str) -> None:
    """Record a failure on both the run and its dataset.

    Committed separately from the work that failed, so the failure survives.
    """
    with get_connection() as connection:
        repository.fail_import(connection, import_id, error)
    with get_connection() as connection:
        repository.set_dataset_status(
            connection, dataset_id, repository.STATUS_FAILED
        )


def run_import(import_id: int) -> Dict[str, Any]:
    """Run one import from the queue and return its counts.

    Raises `UnknownImport` when the id does not exist; every other failure is
    recorded on the run and re-raised.
    """
    with get_connection() as connection:
        import_run = repository.get_import(connection, import_id)

    if import_run is None:
        raise UnknownImport("Import {0} not found".format(import_id))

    dataset_id = import_run["dataset_id"]
    feed_url = import_run["feed_url"]

    with get_connection() as connection:
        repository.start_import(connection, import_id)
    with get_connection() as connection:
        repository.set_dataset_status(
            connection, dataset_id, repository.STATUS_PROCESSING
        )

    logger.info(
        "import %s: starting for dataset %s from %s",
        import_id,
        dataset_id,
        feed_url,
    )

    try:
        payload = usgs.fetch_feed(url=feed_url)
        records, errors = usgs.normalize_feed(payload)
        fetched = len(payload.get("features", []))

        with get_connection() as connection:
            inserted, updated = repository.upsert_earthquakes(
                connection, dataset_id, records
            )
    except usgs.IngestionError as exc:
        logger.warning("import %s: failed, %s", import_id, exc)
        _fail(import_id, dataset_id, str(exc))
        raise
    except Exception as exc:
        logger.exception("import %s: unexpected failure", import_id)
        _fail(import_id, dataset_id, repr(exc))
        raise

    with get_connection() as connection:
        repository.complete_import(
            connection,
            import_id,
            fetched=fetched,
            valid=len(records),
            invalid=len(errors),
            inserted=inserted,
            updated=updated,
            invalid_sample=(
                "\n".join(errors[:MAX_STORED_ERRORS]) if errors else None
            ),
        )
    with get_connection() as connection:
        repository.set_dataset_status(
            connection, dataset_id, repository.STATUS_COMPLETED
        )

    logger.info(
        "import %s: completed, %s fetched, %s inserted, %s updated, %s invalid",
        import_id,
        fetched,
        inserted,
        updated,
        len(errors),
    )

    return {
        "import_id": import_id,
        "dataset_id": dataset_id,
        "fetched": fetched,
        "valid": len(records),
        "invalid": len(errors),
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
    }
