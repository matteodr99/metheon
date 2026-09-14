"""Deployment-facing settings, read from the environment.

Everything here is inert in local development: the defaults reproduce the
behaviour the project had before any of it existed.
"""

import os
from typing import List

INGESTION_MODES = ("queue", "inline")


def ingestion_mode() -> str:
    """How POST /ingest does its work.

    `queue` hands the run to Redis and a worker — local development, Kind.
    `inline` runs it inside the request — a deployment with no worker.
    Read per call so a test can switch it; validated so a typo in the
    environment is an error, not a silent fallback.
    """
    value = os.getenv("INGESTION_MODE", "queue").strip().lower()
    if value not in INGESTION_MODES:
        raise RuntimeError(
            "INGESTION_MODE must be one of {0}, not {1!r}".format(
                ", ".join(INGESTION_MODES), value
            )
        )
    return value


def cors_origins() -> List[str]:
    """Origins allowed to call the API from a browser.

    Empty by default: in development the Vite proxy makes the browser see
    one origin and no CORS is involved. A deployed frontend on another
    domain lists itself here, comma-separated.
    """
    raw = os.getenv("CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
