"""Non-official giveaway action planning and write safety boundaries.

The DOM transport lives in :mod:`transport`; this module owns the reusable
action order, target validation and no-retry checkpoint semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse

from backend.activity_engine.models import ParticipationRequirements, UnofficialType
from backend.activity_engine.shared.manual_gate import ManualGate


class UnofficialAction(StrEnum):
    """The only mutation steps allowed in the non-official flow."""

    COMMENT = "comment"
    REPOST = "repost"
    LIKE = "like"
    FOLLOW = "follow"


DEFAULT_UNOFFICIAL_ACTIONS: tuple[UnofficialAction, ...] = (
    UnofficialAction.COMMENT,
    UnofficialAction.REPOST,
    UnofficialAction.LIKE,
    UnofficialAction.FOLLOW,
)

# Kept as a named compatibility alias for callers that distinguish the
# classifier subtype.  Both normal and boosted giveaways now use the comment
# component's sync-to-dynamic checkbox, so their executable sequence is the
# same: comment (with repost) -> like -> follow.
BOOSTED_UNOFFICIAL_ACTIONS: tuple[UnofficialAction, ...] = DEFAULT_UNOFFICIAL_ACTIONS


class CheckpointState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


class WriteOutcomeState(StrEnum):
    SUCCESS = "success"
    ALREADY_DONE = "already_done"
    UNKNOWN = "unknown"
    FAILED = "failed"


class CheckpointError(RuntimeError):
    """Base class for an invalid or unsafe checkpoint transition."""


class CheckpointOrderError(CheckpointError):
    """Raised when an action is started before its predecessors are confirmed."""


class CheckpointBlockedError(CheckpointError):
    """Raised when an unknown/failed result prevents automatic continuation."""


class InvalidWriteTargetError(CheckpointError):
    """Raised when a future writer is given a URL outside the dynamic allowlist."""


@dataclass(frozen=True, slots=True)
class WriteOperationResult:
    """Normalized result returned by a browser write adapter."""

    state: WriteOutcomeState
    code: str
    message: str
    confirmed_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionCheckpoint:
    action: UnofficialAction
    state: CheckpointState = CheckpointState.PENDING
    attempts: int = 0
    result_code: str = "CHECKPOINT_PENDING"
    result_message: str = "等待执行"


class ActionCheckpointLedger:
    """In-memory state machine for one non-official giveaway.

    A checkpoint becomes ``confirmed`` only after a definite success or an
    idempotent ``already_done`` response.  ``unknown`` and ``failed`` are
    terminal for automatic execution: callers must stop and ask a human to
    inspect the page.  This intentionally prevents duplicate comments,
    reposts, likes, or follows after a timeout whose server-side effect is
    unknown.
    """

    def __init__(self, actions: Sequence[UnofficialAction] = DEFAULT_UNOFFICIAL_ACTIONS):
        normalized = tuple(_coerce_action(action) for action in actions)
        if not normalized:
            raise ValueError("UNOFFICIAL_ACTIONS_EMPTY")
        if len(set(normalized)) != len(normalized):
            raise ValueError("UNOFFICIAL_ACTIONS_DUPLICATE")
        self._actions = normalized
        self._checkpoints = {action: ActionCheckpoint(action=action) for action in normalized}

    @property
    def actions(self) -> tuple[UnofficialAction, ...]:
        return self._actions

    @property
    def checkpoints(self) -> tuple[ActionCheckpoint, ...]:
        return tuple(self._checkpoints[action] for action in self._actions)

    @property
    def status(self) -> str:
        states = [checkpoint.state for checkpoint in self.checkpoints]
        if all(state is CheckpointState.CONFIRMED for state in states):
            return "completed"
        if any(state is CheckpointState.UNKNOWN for state in states):
            return "blocked_unknown"
        if any(state is CheckpointState.FAILED for state in states):
            return "blocked_failed"
        if any(state is CheckpointState.IN_PROGRESS for state in states):
            return "in_progress"
        return "ready"

    @property
    def next_action(self) -> UnofficialAction | None:
        if self.status != "ready":
            return None
        for checkpoint in self.checkpoints:
            if checkpoint.state is CheckpointState.PENDING:
                return checkpoint.action
        return None

    def start(self, action: UnofficialAction) -> ActionCheckpoint:
        action = _coerce_action(action)
        checkpoint = self._get(action)
        if self.status in {"blocked_unknown", "blocked_failed"}:
            raise CheckpointBlockedError(f"CHECKPOINT_BLOCKED:{self.status}:{action.value}")
        if checkpoint.state is not CheckpointState.PENDING:
            raise CheckpointOrderError(
                f"CHECKPOINT_NOT_PENDING:{action.value}:{checkpoint.state.value}"
            )
        if self.next_action is not action:
            expected = self.next_action.value if self.next_action else "none"
            raise CheckpointOrderError(f"CHECKPOINT_ORDER_REQUIRED:{expected}:{action.value}")
        updated = replace(
            checkpoint,
            state=CheckpointState.IN_PROGRESS,
            result_code="CHECKPOINT_IN_PROGRESS",
            result_message="动作已获准，等待写适配器返回确定结果",
        )
        self._checkpoints[action] = updated
        return updated

    def record(self, action: UnofficialAction, result: WriteOperationResult) -> ActionCheckpoint:
        action = _coerce_action(action)
        checkpoint = self._get(action)
        if checkpoint.state is not CheckpointState.IN_PROGRESS:
            raise CheckpointOrderError(
                f"CHECKPOINT_NOT_IN_PROGRESS:{action.value}:{checkpoint.state.value}"
            )
        if result.state in {WriteOutcomeState.SUCCESS, WriteOutcomeState.ALREADY_DONE}:
            next_state = CheckpointState.CONFIRMED
        elif result.state is WriteOutcomeState.UNKNOWN:
            next_state = CheckpointState.UNKNOWN
        else:
            next_state = CheckpointState.FAILED
        updated = replace(
            checkpoint,
            state=next_state,
            attempts=checkpoint.attempts + 1,
            result_code=result.code,
            result_message=result.message,
        )
        self._checkpoints[action] = updated
        return updated

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "nextAction": self.next_action.value if self.next_action else None,
            "unknownResultPolicy": "manual_review_no_retry",
            "checkpoints": [
                {
                    "action": checkpoint.action.value,
                    "state": checkpoint.state.value,
                    "attempts": checkpoint.attempts,
                    "resultCode": checkpoint.result_code,
                    "resultMessage": checkpoint.result_message,
                }
                for checkpoint in self.checkpoints
            ],
        }

    def _get(self, action: UnofficialAction) -> ActionCheckpoint:
        try:
            return self._checkpoints[action]
        except KeyError as exc:
            raise CheckpointOrderError(f"UNKNOWN_UNOFFICIAL_ACTION:{action.value}") from exc


@dataclass(frozen=True, slots=True)
class UnofficialActionPlan:
    """Immutable action description captured in the confirmed run plan."""

    actions: tuple[UnofficialAction, ...] = DEFAULT_UNOFFICIAL_ACTIONS
    execution_policy: str = "confirm_each"
    unknown_result_policy: str = "manual_review_no_retry"
    direct_write_enabled: bool = False
    interaction_strategy: str = "comment_with_repost_checkbox"
    target_scope: str = "current_dynamic"
    unofficial_type: str = UnofficialType.NORMAL.value
    detected_required_actions: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "actions": [action.value for action in self.actions],
            "executionPolicy": self.execution_policy,
            "unknownResultPolicy": self.unknown_result_policy,
            "directWriteEnabled": self.direct_write_enabled,
            "interactionStrategy": self.interaction_strategy,
            "targetScope": self.target_scope,
            "unofficialType": self.unofficial_type,
            "detectedRequiredActions": list(self.detected_required_actions),
            "actionLabels": {
                "comment": "评论",
                "repost": "转发",
                "like": "点赞",
                "follow": "关注作者",
            },
        }


class UnofficialActionPlanner:
    """Build a deterministic action plan without opening a write request."""

    def build(
        self,
        *,
        unofficial_type: UnofficialType = UnofficialType.UNKNOWN,
        requirements: ParticipationRequirements | None = None,
        direct_write_enabled: bool = False,
    ) -> UnofficialActionPlan:
        actions = (
            BOOSTED_UNOFFICIAL_ACTIONS
            if unofficial_type is UnofficialType.BOOSTED
            else DEFAULT_UNOFFICIAL_ACTIONS
        )
        return UnofficialActionPlan(
            actions=actions,
            direct_write_enabled=direct_write_enabled,
            interaction_strategy="comment_with_repost_checkbox",
            target_scope="current_dynamic",
            unofficial_type=unofficial_type.value,
            detected_required_actions=(
                requirements.required_actions if requirements is not None else ()
            ),
        )


class UnofficialWriteTransport(Protocol):
    async def perform(
        self,
        action: UnofficialAction,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> WriteOperationResult: ...


class GuardedUnofficialActionExecutor:
    """Call a future writer only after every safety gate has passed.

    The application currently constructs no instance with a live Bilibili
    transport and the global ``ManualGate`` is disabled.  If a transport later
    raises after sending a request, the outcome is marked ``unknown`` rather
    than retried, because the operation may already have taken effect.
    """

    def __init__(self, gate: ManualGate, transport: UnofficialWriteTransport):
        self.gate = gate
        self.transport = transport

    async def execute(
        self,
        ledger: ActionCheckpointLedger,
        action: UnofficialAction,
        *,
        target_url: str,
        payload: Mapping[str, object] | None = None,
        user_confirmed: bool = False,
    ) -> WriteOperationResult:
        action = _coerce_action(action)
        _validate_dynamic_target(target_url)
        self.gate.require_confirmation(action.value, user_confirmed=user_confirmed)
        ledger.start(action)
        try:
            result = await self.transport.perform(
                action,
                target_url=target_url,
                payload=payload or {},
            )
        except Exception as exc:  # noqa: BLE001 - a transport timeout is unknown
            result = WriteOperationResult(
                WriteOutcomeState.UNKNOWN,
                "WRITE_RESULT_UNKNOWN",
                f"写操作返回未知结果，必须人工检查后再决定是否继续（{type(exc).__name__}）",
            )
        ledger.record(action, result)
        return result


def _coerce_action(action: UnofficialAction | str) -> UnofficialAction:
    try:
        return action if isinstance(action, UnofficialAction) else UnofficialAction(action)
    except ValueError as exc:
        raise ValueError(f"UNKNOWN_UNOFFICIAL_ACTION:{action}") from exc


def _validate_dynamic_target(target_url: str) -> None:
    parsed = urlparse(target_url)
    path = parsed.path.rstrip("/")
    is_opus = parsed.hostname in {"www.bilibili.com", "bilibili.com"} and path.startswith("/opus/")
    is_dynamic = parsed.hostname == "t.bilibili.com" and path.count("/") == 1
    valid_id = path.rsplit("/", 1)[-1].isdigit()
    if parsed.scheme != "https" or not (is_opus or is_dynamic) or not valid_id:
        raise InvalidWriteTargetError("WRITE_TARGET_MUST_BE_BILIBILI_OPUS")
