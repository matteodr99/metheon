"""The GraphQL schema answers what the REST routes answer.

The seed spreads events over magnitude, type, time and position so that
every filter selects a different subset; each GraphQL query is then asked
of the REST route too, and the two answers must agree. The one thing the
schema does on its own — refusing, and masking what it did not mean to
say — is tested against the wire.
"""

from datetime import datetime

import psycopg
import pytest

from app import graphql
from app.db import repository
from tests.conftest import requires_postgres

pytestmark = requires_postgres

# (external_id, magnitude, event_type, occurred_at, longitude, latitude)
SEED = [
    ("m1", 1.0, "earthquake", datetime(2026, 9, 1, 10, 0), 13.4, 42.3),
    ("m2", 2.5, "earthquake", datetime(2026, 9, 2, 10, 0), 15.1, 38.2),
    ("m3", 4.0, "quarry blast", datetime(2026, 9, 3, 10, 0), -120.0, 36.0),
    ("m4", 5.5, "earthquake", datetime(2026, 9, 4, 10, 0), 142.0, 37.5),
    ("m5", None, "explosion", datetime(2026, 9, 5, 10, 0), 0.0, 0.0),
]

ITALY = {"minLatitude": 36, "maxLatitude": 47, "minLongitude": 6, "maxLongitude": 19}
ITALY_QUERY = "min_latitude=36&max_latitude=47&min_longitude=6&max_longitude=19"


@pytest.fixture
def seeded(db, dataset):
    records = [
        {
            "external_id": external_id,
            "magnitude": magnitude,
            "magnitude_unit": "ml",
            "title": "somewhere",
            "event_type": event_type,
            "occurred_at": occurred_at,
            "source_updated_at": None,
            "longitude": longitude,
            "latitude": latitude,
            "attributes": {"depth_km": 1.0, "tsunami": False, "significance": 10},
            "url": None,
        }
        for external_id, magnitude, event_type, occurred_at, longitude, latitude in SEED
    ]
    with db() as connection:
        repository.upsert_events(connection, dataset["id"], records)
    return dataset


def graphql_post(client, query, variables=None):
    response = client.post("/api/graphql", json={"query": query, "variables": variables or {}})
    assert response.status_code == 200, response.text
    return response.json()


def data(client, query, variables=None):
    body = graphql_post(client, query, variables)
    assert "errors" not in body, body
    return body["data"]


def errors(client, query, variables=None):
    body = graphql_post(client, query, variables)
    assert body.get("errors"), body
    return [error["message"] for error in body["errors"]]


EVENTS = """
query ($id: Int!, $filters: EventFilterInput, $limit: Int, $offset: Int) {
  dataset(id: $id) {
    events(filters: $filters, limit: $limit, offset: $offset) {
      total limit offset
      items { externalId magnitude eventType occurredAt longitude latitude attributes }
    }
  }
}
"""

SUMMARY = """
query ($id: Int!, $filters: EventFilterInput) {
  dataset(id: $id) {
    summary(filters: $filters) {
      total
      magnitude { min max average unknown }
      occurredAt { first last }
      byEventType { eventType count }
      byDay { day count }
    }
  }
}
"""


def graphql_ids(page):
    return sorted(item["externalId"] for item in page["items"])


def rest_ids(response):
    return sorted(item["external_id"] for item in response.json()["items"])


class TestDatasets:
    def test_the_list_is_the_rest_list(self, client, seeded):
        rest = client.get("/api/datasets").json()
        answer = data(client, "{ datasets { id name source kind status description lastIngestedAt } }")

        assert [d["id"] for d in answer["datasets"]] == [d["id"] for d in rest]
        assert answer["datasets"][0]["name"] == rest[0]["name"]
        assert answer["datasets"][0]["kind"] == rest[0]["kind"]

    def test_one_dataset_by_id(self, client, seeded):
        answer = data(client, "query ($id: Int!) { dataset(id: $id) { id name } }", {"id": seeded["id"]})

        assert answer["dataset"] == {"id": seeded["id"], "name": seeded["name"]}

    def test_an_unknown_dataset_is_null_not_an_error(self, client, seeded):
        """GraphQL's way of saying 404: the field is nullable and null."""
        answer = data(client, "{ dataset(id: 9999) { id } }")

        assert answer["dataset"] is None


