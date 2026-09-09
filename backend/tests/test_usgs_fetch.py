"""Error handling in `fetch_feed`.

`httpx.get` is replaced in every test, so the suite never reaches the
network and stays deterministic.
"""

import json

import httpx
import pytest

from app.ingestion import usgs
from app.ingestion.usgs import IngestionError, fetch_feed


class FakeResponse:
    def __init__(self, payload, raise_for_status=None):
        self._payload = payload
        self._raise_for_status = raise_for_status

    def raise_for_status(self):
        if self._raise_for_status is not None:
            raise self._raise_for_status

    def json(self):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """Install a stand-in for httpx.get and record the call arguments."""
    calls = {}

    def install(response):
        def _get(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(usgs.httpx, "get", _get)
        return calls

    return install


def valid_payload(features=None):
    return {"type": "FeatureCollection", "features": features or []}


class TestSuccessfulFetch:
    def test_a_feature_collection_is_returned_as_is(self, fake_get):
        fake_get(FakeResponse(valid_payload([{"id": "x"}])))

        payload = fetch_feed()

        assert payload["type"] == "FeatureCollection"
        assert payload["features"] == [{"id": "x"}]

    def test_the_default_feed_is_used_when_no_url_is_given(self, fake_get):
        calls = fake_get(FakeResponse(valid_payload()))

        fetch_feed()

        assert calls["url"] == usgs.DEFAULT_FEED_URL

    def test_an_explicit_url_overrides_the_default(self, fake_get):
        calls = fake_get(FakeResponse(valid_payload()))

        fetch_feed(url="https://example.invalid/feed.geojson")

        assert calls["url"] == "https://example.invalid/feed.geojson"

    def test_a_timeout_is_always_passed(self, fake_get):
        """A request without a timeout could hang the whole ingestion."""
        calls = fake_get(FakeResponse(valid_payload()))

        fetch_feed()

        assert calls["timeout"] == usgs.DEFAULT_TIMEOUT_SECONDS

    def test_an_explicit_timeout_overrides_the_default(self, fake_get):
        calls = fake_get(FakeResponse(valid_payload()))

        fetch_feed(timeout=1.5)

        assert calls["timeout"] == 1.5


class TestFailedFetch:
    def test_a_transport_error_becomes_an_ingestion_error(self, fake_get):
        fake_get(httpx.ConnectError("connection refused"))

        with pytest.raises(IngestionError) as exc_info:
            fetch_feed()

        assert "Could not fetch" in str(exc_info.value)

    def test_an_http_error_status_becomes_an_ingestion_error(self, fake_get):
        failure = httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", "https://example.invalid"), response=None
        )
        fake_get(FakeResponse(None, raise_for_status=failure))

        with pytest.raises(IngestionError) as exc_info:
            fetch_feed()

        assert "Could not fetch" in str(exc_info.value)

    def test_a_non_json_body_becomes_an_ingestion_error(self, fake_get):
        fake_get(FakeResponse("<html>error page</html>"))

        with pytest.raises(IngestionError) as exc_info:
            fetch_feed()

        assert "not valid JSON" in str(exc_info.value)

    @pytest.mark.parametrize(
        "payload",
        [
            {"type": "Feature", "features": []},
            {"features": []},
            ["not", "a", "mapping"],
        ],
    )
    def test_a_payload_that_is_not_a_feature_collection_is_rejected(
        self, fake_get, payload
    ):
        fake_get(FakeResponse(payload))

        with pytest.raises(IngestionError) as exc_info:
            fetch_feed()

        assert "FeatureCollection" in str(exc_info.value)

    @pytest.mark.parametrize("features", [None, "not a list", {}])
    def test_a_payload_without_a_feature_list_is_rejected(self, fake_get, features):
        fake_get(FakeResponse({"type": "FeatureCollection", "features": features}))

        with pytest.raises(IngestionError) as exc_info:
            fetch_feed()

        assert "list of features" in str(exc_info.value)
