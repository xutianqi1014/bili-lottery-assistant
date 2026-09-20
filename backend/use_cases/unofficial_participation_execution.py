"""Execute the confirmed non-official action plan through the DOM transport."""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from backend.activity_engine.models import ParticipationRequirements
from backend.activity_engine.unofficial import (
    ActionCheckpointLedger,
    UnofficialAction,
    UnofficialActionPlan,
    UnofficialWriteTransport,
    WriteOperationResult,
    WriteOutcomeState,
)
from backend.activity_engine.unofficial.transport import DomUnofficialTransport
from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.models.run import Run, RunItem
from backend.domain.json_utils import load_json_object as _load_object
from backend.integrations.deepseek import (
    DeepSeekCommentGenerationError,
    DeepSeekCommentRequest,
)
from backend.problems.registry import ProblemRegistry
from backend.use_cases.run_stats import reconcile_run_item_stats


class CommentGenerator(Protocol):
    async def generate(self, request: DeepSeekCommentRequest) -> str: ...


class UnofficialParticipationExecutionService:
    """Run non-official actions with DOM checkpoints and async comment acceptance."""

    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        browser: BrowserManager,
        *,
        transport_factory: Callable[[], UnofficialWriteTransport] | None = None,
        comment_generator: CommentGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.browser = browser
        self.transport_factory = transport_factory
        self.comment_generator = comment_generator
        self.problems = ProblemRegistry(engine)

    async def execute(
        self,
        run_id: int,
        *,
        activity_id: int,
        action_plan: UnofficialActionPlan,
        requirements: ParticipationRequirements,
        activity_text: str = "",
        source_policy_authorized: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.unofficial_automation_enabled:
            raise ValueError("UNOFFICIAL_PARTICIPATION_AUTOMATION_DISABLED")
        run, item = self._get_target(run_id, activity_id)
        if item.family == "official" and not source_policy_authorized:
            raise ValueError("UNOFFICIAL_PARTICIPATION_TARGET_IS_OFFICIAL")
        existing = self._existing_write(run, activity_id)
        if existing is not None:
            return self._reuse_or_reject(run_id, activity_id, existing)
        if item.state not in {"planned", "running"}:
            raise ValueError("UNOFFICIAL_PARTICIPATION_AUTOMATION_ITEM_NOT_READY")

        ledger = ActionCheckpointLedger(action_plan.actions)
        configured_names = self.settings.unofficial_mention_name_list
        mention_names = configured_names[: max(0, requirements.required_mention_count)]
        if requirements.mention_limit_exceeded:
            result = WriteOperationResult(
                WriteOutcomeState.FAILED,
                "COMMENT_MENTION_LIMIT_EXCEEDED",
                "动态要求的 @好友数量超过安全解析上限，未执行任何写操作",
            )
            return self._finish_blocked(
                run,
                item,
                ledger,
                result,
                plan=action_plan,
                comment_text="",
                activity_text=activity_text,
                requirements=requirements,
                mention_names=mention_names,
                stage="unofficial_participation_preflight",
            )
        if requirements.required_mention_count > len(configured_names):
            result = WriteOperationResult(
                WriteOutcomeState.FAILED,
                "COMMENT_MENTION_MAPPING_EXHAUSTED",
                (
                    f"动态要求 @{requirements.required_mention_count} 名好友，但当前仅安全配置 "
                    f"{len(configured_names)} 个固定账号"
                ),
            )
            return self._finish_blocked(
                run,
                item,
                ledger,
                result,
                plan=action_plan,
                comment_text="",
                activity_text=activity_text,
                requirements=requirements,
                mention_names=mention_names,
                stage="unofficial_participation_preflight",
            )

        # Direct service tests may omit the integration.  The application
        # always injects it, while this fallback keeps deterministic local
        # tests and migrations independent of a network key.
        if self.comment_generator is None and requirements.required_mention_count > 0:
            result = WriteOperationResult(
                WriteOutcomeState.FAILED,
                "COMMENT_MENTION_REQUIRED",
                "评论需要 @好友，但当前执行器未配置安全的固定账号映射",
            )
            return self._finish_blocked(
                run,
                item,
                ledger,
                result,
                plan=action_plan,
                comment_text="",
                activity_text=activity_text,
                requirements=requirements,
                mention_names=mention_names,
                stage="unofficial_participation_preflight",
            )

        comment_source = "configured_default"
        generated_comment = ""
        if self.comment_generator is not None:
            try:
                generated_comment = await self.comment_generator.generate(
                    DeepSeekCommentRequest(
                        activity_text=activity_text,
                        unofficial_type=(
                            action_plan.unofficial_type
                        ),
                        comment_instruction=requirements.comment_instruction,
                        required_topics=requirements.required_topics,
                        required_mention_count=requirements.required_mention_count,
                    )
                )
                comment_source = "deepseek"
            except DeepSeekCommentGenerationError as exc:
                result = WriteOperationResult(WriteOutcomeState.FAILED, exc.code, exc.message)
                return self._finish_blocked(
                    run,
                    item,
                    ledger,
                    result,
                    plan=action_plan,
                    comment_text="",
                    activity_text=activity_text,
                    requirements=requirements,
                    mention_names=mention_names,
                    stage="unofficial_participation_preflight",
                )
            except Exception as exc:  # noqa: BLE001 - no Bilibili write has occurred
                result = WriteOperationResult(
                    WriteOutcomeState.FAILED,
                    "DEEPSEEK_COMMENT_GENERATION_FAILED",
                    f"DeepSeek 评论生成失败（{type(exc).__name__}）",
                )
                return self._finish_blocked(
                    run,
                    item,
                    ledger,
                    result,
                    plan=action_plan,
                    comment_text="",
                    activity_text=activity_text,
                    requirements=requirements,
                    mention_names=mention_names,
                    stage="unofficial_participation_preflight",
                )

        comment_text = _compose_comment(
            self.settings,
            requirements,
            generated_comment=generated_comment,
            mention_names=mention_names,
        )
        if not comment_text:
            result = WriteOperationResult(
                WriteOutcomeState.FAILED,
                "COMMENT_TEXT_EMPTY",
                "未能生成安全评论文本，未执行任何写操作",
            )
            return self._finish_blocked(
                run,
                item,
                ledger,
                result,
                plan=action_plan,
                comment_text="",
                activity_text=activity_text,
                requirements=requirements,
                mention_names=mention_names,
                stage="unofficial_participation_preflight",
            )

        started_at = _now()
        record = self._record_payload(
            run,
            item,
            action_plan,
            ledger,
            comment_text=comment_text,
            activity_text=activity_text,
            requirements=requirements,
            mention_names=mention_names,
            comment_source=comment_source,
            started_at=started_at,
            state="running",
        )
        self._save_record(run_id, activity_id, record, item_state="running")

        transport = (
            self.transport_factory()
            if self.transport_factory is not None
            else DomUnofficialTransport(self.browser)
        )
        for index, action in enumerate(action_plan.actions):
            if ledger._get(action).state.value == "confirmed":  # side effect from comment checkbox
                continue
            payload: dict[str, object] = {
                "runId": run_id,
                "activityId": activity_id,
                "dynamicId": item.dynamic_id,
                "commentText": comment_text,
                "repostWithComment": (
                    action_plan.interaction_strategy == "comment_with_repost_checkbox"
                    and self.settings.unofficial_comment_repost_with_comment
                    and action is UnofficialAction.COMMENT
                ),
                "targetScope": action_plan.target_scope,
            }
            try:
                ledger.start(action)
                result = await transport.perform(
                    action,
                    target_url=item.canonical_url,
                    payload=payload,
                )
            except asyncio.CancelledError:
                unknown = WriteOperationResult(
                    WriteOutcomeState.UNKNOWN,
                    "UNOFFICIAL_PARTICIPATION_INTERRUPTED_UNKNOWN",
                    (
                        "run was interrupted after a write attempt; external state "
                        "must be checked manually"
                    ),
                )
                if ledger._get(action).state.value == "in_progress":
                    ledger.record(action, unknown)
                record = self._record_payload(
                    run,
                    item,
                    action_plan,
                    ledger,
                    comment_text=comment_text,
                    activity_text=activity_text,
                    requirements=requirements,
                    mention_names=mention_names,
                    comment_source=comment_source,
                    started_at=started_at,
                    state="blocked_unknown",
                    result=unknown,
                )
                self._save_record(run_id, activity_id, record, item_state="waiting_user")
                self._record_problem(run, item, unknown)
                raise
            except Exception as exc:  # transport exceptions are not safe to retry
                result = WriteOperationResult(
                    WriteOutcomeState.UNKNOWN,
                    "UNOFFICIAL_PARTICIPATION_EXECUTION_UNKNOWN",
                    f"write result is unknown ({type(exc).__name__})",
                )

            ledger.record(action, result)
            for confirmed_action in result.confirmed_actions:
                try:
                    side = UnofficialAction(confirmed_action)
                    if ledger._get(side).state.value == "pending":
                        ledger.start(side)
                        ledger.record(
                            side,
                            WriteOperationResult(
                                WriteOutcomeState.ALREADY_DONE,
                                f"{side.value.upper()}_CONFIRMED_BY_COMMENT",
                                "confirmed by the comment sync-to-dynamic terminal state",
                            ),
                        )
                except (ValueError, RuntimeError):
                    # A malformed side-effect claim is unsafe; the primary result
                    # remains recorded and the ledger will stop below if needed.
                    pass

            state = _ledger_state(ledger.status)
            record = self._record_payload(
                run,
                item,
                action_plan,
                ledger,
                comment_text=comment_text,
                activity_text=activity_text,
                requirements=requirements,
                mention_names=mention_names,
                comment_source=comment_source,
                started_at=started_at,
                state=state,
                result=result,
            )
            item_state = "completed" if state == "completed" else "waiting_user"
            self._save_record(run_id, activity_id, record, item_state=item_state)
            if result.state in {WriteOutcomeState.UNKNOWN, WriteOutcomeState.FAILED}:
                self._record_problem(run, item, result)
                return self._response(run_id, activity_id, record, result)
            if index + 1 < len(action_plan.actions) and ledger.next_action is not None:
                await asyncio.sleep(self._next_delay_seconds())

        final = WriteOperationResult(
            WriteOutcomeState.SUCCESS,
            "UNOFFICIAL_PARTICIPATION_CONFIRMED",
            "comment submit accepted; repost, like and follow terminal states were confirmed",
        )
        record = self._record_payload(
            run,
            item,
            action_plan,
            ledger,
            comment_text=comment_text,
            activity_text=activity_text,
            requirements=requirements,
            mention_names=mention_names,
            comment_source=comment_source,
            started_at=started_at,
            state="completed",
            result=final,
        )
        self._save_record(run_id, activity_id, record, item_state="completed")
        return self._response(run_id, activity_id, record, final)

    def _finish_blocked(
        self,
        run: Run,
        item: RunItem,
        ledger: ActionCheckpointLedger,
        result: WriteOperationResult,
        *,
        plan: UnofficialActionPlan | None = None,
        comment_text: str,
        activity_text: str,
        requirements: ParticipationRequirements,
        mention_names: tuple[str, ...],
        stage: str,
    ) -> dict[str, Any]:
        action = ledger.next_action or ledger.actions[0]
        ledger.start(action)
        ledger.record(action, result)
        record = self._record_payload(
            run,
            item,
            plan or UnofficialActionPlan(actions=ledger.actions),
            ledger,
            comment_text=comment_text,
            activity_text=activity_text,
            requirements=requirements,
            mention_names=mention_names,
            started_at=_now(),
            state="blocked_failed",
            result=result,
        )
        self._save_record(run.id or 0, item.activity_id, record, item_state="waiting_user")
        self._record_problem(run, item, result, stage=stage)
        return self._response(run.id or 0, item.activity_id, record, result)

    def _next_delay_seconds(self) -> float:
        minimum = max(0.0, self.settings.unofficial_automation_delay_min_sec)
        maximum = max(minimum, self.settings.unofficial_automation_delay_max_sec)
        return random.uniform(minimum, maximum)

    def _get_target(self, run_id: int, activity_id: int) -> tuple[Run, RunItem]:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            return run, item

    def _existing_write(self, run: Run, activity_id: int) -> dict[str, Any] | None:
        stats = _load_object(run.stats_json)
        writes = stats.get("unofficialParticipationWrites")
        if not isinstance(writes, dict):
            return None
        record = writes.get(str(activity_id))
        return record if isinstance(record, dict) else None

    def _reuse_or_reject(
        self,
        run_id: int,
        activity_id: int,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        state = str(record.get("state", ""))
        if state == "completed":
            return {
                "runId": run_id,
                "activityId": activity_id,
                "state": "completed",
                "resultState": record.get("resultState", "already_done"),
                "resultCode": record.get("resultCode", "UNOFFICIAL_PARTICIPATION_CONFIRMED"),
                "resultMessage": record.get(
                    "resultMessage", "non-official participation was already confirmed"
                ),
                "checkpoint": record.get("checkpoint"),
                "write": record,
            }
        if state in {"running", "blocked_unknown", "blocked_failed"}:
            previous_code = str(record.get("resultCode") or "UNKNOWN")
            raise ValueError(
                "UNOFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY"
                f":previous={previous_code};state={state}"
            )
        raise ValueError("UNOFFICIAL_PARTICIPATION_WRITE_STATE_INVALID")

    def _record_payload(
        self,
        run: Run,
        item: RunItem,
        plan: UnofficialActionPlan,
        ledger: ActionCheckpointLedger,
        *,
        comment_text: str,
        activity_text: str = "",
        requirements: ParticipationRequirements | None = None,
        mention_names: tuple[str, ...] = (),
        comment_source: str = "configured_default",
        started_at: str,
        state: str,
        result: WriteOperationResult | None = None,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "activityId": item.activity_id,
            "dynamicId": item.dynamic_id,
            "targetUrl": item.canonical_url,
            "strategy": plan.interaction_strategy,
            "targetScope": plan.target_scope,
            "actions": [action.value for action in plan.actions],
            "commentText": comment_text,
            "commentSource": comment_source,
            "activityContext": activity_text[:4000],
            "requiredTopics": list(requirements.required_topics) if requirements else [],
            "requiredMentionCount": requirements.required_mention_count if requirements else 0,
            "mentionNames": [f"@{name}" for name in mention_names],
            "resultState": result.state.value if result is not None else None,
            "resultCode": result.code if result is not None else "CHECKPOINT_RUNNING",
            "resultMessage": result.message if result is not None else "write sequence is running",
            "checkpoint": ledger.to_payload(),
            "startedAt": started_at,
            "finishedAt": _now()
            if state in {"completed", "blocked_unknown", "blocked_failed"}
            else None,
            "authorizationMode": "confirmed_run_automation",
            "unknownResultPolicy": "manual_review_no_retry",
        }

    def _save_record(
        self,
        run_id: int,
        activity_id: int,
        record: dict[str, Any],
        *,
        item_state: str,
    ) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            stats = _load_object(run.stats_json)
            writes = stats.get("unofficialParticipationWrites")
            if not isinstance(writes, dict):
                writes = {}
            writes[str(activity_id)] = record
            stats["unofficialParticipationWrites"] = writes
            stats["unofficialParticipationLastResult"] = record.get("resultCode")
            item.state = item_state
            item.platform_status = "participated" if item_state == "completed" else "manual_review"
            item.result_code = record.get("resultCode")
            item.result_message = record.get("resultMessage")
            item.block_reason = None if item_state == "completed" else record.get("resultMessage")
            session.add(item)
            session.flush()
            items = list(session.exec(select(RunItem).where(RunItem.run_id == run_id)).all())
            stats = reconcile_run_item_stats(stats, items)
            stats["requiresManualReview"] = any(
                row.state in {"blocked", "waiting_user"} for row in items
            )
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()

    def _record_problem(
        self,
        run: Run,
        item: RunItem,
        result: WriteOperationResult,
        *,
        stage: str = "unofficial_participation",
    ) -> None:
        for source_article_id in _load_json_ints(item.source_article_ids_json):
            self.problems.record(
                discovery_run_id=run.discovery_run_id,
                source_article_id=source_article_id,
                problem_url=item.canonical_url,
                page_type="activity",
                stage=stage,
                problem_code=result.code,
                safe_detail=result.message,
            )

    def _response(
        self,
        run_id: int,
        activity_id: int,
        record: dict[str, Any],
        result: WriteOperationResult,
    ) -> dict[str, Any]:
        return {
            "runId": run_id,
            "activityId": activity_id,
            "state": record["state"],
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": record["checkpoint"],
            "write": record,
        }


def _ledger_state(status: str) -> str:
    if status == "completed":
        return "completed"
    if status == "blocked_unknown":
        return "blocked_unknown"
    if status == "blocked_failed":
        return "blocked_failed"
    return "running"


def _compose_comment(
    settings: Settings,
    requirements: ParticipationRequirements,
    *,
    generated_comment: str = "",
    mention_names: tuple[str, ...] = (),
) -> str:
    base = generated_comment.strip() or requirements.comment_instruction.strip()
    if not base:
        base = settings.unofficial_comment_default.strip()
    base = _append_topics(base, requirements.required_topics)
    return _append_mentions(base, mention_names)


def _append_topics(comment: str, topics: tuple[str, ...]) -> str:
    base = " ".join(comment.split())
    existing = set(re.findall(r"#[^#\r\n]{1,80}#", base))
    missing = [topic.strip() for topic in topics if topic.strip() and topic.strip() not in existing]
    return " ".join(part for part in (base, " ".join(dict.fromkeys(missing))) if part).strip()


def _append_mentions(comment: str, names: tuple[str, ...]) -> str:
    base = " ".join(comment.split())
    missing: list[str] = []
    for name in names:
        normalized = name.strip()
        if not normalized:
            continue
        pattern = rf"@?{re.escape(normalized)}(?:\s|$|[，。！？,.!?])"
        if not re.search(pattern, base):
            missing.append(f"@{normalized}")
    return " ".join(part for part in (base, " ".join(missing)) if part).strip()





def _load_json_ints(value: str) -> list[int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, int)] if isinstance(parsed, list) else []


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["UnofficialParticipationExecutionService"]
