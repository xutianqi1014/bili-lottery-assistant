from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, select

from backend.activity_engine.models import ParticipationRequirements, UnofficialType
from backend.activity_engine.unofficial import (
    UnofficialAction,
    UnofficialActionPlanner,
    WriteOperationResult,
    WriteOutcomeState,
)
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.integrations.deepseek import DeepSeekCommentRequest
from backend.jobs.events import EventHub
from backend.use_cases.run_execution import RunExecutionService
from backend.use_cases.unofficial_participation_execution import (
    UnofficialParticipationExecutionService,
)


class _Transport:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[UnofficialAction] = []
        self.payloads: list[dict[str, object]] = []

    async def perform(self, action, *, target_url, payload):
        del target_url
        self.calls.append(action)
        self.payloads.append(dict(payload))
        return self.results[len(self.calls) - 1]


class _CommentGenerator:
    def __init__(self, comment: str = "这次活动很有诚意，感谢分享！"):
        self.comment = comment
        self.requests: list[DeepSeekCommentRequest] = []

    async def generate(self, request: DeepSeekCommentRequest) -> str:
        self.requests.append(request)
        return self.comment


class _RuntimeLocator:
    def __init__(self, count=0, text=""):
        self._count = count
        self._text = text

    async def count(self):
        return self._count

    async def inner_text(self, **_kwargs):
        return self._text

    async def is_visible(self):
        return self._count > 0


class _RuntimePage:
    url = "https://www.bilibili.com/opus/123456789"

    async def content(self):
        return "<div class='opus-module-content'>抽奖 评论 转发 点赞 关注</div>"

    async def title(self):
        return "normal giveaway"

    def locator(self, selector):
        if selector == "body":
            return _RuntimeLocator(1, "抽奖 评论 转发 点赞 关注")
        if selector in {".opus-module-content", '.bili-dyn-content__forw__desc[data-orig="0"]'}:
            return _RuntimeLocator(1, "抽奖 评论 转发 点赞 关注")
        return _RuntimeLocator(0)


class _RuntimeBrowser:
    async def open(self, _url):
        return _RuntimePage()


def _seed(engine, *, source_ids: str = "[1]") -> tuple[int, int]:
    with Session(engine) as session:
        discovery = DiscoveryRun(source_profile_id=1, state="preview_ready")
        activity = Activity(
            dynamic_id="123456789",
            canonical_url="https://www.bilibili.com/opus/123456789",
            title="normal giveaway",
        )
        session.add_all([discovery, activity])
        session.flush()
        run = Run(
            discovery_run_id=discovery.id,
            state="running",
            stats_json=json.dumps({"requiresManualReview": False}),
        )
        session.add(run)
        session.flush()
        session.add(
            RunItem(
                run_id=run.id,
                activity_id=activity.id,
                sequence=1,
                dynamic_id=activity.dynamic_id,
                canonical_url=activity.canonical_url,
                title=activity.title,
                family="normal",
                mode="unofficial",
                unofficial_type="normal",
                platform_status="eligible_waiting_user",
                source_article_ids_json=source_ids,
            )
        )
        session.commit()
        assert run.id is not None and activity.id is not None
        return run.id, activity.id


def _plan():
    requirements = ParticipationRequirements(
        required_actions=("comment", "repost", "like", "follow"),
        comment_instruction="参与抽奖",
    )
    plan = UnofficialActionPlanner().build(
        unofficial_type=UnofficialType.NORMAL,
        requirements=requirements,
    )
    return plan, requirements


