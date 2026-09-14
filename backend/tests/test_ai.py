"""Insights: the Gemini call, the digest, and the endpoint.

`httpx.post` is replaced throughout. No test here needs a key, the network
or a database unless marked; the endpoint tests use the test database.
"""

import json
from datetime import datetime

import httpx
import pytest

from app.ai import AIError, gemini, insights
from app.db import repository
from tests.conftest import requires_postgres


def interaction(text):
    """A completed Interaction whose model_output says `text`."""
    return {
        "id": "v1_x",
        "status": "completed",
        "model": "gemini-3.8-flash",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
        "usage": {},
    }


GOOD_ANSWER = {
    "summary": "A week of 344 events, most of them small.",
    "key_trends": ["Activity peaked on 2026-09-10 with 61 events."],
    "anomalies": ["One M6.3 event off Vanuatu stands far above the rest."],
    "recommendations": ["Filter to magnitude 3 and above to see the significant events."],
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("POST", gemini.ENDPOINT), response=self
            )

    def json(self):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


@pytest.fixture
def without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def fake_post(monkeypatch):
    """Install a stand-in for httpx.post and keep what it was called with."""
    calls = {}

    def install(response):
        def _post(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(gemini.httpx, "post", _post)
        return calls

    return install


class TestConfiguration:
    def test_no_key_means_not_configured(self, without_key):
        assert gemini.is_configured() is False

    def test_a_blank_key_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "   ")

        assert gemini.is_configured() is False

    def test_a_key_is_read_per_call(self, monkeypatch):
        """Adding a key to .env must not need a restart."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert gemini.is_configured() is False
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        assert gemini.is_configured() is True

    def test_calling_without_a_key_says_so_and_never_hits_the_network(
        self, without_key, fake_post
    ):
        calls = fake_post(FakeResponse(interaction("{}")))

        with pytest.raises(AIError) as exc_info:
            gemini.generate_json("p", {"type": "object"}, "s")

        assert exc_info.value.configured is False
        assert "GEMINI_API_KEY" in str(exc_info.value)
        assert calls == {}


class TestTheRequest:
    def test_it_goes_to_the_interactions_endpoint_with_the_key_in_a_header(
        self, with_key, fake_post
    ):
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        gemini.generate_json("prompt", {"type": "object"}, "system")

        assert calls["url"] == gemini.ENDPOINT
        assert calls["headers"]["x-goog-api-key"] == "test-key"
        assert "test-key" not in calls["url"]

    def test_it_asks_for_json_matching_the_schema(self, with_key, fake_post):
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))
        schema = {"type": "object", "properties": {"summary": {"type": "string"}}}

        gemini.generate_json("prompt", schema, "system")

        body = calls["json"]
        assert body["response_format"] == {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        }
        assert body["input"] == "prompt"
        assert body["system_instruction"] == "system"
        assert body["model"] == gemini.DEFAULT_MODEL

    def test_interactions_are_not_stored(self, with_key, fake_post):
        """Nothing reads them back; no reason for Google to keep a copy."""
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        gemini.generate_json("p", {"type": "object"}, "s")

        assert calls["json"]["store"] is False

    def test_a_timeout_is_always_sent(self, with_key, fake_post):
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        gemini.generate_json("p", {"type": "object"}, "s")

        assert calls["timeout"] == gemini.DEFAULT_TIMEOUT_SECONDS


class TestTheAnswer:
    def test_the_models_json_is_returned_parsed(self, with_key, fake_post):
        fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        assert gemini.generate_json("p", {"type": "object"}, "s") == GOOD_ANSWER

    def test_a_transport_error_is_an_ai_error(self, with_key, fake_post):
        fake_post(httpx.ConnectError("refused"))

        with pytest.raises(AIError) as exc_info:
            gemini.generate_json("p", {"type": "object"}, "s")

        assert exc_info.value.configured is True
        assert "Could not reach Gemini" in str(exc_info.value)

    def test_an_error_status_carries_googles_message(self, with_key, fake_post):
        fake_post(FakeResponse({"error": {"message": "API key not valid"}}, status=400))

        with pytest.raises(AIError) as exc_info:
            gemini.generate_json("p", {"type": "object"}, "s")

        assert "400" in str(exc_info.value)
        assert "API key not valid" in str(exc_info.value)

    def test_model_text_that_is_not_json_is_an_ai_error(self, with_key, fake_post):
        fake_post(FakeResponse(interaction("Sure! Here is my analysis: ...")))

        with pytest.raises(AIError) as exc_info:
            gemini.generate_json("p", {"type": "object"}, "s")

        assert "not valid JSON" in str(exc_info.value)

    def test_model_json_that_is_not_an_object_is_an_ai_error(self, with_key, fake_post):
        fake_post(FakeResponse(interaction("[1, 2]")))

        with pytest.raises(AIError):
            gemini.generate_json("p", {"type": "object"}, "s")

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "completed"},
            {"steps": "nope"},
            {"steps": []},
            {"steps": [{"type": "thought", "content": [{"type": "text", "text": "hm"}]}]},
            {"steps": [{"type": "model_output", "content": []}]},
        ],
    )
    def test_a_reply_without_model_text_is_an_ai_error(self, with_key, fake_post, payload):
        fake_post(FakeResponse(payload))

        with pytest.raises(AIError) as exc_info:
            gemini.generate_json("p", {"type": "object"}, "s")

        assert "Unexpected reply" in str(exc_info.value)


class TestTheDigest:
    dataset = {"name": "Terremoti Italia", "source": "ingv", "description": None}
    summary = {
        "filters": {"min_magnitude": 2.0},
        "total": 344,
        "magnitude": {"min": 2.0, "max": 6.3, "average": 2.7, "unknown": 0},
        "occurred_at": {"first": datetime(2026, 9, 7, 1, 0), "last": datetime(2026, 9, 14, 7, 0)},
        "by_event_type": [{"event_type": "earthquake", "count": 340}],
        "by_day": [{"day": datetime(2026, 9, 10).date(), "count": 61}],
    }
    strongest = [
        {
            "external_id": "x",
            "magnitude": 6.3,
            "title": "Vanuatu Islands",
            "event_type": "earthquake",
            "occurred_at": datetime(2026, 9, 9, 3, 0),
            "attributes": {"depth_km": 33.0, "tsunami": False},
        }
    ]

    def test_it_carries_the_numbers_the_model_must_cite(self):
        digest = insights.build_digest(self.dataset, self.summary, self.strongest)

        assert digest["total_events"] == 344
        assert digest["magnitude"]["max"] == 6.3
        assert digest["events_by_day"] == [{"day": "2026-09-10", "count": 61}]
        assert digest["strongest_events"][0]["title"] == "Vanuatu Islands"
        assert digest["strongest_events"][0]["depth_km"] == 33.0
        assert digest["dataset"]["kind"] == "earthquake"
        assert digest["dataset"]["source"] == "ingv"
        assert digest["filters"] == {"min_magnitude": 2.0}

    def test_it_never_carries_rows(self):
        """Only the summary and a handful of events reach the model."""
        digest = insights.build_digest(self.dataset, self.summary, self.strongest)

        assert "items" not in digest
        assert len(json.dumps(digest, default=str)) < 4000

    def test_dates_are_serialisable(self):
        digest = insights.build_digest(self.dataset, self.summary, self.strongest)

        json.dumps(digest)  # must not raise

    def test_the_prompt_embeds_the_digest(self):
        digest = insights.build_digest(self.dataset, self.summary, self.strongest)

        prompt = insights.build_prompt(digest)

        assert "Vanuatu Islands" in prompt
        assert '"total_events": 344' in prompt

    def test_the_answer_is_shaped_even_if_the_model_strays(self, monkeypatch):
        """The schema asks for strings; a stray number must not crash."""
        monkeypatch.setattr(
            gemini,
            "generate_json",
            lambda **kwargs: {"summary": "s", "key_trends": ["a", 7, ""], "anomalies": None},
        )

        answer = insights.generate_insights(self.dataset, self.summary, self.strongest)

        assert answer == {
            "summary": "s",
            "key_trends": ["a"],
            "anomalies": [],
            "recommendations": [],
        }

    def test_the_system_instruction_forbids_invention(self):
        assert "Do not invent" in insights.SYSTEM_INSTRUCTION


@requires_postgres
class TestTheEndpoint:
    @pytest.fixture
    def seeded(self, db, dataset):
        records = [
            {
                "external_id": "eq{0}".format(i),
                "magnitude": float(i),
                "magnitude_unit": "ml",
                "title": "place {0}".format(i),
                "event_type": "earthquake",
                "occurred_at": datetime(2026, 9, 9, i, 0),
                "source_updated_at": None,
                "longitude": 0.0,
                "latitude": 0.0,
                "attributes": {"depth_km": 1.0, "tsunami": False, "significance": None},
                "url": None,
            }
            for i in range(1, 8)
        ]
        with db() as connection:
            repository.upsert_events(connection, dataset["id"], records)
        return dataset

    def test_ai_status_reports_the_key(self, client, without_key):
        assert client.get("/api/ai").json()["configured"] is False

    def test_without_a_key_it_is_a_503_and_the_rest_still_works(
        self, client, seeded, without_key
    ):
        """Off is not broken: the feature is unavailable, the API is up."""
        response = client.get("/api/datasets/{0}/insights".format(seeded["id"]))

        assert response.status_code == 503
        assert "GEMINI_API_KEY" in response.json()["detail"]
        assert client.get("/api/datasets/{0}/events".format(seeded["id"])).status_code == 200

    def test_a_successful_answer_is_returned_in_shape(
        self, client, seeded, with_key, fake_post
    ):
        fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        response = client.get("/api/datasets/{0}/insights".format(seeded["id"]))

        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == GOOD_ANSWER["summary"]
        assert body["key_trends"] == GOOD_ANSWER["key_trends"]
        assert body["dataset_id"] == seeded["id"]
        assert body["model"] == gemini.DEFAULT_MODEL

    def test_the_model_is_shown_the_filtered_view(self, client, seeded, with_key, fake_post):
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        client.get("/api/datasets/{0}/insights?min_magnitude=5".format(seeded["id"]))

        prompt = calls["json"]["input"]
        assert '"total_events": 3' in prompt  # magnitudes 5, 6, 7
        assert "place 7" in prompt
        assert "place 1" not in prompt

    def test_the_strongest_events_are_the_strongest(self, client, seeded, with_key, fake_post):
        calls = fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))

        client.get("/api/datasets/{0}/insights".format(seeded["id"]))

        digest = json.loads(calls["json"]["input"].split("\n\n", 1)[1])
        magnitudes = [e["magnitude"] for e in digest["strongest_events"]]
        assert magnitudes == [7.0, 6.0, 5.0, 4.0, 3.0]

    def test_an_upstream_failure_is_a_502(self, client, seeded, with_key, fake_post):
        fake_post(FakeResponse({"error": {"message": "quota exceeded"}}, status=429))

        response = client.get("/api/datasets/{0}/insights".format(seeded["id"]))

        assert response.status_code == 502
        assert "quota exceeded" in response.json()["detail"]

    def test_an_unknown_dataset_is_a_404_before_any_call(
        self, client, with_key, fake_post
    ):
        calls = fake_post(FakeResponse(interaction("{}")))

        assert client.get("/api/datasets/999/insights").status_code == 404
        assert calls == {}

    def test_the_key_never_reaches_the_log(self, client, seeded, with_key, fake_post, caplog):
        import logging

        fake_post(FakeResponse(interaction(json.dumps(GOOD_ANSWER))))
        with caplog.at_level(logging.DEBUG):
            client.get("/api/datasets/{0}/insights".format(seeded["id"]))

        assert "test-key" not in caplog.text
