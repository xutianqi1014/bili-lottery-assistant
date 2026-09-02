import json

import pytest
from sqlmodel import Session, create_engine, select

from backend.activity_engine.models import ActivitySnapshot
from backend.activity_engine.official.participation import (
    OfficialParticipationOutcomeState,
    OfficialParticipationWriteResult,
)
from backend.activity_engine.runtime_inspection import RuntimeActivityRead
from backend.api.routes.runs import _serialize_run
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle
from backend.jobs.events import EventHub
from backend.source_adapters.lottery_toolman.source_like import (
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.use_cases.official_participation_execution import (
    OfficialParticipationExecutionService,
)
from backend.use_cases.run_execution import RunExecutionService
from backend.use_cases.source_like_automation import SourceLikeAutomationService


class _Locator:
    def __init__(self, count: int, text: str = "", on_click=None) -> None:
        self._count = count
        self._text = text
        self._on_click = on_click

    async def count(self) -> int:
        return self._count

    async def inner_text(self, timeout: int = 0) -> str:
        return self._text

    async def click(self, timeout: int = 0) -> None:
        if self._on_click is not None:
            self._on_click()

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        return None

    async def is_visible(self) -> bool:
        return bool(self._count)


class _FrameLocator:
    def __init__(self, text: str) -> None:
        self._text = text

    def locator(self, selector: str) -> _Locator:
        return _Locator(1, self._text)


class _Page:
    url = "https://www.bilibili.com/opus/910000001"

    def __init__(
        self,
        body: str,
        panel_text: str,
        show_panel: bool = True,
        liked: bool = False,
    ) -> None:
        self.body = body
        self.panel_text = panel_text
        self.show_panel = show_panel
        self.liked = liked
        self.clicked = False

    async def content(self) -> str:
        return '<a data-type="lottery" href="#">互动抽奖</a>'

    async def title(self) -> str:
        return "测试官方动态"

    def locator(self, selector: str) -> _Locator:
        if selector == "body":
            return _Locator(1, self.body)
        if selector == 'a[data-type="lottery"]':
            return _Locator(1, on_click=lambda: setattr(self, "clicked", True))
        if selector == 'iframe[src*="/h5/lottery/result"]':
            return _Locator(1 if self.clicked and self.show_panel else 0)
        if selector == ".side-toolbar__action.like.is-active":
            return _Locator(1 if self.liked else 0)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like.is-active",
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[aria-pressed="true"]',
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[data-state="active"]',
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[data-liked="true"]',
        }:
            return _Locator(1 if self.liked else 0)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like",
            ".content .sidebar-wrap .side-toolbar__action.like",
            ".side-toolbar__action.like",
            ".bili-dyn-action.like",
        }:
            return _Locator(1)
        return _Locator(0)

    def frame_locator(self, selector: str) -> _FrameLocator:
        return _FrameLocator(self.panel_text)


class _Browser:
    def __init__(
        self,
        body: str,
        panel_text: str = "",
        show_panel: bool = True,
        liked: bool = False,
    ) -> None:
        self.body = body
        self.panel_text = panel_text
        self.show_panel = show_panel
        self.liked = liked
        self.opened_urls: list[str] = []
        self.pages: list[_Page] = []

    async def open(self, url: str) -> _Page:
        self.opened_urls.append(url)
        page = _Page(self.body, self.panel_text, self.show_panel, self.liked)
        self.pages.append(page)
        return page


class _NonOfficialPage(_Page):
    async def content(self) -> str:
        return "<div class=opus-content>评论 转发 关注</div>"

    def locator(self, selector: str) -> _Locator:
        if selector == "body":
            return _Locator(1, self.body)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like",
            ".content .sidebar-wrap .side-toolbar__action.like",
            ".side-toolbar__action.like",
            ".bili-dyn-action.like",
        }:
            return _Locator(1)
        return _Locator(0)


class _NonOfficialBrowser(_Browser):
    async def open(self, url: str) -> _NonOfficialPage:
        self.opened_urls.append(url)
        page = _NonOfficialPage(self.body, self.panel_text, self.show_panel)
        self.pages.append(page)
        return page


