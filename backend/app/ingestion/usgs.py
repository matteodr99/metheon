"""Ingestion of public earthquake data from the USGS GeoJSON feeds.

The feeds are documented at
https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php

This module only fetches and normalizes the data. Persistence lives in
`app.db.repository`, so the two concerns stay independently testable.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.ingestion import IngestionError
from app.ingestion.geojson import collect_records, optional_number, parse_point_feature

DEFAULT_FEED_URL = os.getenv(
    "USGS_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("USGS_TIMEOUT_SECONDS", "30"))


def fetch_feed(
    url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Download the GeoJSON feed and return it as a dictionary."""
    url = url or DEFAULT_FEED_URL
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise IngestionError("Could not fetch the USGS feed: {0}".format(exc))
    except ValueError as exc:
        raise IngestionError("The USGS feed is not valid JSON: {0}".format(exc))

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise IngestionError("Unexpected payload: a GeoJSON FeatureCollection was expected")

    if not isinstance(payload.get("features"), list):
        raise IngestionError("The feed does not contain a list of features")

    return payload


def _epoch_ms_to_datetime(value: Any) -> Optional[datetime]:
    """Convert USGS epoch milliseconds into a naive UTC datetime."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        moment = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.replace(tzinfo=None)


def normalize_feature(feature: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize a single GeoJSON feature.

    Returns a `(record, error)` pair: exactly one of the two is set, so an
    invalid feature is reported instead of silently dropped.
    """
    point, error = parse_point_feature(feature, lambda f: f.get("id"))
    if error is not None:
        return None, error

    external_id = point["external_id"]
    properties = point["properties"]

    occurred_at = _epoch_ms_to_datetime(properties.get("time"))
    if occurred_at is None:
        return None, "{0}: missing or invalid time".format(external_id)

    record = {
        "external_id": external_id,
        "magnitude": optional_number(properties.get("mag")),
        "magnitude_type": properties.get("magType"),
        "place": properties.get("place"),
        "event_type": properties.get("type"),
        "occurred_at": occurred_at,
        "source_updated_at": _epoch_ms_to_datetime(properties.get("updated")),
        "longitude": point["longitude"],
        "latitude": point["latitude"],
        "depth_km": point["depth_km"],
        "tsunami": bool(properties.get("tsunami")),
        "significance": properties.get("sig"),
        "url": properties.get("url"),
    }
    return record, None


def normalize_feed(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every feature, returning the valid records and the errors."""
    return collect_records(payload, normalize_feature)
