"""Authorization policy derived from an immutable confirmed run plan."""

from __future__ import annotations

from dataclasses import dataclass


class OfficialParticipationAutomationError(RuntimeError):
    """Base error for a rejected automatic official-participation target."""


class OfficialParticipationAutomationAuthorizationError(
    OfficialParticipationAutomationError
):
    """Raised when a target is outside the configured automatic run scope."""


@dataclass(frozen=True, slots=True)
class OfficialParticipationAutomationPolicy:
    """Validate that automation cannot expand beyond one confirmed run."""

    def authorize_run(self, dynamic_ids: list[str]) -> tuple[str, ...]:
        unique_ids = tuple(dict.fromkeys(dynamic_ids))
        if not unique_ids:
            raise OfficialParticipationAutomationAuthorizationError(
                "OFFICIAL_AUTOMATION_RUN_HAS_NO_OFFICIAL_TARGETS"
            )
        for dynamic_id in unique_ids:
            if not dynamic_id.isdecimal():
                raise OfficialParticipationAutomationAuthorizationError(
                    "OFFICIAL_AUTOMATION_RUN_TARGET_INVALID"
                )
        return unique_ids

    def require_target(self, dynamic_id: str, run_dynamic_ids: tuple[str, ...]) -> None:
        if dynamic_id not in run_dynamic_ids:
            raise OfficialParticipationAutomationAuthorizationError(
                "OFFICIAL_AUTOMATION_TARGET_OUTSIDE_CONFIRMED_RUN"
            )
