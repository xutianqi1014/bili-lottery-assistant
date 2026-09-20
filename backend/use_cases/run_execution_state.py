"""Transactional run lifecycle, restart ledger, and persisted progress."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import select

from backend.db.engine import open_session
from backend.db.models.activity import Activity
from backend.db.models.run import Run, RunItem
from backend.db.repositories import runs
from backend.domain.json_utils import load_json_ints as _load_json_ints
from backend.domain.json_utils import load_json_object as _load_json_object
from backend.problems.registry import ProblemRegistry
from backend.use_cases.official_participation_execution import OfficialParticipationExecutionService
from backend.use_cases.run_execution_outcomes import RuntimeOutcome
from backend.use_cases.run_stats import reconcile_run_item_stats
from backend.use_cases.source_closure import SourceClosureService

_LEGACY_PREWRITE_SECURITY_ACTIONS = {
    "COMMENT_SECURITY_CHALLENGE": "comment",
    "DYNAMIC_LIKE_SECURITY_CHALLENGE": "like",
    "REPOST_SECURITY_CHALLENGE": "repost",
}


class RunExecutionStore:
    """Own database transactions; callers retain event publication ordering."""

    def __init__(
        self, engine: Engine, source_closure: SourceClosureService, problems: ProblemRegistry
    ) -> None:
        self.engine = engine
        self.source_closure = source_closure
        self.problems = problems

    def queue(
        self,
        run_id: int,
        *,
        resume: bool = False,
        official_automation_enabled: bool,
        unofficial_automation_enabled: bool,
        official_participation_service: OfficialParticipationExecutionService | None,
        unofficial_service_available: bool,
    ) -> Run:
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
                        # ``interactive`` is a mixed source-article section;
                        # do not force the official writer/scope validation
                        # before the dynamic's like-first runtime inspection.
                        RunItem.mode != "interactive",
                        RunItem.__table__.c.state.in_(  # type: ignore[attr-defined]
                            ["planned", "running", "waiting_user"]
                        ),
                    )
                ).first()
            )
            has_pending_interactive = bool(
                session.exec(
                    select(RunItem.activity_id).where(
                        RunItem.run_id == run_id,
                        RunItem.mode == "interactive",
                        RunItem.__table__.c.state.in_(  # type: ignore[attr-defined]
                            ["planned", "running", "waiting_user"]
                        ),
                    )
                ).first()
            )
            if official_automation_enabled and has_pending_official:
                if official_participation_service is None:
                    raise ValueError("OFFICIAL_PARTICIPATION_AUTOMATION_SERVICE_MISSING")
                official_participation_service.validate_run_scope(run_id)
                next_detail = "已进入执行队列；官方目标将自动处理，非官方目标按当前策略检查。"
            elif has_pending_interactive:
                next_detail = "已进入互动混合执行队列；每条先检查点赞，再按页面实际类型处理。"
            elif (
                unofficial_automation_enabled
                and unofficial_service_available
            ):
                next_detail = "non-official actions will run automatically after runtime checks"
            elif official_automation_enabled:
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

    def prepare_restart(self, run_id: int) -> Run:
        """Reset the current blocked item before an explicit user restart.

        A restart is different from the normal resume endpoint.  It is an
        explicit acknowledgement that the user has manually completed (or
        corrected) the dynamic that stopped the run.  Only the first
        unresolved item is reset to ``planned`` so completed and skipped
        items remain terminal and are never replayed.  The next execution
        performs a fresh runtime inspection; it can therefore detect the
        user's manual action and safely skip an already-participated dynamic.
        """

        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            if run.state not in {"waiting_user", "interrupted"}:
                raise ValueError("RUN_NOT_RESTARTABLE")

            items = list(
                session.exec(
                    select(RunItem)
                    .where(RunItem.run_id == run_id)
                    .order_by(RunItem.__table__.c.sequence)  # type: ignore[attr-defined]
                ).all()
            )
            unresolved = [
                row
                for row in items
                if row.state in {"blocked", "waiting_user", "running"}
            ]
            if len(unresolved) > 1:
                raise ValueError("RUN_RESTART_MULTIPLE_PENDING_ITEMS")

            stats = _load_json_object(run.stats_json)
            if unresolved:
                item = unresolved[0]
                # Keep the discovery-time section hint available after a
                # manual repair.  Runtime mode may have been overwritten by
                # the failed inspection, so it cannot be used as the hint.
                item.mode = item.source_section or "unknown"
                item.unofficial_type = "unknown"
                item.platform_status = "unchecked"
                item.state = "planned"
                item.block_reason = None
                item.runtime_inspected_at = None
                item.runtime_selector_version = None
                item.runtime_inspection_json = "{}"
                item.result_code = None
                item.result_message = None
                session.add(item)
                # A deterministic pre-write failure (for example, a
                # transiently duplicated comment editor) is safe to retry
                # after the user explicitly chooses Restart.  Unknown writes,
                # in-progress writes, and records with confirmed side effects
                # remain durable so Restart cannot duplicate an external
                # action.
                _clear_restartable_unofficial_write(stats, item.activity_id)

            # The explicit restart clears the item-level manual-review gate;
            # queue() will still fail closed if a different blocked item is
            # present or if the run state changed concurrently.
            refreshed_items = list(
                session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
            )
            stats = reconcile_run_item_stats(stats, refreshed_items)
            stats["requiresManualReview"] = any(
                row.state in {"blocked", "waiting_user"} for row in refreshed_items
            )
            try:
                restart_count = int(stats.get("restartCount", 0) or 0)
            except (TypeError, ValueError):
                restart_count = 0
            stats["restartCount"] = restart_count + 1
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            run.status_detail = (
                "已人工处理当前问题动态；重新开始后将重新检查当前动态，"
                "已完成和已跳过动态不会重复执行。"
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

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

    def set_running(self, run_id: int) -> Run:
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

    def next_item(self, run_id: int) -> RunItem | None:
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

    def read_item_mode(self, run_id: int, activity_id: int) -> str:
        """Read the post-inspection mode for delay selection.

        ``execute`` holds a stale ORM snapshot while the configured automatic
        path persists the actual runtime classification.  Re-reading this
        single field avoids applying the official delay after a provisional
        interactive item resolves to a non-official dynamic.
        """

        with open_session(self.engine) as session:
            item = session.get(RunItem, (run_id, activity_id))
            return item.mode if item is not None else "unknown"

    def mark_item_running(self, run_id: int, activity_id: int) -> None:
        with open_session(self.engine) as session:
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            item.state = "running"
            item.block_reason = None
            session.add(item)
            session.commit()

    def mark_item_waiting(self, run_id: int, activity_id: int, code: str, message: str) -> None:
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

    def persist_outcome(
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
                    session, run_row, items=run_items
                ).to_payload()
                run_stats = reconcile_run_item_stats(run_stats, run_items)
                run_stats["lastRuntimeResult"] = outcome.result_code
                run_row.stats_json = json.dumps(run_stats, ensure_ascii=False)
                session.add(run_row)
            session.commit()

    def get_source_closure(self, run_id: int) -> dict[str, Any]:
        return self.source_closure.get(run_id).to_payload()

    def refresh_source_closure(self, run_id: int) -> None:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_json_object(run.stats_json)
            items = list(session.exec(select(RunItem).where(RunItem.run_id == run_id)).all())
            stats = reconcile_run_item_stats(stats, items)
            stats["sourceClosure"] = self.source_closure.calculate(
                session, run, items=items
            ).to_payload()
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()

    def record_runtime_problem(self, run: Run, item: RunItem, code: str, message: str) -> None:
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

    def set_waiting(self, run_id: int, detail: str | None) -> Run:
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

    def finish(self, run_id: int, detail: str) -> Run:
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

    def set_failed(self, run_id: int, detail: str) -> Run:
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

    def set_interrupted(self, run_id: int, detail: str | None = None) -> Run:
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


def _clear_restartable_unofficial_write(stats: dict[str, Any], activity_id: int) -> None:
    """Drop only a known pre-write failure before an explicit item restart.

    ``blocked_failed`` is used for deterministic DOM/preflight failures, but
    the durable write ledger must still be treated as authoritative whenever
    an action was confirmed or its outcome was unknown.  The checkpoint shape
    lets us distinguish the safe-to-retry case without weakening the global
    no-automatic-retry guarantee.  A v1.5.1 security false positive was stored
    as ``blocked_unknown`` before any DOM write; the narrowly identified legacy
    shape is also safe to clear during an explicit restart.
    """

    writes = stats.get("unofficialParticipationWrites")
    if not isinstance(writes, dict):
        return
    key = str(activity_id)
    record = writes.get(key)
    if not isinstance(record, dict):
        return
    checkpoint = record.get("checkpoint")
    if not isinstance(checkpoint, dict):
        return
    checkpoints = checkpoint.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        return

    record_state = record.get("state")
    result_state = record.get("resultState")
    if record_state == "blocked_failed" and result_state == "failed":
        if any(
            not isinstance(action, dict)
            or action.get("state") in {"confirmed", "in_progress", "unknown"}
            for action in checkpoints
        ):
            return
    elif record_state == "blocked_unknown" and result_state == "unknown":
        expected_action = _LEGACY_PREWRITE_SECURITY_ACTIONS.get(
            str(record.get("resultCode"))
        )
        if expected_action is None or checkpoint.get("status") != "blocked_unknown":
            return
        unknown_indexes = [
            index
            for index, action in enumerate(checkpoints)
            if isinstance(action, dict) and action.get("state") == "unknown"
        ]
        if len(unknown_indexes) != 1:
            return
        unknown_index = unknown_indexes[0]
        unknown_action = checkpoints[unknown_index]
        if not isinstance(unknown_action, dict) or unknown_action.get("action") != expected_action:
            return
        if any(
            not isinstance(action, dict) or action.get("state") != "pending"
            for index, action in enumerate(checkpoints)
            if index != unknown_index
        ):
            return
    else:
        return

    previous_result = record.get("resultCode")
    writes.pop(key, None)
    if writes:
        stats["unofficialParticipationWrites"] = writes
    else:
        stats.pop("unofficialParticipationWrites", None)
    if stats.get("unofficialParticipationLastResult") == previous_result:
        stats.pop("unofficialParticipationLastResult", None)
