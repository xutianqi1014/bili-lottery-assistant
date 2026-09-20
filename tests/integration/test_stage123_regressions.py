"""Regression coverage for discovery identity and mixed-section plans."""

import asyncio

import pytest
from sqlmodel import Session, create_engine

from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.source import Readlist, SourceArticle
from backend.db.repositories import activities, discoveries
from backend.db.repositories.profiles import seed_default_profile
from backend.jobs.events import EventHub
from backend.jobs.runner import JobRunner
from backend.use_cases.execution_plan import ExecutionPlanService, PlanRequest


def seed(session):
    profile = seed_default_profile(session)
    discovery = discoveries.create_discovery(session, profile.id, 5)
    discovery.state = "preview_ready"
    readlist = Readlist(
        source_profile_id=profile.id,
        rl_id="1",
        canonical_url="https://www.bilibili.com/read/readlist/rl1",
        family="official",
        title="test",
        normalized_title="test",
        suffix_value=1,
    )
    article = SourceArticle(
        article_id="610001", canonical_url="https://www.bilibili.com/read/cv610001", title="test"
    )
    session.add_all([discovery, readlist, article])
    session.flush()
    discoveries.add_selection(
        session, discovery.id, article, readlist, 1, 1, "unliked", "process", "test"
    )
    return discovery, readlist, article


@pytest.mark.parametrize(
    "sections",
    [
        ("interactive", "reservation", None),
        (None, "reservation", "interactive"),
    ],
)
def test_mixed_sections_are_preserved_per_item(sections):
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        discovery, _, article = seed(session)
        for index, section in enumerate(sections, 1):
            activity = Activity(
                dynamic_id=str(510000 + index),
                canonical_url=f"https://www.bilibili.com/opus/{510000 + index}",
            )
            session.add(activity)
            session.flush()
            activities.add_origin(session, article.id, activity, index, discovery.id, section)
        session.commit()
        discovery_id = discovery.id
    service = ExecutionPlanService(Settings(), engine, EventHub())
    run = service.create(PlanRequest(discovery_id))
    _, items = service.get(run.id)
    assert [item.source_section for item in items] == list(sections)
    assert [item.mode for item in items] == [s or "unknown" for s in sections]


def test_rediscovery_preserves_previous_membership_and_section():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        discovery, _, article = seed(session)
        activity = Activity(
            dynamic_id="510001", canonical_url="https://www.bilibili.com/opus/510001"
        )
        session.add(activity)
        session.flush()
        activities.add_origin(session, article.id, activity, 1, discovery.id, "interactive")
        session.commit()
        second = discoveries.create_discovery(session, discovery.source_profile_id, 5)
        activities.add_origin(session, article.id, activity, 9, second.id, "reservation")
        session.commit()
        assert len(activities.list_for_discovery(session, discovery.id)) == 1
        old = activities.list_origins_for_discovery(session, discovery.id)[0]
        new = activities.list_origins_for_discovery(session, second.id)[0]
        assert (old.source_position, old.source_section) == (1, "interactive")
        assert (new.source_position, new.source_section) == (9, "reservation")


def test_same_article_can_keep_two_readlist_contexts():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        discovery, _, article = seed(session)
        other = Readlist(
            source_profile_id=discovery.source_profile_id,
            rl_id="2",
            canonical_url="https://www.bilibili.com/read/readlist/rl2",
            family="normal",
            title="other",
            normalized_title="other",
            suffix_value=1,
        )
        session.add(other)
        session.flush()
        discoveries.add_selection(
            session, discovery.id, article, other, 1, 2, "unliked", "process", "test"
        )
        session.commit()
        assert len(discoveries.list_selections(session, discovery.id)) == 2


@pytest.mark.asyncio
async def test_completed_jobs_do_not_accumulate_and_ids_can_be_reused():
    runner = JobRunner(EventHub())

    async def noop():
        pass

    for index in range(100):
        runner.submit(str(index % 3), noop)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert not runner._tasks
    assert runner.can_submit("next")
    await runner.shutdown()


@pytest.mark.asyncio
async def test_job_cancelled_before_start_is_removed():
    runner = JobRunner(EventHub())

    async def never():
        raise AssertionError("cancelled job must not start")

    runner.submit("cancel", never)
    task = runner._tasks["cancel"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert not runner._tasks
    assert runner.can_submit("next")


@pytest.mark.asyncio
async def test_discovery_checks_shared_article_once_but_keeps_both_contexts():
    from backend.domain.entities import (
        ActivityExtractionResult,
        ActivityRef,
        MarkerInspection,
        ReadlistCandidate,
        SourceArticleCandidate,
    )
    from backend.domain.enums import LikeState, SourceFamily
    from backend.use_cases.discover_source import DiscoveryService

    class Adapter:
        checks = 0
        extracts = 0

        async def discover_readlists(self, profile, browser):
            return [
                ReadlistCandidate(
                    str(i),
                    f"https://www.bilibili.com/read/readlist/rl{i}",
                    "test",
                    "test",
                    family,
                    1,
                    1,
                    None,
                    None,
                )
                for i, family in enumerate((SourceFamily.NORMAL, SourceFamily.OFFICIAL), 1)
            ]

        def select_readlists(self, rows):
            return rows

        async def discover_entries(self, readlist, limit, browser):
            return [
                SourceArticleCandidate(
                    "610002", "https://www.bilibili.com/read/cv610002", "shared", 1
                )
            ]

        async def inspect_processed_marker(self, article, browser):
            self.checks += 1
            return MarkerInspection(LikeState.UNLIKED, "TEST", "test")

        async def extract_activities(self, article, browser):
            self.extracts += 1
            return ActivityExtractionResult(
                refs=(
                    ActivityRef(
                        "510002",
                        "https://www.bilibili.com/opus/510002",
                        1,
                        source_section="interactive",
                    ),
                )
            )

    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        profile = seed_default_profile(session)
        profile_id = profile.id
        adapter_key = profile.adapter_key
    service = DiscoveryService(Settings(), engine, object(), EventHub())
    adapter = Adapter()
    service.adapters[adapter_key] = adapter
    discovery = service.create(profile_id)
    await service.execute(discovery.id)
    with Session(engine) as session:
        saved = discoveries.get_discovery(session, discovery.id)
        assert saved.state == "preview_ready", saved.error_detail
        assert len(discoveries.list_selections(session, discovery.id)) == 2
        rows = activities.list_for_discovery(session, discovery.id)
        assert len(rows) == 1
        assert len(activities.list_origin_contexts(session, discovery.id, rows[0].id)) == 2
    assert (adapter.checks, adapter.extracts) == (1, 1)
