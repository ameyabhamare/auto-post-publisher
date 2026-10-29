"""One structured-output request to Claude, shared by drafting and style learning."""

import json

import anthropic

from .config import EFFORT, MODEL

client = anthropic.Anthropic()


class ClaudeError(Exception):
    pass


def call_json(system: list[dict], messages: list[dict], schema: dict, max_tokens: int = 16000):
    """Run one request constrained to `schema`. Returns (parsed JSON, response content as dicts)."""
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
            # If a safety classifier declines, re-run on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Could not reach the Claude API. Check your connection.") from e

    if response.stop_reason == "refusal":
        raise ClaudeError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude's reply was cut off (max_tokens). Try shorter input or raise max_tokens.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ClaudeError("Claude returned no text.")
    return json.loads(text), response.to_dict()["content"]
