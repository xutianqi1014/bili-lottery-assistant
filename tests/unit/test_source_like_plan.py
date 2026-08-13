import json

import pytest
from sqlmodel import Session, create_engine, select

from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle, SourceProfile
from backend.use_cases.source_like_plan import SourceLikePlanService


def _seed_plan(engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="source-like-test",
            mid="200",
            upload_url="https://space.bilibili.com/200/upload/opus",
            adapter_key="test",
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id or 0, state="preview_ready")
        ready = SourceArticle(
            article_id="cv-plan-ready",
            canonical_url="https://www.bilibili.com/read/cv-plan-ready",
            title="可收尾来源",
            like_state="unliked",
        )
        blocked = SourceArticle(
            article_id="cv-plan-blocked",
            canonical_url="https://www.bilibili.com/read/cv-plan-blocked",
            title="阻塞来源",
            like_state="unliked",
        )
        session.add_all([discovery, ready, blocked])
        session.flush()
        activity_ready = Activity(
            dynamic_id="plan-ready-dynamic",
            canonical_url="https://www.bilibili.com/opus/7001",
            title="可收尾动态",
        )
        activity_blocked = Activity(
            dynamic_id="plan-blocked-dynamic",
            canonical_url="https://www.bilibili.com/opus/7002",
            title="阻塞动态",
        )
        session.add_all([activity_ready, activity_blocked])
        session.flush()
        assert discovery.id is not None
        assert ready.id is not None and blocked.id is not None
        assert activity_ready.id is not None and activity_blocked.id is not None
        run = Run(
            discovery_run_id=discovery.id,
            source_article_ids_json=json.dumps([ready.id, blocked.id]),
        )
        session.add(run)
        session.flush()
        assert run.id is not None
        session.add_all(
            [
                RunItem(
                    run_id=run.id,
                    activity_id=activity_ready.id,
                    sequence=1,
                    dynamic_id=activity_ready.dynamic_id,
                    canonical_url=activity_ready.canonical_url,
                    title=activity_ready.title,
                    family="official",
                    mode="official",
                    unofficial_type="unknown",
                    platform_status="already_participated",
                    source_article_ids_json=json.dumps([ready.id]),
                    state="completed",
                ),
                RunItem(
                    run_id=run.id,
                    activity_id=activity_blocked.id,
                    sequence=2,
                    dynamic_id=activity_blocked.dynamic_id,
                    canonical_url=activity_blocked.canonical_url,
                    title=activity_blocked.title,
                    family="official",
                    mode="official",
                    unofficial_type="unknown",
                    platform_status="eligible_waiting_user",
                    source_article_ids_json=json.dumps([blocked.id]),
                    state="waiting_user",
                ),
            ]
        )
        session.commit()
        return run.id, ready.id, blocked.id


def test_source_like_plan_only_targets_ready_sources():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, ready_id, blocked_id = _seed_plan(engine)

    plan = SourceLikePlanService(engine).get(run_id)

    assert plan.state == "awaiting_confirmation"
    assert plan.direct_write_enabled is False
    assert [target.source_article_id for target in plan.targets] == [ready_id]
    assert plan.blocked_count == 1
    assert blocked_id not in {target.source_article_id for target in plan.targets}


def test_confirm_source_like_plan_reconciles_successful_source_like():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, ready_id, _blocked_id = _seed_plan(engine)
    service = SourceLikePlanService(engine)

    confirmed = service.confirm(run_id, "人工确认来源收尾")
    assert confirmed.state == "confirmed_waiting_write"
    assert confirmed.confirmation_note == "人工确认来源收尾"
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        stats = json.loads(run.stats_json)
        assert stats["sourceLikePlan"]["targetSourceArticleIds"] == [ready_id]
        article = session.get(SourceArticle, ready_id)
        assert article is not None
        article.like_state = "liked"
        session.add(article)
        session.commit()

    completed = service.get(run_id)
    assert completed.state == "completed"
    assert completed.reason == "SOURCE_LIKE_CONFIRMED"


def test_confirm_requires_at_least_one_ready_source():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, _ready_id, _blocked_id = _seed_plan(engine)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        articles = session.exec(select(SourceArticle)).all()
        for article in articles:
            article.like_state = "liked"
            session.add(article)
        session.commit()

    with pytest.raises(ValueError, match="NO_SOURCE_LIKE_TARGETS"):
        SourceLikePlanService(engine).confirm(run_id)
