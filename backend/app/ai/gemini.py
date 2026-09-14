"""The one call this project makes to Gemini.

Uses the Interactions API over plain HTTP, with a JSON Schema for the
response, so the model's answer is validated before anything reads it.
No SDK: one endpoint does not pay for a dependency tree, and httpx is
already here.

Documented at https://ai.google.dev/gemini-api/docs/structured-output
"""

import json
import os
from typing import Any, Dict, Optional

import httpx

from app.ai import AIError

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))


def api_key() -> Optional[str]:
    """Read per call, not at import, so a key added to .env after the
    server started — or removed — takes effect without a restart."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return api_key() is not None


def generate_json(
    prompt: str,
    schema: Dict[str, Any],
    system_instruction: str,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Ask the model for an object matching `schema` and return it parsed.

    Raises AIError with `configured=False` when there is no key, and with
    `configured=True` for anything that went wrong with the call or its
    output. The caller turns those into 503 and 502 respectively.
    """
    key = api_key()
    if key is None:
        raise AIError("AI insights are not configured: GEMINI_API_KEY is not set", configured=False)

    body = {
        "model": model or DEFAULT_MODEL,
        "input": prompt,
        "system_instruction": system_instruction,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
        # Public data, but there is no reason for Google to keep a copy of
        # each interaction; nothing here reads it back.
        "store": False,
    }

    try:
        response = httpx.post(
            ENDPOINT,
            json=body,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise AIError("Gemini answered {0}: {1}".format(
            exc.response.status_code, _reason(exc.response)
        ))
    except httpx.HTTPError as exc:
        raise AIError("Could not reach Gemini: {0}".format(exc))
    except ValueError as exc:
        raise AIError("Gemini did not answer with JSON: {0}".format(exc))

    text = _model_text(payload)
    try:
        result = json.loads(text)
    except ValueError as exc:
        raise AIError("The model's answer was not valid JSON: {0}".format(exc))
    if not isinstance(result, dict):
        raise AIError("The model's answer was not an object")
    return result


def _model_text(payload: Any) -> str:
    """Find the text in a completed Interaction.

    The answer sits at steps[].content[].text on the model_output step.
    Anything else — a refusal, an empty step, an unexpected shape — is an
    error the caller must see, not an empty string.
    """
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(steps, list):
        raise AIError("Unexpected reply from Gemini: no steps")
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for part in step.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return part["text"]
    raise AIError("Unexpected reply from Gemini: no text output")


def _reason(response: httpx.Response) -> str:
    try:
        detail = response.json()
        message = detail.get("error", {}).get("message")
        if isinstance(message, str):
            return message
    except ValueError:
        pass
    return response.text[:200]
