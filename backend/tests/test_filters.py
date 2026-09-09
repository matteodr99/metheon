"""Filtering on the earthquakes endpoint.

The seeded data is deliberately small and explicit, so each assertion names
the events it expects rather than counting rows.
"""

from datetime import datetime

import pytest

from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres

# One event per hour, with magnitudes spanning the range and two events that
# are not earthquakes.
SEED = [
    ("m1", 1.0, "earthquake", datetime(2026, 9, 1, 10, 0)),
    ("m2", 2.5, "earthquake", datetime(2026, 9, 2, 10, 0)),
    ("m3", 4.0, "quarry blast", datetime(2026, 9, 3, 10, 0)),
    ("m4", 5.5, "earthquake", datetime(2026, 9, 4, 10, 0)),
    ("m5", None, "explosion", datetime(2026, 9, 5, 10, 0)),
]


@pytest.fixture
def seeded(db, dataset):
    records = [
        {
            "external_id": external_id,
            "magnitude": magnitude,
            "magnitude_type": "ml",
            "place": "somewhere",
            "event_type": event_type,
            "occurred_at": occurred_at,
            "source_updated_at": None,
            "longitude": 0.0,
            "latitude": 0.0,
            "depth_km": 1.0,
            "tsunami": False,
            "significance": 10,
            "url": None,
        }
        for external_id, magnitude, event_type, occurred_at in SEED
    ]
    with db() as connection:
        repository.upsert_earthquakes(connection, dataset["id"], records)
    return dataset


def ids(response):
    return sorted(item["external_id"] for item in response.json()["items"])


def get(client, dataset, query=""):
    return client.get(
        "/api/datasets/{0}/earthquakes{1}".format(
            dataset["id"], "?" + query if query else ""
        )
    )


class TestNoFilters:
    def test_everything_comes_back(self, client, seeded):
        assert ids(get(client, seeded)) == ["m1", "m2", "m3", "m4", "m5"]

    def test_no_filters_are_echoed(self, client, seeded):
        assert get(client, seeded).json()["filters"] == {}


class TestMagnitude:
    def test_a_lower_bound_is_inclusive(self, client, seeded):
        assert ids(get(client, seeded, "min_magnitude=2.5")) == ["m2", "m3", "m4"]

    def test_an_upper_bound_is_inclusive(self, client, seeded):
        assert ids(get(client, seeded, "max_magnitude=2.5")) == ["m1", "m2"]

    def test_both_bounds_make_a_range(self, client, seeded):
        assert ids(get(client, seeded, "min_magnitude=2&max_magnitude=4.5")) == [
            "m2",
            "m3",
        ]

    def test_events_without_a_magnitude_are_excluded(self, client, seeded):
        """A null magnitude cannot satisfy a bound, and must not slip through."""
        assert "m5" not in ids(get(client, seeded, "min_magnitude=0"))

    def test_events_without_a_magnitude_survive_an_unfiltered_query(
        self, client, seeded
    ):
        assert "m5" in ids(get(client, seeded))

    def test_a_bound_matching_nothing_returns_an_empty_page(self, client, seeded):
        body = get(client, seeded, "min_magnitude=9").json()

        assert body["items"] == []
        assert body["total"] == 0


class TestTimeRange:
    def test_a_start_is_inclusive(self, client, seeded):
        assert ids(get(client, seeded, "start_time=2026-09-04T10:00:00")) == [
            "m4",
            "m5",
        ]

    def test_an_end_is_inclusive(self, client, seeded):
        assert ids(get(client, seeded, "end_time=2026-09-02T10:00:00")) == ["m1", "m2"]

    def test_both_bounds_make_a_window(self, client, seeded):
        query = "start_time=2026-09-02T00:00:00&end_time=2026-09-04T00:00:00"

        assert ids(get(client, seeded, query)) == ["m2", "m3"]


class TestEventType:
    def test_only_the_requested_type_comes_back(self, client, seeded):
        assert ids(get(client, seeded, "event_type=earthquake")) == ["m1", "m2", "m4"]

    def test_a_non_earthquake_type_can_be_selected(self, client, seeded):
        """Storing quarry blasts is only useful if they can be asked for."""
        assert ids(get(client, seeded, "event_type=quarry blast")) == ["m3"]

    def test_an_unknown_type_returns_nothing(self, client, seeded):
        assert ids(get(client, seeded, "event_type=meteorite")) == []


class TestCombinedFilters:
    def test_filters_are_applied_together(self, client, seeded):
        query = "event_type=earthquake&min_magnitude=2"

        assert ids(get(client, seeded, query)) == ["m2", "m4"]

    def test_the_applied_filters_are_echoed_back(self, client, seeded):
        body = get(client, seeded, "event_type=earthquake&min_magnitude=2").json()

        assert body["filters"] == {"event_type": "earthquake", "min_magnitude": 2.0}


class TestTotalRespectsFilters:
    def test_total_counts_matches_not_the_whole_dataset(self, client, seeded):
        """A total ignoring the filters would make the page count wrong."""
        body = get(client, seeded, "event_type=earthquake").json()

        assert body["total"] == 3

    def test_total_is_stable_across_pages(self, client, seeded):
        query = "event_type=earthquake&limit=2"
        first = get(client, seeded, query).json()
        second = get(client, seeded, query + "&offset=2").json()

        assert first["total"] == second["total"] == 3
        assert len(first["items"]) == 2
        assert len(second["items"]) == 1


class TestInvalidFilters:
    def test_an_inverted_magnitude_range_is_rejected(self, client, seeded):
        """Silently returning nothing would read as "no data", not a mistake."""
        response = get(client, seeded, "min_magnitude=5&max_magnitude=1")

        assert response.status_code == 422
        assert "inverted" in response.json()["detail"]

    def test_an_inverted_time_range_is_rejected(self, client, seeded):
        response = get(
            client,
            seeded,
            "start_time=2026-09-05T00:00:00&end_time=2026-09-01T00:00:00",
        )

        assert response.status_code == 422

    def test_equal_bounds_are_allowed(self, client, seeded):
        assert (
            get(client, seeded, "min_magnitude=2.5&max_magnitude=2.5").status_code
            == 200
        )

    @pytest.mark.parametrize(
        "query",
        ["min_magnitude=big", "start_time=not-a-date", "max_magnitude="],
    )
    def test_unparsable_values_are_rejected(self, client, seeded, query):
        assert get(client, seeded, query).status_code == 422


class TestFiltersAreNotInjectable:
    def test_a_hostile_event_type_is_treated_as_a_value(self, client, seeded):
        """The clause is built from constants; values are always parameters."""
        response = get(client, seeded, "event_type=x'; DROP TABLE earthquakes; --")

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert ids(get(client, seeded)) == ["m1", "m2", "m3", "m4", "m5"]
