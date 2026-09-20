"""Automatically close safe source articles for one confirmed run.

The service is deliberately separate from activity participation.  It consumes
only ``ready_to_mark`` rows produced by :mod:`backend.use_cases.source_closure`,
uses the immutable run-scoped source IDs, and performs at most one DOM like per
source article.  Unknown or failed outcomes are terminal, are recorded in the
problem registry, and are never retried automatically.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine

from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.run import Run
from backend.db.models.source import SourceArticle
from backend.domain.json_utils import load_json_object as _load_object
from backend.problems.registry import ProblemRegistry
from backend.source_adapters.lottery_toolman.source_like import (
    InvalidSourceLikeTargetError,
    SourceLikeCheckpointLedger,
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
    validate_source_like_target,
)
from backend.source_adapters.lottery_toolman.source_like_dom import DomSourceLikeTransport
from backend.use_cases.source_closure import (
    SourceClosureRow,
    SourceClosureService,
    calculate_source_closure,
)

_AUTOMATION_KEY = "sourceLikeAutomation"
_TERMINAL_BLOCK_STATES = frozenset({"blocked_unknown", "blocked_failed"})


@dataclass(frozen=True, slots=True)
class SourceLikeAutomationResult:
    """Run-level source closure outcome returned to the run orchestrator."""

    state: str
    result_code: str
    result_message: str
    target_count: int
    completed_count: int
    blocks_run: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "resultCode": self.result_code,
            "resultMessage": self.result_message,
            "targetCount": self.target_count,
            "completedCount": self.completed_count,
            "blocksRun": self.blocks_run,
        }


class SourceLikeAutomationService:
    """Like source articles only after their confirmed run is safely closed."""

    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        browser: BrowserManager,
        *,
        transport_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.browser = browser
        self.transport_factory = transport_factory
        self.closure = SourceClosureService(engine)
        self.problems = ProblemRegistry(engine)

    async def execute_ready(self, run_id: int) -> SourceLikeAutomationResult:
        """Execute every currently safe source target exactly once.

        A completed or blocked record is idempotent.  A persisted ``running``
        record means the previous process may have clicked before interruption;
        it is converted to an unknown terminal result and is not retried.
        """

        run, rows, saved = self._load_context(run_id)
        if run.state != "running":
            raise ValueError("SOURCE_LIKE_AUTOMATION_RUN_NOT_RUNNING")

        saved_state = str(saved.get("state", ""))
        if saved_state in {"completed", "skipped", "disabled"}:
            return _result_from_record(saved, blocks_run=False)
        if saved_state in _TERMINAL_BLOCK_STATES:
            return _result_from_record(saved, blocks_run=True)
        if saved_state == "running":
            return self._block_interrupted_attempt(run, rows, saved)

        if not self.settings.source_like_automation_enabled:
            return self._save_overall(
                run_id,
                state="disabled",
                result_code="SOURCE_LIKE_AUTOMATION_DISABLED",
                result_message="来源专栏自动收尾已由配置关闭，本轮未执行来源点赞",
                target_ids=[row.source_article_id for row in rows if row.ready_to_mark],
                completed_count=0,
                blocks_run=False,
            )

        ready = tuple(row for row in rows if row.ready_to_mark)
        if not ready:
            blocked_count = sum(row.status == "blocked_not_marked" for row in rows)
            if blocked_count:
                return self._save_overall(
                    run_id,
                    state="skipped",
                    result_code="SOURCE_CLOSURE_BLOCKED_NOT_LIKED",
                    result_message=(
                        f"{blocked_count} 个来源专栏存在未完成条目、未知点赞状态或开放问题；"
                        "本轮未点赞这些来源"
                    ),
                    target_ids=[],
                    completed_count=0,
                    blocks_run=False,
                )
            code = "ALL_SOURCES_ALREADY_LIKED" if rows else "NO_SOURCE_ARTICLES"
            message = (
                "所有来源专栏均已点赞，无需新增来源点赞"
                if rows
                else "本轮没有来源专栏，无需执行来源收尾"
            )
            return self._save_overall(
                run_id,
                state="completed",
                result_code=code,
                result_message=message,
                target_ids=[],
                completed_count=0,
                blocks_run=False,
            )

        maximum = max(0, self.settings.source_like_automation_max_items_per_run)
        if len(ready) > maximum:
            return self._block_preflight(
                run,
                ready,
                "SOURCE_LIKE_AUTOMATION_SCOPE_TOO_LARGE",
                f"来源收尾目标数 {len(ready)} 超过单轮上限 {maximum}，未执行点击",
            )

        for row in ready:
            try:
                validate_source_like_target(row.url)
            except InvalidSourceLikeTargetError:
                return self._block_preflight(
                    run,
                    (row,),
                    "SOURCE_LIKE_AUTOMATION_TARGET_INVALID",
                    "来源专栏网址不符合 B 站数字 cv 专栏白名单，未执行点击",
                )

        started_at = _now()
        target_ids = [row.source_article_id for row in ready]
        self._save_overall(
            run_id,
            state="running",
            result_code="SOURCE_LIKE_AUTOMATION_RUNNING",
            result_message=f"正在自动收尾 {len(ready)} 个来源专栏",
            target_ids=target_ids,
            completed_count=0,
            blocks_run=False,
            started_at=started_at,
        )

        completed_count = 0
        for row in ready:
            await asyncio.sleep(self._next_delay_seconds())
            result, checkpoint, target_started_at = await self._execute_target(run_id, row)
            target_state = _target_state(result.state)
            self._save_target_record(
                run_id,
                row,
                {
                    "state": target_state,
                    "sourceArticleId": row.source_article_id,
                    "title": row.title,
                    "targetUrl": row.url,
                    "resultState": result.state.value,
                    "resultCode": result.code,
                    "resultMessage": result.message,
                    "checkpoint": checkpoint,
                    "startedAt": target_started_at,
                    "finishedAt": _now(),
                },
                mark_article_liked=target_state == "completed",
            )
            if target_state == "completed":
                completed_count += 1
                continue

            self._record_problem(run, row, result.code, result.message)
            return self._save_overall(
                run_id,
                state=target_state,
                result_code=result.code,
                result_message=result.message,
                target_ids=target_ids,
                completed_count=completed_count,
                blocks_run=True,
                started_at=started_at,
            )

        return self._save_overall(
            run_id,
            state="completed",
            result_code="SOURCE_LIKE_AUTOMATION_CONFIRMED",
            result_message=f"{completed_count} 个来源专栏已自动点赞并确认终态",
            target_ids=target_ids,
            completed_count=completed_count,
            blocks_run=False,
            started_at=started_at,
        )

    async def _execute_target(
        self,
        run_id: int,
        row: SourceClosureRow,
    ) -> tuple[SourceLikeWriteResult, dict[str, object], str]:
        started_at = _now()
        self._save_target_record(
            run_id,
            row,
            {
                "state": "running",
                "sourceArticleId": row.source_article_id,
                "title": row.title,
                "targetUrl": row.url,
                "resultCode": "SOURCE_LIKE_AUTOMATION_TARGET_RUNNING",
                "resultMessage": "正在读取来源专栏点赞状态",
                "startedAt": started_at,
            },
        )
        ledger = SourceLikeCheckpointLedger()
        ledger.start()
        transport = (
            self.transport_factory()
            if self.transport_factory is not None
            else DomSourceLikeTransport(self.browser)
        )
        try:
            result = await transport.perform(
                target_url=row.url,
                payload={
                    "runId": run_id,
                    "sourceArticleId": row.source_article_id,
                    "authorizationMode": "confirmed_run_source_closure",
                },
            )
        except Exception as exc:  # noqa: BLE001 - click outcome may be unknown
            result = SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_AUTOMATION_RESULT_UNKNOWN",
                f"来源专栏自动点赞结果未知，必须人工复核（{type(exc).__name__}）",
            )
        ledger.record(result)
        return result, ledger.to_payload(), started_at

    def _load_context(
        self,
        run_id: int,
    ) -> tuple[Run, tuple[SourceClosureRow, ...], dict[str, Any]]:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            summary = calculate_source_closure(session, run)
            stats = _load_object(run.stats_json)
            raw = stats.get(_AUTOMATION_KEY)
            saved = dict(raw) if isinstance(raw, dict) else {}
            return run, summary.rows, saved

    def _block_interrupted_attempt(
        self,
        run: Run,
        rows: tuple[SourceClosureRow, ...],
        saved: dict[str, Any],
    ) -> SourceLikeAutomationResult:
        writes = saved.get("writes")
        recorded_source_ids: set[int] = set()
        if isinstance(writes, dict):
            for value in writes.values():
                if not isinstance(value, dict) or value.get("state") != "running":
                    continue
                source_id = value.get("sourceArticleId")
                target_url = value.get("targetUrl")
                if isinstance(source_id, int) and isinstance(target_url, str):
                    row = SourceClosureRow(
                        source_article_id=source_id,
                        title=str(value.get("title", "")),
                        url=target_url,
                        status="ready_to_mark",
                        activity_count=0,
                        terminal_activity_count=0,
                        pending_activity_count=0,
                        open_problem_count=0,
                        problem_codes=(),
                        reason_codes=(),
                    )
                    self._record_problem(
                        run,
                        row,
                        "SOURCE_LIKE_AUTOMATION_INTERRUPTED_UNKNOWN",
                        "上次来源点赞在运行中中断，外部结果未知；禁止自动重试",
                    )
                    recorded_source_ids.add(source_id)
        for row in rows:
            if row.ready_to_mark and row.source_article_id not in recorded_source_ids:
                self._record_problem(
                    run,
                    row,
                    "SOURCE_LIKE_AUTOMATION_INTERRUPTED_UNKNOWN",
                    "上次来源收尾在运行状态中中断，已停止且禁止自动重试",
                )
        return self._save_overall(
            run.id or 0,
            state="blocked_unknown",
            result_code="SOURCE_LIKE_AUTOMATION_INTERRUPTED_UNKNOWN",
            result_message="上次来源点赞在运行中中断，结果未知；已停止且禁止自动重试",
            target_ids=_load_json_ints(saved.get("targetSourceArticleIds")),
            completed_count=int(saved.get("completedCount", 0) or 0),
            blocks_run=True,
            started_at=str(saved.get("startedAt", "")) or None,
        )

    def _block_preflight(
        self,
        run: Run,
        rows: tuple[SourceClosureRow, ...],
        code: str,
        message: str,
    ) -> SourceLikeAutomationResult:
        for row in rows:
            self._record_problem(run, row, code, message)
        return self._save_overall(
            run.id or 0,
            state="blocked_failed",
            result_code=code,
            result_message=message,
            target_ids=[row.source_article_id for row in rows],
            completed_count=0,
            blocks_run=True,
        )

    def _record_problem(
        self,
        run: Run,
        row: SourceClosureRow,
        code: str,
        message: str,
    ) -> None:
        self.problems.record(
            discovery_run_id=run.discovery_run_id,
            source_article_id=row.source_article_id,
            problem_url=row.url,
            page_type="source_article",
            stage="source_like_automation",
            problem_code=code,
            safe_detail=message,
        )

    def _save_target_record(
        self,
        run_id: int,
        row: SourceClosureRow,
        record: dict[str, Any],
        *,
        mark_article_liked: bool = False,
    ) -> None:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_object(run.stats_json)
            automation = _load_mapping(stats.get(_AUTOMATION_KEY))
            writes = _load_mapping(automation.get("writes"))
            writes[str(row.source_article_id)] = record
            automation["writes"] = writes
            stats[_AUTOMATION_KEY] = automation
            if mark_article_liked:
                article = session.get(SourceArticle, row.source_article_id)
                if article is None:
                    raise ValueError("SOURCE_ARTICLE_NOT_FOUND")
                article.like_state = "liked"
                article.like_checked_at = datetime.now(UTC)
                session.add(article)
                session.flush()
            stats["sourceClosure"] = calculate_source_closure(session, run).to_payload()
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()

    def _save_overall(
        self,
        run_id: int,
        *,
        state: str,
        result_code: str,
        result_message: str,
        target_ids: list[int],
        completed_count: int,
        blocks_run: bool,
        started_at: str | None = None,
    ) -> SourceLikeAutomationResult:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_object(run.stats_json)
            saved = _load_mapping(stats.get(_AUTOMATION_KEY))
            record = {
                **saved,
                "state": state,
                "automatic": True,
                "authorizationMode": "confirmed_run_source_closure",
                "targetSourceArticleIds": target_ids,
                "targetCount": len(target_ids),
                "completedCount": completed_count,
                "resultCode": result_code,
                "resultMessage": result_message,
                "unknownResultPolicy": "manual_review_no_retry",
                "startedAt": started_at or saved.get("startedAt") or _now(),
            }
            if state != "running":
                record["finishedAt"] = _now()
            stats[_AUTOMATION_KEY] = record
            if blocks_run:
                stats["requiresManualReview"] = True
            stats["sourceClosure"] = calculate_source_closure(session, run).to_payload()
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()
        return SourceLikeAutomationResult(
            state=state,
            result_code=result_code,
            result_message=result_message,
            target_count=len(target_ids),
            completed_count=completed_count,
            blocks_run=blocks_run,
        )

    def _next_delay_seconds(self) -> float:
        minimum = max(0.0, self.settings.source_like_automation_delay_min_sec)
        maximum = max(minimum, self.settings.source_like_automation_delay_max_sec)
        return random.uniform(minimum, maximum)


def _target_state(state: SourceLikeOutcomeState) -> str:
    if state in {SourceLikeOutcomeState.SUCCESS, SourceLikeOutcomeState.ALREADY_DONE}:
        return "completed"
    if state is SourceLikeOutcomeState.UNKNOWN:
        return "blocked_unknown"
    return "blocked_failed"


def _result_from_record(
    record: dict[str, Any],
    *,
    blocks_run: bool,
) -> SourceLikeAutomationResult:
    target_ids = _load_json_ints(record.get("targetSourceArticleIds"))
    completed = record.get("completedCount", 0)
    return SourceLikeAutomationResult(
        state=str(record.get("state", "blocked_unknown")),
        result_code=str(record.get("resultCode", "SOURCE_LIKE_AUTOMATION_STATE_UNKNOWN")),
        result_message=str(record.get("resultMessage", "来源专栏自动收尾状态未知")),
        target_count=len(target_ids),
        completed_count=completed if isinstance(completed, int) else 0,
        blocks_run=blocks_run,
    )





def _load_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _load_json_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]


def _now() -> str:
    return datetime.now(UTC).isoformat()