@pytest.mark.asyncio
async def test_normal_comment_checkbox_marks_repost_and_persists_all_checkpoints():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport(
        [
            WriteOperationResult(
                WriteOutcomeState.SUCCESS,
                "COMMENT_SUBMIT_ACCEPTED",
                "comment submit accepted",
                ("repost",),
            ),
            WriteOperationResult(
                WriteOutcomeState.SUCCESS, "DYNAMIC_LIKE_CONFIRMED", "like confirmed"
            ),
            WriteOperationResult(
                WriteOutcomeState.ALREADY_DONE, "FOLLOW_ALREADY_DONE", "already followed"
            ),
        ]
    )
    settings = Settings(
        unofficial_automation_enabled=True,
        unofficial_automation_delay_min_sec=0,
        unofficial_automation_delay_max_sec=0,
    )
    service = UnofficialParticipationExecutionService(
        settings,
        engine,
        object(),
        transport_factory=lambda: transport,
    )
    plan, requirements = _plan()

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
    )

    assert result["state"] == "completed"
    assert transport.calls == [
        UnofficialAction.COMMENT,
        UnofficialAction.LIKE,
        UnofficialAction.FOLLOW,
    ]
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        run = session.get(Run, run_id)
        assert item is not None and item.state == "completed"
        assert run is not None
        writes = json.loads(run.stats_json)["unofficialParticipationWrites"]
        assert writes[str(activity_id)]["checkpoint"]["status"] == "completed"


@pytest.mark.asyncio
async def test_boosted_uses_comment_checkbox_without_separate_repost():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport(
        [
            WriteOperationResult(
                WriteOutcomeState.SUCCESS,
                "COMMENT_SUBMIT_ACCEPTED",
                "comment submit accepted",
                ("repost",),
            ),
            WriteOperationResult(
                WriteOutcomeState.SUCCESS, "DYNAMIC_LIKE_CONFIRMED", "like confirmed"
            ),
            WriteOperationResult(
                WriteOutcomeState.ALREADY_DONE, "FOLLOW_ALREADY_DONE", "already followed"
            ),
        ]
    )
    settings = Settings(
        unofficial_automation_enabled=True,
        unofficial_automation_delay_min_sec=0,
        unofficial_automation_delay_max_sec=0,
    )
    service = UnofficialParticipationExecutionService(
        settings,
        engine,
        object(),
        transport_factory=lambda: transport,
    )
    requirements = ParticipationRequirements(
        required_actions=("comment", "repost", "like", "follow"),
        comment_instruction="参与加码抽奖",
    )
    plan = UnofficialActionPlanner().build(
        unofficial_type=UnofficialType.BOOSTED,
        requirements=requirements,
    )

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
    )

    assert result["state"] == "completed"
    assert transport.calls == [
        UnofficialAction.COMMENT,
        UnofficialAction.LIKE,
        UnofficialAction.FOLLOW,
    ]
    assert transport.payloads[0]["repostWithComment"] is True
    assert plan.unofficial_type == "boosted"


@pytest.mark.asyncio
async def test_unknown_result_is_persisted_and_second_call_is_rejected():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport(
        [
            WriteOperationResult(
                WriteOutcomeState.UNKNOWN,
                "COMMENT_SUBMIT_UNKNOWN",
                "comment submit click was unknown",
            )
        ]
    )
    service = UnofficialParticipationExecutionService(
        Settings(unofficial_automation_enabled=True),
        engine,
        object(),
        transport_factory=lambda: transport,
    )
    plan, requirements = _plan()

    first = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
    )
    assert first["state"] == "blocked_unknown"
    with pytest.raises(ValueError, match="UNOFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY"):
        await service.execute(
            run_id,
            activity_id=activity_id,
            action_plan=plan,
            requirements=requirements,
        )
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        problem = session.exec(select(ProblemRecord)).first()
        assert item is not None and item.state == "waiting_user"
        assert problem is not None and problem.problem_code == "COMMENT_SUBMIT_UNKNOWN"