class _SequentialOfficialTransport:
    def __init__(self, results: list[OfficialParticipationWriteResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del payload
        self.calls.append(target_url)
        return self.results[len(self.calls) - 1]


class _SourceLikeTransport:
    def __init__(self, result: SourceLikeWriteResult) -> None:
        self.result = result
        self.calls: list[str] = []

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del payload
        self.calls.append(target_url)
        return self.result


def test_official_automation_delay_is_randomized_within_configured_range() -> None:
    engine = create_engine("sqlite://")
    settings = Settings(
        official_automation_delay_min_sec=3,
        official_automation_delay_max_sec=5,
    )
    runner = RunExecutionService(
        engine,
        _Browser(""),
        EventHub(),
        settings=settings,
    )

    samples = [runner._next_official_delay_seconds() for _ in range(100)]

    assert all(3 <= sample <= 5 for sample in samples)
    assert len(set(samples)) > 1


def _seed_run(engine, state: str = "queued", family: str = "official") -> int:
    with Session(engine) as session:
        discovery = DiscoveryRun(source_profile_id=1, state="preview_ready")
        activity = Activity(
            dynamic_id="910000001",
            canonical_url="https://www.bilibili.com/opus/910000001",
            title="测试官方动态",
        )
        session.add_all([discovery, activity])
        session.flush()
        assert discovery.id is not None and activity.id is not None
        run = Run(
            discovery_run_id=discovery.id,
            state=state,
            stats_json=json.dumps(
                {
                    "totalActivities": 1,
                    "plannedActivities": 1,
                    "blockedActivities": 0,
                    "requiresManualReview": False,
                    "activityPreflightUsed": False,
                }
            ),
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
                family=family,
                mode="unknown",
                unofficial_type="unknown",
                platform_status="unchecked",
                state="planned",
            )
        )
        session.commit()
        return run.id


def _append_official_item(engine, run_id: int, *, dynamic_id: str, sequence: int) -> None:
    with Session(engine) as session:
        activity = Activity(
            dynamic_id=dynamic_id,
            canonical_url=f"https://www.bilibili.com/opus/{dynamic_id}",
            title=f"测试官方动态 {sequence}",
        )
        session.add(activity)
        session.flush()
        assert activity.id is not None
        session.add(
            RunItem(
                run_id=run_id,
                activity_id=activity.id,
                sequence=sequence,
                dynamic_id=dynamic_id,
                canonical_url=activity.canonical_url,
                title=activity.title,
                family="official",
                mode="official",
                unofficial_type="unknown",
                platform_status="unchecked",
                state="planned",
            )
        )
        session.commit()


@pytest.mark.asyncio
async def test_execution_inspects_one_terminal_item_and_never_writes():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    browser = _Browser("互动抽奖 抽奖已结束", "抽奖已结束")
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "completed"
        item = session.get(RunItem, (run_id, 1))
        assert item is not None
        assert item.state == "skipped"
        assert item.platform_status == "expired"
        assert item.result_code == "LOTTERY_EXPIRED"
        assert item.runtime_inspected_at is not None
        assert json.loads(item.runtime_inspection_json)["evidenceCodes"] == [
            "OFFICIAL_IFRAME_ENTRY",
            "OFFICIAL_LOTTERY_PANEL_OPENED",
            "OFFICIAL_ACTIVITY_UNLIKED_MARKER",
        ]
        assert json.loads(item.runtime_inspection_json)["officialEntryOpened"] is True
    assert browser.opened_urls == ["https://www.bilibili.com/opus/910000001"]


@pytest.mark.asyncio
async def test_execution_pauses_at_manual_gate_for_eligible_item():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    browser = _Browser(
        "互动抽奖 请完成评论后参与",
        "开奖时间：2026年08月09日 18:00 参与条件：请完成评论后参与",
    )
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.state == "waiting_user"
        assert run.status_detail is not None
        item = session.get(RunItem, (run_id, 1))
        assert item is not None
        assert item.state == "waiting_user"
        assert item.result_code == "MANUAL_GATE_REQUIRED"
        assert item.platform_status == "eligible_waiting_user"
    assert browser.opened_urls == ["https://www.bilibili.com/opus/910000001"]


def test_prepare_restart_resets_only_the_current_manual_review_item() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="waiting_user")
    _append_official_item(engine, run_id, dynamic_id="910000002", sequence=2)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        current = session.get(RunItem, (run_id, 1))
        completed = session.get(RunItem, (run_id, 2))
        assert run is not None and current is not None and completed is not None
        current.state = "waiting_user"
        current.mode = "official"
        current.platform_status = "manual_review"
        current.runtime_inspected_at = current.created_at
        current.runtime_selector_version = "runtime-v1"
        current.runtime_inspection_json = json.dumps({"resultCode": "UNKNOWN"})
        current.result_code = "UNKNOWN"
        current.result_message = "manual review required"
        current.block_reason = "manual review required"
        completed.state = "skipped"
        completed.platform_status = "already_participated"
        run.stats_json = json.dumps(
            {
                "totalActivities": 2,
                "plannedActivities": 2,
                "blockedActivities": 1,
                "skippedActivities": 1,
                "requiresManualReview": True,
                "unofficialParticipationLastResult": "COMMENT_EDITOR_NOT_UNIQUE",
                "unofficialParticipationWrites": {
                    str(current.activity_id): {
                        "state": "blocked_failed",
                        "resultState": "failed",
                        "resultCode": "COMMENT_EDITOR_NOT_UNIQUE",
                        "checkpoint": {
                            "status": "blocked_failed",
                            "checkpoints": [
                                {"action": "comment", "state": "failed"},
                                {"action": "repost", "state": "pending"},
                                {"action": "like", "state": "pending"},
                                {"action": "follow", "state": "pending"},
                            ],
                        },
                    }
                },
            }
        )
        session.add_all([run, current, completed])
        session.commit()

    runner = RunExecutionService(engine, _Browser(""), EventHub())
    prepared = runner.prepare_restart(run_id)
    assert prepared.state == "waiting_user"

    with Session(engine) as session:
        run = session.get(Run, run_id)
        current = session.get(RunItem, (run_id, 1))
        completed = session.get(RunItem, (run_id, 2))
        assert run is not None and current is not None and completed is not None
        assert current.state == "planned"
        assert current.platform_status == "unchecked"
        assert current.runtime_inspected_at is None
        assert current.runtime_inspection_json == "{}"
        assert current.result_code is None
        assert completed.state == "skipped"
        stats = json.loads(run.stats_json)
        assert stats["requiresManualReview"] is False
        assert stats["restartCount"] == 1
        assert str(current.activity_id) not in stats.get("unofficialParticipationWrites", {})
        assert "unofficialParticipationLastResult" not in stats

    queued = runner.queue(run_id, resume=True)
    assert queued.state == "queued"


