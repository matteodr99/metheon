"""Apply init.sql to whatever database the environment points at.

    python -m app.db.apply_schema

Locally the postgres image runs init.sql on first start and this is never
needed. A hosted database has no docker-entrypoint-initdb.d, so this is how
the schema gets there — from the same file, so it keeps its single source.
Idempotent: every statement in init.sql is IF NOT EXISTS.
"""

import io
import os
import sys

from app.db.database import get_connection, get_database_url

INIT_SQL = os.path.join(os.path.dirname(__file__), "init.sql")


def apply_schema() -> None:
    with io.open(INIT_SQL, encoding="utf-8") as handle:
        schema = handle.read()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema)


def main() -> int:
    target = get_database_url().split(" password=")[0]
    print("applying init.sql to {0}".format(target))
    apply_schema()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
