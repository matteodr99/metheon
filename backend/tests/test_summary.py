"""Aggregations on the earthquakes endpoint.

The seed is shared with the filter tests, so the two files describe the same
data and a summary can be checked against the listing it summarizes.
"""

import pytest

from tests.conftest import requires_postgres
from tests.test_filters import SEED, seeded  # noqa: F401  (fixture import)

pytestmark = requires_postgres


def summary(client, dataset, query=""):
    return client.get(
        "/api/datasets/{0}/earthquakes/summary{1}".format(
            dataset["id"], "?" + query if query else ""
        )
    ).json()


class TestTotals:
    def test_every_event_is_counted(self, client, seeded):
        assert summary(client, seeded)["total"] == len(SEED)

    def test_magnitude_bounds_come_from_the_data(self, client, seeded):
        magnitude = summary(client, seeded)["magnitude"]

        assert magnitude["min"] == 1.0
        assert magnitude["max"] == 5.5

    def test_the_average_ignores_events_without_a_magnitude(self, client, seeded):
        """(1.0 + 2.5 + 4.0 + 5.5) / 4, not divided by all five events."""
        assert summary(client, seeded)["magnitude"]["average"] == 3.25

    def test_events_without_a_magnitude_are_counted_separately(self, client, seeded):
        """Their absence must be visible, not hidden inside the total."""
        result = summary(client, seeded)

        assert result["total"] == 5
        assert result["magnitude"]["unknown"] == 1

    def test_the_time_span_covers_the_data(self, client, seeded):
        occurred = summary(client, seeded)["occurred_at"]

        assert occurred["first"].startswith("2026-09-01")
        assert occurred["last"].startswith("2026-09-05")


class TestGroupings:
    def test_events_are_grouped_by_type(self, client, seeded):
        counts = {
            row["event_type"]: row["count"]
            for row in summary(client, seeded)["by_event_type"]
        }

        assert counts == {"earthquake": 3, "quarry blast": 1, "explosion": 1}

    def test_types_are_ordered_by_count(self, client, seeded):
        counts = [row["count"] for row in summary(client, seeded)["by_event_type"]]

        assert counts == sorted(counts, reverse=True)

    def test_events_are_grouped_by_day(self, client, seeded):
        by_day = summary(client, seeded)["by_day"]

        assert by_day == [
            {"day": "2026-09-01", "count": 1},
            {"day": "2026-09-02", "count": 1},
            {"day": "2026-09-03", "count": 1},
            {"day": "2026-09-04", "count": 1},
            {"day": "2026-09-05", "count": 1},
        ]

    def test_days_are_chronological_not_ordered_by_count(self, client, dataset, db):
        """A chart consumes this in order, so the order must be by day.

        The counts per day are deliberately uneven: with one event per day
        an ordering by count would be a tie and this would prove nothing.
        """
        from datetime import datetime

        from app.db import repository

        records = []
        for day, count in ((1, 1), (2, 3), (3, 2)):
            for index in range(count):
                records.append(
                    {
                        "external_id": "d{0}e{1}".format(day, index),
                        "magnitude": 1.0,
                        "magnitude_type": "ml",
                        "place": "p",
                        "event_type": "earthquake",
                        "occurred_at": datetime(2026, 9, day, index, 0),
                        "source_updated_at": None,
                        "longitude": 0.0,
                        "latitude": 0.0,
                        "depth_km": 1.0,
                        "tsunami": False,
                        "significance": 1,
                        "url": None,
                    }
                )
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], records)

        assert summary(client, dataset)["by_day"] == [
            {"day": "2026-09-01", "count": 1},
            {"day": "2026-09-02", "count": 3},
            {"day": "2026-09-03", "count": 2},
        ]

    def test_several_events_on_one_day_are_summed(self, client, dataset, db):
        from datetime import datetime

        from app.db import repository

        records = [
            {
                "external_id": "same{0}".format(index),
                "magnitude": 1.0,
                "magnitude_type": "ml",
                "place": "p",
                "event_type": "earthquake",
                "occurred_at": datetime(2026, 9, 1, index, 0),
                "source_updated_at": None,
                "longitude": 0.0,
                "latitude": 0.0,
                "depth_km": 1.0,
                "tsunami": False,
                "significance": 1,
                "url": None,
            }
            for index in range(3)
        ]
        with db() as connection:
            repository.upsert_earthquakes(connection, dataset["id"], records)

        assert summary(client, dataset)["by_day"] == [
            {"day": "2026-09-01", "count": 3}
        ]


class TestFiltersApply:
    def test_a_filter_narrows_the_totals(self, client, seeded):
        result = summary(client, seeded, "event_type=earthquake")

        assert result["total"] == 3
        assert result["by_event_type"] == [{"event_type": "earthquake", "count": 3}]

    def test_a_filter_narrows_the_magnitude_bounds(self, client, seeded):
        magnitude = summary(client, seeded, "min_magnitude=2.5")["magnitude"]

        assert magnitude["min"] == 2.5
        assert magnitude["max"] == 5.5

    def test_a_filter_narrows_the_days(self, client, seeded):
        query = "start_time=2026-09-02T00:00:00&end_time=2026-09-03T23:59:59"

        days = [row["day"] for row in summary(client, seeded, query)["by_day"]]

        assert days == ["2026-09-02", "2026-09-03"]

    def test_the_applied_filters_are_echoed_back(self, client, seeded):
        assert summary(client, seeded, "event_type=earthquake")["filters"] == {
            "event_type": "earthquake"
        }

    def test_the_summary_total_matches_the_listing_total(self, client, seeded):
        """The two endpoints must never disagree about the same filter."""
        query = "min_magnitude=2"
        listed = client.get(
            "/api/datasets/{0}/earthquakes?{1}".format(seeded["id"], query)
        ).json()

        assert summary(client, seeded, query)["total"] == listed["total"]


class TestEmptyAndInvalid:
    def test_a_dataset_without_events_summarizes_to_nulls(self, client, dataset):
        result = summary(client, dataset)

        assert result["total"] == 0
        assert result["magnitude"] == {
            "min": None,
            "max": None,
            "average": None,
            "unknown": 0,
        }
        assert result["occurred_at"] == {"first": None, "last": None}
        assert result["by_event_type"] == []
        assert result["by_day"] == []

    def test_a_filter_matching_nothing_summarizes_to_nulls(self, client, seeded):
        result = summary(client, seeded, "min_magnitude=99")

        assert result["total"] == 0
        assert result["by_day"] == []

    def test_an_unknown_dataset_returns_404(self, client):
        assert (
            client.get("/api/datasets/999/earthquakes/summary").status_code == 404
        )

    def test_an_inverted_range_is_rejected(self, client, seeded):
        response = client.get(
            "/api/datasets/{0}/earthquakes/summary"
            "?min_magnitude=5&max_magnitude=1".format(seeded["id"])
        )

        assert response.status_code == 422