def test_prepare_restart_keeps_unofficial_write_with_confirmed_side_effect() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="waiting_user", family="normal")
    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        item.state = "waiting_user"
        run.stats_json = json.dumps(
            {
                "requiresManualReview": True,
                "unofficialParticipationLastResult": "LIKE_CONTROL_NOT_UNIQUE",
                "unofficialParticipationWrites": {
                    str(item.activity_id): {
                        "state": "blocked_failed",
                        "resultState": "failed",
                        "resultCode": "LIKE_CONTROL_NOT_UNIQUE",
                        "checkpoint": {
                            "status": "blocked_failed",
                            "checkpoints": [
                                {"action": "comment", "state": "confirmed"},
                                {"action": "repost", "state": "confirmed"},
                                {"action": "like", "state": "failed"},
                                {"action": "follow", "state": "pending"},
                            ],
                        },
                    }
                },
            }
        )
        session.add_all([run, item])
        session.commit()

    runner = RunExecutionService(engine, _Browser(""), EventHub())
    runner.prepare_restart(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        stats = json.loads(run.stats_json)
        assert item.state == "planned"
        assert str(item.activity_id) in stats["unofficialParticipationWrites"]
        assert stats["unofficialParticipationLastResult"] == "LIKE_CONTROL_NOT_UNIQUE"


def test_prepare_restart_clears_legacy_prewrite_security_unknown() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="waiting_user", family="normal")
    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        item.state = "waiting_user"
        run.stats_json = json.dumps(
            {
                "requiresManualReview": True,
                "unofficialParticipationLastResult": "COMMENT_SECURITY_CHALLENGE",
                "unofficialParticipationWrites": {
                    str(item.activity_id): {
                        "state": "blocked_unknown",
                        "resultState": "unknown",
                        "resultCode": "COMMENT_SECURITY_CHALLENGE",
                        "checkpoint": {
                            "status": "blocked_unknown",
                            "checkpoints": [
                                {"action": "comment", "state": "unknown"},
                                {"action": "repost", "state": "pending"},
                                {"action": "like", "state": "pending"},
                                {"action": "follow", "state": "pending"},
                            ],
                        },
                    }
                },
            }
        )
        session.add_all([run, item])
        session.commit()

    runner = RunExecutionService(engine, _Browser(""), EventHub())
    runner.prepare_restart(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        stats = json.loads(run.stats_json)
        assert item.state == "planned"
        assert str(item.activity_id) not in stats.get("unofficialParticipationWrites", {})
        assert "unofficialParticipationLastResult" not in stats


@pytest.mark.asyncio
async def test_execution_uses_liked_marker_without_opening_panel():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    browser = _Browser(
        "互动抽奖",
        "开奖时间：2026年08月09日 18:00",
        liked=True,
    )
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        assert run.state == "completed"
        assert item.state == "skipped"
        assert item.result_code == "ALREADY_PARTICIPATED_LIKED"
        inspection = json.loads(item.runtime_inspection_json)
        assert inspection["officialEntryOpened"] is False
        assert inspection["isParticipated"] is True
        stats = json.loads(run.stats_json)
        assert stats["totalActivities"] == 1
        assert stats["plannedActivities"] == 1
        assert stats["skippedActivities"] == 1
        assert stats["blockedActivities"] == 0


def test_run_serializer_reconciles_historical_stale_skip_count() -> None:
    run = Run(
        id=63,
        discovery_run_id=7,
        state="completed",
        stats_json=json.dumps(
            {
                "totalActivities": 2,
                "plannedActivities": 2,
                "skippedActivities": 0,
                "blockedActivities": 0,
            }
        ),
    )
    items = [
        RunItem(
            run_id=63,
            activity_id=index,
            sequence=index,
            dynamic_id=str(index),
            canonical_url=f"https://www.bilibili.com/opus/{index}",
            title=f"动态 {index}",
            family="official",
            mode="official",
            unofficial_type="unknown",
            platform_status="already_liked",
            state="skipped",
        )
        for index in (1, 2)
    ]

    payload = _serialize_run(run, items)

    assert payload["stats"]["totalActivities"] == 2
    assert payload["stats"]["plannedActivities"] == 2
    assert payload["stats"]["skippedActivities"] == 2
    assert payload["stats"]["blockedActivities"] == 0


@pytest.mark.asyncio
async def test_execution_persists_source_closure_after_terminal_item():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    with Session(engine) as session:
        article = SourceArticle(
            article_id="closure-cv",
            canonical_url="https://www.bilibili.com/read/closure-cv",
            title="收尾来源",
            like_state="unliked",
        )
        session.add(article)
        session.flush()
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert article.id is not None and run is not None and item is not None
        run.source_article_ids_json = json.dumps([article.id])
        item.source_article_ids_json = json.dumps([article.id])
        session.add_all([run, item])
        session.commit()

    browser = _Browser("互动抽奖 抽奖已结束", "抽奖已结束")
    service = RunExecutionService(engine, browser, EventHub())
    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        closure = json.loads(run.stats_json)["sourceClosure"]
        assert closure["readyToMarkCount"] == 1
        assert closure["items"][0]["status"] == "ready_to_mark"


@pytest.mark.asyncio
async def test_active_countdown_is_not_marked_expired_by_stale_body_copy():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    browser = _Browser(
        "互动抽奖 抽奖已结束",
        "开奖倒计时 03 天 19 时 22 分 开奖时间：2026年08月12日 18:00 已成功参与",
    )
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        assert run.state == "waiting_user"
        assert item.result_code == "MANUAL_GATE_REQUIRED"
        assert item.platform_status == "eligible_waiting_user"
        assert json.loads(item.runtime_inspection_json)["isExpired"] is False


@pytest.mark.asyncio
async def test_lottery_panel_failure_records_problem_url_and_waits():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine)
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, 1))
        assert item is not None
        item.source_article_ids_json = json.dumps([7001])
        session.add(item)
        session.commit()

    browser = _Browser("互动抽奖", show_panel=False)
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        problem = session.exec(select(ProblemRecord)).first()
        assert problem is not None
        assert problem.problem_url == "https://www.bilibili.com/opus/910000001"
        assert problem.problem_code == "OFFICIAL_LOTTERY_PANEL_NOT_FOUND"
        assert problem.status == "open"

        item = session.get(RunItem, (run_id, 1))
        assert item is not None
        assert item.platform_status == "manual_review"


