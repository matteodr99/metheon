import io
import json
import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with io.open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def real_feed():
    """A real USGS all_hour response, captured on 2026-09-09.

    Keeping a genuine payload guards against the feed shape being
    misremembered: the handcrafted features in the tests below only cover
    the cases they were written for.
    """
    return load_fixture("usgs_all_hour.json")


def make_feature(**overrides):
    """Build a minimal valid feature, overriding single fields per test."""
    feature = {
        "id": "test1",
        "properties": {
            "time": 1788942354913,
            "updated": 1788942565428,
            "mag": 1.4,
            "magType": "ml",
            "place": "26 km SW of Garden City, Texas",
            "type": "earthquake",
            "tsunami": 0,
            "sig": 30,
            "url": "https://example.invalid/event",
        },
        "geometry": {"type": "Point", "coordinates": [-101.696, 31.715, 2.4688]},
    }
    for key, value in overrides.items():
        if key in ("properties", "geometry") and isinstance(value, dict):
            feature[key] = value
        else:
            feature[key] = value
    return feature
