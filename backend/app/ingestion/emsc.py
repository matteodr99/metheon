"""Ingestion of earthquake data from EMSC, the Euro-Mediterranean centre.

EMSC aggregates the bulletins of dozens of national networks and serves
them through an FDSN event service, documented at
https://www.seismicportal.eu/fdsn-wsevent.html

Like INGV it answers a query, so this module asks for a window ending now,
EMSC_DAYS long. The properties are EMSC's own; the shape is the shared one.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.ingestion import IngestionError, fdsn
from app.ingestion.geojson import (
    collect_records,
    optional_number,
    parse_point_feature,
    seismic_attributes,
)

# One kind of event, so `kind` is accepted and ignored throughout.
KINDS = ("earthquake",)

DEFAULT_FEED_URL = os.getenv(
    "EMSC_FEED_URL",
    "https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=5000",
)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("EMSC_TIMEOUT_SECONDS", "30"))

DEFAULT_DAYS = int(os.getenv("EMSC_DAYS", "7"))

EVENT_PAGE = "https://www.seismicportal.eu/eventdetails.html?unid={0}"

# EMSC codes its event types the QuakeML way: a letter for "known" or
# "suspected" and one for the kind. Spelled out here in the words USGS
# uses, so one `event_type` value means one thing across sources; a code
# not listed is kept as it is rather than guessed at.
EVENT_TYPES = {
    "ke": "earthquake",
    "se": "suspected earthquake",
    "qb": "quarry blast",
    "kq": "quarry blast",
    "sq": "suspected quarry blast",
    "km": "mining explosion",
    "sm": "suspected mining explosion",
    "kx": "explosion",
    "sx": "suspected explosion",
    "kn": "nuclear explosion",
    "sn": "suspected nuclear explosion",
    "ki": "induced event",
    "si": "suspected induced event",
    "ls": "landslide",
    "ue": "unknown",
}


def fetch_feed(
    url: Optional[str] = None,
    timeout: Optional[float] = None,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Query the event service and return the GeoJSON as a dictionary."""
    url = fdsn.with_time_window(url or DEFAULT_FEED_URL, DEFAULT_DAYS)
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise IngestionError("Could not fetch the EMSC feed: {0}".format(exc))
    except ValueError as exc:
        raise IngestionError("The EMSC feed is not valid JSON: {0}".format(exc))

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise IngestionError("Unexpected payload: a GeoJSON FeatureCollection was expected")

    if not isinstance(payload.get("features"), list):
        raise IngestionError("The feed does not contain a list of features")

    return payload


def _event_id(feature: Dict[str, Any]) -> Optional[str]:
    """EMSC's id is the feature `id`, repeated as `properties.unid`."""
    event_id = feature.get("id")
    if isinstance(event_id, str) and event_id:
        return event_id
    properties = feature.get("properties")
    if isinstance(properties, dict):
        unid = properties.get("unid")
        if isinstance(unid, str) and unid:
            return unid
    return None


def normalize_feature(feature: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize a single EMSC feature into the shared earthquake record."""
    point, error = parse_point_feature(feature, _event_id)
    if error is not None:
        return None, error

    external_id = point["external_id"]
    properties = point["properties"]

    occurred_at = fdsn.parse_iso_utc(properties.get("time"))
    if occurred_at is None:
        return None, "{0}: missing or invalid time".format(external_id)

    magnitude_type = properties.get("magtype")
    if isinstance(magnitude_type, str):
        magnitude_type = magnitude_type.lower()

    event_type = properties.get("evtype")
    if isinstance(event_type, str):
        event_type = EVENT_TYPES.get(event_type.lower(), event_type)

    record = {
        "external_id": external_id,
        "title": properties.get("flynn_region"),
        "event_type": event_type,
        "occurred_at": occurred_at,
        "ended_at": None,
        "source_updated_at": fdsn.parse_iso_utc(properties.get("lastupdate")),
        "longitude": point["longitude"],
        "latitude": point["latitude"],
        "geometry": None,
        "magnitude": optional_number(properties.get("mag")),
        "magnitude_unit": magnitude_type,
        "attributes": seismic_attributes(
            # The third coordinate is an elevation, negative below the
            # surface; `depth` is the same number the way round every other
            # source has it.
            depth_km=optional_number(properties.get("depth")),
            network=properties.get("auth"),
        ),
        "url": EVENT_PAGE.format(external_id),
    }
    return record, None


def normalize_feed(
    payload: Dict[str, Any], kind: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every feature, returning the valid records and the errors."""
    return collect_records(payload, normalize_feature)
