"""Behavior and operation-count checks for stage 4 data-path optimizations."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import Session, create_engine

from backend.api.routes import discoveries as discovery_routes
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity, ActivityOrigin
from backend.db.models.discovery import DiscoveryRun, DiscoverySelection
from backend.db.models.run import Run
from backend.db.models.source import Readlist, SourceArticle, SourceProfile
from backend.db.repositories import activities
from backend.domain.json_utils import load_json_object
from backend.jobs.events import EventHub
from backend.use_cases import source_closure
from backend.use_cases.execution_plan import ExecutionPlanService, PlanRequest


def seed(engine, count):
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="stage45", mid="42", upload_url="https://space/42", adapter_key="test"
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id, state="preview_ready")
        readlist = Readlist(
            source_profile_id=profile.id, rl_id="1", canonical_url="https://read/1",
            title="official", normalized_title="official", family="official", suffix_value=1,
        )
        article = SourceArticle(
            article_id="101", canonical_url="https://read/101", title="source", like_state="unliked"
        )
        session.add_all([discovery, readlist, article])
        session.flush()
        other = Readlist(
            source_profile_id=profile.id, rl_id="2", canonical_url="https://read/2",
            title="normal", normalized_title="normal", family="normal", suffix_value=1,
        )
        session.add(other)
        session.flush()
        for selected in [readlist, other]:
            session.add(DiscoverySelection(
                discovery_run_id=discovery.id, source_article_id=article.id,
                readlist_id=selected.id, family=selected.family, selected_rank=1,
                source_position=1, like_state_snapshot="unliked", decision="process",
                decision_reason="test",
            ))
        for index in range(count):
            activity = Activity(
                dynamic_id=str(500000 + index),
                canonical_url=f"https://www.bilibili.com/opus/{500000 + index}",
            )
            session.add(activity)
            session.flush()
            session.add(ActivityOrigin(
                source_article_id=article.id, activity_id=activity.id,
                discovered_in_run_id=discovery.id, source_position=count - index,
                source_section="interactive" if index % 2 else "reservation",
            ))
        session.commit()
        return discovery.id, article.id


@pytest.mark.parametrize("count", [100, 1000])
def test_plan_and_preview_use_one_context_query_regardless_of_activity_count(count, monkeypatch):
    engine = create_engine("sqlite://")
    init_database(engine)
    discovery_id, article_id = seed(engine, count)
    queries = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        service = ExecutionPlanService(Settings(), engine, EventHub())
        plan = service.create(PlanRequest(discovery_id, source_article_ids=(article_id,)))
        assert sum("JOIN discovery_selections" in q for q in queries) == 1
        assert len(queries) <= 12  # Whole plan read count remains bounded, not merely the join.
        _, items = service.get(plan.id)
        assert len(items) == count
        assert [item.dynamic_id for item in items] == [
            str(500000 + i) for i in reversed(range(count))
        ]
        assert all(item.family == "normal" for item in items)
        assert [item.source_section for item in items] == [
            "interactive" if i % 2 else "reservation" for i in reversed(range(count))
        ]
        queries.clear()
        monkeypatch.setattr(
            discovery_routes, "get_state", lambda _: SimpleNamespace(engine=engine)
        )
        preview = discovery_routes.get_discovery(discovery_id, None)
        assert len(preview["activities"]) == count
        assert all(len(row["origins"]) == 2 for row in preview["activities"])
        assert sum("JOIN discovery_selections" in q for q in queries) == 1
        assert len(queries) <= 8
        with Session(engine) as session:
            assert activities.list_origin_contexts_by_activity(session, -1) == {}
            first_id = items[0].activity_id
            assert len(activities.list_origin_contexts(session, discovery_id, first_id)) == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        engine.dispose()


def test_closure_parses_each_item_once_and_preserves_duplicate_source_semantics(monkeypatch):
    engine = create_engine("sqlite://")
    init_database(engine)
    discovery_id, article_id = seed(engine, 100)
    service = ExecutionPlanService(Settings(), engine, EventHub())
    run = service.create(PlanRequest(discovery_id))
    _, items = service.get(run.id)
    with Session(engine) as session:
        for item in items:
            item.state = "completed"
            item.source_article_ids_json = json.dumps([article_id, article_id, 9999])
            session.add(item)
        saved = session.get(Run, run.id)
        saved.source_article_ids_json = json.dumps([article_id, 9999, article_id])
        session.commit()
    original = source_closure._load_json_ints
    calls = []

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(source_closure, "_load_json_ints", counted)
    summary = source_closure.SourceClosureService(engine).get(run.id)
    assert len(calls) == 101  # One header plus each item, independent of source count.
    assert len(summary.rows) == 2
    assert summary.rows[0].status == "ready_to_mark"
    assert summary.rows[0].activity_count == 100
    assert summary.rows[1].reason_codes == ("SOURCE_ARTICLE_NOT_FOUND",)
    assert summary.rows[1].activity_count == 100
    engine.dispose()


@pytest.mark.parametrize("value,expected", [
    ("invalid", {}), ("null", {}), ("[]", {}), ("3", {}), ("true", {}),
    ('{"flag": true, "number": "3", "items": [1]}', {"flag": True, "number": "3", "items": [1]}),
])
def test_shared_object_reader_preserves_values_without_coercion(value, expected):
    assert load_json_object(value) == expected


def test_legacy_public_imports_are_compatible():
    from backend.legacy.source_like_plan import SourceLikePlanService
    from backend.use_cases.source_like_plan import SourceLikePlanService as old_service

    assert old_service is SourceLikePlanService
