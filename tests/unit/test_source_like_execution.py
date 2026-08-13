import json

import pytest
from sqlmodel import Session, create_engine

from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle, SourceProfile
from backend.source_adapters.lottery_toolman.source_like import (
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.use_cases.source_like_execution import SourceLikeExecutionService
from backend.use_cases.source_like_plan import SourceLikePlanService
from backend.use_cases.source_like_write_test import LIVE_WRITE_CONFIRMATION


class _Transport:
    def __init__(self, result: SourceLikeWriteResult) -> None:
        self.result = result
        self.calls = 0

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del target_url, payload
        self.calls += 1
        return self.result


class _Browser:
    async def open(self, url: str):
        raise AssertionError(f"DOM browser must not be used by the fake transport: {url}")


def _seed_single_target(engine) -> tuple[int, int]:
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="source-like-execution-test",
            mid="200",
            upload_url="https://space.bilibili.com/200/upload/opus",
            adapter_key="test",
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id or 0, state="preview_ready")
        article = SourceArticle(
            article_id="123",
            canonical_url="https://www.bilibili.com/read/cv123",
            title="受控来源",
            like_state="unliked",
        )
        activity = Activity(
            dynamic_id="execution-dynamic",
            canonical_url="https://www.bilibili.com/opus/7001",
            title="已完成动态",
        )
        session.add_all([discovery, article, activity])
        session.flush()
        assert discovery.id is not None and article.id is not None and activity.id is not None
        run = Run(
            discovery_run_id=discovery.id,
            source_article_ids_json=json.dumps([article.id]),
        )
        session.add(run)
        session.flush()
        assert run.id is not None
        session.add(
            RunItem(
                run_id=run.id,
                activity_id=activity.id,
                sequence=1,
                dynamic_id=activity.dynamic_id,
                canonical_url=activity.canonical_url,
                title=activity.title,
                family="official",
                mode="official",
                unofficial_type="unknown",
                platform_status="already_participated",
                source_article_ids_json=json.dumps([article.id]),
                state="completed",
            )
        )
        session.commit()
        return run.id, article.id


def _settings(tmp_path, *, enabled: bool) -> Settings:
    allowlist = tmp_path / "write_allowlist.yaml"
    allowlist.write_text("enabled: true\narticle_ids: [123]\n", encoding="utf-8")
    return Settings(
        enable_direct_write_api=enabled,
        source_like_write_allowlist_path=allowlist,
    )


@pytest.mark.asyncio
async def test_single_target_execution_persists_success_and_is_idempotent(tmp_path):
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, source_article_id = _seed_single_target(engine)
    plan_service = SourceLikePlanService(engine)
    plan_service.confirm(run_id)
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.SUCCESS,
            "SOURCE_LIKE_CONFIRMED",
            "confirmed",
        )
    )
    service = SourceLikeExecutionService(
        _settings(tmp_path, enabled=True),
        engine,
        _Browser(),
        plan_service,
        transport_factory=lambda: transport,
        environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"},
    )

    result = await service.execute(
        run_id,
        source_article_id=source_article_id,
        user_confirmed=True,
        confirmation_text=LIVE_WRITE_CONFIRMATION,
    )
    assert result["state"] == "completed"
    assert result["resultCode"] == "SOURCE_LIKE_CONFIRMED"
    assert transport.calls == 1
    assert plan_service.get(run_id).write_state == "completed"
    with Session(engine) as session:
        article = session.get(SourceArticle, source_article_id)
        run = session.get(Run, run_id)
        assert article is not None and article.like_state == "liked"
        assert run is not None
        record = json.loads(run.stats_json)["sourceLikeWrite"]
        assert record["state"] == "completed"
        assert record["checkpoint"]["checkpoint"]["state"] == "confirmed"

    repeated = await service.execute(
        run_id,
        source_article_id=source_article_id,
        user_confirmed=True,
        confirmation_text=LIVE_WRITE_CONFIRMATION,
    )
    assert repeated["state"] == "completed"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_disabled_application_gate_never_calls_transport(tmp_path):
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, source_article_id = _seed_single_target(engine)
    plan_service = SourceLikePlanService(engine)
    plan_service.confirm(run_id)
    transport = _Transport(
        SourceLikeWriteResult(SourceLikeOutcomeState.SUCCESS, "OK", "should not run")
    )
    service = SourceLikeExecutionService(
        _settings(tmp_path, enabled=False),
        engine,
        _Browser(),
        plan_service,
        transport_factory=lambda: transport,
        environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"},
    )

    with pytest.raises(ValueError, match="SOURCE_LIKE_WRITE_DISABLED"):
        await service.execute(
            run_id,
            source_article_id=source_article_id,
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_unknown_result_is_persisted_and_cannot_retry(tmp_path):
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, source_article_id = _seed_single_target(engine)
    plan_service = SourceLikePlanService(engine)
    plan_service.confirm(run_id)
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.UNKNOWN,
            "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN",
            "unknown",
        )
    )
    service = SourceLikeExecutionService(
        _settings(tmp_path, enabled=True),
        engine,
        _Browser(),
        plan_service,
        transport_factory=lambda: transport,
        environment={"BILI_LIVE_WRITE_TEST": "I_UNDERSTAND"},
    )

    result = await service.execute(
        run_id,
        source_article_id=source_article_id,
        user_confirmed=True,
        confirmation_text=LIVE_WRITE_CONFIRMATION,
    )
    assert result["state"] == "blocked_unknown"
    assert plan_service.get(run_id).write_state == "blocked_unknown"
    with pytest.raises(ValueError, match="SOURCE_LIKE_WRITE_TERMINAL_NO_RETRY"):
        await service.execute(
            run_id,
            source_article_id=source_article_id,
            user_confirmed=True,
            confirmation_text=LIVE_WRITE_CONFIRMATION,
        )
    assert transport.calls == 1
