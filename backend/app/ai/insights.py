"""Insights over a dataset: what the model is asked, and with what.

The model never sees the rows. It sees the summary the API already
computes — totals, magnitude statistics, counts per day and per type — and
the handful of strongest events, so it can name them. That keeps the call
small and keeps the AI where CLAUDE.md puts it: an analytical layer over
data the platform has already ingested, validated and aggregated.
"""

import json
from typing import Any, Dict, List, Optional

from app.ai import gemini

STRONGEST_EVENTS = 5

# Pairs the model is shown when a comparison is asked for: the ones where
# the two agencies disagree most on the measure. Enough to name; the rest
# is in the means.
MOST_DISCORDANT = 5

# How many pairs to pull to find those: the comparison's own cap.
COMPARISON_PAIRS = 500

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
        "agency_comparison": {
            "type": "string",
            "description": "When a comparison with another agency is given: two or three sentences on how the two agree or differ, citing the counts and the mean differences. Empty otherwise.",
        },
    },
    "required": ["summary", "key_trends", "anomalies", "recommendations", "agency_comparison"],
}

SYSTEM_INSTRUCTION = """You are an analyst writing for a dashboard of public natural-event data.

You are given an aggregate summary of one dataset, already filtered by the
reader, plus its strongest events. A dataset holds events of one kind —
earthquakes, wildfires, storms — and `magnitude` is the number that kind is
measured by, in `magnitude_unit`: a seismic scale, hectares burnt, knots of
wind. Work only from those numbers. Do not invent events, places or figures
that are not in the data. If the data is thin or empty, say so plainly
instead of padding.

Be concrete: cite counts, magnitudes with their unit, dates and places from
the data. Keep every item to one sentence. Do not give safety advice or
speculate about future events; describe what the data shows.

Sources differ: USGS covers the world above roughly magnitude 4 plus finer
detail in the United States; INGV covers Italy in fine detail;
NASA EONET curates natural events worldwide from satellite and partner
reports; GDACS grades events by humanitarian impact and takes its seismic
data from USGS. Read the dataset's source and judge the coverage
accordingly.

When the digest carries a `comparison`, another agency's dataset of the
same kind was paired with this one: each pair is one event as the two
reported it. Say, in `agency_comparison`, how many events the other agency
also reported, how far apart the two put them in space and time, and how
much their measures differ — and name the most discordant pairs. Different
networks and methods explain most differences; do not call either agency
wrong. Leave `agency_comparison` empty when there is no comparison."""


def build_comparison(
    other: Dict[str, Any],
    matches: Dict[str, Any],
    window_seconds: float,
    radius_km: float,
) -> Dict[str, Any]:
    """What the model is told about the other agency's reports.

    The counts and the means over every pair, plus the pairs where the two
    measures differ most — those are the ones worth a sentence. Pairs
    without a measure on both sides cannot be discordant and are left out.
    """
    measured = [pair for pair in matches["pairs"] if pair["delta_magnitude"] is not None]
    discordant = sorted(measured, key=lambda pair: abs(pair["delta_magnitude"]), reverse=True)
    return {
        "other": {"name": other["name"], "source": other["source"]},
        "window_seconds": window_seconds,
        "radius_km": radius_km,
        "events": matches["events"],
        "matched": matches["matched"],
        "unmatched": matches["events"] - matches["matched"],
        "mean_abs_delta_seconds": matches["mean_abs_delta_seconds"],
        "mean_distance_km": matches["mean_distance_km"],
        "mean_abs_delta_magnitude": matches["mean_abs_delta_magnitude"],
        "most_discordant": [
            {
                "title": pair["event"]["title"],
                "magnitude": pair["event"]["magnitude"],
                "other_title": pair["other"]["title"],
                "other_magnitude": pair["other"]["magnitude"],
                "magnitude_unit": pair["event"]["magnitude_unit"],
                "delta_magnitude": pair["delta_magnitude"],
                "distance_km": round(pair["distance_km"], 1),
                "delta_seconds": round(pair["delta_seconds"], 1),
            }
            for pair in discordant[:MOST_DISCORDANT]
        ],
    }


def build_digest(
    dataset: Dict[str, Any],
    summary: Dict[str, Any],
    strongest: List[Dict[str, Any]],
    comparison: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The exact object the model is shown. Kept as data so a test can
    assert on it, and so it can be logged or returned for transparency."""
    digest = {
        "dataset": {
            "name": dataset["name"],
            "source": dataset["source"],
            "kind": dataset.get("kind", "earthquake"),
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
                "magnitude_unit": event.get("magnitude_unit"),
                "title": event["title"],
                "occurred_at": _iso(event["occurred_at"]),
                "event_type": event["event_type"],
                # Whatever the source knew beyond the shared columns — for a
                # quake its depth, its network — goes to the model as-is.
                **event.get("attributes", {}),
            }
            for event in strongest
        ],
    }
    if comparison is not None:
        digest["comparison"] = comparison
    return digest


def build_prompt(digest: Dict[str, Any]) -> str:
    return (
        "Analyse this dataset of {0} events and answer in the required JSON shape.\n\n".format(
            digest["dataset"]["kind"]
        )
        + json.dumps(digest, indent=2, default=str)
    )


def generate_insights(
    dataset: Dict[str, Any],
    summary: Dict[str, Any],
    strongest: List[Dict[str, Any]],
    comparison: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    digest = build_digest(dataset, summary, strongest, comparison)
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
        # Asked for even without a comparison, so the model cannot omit the
        # key; blanked here when there was nothing to compare, whatever it
        # wrote.
        "agency_comparison": (
            str(answer.get("agency_comparison", "")).strip() if comparison is not None else ""
        ),
    }


def _strings(value: Any) -> List[str]:
    """The schema asks for strings; a model that slipped in something else
    should not crash the response, just lose the odd item."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
