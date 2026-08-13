"""Safety-gated primitives for one official lottery participation.

The application keeps this writer behind several independent gates.  The
ledger is deliberately one-shot: once a browser click has been attempted, an
unknown terminal state is persisted and the same target cannot be retried by
the service automatically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from backend.activity_engine.shared.manual_gate import WriteDisabledError


class OfficialParticipationCheckpointState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


class OfficialParticipationOutcomeState(StrEnum):
    SUCCESS = "success"
    ALREADY_PARTICIPATED = "already_participated"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    FAILED = "failed"


class OfficialParticipationCheckpointError(RuntimeError):
    """Base class for an invalid or unsafe official transition."""


class OfficialParticipationCheckpointOrderError(OfficialParticipationCheckpointError):
    """Raised when a one-shot official checkpoint is used out of order."""


class InvalidOfficialParticipationTargetError(OfficialParticipationCheckpointError):
    """Raised when a writer receives a URL outside the official opus scope."""


@dataclass(frozen=True, slots=True)
class OfficialParticipationWriteResult:
    state: OfficialParticipationOutcomeState
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OfficialParticipationCheckpoint:
    state: OfficialParticipationCheckpointState = OfficialParticipationCheckpointState.PENDING
    attempts: int = 0
    result_code: str = "OFFICIAL_PARTICIPATION_CHECKPOINT_PENDING"
    result_message: str = "waiting for official lottery participation"


class OfficialParticipationCheckpointLedger:
    """One-step ledger that never retries an uncertain official click."""

    def __init__(self) -> None:
        self._checkpoint = OfficialParticipationCheckpoint()

    @property
    def checkpoint(self) -> OfficialParticipationCheckpoint:
        return self._checkpoint

    @property
    def status(self) -> str:
        return {
            OfficialParticipationCheckpointState.PENDING: "ready",
            OfficialParticipationCheckpointState.IN_PROGRESS: "in_progress",
            OfficialParticipationCheckpointState.CONFIRMED: "completed",
            OfficialParticipationCheckpointState.UNKNOWN: "blocked_unknown",
            OfficialParticipationCheckpointState.FAILED: "blocked_failed",
        }[self._checkpoint.state]

    def start(self) -> OfficialParticipationCheckpoint:
        if self._checkpoint.state is not OfficialParticipationCheckpointState.PENDING:
            raise OfficialParticipationCheckpointOrderError(
                "OFFICIAL_PARTICIPATION_CHECKPOINT_NOT_PENDING"
            )
        self._checkpoint = replace(
            self._checkpoint,
            state=OfficialParticipationCheckpointState.IN_PROGRESS,
            result_code="OFFICIAL_PARTICIPATION_CHECKPOINT_IN_PROGRESS",
            result_message="official participation click is in progress",
        )
        return self._checkpoint

    def record(
        self, result: OfficialParticipationWriteResult
    ) -> OfficialParticipationCheckpoint:
        if self._checkpoint.state is not OfficialParticipationCheckpointState.IN_PROGRESS:
            raise OfficialParticipationCheckpointOrderError(
                "OFFICIAL_PARTICIPATION_CHECKPOINT_NOT_IN_PROGRESS"
            )
        if result.state in {
            OfficialParticipationOutcomeState.SUCCESS,
            OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
            OfficialParticipationOutcomeState.EXPIRED,
        }:
            next_state = OfficialParticipationCheckpointState.CONFIRMED
        elif result.state is OfficialParticipationOutcomeState.UNKNOWN:
            next_state = OfficialParticipationCheckpointState.UNKNOWN
        else:
            next_state = OfficialParticipationCheckpointState.FAILED
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


class OfficialParticipationWriteTransport(Protocol):
    async def perform(
        self,
        *,
        target_url: str,
        payload: Mapping[str, object],
    ) -> OfficialParticipationWriteResult: ...


class GuardedOfficialParticipationExecutor:
    """Call the DOM writer only when run-scoped automation is enabled."""

    def __init__(
        self,
        write_enabled: bool,
        transport: OfficialParticipationWriteTransport,
    ) -> None:
        self.write_enabled = write_enabled
        self.transport = transport

    async def execute(
        self,
        ledger: OfficialParticipationCheckpointLedger,
        *,
        target_url: str,
        payload: Mapping[str, object] | None = None,
    ) -> OfficialParticipationWriteResult:
        validate_official_participation_target(target_url)
        if not self.write_enabled:
            raise WriteDisabledError("DIRECT_WRITE_DISABLED:official_participation")
        ledger.start()
        try:
            result = await self.transport.perform(
                target_url=target_url,
                payload=payload or {},
            )
        except Exception as exc:  # noqa: BLE001 - click outcome is uncertain
            result = OfficialParticipationWriteResult(
                OfficialParticipationOutcomeState.UNKNOWN,
                "OFFICIAL_PARTICIPATION_WRITE_RESULT_UNKNOWN",
                f"official participation result is unknown: {type(exc).__name__}",
            )
        ledger.record(result)
        return result


def validate_official_participation_target(target_url: str) -> str:
    """Return the numeric opus id or reject a non-official target URL."""

    parsed = urlsplit(target_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.bilibili.com", "bilibili.com"}
        or not parsed.path.startswith("/opus/")
        or not parsed.path.removeprefix("/opus/").isdigit()
        or not parsed.path.removeprefix("/opus/")
    ):
        raise InvalidOfficialParticipationTargetError(
            "OFFICIAL_PARTICIPATION_TARGET_MUST_BE_BILIBILI_OPUS"
        )
    return parsed.path.removeprefix("/opus/")
