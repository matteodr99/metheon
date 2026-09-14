"""Bring whatever database the environment points at up to the schema.

    python -m app.db.apply_schema

Two files describe the schema. `init.sql` is the final shape, all of it
`IF NOT EXISTS`, and is what a fresh database gets — the postgres image
runs it on first start, the test suite and Kind apply it themselves. The
numbered files under `migrations/` bring a database that already holds
data up to that shape; each runs once, in order, in its own transaction,
and records its version in `schema_migrations`.

A hosted database has neither docker-entrypoint-initdb.d nor a shell, so
this is how both get there. Idempotent: run it twice and the second run
does nothing.
"""

import io
import os
import re
import sys
from typing import List, Tuple

from app.db.database import get_connection, get_database_url

HERE = os.path.dirname(__file__)
INIT_SQL = os.path.join(HERE, "init.sql")
MIGRATIONS_DIR = os.path.join(HERE, "migrations")

_MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def list_migrations(directory: str = MIGRATIONS_DIR) -> List[Tuple[int, str]]:
    """The migration files, as (version, path), in version order."""
    found = []
    for name in os.listdir(directory):
        match = _MIGRATION_NAME.match(name)
        if match:
            found.append((int(match.group(1)), os.path.join(directory, name)))
    return sorted(found)


def apply_schema(directory: str = MIGRATIONS_DIR) -> List[int]:
    """Apply init.sql, then every migration not yet recorded.

    Returns the versions applied this time, so a caller can say so.
    """
    with io.open(INIT_SQL, encoding="utf-8") as handle:
        schema = handle.read()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema)

    applied = []
    for version, path in list_migrations(directory):
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
                )
                if cursor.fetchone() is not None:
                    continue
                with io.open(path, encoding="utf-8") as handle:
                    cursor.execute(handle.read())
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                )
        applied.append(version)
    return applied


def main() -> int:
    target = get_database_url().split(" password=")[0]
    print("applying init.sql to {0}".format(target))
    applied = apply_schema()
    for version in applied:
        print("applied migration {0:03d}".format(version))
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