@pytest.mark.asyncio
async def test_unofficial_runtime_snapshot_exposes_checkpoints_without_writing():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, family="normal")
    browser = _NonOfficialBrowser("评论 转发 关注")
    service = RunExecutionService(engine, browser, EventHub())

    await service.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        assert run.state == "waiting_user"
        inspection = json.loads(item.runtime_inspection_json)
        assert inspection["unofficialActionPlan"]["directWriteEnabled"] is False
        assert inspection["unofficialActionPlan"]["actions"] == [
            "comment",
            "repost",
            "like",
            "follow",
        ]
        assert inspection["unofficialCheckpoints"]["status"] == "ready"
        assert inspection["unofficialCheckpoints"]["nextAction"] == "comment"
        assert browser.opened_urls == ["https://www.bilibili.com/opus/910000001"]


@pytest.mark.asyncio
async def test_unofficial_requirements_use_scoped_dynamic_text_not_page_chrome():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, family="normal")
    observed_delay: list[float] = []

    class _ScopedReader:
        async def read(
            self,
            browser,
            dynamic_id,
            canonical_url,
            *,
            post_open_delay_sec=0.0,
        ):
            del browser, dynamic_id, canonical_url
            observed_delay.append(post_open_delay_sec)
            return RuntimeActivityRead(
                snapshot=ActivitySnapshot(
                    dynamic_id="910000001",
                    canonical_url="https://www.bilibili.com/opus/910000001",
                    body_text=(
                        "转发+关注即可参与 评论 2276 赞与转发 1712 56 2579 2276 顶部"
                    ),
                    actionable_text="转发+关注即可参与",
                    nonofficial_dom_evidence=("UNOFFICIAL_SCOPED_BODY_FOUND",),
                ),
                body_excerpt="转发+关注即可参与 评论 2276 赞与转发 1712",
                page_title="测试非官方动态",
                nonofficial_outer_text="转发+关注即可参与",
                nonofficial_evidence_codes=("UNOFFICIAL_SCOPED_BODY_FOUND",),
            )

    service = RunExecutionService(engine, _Browser(""), EventHub())
    service.reader = _ScopedReader()
    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        assert run is not None and item is not None
        outcome = await service._inspect_item(run, item)

    assert outcome.requirements is not None
    assert outcome.requirements.comment_instruction == ""
    assert outcome.requirements.required_actions == ("repost", "follow")
    assert len(observed_delay) == 1
    assert 1.0 <= observed_delay[0] <= 2.0


