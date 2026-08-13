"""Execute a confirmed run in its configured read-only or official-auto mode."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import select

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.models import (
    ActionResult,
    ActionState,
    ActivityMode,
    ParticipationRequirements,
)
from backend.activity_engine.official import OfficialFlow
from backend.activity_engine.requirements import RequirementParser
from backend.activity_engine.runtime_inspection import RuntimeActivityRead, RuntimeActivityReader
from backend.activity_engine.shared import ManualGate
from backend.activity_engine.unofficial import (
    ActionCheckpointLedger,
    UnofficialActionPlan,
    UnofficialFlow,
)
from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.activity import Activity
from backend.db.models.run import Run, RunItem
from backend.db.repositories import runs
from backend.jobs.events import EventHub
from backend.problems.registry import ProblemRegistry
from backend.use_cases.official_participation_execution import (
    OfficialParticipationExecutionService,
)
from backend.use_cases.run_stats import reconcile_run_item_stats
from backend.use_cases.source_closure import SourceClosureService
from backend.use_cases.source_like_automation import SourceLikeAutomationService
from backend.use_cases.unofficial_participation_execution import (
    UnofficialParticipationExecutionService,
)


@dataclass(frozen=True)
class RuntimeOutcome:
    item_state: str
    mode: str
    unofficial_type: str
    platform_status: str
    result_code: str
    result_message: str
    block_reason: str | None
    inspection: dict[str, Any]
    selector_version: str
    inspected_at: datetime
    requirements: ParticipationRequirements | None = None
    unofficial_action_plan: UnofficialActionPlan | None = None
    comment_context: str = ""


class RunExecutionService:
    """Run a confirmed plan with a single current browser page.

    Read-only mode inspects at most one item and pauses.  Official automation
    mode processes the immutable confirmed run sequentially with a delay
    between items and stops on the first uncertain or failed result.
    """

    def __init__(
        self,
        engine: Engine,
        browser: BrowserManager,
        events: EventHub,
        *,
        settings: Settings | None = None,
        official_participation_service: OfficialParticipationExecutionService | None = None,
        source_like_automation_service: SourceLikeAutomationService | None = None,
        unofficial_participation_service: UnofficialParticipationExecutionService | None = None,
    ) -> None:
        self.engine = engine
        self.browser = browser
        self.events = events
        # Direct construction without application settings remains read-only.
        self.settings = settings or Settings(official_automation_enabled=False)
        self.official_participation_service = official_participation_service
        self.source_like_automation_service = source_like_automation_service
        self.unofficial_participation_service = unofficial_participation_service
        self.reader = RuntimeActivityReader()
        self.classifier = ActivityClassifier()
        self.requirements = RequirementParser()
        self.gate = ManualGate(direct_write_enabled=False)
        self.problems = ProblemRegistry(engine)
        self.source_closure = SourceClosureService(engine)

    def queue(self, run_id: int, *, resume: bool = False) -> Run:
        allowed = ("waiting_user", "interrupted") if resume else ("confirmed_waiting_user",)
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            if run.direct_write_enabled_snapshot:
                raise ValueError("DIRECT_WRITE_NOT_IMPLEMENTED")
            if run.state not in allowed:
                raise ValueError("RUN_NOT_STARTABLE" if not resume else "RUN_NOT_RESUMABLE")
            stats = _load_json_object(run.stats_json)
            if bool(stats.get("requiresManualReview")):
                raise ValueError("RUN_HAS_BLOCKED_ITEMS")
            has_pending_official = bool(
                session.exec(
                    select(RunItem.activity_id).where(
                        RunItem.run_id == run_id,
                        RunItem.family == "official",
                        RunItem.__table__.c.state.in_(  # type: ignore[attr-defined]
                            ["planned", "running", "waiting_user"]
                        ),
                    )
                ).first()
            )
            if self._official_automation_enabled and has_pending_official:
                if self.official_participation_service is None:
                    raise ValueError("OFFICIAL_PARTICIPATION_AUTOMATION_SERVICE_MISSING")
                self.official_participation_service.validate_run_scope(run_id)
                next_detail = "已进入执行队列；官方目标将自动处理，非官方目标按当前策略检查。"
            elif (
                self._unofficial_automation_enabled
                and self.unofficial_participation_service is not None
            ):
                next_detail = "non-official actions will run automatically after runtime checks"
            elif self._official_automation_enabled:
                next_detail = "已进入非官方执行队列；将打开当前一条并生成可审查动作策略。"
            else:
                next_detail = "已进入队列，等待逐条运行时检查。"
            return runs.set_run_state(
                session,
                run,
                expected=allowed,
                next_state="queued",
                status_detail=next_detail,
            )

    def rollback_queue(self, run_id: int, previous_state: str) -> None:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None or run.state != "queued":
                return
            runs.set_run_state(
                session,
                run,
                expected="queued",
                next_state=previous_state,
                status_detail=None,
            )

    async def execute(self, run_id: int) -> None:
        run = self._set_running(run_id)
        assert run.id is not None
        await self.events.publish(
            "run.started",
            {"runId": run_id, "state": run.state, "discoveryId": run.discovery_run_id},
        )
        try:
            automated_count = 0
            while True:
                item = self._next_item(run_id)
                if item is None:
                    self._refresh_source_closure(run_id)
                    if self._official_automation_enabled:
                        can_finish, closure_detail = await self._execute_automatic_source_closure(
                            run_id
                        )
                        if not can_finish:
                            return
                        detail = f"官方自动执行完成，共处理 {automated_count} 条；{closure_detail}"
                    else:
                        detail = "没有待处理条目，运行已完成。"
                    finished = self._finish(run_id, detail)
                    await self._publish_finished(finished)
                    return

                self._mark_item_running(run_id, item.activity_id)
                await self.events.publish(
                    "run.item_started",
                    {
                        "runId": run_id,
                        "activityId": item.activity_id,
                        "sequence": item.sequence,
                        "dynamicId": item.dynamic_id,
                    },
                )

                if self._official_automation_enabled and item.family == "official":
                    should_continue = await self._execute_automatic_official(run, item)
                    if not should_continue:
                        return
                    automated_count += 1
                    if self._next_item(run_id) is not None:
                        await asyncio.sleep(self._next_official_delay_seconds())
                    continue

                if (
                    self._unofficial_automation_enabled
                    and item.family != "official"
                    and self.unofficial_participation_service is not None
                ):
                    should_continue = await self._execute_automatic_unofficial(run, item)
                    if not should_continue:
                        return
                    automated_count += 1
                    if self._next_item(run_id) is not None:
                        await asyncio.sleep(self._next_unofficial_delay_seconds())
                    continue

                await self._execute_read_only_item(run, item)
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed = self._set_failed(run_id, f"运行失败，需要人工复核：{type(exc).__name__}")
            await self.events.publish(
                "run.failed",
                {"runId": run_id, "state": failed.state, "error": type(exc).__name__},
            )

    @property
    def _official_automation_enabled(self) -> bool:
        return self.settings.official_automation_enabled

    def _next_official_delay_seconds(self) -> float:
        minimum = max(0.0, self.settings.official_automation_delay_min_sec)
        maximum = max(minimum, self.settings.official_automation_delay_max_sec)
        return random.uniform(minimum, maximum)

    @property
    def _unofficial_automation_enabled(self) -> bool:
        return self.settings.unofficial_automation_enabled

    def _next_unofficial_delay_seconds(self) -> float:
        minimum = max(0.0, self.settings.unofficial_automation_delay_min_sec)
        maximum = max(minimum, self.settings.unofficial_automation_delay_max_sec)
        return random.uniform(minimum, maximum)

    async def _execute_automatic_official(self, run: Run, item: RunItem) -> bool:
        service = self.official_participation_service
        run_id = run.id or 0
        if service is None:
            message = "官方自动执行服务未就绪，已停止且未重试。"
            self._mark_item_waiting(
                run_id,
                item.activity_id,
                "OFFICIAL_PARTICIPATION_AUTOMATION_SERVICE_MISSING",
                message,
            )
            self._set_waiting(run_id, message)
            return False
        try:
            result = await service.execute(run_id, activity_id=item.activity_id)
        except asyncio.CancelledError:
            self._mark_item_waiting(
                run_id,
                item.activity_id,
                "EXECUTION_INTERRUPTED",
                "官方自动执行被中断；恢复前必须人工复核当前动态。",
            )
            self._set_interrupted(run_id)
            raise
        except Exception as exc:  # policy/configuration failures occur before clicking
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            message = f"官方自动执行在写入前被安全策略阻止：{code}"
            self._mark_item_waiting(run_id, item.activity_id, code, message)
            self._record_runtime_problem(run, item, code, message)
            self._refresh_source_closure(run_id)
            waiting = self._set_waiting(run_id, message)
            await self.events.publish(
                "run.waiting_user",
                {
                    "runId": run_id,
                    "state": waiting.state,
                    "activityId": item.activity_id,
                    "sequence": item.sequence,
                    "reason": message,
                },
            )
            return False

        self._refresh_source_closure(run_id)
        await self.events.publish(
            "run.item_updated",
            {
                "runId": run_id,
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "state": result["state"],
                "resultCode": result["resultCode"],
                "mode": "official",
                "platformStatus": result["resultState"],
            },
        )
        if result["state"] == "completed":
            return True
        waiting = self._set_waiting(run_id, str(result["resultMessage"]))
        await self.events.publish(
            "run.waiting_user",
            {
                "runId": run_id,
                "state": waiting.state,
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "reason": result["resultMessage"],
            },
        )
        return False

    async def _execute_automatic_source_closure(self, run_id: int) -> tuple[bool, str]:
        """Run source-article closure after every activity has a safe terminal state."""

        summary = self.source_closure.get(run_id)
        service = self.source_like_automation_service
        if service is None:
            if summary.ready_to_mark_count == 0:
                if summary.blocked_count:
                    return True, "存在问题或未满足条件的来源专栏，本轮未点赞来源"
                return True, "来源专栏均已点赞或本轮没有来源目标"
            with open_session(self.engine) as session:
                run = session.get(Run, run_id)
                if run is None:
                    raise ValueError("RUN_NOT_FOUND")
                discovery_run_id = run.discovery_run_id
            message = "来源专栏自动收尾服务未就绪，未执行点赞"
            for row in summary.rows:
                if not row.ready_to_mark:
                    continue
                self.problems.record(
                    discovery_run_id=discovery_run_id,
                    source_article_id=row.source_article_id,
                    problem_url=row.url,
                    page_type="source_article",
                    stage="source_like_automation",
                    problem_code="SOURCE_LIKE_AUTOMATION_SERVICE_MISSING",
                    safe_detail=message,
                )
            self._refresh_source_closure(run_id)
            waiting = self._set_waiting(run_id, message)
            await self.events.publish(
                "run.waiting_user",
                {
                    "runId": run_id,
                    "state": waiting.state,
                    "reason": message,
                    "resultCode": "SOURCE_LIKE_AUTOMATION_SERVICE_MISSING",
                },
            )
            return False, message

        await self.events.publish(
            "run.source_closure_started",
            {
                "runId": run_id,
                "targetCount": summary.ready_to_mark_count,
            },
        )
        try:
            result = await service.execute_ready(run_id)
        except asyncio.CancelledError:
            interrupted = self._set_interrupted(
                run_id,
                "来源专栏自动收尾被中断；外部结果可能未知，恢复时禁止自动重试未确认目标。",
            )
            await self.events.publish(
                "run.interrupted",
                {
                    "runId": run_id,
                    "state": interrupted.state,
                    "reason": interrupted.status_detail,
                },
            )
            raise
        self._refresh_source_closure(run_id)
        await self.events.publish(
            "run.source_closure_updated",
            {"runId": run_id, **result.to_payload()},
        )
        if not result.blocks_run:
            return True, result.result_message

        waiting = self._set_waiting(run_id, result.result_message)
        await self.events.publish(
            "run.waiting_user",
            {
                "runId": run_id,
                "state": waiting.state,
                "reason": result.result_message,
                "resultCode": result.result_code,
            },
        )
        return False, result.result_message

    async def _execute_automatic_unofficial(self, run: Run, item: RunItem) -> bool:
        """Inspect one non-official dynamic, then run its confirmed action plan."""

        run_id = run.id or 0
        service = self.unofficial_participation_service
        if service is None:
            return False
        try:
            outcome = await self._inspect_item(run, item)
        except asyncio.CancelledError:
            self._mark_item_waiting(
                run_id,
                item.activity_id,
                "EXECUTION_INTERRUPTED",
                "run was interrupted; inspect the current dynamic before resuming",
            )
            self._set_interrupted(run_id)
            raise
        except Exception as exc:
            outcome = self._failure_outcome(exc)

        eligible = (
            outcome.mode == ActivityMode.UNOFFICIAL.value
            and outcome.item_state == "waiting_user"
            and outcome.unofficial_action_plan is not None
            and outcome.requirements is not None
        )
        if not eligible:
            self._persist_outcome(run, item, outcome)
            if outcome.item_state == "waiting_user":
                self._record_runtime_problem(run, item, outcome.result_code, outcome.result_message)
            self._refresh_source_closure(run_id)
            await self.events.publish(
                "run.item_updated",
                {
                    "runId": run_id,
                    "activityId": item.activity_id,
                    "sequence": item.sequence,
                    "state": outcome.item_state,
                    "resultCode": outcome.result_code,
                    "mode": outcome.mode,
                    "platformStatus": outcome.platform_status,
                },
            )
            if outcome.item_state in {"waiting_user", "running"}:
                waiting = self._set_waiting(run_id, outcome.result_message)
                await self.events.publish(
                    "run.waiting_user",
                    {
                        "runId": run_id,
                        "state": waiting.state,
                        "activityId": item.activity_id,
                        "sequence": item.sequence,
                        "reason": outcome.result_message,
                    },
                )
                return False
            return True

        assert outcome.unofficial_action_plan is not None
        assert outcome.requirements is not None
        # Keep the item running while the write service creates its durable
        # running marker.  This prevents a crash between inspection and the
        # first click from being mistaken for a clean terminal result.
        self._persist_outcome(run, item, outcome, preserve_running=True)
        try:
            result = await service.execute(
                run_id,
                activity_id=item.activity_id,
                action_plan=outcome.unofficial_action_plan,
                requirements=outcome.requirements,
                activity_text=outcome.comment_context,
            )
        except asyncio.CancelledError:
            interrupted = self._set_interrupted(
                run_id,
                (
                    "non-official write was interrupted; external state is unknown "
                    "and automatic retry is disabled"
                ),
            )
            await self.events.publish(
                "run.interrupted",
                {"runId": run_id, "state": interrupted.state, "reason": interrupted.status_detail},
            )
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            message = f"non-official automatic execution was stopped before continuation: {code}"
            self._mark_item_waiting(run_id, item.activity_id, code, message)
            self._record_runtime_problem(run, item, code, message)
            waiting = self._set_waiting(run_id, message)
            await self.events.publish(
                "run.waiting_user",
                {
                    "runId": run_id,
                    "state": waiting.state,
                    "activityId": item.activity_id,
                    "sequence": item.sequence,
                    "reason": message,
                },
            )
            return False

        self._refresh_source_closure(run_id)
        await self.events.publish(
            "run.item_updated",
            {
                "runId": run_id,
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "state": result["state"],
                "resultCode": result["resultCode"],
                "mode": "unofficial",
                "platformStatus": "participated"
                if result["state"] == "completed"
                else "manual_review",
            },
        )
        if result["state"] in {"completed", "skipped"}:
            return True
        waiting = self._set_waiting(run_id, str(result["resultMessage"]))
        await self.events.publish(
            "run.waiting_user",
            {
                "runId": run_id,
                "state": waiting.state,
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "reason": result["resultMessage"],
            },
        )
        return False

    async def _execute_read_only_item(self, run: Run, item: RunItem) -> None:
        run_id = run.id or 0
        try:
            outcome = await self._inspect_item(run, item)
        except asyncio.CancelledError:
            self._mark_item_waiting(
                run_id,
                item.activity_id,
                "EXECUTION_INTERRUPTED",
                "运行被中断；恢复前请人工复查当前动态是否发生变化。",
            )
            self._set_interrupted(run_id)
            raise
        except Exception as exc:
            outcome = self._failure_outcome(exc)

        self._persist_outcome(run, item, outcome)
        if _should_record_runtime_problem(outcome.result_code):
            self._record_runtime_problem(run, item, outcome.result_code, outcome.result_message)
        self._refresh_source_closure(run_id)
        await self.events.publish(
            "run.item_updated",
            {
                "runId": run_id,
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "state": outcome.item_state,
                "resultCode": outcome.result_code,
                "mode": outcome.mode,
                "platformStatus": outcome.platform_status,
            },
        )
        if outcome.item_state in {"waiting_user", "running"}:
            waiting = self._set_waiting(run_id, outcome.result_message)
            await self.events.publish(
                "run.waiting_user",
                {
                    "runId": run_id,
                    "state": waiting.state,
                    "activityId": item.activity_id,
                    "sequence": item.sequence,
                    "reason": outcome.result_message,
                },
            )
            return

        if self._next_item(run_id) is not None:
            waiting = self._set_waiting(
                run_id,
                "当前条目已得到安全终态；点击继续后才会打开下一条动态。",
            )
            await self.events.publish(
                "run.waiting_user",
                {
                    "runId": run_id,
                    "state": waiting.state,
                    "activityId": item.activity_id,
                    "sequence": item.sequence,
                    "reason": waiting.status_detail,
                },
            )
            return

        finished = self._finish(
            run_id,
            "所有条目均已得到安全终态；未执行外部写操作。",
        )
        await self._publish_finished(finished)

    async def _inspect_item(self, run: Run, item: RunItem) -> RuntimeOutcome:
        # Non-official dynamics receive a short visible-page settling window
        # immediately after navigation and before the first scoped read.  The
        # same configured 1–2 second range is used for both automated and
        # read-only execution; official dynamics keep their existing timing.
        post_open_delay = (
            self._next_unofficial_delay_seconds() if item.family != "official" else 0.0
        )
        read = await self.reader.read(
            self.browser,
            item.dynamic_id,
            item.canonical_url,
            post_open_delay_sec=post_open_delay,
        )
        classification = self.classifier.classify(read.snapshot)
        # Non-official pages expose a scoped outer body separately from the
        # full visible page.  The full body also contains the comment tab,
        # like/repost counts and other users' text; parsing it can fabricate a
        # comment instruction such as "评论 2276 ...".  Always parse the
        # reader's actionable text so only the current dynamic's own
        # participation requirements reach the write planner.
        requirements = self.requirements.parse(read.snapshot.actionable_text)
        inspection = _inspection_payload(read, classification, requirements)
        action_plan: UnofficialActionPlan | None = None

        if classification.mode is ActivityMode.UNKNOWN:
            result = ActionResult(
                ActionState.WAITING_USER,
                "CLASSIFICATION_UNKNOWN",
                "动态页面未能稳定识别为官方或非官方抽奖，需要人工复核。",
                True,
            )
        else:
            expected_mode = (
                ActivityMode.OFFICIAL if item.family == "official" else ActivityMode.UNOFFICIAL
            )
            if expected_mode is ActivityMode.OFFICIAL:
                result = await OfficialFlow(self.gate).prepare(read.snapshot, classification)
            else:
                unofficial_flow = UnofficialFlow(self.gate)
                action_plan = unofficial_flow.action_plan(classification, requirements)
                inspection["unofficialActionPlan"] = action_plan.to_payload()
                inspection["unofficialCheckpoints"] = ActionCheckpointLedger(
                    action_plan.actions
                ).to_payload()
                result = await unofficial_flow.prepare(read.snapshot, classification)

        inspection["resultCode"] = result.code
        inspection["resultMessage"] = result.message
        item_state = _item_state_for(result.state)
        return RuntimeOutcome(
            item_state=item_state,
            mode=classification.mode.value,
            unofficial_type=classification.unofficial_type.value,
            platform_status=_platform_status(classification.mode, result.state, result.code),
            result_code=result.code,
            result_message=result.message,
            block_reason=result.message if item_state == "waiting_user" else None,
            inspection=inspection,
            selector_version=(
                read.nonofficial_selector_version
                if classification.mode is ActivityMode.UNOFFICIAL
                else read.selector_version
            ),
            inspected_at=datetime.now(UTC),
            requirements=requirements,
            unofficial_action_plan=action_plan,
            comment_context=read.snapshot.actionable_text,
        )

    def _failure_outcome(self, exc: Exception) -> RuntimeOutcome:
        code = f"RUNTIME_INSPECTION_{type(exc).__name__.upper()}"
        message = "动态页面即时读取失败，需要人工复核；本轮不会自动重试写操作。"
        return RuntimeOutcome(
            item_state="waiting_user",
            mode="unknown",
            unofficial_type="unknown",
            platform_status="manual_review",
            result_code=code,
            result_message=message,
            block_reason=message,
            inspection={"errorType": type(exc).__name__, "resultCode": code},
            selector_version="runtime-inspection-error",
            inspected_at=datetime.now(UTC),
            comment_context="",
        )

    def _set_running(self, run_id: int) -> Run:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return runs.set_run_state(
                session,
                run,
                expected="queued",
                next_state="running",
                status_detail="正在打开当前条目并进行即时检查。",
            )

    def _next_item(self, run_id: int) -> RunItem | None:
        with open_session(self.engine) as session:
            return session.exec(
                select(RunItem)
                .where(
                    RunItem.run_id == run_id,
                    RunItem.__table__.c.state.in_(  # type: ignore[attr-defined]
                        ["planned", "waiting_user", "running"]
                    ),
                )
                .order_by(RunItem.__table__.c.sequence)  # type: ignore[attr-defined]
            ).first()

    def _mark_item_running(self, run_id: int, activity_id: int) -> None:
        with open_session(self.engine) as session:
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            item.state = "running"
            item.block_reason = None
            session.add(item)
            session.commit()

    def _mark_item_waiting(self, run_id: int, activity_id: int, code: str, message: str) -> None:
        with open_session(self.engine) as session:
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                return
            item.state = "waiting_user"
            item.result_code = code
            item.result_message = message
            item.block_reason = message
            session.add(item)
            session.flush()
            run = session.get(Run, run_id)
            if run is not None:
                items = list(
                    session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
                )
                run.stats_json = json.dumps(
                    {
                        **reconcile_run_item_stats(
                            _load_json_object(run.stats_json), items
                        ),
                        "requiresManualReview": True,
                    },
                    ensure_ascii=False,
                )
                session.add(run)
            session.commit()

    def _persist_outcome(
        self,
        run: Run,
        item: RunItem,
        outcome: RuntimeOutcome,
        *,
        preserve_running: bool = False,
    ) -> None:
        with open_session(self.engine) as session:
            db_item = session.get(RunItem, (run.id, item.activity_id))
            if db_item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            db_item.mode = outcome.mode
            db_item.unofficial_type = outcome.unofficial_type
            db_item.platform_status = outcome.platform_status
            db_item.runtime_inspected_at = outcome.inspected_at
            db_item.runtime_selector_version = outcome.selector_version
            db_item.runtime_inspection_json = json.dumps(outcome.inspection, ensure_ascii=False)
            db_item.state = "running" if preserve_running else outcome.item_state
            db_item.result_code = outcome.result_code
            db_item.result_message = outcome.result_message
            db_item.block_reason = outcome.block_reason

            activity = session.get(Activity, item.activity_id)
            if activity is not None:
                activity.mode_detected = outcome.mode
                activity.unofficial_type = outcome.unofficial_type
                activity.platform_status = outcome.platform_status
                activity.classification_json = json.dumps(outcome.inspection, ensure_ascii=False)
                activity.runtime_inspected_at = outcome.inspected_at
                activity.runtime_selector_version = outcome.selector_version
                body_excerpt = outcome.inspection.get("bodyExcerpt")
                if isinstance(body_excerpt, str):
                    activity.body_excerpt = body_excerpt[:2000]
                session.add(activity)
            session.add(db_item)
            run_row = session.get(Run, run.id)
            if run_row is not None:
                run_stats = _load_json_object(run_row.stats_json)
                run_items = list(
                    session.exec(select(RunItem).where(RunItem.run_id == run.id)).all()
                )
                run_stats["sourceClosure"] = self.source_closure.calculate(
                    session, run_row
                ).to_payload()
                run_stats = reconcile_run_item_stats(run_stats, run_items)
                run_stats["lastRuntimeResult"] = outcome.result_code
                run_row.stats_json = json.dumps(run_stats, ensure_ascii=False)
                session.add(run_row)
            session.commit()

    def get_source_closure(self, run_id: int) -> dict[str, Any]:
        return self.source_closure.get(run_id).to_payload()

    def _refresh_source_closure(self, run_id: int) -> None:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_json_object(run.stats_json)
            items = list(session.exec(select(RunItem).where(RunItem.run_id == run_id)).all())
            stats = reconcile_run_item_stats(stats, items)
            stats["sourceClosure"] = self.source_closure.calculate(session, run).to_payload()
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()

    def _record_runtime_problem(self, run: Run, item: RunItem, code: str, message: str) -> None:
        for source_article_id in _load_json_ints(item.source_article_ids_json):
            self.problems.record(
                discovery_run_id=run.discovery_run_id,
                source_article_id=source_article_id,
                problem_url=item.canonical_url,
                page_type="activity",
                stage="runtime_inspection",
                problem_code=code,
                safe_detail=message,
            )

    def _set_waiting(self, run_id: int, detail: str | None) -> Run:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return runs.set_run_state(
                session,
                run,
                expected="running",
                next_state="waiting_user",
                status_detail=detail,
            )

    def _finish(self, run_id: int, detail: str) -> Run:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return runs.set_run_state(
                session,
                run,
                expected="running",
                next_state="completed",
                status_detail=detail,
            )

    def _set_failed(self, run_id: int, detail: str) -> Run:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            if run.state not in {"running", "queued"}:
                return run
            return runs.set_run_state(
                session,
                run,
                expected=("running", "queued"),
                next_state="failed",
                status_detail=detail,
            )

    def _set_interrupted(self, run_id: int, detail: str | None = None) -> Run:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return runs.set_run_state(
                session,
                run,
                expected=("running", "queued"),
                next_state="interrupted",
                status_detail=detail or "运行被中断；恢复前请人工复查当前条目。",
            )

    async def _publish_finished(self, run: Run) -> None:
        await self.events.publish(
            "run.finished",
            {"runId": run.id, "state": run.state, "discoveryId": run.discovery_run_id},
        )


def _inspection_payload(
    read: RuntimeActivityRead,
    classification: Any,
    requirements: Any,
) -> dict[str, Any]:
    return {
        "pageTitle": read.page_title,
        "bodyExcerpt": read.body_excerpt,
        "mode": classification.mode.value,
        "unofficialType": classification.unofficial_type.value,
        "isExpired": classification.is_expired,
        "isParticipated": classification.is_participated,
        "confidence": classification.confidence,
        "evidenceCodes": list(classification.evidence_codes),
        "requiredTopics": list(requirements.required_topics),
        "requiredMentionCount": requirements.required_mention_count,
        "commentInstruction": requirements.comment_instruction,
        "requiredActions": list(requirements.required_actions),
        "mentionLimitExceeded": requirements.mention_limit_exceeded,
        "requirementEvidenceCodes": list(requirements.evidence_codes),
        "officialEntryOpened": read.lottery_entry_opened,
        "officialPanelSelector": read.lottery_panel_selector,
        "officialPanelText": read.lottery_panel_text,
        "officialPanelError": read.lottery_panel_error,
        "nonofficialOuterText": read.nonofficial_outer_text,
        "nonofficialForwardedOriginalText": read.nonofficial_forwarded_original_text,
        "nonofficialHasForwardedOriginal": read.nonofficial_has_forwarded_original,
        "nonofficialAuthorName": read.nonofficial_author_name,
        "nonofficialCommentEditorPresent": read.nonofficial_comment_editor_present,
        "nonofficialCommentPublishPresent": read.nonofficial_comment_publish_present,
        "nonofficialCommentRepostControlPresent": (read.nonofficial_comment_repost_control_present),
        "nonofficialEvidenceCodes": list(read.nonofficial_evidence_codes),
        "nonofficialSelectorVersion": read.nonofficial_selector_version,
    }


def _item_state_for(action_state: ActionState) -> str:
    if action_state in {
        ActionState.EXPIRED,
        ActionState.ALREADY_PARTICIPATED,
        ActionState.ALREADY_LIKED_SKIPPED,
    }:
        return "skipped"
    if action_state is ActionState.SUCCESS:
        return "completed"
    return "waiting_user"


def _platform_status(
    mode: ActivityMode,
    action_state: ActionState,
    result_code: str | None = None,
) -> str:
    if action_state is ActionState.EXPIRED:
        return "expired"
    if action_state is ActionState.ALREADY_PARTICIPATED:
        return "already_participated"
    if action_state is ActionState.ALREADY_LIKED_SKIPPED:
        return "already_liked"
    if (
        mode is ActivityMode.UNKNOWN
        or action_state is ActionState.MODE_MISMATCH
        or _should_record_runtime_problem(result_code or "")
    ):
        return "manual_review"
    return "eligible_waiting_user"


def _should_record_runtime_problem(result_code: str) -> bool:
    return result_code.startswith("RUNTIME_INSPECTION_") or result_code in {
        "CLASSIFICATION_UNKNOWN",
        "MODE_MISMATCH",
        "OFFICIAL_LOTTERY_ENTRY_CLICK_FAILED",
        "OFFICIAL_LOTTERY_PANEL_NOT_FOUND",
        "OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY",
    }


def _load_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_json_ints(value: str) -> list[int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, int)]
