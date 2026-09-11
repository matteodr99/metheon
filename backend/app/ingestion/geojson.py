"""Validation shared by every source that publishes GeoJSON point features.

Each source maps its own properties, but the envelope — an id, a Point with
usable coordinates — is the same, and so are the mistakes a feed can make.
"""

from typing import Any, Callable, Dict, Optional, Tuple


def optional_number(value: Any) -> Optional[float]:
    """A float, or None for anything that is not a real number.

    Booleans are numbers to Python but never to a feed, so they are refused.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_point_feature(
    feature: Any,
    id_of: Callable[[Dict[str, Any]], Optional[str]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Check the envelope of a feature and return its position.

    Returns `(point, error)` with exactly one set. `point` carries the
    external id, the properties for the caller to map, and the coordinates
    already validated: longitude and latitude in range, depth optional.
    """
    if not isinstance(feature, dict):
        return None, "Feature is not an object"

    external_id = id_of(feature)
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

    longitude = optional_number(coordinates[0])
    latitude = optional_number(coordinates[1])
    if longitude is None or latitude is None:
        return None, "{0}: non-numeric coordinates".format(external_id)
    if not -180.0 <= longitude <= 180.0:
        return None, "{0}: longitude out of range ({1})".format(external_id, longitude)
    if not -90.0 <= latitude <= 90.0:
        return None, "{0}: latitude out of range ({1})".format(external_id, latitude)

    depth_km = optional_number(coordinates[2]) if len(coordinates) > 2 else None

    return (
        {
            "external_id": external_id,
            "properties": properties,
            "longitude": longitude,
            "latitude": latitude,
            "depth_km": depth_km,
        },
        None,
    )


def collect_records(
    payload: Dict[str, Any],
    normalize_feature: Callable[[Any], Tuple[Optional[Dict[str, Any]], Optional[str]]],
):
    """Normalize every feature, separating the valid records from the errors.

    Features carrying a duplicate id are kept only once: the feed is the
    single source of truth for an event, and a duplicate would otherwise
    make the upsert operate twice on the same row.
    """
    records = []
    errors = []
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