@pytest.mark.asyncio
async def test_official_automation_processes_confirmed_run_without_per_item_gate(tmp_path):
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="confirmed_waiting_user")
    _append_official_item(engine, run_id, dynamic_id="910000002", sequence=2)
    del tmp_path
    settings = Settings(
        official_automation_enabled=True,
        official_automation_delay_min_sec=0,
        official_automation_delay_max_sec=0,
    )
    transport = _SequentialOfficialTransport(
        [
            OfficialParticipationWriteResult(
                OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
                "ALREADY_PARTICIPATED",
                "already done",
            ),
            OfficialParticipationWriteResult(
                OfficialParticipationOutcomeState.SUCCESS,
                "OFFICIAL_PARTICIPATION_CONFIRMED",
                "confirmed",
            ),
        ]
    )
    browser = _Browser("")
    official_service = OfficialParticipationExecutionService(
        settings,
        engine,
        browser,
        transport_factory=lambda: transport,
    )
    runner = RunExecutionService(
        engine,
        browser,
        EventHub(),
        settings=settings,
        official_participation_service=official_service,
    )

    queued = runner.queue(run_id)
    assert queued.state == "queued"
    await runner.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        items = list(
            session.exec(
                select(RunItem)
                .where(RunItem.run_id == run_id)
                .order_by(RunItem.__table__.c.sequence)  # type: ignore[attr-defined]
            ).all()
        )
        assert run is not None and run.state == "completed"
        assert [item.state for item in items] == ["skipped", "completed"]
        assert [item.result_code for item in items] == [
            "ALREADY_PARTICIPATED",
            "OFFICIAL_PARTICIPATION_CONFIRMED",
        ]
        stats = json.loads(run.stats_json)
        assert stats["totalActivities"] == 2
        assert stats["plannedActivities"] == 1
        assert stats["skippedActivities"] == 1
        assert stats["blockedActivities"] == 0
    assert transport.calls == [
        "https://www.bilibili.com/opus/910000001",
        "https://www.bilibili.com/opus/910000002",
    ]
    assert browser.opened_urls == []


