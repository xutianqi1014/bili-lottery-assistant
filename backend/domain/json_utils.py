"""Tolerant readers for persisted JSON strings."""

import json
from typing import Any


def load_json_object(value: str) -> dict[str, Any]:
    """Read a JSON object; malformed JSON and non-object values become empty."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_json_ints(value: str) -> list[int]:
    """Keep integer values, order and duplicates; preserve legacy bool handling.

    Python bool is an int subclass. Existing persisted-list readers accepted
    it, so this consolidation deliberately keeps that behavior.
    """
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, int)]
