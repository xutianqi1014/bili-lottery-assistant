import pytest

from backend.activity_engine.shared import ManualGate, WriteDisabledError
from backend.source_adapters.lottery_toolman.source_like import (
    GuardedSourceLikeExecutor,
    InvalidSourceLikeTargetError,
    SourceLikeCheckpointLedger,
    SourceLikeCheckpointOrderError,
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
    validate_source_like_target,
)


class _Transport:
    def __init__(self, result: SourceLikeWriteResult | None = None) -> None:
        self.result = result or SourceLikeWriteResult(
            SourceLikeOutcomeState.SUCCESS,
            "SOURCE_LIKE_CONFIRMED",
            "confirmed",
        )
        self.calls = 0

    async def perform(
        self, *, target_url: str, payload: dict[str, object]
    ) -> SourceLikeWriteResult:
        self.calls += 1
        return self.result


def test_source_like_target_allowlist_is_strict():
    validate_source_like_target("https://www.bilibili.com/read/cv123")
    validate_source_like_target("https://bilibili.com/read/cv987?from=assistant")
    with pytest.raises(InvalidSourceLikeTargetError):
        validate_source_like_target("https://www.bilibili.com/opus/123")
    with pytest.raises(InvalidSourceLikeTargetError):
        validate_source_like_target("http://www.bilibili.com/read/cv123")
    with pytest.raises(InvalidSourceLikeTargetError):
        validate_source_like_target("https://evil.example/read/cv123")


@pytest.mark.asyncio
async def test_disabled_gate_never_calls_source_like_transport():
    transport = _Transport()
    executor = GuardedSourceLikeExecutor(ManualGate(False), transport)
    with pytest.raises(WriteDisabledError, match="DIRECT_WRITE_DISABLED:source_like"):
        await executor.execute(
            SourceLikeCheckpointLedger(),
            target_url="https://www.bilibili.com/read/cv123",
            user_confirmed=True,
        )
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_source_like_unknown_result_blocks_without_retry():
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.UNKNOWN,
            "SOURCE_LIKE_WRITE_RESULT_UNKNOWN",
            "unknown",
        )
    )
    executor = GuardedSourceLikeExecutor(ManualGate(True), transport)
    ledger = SourceLikeCheckpointLedger()
    result = await executor.execute(
        ledger,
        target_url="https://www.bilibili.com/read/cv123",
        user_confirmed=True,
    )
    assert result.state is SourceLikeOutcomeState.UNKNOWN
    assert ledger.status == "blocked_unknown"
    assert ledger.checkpoint.attempts == 1
    with pytest.raises(SourceLikeCheckpointOrderError):
        await executor.execute(
            ledger,
            target_url="https://www.bilibili.com/read/cv123",
            user_confirmed=True,
        )
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_source_like_success_is_confirmed_and_idempotent():
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.ALREADY_DONE,
            "SOURCE_ALREADY_LIKED",
            "already liked",
        )
    )
    executor = GuardedSourceLikeExecutor(ManualGate(True), transport)
    ledger = SourceLikeCheckpointLedger()
    result = await executor.execute(
        ledger,
        target_url="https://www.bilibili.com/read/cv123",
        user_confirmed=True,
    )
    assert result.state is SourceLikeOutcomeState.ALREADY_DONE
    assert ledger.status == "completed"
    assert ledger.to_payload()["checkpoint"]["state"] == "confirmed"
