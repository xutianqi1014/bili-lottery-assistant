import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session, create_engine, select

from backend.api.routes.discoveries import _execute_discovery_and_plan
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity, ActivityOrigin
from backend.db.models.discovery import DiscoveryRun, DiscoverySelection
from backend.db.models.run import Run
from backend.db.models.source import Readlist, SourceArticle
from backend.db.repositories.discoveries import create_discovery
from backend.db.repositories.profiles import seed_default_profile
from backend.jobs.events import EventHub
from backend.use_cases.automatic_execution_plan import AutomaticExecutionPlanService
from backend.use_cases.execution_plan import ExecutionPlanService


def _seed_preview(engine, *, with_candidate: bool) -> int:
    init_database(engine)
    with Session(engine) as session:
        profile = seed_default_profile(session)
        assert profile.id is not None
        discovery = create_discovery(session, profile.id, 5)
        discovery.state = "preview_ready"
        discovery.stats_json = json.dumps(
            {"activityRefsUnique": 1 if with_candidate else 0}
        )
        session.add(discovery)
        session.commit()
        session.refresh(discovery)
        assert discovery.id is not None
        if not with_candidate:
            return discovery.id

        readlist = Readlist(
            source_profile_id=profile.id,
            rl_id="rl-auto-plan",
            canonical_url="https://www.bilibili.com/read/readlist/rl-auto-plan",
            family="official",
            title="官方抽奖合集",
            normalized_title="官方抽奖合集",
            suffix_value=1,
        )
        article = SourceArticle(
            article_id="620000001",
            canonical_url="https://www.bilibili.com/read/cv620000001",
            title="自动计划来源专栏",
            like_state="unliked",
        )
        activity = Activity(
            dynamic_id="520000001",
            canonical_url="https://www.bilibili.com/opus/520000001",
            title="自动计划官方活动",
        )
        session.add_all([readlist, article, activity])
        session.flush()
        assert readlist.id is not None
        assert article.id is not None
        assert activity.id is not None
        session.add(
            DiscoverySelection(
                discovery_run_id=discovery.id,
                source_article_id=article.id,
                readlist_id=readlist.id,
                family="official",
                selected_rank=1,
                source_position=1,
                like_state_snapshot="unliked",
                decision="process",
                decision_reason="test",
            )
        )
        session.add(
            ActivityOrigin(
                source_article_id=article.id,
                activity_id=activity.id,
                source_position=1,
                discovered_in_run_id=discovery.id,
            )
        )
        session.commit()
        return discovery.id


@pytest.mark.asyncio
async def test_candidate_discovery_automatically_creates_one_reviewable_plan() -> None:
    engine = create_engine("sqlite://")
    discovery_id = _seed_preview(engine, with_candidate=True)
    events = EventHub()
    event_queue = events.subscribe()
    plan_service = ExecutionPlanService(Settings(), engine, events)
    service = AutomaticExecutionPlanService(engine, events, plan_service)

    created = await service.create_if_needed(discovery_id)
    reused = await service.create_if_needed(discovery_id)

    assert created.state == "created"
    assert created.candidate_count == 1
    assert created.run_id is not None
    assert reused.state == "reused"
    assert reused.run_id == created.run_id
    assert event_queue.get_nowait().name == "run.plan_created"
    with Session(engine) as session:
        plans = list(
            session.exec(select(Run).where(Run.discovery_run_id == discovery_id)).all()
        )
        discovery = session.get(DiscoveryRun, discovery_id)
        assert len(plans) == 1
        assert plans[0].state == "awaiting_confirmation"
        assert discovery is not None
        stats = json.loads(discovery.stats_json)
        assert stats["automaticPlanState"] == "created"
        assert stats["automaticPlanRunId"] == created.run_id
        assert stats["automaticPlanCandidateCount"] == 1


@pytest.mark.asyncio
async def test_discovery_without_candidates_does_not_create_plan() -> None:
    engine = create_engine("sqlite://")
    discovery_id = _seed_preview(engine, with_candidate=False)
    events = EventHub()
    event_queue = events.subscribe()
    service = AutomaticExecutionPlanService(
        engine,
        events,
        ExecutionPlanService(Settings(), engine, events),
    )

    result = await service.create_if_needed(discovery_id)

    assert result.state == "skipped_no_candidates"
    assert result.run_id is None
    assert event_queue.get_nowait().name == "discovery.plan_skipped"
    with Session(engine) as session:
        assert list(session.exec(select(Run)).all()) == []
        discovery = session.get(DiscoveryRun, discovery_id)
        assert discovery is not None
        stats = json.loads(discovery.stats_json)
        assert stats["automaticPlanState"] == "skipped_no_candidates"
        assert stats["automaticPlanCandidateCount"] == 0
        assert "automaticPlanRunId" not in stats


@pytest.mark.asyncio
async def test_automatic_plan_failure_is_visible_and_does_not_create_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite://")
    discovery_id = _seed_preview(engine, with_candidate=True)
    events = EventHub()
    event_queue = events.subscribe()
    plan_service = ExecutionPlanService(Settings(), engine, events)

    def _fail_create(_request: object) -> Run:
        raise RuntimeError("sensitive detail must not be persisted")

    monkeypatch.setattr(plan_service, "create", _fail_create)
    service = AutomaticExecutionPlanService(engine, events, plan_service)

    result = await service.create_if_needed(discovery_id)

    assert result.state == "failed"
    assert result.error_code == "AUTOMATIC_PLAN_CREATION_RUNTIMEERROR"
    event = event_queue.get_nowait()
    assert event.name == "discovery.plan_failed"
    assert event.data["errorCode"] == "AUTOMATIC_PLAN_CREATION_RUNTIMEERROR"
    with Session(engine) as session:
        assert list(session.exec(select(Run)).all()) == []
        discovery = session.get(DiscoveryRun, discovery_id)
        assert discovery is not None
        stats = json.loads(discovery.stats_json)
        assert stats["automaticPlanState"] == "failed"
        assert stats["automaticPlanErrorCode"] == (
            "AUTOMATIC_PLAN_CREATION_RUNTIMEERROR"
        )
        assert "sensitive detail" not in discovery.stats_json


@pytest.mark.asyncio
async def test_discovery_route_waits_for_discovery_before_plan_decision() -> None:
    calls: list[str] = []

    class _DiscoveryService:
        async def execute(self, discovery_id: int) -> None:
            calls.append(f"discovery:{discovery_id}")

    class _AutomaticPlanService:
        async def create_if_needed(self, discovery_id: int) -> None:
            calls.append(f"plan:{discovery_id}")

    state = SimpleNamespace(
        discovery_service=_DiscoveryService(),
        automatic_plan_service=_AutomaticPlanService(),
    )

    await _execute_discovery_and_plan(state, 77)

    assert calls == ["discovery:77", "plan:77"]
