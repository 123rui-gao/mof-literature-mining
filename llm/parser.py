"""Strip markdown code fences and parse JSON array from LLM output."""

from __future__ import annotations

import json
import re

from loguru import logger


def parse_llm_json(raw: str) -> list[dict]:
    """Extract JSON array from LLM response text. Handles markdown code fences."""
    text = raw.strip()

    # Strip ```json / ``` fences
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()

    # Find the outermost JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        logger.warning(f"  JSON parse failed, raw first 500 chars: {raw[:500]}")
        return []

    return []
