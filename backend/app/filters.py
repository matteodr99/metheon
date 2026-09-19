"""What a set of event filters may say, checked once for REST and GraphQL.

The REST routes take their filters through `main.EventFilters` and the
GraphQL schema through `graphql.EventFilterInput`; both hand the values to
`problem` and refuse with its sentence. Two copies of these rules would be
two ways for the same filter to be accepted on one path and refused on the
other.
"""

from typing import Any, Dict, Optional

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

# Degrees. FastAPI checks these on the query string before the values get
# here; GraphQL has no such step, so the check is also made here.
BOUNDS = {
    "min_latitude": (-90, 90),
    "max_latitude": (-90, 90),
    "min_longitude": (-180, 180),
    "max_longitude": (-180, 180),
}

# A range whose bounds are the wrong way round silently matches nothing,
# which reads as "no data" rather than as the mistake it is. A box that
# crosses the antimeridian would be an inverted longitude range and is
# refused rather than supported.
RANGES = (
    ("min_magnitude", "max_magnitude", "magnitude"),
    ("start_time", "end_time", "time"),
    ("min_latitude", "max_latitude", "latitude"),
    ("min_longitude", "max_longitude", "longitude"),
)


def problem(values: Dict[str, Any]) -> Optional[str]:
    """The first thing wrong with these filters, as a sentence, or None."""
    for name, (low, high) in BOUNDS.items():
        value = values.get(name)
        if value is not None and not low <= value <= high:
            return "{0} must be between {1} and {2}".format(name, low, high)

    for lower_name, upper_name, label in RANGES:
        lower, upper = values.get(lower_name), values.get(upper_name)
        if lower is not None and upper is not None and lower > upper:
            return "The {0} range is inverted: {1} is greater than {2}".format(
                label, lower, upper
            )

    return None


def page_problem(limit: int, offset: int) -> Optional[str]:
    """What is wrong with a page request, or None."""
    if not 1 <= limit <= MAX_PAGE_SIZE:
        return "limit must be between 1 and {0}".format(MAX_PAGE_SIZE)
    if offset < 0:
        return "offset must be 0 or more"
    return None
