import pytest

from backend.activity_engine.shared import ManualGate, WriteDisabledError
from backend.activity_engine.unofficial import (
    ActionCheckpointLedger,
    CheckpointBlockedError,
    CheckpointOrderError,
    GuardedUnofficialActionExecutor,
    InvalidWriteTargetError,
    UnofficialAction,
    WriteOperationResult,
    WriteOutcomeState,
)


class _Transport:
    def __init__(self, result: WriteOperationResult | None = None, error: Exception | None = None):
        self.result = result or WriteOperationResult(
            WriteOutcomeState.SUCCESS,
            "WRITE_OK",
            "ok",
        )
        self.error = error
        self.calls: list[tuple[UnofficialAction, str]] = []

    async def perform(self, action, *, target_url, payload):
        self.calls.append((action, target_url))
        if self.error is not None:
            raise self.error
        return self.result


def test_checkpoint_ledger_requires_order_and_confirms_idempotent_results():
    ledger = ActionCheckpointLedger()
    with pytest.raises(CheckpointOrderError, match="CHECKPOINT_ORDER_REQUIRED"):
        ledger.start(UnofficialAction.LIKE)

    ledger.start(UnofficialAction.COMMENT)
    ledger.record(
        UnofficialAction.COMMENT,
        WriteOperationResult(WriteOutcomeState.SUCCESS, "COMMENT_OK", "评论已确认"),
    )
    assert ledger.next_action is UnofficialAction.REPOST

    ledger.start(UnofficialAction.REPOST)
    ledger.record(
        UnofficialAction.REPOST,
        WriteOperationResult(WriteOutcomeState.ALREADY_DONE, "REPOST_EXISTS", "已转发"),
    )
    assert ledger.next_action is UnofficialAction.LIKE


def test_unknown_result_blocks_without_retry():
    ledger = ActionCheckpointLedger()
    ledger.start(UnofficialAction.COMMENT)
    ledger.record(
        UnofficialAction.COMMENT,
        WriteOperationResult(WriteOutcomeState.UNKNOWN, "WRITE_RESULT_UNKNOWN", "超时"),
    )

    assert ledger.status == "blocked_unknown"
    assert ledger.next_action is None
    with pytest.raises(CheckpointBlockedError, match="CHECKPOINT_BLOCKED:blocked_unknown"):
        ledger.start(UnofficialAction.COMMENT)
    assert ledger.to_payload()["unknownResultPolicy"] == "manual_review_no_retry"


@pytest.mark.asyncio
async def test_disabled_gate_never_calls_transport_or_changes_checkpoint():
    transport = _Transport()
    executor = GuardedUnofficialActionExecutor(ManualGate(False), transport)
    ledger = ActionCheckpointLedger()

    with pytest.raises(WriteDisabledError, match="DIRECT_WRITE_DISABLED:comment"):
        await executor.execute(
            ledger,
            UnofficialAction.COMMENT,
            target_url="https://www.bilibili.com/opus/1",
            user_confirmed=True,
        )

    assert transport.calls == []
    assert ledger.status == "ready"
    assert ledger.next_action is UnofficialAction.COMMENT


@pytest.mark.asyncio
async def test_transport_exception_is_unknown_and_stops_following_actions():
    transport = _Transport(error=TimeoutError("network timeout"))
    executor = GuardedUnofficialActionExecutor(ManualGate(True), transport)
    ledger = ActionCheckpointLedger()

    result = await executor.execute(
        ledger,
        UnofficialAction.COMMENT,
        target_url="https://www.bilibili.com/opus/1",
        user_confirmed=True,
    )

    assert result.state is WriteOutcomeState.UNKNOWN
    assert ledger.status == "blocked_unknown"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_confirmation_and_target_checks_happen_before_transport():
    transport = _Transport()
    executor = GuardedUnofficialActionExecutor(ManualGate(True), transport)
    ledger = ActionCheckpointLedger()

    with pytest.raises(WriteDisabledError, match="USER_CONFIRMATION_REQUIRED:comment"):
        await executor.execute(
            ledger,
            UnofficialAction.COMMENT,
            target_url="https://www.bilibili.com/opus/1",
            user_confirmed=False,
        )
    with pytest.raises(InvalidWriteTargetError):
        await executor.execute(
            ledger,
            UnofficialAction.COMMENT,
            target_url="https://example.com/opus/1",
            user_confirmed=True,
        )
    assert transport.calls == []
    assert ledger.status == "ready"
