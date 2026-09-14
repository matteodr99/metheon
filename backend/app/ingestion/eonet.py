"""Ingestion of natural events from NASA EONET, the Earth Observatory
Natural Event Tracker.

Documented at https://eonet.gsfc.nasa.gov/docs/v3

EONET curates events of many kinds — wildfires, storms, floods, sea ice —
from satellite imagery and partner reports, one feed for all of them and a
`category` parameter to ask for one. This is the first source that serves
several kinds: a dataset picks one, and each run asks for that category
over the last EONET_DAYS.

Not GeoJSON. An event carries a list of dated geometries — one point for
a fire, a track of points for a storm, polygons for a flood — each with an
optional measurement. The shared columns take the earliest date, the latest
position and the peak measurement; the whole list is kept as geometry when
it is more than a single point.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.ingestion import IngestionError
from app.ingestion.geojson import collect_records, optional_number

# EONET's category ids, by the kind in the registry's vocabulary.
CATEGORY_BY_KIND = {
    "wildfire": "wildfires",
    "storm": "severeStorms",
    "volcano": "volcanoes",
    "flood": "floods",
    "landslide": "landslides",
    "sea_ice": "seaLakeIce",
    "drought": "drought",
    "dust": "dustHaze",
    "temperature": "tempExtremes",
    "manmade": "manmade",
    "snow": "snow",
    "water_color": "waterColor",
    "earthquake": "earthquakes",
}

KINDS = tuple(CATEGORY_BY_KIND)

DEFAULT_FEED_URL = os.getenv(
    "EONET_FEED_URL", "https://eonet.gsfc.nasa.gov/api/v3/events?status=all"
)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("EONET_TIMEOUT_SECONDS", "30"))

DEFAULT_DAYS = int(os.getenv("EONET_DAYS", "7"))

# One unit per kind: fires are reported in hectares or acres, and a dataset
# comparing the two would be comparing nothing.
HECTARES_PER_ACRE = 0.404686
UNITS = {"hectare": "hectares", "hectares": "hectares", "acres": "hectares", "acre": "hectares"}


def with_category_and_window(
    url: str, kind: str, days: int = DEFAULT_DAYS
) -> str:
    """Ask for one category over the last `days`, unless the url says so.

    A url that already names either is left alone on that point, so a
    caller can ask for exactly what it wants.
    """
    category = CATEGORY_BY_KIND.get(kind)
    if category is None:
        raise IngestionError("EONET does not serve {0!r} events".format(kind))
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query.setdefault("category", [category])
    query.setdefault("days", [str(days)])
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def fetch_feed(
    url: Optional[str] = None,
    timeout: Optional[float] = None,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Query EONET for one kind and return the payload as a dictionary."""
    if kind is None:
        raise IngestionError("EONET serves several kinds; the dataset must say which")
    url = with_category_and_window(url or DEFAULT_FEED_URL, kind)
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise IngestionError("Could not fetch the EONET feed: {0}".format(exc))
    except ValueError as exc:
        raise IngestionError("The EONET feed is not valid JSON: {0}".format(exc))

    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise IngestionError("Unexpected payload: an object with an `events` list was expected")

    return payload


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _centroid(coordinates: Any) -> Optional[Tuple[float, float]]:
    """The mean of a polygon's outer ring, or of a point; None when unusable.

    Good enough for a marker on a map: a flood polygon spanning a valley
    still gets one dot in the middle of it.
    """
    if not isinstance(coordinates, list) or not coordinates:
        return None
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in coordinates[:2]) and len(coordinates) >= 2:
        return float(coordinates[0]), float(coordinates[1])
    ring = coordinates[0] if isinstance(coordinates[0], list) and coordinates[0] and isinstance(coordinates[0][0], list) else coordinates
    points = [p for p in ring if isinstance(p, list) and len(p) >= 2 and all(isinstance(v, (int, float)) for v in p[:2])]
    if not points:
        return None
    return (
        sum(float(p[0]) for p in points) / len(points),
        sum(float(p[1]) for p in points) / len(points),
    )


def _measure(entry: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    value = optional_number(entry.get("magnitudeValue"))
    unit = entry.get("magnitudeUnit")
    if value is None or not isinstance(unit, str) or not unit:
        return None, None
    if unit in ("acres", "acre"):
        value = round(value * HECTARES_PER_ACRE, 2)
    return value, UNITS.get(unit, unit)


def normalize_event(event: Any, kind: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize one EONET event into the shared record."""
    if not isinstance(event, dict):
        return None, "Event is not an object"
    external_id = event.get("id")
    if not isinstance(external_id, str) or not external_id:
        return None, "Event without a usable id"

    entries = [g for g in event.get("geometry") or [] if isinstance(g, dict)]
    dated = sorted(
        ((_parse_time(g.get("date")), g) for g in entries),
        key=lambda pair: pair[0] or datetime.min,
    )
    dated = [(moment, g) for moment, g in dated if moment is not None]
    if not dated:
        return None, "{0}: no dated geometry".format(external_id)

    first_time, _ = dated[0]
    _, latest = dated[-1]
    point = _centroid(latest.get("coordinates"))
    # EONET writes points as [longitude, latitude], as GeoJSON does, but
    # its polygons the other way round: every flood polygon captured on
    # 2026-09-14 put Croatia at 43.5, 16.3. Swapped here, so the marker
    # lands in Croatia; the geometry column keeps the coordinates as sent.
    if point is not None and latest.get("type") == "Polygon":
        point = (point[1], point[0])
    if point is None:
        return None, "{0}: latest geometry has no usable coordinates".format(external_id)
    longitude, latitude = point
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None, "{0}: coordinates out of range ({1}, {2})".format(external_id, longitude, latitude)

    # The peak measurement over the event's life: a fire's area only grows,
    # a storm's wind peaks and fades, and the peak is what both are known by.
    measures = [_measure(g) for _, g in dated]
    measures = [(v, u) for v, u in measures if v is not None]
    magnitude, unit = max(measures, key=lambda m: m[0]) if measures else (None, None)

    # Everything beyond a single point is kept as it came, ordered by date:
    # a storm track, a flood's polygons.
    geometry = None
    if len(dated) > 1 or latest.get("type") != "Point":
        geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {"type": g.get("type"), "coordinates": g.get("coordinates"), "date": g.get("date")}
                for _, g in dated
            ],
        }

    sources = [s.get("id") for s in event.get("sources") or [] if isinstance(s, dict) and s.get("id")]
    source_url = next(
        (s.get("url") for s in event.get("sources") or [] if isinstance(s, dict) and s.get("url")),
        None,
    )

    record = {
        "external_id": external_id,
        "title": event.get("title"),
        "event_type": kind,
        "occurred_at": first_time,
        "ended_at": _parse_time(event.get("closed")),
        "source_updated_at": None,
        "longitude": longitude,
        "latitude": latitude,
        "geometry": geometry,
        "magnitude": magnitude,
        "magnitude_unit": unit,
        "attributes": {
            "category": CATEGORY_BY_KIND.get(kind, kind),
            "sources": sources,
            "samples": len(dated),
        },
        # EONET's own link is an API document; a partner's page, when there
        # is one, is what a reader can open.
        "url": source_url or event.get("link"),
    }
    return record, None


def normalize_feed(
    payload: Dict[str, Any], kind: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every event, returning the valid records and the errors."""
    if kind is None:
        raise IngestionError("EONET serves several kinds; the dataset must say which")
    return collect_records(payload, lambda event: normalize_event(event, kind), items="events")
