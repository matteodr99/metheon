"""The EONET source: many kinds in one feed, dated geometries, one measure."""

from datetime import datetime

import httpx
import pytest

from app.db import repository
from app.ingestion import IngestionError, eonet, sources
from tests.conftest import load_fixture, requires_postgres


def fire(**overrides):
    """A minimal EONET wildfire, mirroring the real shape."""
    event = {
        "id": "EONET_24268",
        "title": "Wildfire in Namibia 1031934",
        "description": None,
        "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_24268",
        "closed": "2026-09-12T00:00:00Z",
        "categories": [{"id": "wildfires", "title": "Wildfires"}],
        "sources": [{"id": "GDACS", "url": "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1031934"}],
        "geometry": [
            {
                "magnitudeValue": 5747.0,
                "magnitudeUnit": "hectare",
                "date": "2026-09-11T19:00:00Z",
                "type": "Point",
                "coordinates": [16.525, -19.219],
            }
        ],
    }
    event.update(overrides)
    return event


def storm():
    """A track: three dated points, the wind peaking in the middle."""
    return fire(
        id="EONET_24300",
        title="Tropical Storm Norbert",
        closed=None,
        categories=[{"id": "severeStorms", "title": "Severe Storms"}],
        sources=[],
        geometry=[
            {"magnitudeValue": 35.0, "magnitudeUnit": "kts", "date": "2026-09-10T00:00:00Z", "type": "Point", "coordinates": [-117.3, 16.4]},
            {"magnitudeValue": 60.0, "magnitudeUnit": "kts", "date": "2026-09-10T12:00:00Z", "type": "Point", "coordinates": [-118.6, 16.5]},
            {"magnitudeValue": 40.0, "magnitudeUnit": "kts", "date": "2026-09-11T00:00:00Z", "type": "Point", "coordinates": [-119.9, 16.5]},
        ],
    )


class TestKinds:
    def test_it_serves_every_category_as_a_kind(self):
        assert set(eonet.KINDS) <= set(sources.KINDS)
        assert "wildfire" in eonet.KINDS and "storm" in eonet.KINDS

    def test_the_query_asks_for_the_kinds_category_and_the_window(self):
        url = eonet.with_category_and_window("https://x.invalid/events?status=all", "wildfire", days=7)

        assert url == "https://x.invalid/events?status=all&category=wildfires&days=7"

    def test_a_url_naming_its_own_category_or_window_is_left_alone(self):
        url = eonet.with_category_and_window("https://x.invalid/events?category=floods&days=30", "wildfire")

        assert url == "https://x.invalid/events?category=floods&days=30"

    def test_a_kind_it_does_not_serve_is_an_error(self):
        with pytest.raises(IngestionError):
            eonet.with_category_and_window("https://x.invalid/events", "meteorite")

    def test_fetching_without_a_kind_is_an_error(self):
        with pytest.raises(IngestionError):
            eonet.fetch_feed()

    def test_the_fetch_asks_for_the_category(self, monkeypatch):
        seen = {}

        def fake_get(url, timeout, follow_redirects):
            seen["url"] = url
            return httpx.Response(200, json={"events": []}, request=httpx.Request("GET", url))

        monkeypatch.setattr(eonet.httpx, "get", fake_get)
        eonet.fetch_feed(kind="storm")

        assert "category=severeStorms" in seen["url"]
        assert "days=" in seen["url"]

    def test_a_payload_without_events_is_refused(self, monkeypatch):
        def fake_get(url, timeout, follow_redirects):
            return httpx.Response(200, json={"type": "FeatureCollection"}, request=httpx.Request("GET", url))

        monkeypatch.setattr(eonet.httpx, "get", fake_get)
        with pytest.raises(IngestionError):
            eonet.fetch_feed(kind="wildfire")


