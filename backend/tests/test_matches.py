"""Pairing one agency's events with another's reports of the same quakes.

Two datasets are seeded with events built to land inside or outside the
time window and the radius, so each assertion names the pair it expects.
"""

from datetime import datetime, timedelta

import pytest

from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres

T0 = datetime(2026, 9, 1, 12, 0, 0)

# One degree of latitude is about 111 km; 0.5 degrees is about 56 km.
USGS = [
    # id, seconds after T0, longitude, latitude, magnitude
    ("big", 0, 12.5, 41.9, 5.0),
    ("twin", 3600, 14.3, 40.8, 3.0),
    ("lonely", 7200, 139.7, 35.7, 4.0),
    ("nomag", 10800, -77.0, -12.0, None),
]
INGV = [
    ("big-ingv", 5, 12.6, 41.95, 5.3),          # 5 s later, ~12 km away: a pair
    ("twin-early", 3600 - 20, 14.3, 40.8, 2.8),  # both candidates for "twin"…
    ("twin-late", 3600 + 4, 14.31, 40.81, 3.1),  # …this one is nearer in time
    ("far", 7200 + 1, 139.7, 37.7, 4.0),         # 1 s from "lonely" but ~222 km north
    ("east", 7200 + 2, 141.7, 35.7, 4.0),        # same latitude, ~180 km east: only the
                                                 # exact distance can rule it out
    ("late", 7200 + 120, 139.7, 35.7, 4.0),      # same place as "lonely", 2 min later
    ("nomag-ingv", 10800, -77.0, -12.0, 2.0),    # pairs with "nomag"
]


def records(events):
    return [
        {
            "external_id": external_id,
            "magnitude": magnitude,
            "magnitude_unit": "ml",
            "title": external_id,
            "event_type": "earthquake",
            "occurred_at": T0 + timedelta(seconds=seconds),
            "source_updated_at": None,
            "longitude": longitude,
            "latitude": latitude,
            "attributes": {"depth_km": 10.0, "tsunami": False, "significance": 10},
            "url": None,
        }
        for external_id, seconds, longitude, latitude, magnitude in events
    ]


@pytest.fixture
def two(db, dataset):
    with db() as connection:
        other = repository.create_dataset(connection, "Terremoti Italia", "ingv", None)
        repository.upsert_events(connection, dataset["id"], records(USGS))
        repository.upsert_events(connection, other["id"], records(INGV))
    return dataset, other


def matches(client, dataset, other, query=""):
    return client.get(
        "/api/datasets/{0}/events/matches?other={1}{2}".format(
            dataset["id"], other["id"], "&" + query if query else ""
        )
    )


def pairs_of(response):
    return {
        pair["event"]["external_id"]: pair["other"]["external_id"]
        for pair in response.json()["pairs"]
    }


class TestPairing:
    def test_events_within_the_window_and_radius_are_paired(self, client, two):
        assert pairs_of(matches(client, *two)) == {
            "big": "big-ingv",
            "twin": "twin-late",
            "nomag": "nomag-ingv",
        }

    def test_the_nearer_in_time_of_two_candidates_wins(self, client, two):
        assert pairs_of(matches(client, *two))["twin"] == "twin-late"

    def test_a_report_outside_the_radius_is_not_a_pair(self, client, two):
        # "far" fails the latitude pre-check, "east" only the distance itself.
        assert "lonely" not in pairs_of(matches(client, *two))

    def test_widening_the_radius_pairs_it(self, client, two):
        assert pairs_of(matches(client, *two, "radius_km=300"))["lonely"] == "far"

    def test_widening_the_window_pairs_the_late_report(self, client, two):
        # With 300 s, "late" (120 s, same place) and "far" (1 s, 222 km) are
        # both in the window; only "late" is within the radius.
        assert pairs_of(matches(client, *two, "window_seconds=300"))["lonely"] == "late"

    def test_counts_cover_the_filtered_events(self, client, two):
        body = matches(client, *two).json()
        assert (body["events"], body["matched"], body["unmatched"]) == (4, 3, 1)

    def test_the_deltas_are_other_minus_event(self, client, two):
        [big] = [pair for pair in matches(client, *two).json()["pairs"] if pair["event"]["external_id"] == "big"]
        assert big["delta_seconds"] == 5.0
        assert big["delta_magnitude"] == pytest.approx(0.3)
        assert 8 < big["distance_km"] < 12

    def test_a_missing_magnitude_gives_no_magnitude_delta(self, client, two):
        [nomag] = [pair for pair in matches(client, *two).json()["pairs"] if pair["event"]["external_id"] == "nomag"]
        assert nomag["delta_magnitude"] is None

    def test_the_means_are_over_every_pair(self, client, two):
        body = matches(client, *two, "limit=1").json()
        assert len(body["pairs"]) == 1
        assert body["matched"] == 3
        assert body["mean_abs_delta_seconds"] == pytest.approx((5 + 4 + 0) / 3)
        # "nomag" has no magnitude on one side and is left out of this mean.
        assert body["mean_abs_delta_magnitude"] == pytest.approx((0.3 + 0.1) / 2)

    def test_the_strongest_pairs_come_first(self, client, two):
        ids = [pair["event"]["external_id"] for pair in matches(client, *two).json()["pairs"]]
        assert ids == ["big", "twin", "nomag"]

    def test_no_pairs_means_null_means(self, client, two):
        body = matches(client, *two, "min_magnitude=6").json()
        assert body["matched"] == 0
        assert body["mean_distance_km"] is None
        assert body["pairs"] == []


class TestFiltersAndRefusals:
    def test_the_filters_apply_to_this_side(self, client, two):
        body = matches(client, *two, "min_magnitude=4.5").json()
        assert body["events"] == 1
        assert pairs_of(matches(client, *two, "min_magnitude=4.5")) == {"big": "big-ingv"}

    def test_the_comparison_works_the_other_way_round(self, client, two):
        dataset, other = two
        assert pairs_of(matches(client, other, dataset)) == {
            "big-ingv": "big",
            "twin-late": "twin",
            "twin-early": "twin",
            "nomag-ingv": "nomag",
        }

    def test_the_parameters_are_echoed(self, client, two):
        body = matches(client, *two, "window_seconds=30&radius_km=50&min_magnitude=2").json()
        assert (body["window_seconds"], body["radius_km"]) == (30.0, 50.0)
        assert body["filters"] == {"min_magnitude": 2.0}
        assert body["other_id"] == two[1]["id"]

    def test_a_dataset_is_not_compared_with_itself(self, client, two):
        dataset, _ = two
        response = matches(client, dataset, dataset)
        assert response.status_code == 422
        assert "itself" in response.json()["detail"]

    def test_an_unknown_other_is_404(self, client, two):
        dataset, _ = two
        assert matches(client, dataset, {"id": 999999}).status_code == 404

    def test_an_unknown_dataset_is_404(self, client, two):
        _, other = two
        assert matches(client, {"id": 999999}, other).status_code == 404

    def test_other_is_required(self, client, two):
        dataset, _ = two
        assert client.get("/api/datasets/{0}/events/matches".format(dataset["id"])).status_code == 422

    @pytest.mark.parametrize("query", ["window_seconds=0", "window_seconds=3601", "radius_km=0", "radius_km=1001"])
    def test_out_of_range_parameters_are_refused(self, client, two, query):
        assert matches(client, *two, query).status_code == 422
