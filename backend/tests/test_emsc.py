"""The EMSC source: its own properties on the shared FDSN shape."""

from datetime import datetime, timezone

import httpx
import pytest

from app.ingestion import IngestionError, emsc, fdsn, sources
from tests.conftest import load_fixture


def emsc_feature(**overrides):
    """A minimal valid EMSC feature, mirroring the real shape."""
    feature = {
        "type": "Feature",
        "id": "20260914_0000206",
        "properties": {
            "source_id": "2060268",
            "source_catalog": "EMSC-RTS",
            "lastupdate": "2026-09-14T15:28:33.201952Z",
            "time": "2026-09-14T15:20:22.0Z",
            "flynn_region": "FLORES SEA",
            "lat": -7.91,
            "lon": 120.59,
            "depth": 13.0,
            "evtype": "ke",
            "auth": "BMKG",
            "mag": 2.8,
            "magtype": "M",
            "unid": "20260914_0000206",
        },
        # The third coordinate is an elevation: negative below the surface.
        "geometry": {"type": "Point", "coordinates": [120.59, -7.91, -13.0]},
    }
    for key, value in overrides.items():
        if key == "properties":
            feature["properties"].update(value)
        else:
            feature[key] = value
    return feature


class TestSharedFdsn:
    """The window and the time parsing live in fdsn.py; INGV uses the same."""

    def test_the_window_is_added_with_this_sources_length(self):
        now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        url = fdsn.with_time_window("https://x.invalid/q?format=json", emsc.DEFAULT_DAYS, now=now)

        assert url == "https://x.invalid/q?format=json&starttime=2026-09-07T12%3A00%3A00"

    def test_a_zulu_time_becomes_naive_utc(self):
        assert fdsn.parse_iso_utc("2026-09-14T15:20:22.0Z") == datetime(2026, 9, 14, 15, 20, 22)

    def test_an_offset_time_is_converted_to_utc(self):
        assert fdsn.parse_iso_utc("2026-09-14T17:20:22+02:00") == datetime(2026, 9, 14, 15, 20, 22)

    @pytest.mark.parametrize("value", [None, "", "yesterday", 1726000000])
    def test_anything_else_is_none(self, value):
        assert fdsn.parse_iso_utc(value) is None


class TestNormalization:
    def test_a_real_feature_normalizes(self):
        record, error = emsc.normalize_feature(emsc_feature())

        assert error is None
        assert record["external_id"] == "20260914_0000206"
        assert record["magnitude"] == 2.8
        assert record["magnitude_type"] == "m"
        assert record["place"] == "FLORES SEA"
        assert record["event_type"] == "earthquake"
        assert record["occurred_at"] == datetime(2026, 9, 14, 15, 20, 22)
        assert record["source_updated_at"] == datetime(2026, 9, 14, 15, 28, 33, 201952)
        assert record["longitude"] == 120.59
        assert record["latitude"] == -7.91
        assert record["url"] == "https://www.seismicportal.eu/eventdetails.html?unid=20260914_0000206"

    def test_the_depth_is_positive_and_comes_from_the_property(self):
        """The coordinate is an elevation, -13 for 13 km down; that sign
        would put the event in the sky in every other source's terms."""
        record, _ = emsc.normalize_feature(emsc_feature())

        assert record["depth_km"] == 13.0

    def test_the_id_falls_back_to_unid(self):
        feature = emsc_feature()
        del feature["id"]
        record, error = emsc.normalize_feature(feature)

        assert error is None
        assert record["external_id"] == "20260914_0000206"

    def test_a_feature_without_any_id_is_rejected(self):
        feature = emsc_feature(properties={"unid": None})
        del feature["id"]
        record, error = emsc.normalize_feature(feature)

        assert record is None
        assert "id" in error

    @pytest.mark.parametrize(
        "code, expected",
        [("ke", "earthquake"), ("se", "suspected earthquake"), ("qb", "quarry blast"),
         ("KE", "earthquake"), ("ue", "unknown"), ("zz", "zz")],
    )
    def test_event_type_codes_are_spelled_out(self, code, expected):
        record, _ = emsc.normalize_feature(emsc_feature(properties={"evtype": code}))

        assert record["event_type"] == expected

    def test_a_missing_time_is_an_error(self):
        record, error = emsc.normalize_feature(emsc_feature(properties={"time": None}))

        assert record is None
        assert "time" in error

    def test_a_missing_magnitude_is_kept_as_null(self):
        record, error = emsc.normalize_feature(emsc_feature(properties={"mag": None}))

        assert error is None
        assert record["magnitude"] is None


class TestFetch:
    def test_the_window_is_added_to_the_default_url(self, monkeypatch):
        seen = {}

        def fake_get(url, timeout, follow_redirects):
            seen["url"] = url
            request = httpx.Request("GET", url)
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=request)

        monkeypatch.setattr(emsc.httpx, "get", fake_get)
        emsc.fetch_feed()

        assert seen["url"].startswith("https://www.seismicportal.eu/fdsnws/event/1/query?")
        assert "starttime=" in seen["url"]

    def test_a_non_collection_is_refused(self, monkeypatch):
        def fake_get(url, timeout, follow_redirects):
            return httpx.Response(200, json={"hello": "world"}, request=httpx.Request("GET", url))

        monkeypatch.setattr(emsc.httpx, "get", fake_get)
        with pytest.raises(IngestionError):
            emsc.fetch_feed()


class TestAgainstRealFeed:
    def test_the_captured_feed_normalizes_without_errors(self):
        payload = load_fixture("emsc_week.json")

        records, errors = emsc.normalize_feed(payload)

        assert errors == []
        assert len(records) == len(payload["features"])

    def test_every_captured_depth_is_below_the_surface(self):
        records, _ = emsc.normalize_feed(load_fixture("emsc_week.json"))

        assert all(r["depth_km"] is None or r["depth_km"] >= 0 for r in records)

    def test_the_captured_feed_has_a_suspected_earthquake(self):
        records, _ = emsc.normalize_feed(load_fixture("emsc_week.json"))

        assert any(r["event_type"] == "suspected earthquake" for r in records)


class TestRegistered:
    def test_emsc_is_a_known_source(self):
        assert sources.get_source("EMSC").key == "emsc"

    def test_its_default_feed_names_the_service(self):
        assert "seismicportal.eu" in sources.get_source("emsc").default_feed_url

    def test_a_dataset_can_be_created_for_emsc(self, client):
        response = client.post(
            "/api/datasets", json={"name": "Euro-Med Earthquakes", "source": "emsc"}
        )
        assert response.status_code == 200
        assert response.json()["source"] == "emsc"
