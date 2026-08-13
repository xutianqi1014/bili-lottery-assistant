import json

import pytest
from sqlmodel import Session, create_engine, select

from backend.api.app import create_app
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle
from backend.source_adapters.lottery_toolman.source_like import (
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.use_cases.source_like_automation import SourceLikeAutomationService


class _Transport:
    def __init__(self, result: SourceLikeWriteResult) -> None:
        self.result = result
        self.calls: list[str] = []

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        assert payload["authorizationMode"] == "confirmed_run_source_closure"
        self.calls.append(target_url)
        return self.result


class _Browser:
    async def open(self, url: str):
        raise AssertionError(f"fake transport should own the operation: {url}")


def _seed_ready_run(engine, *, with_problem: bool = False) -> tuple[int, int, str]:
    with Session(engine) as session:
        discovery = DiscoveryRun(source_profile_id=1, state="preview_ready")
        article = SourceArticle(
            article_id="52199999",
            canonical_url="https://www.bilibili.com/read/cv52199999",
            title="自动收尾来源",
            like_state="unliked",
        )
        activity = Activity(
            dynamic_id="990000001",
            canonical_url="https://www.bilibili.com/opus/990000001",
            title="已完成官方动态",
        )
        session.add_all([discovery, article, activity])
        session.flush()
        assert discovery.id is not None and article.id is not None and activity.id is not None
        run = Run(
            discovery_run_id=discovery.id,
            state="running",
            source_article_ids_json=json.dumps([article.id]),
            stats_json=json.dumps({"requiresManualReview": False}),
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
                platform_status="participated",
                source_article_ids_json=json.dumps([article.id]),
                state="completed",
            )
        )
        if with_problem:
            session.add(
                ProblemRecord(
                    discovery_run_id=discovery.id,
                    source_article_id=article.id,
                    problem_url=activity.canonical_url,
                    page_type="activity",
                    stage="official_participation",
                    problem_code="TEST_OPEN_PROBLEM",
                    safe_detail="do not close source",
                )
            )
        session.commit()
        return run.id, article.id, article.canonical_url


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        source_like_automation_enabled=enabled,
        source_like_automation_delay_min_sec=0,
        source_like_automation_delay_max_sec=0,
    )


def test_legacy_source_like_manual_routes_are_not_exposed():
    paths = set(create_app().openapi()["paths"])

    assert "/api/runs/{run_id}/source-like-plan" not in paths
    assert "/api/runs/{run_id}/source-like-plan/confirm" not in paths
    assert "/api/runs/{run_id}/source-like-plan/execute" not in paths
    assert "/api/runs/{run_id}/start" in paths


@pytest.mark.asyncio
async def test_ready_source_is_liked_once_and_persisted_idempotently():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, article_id, target_url = _seed_ready_run(engine)
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.SUCCESS,
            "SOURCE_LIKE_CONFIRMED",
            "confirmed",
        )
    )
    service = SourceLikeAutomationService(
        _settings(),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute_ready(run_id)

    assert result.state == "completed"
    assert result.result_code == "SOURCE_LIKE_AUTOMATION_CONFIRMED"
    assert result.completed_count == 1
    assert transport.calls == [target_url]
    with Session(engine) as session:
        article = session.get(SourceArticle, article_id)
        run = session.get(Run, run_id)
        assert article is not None and article.like_state == "liked"
        assert run is not None
        stats = json.loads(run.stats_json)
        assert stats["sourceLikeAutomation"]["writes"][str(article_id)]["state"] == "completed"
        assert stats["sourceClosure"]["alreadyLikedCount"] == 1

    repeated = await service.execute_ready(run_id)
    assert repeated.state == "completed"
    assert transport.calls == [target_url]


@pytest.mark.asyncio
async def test_unknown_source_like_records_url_and_never_retries():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, article_id, target_url = _seed_ready_run(engine)
    transport = _Transport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.UNKNOWN,
            "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN",
            "terminal marker unknown",
        )
    )
    service = SourceLikeAutomationService(
        _settings(),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute_ready(run_id)

    assert result.state == "blocked_unknown"
    assert result.blocks_run is True
    assert transport.calls == [target_url]
    with Session(engine) as session:
        article = session.get(SourceArticle, article_id)
        problem = session.exec(select(ProblemRecord)).one()
        run = session.get(Run, run_id)
        assert article is not None and article.like_state == "unliked"
        assert problem.problem_url == target_url
        assert problem.stage == "source_like_automation"
        assert problem.problem_code == "SOURCE_LIKE_TERMINAL_STATE_UNKNOWN"
        assert run is not None and json.loads(run.stats_json)["requiresManualReview"] is True

    repeated = await service.execute_ready(run_id)
    assert repeated.state == "blocked_unknown"
    assert transport.calls == [target_url]


@pytest.mark.asyncio
async def test_interrupted_running_record_is_blocked_without_transport_retry():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, article_id, target_url = _seed_ready_run(engine)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        stats = json.loads(run.stats_json)
        stats["sourceLikeAutomation"] = {
            "state": "running",
            "targetSourceArticleIds": [article_id],
            "targetCount": 1,
            "completedCount": 0,
            "resultCode": "SOURCE_LIKE_AUTOMATION_RUNNING",
            "resultMessage": "interrupted before a terminal record",
        }
        run.stats_json = json.dumps(stats)
        session.add(run)
        session.commit()
    transport = _Transport(
        SourceLikeWriteResult(SourceLikeOutcomeState.SUCCESS, "SHOULD_NOT_RUN", "bad")
    )
    service = SourceLikeAutomationService(
        _settings(),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute_ready(run_id)

    assert result.state == "blocked_unknown"
    assert result.result_code == "SOURCE_LIKE_AUTOMATION_INTERRUPTED_UNKNOWN"
    assert transport.calls == []
    with Session(engine) as session:
        article = session.get(SourceArticle, article_id)
        problem = session.exec(select(ProblemRecord)).one()
        assert article is not None and article.like_state == "unliked"
        assert problem.problem_url == target_url
        assert problem.problem_code == "SOURCE_LIKE_AUTOMATION_INTERRUPTED_UNKNOWN"


@pytest.mark.asyncio
async def test_open_problem_skips_source_without_calling_transport():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, article_id, _target_url = _seed_ready_run(engine, with_problem=True)
    transport = _Transport(
        SourceLikeWriteResult(SourceLikeOutcomeState.SUCCESS, "SHOULD_NOT_RUN", "bad")
    )
    service = SourceLikeAutomationService(
        _settings(),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute_ready(run_id)

    assert result.state == "skipped"
    assert result.result_code == "SOURCE_CLOSURE_BLOCKED_NOT_LIKED"
    assert transport.calls == []
    with Session(engine) as session:
        article = session.get(SourceArticle, article_id)
        assert article is not None and article.like_state == "unliked"


@pytest.mark.asyncio
async def test_disabled_automation_keeps_ready_source_unliked():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, article_id, _target_url = _seed_ready_run(engine)
    transport = _Transport(
        SourceLikeWriteResult(SourceLikeOutcomeState.SUCCESS, "SHOULD_NOT_RUN", "bad")
    )
    service = SourceLikeAutomationService(
        _settings(enabled=False),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute_ready(run_id)

    assert result.state == "disabled"
    assert transport.calls == []
    with Session(engine) as session:
        article = session.get(SourceArticle, article_id)
        assert article is not None and article.like_state == "unliked"
