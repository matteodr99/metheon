"""The registry of data sources the platform can ingest.

A dataset names its source, and everything about how that source is
fetched and normalized lives in one module per source. Adding a source means
writing such a module and listing it here — nothing else in the pipeline
needs to know it exists.

A source module must provide:

    DEFAULT_FEED_URL: str
    fetch_feed(url: Optional[str] = None, timeout: Optional[float] = None) -> dict
    normalize_feed(payload: dict) -> Tuple[List[dict], List[str]]
"""

from types import ModuleType
from typing import Dict, List, Optional

from app.ingestion import usgs


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

    def fetch_feed(self, url: Optional[str] = None, timeout: Optional[float] = None):
        return self.module.fetch_feed(url=url, timeout=timeout)

    def normalize_feed(self, payload):
        return self.module.normalize_feed(payload)


SOURCES: Dict[str, Source] = {
    "usgs": Source("usgs", "USGS Earthquake Hazards Program", usgs),
}


def normalize_key(source: str) -> str:
    """Datasets created before the registry existed say 'USGS'; the key is
    lowercase. Matching case-insensitively keeps them working."""
    return source.strip().lower()


def get_source(source: str) -> Optional[Source]:
    return SOURCES.get(normalize_key(source))


def known_sources() -> List[str]:
    return sorted(SOURCES.keys())
