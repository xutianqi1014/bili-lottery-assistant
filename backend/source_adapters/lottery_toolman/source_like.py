"""Source-article like checkpoint, validation, and legacy manual executor.

The confirmed-run automation service reuses the strict URL validator and
single-attempt checkpoint ledger.  ``GuardedSourceLikeExecutor`` remains for
the historical single-target controlled test and is not an application route.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse

from backend.activity_engine.shared.manual_gate import ManualGate


class SourceLikeCheckpointState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


class SourceLikeOutcomeState(StrEnum):
    SUCCESS = "success"
    ALREADY_DONE = "already_done"
    UNKNOWN = "unknown"
    FAILED = "failed"


class SourceLikeCheckpointError(RuntimeError):
    """Base class for an invalid or unsafe source-like transition."""


class SourceLikeCheckpointOrderError(SourceLikeCheckpointError):
    """Raised when the source-like checkpoint is not in the expected state."""


class SourceLikeCheckpointBlockedError(SourceLikeCheckpointError):
    """Raised after an unknown or failed result requires human review."""


class InvalidSourceLikeTargetError(SourceLikeCheckpointError):
    """Raised when a writer receives a URL outside the article allowlist."""


@dataclass(frozen=True, slots=True)
class SourceLikeWriteResult:
    state: SourceLikeOutcomeState
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceLikeCheckpoint:
    state: SourceLikeCheckpointState = SourceLikeCheckpointState.PENDING
    attempts: int = 0
    result_code: str = "SOURCE_LIKE_CHECKPOINT_PENDING"
    result_message: str = "等待来源专栏点赞"


class SourceLikeCheckpointLedger:
    """One-step ledger that never retries an uncertain source like."""

    def __init__(self) -> None:
        self._checkpoint = SourceLikeCheckpoint()

    @property
    def checkpoint(self) -> SourceLikeCheckpoint:
        return self._checkpoint

    @property
    def status(self) -> str:
        return {
            SourceLikeCheckpointState.PENDING: "ready",
            SourceLikeCheckpointState.IN_PROGRESS: "in_progress",
            SourceLikeCheckpointState.CONFIRMED: "completed",
            SourceLikeCheckpointState.UNKNOWN: "blocked_unknown",
            SourceLikeCheckpointState.FAILED: "blocked_failed",
        }[self._checkpoint.state]

    def start(self) -> SourceLikeCheckpoint:
        if self._checkpoint.state is not SourceLikeCheckpointState.PENDING:
            raise SourceLikeCheckpointOrderError(
                f"SOURCE_LIKE_CHECKPOINT_NOT_PENDING:{self._checkpoint.state.value}"
            )
        self._checkpoint = replace(
            self._checkpoint,
            state=SourceLikeCheckpointState.IN_PROGRESS,
            result_code="SOURCE_LIKE_CHECKPOINT_IN_PROGRESS",
            result_message="来源专栏点赞已获准，等待写适配器返回确定结果",
        )
        return self._checkpoint

    def record(self, result: SourceLikeWriteResult) -> SourceLikeCheckpoint:
        if self._checkpoint.state is not SourceLikeCheckpointState.IN_PROGRESS:
            raise SourceLikeCheckpointOrderError(
                f"SOURCE_LIKE_CHECKPOINT_NOT_IN_PROGRESS:{self._checkpoint.state.value}"
            )
        if result.state in {
            SourceLikeOutcomeState.SUCCESS,
            SourceLikeOutcomeState.ALREADY_DONE,
        }:
            next_state = SourceLikeCheckpointState.CONFIRMED
        elif result.state is SourceLikeOutcomeState.UNKNOWN:
            next_state = SourceLikeCheckpointState.UNKNOWN
        else:
            next_state = SourceLikeCheckpointState.FAILED
        self._checkpoint = replace(
            self._checkpoint,
            state=next_state,
            attempts=self._checkpoint.attempts + 1,
            result_code=result.code,
            result_message=result.message,
        )
        return self._checkpoint

    def to_payload(self) -> dict[str, object]:
        checkpoint = self._checkpoint
        return {
            "status": self.status,
            "unknownResultPolicy": "manual_review_no_retry",
            "checkpoint": {
                "state": checkpoint.state.value,
                "attempts": checkpoint.attempts,
                "resultCode": checkpoint.result_code,
                "resultMessage": checkpoint.result_message,
            },
        }


class SourceLikeWriteTransport(Protocol):
    async def perform(
        self,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> SourceLikeWriteResult: ...


class GuardedSourceLikeExecutor:
    """Call the legacy controlled writer after its manual gates pass."""

    def __init__(self, gate: ManualGate, transport: SourceLikeWriteTransport):
        self.gate = gate
        self.transport = transport

    async def execute(
        self,
        ledger: SourceLikeCheckpointLedger,
        *,
        target_url: str,
        payload: Mapping[str, object] | None = None,
        user_confirmed: bool = False,
    ) -> SourceLikeWriteResult:
        validate_source_like_target(target_url)
        self.gate.require_confirmation("source_like", user_confirmed=user_confirmed)
        ledger.start()
        try:
            result = await self.transport.perform(
                target_url=target_url,
                payload=payload or {},
            )
        except Exception as exc:  # noqa: BLE001 - transport outcome is unknown
            result = SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_WRITE_RESULT_UNKNOWN",
                f"来源点赞返回未知结果，必须人工检查后决定是否继续（{type(exc).__name__}）",
            )
        ledger.record(result)
        return result


def validate_source_like_target(target_url: str) -> None:
    parsed = urlparse(target_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.bilibili.com", "bilibili.com"}
        or not parsed.path.startswith("/read/cv")
        or not parsed.path.removeprefix("/read/cv").isdigit()
    ):
        raise InvalidSourceLikeTargetError("SOURCE_LIKE_TARGET_MUST_BE_BILIBILI_ARTICLE")
