import pytest

from backend.activity_engine.official.participation import (
    GuardedOfficialParticipationExecutor,
    InvalidOfficialParticipationTargetError,
    OfficialParticipationCheckpointLedger,
    OfficialParticipationOutcomeState,
    OfficialParticipationWriteResult,
    validate_official_participation_target,
)
from backend.activity_engine.shared import WriteDisabledError


class _Transport:
    def __init__(self, result: OfficialParticipationWriteResult) -> None:
        self.result = result
        self.calls = 0

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del target_url, payload
        self.calls += 1
        return self.result


def test_official_target_validator_accepts_only_opus_urls() -> None:
    assert validate_official_participation_target(
        "https://www.bilibili.com/opus/12345?from=console"
    ) == "12345"
    with pytest.raises(InvalidOfficialParticipationTargetError):
        validate_official_participation_target("https://www.bilibili.com/read/cv12345")
    with pytest.raises(InvalidOfficialParticipationTargetError):
        validate_official_participation_target("http://www.bilibili.com/opus/12345")


@pytest.mark.asyncio
async def test_disabled_gate_does_not_call_official_transport() -> None:
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.SUCCESS, "OK", "should not run"
        )
    )
    with pytest.raises(WriteDisabledError):
        await GuardedOfficialParticipationExecutor(
            False, transport
        ).execute(
            OfficialParticipationCheckpointLedger(),
            target_url="https://www.bilibili.com/opus/12345",
        )
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_unknown_official_result_is_terminal_and_never_retried() -> None:
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_PARTICIPATION_TERMINAL_STATE_UNKNOWN",
            "unknown",
        )
    )
    ledger = OfficialParticipationCheckpointLedger()
    executor = GuardedOfficialParticipationExecutor(True, transport)
    result = await executor.execute(
        ledger,
        target_url="https://www.bilibili.com/opus/12345",
    )
    assert result.state is OfficialParticipationOutcomeState.UNKNOWN
    assert ledger.status == "blocked_unknown"
    with pytest.raises(Exception):
        await executor.execute(
            ledger,
            target_url="https://www.bilibili.com/opus/12345",
        )
    assert transport.calls == 1
