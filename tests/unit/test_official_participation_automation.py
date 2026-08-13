import pytest

from backend.use_cases.official_participation_automation import (
    OfficialParticipationAutomationAuthorizationError,
    OfficialParticipationAutomationPolicy,
)


def test_run_scope_accepts_multiple_targets_from_confirmed_plan() -> None:
    policy = OfficialParticipationAutomationPolicy()

    scope = policy.authorize_run(["12345", "67890", "12345"])

    assert scope == ("12345", "67890")
    policy.require_target("67890", scope)


def test_run_scope_rejects_out_of_plan_target() -> None:
    policy = OfficialParticipationAutomationPolicy()
    scope = policy.authorize_run(["12345", "67890"])

    with pytest.raises(
        OfficialParticipationAutomationAuthorizationError,
        match="OFFICIAL_AUTOMATION_TARGET_OUTSIDE_CONFIRMED_RUN",
    ):
        policy.require_target("99999", scope)


def test_run_scope_has_no_item_count_limit() -> None:
    dynamic_ids = [str(1_000_000_000 + index) for index in range(1_000)]

    scope = OfficialParticipationAutomationPolicy().authorize_run(dynamic_ids)

    assert scope == tuple(dynamic_ids)


def test_empty_or_non_numeric_run_scope_fails_closed() -> None:
    with pytest.raises(
        OfficialParticipationAutomationAuthorizationError,
        match="OFFICIAL_AUTOMATION_RUN_HAS_NO_OFFICIAL_TARGETS",
    ):
        OfficialParticipationAutomationPolicy().authorize_run([])
    with pytest.raises(
        OfficialParticipationAutomationAuthorizationError,
        match="OFFICIAL_AUTOMATION_RUN_TARGET_INVALID",
    ):
        OfficialParticipationAutomationPolicy().authorize_run(["not-an-opus-id"])
