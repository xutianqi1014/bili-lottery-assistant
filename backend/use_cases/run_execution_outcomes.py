"""Immutable runtime evidence and outcome mapping for run execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from backend.activity_engine.models import (
    ActionResult,
    ActionState,
    ActivityClassification,
    ActivityMode,
    ParticipationRequirements,
    UnofficialType,
)
from backend.activity_engine.runtime_inspection import RuntimeActivityRead
from backend.activity_engine.source_policy import SourceActivityPolicy
from backend.activity_engine.unofficial import UnofficialActionPlan

DYNAMIC_UNAVAILABLE_SKIP_CODE = "DYNAMIC_UNAVAILABLE_SKIPPED"


@dataclass(frozen=True)
class RuntimeOutcome:
    item_state: str
    mode: str
    unofficial_type: str
    platform_status: str
    result_code: str
    result_message: str
    block_reason: str | None
    inspection: dict[str, Any]
    selector_version: str
    inspected_at: datetime
    requirements: ParticipationRequirements | None = None
    unofficial_action_plan: UnofficialActionPlan | None = None
    comment_context: str = ""


def _inspection_payload(
    read: RuntimeActivityRead,
    classification: ActivityClassification,
    requirements: ParticipationRequirements,
) -> dict[str, Any]:
    return {
        "pageTitle": read.page_title,
        "bodyExcerpt": read.body_excerpt,
        "dynamicUnavailable": read.dynamic_unavailable,
        "mode": classification.mode.value,
        "unofficialType": classification.unofficial_type.value,
        "isExpired": classification.is_expired,
        "isParticipated": classification.is_participated,
        "activityLikeState": read.activity_like_state,
        "activityLikeReasonCode": read.activity_like_reason_code,
        "confidence": classification.confidence,
        "evidenceCodes": list(classification.evidence_codes),
        "requiredTopics": list(requirements.required_topics),
        "requiredMentionCount": requirements.required_mention_count,
        "commentInstruction": requirements.comment_instruction,
        "requiredActions": list(requirements.required_actions),
        "mentionLimitExceeded": requirements.mention_limit_exceeded,
        "requirementEvidenceCodes": list(requirements.evidence_codes),
        "officialEntryOpened": read.lottery_entry_opened,
        "officialPanelSelector": read.lottery_panel_selector,
        "officialPanelText": read.lottery_panel_text,
        "officialPanelError": read.lottery_panel_error,
        "reservationEntryPresent": read.reservation_entry_present,
        "reservationActive": read.reservation_active,
        "reservationControlText": read.reservation_control_text,
        "nonofficialOuterText": read.nonofficial_outer_text,
        "nonofficialForwardedOriginalText": read.nonofficial_forwarded_original_text,
        "nonofficialHasForwardedOriginal": read.nonofficial_has_forwarded_original,
        "nonofficialAuthorName": read.nonofficial_author_name,
        "nonofficialCommentEditorPresent": read.nonofficial_comment_editor_present,
        "nonofficialCommentPublishPresent": read.nonofficial_comment_publish_present,
        "nonofficialCommentRepostControlPresent": (read.nonofficial_comment_repost_control_present),
        "nonofficialEvidenceCodes": list(read.nonofficial_evidence_codes),
        "nonofficialSelectorVersion": read.nonofficial_selector_version,
    }


def _already_liked_runtime_outcome(read: RuntimeActivityRead) -> RuntimeOutcome:
    """Build the type-independent terminal result for an active like marker."""

    classification = ActivityClassification(
        mode=ActivityMode.UNKNOWN,
        unofficial_type=UnofficialType.UNKNOWN,
        is_expired=False,
        is_participated=True,
        confidence="high",
        evidence_codes=("ACTIVITY_LIKE_ACTIVE_EARLY_SKIP",),
    )
    requirements = ParticipationRequirements()
    result = ActionResult(
        ActionState.ALREADY_LIKED_SKIPPED,
        "ALREADY_PARTICIPATED_LIKED",
        "动态已经点赞，直接按已参与跳过，不判断动态类型或执行后续写操作。",
    )
    inspection = _inspection_payload(read, classification, requirements)
    inspection["typeClassificationSkipped"] = True
    inspection["resultCode"] = result.code
    inspection["resultMessage"] = result.message
    return RuntimeOutcome(
        item_state="skipped",
        mode=ActivityMode.UNKNOWN.value,
        unofficial_type=UnofficialType.UNKNOWN.value,
        platform_status="already_liked",
        result_code=result.code,
        result_message=result.message,
        block_reason=None,
        inspection=inspection,
        selector_version=read.selector_version,
        inspected_at=datetime.now(UTC),
        requirements=None,
        unofficial_action_plan=None,
        comment_context="",
    )


def _activity_like_state_unknown_runtime_outcome(
    read: RuntimeActivityRead,
) -> RuntimeOutcome:
    """Stop before type-specific reads when the global like marker is unclear."""

    classification = ActivityClassification(
        mode=ActivityMode.UNKNOWN,
        unofficial_type=UnofficialType.UNKNOWN,
        is_expired=None,
        is_participated=None,
        confidence="low",
        evidence_codes=("ACTIVITY_LIKE_STATE_UNKNOWN_EARLY_STOP",),
    )
    requirements = ParticipationRequirements()
    result = ActionResult(
        ActionState.WAITING_USER,
        "ACTIVITY_LIKE_STATE_UNKNOWN",
        "打开动态后无法唯一确认点赞状态，已停止类型判断和所有写操作，请人工复核。",
        True,
    )
    inspection = _inspection_payload(read, classification, requirements)
    inspection["typeClassificationSkipped"] = True
    inspection["resultCode"] = result.code
    inspection["resultMessage"] = result.message
    return RuntimeOutcome(
        item_state="waiting_user",
        mode=ActivityMode.UNKNOWN.value,
        unofficial_type=UnofficialType.UNKNOWN.value,
        platform_status="manual_review",
        result_code=result.code,
        result_message=result.message,
        block_reason=result.message,
        inspection=inspection,
        selector_version=read.selector_version,
        inspected_at=datetime.now(UTC),
        requirements=None,
        unofficial_action_plan=None,
        comment_context="",
    )


def _item_state_for(action_state: ActionState) -> str:
    if action_state in {
        ActionState.EXPIRED,
        ActionState.ALREADY_PARTICIPATED,
        ActionState.ALREADY_LIKED_SKIPPED,
    }:
        return "skipped"
    if action_state is ActionState.SUCCESS:
        return "completed"
    return "waiting_user"


def _platform_status(
    mode: ActivityMode,
    action_state: ActionState,
    result_code: str | None = None,
) -> str:
    if action_state is ActionState.EXPIRED:
        return "expired"
    if action_state is ActionState.ALREADY_PARTICIPATED:
        return "already_participated"
    if action_state is ActionState.ALREADY_LIKED_SKIPPED:
        return "already_liked"
    if (
        mode is ActivityMode.UNKNOWN
        or action_state is ActionState.MODE_MISMATCH
        or _should_record_runtime_problem(result_code or "")
    ):
        return "manual_review"
    return "eligible_waiting_user"


def _should_record_runtime_problem(result_code: str) -> bool:
    return (
        result_code.startswith("RUNTIME_INSPECTION_")
        or result_code.startswith("RESERVATION_")
        or result_code
        in {
            "CLASSIFICATION_UNKNOWN",
            "MODE_MISMATCH",
            "OFFICIAL_LOTTERY_ENTRY_CLICK_FAILED",
            "OFFICIAL_LOTTERY_PANEL_NOT_FOUND",
            "OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY",
            "RESERVATION_CONTROL_AMBIGUOUS",
            "RESERVATION_CONTROL_DISABLED",
            "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED",
            "ACTIVITY_LIKE_STATE_UNKNOWN",
        }
    )


def _source_policy_blocked_outcome(
    outcome: RuntimeOutcome,
    policy: SourceActivityPolicy,
) -> RuntimeOutcome:
    message = (
        f"当前来源仅允许 {', '.join(policy.allowed_type_names)} 动态；"
        f"页面被识别为 {outcome.mode}，已停止本条且不执行写操作。"
    )
    inspection = {
        **outcome.inspection,
        "allowedActivityTypes": list(policy.allowed_type_names),
        "resultCode": "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED",
        "resultMessage": message,
    }
    return replace(
        outcome,
        item_state="waiting_user",
        platform_status="manual_review",
        result_code="SOURCE_ACTIVITY_TYPE_NOT_ALLOWED",
        result_message=message,
        block_reason=message,
        inspection=inspection,
    )



def failure_outcome(exc: Exception) -> RuntimeOutcome:
    code = f"RUNTIME_INSPECTION_{type(exc).__name__.upper()}"
    message = "动态页面即时读取失败，需要人工复核；本轮不会自动重试写操作。"
    return RuntimeOutcome(
        item_state="waiting_user",
        mode="unknown",
        unofficial_type="unknown",
        platform_status="manual_review",
        result_code=code,
        result_message=message,
        block_reason=message,
        inspection={"errorType": type(exc).__name__, "resultCode": code},
        selector_version="runtime-inspection-error",
        inspected_at=datetime.now(UTC),
        comment_context="",
    )
