"""The GDACS source: graded alerts from an RSS feed, many kinds in one."""

import os
from datetime import datetime

import httpx
import pytest

from app.db import repository
from app.ingestion import IngestionError, gdacs, sources
from tests.conftest import FIXTURES_DIR, load_fixture, requires_postgres

RSS = os.path.join(FIXTURES_DIR, "gdacs_week.xml")


def rss_document():
    with open(RSS, "rb") as handle:
        return handle.read()


def item(**overrides):
    """A GDACS wildfire alert as `item_to_dict` flattens it."""
    fields = {
        "title": "Green forest fire notification in Namibia",
        "link": "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1031934",
        "pubDate": "Mon, 14 Sep 2026 15:08:41 GMT",
        "datemodified": "Mon, 14 Sep 2026 15:08:41 GMT",
        "fromdate": "Sat, 12 Sep 2026 00:00:00 GMT",
        "todate": "Mon, 14 Sep 2026 00:00:00 GMT",
        "guid": "WF1031934",
        "lat": "-19.2",
        "long": "16.5",
        "eventtype": "WF",
        "alertlevel": "Green",
        "alertscore": "1",
        "eventname": "",
        "eventid": "1031934",
        "episodeid": "5",
        "country": "Namibia",
        "iso3": "NAM",
        "severity": {"unit": "ha", "value": "13429", "text": "Green impact for forestfire in 13429 ha"},
    }
    fields.update(overrides)
    return fields


class TestTheFeed:
    def test_it_serves_kinds_from_the_vocabulary(self):
        assert set(gdacs.KINDS) <= set(sources.KINDS)
        assert {"earthquake", "storm", "wildfire", "flood"} <= set(gdacs.KINDS)

    def test_the_rss_is_flattened_and_filtered_to_the_kind(self):
        payload = gdacs.parse_feed(rss_document(), "earthquake")

        assert payload["items"]
        assert {entry["eventtype"] for entry in payload["items"]} == {"EQ"}
        first = payload["items"][0]
        assert first["guid"].startswith("EQ")
        assert {"lat", "long", "fromdate", "alertlevel", "severity", "link"} <= set(first)
        assert first["severity"]["unit"] == "M"

    def test_a_kind_it_does_not_serve_is_an_error(self):
        with pytest.raises(IngestionError):
            gdacs.parse_feed(rss_document(), "sea_ice")

    def test_a_document_that_is_not_rss_is_refused(self):
        with pytest.raises(IngestionError):
            gdacs.parse_feed(b"<html><body>maintenance</body></html>", "wildfire")
        with pytest.raises(IngestionError):
            gdacs.parse_feed(b"{\"message\": \"Eventtype is required.\"}", "wildfire")

    def test_fetching_without_a_kind_is_an_error(self):
        with pytest.raises(IngestionError):
            gdacs.fetch_feed()

    def test_the_fetch_keeps_only_the_kind_asked_for(self, monkeypatch):
        seen = {}

        def fake_get(url, timeout, follow_redirects):
            seen["url"] = url
            return httpx.Response(200, content=rss_document(), request=httpx.Request("GET", url))

        monkeypatch.setattr(gdacs.httpx, "get", fake_get)
        payload = gdacs.fetch_feed(kind="storm")

        assert seen["url"] == gdacs.DEFAULT_FEED_URL
        assert {entry["eventtype"] for entry in payload["items"]} == {"TC"}


