import io
import json
import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with io.open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def real_feed():
    """A real USGS all_hour response, captured on 2026-09-09.

    Keeping a genuine payload guards against the feed shape being
    misremembered: the handcrafted features in the tests below only cover
    the cases they were written for.
    """
    return load_fixture("usgs_all_hour.json")


def make_feature(**overrides):
    """Build a minimal valid feature, overriding single fields per test."""
    feature = {
        "id": "test1",
        "properties": {
            "time": 1788942354913,
            "updated": 1788942565428,
            "mag": 1.4,
            "magType": "ml",
            "place": "26 km SW of Garden City, Texas",
            "type": "earthquake",
            "tsunami": 0,
            "sig": 30,
            "url": "https://example.invalid/event",
        },
        "geometry": {"type": "Point", "coordinates": [-101.696, 31.715, 2.4688]},
    }
    for key, value in overrides.items():
        if key in ("properties", "geometry") and isinstance(value, dict):
            feature[key] = value
        else:
            feature[key] = value
    return feature


# --------------------------------------------------------------------------
# Database-backed tests
#
# These use a dedicated database, created once per session from init.sql and
# emptied between tests. They are skipped, not failed, when PostgreSQL is not
# reachable, so the pure tests still run on a machine with nothing started.
# --------------------------------------------------------------------------

TEST_DB_NAME = os.getenv("TEST_POSTGRES_DB", "metheon_test")

INIT_SQL = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "app", "db", "init.sql"
)

TABLES = ("earthquakes", "imports", "datasets")


def _admin_dsn():
    """A connection string for the maintenance database."""
    import os as _os

    return (
        "host={0} port={1} dbname=postgres user={2} password={3}".format(
            _os.getenv("POSTGRES_HOST", "localhost"),
            _os.getenv("POSTGRES_PORT", "5432"),
            _os.getenv("POSTGRES_USER", "metheon"),
            _os.getenv("POSTGRES_PASSWORD", "metheon"),
        )
    )


def _postgres_is_reachable():
    try:
        import psycopg

        with psycopg.connect(_admin_dsn(), connect_timeout=2):
            return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_is_reachable(),
    reason="PostgreSQL is not reachable; start it with `docker compose up -d`",
)


@pytest.fixture(scope="session")
def test_database():
    """Create the test database from init.sql and point the app at it.

    The environment is changed rather than the code: `get_database_url` is
    read per connection, so the application picks this up on its own.
    """
    import psycopg

    with psycopg.connect(_admin_dsn(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS {0}".format(TEST_DB_NAME))
            cursor.execute("CREATE DATABASE {0}".format(TEST_DB_NAME))

    previous = os.environ.get("POSTGRES_DB")
    os.environ["POSTGRES_DB"] = TEST_DB_NAME

    from app.db.database import get_connection

    with io.open(INIT_SQL, encoding="utf-8") as handle:
        schema = handle.read()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema)

    yield TEST_DB_NAME

    if previous is None:
        del os.environ["POSTGRES_DB"]
    else:
        os.environ["POSTGRES_DB"] = previous

    with psycopg.connect(_admin_dsn(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS {0}".format(TEST_DB_NAME))


@pytest.fixture
def db(test_database):
    """Empty every table before each test, and hand back a connection factory.

    TRUNCATE rather than a rolled-back transaction: the application opens its
    own connections, so a transaction held by the test would not be visible
    to the code under test.
    """
    from app.db.database import get_connection

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE {0} RESTART IDENTITY CASCADE".format(", ".join(TABLES))
            )

    return get_connection


@pytest.fixture
def dataset(db):
    """Insert one dataset and return it."""
    from app.db import repository

    with db() as connection:
        return repository.create_dataset(
            connection, "Global Earthquakes", "USGS", "Test dataset"
        )


class FakeQueue:
    """Stands in for Redis so the API tests never need a running server."""

    def __init__(self):
        self.enqueued = []
        self.fail_with = None

    def enqueue_import(self, import_id, client=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.enqueued.append(import_id)

    def ping(self, client=None):
        return self.fail_with is None


@pytest.fixture
def fake_queue(monkeypatch):
    """Replace the queue functions the API calls."""
    from app import jobs

    queue = FakeQueue()
    monkeypatch.setattr(jobs, "enqueue_import", queue.enqueue_import)
    monkeypatch.setattr(jobs, "ping", queue.ping)
    return queue


@pytest.fixture
def client(db, fake_queue):
    """A TestClient wired to the test database and the fake queue."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
