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

DEFAULT_FEED_URL = os.getenv(
    "USGS_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("USGS_TIMEOUT_SECONDS", "30"))


class IngestionError(Exception):
    """Raised when the feed cannot be retrieved or is not usable."""


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


def _optional_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def normalize_feature(feature: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize a single GeoJSON feature.

    Returns a `(record, error)` pair: exactly one of the two is set, so an
    invalid feature is reported instead of silently dropped.
    """
    if not isinstance(feature, dict):
        return None, "Feature is not an object"

    external_id = feature.get("id")
    if not isinstance(external_id, str) or not external_id.strip():
        return None, "Feature without a usable id"

    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return None, "{0}: missing properties".format(external_id)

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None, "{0}: missing geometry".format(external_id)

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None, "{0}: geometry without longitude and latitude".format(external_id)

    longitude = _optional_number(coordinates[0])
    latitude = _optional_number(coordinates[1])
    if longitude is None or latitude is None:
        return None, "{0}: non-numeric coordinates".format(external_id)
    if not -180.0 <= longitude <= 180.0:
        return None, "{0}: longitude out of range ({1})".format(external_id, longitude)
    if not -90.0 <= latitude <= 90.0:
        return None, "{0}: latitude out of range ({1})".format(external_id, latitude)

    occurred_at = _epoch_ms_to_datetime(properties.get("time"))
    if occurred_at is None:
        return None, "{0}: missing or invalid time".format(external_id)

    depth_km = _optional_number(coordinates[2]) if len(coordinates) > 2 else None

    record = {
        "external_id": external_id,
        "magnitude": _optional_number(properties.get("mag")),
        "magnitude_type": properties.get("magType"),
        "place": properties.get("place"),
        "event_type": properties.get("type"),
        "occurred_at": occurred_at,
        "source_updated_at": _epoch_ms_to_datetime(properties.get("updated")),
        "longitude": longitude,
        "latitude": latitude,
        "depth_km": depth_km,
        "tsunami": bool(properties.get("tsunami")),
        "significance": properties.get("sig"),
        "url": properties.get("url"),
    }
    return record, None


def normalize_feed(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every feature, returning the valid records and the errors.

    Features carrying a duplicate id are kept only once: the feed is the
    single source of truth for an event, and a duplicate would otherwise
    make the upsert operate twice on the same row.
    """
    records: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen = set()

    for feature in payload.get("features", []):
        record, error = normalize_feature(feature)
        if error is not None:
            errors.append(error)
            continue
        if record["external_id"] in seen:
            errors.append("{0}: duplicate id in the feed".format(record["external_id"]))
            continue
        seen.add(record["external_id"])
        records.append(record)

    return records, errors
