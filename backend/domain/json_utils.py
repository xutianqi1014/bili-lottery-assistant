"""Tolerant readers for persisted JSON objects.

List readers remain with their callers because their validation rules differ.
"""

import json
from typing import Any


def load_json_object(value: str) -> dict[str, Any]:
    """Read a JSON object; malformed JSON and non-object values become empty."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
