"""The INGV source: time window, normalization, and coexistence with USGS."""

from datetime import datetime, timezone

import pytest

from app.db import repository
from app.ingestion import ingv, sources
from tests.conftest import load_fixture, make_feature, requires_postgres


def ingv_feature(**overrides):
    """A minimal valid INGV feature, mirroring the real shape."""
    feature = {
        "type": "Feature",
        "properties": {
            "eventId": 47142392,
            "originId": 147438921,
            "time": "2026-09-11T08:45:27.120000",
            "author": "SURVEY-INGV",
            "magType": "ML",
            "mag": 1.4,
            "type": "earthquake",
            "place": "3 km E Sant'Angelo in Pontano (MC)",
            "version": 100,
        },
        "geometry": {"type": "Point", "coordinates": [13.4322, 43.1037, 26]},
    }
    for key, value in overrides.items():
        feature[key] = value
    return feature


class TestTimeWindow:
    def test_a_start_time_is_added_for_the_last_seven_days(self):
        now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

        url = ingv.with_time_window("https://x.invalid/q?format=geojson", now=now)

        assert "starttime=2026-09-04T12%3A00%3A00" in url
        assert "format=geojson" in url

    def test_the_window_length_can_be_chosen(self):
        now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)

        url = ingv.with_time_window("https://x.invalid/q", days=1, now=now)

        assert "starttime=2026-09-10T12%3A00%3A00" in url

    def test_an_explicit_start_time_is_left_alone(self):
        """A caller asking for a specific period must get exactly that."""
        url = "https://x.invalid/q?starttime=2020-01-01T00:00:00"

        assert ingv.with_time_window(url) == url

    def test_fetch_feed_requests_a_windowed_url(self, monkeypatch):
        seen = {}

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"type": "FeatureCollection", "features": []}

        def fake_get(url, **kwargs):
            seen["url"] = url
            return Response()

        monkeypatch.setattr(ingv.httpx, "get", fake_get)
        ingv.fetch_feed()

        assert "starttime=" in seen["url"]
        assert seen["url"].startswith(ingv.DEFAULT_FEED_URL.split("?")[0])


class TestNormalization:
    def test_a_real_feature_normalizes(self):
        record, error = ingv.normalize_feature(ingv_feature())

        assert error is None
        assert record["external_id"] == "47142392"
        assert record["magnitude"] == 1.4
        assert record["event_type"] == "earthquake"
        assert record["place"] == "3 km E Sant'Angelo in Pontano (MC)"
        assert record["longitude"] == 13.4322
        assert record["latitude"] == 43.1037
        assert record["depth_km"] == 26.0

    def test_the_iso_time_becomes_naive_utc(self):
        record, _ = ingv.normalize_feature(ingv_feature())

        assert record["occurred_at"] == datetime(2026, 9, 11, 8, 45, 27, 120000)
        assert record["occurred_at"].tzinfo is None

    def test_the_integer_id_is_stored_as_text(self):
        """It must share a column with USGS's alphanumeric ids."""
        record, _ = ingv.normalize_feature(ingv_feature())

        assert isinstance(record["external_id"], str)

    def test_the_magnitude_type_is_lowercased(self):
        """USGS says "ml"; INGV says "ML". One spelling per type."""
        record, _ = ingv.normalize_feature(ingv_feature())

        assert record["magnitude_type"] == "ml"

    def test_the_event_page_is_linked(self):
        record, _ = ingv.normalize_feature(ingv_feature())

        assert record["url"] == "https://terremoti.ingv.it/event/47142392"

    def test_fields_ingv_does_not_publish_are_null_or_false(self):
        record, _ = ingv.normalize_feature(ingv_feature())

        assert record["tsunami"] is False
        assert record["significance"] is None
        assert record["source_updated_at"] is None

    def test_a_missing_event_id_is_rejected(self):
        feature = ingv_feature()
        del feature["properties"]["eventId"]

        record, error = ingv.normalize_feature(feature)

        assert record is None
        assert "usable id" in error

    @pytest.mark.parametrize("time_value", [None, "", "yesterday", 1788942354913])
    def test_a_missing_or_invalid_time_is_rejected(self, time_value):
        feature = ingv_feature()
        feature["properties"]["time"] = time_value

        record, error = ingv.normalize_feature(feature)

        assert record is None
        assert "missing or invalid time" in error

    def test_shared_envelope_checks_apply(self):
        """Out-of-range coordinates are refused here as they are for USGS."""
        feature = ingv_feature()
        feature["geometry"]["coordinates"] = [0, 999, 0]

        record, error = ingv.normalize_feature(feature)

        assert record is None
        assert "latitude out of range" in error

    def test_a_usgs_feature_is_not_accepted_by_mistake(self):
        """USGS puts the id at the top level; INGV under properties."""
        record, error = ingv.normalize_feature(make_feature())

        assert record is None
        assert "usable id" in error


