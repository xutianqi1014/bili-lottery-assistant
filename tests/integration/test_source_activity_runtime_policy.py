import json

import pytest
from sqlmodel import Session, create_engine, select

from backend.activity_engine.models import ActivitySnapshot
from backend.activity_engine.runtime_inspection import RuntimeActivityRead
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceProfile
from backend.jobs.events import EventHub
from backend.use_cases.run_execution import RunExecutionService


class _Reader:
    def __init__(
        self,
        snapshot: ActivitySnapshot,
        *,
        dynamic_unavailable: bool = False,
        activity_like_unknown: bool = False,
    ) -> None:
        self.snapshot = snapshot
        self.dynamic_unavailable = dynamic_unavailable
        self.activity_like_unknown = activity_like_unknown

    async def read(self, *args, **kwargs) -> RuntimeActivityRead:
        del args, kwargs
        return RuntimeActivityRead(
            snapshot=self.snapshot,
            body_excerpt=self.snapshot.body_text,
            page_title="测试动态",
            dynamic_unavailable=self.dynamic_unavailable,
            reservation_entry_present=self.snapshot.has_reservation_entry,
            reservation_control_text=self.snapshot.reservation_control_text,
            nonofficial_evidence_codes=self.snapshot.nonofficial_dom_evidence,
            activity_like_state=("unknown" if self.activity_like_unknown else "not_checked"),
            activity_like_reason_code=(
                "ACTIVITY_LIKE_CONTROL_NOT_FOUND" if self.activity_like_unknown else ""
            ),
            activity_like_unknown=self.activity_like_unknown,
        )


def _seed(engine, config: dict[str, object]) -> tuple[RunExecutionService, Run, RunItem]:
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="policy-test",
            mid="200",
            upload_url="https://space.bilibili.com/200/upload/opus",
            adapter_key="policy-test-v1",
            config_json=json.dumps(config),
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id or 0, state="preview_ready")
        activity = Activity(
            dynamic_id="1236380630515712009",
            canonical_url="https://www.bilibili.com/opus/1236380630515712009",
            title="测试预约混合动态",
        )
        session.add_all([discovery, activity])
        session.flush()
        run = Run(
            discovery_run_id=discovery.id or 0,
            state="running",
            stats_json=json.dumps({"requiresManualReview": False}),
        )
        session.add(run)
        session.flush()
        item = RunItem(
            run_id=run.id or 0,
            activity_id=activity.id or 0,
            sequence=1,
            dynamic_id=activity.dynamic_id,
            canonical_url=activity.canonical_url,
            title=activity.title,
            family="official",
            mode="unknown",
            unofficial_type="unknown",
            platform_status="unchecked",
        )
        session.add(item)
        session.commit()
        session.refresh(run)
        session.refresh(item)

    return RunExecutionService(engine, object(), EventHub(), settings=Settings()), run, item


@pytest.mark.asyncio
async def test_default_profile_blocks_reservation_without_reclassifying_it() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "预约抽奖 评论 转发 关注",
        has_reservation_entry=True,
        reservation_control_text="预约",
        actionable_text="评论转发关注，预约抽奖",
        nonofficial_dom_evidence=("UNOFFICIAL_SCOPED_BODY_FOUND",),
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "unofficial"]},
    )
    runner.reader = _Reader(snapshot)

    outcome = await runner._inspect_item(run, item)

    assert outcome.mode == "reservation"
    assert outcome.result_code == "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED"
    assert outcome.platform_status == "manual_review"
    assert "SOURCE_POLICY_RESERVATION_AS_UNOFFICIAL" not in outcome.inspection["evidenceCodes"]


@pytest.mark.asyncio
async def test_nuomi_profile_blocks_nonofficial_dynamic_type() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "评论 转发 关注",
        actionable_text="评论转发关注",
        nonofficial_dom_evidence=("UNOFFICIAL_SCOPED_BODY_FOUND",),
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "reservation"]},
    )
    runner.reader = _Reader(snapshot)

    outcome = await runner._inspect_item(run, item)

    assert outcome.mode == "unofficial"
    assert outcome.result_code == "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED"
    assert outcome.item_state == "waiting_user"


@pytest.mark.asyncio
async def test_nuomi_profile_skips_unavailable_dynamic_before_type_allowlist() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "返回上一页 换一张",
        actionable_text="返回上一页 换一张",
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "reservation"]},
    )
    runner.reader = _Reader(snapshot, dynamic_unavailable=True)

    policy = runner._source_activity_policy(run, item)
    continued = await runner._execute_configured_automatic_item(run, item, policy)

    assert continued is True
    with Session(engine) as session:
        saved = session.exec(
            select(RunItem).where(RunItem.activity_id == item.activity_id)
        ).one()
        assert saved is not None
        assert saved.state == "skipped"
        assert saved.result_code == "DYNAMIC_UNAVAILABLE_SKIPPED"
        assert saved.platform_status == "expired"


@pytest.mark.asyncio
async def test_liked_dynamic_skips_before_type_allowlist() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "已点赞动态正文",
        activity_like_active=True,
        actionable_text="已点赞动态正文",
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "reservation"]},
    )
    runner.reader = _Reader(snapshot)

    policy = runner._source_activity_policy(run, item)
    continued = await runner._execute_configured_automatic_item(run, item, policy)

    assert continued is True
    with Session(engine) as session:
        saved = session.exec(
            select(RunItem).where(RunItem.activity_id == item.activity_id)
        ).one()
        assert saved.state == "skipped"
        assert saved.result_code == "ALREADY_PARTICIPATED_LIKED"
        assert saved.platform_status == "already_liked"
        inspection = json.loads(saved.runtime_inspection_json)
        assert inspection["typeClassificationSkipped"] is True


@pytest.mark.asyncio
async def test_unknown_like_state_is_not_rewritten_as_source_type_mismatch() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "动态壳页面",
        actionable_text="动态壳页面",
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "unofficial", "reservation"]},
    )
    runner.reader = _Reader(snapshot, activity_like_unknown=True)

    policy = runner._source_activity_policy(run, item)
    continued = await runner._execute_configured_automatic_item(run, item, policy)

    assert continued is False
    with Session(engine) as session:
        saved = session.exec(
            select(RunItem).where(RunItem.activity_id == item.activity_id)
        ).one()
        assert saved.state == "waiting_user"
        assert saved.mode == "unknown"
        assert saved.result_code == "ACTIVITY_LIKE_STATE_UNKNOWN"
        assert saved.result_message is not None
        assert "点赞状态" in saved.result_message
        inspection = json.loads(saved.runtime_inspection_json)
        assert inspection["resultCode"] == "ACTIVITY_LIKE_STATE_UNKNOWN"
        assert inspection["typeClassificationSkipped"] is True


@pytest.mark.asyncio
async def test_nuomi_profile_skips_watch_only_reservation_before_writer() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    snapshot = ActivitySnapshot(
        "1236223920055517329",
        "https://www.bilibili.com/opus/1236223920055517329",
        "预约有奖：直播回放",
        has_reservation_entry=True,
        reservation_control_text="去观看",
        actionable_text="预约有奖：直播回放",
    )
    runner, run, item = _seed(
        engine,
        {"activityTypes": ["official", "reservation"]},
    )
    runner.reader = _Reader(snapshot)

    policy = runner._source_activity_policy(run, item)
    continued = await runner._execute_configured_automatic_item(run, item, policy)

    assert continued is True
    with Session(engine) as session:
        saved = session.exec(
            select(RunItem).where(RunItem.activity_id == item.activity_id)
        ).one()
        assert saved.state == "skipped"
        assert saved.result_code == "RESERVATION_WATCH_ONLY_SKIPPED"
        assert saved.platform_status == "expired"
