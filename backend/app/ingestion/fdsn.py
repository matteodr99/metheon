"""Helpers for FDSN event queries.

INGV's FDSN `event` service is a query, not a feed: it accepts `starttime`
and returns GeoJSON with ISO 8601 times. These helpers build the requested
time window and parse timestamps into the shared UTC representation.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def with_time_window(url: str, days: int, now: Optional[datetime] = None) -> str:
    """Add a `starttime` covering the last `days` unless the url has one.

    A url that already names its window is left alone, so a caller can ask
    for a specific period and get exactly that.
    """
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if "starttime" in query:
        return url

    moment = now or datetime.now(timezone.utc)
    start = (moment - timedelta(days=days)).replace(microsecond=0)
    query["starttime"] = [start.strftime("%Y-%m-%dT%H:%M:%S")]
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def parse_iso_utc(value: Any) -> Optional[datetime]:
    """An ISO 8601 time as naive UTC; None when it is not one.

    INGV writes no zone and means UTC.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment
