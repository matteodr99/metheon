"""Ingestion of disaster alerts from GDACS, the Global Disaster Alert and
Coordination System of the UN and the European Commission.

Documented at https://www.gdacs.org/ (the RSS feeds under /xml/)

GDACS grades each event it tracks — earthquakes, tropical cyclones,
floods, volcanoes, wildfires, droughts — with an alert level, Green,
Orange or Red, by its expected humanitarian impact. It serves the same
storms and fires EONET does, which is what makes it worth comparing with;
and its alert level is the attribute none of the other sources has.

The feed is RSS, not JSON: the JSON search API answers at most a hundred
events per query with no way to page, and a week of wildfires is more
than that. The seven-day RSS carries every event of every type, so one
request serves any kind; the items of other types are dropped on fetch.
Parsed with the standard library — one XML feed does not pay for a
dependency.
"""

import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

import httpx

from app.ingestion import IngestionError
from app.ingestion.geojson import collect_records

# GDACS's event type codes, by the kind in the registry's vocabulary.
EVENT_TYPE_BY_KIND = {
    "earthquake": "EQ",
    "storm": "TC",
    "flood": "FL",
    "volcano": "VO",
    "wildfire": "WF",
    "drought": "DR",
}

KINDS = tuple(EVENT_TYPE_BY_KIND)

DEFAULT_FEED_URL = os.getenv("GDACS_FEED_URL", "https://www.gdacs.org/xml/rss_7d.xml")

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GDACS_TIMEOUT_SECONDS", "30"))

# GDACS's units, in the spelling the other sources use, so a dataset of
# one kind has one unit whichever source filled it: EONET's storms are in
# knots and its fires in hectares.
KILOMETRES_PER_HOUR_PER_KNOT = 1.852
UNITS = {"ha": "hectares", "M": "m", "km/h": "kts", "km2": "km2"}

_DEPTH = re.compile(r"Depth:\s*([0-9.]+)\s*km")


def _number(value: Any) -> Optional[float]:
    """A float from XML text, or None. Everything in RSS is a string."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _local(tag: str) -> str:
    """`{http://www.gdacs.org}eventtype` → `eventtype`."""
    return tag.rsplit("}", 1)[-1]


def item_to_dict(item: ElementTree.Element) -> Dict[str, Any]:
    """Flatten one RSS `<item>` into a dictionary of its fields.

    Namespaces are dropped: `gdacs:eventid` becomes `eventid`. `severity`
    keeps its `unit` and `value` attributes as a nested dictionary, and the
    point's `lat`/`long` are lifted out of `geo:Point`.
    """
    fields: Dict[str, Any] = {}
    for child in item:
        name = _local(child.tag)
        if name == "Point":
            for coordinate in child:
                fields[_local(coordinate.tag)] = (coordinate.text or "").strip()
        elif name == "severity":
            fields["severity"] = {
                "unit": child.get("unit", ""),
                "value": child.get("value", ""),
                "text": (child.text or "").strip(),
            }
        elif len(child) == 0:
            fields[name] = (child.text or "").strip()
    return fields


def parse_feed(document: bytes, kind: str) -> Dict[str, Any]:
    """The items of one kind, as dictionaries, from the RSS document."""
    event_type = EVENT_TYPE_BY_KIND.get(kind)
    if event_type is None:
        raise IngestionError("GDACS does not serve {0!r} events".format(kind))
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise IngestionError("The GDACS feed is not valid XML: {0}".format(exc))
    items = [item_to_dict(item) for item in root.iter("item")]
    if not items and root.find("channel") is None:
        raise IngestionError("Unexpected payload: an RSS document was expected")
    return {"items": [item for item in items if item.get("eventtype") == event_type]}


def fetch_feed(
    url: Optional[str] = None,
    timeout: Optional[float] = None,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch the RSS and keep the items of the dataset's kind."""
    if kind is None:
        raise IngestionError("GDACS serves several kinds; the dataset must say which")
    url = url or DEFAULT_FEED_URL
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionError("Could not fetch the GDACS feed: {0}".format(exc))

    return parse_feed(response.content, kind)


def _parse_rfc2822(value: Any) -> Optional[datetime]:
    """`Mon, 14 Sep 2026 21:13:15 GMT` as naive UTC; None when it is not one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _measure(item: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    severity = item.get("severity")
    if not isinstance(severity, dict):
        return None, None
    value = _number(severity.get("value"))
    unit = severity.get("unit")
    if value is None or not isinstance(unit, str) or not unit:
        # A flood or an eruption with "severity 0" and no unit is unmeasured,
        # not a measure of zero.
        return None, None
    if unit == "km/h":
        value = round(value / KILOMETRES_PER_HOUR_PER_KNOT, 1)
    return value, UNITS.get(unit, unit)


def normalize_item(item: Any, kind: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Normalize one GDACS alert into the shared record."""
    if not isinstance(item, dict):
        return None, "Item is not an object"
    external_id = item.get("guid") or None
    if not external_id:
        event_type, event_id = item.get("eventtype"), item.get("eventid")
        if event_type and event_id:
            external_id = "{0}{1}".format(event_type, event_id)
    if not isinstance(external_id, str) or not external_id:
        return None, "Item without a usable id"
    if item.get("eventtype") != EVENT_TYPE_BY_KIND.get(kind):
        return None, "{0}: not a {1}".format(external_id, kind)

    longitude = _number(item.get("long"))
    latitude = _number(item.get("lat"))
    if longitude is None or latitude is None:
        return None, "{0}: missing coordinates".format(external_id)
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None, "{0}: coordinates out of range ({1}, {2})".format(external_id, longitude, latitude)

    occurred_at = _parse_rfc2822(item.get("fromdate"))
    if occurred_at is None:
        return None, "{0}: missing or invalid fromdate".format(external_id)
    ended_at = _parse_rfc2822(item.get("todate"))
    if ended_at is not None and ended_at <= occurred_at:
        ended_at = None

    magnitude, unit = _measure(item)
    severity = item.get("severity") if isinstance(item.get("severity"), dict) else {}

    attributes: Dict[str, Any] = {
        "alert_level": (item.get("alertlevel") or "").lower() or None,
        "alert_score": _number(item.get("alertscore")),
        "severity_text": severity.get("text") or None,
        "country": item.get("country") or None,
        "iso3": item.get("iso3") or None,
        "episode_id": _number(item.get("episodeid")),
    }
    # An earthquake's depth is only in the severity text; the key is the
    # one the seismic sources use, so it lines up in a comparison.
    depth = _DEPTH.search(severity.get("text") or "")
    if depth is not None:
        attributes["depth_km"] = float(depth.group(1))
    attributes = {key: value for key, value in attributes.items() if value is not None}

    record = {
        "external_id": external_id,
        "title": item.get("title") or item.get("eventname") or None,
        "event_type": kind,
        "occurred_at": occurred_at,
        "ended_at": ended_at,
        "source_updated_at": _parse_rfc2822(item.get("datemodified")),
        "longitude": longitude,
        "latitude": latitude,
        "geometry": None,
        "magnitude": magnitude,
        "magnitude_unit": unit,
        "attributes": attributes,
        "url": item.get("link") or None,
    }
    return record, None


def normalize_feed(
    payload: Dict[str, Any], kind: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize every alert, returning the valid records and the errors."""
    if kind is None:
        raise IngestionError("GDACS serves several kinds; the dataset must say which")
    return collect_records(payload, lambda item: normalize_item(item, kind), items="items")
