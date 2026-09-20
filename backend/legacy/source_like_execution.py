"""Run one explicitly authorized source-article like through the DOM adapter.

The normal application keeps this entry point disabled.  When a separately
configured single-target allowlist, environment acknowledgement, CSRF-protected
request and user confirmation are all present, the service performs exactly one
source-like operation and persists its terminal result.  Unknown results are
terminal and are never retried automatically.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend.activity_engine.shared import ManualGate
from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.models.run import Run
from backend.db.models.source import SourceArticle
from backend.domain.json_utils import load_json_object as _load_object
from backend.legacy.source_like_plan import SourceLikePlan, SourceLikePlanService
from backend.legacy.source_like_write_test import (
    LIVE_WRITE_CONFIRMATION,
    ControlledSourceLikeWriteTest,
    SourceLikeWriteAllowlist,
    SourceLikeWriteTestError,
)
from backend.source_adapters.lottery_toolman.source_like import (
    GuardedSourceLikeExecutor,
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.source_adapters.lottery_toolman.source_like_dom import DomSourceLikeTransport


class SourceLikeExecutionService:
    """Persist and execute one source-like target behind all safety gates."""

    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        browser: BrowserManager,
        plan_service: SourceLikePlanService,
        *,
        transport_factory: Callable[[], Any] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.browser = browser
        self.plan_service = plan_service
        self.transport_factory = transport_factory
        self.environment = environment

    async def execute(
        self,
        run_id: int,
        *,
        source_article_id: int,
        user_confirmed: bool,
        confirmation_text: str,
    ) -> dict[str, Any]:
        if not self.settings.enable_direct_write_api:
            raise ValueError("SOURCE_LIKE_WRITE_DISABLED")

        plan = self.plan_service.get(run_id)
        existing = self._existing_write(run_id)
        if existing is not None:
            return self._reuse_or_reject(existing, run_id, source_article_id, plan)
        if plan.state != "confirmed_waiting_write":
            raise ValueError(f"SOURCE_LIKE_PLAN_NOT_EXECUTABLE:{plan.state}")
        if len(plan.targets) != 1:
            raise ValueError("SOURCE_LIKE_SINGLE_TARGET_REQUIRED")
        target = plan.targets[0]
        if target.source_article_id != source_article_id:
            raise ValueError("SOURCE_LIKE_TARGET_NOT_IN_CONFIRMED_PLAN")

        allowlist_path = self.settings.source_like_write_allowlist_path
        if allowlist_path is None:
            raise ValueError("SOURCE_LIKE_WRITE_ALLOWLIST_NOT_CONFIGURED")
        try:
            allowlist = SourceLikeWriteAllowlist.from_path(allowlist_path)
            session = ControlledSourceLikeWriteTest(allowlist, environment=self.environment)
            # Validate all authorization conditions before making the durable
            # running marker.  The same checks are repeated by execute().
            session.authorize(
                target.url,
                user_confirmed=user_confirmed,
                confirmation_text=confirmation_text,
            )
        except SourceLikeWriteTestError as exc:
            raise ValueError(str(exc)) from exc

        article_id = self._article_id(run_id, source_article_id)
        started_at = _now()
        self._save_write(
            run_id,
            {
                "state": "running",
                "sourceArticleId": source_article_id,
                "articleId": article_id,
                "targetUrl": target.url,
                "startedAt": started_at,
                "confirmationTextAccepted": confirmation_text == LIVE_WRITE_CONFIRMATION,
            },
        )

        transport = (
            self.transport_factory()
            if self.transport_factory is not None
            else DomSourceLikeTransport(self.browser)
        )
        executor = GuardedSourceLikeExecutor(
            ManualGate(self.settings.enable_direct_write_api),
            transport,
        )
        try:
            result = await session.execute(
                executor,
                target_url=target.url,
                user_confirmed=user_confirmed,
                confirmation_text=confirmation_text,
            )
        except Exception as exc:  # noqa: BLE001 - persist a terminal safe state
            result = SourceLikeWriteResult(
                SourceLikeOutcomeState.UNKNOWN,
                "SOURCE_LIKE_EXECUTION_UNKNOWN",
                f"来源专栏点赞执行结果未知，必须人工检查（{type(exc).__name__}）",
            )

        state = _result_state(result.state)
        checkpoint = session.ledger.to_payload()
        write_record = {
            "state": state,
            "sourceArticleId": source_article_id,
            "articleId": article_id,
            "targetUrl": target.url,
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "startedAt": started_at,
            "finishedAt": _now(),
        }
        self._save_write(run_id, write_record, mark_article_liked=state == "completed")
        return self._response(run_id, source_article_id, result, state, checkpoint)

    def _article_id(self, run_id: int, source_article_id: int) -> str:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            article = session.get(SourceArticle, source_article_id)
            if article is None:
                raise ValueError("SOURCE_ARTICLE_NOT_FOUND")
            return article.article_id

    def _existing_write(self, run_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_object(run.stats_json)
        record = stats.get("sourceLikeWrite")
        return record if isinstance(record, dict) else None

    def _reuse_or_reject(
        self,
        record: dict[str, Any],
        run_id: int,
        source_article_id: int,
        plan: SourceLikePlan,
    ) -> dict[str, Any]:
        if record.get("sourceArticleId") != source_article_id:
            raise ValueError("SOURCE_LIKE_TARGET_NOT_IN_PREVIOUS_WRITE")
        state = str(record.get("state", ""))
        if state == "completed":
            return {
                "runId": run_id,
                "sourceArticleId": source_article_id,
                "state": state,
                "resultState": record.get("resultState", "already_done"),
                "resultCode": record.get("resultCode", "SOURCE_LIKE_CONFIRMED"),
                "resultMessage": record.get("resultMessage", "来源专栏点赞已完成"),
                "checkpoint": record.get("checkpoint"),
                "plan": plan.to_payload(),
            }
        if state in {"running", "blocked_unknown", "blocked_failed"}:
            raise ValueError("SOURCE_LIKE_WRITE_TERMINAL_NO_RETRY")
        raise ValueError("SOURCE_LIKE_WRITE_STATE_INVALID")

    def _save_write(
        self,
        run_id: int,
        record: dict[str, Any],
        *,
        mark_article_liked: bool = False,
    ) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            stats = _load_object(run.stats_json)
            stats["sourceLikeWrite"] = record
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            if mark_article_liked:
                source_article_id = record.get("sourceArticleId")
                if isinstance(source_article_id, int):
                    article = session.get(SourceArticle, source_article_id)
                    if article is not None:
                        article.like_state = "liked"
                        article.like_checked_at = datetime.now(UTC)
                        session.add(article)
            session.commit()

    def _response(
        self,
        run_id: int,
        source_article_id: int,
        result: SourceLikeWriteResult,
        state: str,
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "runId": run_id,
            "sourceArticleId": source_article_id,
            "state": state,
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "plan": self.plan_service.get(run_id).to_payload(),
        }


def _result_state(state: SourceLikeOutcomeState) -> str:
    if state in {SourceLikeOutcomeState.SUCCESS, SourceLikeOutcomeState.ALREADY_DONE}:
        return "completed"
    if state is SourceLikeOutcomeState.UNKNOWN:
        return "blocked_unknown"
    return "blocked_failed"





def _now() -> str:
    return datetime.now(UTC).isoformat()