@pytest.mark.asyncio
async def test_mentions_block_before_any_transport_call():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport([])
    service = UnofficialParticipationExecutionService(
        Settings(unofficial_automation_enabled=True),
        engine,
        object(),
        transport_factory=lambda: transport,
    )
    plan, _requirements = _plan()
    requirements = ParticipationRequirements(
        required_actions=("comment",),
        required_mention_count=1,
    )

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
    )

    assert result["resultCode"] == "COMMENT_MENTION_REQUIRED"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_run_execution_inspects_then_executes_non_official_plan():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.state = "confirmed_waiting_user"
        session.add(run)
        session.commit()
    transport = _Transport(
        [
            WriteOperationResult(
                WriteOutcomeState.SUCCESS,
                "COMMENT_SUBMIT_ACCEPTED",
                "comment submit accepted",
                ("repost",),
            ),
            WriteOperationResult(
                WriteOutcomeState.SUCCESS, "DYNAMIC_LIKE_CONFIRMED", "like confirmed"
            ),
            WriteOperationResult(WriteOutcomeState.SUCCESS, "FOLLOW_CONFIRMED", "follow confirmed"),
        ]
    )
    settings = Settings(
        official_automation_enabled=False,
        unofficial_automation_enabled=True,
        unofficial_automation_delay_min_sec=0,
        unofficial_automation_delay_max_sec=0,
    )
    unofficial_service = UnofficialParticipationExecutionService(
        settings,
        engine,
        _RuntimeBrowser(),
        transport_factory=lambda: transport,
    )
    runner = RunExecutionService(
        engine,
        _RuntimeBrowser(),
        EventHub(),
        settings=settings,
        unofficial_participation_service=unofficial_service,
    )
    runner.queue(run_id)
    await runner.execute(run_id)

    with Session(engine) as session:
        run = session.get(Run, run_id)
        item = session.get(RunItem, (run_id, activity_id))
        assert run is not None and item is not None
        assert run.state == "completed"
        assert item.state == "completed"
    assert transport.calls == [
        UnofficialAction.COMMENT,
        UnofficialAction.LIKE,
        UnofficialAction.FOLLOW,
    ]


@pytest.mark.asyncio
async def test_deepseek_comment_is_augmented_with_topics_and_fixed_mentions():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport(
        [
            WriteOperationResult(
                WriteOutcomeState.SUCCESS,
                "COMMENT_SUBMIT_ACCEPTED",
                "comment submit accepted",
                ("repost",),
            ),
            WriteOperationResult(WriteOutcomeState.SUCCESS, "DYNAMIC_LIKE_CONFIRMED", "liked"),
            WriteOperationResult(WriteOutcomeState.SUCCESS, "FOLLOW_CONFIRMED", "followed"),
        ]
    )
    generator = _CommentGenerator()
    settings = Settings(
        unofficial_automation_enabled=True,
        unofficial_automation_delay_min_sec=0,
        unofficial_automation_delay_max_sec=0,
    )
    service = UnofficialParticipationExecutionService(
        settings,
        engine,
        object(),
        transport_factory=lambda: transport,
        comment_generator=generator,
    )
    plan, _ = _plan()
    requirements = ParticipationRequirements(
        required_topics=("#夏日活动#",),
        required_mention_count=2,
        required_actions=("comment", "repost", "like", "follow"),
    )

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
        activity_text="转发并关注，参加 #夏日活动# 抽奖",
    )

    assert result["state"] == "completed"
    comment = str(transport.payloads[0]["commentText"])
    assert comment.startswith("这次活动很有诚意")
    assert "#夏日活动#" in comment
    assert "@你的抽奖工具人" in comment
    assert "@哔哩哔哩弹幕网" in comment
    assert generator.requests[0].activity_text == "转发并关注，参加 #夏日活动# 抽奖"
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        record = json.loads(run.stats_json)["unofficialParticipationWrites"][str(activity_id)]
        assert record["commentSource"] == "deepseek"
        assert record["requiredTopics"] == ["#夏日活动#"]
        assert record["mentionNames"] == ["@你的抽奖工具人", "@哔哩哔哩弹幕网"]


@pytest.mark.asyncio
async def test_deepseek_failure_stops_before_any_bilibili_write():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed(engine)
    transport = _Transport([])

    class _FailedGenerator:
        async def generate(self, _request: DeepSeekCommentRequest) -> str:
            from backend.integrations.deepseek import DeepSeekCommentGenerationError

            raise DeepSeekCommentGenerationError(
                "DEEPSEEK_HTTP_ERROR", "DeepSeek 请求失败（HTTP 401）"
            )

    service = UnofficialParticipationExecutionService(
        Settings(unofficial_automation_enabled=True),
        engine,
        object(),
        transport_factory=lambda: transport,
        comment_generator=_FailedGenerator(),
    )
    plan, requirements = _plan()

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        action_plan=plan,
        requirements=requirements,
        activity_text="动态正文",
    )

    assert result["state"] == "blocked_failed"
    assert result["resultCode"] == "DEEPSEEK_HTTP_ERROR"
    assert transport.calls == []