def test_official_automation_queue_accepts_two_sources_with_31_targets() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="confirmed_waiting_user")
    for sequence in range(2, 32):
        _append_official_item(
            engine,
            run_id,
            dynamic_id=f"910000{sequence:03d}",
            sequence=sequence,
        )

    with Session(engine) as session:
        sources = [
            SourceArticle(
                article_id=f"52199{index}",
                canonical_url=f"https://www.bilibili.com/read/cv52199{index}",
                title=f"双来源测试 {index}",
                like_state="unliked",
            )
            for index in (1, 2)
        ]
        session.add_all(sources)
        session.flush()
        source_ids = [source.id for source in sources if source.id is not None]
        assert len(source_ids) == 2
        run = session.get(Run, run_id)
        assert run is not None
        run.source_article_ids_json = json.dumps(source_ids)
        items = list(session.exec(select(RunItem).where(RunItem.run_id == run_id)).all())
        for item in items:
            item.source_article_ids_json = json.dumps(
                [source_ids[(item.sequence - 1) % len(source_ids)]]
            )
            session.add(item)
        session.add(run)
        session.commit()

    settings = Settings(official_automation_enabled=True)
    browser = _Browser("")
    official_service = OfficialParticipationExecutionService(
        settings,
        engine,
        browser,
    )
    runner = RunExecutionService(
        engine,
        browser,
        EventHub(),
        settings=settings,
        official_participation_service=official_service,
    )

    assert len(official_service.validate_run_scope(run_id)) == 31
    queued = runner.queue(run_id)

    assert queued.state == "queued"
    assert browser.opened_urls == []


def test_normal_only_run_can_queue_without_official_service() -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(
        engine,
        state="confirmed_waiting_user",
        family="normal",
    )
    browser = _NonOfficialBrowser("评论 转发 点赞 关注")
    runner = RunExecutionService(
        engine,
        browser,
        EventHub(),
        settings=Settings(official_automation_enabled=True),
        official_participation_service=None,
    )

    queued = runner.queue(run_id)

    assert queued.state == "queued"
    assert "非官方执行队列" in (queued.status_detail or "")
    assert browser.opened_urls == []


@pytest.mark.asyncio
async def test_official_run_automatically_likes_safe_source_after_last_item():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id = _seed_run(engine, state="confirmed_waiting_user")
    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, 1))
        article = SourceArticle(
            article_id="52190001",
            canonical_url="https://www.bilibili.com/read/cv52190001",
            title="待自动收尾来源",
            like_state="unliked",
        )
        assert run is not None and item is not None
        session.add(article)
        session.flush()
        assert article.id is not None
        run.source_article_ids_json = json.dumps([article.id])
        item.source_article_ids_json = json.dumps([article.id])
        session.add_all([run, item])
        session.commit()
        source_article_id = article.id

    settings = Settings(
        official_automation_enabled=True,
        official_automation_delay_min_sec=0,
        official_automation_delay_max_sec=0,
        source_like_automation_enabled=True,
        source_like_automation_delay_min_sec=0,
        source_like_automation_delay_max_sec=0,
    )
    official_transport = _SequentialOfficialTransport(
        [
            OfficialParticipationWriteResult(
                OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
                "ALREADY_PARTICIPATED",
                "already done",
            )
        ]
    )
    source_transport = _SourceLikeTransport(
        SourceLikeWriteResult(
            SourceLikeOutcomeState.SUCCESS,
            "SOURCE_LIKE_CONFIRMED",
            "source confirmed",
        )
    )
    browser = _Browser("")
    official_service = OfficialParticipationExecutionService(
        settings,
        engine,
        browser,
        transport_factory=lambda: official_transport,
    )
    source_service = SourceLikeAutomationService(
        settings,
        engine,
        browser,
        transport_factory=lambda: source_transport,
    )
    runner = RunExecutionService(
        engine,
        browser,
        EventHub(),
        settings=settings,
        official_participation_service=official_service,
        source_like_automation_service=source_service,
    )

    runner.queue(run_id)
    await runner.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        article = session.get(SourceArticle, source_article_id)
        assert run is not None and run.state == "completed"
        assert article is not None and article.like_state == "liked"
        stats = json.loads(run.stats_json)
        assert stats["sourceLikeAutomation"]["state"] == "completed"
        assert stats["sourceClosure"]["alreadyLikedCount"] == 1
        assert "1 个来源专栏已自动点赞并确认终态" in (run.status_detail or "")
    assert official_transport.calls == ["https://www.bilibili.com/opus/910000001"]
    assert source_transport.calls == ["https://www.bilibili.com/read/cv52190001"]
