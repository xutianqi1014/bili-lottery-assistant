import json

from sqlmodel import Session, create_engine

from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity, ActivityOrigin
from backend.db.models.discovery import DiscoverySelection
from backend.db.models.source import Readlist, SourceArticle
from backend.db.repositories.discoveries import create_discovery
from backend.db.repositories.profiles import seed_default_profile
from backend.jobs.events import EventHub
from backend.use_cases.execution_plan import ExecutionPlanService, PlanRequest


def test_execution_plan_is_immutable_until_explicit_confirmation():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        profile = seed_default_profile(session)
        assert profile.id is not None
        discovery = create_discovery(session, profile.id, 5)
        discovery.state = "preview_ready"
        discovery.stats_json = json.dumps({"activityRefsUnique": 1})
        readlist = Readlist(
            source_profile_id=profile.id,
            rl_id="rl-plan",
            canonical_url="https://www.bilibili.com/read/readlist/rl-plan",
            family="official",
            title="官方抽奖合集",
            normalized_title="官方抽奖合集",
            suffix_value=1,
        )
        article = SourceArticle(
            article_id="610000001",
            canonical_url="https://www.bilibili.com/read/cv610000001",
            title="来源专栏",
        )
        activity = Activity(
            dynamic_id="510000001",
            canonical_url="https://www.bilibili.com/opus/510000001",
            title="官方活动",
            mode_detected="official",
            platform_status="already_participated",
        )
        session.add_all([readlist, article, activity])
        session.flush()
        assert readlist.id is not None and article.id is not None and activity.id is not None
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
        session.add(discovery)
        session.commit()
        discovery_id = discovery.id

    service = ExecutionPlanService(Settings(), engine, EventHub())
    plan = service.create(PlanRequest(discovery_id=discovery_id))
    assert plan.id is not None
    assert plan.state == "awaiting_confirmation"
    _run, items = service.get(plan.id)
    assert len(items) == 1
    assert items[0].state == "planned"
    assert items[0].mode == "unknown"
    assert items[0].platform_status == "unchecked"
    assert json.loads(items[0].action_plan_json) == [
        "open_dynamic",
        "inspect_runtime_state",
        "execute_official_if_eligible",
    ]
    confirmed = service.confirm(plan.id)
    assert confirmed.state == "confirmed_waiting_user"


def test_execution_plan_keeps_interactive_source_section_as_provisional_mode():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        profile = seed_default_profile(session)
        assert profile.id is not None
        discovery = create_discovery(session, profile.id, 5)
        discovery.state = "preview_ready"
        readlist = Readlist(
            source_profile_id=profile.id,
            rl_id="rl-interactive-plan",
            canonical_url="https://www.bilibili.com/read/readlist/rl-interactive-plan",
            family="official",
            title="互动抽奖",
            normalized_title="互动抽奖",
            suffix_value=1,
        )
        article = SourceArticle(
            article_id="610000002",
            canonical_url="https://www.bilibili.com/read/cv610000002",
            title="互动来源专栏",
        )
        activity = Activity(
            dynamic_id="510000002",
            canonical_url="https://www.bilibili.com/opus/510000002",
            title="互动动态",
        )
        session.add_all([readlist, article, activity])
        session.flush()
        assert readlist.id is not None and article.id is not None and activity.id is not None
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
                source_section="interactive",
                discovered_in_run_id=discovery.id,
            )
        )
        session.add(discovery)
        session.commit()
        discovery_id = discovery.id

    service = ExecutionPlanService(Settings(), engine, EventHub())
    plan = service.create(PlanRequest(discovery_id=discovery_id))
    _run, items = service.get(plan.id or 0)
    assert len(items) == 1
    assert items[0].source_section == "interactive"
    assert items[0].mode == "interactive"
    assert json.loads(items[0].action_plan_json) == [
        "open_dynamic",
        "inspect_activity_like_first",
        "classify_official_or_unofficial",
        "execute_if_eligible",
    ]
