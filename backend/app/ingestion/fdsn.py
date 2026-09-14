"""What the FDSN event services have in common.

INGV and EMSC both implement the FDSN `event` web service: a query with
`starttime`, not a feed, answering GeoJSON with ISO 8601 times. The two
differ in their properties, which stay in each module; this is the shared
part.
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

    INGV writes no zone and means UTC; EMSC writes `Z`. Both end up the
    same, which is what the shared column expects.
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
