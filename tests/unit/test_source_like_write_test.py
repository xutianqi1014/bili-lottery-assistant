import pytest

from backend.activity_engine.shared import ManualGate, WriteDisabledError
from backend.source_adapters.lottery_toolman.source_like import (
    GuardedSourceLikeExecutor,
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.use_cases.source_like_write_test import (
    LIVE_WRITE_CONFIRMATION,
    ControlledSourceLikeWriteTest,
    SourceLikeWriteAllowlist,
    SourceLikeWriteTestAllowlistError,
    SourceLikeWriteTestAuthorizationError,
)


def _allowlist(*, enabled: bool = True, article_ids: tuple[str, ...] = ("123",)):
    return SourceLikeWriteAllowlist(enabled=enabled, article_ids=article_ids)


class _Transport:
    def __init__(self) -> None:
        self.calls = 0

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del target_url, payload
        self.calls += 1
        return SourceLikeWriteResult(
            SourceLikeOutcomeState.ALREADY_DONE,
            "SOURCE_ALREADY_LIKED",
            "already liked",
        )


def test_allowlist_loader_rejects_non_boolean_enabled(tmp_path):
    path = tmp_path / "write_allowlist.yaml"
    path.write_text("enabled: enabled\narticle_ids: [123]\n", encoding="utf-8")
    with pytest.raises(
        SourceLikeWriteTestAllowlistError,
        match="SOURCE_LIKE_WRITE_TEST_ALLOWLIST_ENABLED_INVALID",
    ):
        SourceLikeWriteAllowlist.from_path(path)


def test_authorization_requires_environment_ack_and_second_confirmation():
    session = ControlledSourceLikeWriteTest(_allowlist(), environment={})
    with pytest.raises(
        SourceLikeWriteTestAuthorizationError,
        match="SOURCE_LIKE_WRITE_TEST_ENV_REQUIRED",
    ):
        session.authorize(
            "https://www.bilibili.com/read/cv123",
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )

    session = ControlledSourceLikeWriteTest(
        _allowlist(), environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"}
    )
    with pytest.raises(
        SourceLikeWriteTestAuthorizationError,
        match="SOURCE_LIKE_WRITE_TEST_USER_CONFIRMATION_REQUIRED",
    ):
        session.authorize(
            "https://www.bilibili.com/read/cv123",
            user_confirmed=False,
            confirmation_text="",
        )


def test_authorization_requires_exactly_one_allowlisted_article():
    session = ControlledSourceLikeWriteTest(
        _allowlist(article_ids=("123", "456")),
        environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"},
    )
    with pytest.raises(
        SourceLikeWriteTestAuthorizationError,
        match="SOURCE_LIKE_WRITE_TEST_MUST_HAVE_ONE_ARTICLE",
    ):
        session.authorize(
            "https://www.bilibili.com/read/cv123",
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )

    session = ControlledSourceLikeWriteTest(
        _allowlist(), environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"}
    )
    with pytest.raises(
        SourceLikeWriteTestAuthorizationError,
        match="SOURCE_LIKE_WRITE_TEST_TARGET_NOT_ALLOWLISTED",
    ):
        session.authorize(
            "https://www.bilibili.com/read/cv456",
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )


@pytest.mark.asyncio
async def test_controlled_session_is_one_shot_and_unknown_gate_stays_closed():
    transport = _Transport()
    executor = GuardedSourceLikeExecutor(ManualGate(True), transport)
    session = ControlledSourceLikeWriteTest(
        _allowlist(), environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"}
    )
    result = await session.execute(
        executor,
        target_url="https://www.bilibili.com/read/cv123",
        user_confirmed=True,
        confirmation_text=LIVE_WRITE_CONFIRMATION,
    )
    assert result.state is SourceLikeOutcomeState.ALREADY_DONE
    assert session.consumed is True
    assert session.ledger.checkpoint.attempts == 1
    with pytest.raises(
        SourceLikeWriteTestAuthorizationError,
        match="SOURCE_LIKE_WRITE_TEST_ALREADY_CONSUMED",
    ):
        await session.execute(
            executor,
            target_url="https://www.bilibili.com/read/cv123",
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_controlled_session_cannot_override_disabled_executor_gate():
    transport = _Transport()
    executor = GuardedSourceLikeExecutor(ManualGate(False), transport)
    session = ControlledSourceLikeWriteTest(
        _allowlist(), environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"}
    )
    with pytest.raises(WriteDisabledError, match="DIRECT_WRITE_DISABLED:source_like"):
        await session.execute(
            executor,
            target_url="https://www.bilibili.com/read/cv123",
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )
    assert session.consumed is True
    assert transport.calls == 0
