"""The bounding-box filters and the points endpoint.

Five events on a small grid, so every assertion can name the events a box
should contain.
"""

from datetime import datetime

import pytest

from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres

# (external_id, longitude, latitude, magnitude)
SEED = [
    ("rome", 12.5, 41.9, 3.0),
    ("naples", 14.3, 40.8, 2.0),
    ("tokyo", 139.7, 35.7, 5.0),
    ("lima", -77.0, -12.0, 4.0),
    ("nomag", 12.5, 41.9, None),
]


@pytest.fixture
def seeded(db, dataset):
    records = [
        {
            "external_id": external_id,
            "magnitude": magnitude,
            "magnitude_type": "ml",
            "place": external_id,
            "event_type": "earthquake",
            "occurred_at": datetime(2026, 9, 1, hour),
            "source_updated_at": None,
            "longitude": longitude,
            "latitude": latitude,
            "depth_km": 1.0,
            "tsunami": False,
            "significance": 10,
            "url": None,
        }
        for hour, (external_id, longitude, latitude, magnitude) in enumerate(SEED)
    ]
    with db() as connection:
        repository.upsert_earthquakes(connection, dataset["id"], records)
    return dataset


ITALY = "min_latitude=36&max_latitude=47&min_longitude=6&max_longitude=19"


def listing(client, dataset, query=""):
    return client.get(
        "/api/datasets/{0}/earthquakes{1}".format(dataset["id"], "?" + query if query else "")
    )


def points(client, dataset, query=""):
    return client.get(
        "/api/datasets/{0}/earthquakes/points{1}".format(
            dataset["id"], "?" + query if query else ""
        )
    )


def ids(response):
    return sorted(item["external_id"] for item in response.json()["items"])


class TestBoundingBox:
    def test_a_box_keeps_only_the_events_inside_it(self, client, seeded):
        assert ids(listing(client, seeded, ITALY)) == ["naples", "nomag", "rome"]

    def test_the_bounds_are_inclusive(self, client, seeded):
        exact = "min_latitude=41.9&max_latitude=41.9&min_longitude=12.5&max_longitude=12.5"
        assert ids(listing(client, seeded, exact)) == ["nomag", "rome"]

    def test_one_side_is_enough(self, client, seeded):
        assert ids(listing(client, seeded, "max_latitude=0")) == ["lima"]
        assert ids(listing(client, seeded, "min_longitude=100")) == ["tokyo"]

    def test_the_total_counts_what_the_box_contains(self, client, seeded):
        assert listing(client, seeded, ITALY).json()["total"] == 3

    def test_the_summary_and_the_points_agree_with_the_listing(self, client, seeded):
        summary = client.get(
            "/api/datasets/{0}/earthquakes/summary?{1}".format(seeded["id"], ITALY)
        ).json()
        assert summary["total"] == 3
        assert summary["magnitude"]["max"] == 3.0
        assert points(client, seeded, ITALY).json()["total"] == 3

    def test_the_box_is_echoed_back(self, client, seeded):
        assert listing(client, seeded, ITALY).json()["filters"] == {
            "min_latitude": 36.0,
            "max_latitude": 47.0,
            "min_longitude": 6.0,
            "max_longitude": 19.0,
        }

    def test_it_combines_with_the_other_filters(self, client, seeded):
        assert ids(listing(client, seeded, ITALY + "&min_magnitude=2.5")) == ["rome"]

    @pytest.mark.parametrize(
        "query",
        [
            "min_latitude=-91",
            "max_latitude=90.5",
            "min_longitude=-181",
            "max_longitude=181",
        ],
    )
    def test_a_coordinate_off_the_globe_is_refused(self, client, seeded, query):
        assert listing(client, seeded, query).status_code == 422

    @pytest.mark.parametrize(
        "query, label",
        [
            ("min_latitude=47&max_latitude=36", "latitude"),
            ("min_longitude=19&max_longitude=6", "longitude"),
        ],
    )
    def test_an_inverted_box_is_refused_with_the_reason(self, client, seeded, query, label):
        response = listing(client, seeded, query)
        assert response.status_code == 422
        assert label in response.json()["detail"]
        assert points(client, seeded, query).status_code == 422


class TestPoints:
    def test_every_matching_event_is_a_point(self, client, seeded):
        body = points(client, seeded).json()
        assert body["total"] == 5
        assert len(body["points"]) == 5

    def test_a_point_is_longitude_latitude_magnitude_and_id(self, client, seeded):
        body = points(client, seeded, "min_longitude=100").json()
        [(longitude, latitude, magnitude, event_id)] = body["points"]
        assert (longitude, latitude, magnitude) == (139.7, 35.7, 5.0)
        listed = listing(client, seeded, "min_longitude=100").json()["items"][0]
        assert event_id == listed["id"]

    def test_the_strongest_come_first_and_the_unmeasured_last(self, client, seeded):
        magnitudes = [point[2] for point in points(client, seeded).json()["points"]]
        assert magnitudes == [5.0, 4.0, 3.0, 2.0, None]

    def test_the_limit_keeps_the_strongest_and_reports_the_rest(self, client, seeded):
        body = points(client, seeded, "limit=2").json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert [point[2] for point in body["points"]] == [5.0, 4.0]

    def test_the_limit_is_capped(self, client, seeded):
        assert points(client, seeded, "limit=5001").status_code == 422
        assert points(client, seeded, "limit=0").status_code == 422

    def test_an_unknown_dataset_is_404(self, client, seeded):
        assert client.get("/api/datasets/999999/earthquakes/points").status_code == 404
