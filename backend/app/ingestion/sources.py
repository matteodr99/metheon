"""The registry of data sources the platform can ingest.

A dataset names its source, and everything about how that source is
fetched and normalized lives in one module per source. Adding a source means
writing such a module and listing it here — nothing else in the pipeline
needs to know it exists.

A source module must provide:

    KINDS: Tuple[str, ...]            the kinds of event it can serve, from KINDS below
    DEFAULT_FEED_URL: str
    fetch_feed(url=None, timeout=None, kind=None) -> dict
    normalize_feed(payload, kind=None) -> Tuple[List[dict], List[str]]

A dataset holds events of one kind, fixed when it is created. A source
that serves one kind needs no `kind` argument and may ignore it; one that
serves several (a multi-category feed) is told which one each run wants.
"""

from types import ModuleType
from typing import Dict, List, Optional, Tuple

from app.ingestion import emsc, eonet, gdacs, ingv, usgs

# The vocabulary of kinds, owned here and not by any source. A dataset's
# `kind` is one of these; a source declares the subset it can serve.
KINDS: Tuple[str, ...] = (
    "earthquake",
    "wildfire",
    "storm",
    "volcano",
    "flood",
    "landslide",
    "sea_ice",
    "drought",
    "dust",
    "temperature",
    "manmade",
    "snow",
    "water_color",
)


class UnknownKind(ValueError):
    """The kind asked for is not one the source serves — or no kind was
    asked for and the source serves several."""


class Source:
    """A named entry in the registry, backed by a module.

    The functions are looked up on the module at call time rather than
    captured here. That keeps the module the single place they live — and,
    not incidentally, lets a test replace `usgs.fetch_feed` and have the
    pipeline honour it.
    """

    def __init__(self, key: str, name: str, module: ModuleType):
        self.key = key
        self.name = name
        self.module = module

    @property
    def default_feed_url(self) -> str:
        return self.module.DEFAULT_FEED_URL

    @property
    def kinds(self) -> Tuple[str, ...]:
        return tuple(self.module.KINDS)

    def resolve_kind(self, requested: Optional[str]) -> str:
        """The kind a dataset of this source gets.

        Unasked, a single-kind source answers with its one kind; a
        multi-kind source cannot guess and refuses. Asked, the kind must be
        one this source serves, spelled as in KINDS.
        """
        if requested is None or not requested.strip():
            if len(self.kinds) == 1:
                return self.kinds[0]
            raise UnknownKind(
                "Source {0!r} serves several kinds; say which: {1}".format(
                    self.key, ", ".join(self.kinds)
                )
            )
        kind = requested.strip().lower()
        if kind not in self.kinds:
            raise UnknownKind(
                "Source {0!r} does not serve {1!r}; it serves {2}".format(
                    self.key, requested, ", ".join(self.kinds)
                )
            )
        return kind

    def fetch_feed(
        self,
        url: Optional[str] = None,
        timeout: Optional[float] = None,
        kind: Optional[str] = None,
    ):
        return self.module.fetch_feed(url=url, timeout=timeout, kind=kind)

    def normalize_feed(self, payload, kind: Optional[str] = None):
        return self.module.normalize_feed(payload, kind=kind)


SOURCES: Dict[str, Source] = {
    "usgs": Source("usgs", "USGS Earthquake Hazards Program", usgs),
    "ingv": Source("ingv", "INGV Istituto Nazionale di Geofisica e Vulcanologia", ingv),
    "emsc": Source("emsc", "EMSC European-Mediterranean Seismological Centre", emsc),
    "eonet": Source("eonet", "NASA EONET Earth Observatory Natural Event Tracker", eonet),
    "gdacs": Source("gdacs", "GDACS Global Disaster Alert and Coordination System", gdacs),
}


def normalize_key(source: str) -> str:
    """Datasets created before the registry existed say 'USGS'; the key is
    lowercase. Matching case-insensitively keeps them working."""
    return source.strip().lower()


def get_source(source: str) -> Optional[Source]:
    return SOURCES.get(normalize_key(source))


def known_sources() -> List[str]:
    return sorted(SOURCES.keys())