class TestEventsAgreeWithRest:
    @pytest.mark.parametrize(
        "variables, query",
        [
            ({}, ""),
            ({"minMagnitude": 2.5}, "min_magnitude=2.5"),
            ({"maxMagnitude": 2.5}, "max_magnitude=2.5"),
            ({"minMagnitude": 2, "maxMagnitude": 4.5}, "min_magnitude=2&max_magnitude=4.5"),
            ({"eventType": "quarry blast"}, "event_type=quarry blast"),
            (
                {"startTime": "2026-09-02T00:00:00", "endTime": "2026-09-04T00:00:00"},
                "start_time=2026-09-02T00:00:00&end_time=2026-09-04T00:00:00",
            ),
            (ITALY, ITALY_QUERY),
            ({**ITALY, "minMagnitude": 2}, ITALY_QUERY + "&min_magnitude=2"),
        ],
        ids=["none", "min", "max", "range", "type", "window", "box", "box+magnitude"],
    )
    def test_the_same_filter_selects_the_same_events(self, client, seeded, variables, query):
        rest = client.get(
            "/api/datasets/{0}/events{1}".format(seeded["id"], "?" + query if query else "")
        )
        page = data(client, EVENTS, {"id": seeded["id"], "filters": variables})["dataset"]["events"]

        assert graphql_ids(page) == rest_ids(rest)
        assert page["total"] == rest.json()["total"]

    def test_events_carry_the_rest_fields(self, client, seeded):
        page = data(client, EVENTS, {"id": seeded["id"], "filters": {"eventType": "quarry blast"}})
        [item] = page["dataset"]["events"]["items"]

        assert item["externalId"] == "m3"
        assert item["magnitude"] == 4.0
        assert item["longitude"] == -120.0
        assert item["occurredAt"] == "2026-09-03T10:00:00"
        assert item["attributes"] == {"depth_km": 1.0, "tsunami": False, "significance": 10}

    def test_paging_matches_rest(self, client, seeded):
        rest = client.get("/api/datasets/{0}/events?limit=2&offset=1".format(seeded["id"]))
        page = data(client, EVENTS, {"id": seeded["id"], "limit": 2, "offset": 1})["dataset"]["events"]

        assert [i["externalId"] for i in page["items"]] == [i["external_id"] for i in rest.json()["items"]]
        assert (page["limit"], page["offset"], page["total"]) == (2, 1, 5)

    def test_a_null_magnitude_survives_an_unfiltered_query(self, client, seeded):
        page = data(client, EVENTS, {"id": seeded["id"]})["dataset"]["events"]

        assert "m5" in graphql_ids(page)


class TestSummaryAgreesWithRest:
    @pytest.mark.parametrize(
        "variables, query",
        [({}, ""), ({"minMagnitude": 2}, "min_magnitude=2"), (ITALY, ITALY_QUERY)],
        ids=["none", "min", "box"],
    )
    def test_the_same_numbers(self, client, seeded, variables, query):
        rest = client.get(
            "/api/datasets/{0}/events/summary{1}".format(seeded["id"], "?" + query if query else "")
        ).json()
        summary = data(client, SUMMARY, {"id": seeded["id"], "filters": variables})["dataset"]["summary"]

        assert summary["total"] == rest["total"]
        assert summary["magnitude"] == rest["magnitude"]
        assert summary["occurredAt"] == {"first": rest["occurred_at"]["first"], "last": rest["occurred_at"]["last"]}
        assert [(r["eventType"], r["count"]) for r in summary["byEventType"]] == [
            (r["event_type"], r["count"]) for r in rest["by_event_type"]
        ]
        assert [(r["day"], r["count"]) for r in summary["byDay"]] == [
            (r["day"], r["count"]) for r in rest["by_day"]
        ]


