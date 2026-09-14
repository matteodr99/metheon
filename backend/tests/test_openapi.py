"""The API describes itself completely, and the description matches reality.

Swagger is the reference a client reads. A route without a response model
shows up there as an untyped `object`, which is a reference that says
nothing; these tests keep that from creeping back.
"""

import pytest

from app.main import app
from tests.conftest import requires_postgres


def spec():
    return app.openapi()


def success_schema(operation):
    for code in ("200", "202"):
        body = operation.get("responses", {}).get(code)
        if body:
            return body.get("content", {}).get("application/json", {}).get("schema")
    return None


# Routes that never open a connection: health answers about the database
# rather than through it, and the registry lives in memory.
NO_DATABASE = ("/api/health", "/api/health/live", "/api/sources")


def every_operation():
    for path, operations in spec()["paths"].items():
        for method, operation in operations.items():
            yield method.upper(), path, operation


class TestEveryRouteIsDescribed:
    @pytest.mark.parametrize(
        "method, path, operation",
        list(every_operation()),
        ids=[f"{m} {p}" for m, p, _ in every_operation()],
    )
    def test_the_success_response_has_a_named_schema(self, method, path, operation):
        """An untyped `object` is not documentation."""
        schema = success_schema(operation)

        assert schema is not None, "no success response"
        named = "$ref" in schema or "$ref" in schema.get("items", {})
        assert named, "success response is not a named model"

    @pytest.mark.parametrize(
        "method, path, operation",
        list(every_operation()),
        ids=[f"{m} {p}" for m, p, _ in every_operation()],
    )
    def test_every_route_carries_a_tag(self, method, path, operation):
        assert operation.get("tags"), "route is untagged in Swagger"

    @pytest.mark.parametrize(
        "method, path, operation",
        [(m, p, o) for m, p, o in every_operation() if "{dataset_id}" in p],
        ids=[f"{m} {p}" for m, p, _ in every_operation() if "{dataset_id}" in p],
    )
    def test_routes_taking_a_dataset_declare_404(self, method, path, operation):
        assert "404" in operation["responses"]

    @pytest.mark.parametrize(
        "method, path, operation",
        [(m, p, o) for m, p, o in every_operation() if p not in NO_DATABASE],
        ids=[f"{m} {p}" for m, p, _ in every_operation() if p not in NO_DATABASE],
    )
    def test_routes_touching_the_database_declare_503(self, method, path, operation):
        """The handler for a dead database answers 503 on every such route,
        so every such route must say so."""
        assert "503" in operation["responses"]

    def test_refusals_share_one_body_shape(self):
        problem = spec()["components"]["schemas"]["Problem"]

        assert list(problem["properties"]) == ["detail"]


@requires_postgres
class TestTheDescriptionMatchesReality:
    """`response_model` validates the handler's output; a mismatch would
    surface as a 500. Hitting each route proves the models fit the data."""

    def test_a_dataset_round_trips_through_its_model(self, client):
        created = client.post(
            "/api/datasets", json={"name": "Quakes", "source": "usgs"}
        ).json()

        assert set(created) == {"id", "name", "source", "description", "created_at", "status"}

    def test_a_page_of_events_matches_its_model(self, client, dataset):
        body = client.get("/api/datasets/{0}/earthquakes".format(dataset["id"])).json()

        assert set(body) == {"dataset_id", "total", "limit", "offset", "filters", "items"}

    def test_a_summary_matches_its_model(self, client, dataset):
        body = client.get(
            "/api/datasets/{0}/earthquakes/summary".format(dataset["id"])
        ).json()

        assert set(body["magnitude"]) == {"min", "max", "average", "unknown"}
        assert set(body["occurred_at"]) == {"first", "last"}

    def test_an_import_run_matches_its_model(self, client, dataset):
        client.post("/api/datasets/{0}/ingest".format(dataset["id"]))
        run = client.get("/api/datasets/{0}/imports".format(dataset["id"])).json()[
            "items"
        ][0]

        assert "invalid_sample" in run
        assert "queued_at" in run

    def test_an_output_of_the_wrong_shape_is_refused_not_served(
        self, lenient_client, monkeypatch
    ):
        """The other half of the contract: the model guards the exit. A
        handler returning something the model rejects must not reach the
        client as JSON that merely looks right."""
        from app.db import repository

        monkeypatch.setattr(repository, "list_datasets", lambda connection: [{"id": "x"}])

        response = lenient_client.get("/api/datasets")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
