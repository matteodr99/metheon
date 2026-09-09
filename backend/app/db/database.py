import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "metheon",
    "POSTGRES_USER": "metheon",
    "POSTGRES_PASSWORD": "metheon",
}


def get_database_url() -> str:
    """Build the connection string from the environment.

    Read on every call rather than at import time, so a process can be
    pointed at a different database after the module is loaded — which is
    what the test suite does.
    """
    settings = {key: os.getenv(key, default) for key, default in DEFAULTS.items()}
    return (
        "host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} "
        "user={POSTGRES_USER} password={POSTGRES_PASSWORD}".format(**settings)
    )


def get_connection():
    return psycopg.connect(get_database_url())
