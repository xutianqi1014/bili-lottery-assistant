"""Serial execution coordinator for confirmed runs."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from sqlalchemy.engine import Engine

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.models import ActivityMode
from backend.activity_engine.requirements import RequirementParser
from backend.activity_engine.runtime_inspection import RuntimeActivityReader
from backend.activity_engine.shared import ManualGate
from backend.activity_engine.source_policy import SourceActivityPolicy
from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.run import Run, RunItem
from backend.domain.json_utils import load_json_object as _load_json_object  # noqa: F401
from backend.jobs.events import EventHub
from backend.problems.registry import ProblemRegistry
from backend.use_cases.official_participation_execution import OfficialParticipationExecutionService
from backend.use_cases.run_execution_inspection import RunRuntimeInspector, source_activity_policy
from backend.use_cases.run_execution_outcomes import (
    DYNAMIC_UNAVAILABLE_SKIP_CODE,
    RuntimeOutcome,
    _activity_like_state_unknown_runtime_outcome,  # noqa: F401
    _already_liked_runtime_outcome,  # noqa: F401
    _inspection_payload,  # noqa: F401
    _item_state_for,  # noqa: F401
    _platform_status,  # noqa: F401
    _should_record_runtime_problem,
    _source_policy_blocked_outcome,
    failure_outcome,
)
from backend.use_cases.run_execution_state import (
    _LEGACY_PREWRITE_SECURITY_ACTIONS,  # noqa: F401
    RunExecutionStore,
    _clear_restartable_unofficial_write,  # noqa: F401
    _load_json_ints,  # noqa: F401
)
from backend.use_cases.source_closure import SourceClosureService
from backend.use_cases.source_like_automation import SourceLikeAutomationService
from backend.use_cases.unofficial_participation_execution import (
    UnofficialParticipationExecutionService,
)

_POLICY_CHECKABLE_ACTIVITY_MODES = frozenset(
    {
        ActivityMode.OFFICIAL.value,
        ActivityMode.UNOFFICIAL.value,
        ActivityMode.RESERVATION.value,
    }
)


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

    @property
    def _execution_store(self) -> RunExecutionStore:
        # Resolve current collaborators so existing replacement hooks remain live.
        return RunExecutionStore(self.engine, self.source_closure, self.problems)

    def queue(self, run_id: int, *, resume: bool = False) -> Run:
        return self._execution_store.queue(
            run_id,
            resume=resume,
            official_automation_enabled=self._official_automation_enabled,
            unofficial_automation_enabled=self._unofficial_automation_enabled,
            official_participation_service=self.official_participation_service,
            unofficial_service_available=self.unofficial_participation_service is not None,
        )

    def prepare_restart(self, run_id: int) -> Run:
        """Reset only the unresolved item after explicit manual repair."""
        return self._execution_store.prepare_restart(run_id)

    def rollback_queue(self, run_id: int, previous_state: str) -> None:
        self._execution_store.rollback_queue(run_id, previous_state)

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

                source_policy = self._source_activity_policy(run, item)
                if source_policy.configured:
                    should_continue = await self._execute_configured_automatic_item(
                        run, item, source_policy
                    )
                    if not should_continue:
                        return
                    automated_count += 1
                    if self._next_item(run_id) is not None:
                        processed_mode = self._read_item_mode(run_id, item.activity_id)
                        await asyncio.sleep(
                            self._next_unofficial_delay_seconds()
                            if processed_mode
                            in {ActivityMode.UNOFFICIAL.value, "interactive"}
                            else self._next_official_delay_seconds()
                        )
                    continue

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

    async def _publish_item_updated(
        self, run_id: int, item: RunItem, *, state: str,
        result_code: str, mode: str, platform_status: str,
    ) -> None:
        await self.events.publish(
            "run.item_updated",
            {
                "runId": run_id, "activityId": item.activity_id,
                "sequence": item.sequence, "state": state,
                "resultCode": result_code, "mode": mode,
                "platformStatus": platform_status,
            },
        )

    async def _publish_item_waiting(
        self, run_id: int, item: RunItem, *, state: str, reason: str | None,
    ) -> None:
        await self.events.publish(
            "run.waiting_user",
            {
                "runId": run_id, "state": state,
                "activityId": item.activity_id, "sequence": item.sequence,
                "reason": reason,
            },
        )

    async def _execute_automatic_official(
        self,
        run: Run,
        item: RunItem,
        *,
        source_policy_authorized: bool = False,
    ) -> bool:
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
            result = await service.execute(
                run_id,
                activity_id=item.activity_id,
                source_policy_authorized=source_policy_authorized,
            )
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
            await self._publish_item_waiting(
                run_id, item, state=waiting.state, reason=message,
            )
            return False

        self._refresh_source_closure(run_id)
        await self._publish_item_updated(
            run_id, item,
            state=result["state"],
            result_code=result["resultCode"],
            mode=(
                "reservation"
                if result["resultCode"] in {"ALREADY_RESERVED", "RESERVATION_CONFIRMED"}
                or str(result["resultCode"]).startswith("RESERVATION_")
                else "official"
            ),
            platform_status=result["resultState"],
        )
        if result["state"] == "completed":
            return True
        waiting = self._set_waiting(run_id, str(result["resultMessage"]))
        await self._publish_item_waiting(
            run_id, item, state=waiting.state, reason=result["resultMessage"],
        )
        return False

    async def _execute_configured_automatic_item(
        self,
        run: Run,
        item: RunItem,
        policy: SourceActivityPolicy,
    ) -> bool:
        """Classify a configured source before choosing its write service.

        A source's readlist family is only a discovery grouping.  The page
        itself decides whether the item is official, reservation, or
        non-official.  This preflight is only enabled for profiles that carry
        an explicit ``activityTypes`` allow-list, so legacy/unit-test runs
        retain their previous family-based automation path.
        """

        run_id = run.id or 0
        try:
            outcome = await self._inspect_item(run, item)
        except asyncio.CancelledError:
            self._mark_item_waiting(
                run_id,
                item.activity_id,
                "EXECUTION_INTERRUPTED",
                "运行被中断；恢复前必须人工复核当前动态。",
            )
            self._set_interrupted(run_id)
            raise
        except Exception as exc:
            outcome = self._failure_outcome(exc)

        if (
            outcome.item_state != "skipped"
            and outcome.result_code != DYNAMIC_UNAVAILABLE_SKIP_CODE
            # ``unknown`` means that runtime evidence is insufficient (for
            # example, the like control has not hydrated yet), not that the
            # page is a fourth activity type.  Preserve that safety result
            # instead of rewriting it as a source-policy mismatch.
            and outcome.mode in _POLICY_CHECKABLE_ACTIVITY_MODES
            and outcome.mode not in {mode.value for mode in policy.allowed_modes}
        ):
            # _inspect_item normally creates this result itself.  This guard
            # protects against a future classifier branch that forgets to
            # consult the source policy.
            if outcome.result_code != "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED":
                outcome = _source_policy_blocked_outcome(outcome, policy)

        if outcome.item_state == "skipped":
            self._persist_outcome(run, item, outcome)
            self._refresh_source_closure(run_id)
            await self._publish_item_updated(
                run_id, item,
                state=outcome.item_state,
                result_code=outcome.result_code,
                mode=outcome.mode,
                platform_status=outcome.platform_status,
            )
            return True

        if outcome.mode == ActivityMode.UNOFFICIAL.value:
            if (
                self._unofficial_automation_enabled
                and self.unofficial_participation_service is not None
                and outcome.unofficial_action_plan is not None
                and outcome.requirements is not None
                and outcome.item_state == "waiting_user"
            ):
                return await self._execute_automatic_unofficial(
                    run,
                    item,
                    preflight=outcome,
                    source_policy_authorized=True,
                )
            return await self._persist_automatic_block(run, item, outcome)

        if outcome.mode in {
            ActivityMode.OFFICIAL.value,
            ActivityMode.RESERVATION.value,
        }:
            if not self._official_automation_enabled:
                return await self._persist_automatic_block(run, item, outcome)
            # Persist the classifier result before the official writer checks
            # its target.  This also permits an official dynamic discovered in
            # a non-official readlist family when the source policy authorizes
            # both types.
            self._persist_outcome(run, item, outcome, preserve_running=True)
            return await self._execute_automatic_official(
                run,
                item,
                source_policy_authorized=True,
            )

        return await self._persist_automatic_block(run, item, outcome)

    async def _persist_automatic_block(
        self,
        run: Run,
        item: RunItem,
        outcome: RuntimeOutcome,
    ) -> bool:
        run_id = run.id or 0
        self._persist_outcome(run, item, outcome)
        await self._publish_item_updated(
            run_id, item,
            state=outcome.item_state,
            result_code=outcome.result_code,
            mode=outcome.mode,
            platform_status=outcome.platform_status,
        )
        if outcome.item_state == "waiting_user":
            self._record_runtime_problem(run, item, outcome.result_code, outcome.result_message)
            waiting = self._set_waiting(run_id, outcome.result_message)
            await self._publish_item_waiting(
                run_id, item, state=waiting.state, reason=outcome.result_message,
            )
            return False
        return True

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

    async def _execute_automatic_unofficial(
        self,
        run: Run,
        item: RunItem,
        *,
        preflight: RuntimeOutcome | None = None,
        source_policy_authorized: bool = False,
    ) -> bool:
        """Inspect one non-official dynamic, then run its confirmed action plan."""

        run_id = run.id or 0
        service = self.unofficial_participation_service
        if service is None:
            return False
        try:
            outcome = preflight or await self._inspect_item(run, item)
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
            await self._publish_item_updated(
                run_id, item,
                state=outcome.item_state,
                result_code=outcome.result_code,
                mode=outcome.mode,
                platform_status=outcome.platform_status,
            )
            if outcome.item_state in {"waiting_user", "running"}:
                waiting = self._set_waiting(run_id, outcome.result_message)
                await self._publish_item_waiting(
                    run_id, item, state=waiting.state, reason=outcome.result_message,
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
                source_policy_authorized=source_policy_authorized,
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
            await self._publish_item_waiting(
                run_id, item, state=waiting.state, reason=message,
            )
            return False

        self._refresh_source_closure(run_id)
        await self._publish_item_updated(
            run_id, item,
            state=result["state"],
            result_code=result["resultCode"],
            mode="unofficial",
            platform_status="participated"
            if result["state"] == "completed"
            else "manual_review",
        )
        if result["state"] in {"completed", "skipped"}:
            return True
        waiting = self._set_waiting(run_id, str(result["resultMessage"]))
        await self._publish_item_waiting(
            run_id, item, state=waiting.state, reason=result["resultMessage"],
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
        await self._publish_item_updated(
            run_id, item,
            state=outcome.item_state,
            result_code=outcome.result_code,
            mode=outcome.mode,
            platform_status=outcome.platform_status,
        )
        if outcome.item_state in {"waiting_user", "running"}:
            waiting = self._set_waiting(run_id, outcome.result_message)
            await self._publish_item_waiting(
                run_id, item, state=waiting.state, reason=outcome.result_message,
            )
            return

        if self._next_item(run_id) is not None:
            waiting = self._set_waiting(
                run_id,
                "当前条目已得到安全终态；点击继续后才会打开下一条动态。",
            )
            await self._publish_item_waiting(
                run_id, item, state=waiting.state, reason=waiting.status_detail,
            )
            return

        finished = self._finish(
            run_id,
            "所有条目均已得到安全终态；未执行外部写操作。",
        )
        await self._publish_finished(finished)

    async def _inspect_item(self, run: Run, item: RunItem) -> RuntimeOutcome:
        inspector = RunRuntimeInspector(
            self.browser, self.reader, self.classifier, self.requirements, self.gate
        )
        return await inspector.inspect(
            run,
            item,
            next_unofficial_delay=self._next_unofficial_delay_seconds,
            policy_for=self._source_activity_policy,
        )

    def _source_activity_policy(self, run: Run, item: RunItem) -> SourceActivityPolicy:
        return source_activity_policy(self.engine, run, item)

    def _failure_outcome(self, exc: Exception) -> RuntimeOutcome:
        return failure_outcome(exc)

    def _set_running(self, run_id: int) -> Run:
        return self._execution_store.set_running(run_id)

    def _next_item(self, run_id: int) -> RunItem | None:
        return self._execution_store.next_item(run_id)

    def _read_item_mode(self, run_id: int, activity_id: int) -> str:
        return self._execution_store.read_item_mode(run_id, activity_id)

    def _mark_item_running(self, run_id: int, activity_id: int) -> None:
        self._execution_store.mark_item_running(run_id, activity_id)

    def _mark_item_waiting(self, run_id: int, activity_id: int, code: str, message: str) -> None:
        self._execution_store.mark_item_waiting(run_id, activity_id, code, message)

    def _persist_outcome(
        self,
        run: Run,
        item: RunItem,
        outcome: RuntimeOutcome,
        *,
        preserve_running: bool = False,
    ) -> None:
        self._execution_store.persist_outcome(run, item, outcome, preserve_running=preserve_running)

    def get_source_closure(self, run_id: int) -> dict[str, Any]:
        return self._execution_store.get_source_closure(run_id)

    def _refresh_source_closure(self, run_id: int) -> None:
        self._execution_store.refresh_source_closure(run_id)

    def _record_runtime_problem(self, run: Run, item: RunItem, code: str, message: str) -> None:
        self._execution_store.record_runtime_problem(run, item, code, message)

    def _set_waiting(self, run_id: int, detail: str | None) -> Run:
        return self._execution_store.set_waiting(run_id, detail)

    def _finish(self, run_id: int, detail: str) -> Run:
        return self._execution_store.finish(run_id, detail)

    def _set_failed(self, run_id: int, detail: str) -> Run:
        return self._execution_store.set_failed(run_id, detail)

    def _set_interrupted(self, run_id: int, detail: str | None = None) -> Run:
        return self._execution_store.set_interrupted(run_id, detail)

    async def _publish_finished(self, run: Run) -> None:
        await self.events.publish(
            "run.finished",
            {"runId": run.id, "state": run.state, "discoveryId": run.discovery_run_id},
        )