class TestImports:
    def test_the_history_is_the_rest_history(self, client, seeded):
        client.post("/api/datasets/{0}/ingest".format(seeded["id"]))
        rest = client.get("/api/datasets/{0}/imports".format(seeded["id"])).json()["items"]
        answer = data(
            client,
            "query ($id: Int!) { dataset(id: $id) { imports { id status feedUrl queuedAt } } }",
            {"id": seeded["id"]},
        )

        assert [r["id"] for r in answer["dataset"]["imports"]] == [r["id"] for r in rest]
        assert answer["dataset"]["imports"][0]["status"] == rest[0]["status"]


class TestRefusals:
    """The sentences are the REST sentences; the status is GraphQL's 200."""

    def test_an_inverted_range_is_refused_with_the_rest_sentence(self, client, seeded):
        rest = client.get("/api/datasets/{0}/events?min_magnitude=5&max_magnitude=1".format(seeded["id"]))
        [message] = errors(client, EVENTS, {"id": seeded["id"], "filters": {"minMagnitude": 5, "maxMagnitude": 1}})

        assert rest.status_code == 422
        assert message == rest.json()["detail"]

    def test_a_coordinate_out_of_range_is_refused(self, client, seeded):
        """FastAPI checks the bounds on the query string; here the rule
        itself has to."""
        [message] = errors(client, EVENTS, {"id": seeded["id"], "filters": {"minLatitude": 91}})

        assert message == "min_latitude must be between -90 and 90"

    @pytest.mark.parametrize("limit", [0, 501])
    def test_a_limit_out_of_range_is_refused(self, client, seeded, limit):
        [message] = errors(client, EVENTS, {"id": seeded["id"], "limit": limit})

        assert message == "limit must be between 1 and 500"

    def test_a_negative_offset_is_refused(self, client, seeded):
        [message] = errors(client, EVENTS, {"id": seeded["id"], "offset": -1})

        assert message == "offset must be 0 or more"

    def test_a_refused_field_does_not_take_its_siblings_down(self, client, seeded):
        """Errors are per field: the name still answers when the events do not."""
        body = graphql_post(
            client,
            "query ($id: Int!) { dataset(id: $id) { name events(limit: 0) { total } } }",
            {"id": seeded["id"]},
        )

        assert body["data"]["dataset"]["name"] == seeded["name"]
        assert body["data"]["dataset"]["events"] is None
        assert [e["path"] for e in body["errors"]] == [["dataset", "events"]]

    def test_a_query_that_does_not_parse_says_so(self, client, seeded):
        [message] = errors(client, "{ datasets { nope } }")

        assert "nope" in message


class TestUnavailableDatabase:
    def test_the_rest_sentence_and_nothing_from_psycopg(self, client, seeded, monkeypatch):
        """The connection string is in the psycopg message; it must not
        reach the client."""
        def refuse_to_connect():
            raise psycopg.OperationalError("connection to server at host=secret-host failed")

        monkeypatch.setattr(graphql, "get_connection", refuse_to_connect)
        body = graphql_post(client, "{ datasets { id } }")

        assert [e["message"] for e in body["errors"]] == [graphql.DATABASE_UNAVAILABLE]
        assert "secret-host" not in body and "secret-host" not in str(body)

    def test_an_unexpected_exception_is_masked(self, client, seeded, monkeypatch):
        def explode(connection):
            raise RuntimeError("password=hunter2 in a traceback")

        monkeypatch.setattr(repository, "list_datasets", explode)
        body = graphql_post(client, "{ datasets { id } }")

        assert [e["message"] for e in body["errors"]] == ["Unexpected error"]
        assert "hunter2" not in str(body)


class TestServing:
    def test_graphiql_is_served_on_get(self, client):
        response = client.get("/api/graphql", headers={"accept": "text/html"})

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_introspection_opens_no_connection(self, client, monkeypatch):
        """GraphiQL introspects on load; a wake-up of the hosted database
        for that would be a cost for nothing."""
        def must_not_connect():
            raise AssertionError("a connection was opened for introspection")

        monkeypatch.setattr(graphql, "get_connection", must_not_connect)
        answer = data(client, "{ __schema { queryType { name } } }")

        assert answer["__schema"]["queryType"]["name"] == "Query"
