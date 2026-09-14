"""Insights over a dataset: what the model is asked, and with what.

The model never sees the rows. It sees the summary the API already
computes — totals, magnitude statistics, counts per day and per type — and
the handful of strongest events, so it can name them. That keeps the call
small and keeps the AI where CLAUDE.md puts it: an analytical layer over
data the platform has already ingested, validated and aggregated.
"""

import json
from typing import Any, Dict, List

from app.ai import gemini

STRONGEST_EVENTS = 5

# What the model must answer with. The endpoint's response model mirrors
# this, so a conforming answer passes straight through.
RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Two or three sentences on what this data shows.",
        },
        "key_trends": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Patterns over time or across categories, each one sentence.",
        },
        "anomalies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Things that stand out — unusual days, outliers, gaps.",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What a reader of this dashboard might do or look at next.",
        },
    },
    "required": ["summary", "key_trends", "anomalies", "recommendations"],
}

SYSTEM_INSTRUCTION = """You are an analyst writing for a dashboard of public earthquake data.

You are given an aggregate summary of one dataset, already filtered by the
reader, plus its strongest events. Work only from those numbers. Do not invent
events, places or figures that are not in the data. If the data is thin or
empty, say so plainly instead of padding.

Be concrete: cite counts, magnitudes, dates and places from the data. Keep
every item to one sentence. Do not give safety advice or speculate about
future earthquakes; describe what the data shows.

Sources differ: USGS covers the world above roughly magnitude 4 plus finer
detail in the United States; INGV covers Italy in fine detail. Read the
dataset's source and judge the coverage accordingly."""


def build_digest(
    dataset: Dict[str, Any],
    summary: Dict[str, Any],
    strongest: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """The exact object the model is shown. Kept as data so a test can
    assert on it, and so it can be logged or returned for transparency."""
    return {
        "dataset": {
            "name": dataset["name"],
            "source": dataset["source"],
            "description": dataset.get("description"),
        },
        "filters": summary.get("filters", {}),
        "total_events": summary["total"],
        "magnitude": summary["magnitude"],
        "time_span": {
            "first": _iso(summary["occurred_at"]["first"]),
            "last": _iso(summary["occurred_at"]["last"]),
        },
        "events_by_type": summary["by_event_type"],
        "events_by_day": [
            {"day": _iso(row["day"]), "count": row["count"]} for row in summary["by_day"]
        ],
        "strongest_events": [
            {
                "magnitude": event["magnitude"],
                "place": event["place"],
                "occurred_at": _iso(event["occurred_at"]),
                "depth_km": event["depth_km"],
                "event_type": event["event_type"],
            }
            for event in strongest
        ],
    }


def build_prompt(digest: Dict[str, Any]) -> str:
    return (
        "Analyse this earthquake dataset and answer in the required JSON shape.\n\n"
        + json.dumps(digest, indent=2, default=str)
    )


def generate_insights(
    dataset: Dict[str, Any],
    summary: Dict[str, Any],
    strongest: List[Dict[str, Any]],
) -> Dict[str, Any]:
    digest = build_digest(dataset, summary, strongest)
    answer = gemini.generate_json(
        prompt=build_prompt(digest),
        schema=RESPONSE_SCHEMA,
        system_instruction=SYSTEM_INSTRUCTION,
    )
    return {
        "summary": str(answer.get("summary", "")),
        "key_trends": _strings(answer.get("key_trends")),
        "anomalies": _strings(answer.get("anomalies")),
        "recommendations": _strings(answer.get("recommendations")),
    }


def _strings(value: Any) -> List[str]:
    """The schema asks for strings; a model that slipped in something else
    should not crash the response, just lose the odd item."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
