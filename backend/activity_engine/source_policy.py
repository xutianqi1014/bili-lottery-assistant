"""Per-source activity-type policy used by runtime classification.

Readlist families describe how a source article was discovered.  They are
not a reliable description of the dynamic embedded in that article, so the
runtime classifier also receives an explicit allow-list from the source
profile.  Keeping this policy in a small module avoids coupling the generic
classifier to one particular UP's collection naming scheme.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.activity_engine.models import ActivityMode

_MODE_BY_CONFIG_NAME = {
    ActivityMode.OFFICIAL.value: ActivityMode.OFFICIAL,
    ActivityMode.UNOFFICIAL.value: ActivityMode.UNOFFICIAL,
    ActivityMode.RESERVATION.value: ActivityMode.RESERVATION,
}

DEFAULT_ACTIVITY_MODES = frozenset(
    {ActivityMode.OFFICIAL, ActivityMode.UNOFFICIAL}
)
NUOMI_ACTIVITY_MODES = frozenset(
    {ActivityMode.OFFICIAL, ActivityMode.RESERVATION}
)
TOMATO_FRIES_ACTIVITY_MODES = frozenset(
    {ActivityMode.OFFICIAL, ActivityMode.UNOFFICIAL, ActivityMode.RESERVATION}
)


@dataclass(frozen=True)
class SourceActivityPolicy:
    """Allowed runtime activity modes for one source profile."""

    source_key: str
    allowed_modes: frozenset[ActivityMode]
    configured: bool = True

    def allows(self, mode: ActivityMode) -> bool:
        return mode in self.allowed_modes

    @property
    def allowed_type_names(self) -> tuple[str, ...]:
        order = (
            ActivityMode.OFFICIAL,
            ActivityMode.UNOFFICIAL,
            ActivityMode.RESERVATION,
        )
        return tuple(mode.value for mode in order if mode in self.allowed_modes)


def policy_from_profile(
    *,
    source_key: str,
    adapter_key: str,
    config_json: str,
) -> SourceActivityPolicy:
    """Build a policy from ``SourceProfile.config_json``.

    Existing databases may have been created before ``activityTypes`` was
    introduced.  The adapter fallback keeps those databases deterministic
    while the profile seeding code adds the explicit value on the next start.
    """

    config = _load_object(config_json)
    raw_types = config.get("activityTypes")
    allowed = _parse_activity_types(raw_types)
    if not allowed:
        if adapter_key == "nuomi_backpack_v1":
            allowed = NUOMI_ACTIVITY_MODES
        elif adapter_key == "tomato_fries_v1":
            allowed = TOMATO_FRIES_ACTIVITY_MODES
        else:
            allowed = DEFAULT_ACTIVITY_MODES
    return SourceActivityPolicy(
        source_key=source_key,
        allowed_modes=frozenset(allowed),
        configured=isinstance(raw_types, list) and bool(allowed),
    )


def fallback_policy_for_family(family: str) -> SourceActivityPolicy:
    """Return a compatibility policy when a test/legacy run lacks a profile."""

    if family == "official":
        modes = frozenset({ActivityMode.OFFICIAL, ActivityMode.RESERVATION})
    else:
        modes = DEFAULT_ACTIVITY_MODES
    return SourceActivityPolicy(
        source_key="legacy-run",
        allowed_modes=modes,
        configured=False,
    )


def _parse_activity_types(value: Any) -> frozenset[ActivityMode]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        mode
        for item in value
        if isinstance(item, str)
        for mode in (_MODE_BY_CONFIG_NAME.get(item.strip().lower()),)
        if mode is not None
    )


def _load_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