class TestNormalization:
    def test_a_fire_normalizes(self):
        record, error = eonet.normalize_event(fire(), "wildfire")

        assert error is None
        assert record["external_id"] == "EONET_24268"
        assert record["title"] == "Wildfire in Namibia 1031934"
        assert record["event_type"] == "wildfire"
        assert record["occurred_at"] == datetime(2026, 9, 11, 19, 0)
        assert record["ended_at"] == datetime(2026, 9, 12, 0, 0)
        assert (record["longitude"], record["latitude"]) == (16.525, -19.219)
        assert (record["magnitude"], record["magnitude_unit"]) == (5747.0, "hectares")
        assert record["geometry"] is None
        assert record["attributes"] == {"category": "wildfires", "sources": ["GDACS"], "samples": 1}
        assert record["url"] == "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1031934"

    def test_acres_become_hectares(self):
        """One unit per kind, or a dataset would compare fires in two."""
        event = fire()
        event["geometry"][0].update(magnitudeValue=1000.0, magnitudeUnit="acres")
        record, _ = eonet.normalize_event(event, "wildfire")

        assert (record["magnitude"], record["magnitude_unit"]) == (404.69, "hectares")

    def test_a_track_takes_the_first_time_the_last_position_and_the_peak(self):
        record, error = eonet.normalize_event(storm(), "storm")

        assert error is None
        assert record["occurred_at"] == datetime(2026, 9, 10, 0, 0)
        assert (record["longitude"], record["latitude"]) == (-119.9, 16.5)
        assert (record["magnitude"], record["magnitude_unit"]) == (60.0, "kts")
        assert record["ended_at"] is None
        assert record["geometry"]["type"] == "GeometryCollection"
        assert [g["coordinates"] for g in record["geometry"]["geometries"]] == [
            [-117.3, 16.4], [-118.6, 16.5], [-119.9, 16.5]
        ]
        assert record["attributes"]["samples"] == 3

    def test_geometries_are_ordered_by_date_whatever_the_feed_order(self):
        event = storm()
        event["geometry"].reverse()
        record, _ = eonet.normalize_event(event, "storm")

        assert (record["longitude"], record["latitude"]) == (-119.9, 16.5)
        assert record["occurred_at"] == datetime(2026, 9, 10, 0, 0)

    def test_a_polygon_gives_its_centre_with_latitude_first(self):
        """EONET's polygons come as [latitude, longitude], unlike its points."""
        event = fire(
            id="EONET_24157",
            title="Flood in Croatia",
            categories=[{"id": "floods", "title": "Floods"}],
            geometry=[{
                "magnitudeValue": None, "magnitudeUnit": None, "date": "2026-09-10T20:00:00Z",
                "type": "Polygon",
                "coordinates": [[[43.5, 16.3], [43.7, 16.3], [43.7, 16.5], [43.5, 16.5], [43.5, 16.3]]],
            }],
        )
        record, error = eonet.normalize_event(event, "flood")

        assert error is None
        assert record["longitude"] == pytest.approx(16.38)
        assert record["latitude"] == pytest.approx(43.58)
        assert record["magnitude"] is None
        assert record["geometry"]["geometries"][0]["type"] == "Polygon"

    def test_the_api_link_is_the_fallback_url(self):
        record, _ = eonet.normalize_event(fire(sources=[]), "wildfire")

        assert record["url"] == "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_24268"

    def test_an_event_without_dated_geometry_is_rejected(self):
        record, error = eonet.normalize_event(fire(geometry=[]), "wildfire")

        assert record is None
        assert "geometry" in error

    def test_an_event_without_an_id_is_rejected(self):
        record, error = eonet.normalize_event(fire(id=None), "wildfire")

        assert record is None
        assert "id" in error

    def test_normalizing_without_a_kind_is_an_error(self):
        with pytest.raises(IngestionError):
            eonet.normalize_feed({"events": [fire()]})


class TestAgainstRealFeed:
    @pytest.mark.parametrize("kind, category", [("wildfire", "wildfires"), ("storm", "severeStorms"), ("flood", "floods"), ("sea_ice", "seaLakeIce")])
    def test_the_captured_feed_normalizes_without_errors(self, kind, category):
        payload = load_fixture("eonet_month.json")
        payload["events"] = [e for e in payload["events"] if e["categories"][0]["id"] == category]

        records, errors = eonet.normalize_feed(payload, kind)

        assert errors == []
        assert len(records) == len(payload["events"]) > 0
        assert all(-180 <= r["longitude"] <= 180 and -90 <= r["latitude"] <= 90 for r in records)

    def test_every_fire_is_measured_in_hectares(self):
        payload = load_fixture("eonet_month.json")
        payload["events"] = [e for e in payload["events"] if e["categories"][0]["id"] == "wildfires"]

        records, _ = eonet.normalize_feed(payload, "wildfire")

        assert {r["magnitude_unit"] for r in records} == {"hectares"}

    def test_the_captured_floods_land_where_they_happened(self):
        payload = load_fixture("eonet_month.json")
        croatia = [e for e in payload["events"] if e["title"].startswith("Flood in Croatia")]
        assert croatia, "the fixture should carry the Croatian flood"

        record, _ = eonet.normalize_event(croatia[0], "flood")

        assert 13 < record["longitude"] < 20 and 42 < record["latitude"] < 47


class TestRegistered:
    def test_eonet_is_a_known_multi_kind_source(self):
        source = sources.get_source("eonet")
        assert source.key == "eonet"
        assert len(source.kinds) > 1

    @requires_postgres
    def test_a_dataset_needs_a_kind(self, client):
        refused = client.post("/api/datasets", json={"name": "Fires", "source": "eonet"})
        assert refused.status_code == 422

        created = client.post("/api/datasets", json={"name": "Fires", "source": "eonet", "kind": "wildfire"})
        assert created.status_code == 200
        assert created.json()["kind"] == "wildfire"

    @requires_postgres
    def test_a_fire_dataset_ingests_and_lists(self, db, client, monkeypatch):
        payload = load_fixture("eonet_month.json")
        payload["events"] = [e for e in payload["events"] if e["categories"][0]["id"] == "wildfires"]
        monkeypatch.setattr(eonet, "fetch_feed", lambda url=None, timeout=None, kind=None: payload)
        with db() as connection:
            dataset = repository.create_dataset(connection, "Fires", "eonet", None, "wildfire")
            import_id = repository.create_import(connection, dataset["id"], eonet.DEFAULT_FEED_URL)

        from app.ingestion import runner
        result = runner.run_import(import_id)

        assert result["inserted"] == len(payload["events"])
        page = client.get("/api/datasets/{0}/events?limit=1".format(dataset["id"])).json()
        assert page["items"][0]["magnitude_unit"] == "hectares"
        assert page["items"][0]["attributes"]["category"] == "wildfires"
