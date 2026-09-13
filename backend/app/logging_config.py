"""Logging shared by the API and the worker.

One format for both, so `docker compose logs` reads the same whichever
process wrote the line, and one place to change it.
"""

import logging
import os
import sys
import time

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str = LOG_LEVEL) -> None:
    """Send the application's logs to stdout in the shared format, in UTC.

    UTC on purpose: the API runs on the host in local time and the worker
    in a container in UTC, and with each using its own clock the same run
    showed up two hours apart in the two logs. Event times in the database
    are UTC as well, so everything lines up.

    `basicConfig` does nothing if the root logger already has handlers, so
    calling this twice — or under a test runner that installed its own —
    is harmless. The converter is set regardless, since it is a class
    attribute and not tied to a handler.
    """
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=level, format=FORMAT, stream=sys.stdout)