class TestAgainstRealFeed:
    def test_the_captured_feed_normalizes_without_errors(self):
        payload = load_fixture("ingv_week.json")

        records, errors = ingv.normalize_feed(payload)

        assert errors == []
        assert len(records) == len(payload["features"])

    def test_the_captured_feed_includes_a_quarry_blast(self):
        """Kept, like the USGS ones: the type column tells them apart."""
        records, _ = ingv.normalize_feed(load_fixture("ingv_week.json"))

        assert any(r["event_type"] == "quarry blast" for r in records)


class TestRegistered:
    def test_ingv_is_a_known_source(self):
        assert sources.get_source("ingv").key == "ingv"

    def test_its_default_feed_names_the_service(self):
        assert "webservices.ingv.it" in sources.get_source("ingv").default_feed_url


@requires_postgres
class TestSourcesCoexist:
    def _record(self, external_id):
        return {
            "external_id": external_id,
            "magnitude": 1.0,
            "magnitude_type": "ml",
            "place": "p",
            "event_type": "earthquake",
            "occurred_at": datetime(2026, 9, 9, 8, 0),
            "source_updated_at": None,
            "longitude": 0.0,
            "latitude": 0.0,
            "depth_km": 1.0,
            "tsunami": False,
            "significance": None,
            "url": None,
        }

    def test_the_same_id_in_two_datasets_does_not_collide(self, db):
        """Two agencies may reuse an id for different events."""
        with db() as connection:
            usgs_ds = repository.create_dataset(connection, "USGS", "usgs", None)
            ingv_ds = repository.create_dataset(connection, "INGV", "ingv", None)

        with db() as connection:
            first = repository.upsert_earthquakes(
                connection, usgs_ds["id"], [self._record("12345")]
            )
        with db() as connection:
            second = repository.upsert_earthquakes(
                connection, ingv_ds["id"], [self._record("12345")]
            )

        assert first == (1, 0)
        assert second == (1, 0)
        with db() as connection:
            assert repository.count_earthquakes(connection, usgs_ds["id"]) == 1
            assert repository.count_earthquakes(connection, ingv_ds["id"]) == 1

    def test_re_running_one_dataset_leaves_the_other_alone(self, db):
        with db() as connection:
            usgs_ds = repository.create_dataset(connection, "USGS", "usgs", None)
            ingv_ds = repository.create_dataset(connection, "INGV", "ingv", None)
            repository.upsert_earthquakes(connection, usgs_ds["id"], [self._record("a")])
            repository.upsert_earthquakes(connection, ingv_ds["id"], [self._record("a")])

        with db() as connection:
            inserted, updated = repository.upsert_earthquakes(
                connection, ingv_ds["id"], [self._record("a")]
            )

        assert (inserted, updated) == (0, 1)
        with db() as connection:
            assert repository.count_earthquakes(connection, usgs_ds["id"]) == 1

    def test_a_dataset_can_be_created_for_ingv(self, client):
        response = client.post(
            "/api/datasets", json={"name": "Italian Earthquakes", "source": "ingv"}
        )

        assert response.status_code == 200
        assert response.json()["source"] == "ingv"