class TestNormalization:
    def test_a_fire_alert_normalizes(self):
        record, error = gdacs.normalize_item(item(), "wildfire")

        assert error is None
        assert record["external_id"] == "WF1031934"
        assert record["title"] == "Green forest fire notification in Namibia"
        assert record["event_type"] == "wildfire"
        assert record["occurred_at"] == datetime(2026, 9, 12, 0, 0)
        assert record["ended_at"] == datetime(2026, 9, 14, 0, 0)
        assert record["source_updated_at"] == datetime(2026, 9, 14, 15, 8, 41)
        assert (record["longitude"], record["latitude"]) == (16.5, -19.2)
        assert (record["magnitude"], record["magnitude_unit"]) == (13429.0, "hectares")
        assert record["url"] == "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1031934"

    def test_the_alert_level_and_the_rest_are_attributes(self):
        record, _ = gdacs.normalize_item(item(), "wildfire")

        assert record["attributes"] == {
            "alert_level": "green",
            "alert_score": 1.0,
            "severity_text": "Green impact for forestfire in 13429 ha",
            "country": "Namibia",
            "iso3": "NAM",
            "episode_id": 5.0,
        }

    def test_an_item_of_another_type_is_refused(self):
        record, error = gdacs.normalize_item(item(), "earthquake")

        assert record is None
        assert "not a earthquake" in error or "not a" in error

    def test_wind_in_kilometres_per_hour_becomes_knots(self):
        """EONET reports storms in knots; one kind, one unit."""
        storm = item(eventtype="TC", guid="TC1001321", severity={"unit": "km/h", "value": "101.8512", "text": ""})
        record, _ = gdacs.normalize_item(storm, "storm")

        assert (record["magnitude"], record["magnitude_unit"]) == (55.0, "kts")

    def test_an_earthquakes_depth_is_read_from_the_severity_text(self):
        quake = item(
            eventtype="EQ", guid="EQ1566251",
            fromdate="Mon, 14 Sep 2026 21:13:15 GMT", todate="Mon, 14 Sep 2026 21:13:15 GMT",
            severity={"unit": "M", "value": "4.9", "text": "Magnitude 4.9M, Depth:48.4km"},
        )
        record, _ = gdacs.normalize_item(quake, "earthquake")

        assert (record["magnitude"], record["magnitude_unit"]) == (4.9, "m")
        assert record["attributes"]["depth_km"] == 48.4
        assert record["ended_at"] is None

    def test_a_date_with_an_offset_is_converted_to_utc(self):
        """GDACS writes GMT; a feed that ever wrote an offset must not shift."""
        record, _ = gdacs.normalize_item(item(fromdate="Sat, 12 Sep 2026 02:00:00 +0200"), "wildfire")

        assert record["occurred_at"] == datetime(2026, 9, 12, 0, 0)

    def test_a_severity_without_a_unit_is_no_measure(self):
        flood = item(eventtype="FL", guid="FL1", severity={"unit": "", "value": "0", "text": ""})
        record, _ = gdacs.normalize_item(flood, "flood")

        assert record["magnitude"] is None
        assert record["magnitude_unit"] is None

    def test_a_missing_id_falls_back_to_type_and_number_then_fails(self):
        record, _ = gdacs.normalize_item(item(guid=""), "wildfire")
        assert record["external_id"] == "WF1031934"

        record, error = gdacs.normalize_item(item(guid="", eventid=""), "wildfire")
        assert record is None
        assert "id" in error

    def test_missing_or_bad_coordinates_are_errors(self):
        record, error = gdacs.normalize_item(item(lat=""), "wildfire")
        assert record is None and "coordinates" in error

        record, error = gdacs.normalize_item(item(lat="95"), "wildfire")
        assert record is None and "out of range" in error

    def test_a_missing_fromdate_is_an_error(self):
        record, error = gdacs.normalize_item(item(fromdate="yesterday"), "wildfire")

        assert record is None
        assert "fromdate" in error

    def test_normalizing_without_a_kind_is_an_error(self):
        with pytest.raises(IngestionError):
            gdacs.normalize_feed({"items": [item()]})


class TestAgainstRealFeed:
    @pytest.mark.parametrize("kind", ["wildfire", "earthquake", "drought", "flood", "storm"])
    def test_the_captured_feed_normalizes_without_errors(self, kind):
        payload = gdacs.parse_feed(rss_document(), kind)

        records, errors = gdacs.normalize_feed(payload, kind)

        assert errors == []
        assert len(records) == len(payload["items"]) > 0

    def test_the_captured_feed_carries_an_orange_alert(self):
        levels = set()
        for kind in gdacs.KINDS:
            records, _ = gdacs.normalize_feed(gdacs.parse_feed(rss_document(), kind), kind)
            levels |= {r["attributes"].get("alert_level") for r in records}

        assert "orange" in levels

    def test_every_captured_quake_has_a_depth(self):
        records, _ = gdacs.normalize_feed(gdacs.parse_feed(rss_document(), "earthquake"), "earthquake")

        assert all("depth_km" in r["attributes"] for r in records)


class TestRegistered:
    def test_gdacs_is_a_known_multi_kind_source(self):
        source = sources.get_source("gdacs")
        assert source.key == "gdacs"
        assert "earthquake" in source.kinds and "wildfire" in source.kinds

    @requires_postgres
    def test_a_fire_dataset_ingests_and_compares_with_eonet(self, db, client, monkeypatch):
        """The point of GDACS: the same fire, reported by two curators."""
        from app.ingestion import eonet, runner

        eonet_payload = load_fixture("eonet_month.json")
        eonet_payload["events"] = [e for e in eonet_payload["events"] if e["categories"][0]["id"] == "wildfires"]
        monkeypatch.setattr(gdacs, "fetch_feed", lambda url=None, timeout=None, kind=None: gdacs.parse_feed(rss_document(), kind))
        monkeypatch.setattr(eonet, "fetch_feed", lambda url=None, timeout=None, kind=None: eonet_payload)

        with db() as connection:
            fires_gdacs = repository.create_dataset(connection, "GDACS fires", "gdacs", None, "wildfire")
            fires_eonet = repository.create_dataset(connection, "EONET fires", "eonet", None, "wildfire")
            run_gdacs = repository.create_import(connection, fires_gdacs["id"], gdacs.DEFAULT_FEED_URL)
            run_eonet = repository.create_import(connection, fires_eonet["id"], eonet.DEFAULT_FEED_URL)
        runner.run_import(run_gdacs)
        runner.run_import(run_eonet)

        # Fires burn for days and the two curators date them differently:
        # a week's window, same place.
        body = client.get(
            "/api/datasets/{0}/events/matches?other={1}&window_seconds=604800&radius_km=50".format(
                fires_gdacs["id"], fires_eonet["id"]
            )
        ).json()

        assert body["events"] > 0
        assert body["matched"] >= 1
        pair = body["pairs"][0]
        assert pair["event"]["magnitude_unit"] == "hectares"
        assert pair["other"]["magnitude_unit"] == "hectares"
        assert pair["event"]["attributes"]["alert_level"] in ("green", "orange", "red")
