"""Validation and normalization of USGS features.

These tests never touch the network or the database: they exercise the pure
functions in `app.ingestion.usgs`.
"""

from datetime import datetime

import pytest

from app.ingestion.usgs import normalize_feature, normalize_feed
from tests.conftest import make_feature


class TestValidFeatures:
    def test_valid_feature_is_accepted(self):
        record, error = normalize_feature(make_feature())

        assert error is None
        assert record["external_id"] == "test1"
        assert record["magnitude"] == 1.4
        assert record["magnitude_type"] == "ml"
        assert record["event_type"] == "earthquake"
        assert record["longitude"] == -101.696
        assert record["latitude"] == 31.715
        assert record["depth_km"] == 2.4688
        assert record["significance"] == 30

    def test_epoch_milliseconds_become_naive_utc(self):
        record, _ = normalize_feature(make_feature())

        assert record["occurred_at"] == datetime(2026, 9, 9, 8, 25, 54, 913000)
        assert record["occurred_at"].tzinfo is None

    def test_null_magnitude_is_allowed(self):
        feature = make_feature()
        feature["properties"]["mag"] = None

        record, error = normalize_feature(feature)

        assert error is None
        assert record["magnitude"] is None

    def test_missing_depth_is_allowed(self):
        feature = make_feature()
        feature["geometry"]["coordinates"] = [-101.696, 31.715]

        record, error = normalize_feature(feature)

        assert error is None
        assert record["depth_km"] is None

    def test_missing_updated_timestamp_is_allowed(self):
        feature = make_feature()
        del feature["properties"]["updated"]

        record, error = normalize_feature(feature)

        assert error is None
        assert record["source_updated_at"] is None

    @pytest.mark.parametrize(
        "raw, expected",
        [(0, False), (1, True), (None, False)],
    )
    def test_tsunami_is_coerced_to_boolean(self, raw, expected):
        feature = make_feature()
        feature["properties"]["tsunami"] = raw

        record, _ = normalize_feature(feature)

        assert record["tsunami"] is expected

    def test_non_earthquake_events_are_kept(self):
        feature = make_feature()
        feature["properties"]["type"] = "quarry blast"

        record, error = normalize_feature(feature)

        assert error is None
        assert record["event_type"] == "quarry blast"

    @pytest.mark.parametrize(
        "longitude, latitude",
        [(-180.0, -90.0), (180.0, 90.0), (0, 0)],
    )
    def test_coordinate_boundaries_are_accepted(self, longitude, latitude):
        feature = make_feature()
        feature["geometry"]["coordinates"] = [longitude, latitude, 0]

        record, error = normalize_feature(feature)

        assert error is None
        assert record["longitude"] == float(longitude)


class TestRejectedFeatures:
    @pytest.mark.parametrize(
        "feature, expected_fragment",
        [
            ("not a dict", "not an object"),
            ({"properties": {}, "geometry": {}}, "usable id"),
            (make_feature(id=""), "usable id"),
            (make_feature(id=42), "usable id"),
            (make_feature(properties="nope"), "missing properties"),
            (make_feature(geometry="nope"), "missing geometry"),
        ],
    )
    def test_structurally_invalid_features_are_rejected(
        self, feature, expected_fragment
    ):
        record, error = normalize_feature(feature)

        assert record is None
        assert expected_fragment in error

    def test_coordinates_with_a_single_value_are_rejected(self):
        feature = make_feature()
        feature["geometry"]["coordinates"] = [1]

        record, error = normalize_feature(feature)

        assert record is None
        assert "longitude and latitude" in error

    def test_non_numeric_coordinates_are_rejected(self):
        feature = make_feature()
        feature["geometry"]["coordinates"] = ["east", "north"]

        record, error = normalize_feature(feature)

        assert record is None
        assert "non-numeric" in error

    @pytest.mark.parametrize("longitude", [-180.1, 180.1, 1000])
    def test_longitude_out_of_range_is_rejected(self, longitude):
        feature = make_feature()
        feature["geometry"]["coordinates"] = [longitude, 0, 0]

        record, error = normalize_feature(feature)

        assert record is None
        assert "longitude out of range" in error

    @pytest.mark.parametrize("latitude", [-90.1, 90.1, 999])
    def test_latitude_out_of_range_is_rejected(self, latitude):
        feature = make_feature()
        feature["geometry"]["coordinates"] = [0, latitude, 0]

        record, error = normalize_feature(feature)

        assert record is None
        assert "latitude out of range" in error

    @pytest.mark.parametrize("time_value", [None, "yesterday", True])
    def test_missing_or_invalid_time_is_rejected(self, time_value):
        feature = make_feature()
        feature["properties"]["time"] = time_value

        record, error = normalize_feature(feature)

        assert record is None
        assert "missing or invalid time" in error

    def test_error_message_names_the_event(self):
        """An operator reading the errors must be able to find the event."""
        feature = make_feature(id="hv75031332")
        del feature["properties"]["time"]

        _, error = normalize_feature(feature)

        assert error.startswith("hv75031332:")


class TestNormalizeFeed:
    def test_empty_feed_yields_nothing(self):
        records, errors = normalize_feed({"features": []})

        assert records == []
        assert errors == []

    def test_valid_and_invalid_features_are_separated(self):
        payload = {
            "features": [
                make_feature(id="good1"),
                {"id": "bad", "properties": {}, "geometry": {}},
                make_feature(id="good2"),
            ]
        }

        records, errors = normalize_feed(payload)

        assert [r["external_id"] for r in records] == ["good1", "good2"]
        assert len(errors) == 1

    def test_duplicate_ids_are_collapsed(self):
        payload = {"features": [make_feature(id="dup"), make_feature(id="dup")]}

        records, errors = normalize_feed(payload)

        assert len(records) == 1
        assert "duplicate id" in errors[0]

    def test_a_payload_without_features_is_treated_as_empty(self):
        records, errors = normalize_feed({})

        assert records == []
        assert errors == []


class TestAgainstRealFeed:
    def test_the_captured_feed_normalizes_without_errors(self, real_feed):
        records, errors = normalize_feed(real_feed)

        assert errors == []
        assert len(records) == len(real_feed["features"])

    def test_every_record_has_the_columns_the_table_requires(self, real_feed):
        records, _ = normalize_feed(real_feed)

        required = ("external_id", "occurred_at", "longitude", "latitude")
        for record in records:
            for field in required:
                assert record[field] is not None

    def test_fields_the_feed_leaves_null_do_not_break_normalization(self, real_feed):
        """alert, cdi, felt, mmi and tz were null in every captured feature."""
        records, errors = normalize_feed(real_feed)

        assert errors == []
        assert len(records) > 0
