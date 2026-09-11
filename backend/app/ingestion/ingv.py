"""Ingestion of earthquake data from INGV, the Italian national institute.

INGV exposes an FDSN event web service; documented at
https://webservices.ingv.it/

The service answers a query rather than serving a fixed feed, so this
module asks for a time window ending now. The window's length is
INGV_DAYS, seven by default.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.ingestion import IngestionError
from app.ingestion.geojson import collect_records, optional_number, parse_point_feature

DEFAULT_FEED_URL = os.getenv(
    "INGV_FEED_URL",
    "https://webservices.ingv.it/fdsnws/event/1/query?format=geojson&limit=5000",
)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("INGV_TIMEOUT_SECONDS", "30"))

DEFAULT_DAYS = int(os.getenv("INGV_DAYS", "7"))

EVENT_PAGE = "https://terremoti.ingv.it/event/{0}"


def with_time_window(url: str, days: int = DEFAULT_DAYS, now: Optional[datetime] = None) -> str:
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


def fetch_feed(
    url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Query the event service and return the GeoJSON as a dictionary."""
    url = with_time_window(url or DEFAULT_FEED_URL)
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise IngestionError("Could not fetch the INGV feed: {0}".format(exc))
    except ValueError as exc:
        raise IngestionError("The INGV feed is not valid JSON: {0}".format(exc))

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise IngestionError("Unexpected payload: a GeoJSON FeatureCollection was expected")

    if not isinstance(payload.get("features"), list):
        raise IngestionError("The feed does not contain a list of features")

    return payload


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    """INGV writes times as ISO 8601 without a zone; they are UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _event_id(feature: Dict[str, Any]) -> Optional[str]:
    """INGV ids are integers under `properties.eventId`.

    Stored as text so they share a column with USGS's alphanumeric ids.
    """
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return None
    event_id = properties.get("eventId")
    if isinstance(event_id, bool) or not isinstance(event_id, (int, str)):
        return None
    return str(event_id)


def normalize_feature(feature: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize a single INGV feature into the shared earthquake record."""
    point, error = parse_point_feature(feature, _event_id)
    if error is not None:
        return None, error

    external_id = point["external_id"]
    properties = point["properties"]

    occurred_at = _parse_iso_utc(properties.get("time"))
    if occurred_at is None:
        return None, "{0}: missing or invalid time".format(external_id)

    # USGS writes magnitude types in lowercase ("ml"); INGV in mixed case
    # ("ML", "Md"). Lowercasing keeps one spelling per type across sources.
    magnitude_type = properties.get("magType")
    if isinstance(magnitude_type, str):
        magnitude_type = magnitude_type.lower()

    record = {
        "external_id": external_id,
        "magnitude": optional_number(properties.get("mag")),
        "magnitude_type": magnitude_type,
        "place": properties.get("place"),
        "event_type": properties.get("type"),
        "occurred_at": occurred_at,
        "source_updated_at": None,
        "longitude": point["longitude"],
        "latitude": point["latitude"],
        "depth_km": point["depth_km"],
        "tsunami": False,
        "significance": None,
        "url": EVENT_PAGE.format(external_id),
    }
    return record, None


def normalize_feed(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every feature, returning the valid records and the errors."""
    return collect_records(payload, normalize_feature)
