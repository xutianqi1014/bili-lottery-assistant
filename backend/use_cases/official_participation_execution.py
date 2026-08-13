"""Execute one run-scoped automatic official lottery participation.

The immutable run plan is confirmed once.  Each official item is then checked
against the automation switch and that confirmed run scope before the DOM
transport may inspect or click the official lottery panel.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import select

from backend.activity_engine.official.participation import (
    GuardedOfficialParticipationExecutor,
    OfficialParticipationCheckpointLedger,
    OfficialParticipationOutcomeState,
    OfficialParticipationWriteResult,
)
from backend.activity_engine.official.participation_dom import (
    LOTTERY_SELECTOR_VERSION,
    DomOfficialParticipationTransport,
    classify_official_panel_text,
)
from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.run import Run, RunItem
from backend.problems.registry import ProblemRegistry
from backend.use_cases.official_participation_automation import (
    OfficialParticipationAutomationError,
    OfficialParticipationAutomationPolicy,
)
from backend.use_cases.run_stats import reconcile_run_item_stats

_PRE_CLICK_RECONCILABLE_CODES = {
    "OFFICIAL_LOTTERY_PAGE_READ_UNKNOWN",
    "OFFICIAL_PARTICIPATION_BUTTON_NOT_FOUND",
}


class OfficialParticipationExecutionService:
    """Persist and execute one official target behind every safety gate."""

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
        self.problems = ProblemRegistry(engine)

    async def execute(
        self,
        run_id: int,
        *,
        activity_id: int,
    ) -> dict[str, Any]:
        if not self.settings.official_automation_enabled:
            raise ValueError("OFFICIAL_PARTICIPATION_AUTOMATION_DISABLED")

        run, item = self._get_target(run_id, activity_id)
        existing = self._existing_write(run, activity_id)
        if existing is not None:
            return self._reuse_or_reject(run_id, activity_id, item, existing)
        if item.family != "official":
            raise ValueError("OFFICIAL_PARTICIPATION_TARGET_NOT_OFFICIAL")
        if item.state not in {"planned", "running"}:
            raise ValueError("OFFICIAL_PARTICIPATION_AUTOMATION_ITEM_NOT_READY")

        try:
            policy = OfficialParticipationAutomationPolicy()
            run_dynamic_ids = policy.authorize_run(self._official_dynamic_ids(run_id))
            policy.require_target(item.dynamic_id, run_dynamic_ids)
        except OfficialParticipationAutomationError as exc:
            raise ValueError(str(exc)) from exc

        started_at = _now()
        self._save_record(
            run_id,
            activity_id,
            {
                "state": "running",
                "activityId": activity_id,
                "dynamicId": item.dynamic_id,
                "targetUrl": item.canonical_url,
                "startedAt": started_at,
                "authorizationMode": "confirmed_run_automation",
            },
        )

        transport = (
            self.transport_factory()
            if self.transport_factory is not None
            else DomOfficialParticipationTransport(self.browser)
        )
        executor = GuardedOfficialParticipationExecutor(
            self.settings.official_automation_enabled,
            transport,
        )
        ledger = OfficialParticipationCheckpointLedger()
        try:
            result = await executor.execute(
                ledger,
                target_url=item.canonical_url,
                payload={"activityId": activity_id, "dynamicId": item.dynamic_id},
            )
        except Exception as exc:  # noqa: BLE001 - persist a terminal safe state
            result = OfficialParticipationWriteResult(
                OfficialParticipationOutcomeState.UNKNOWN,
                "OFFICIAL_PARTICIPATION_EXECUTION_UNKNOWN",
                f"official participation result is unknown: {type(exc).__name__}",
            )

        state = _result_state(result.state)
        checkpoint = ledger.to_payload()
        record = {
            "state": state,
            "activityId": activity_id,
            "dynamicId": item.dynamic_id,
            "targetUrl": item.canonical_url,
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "startedAt": started_at,
            "finishedAt": _now(),
        }
        self._save_record(run_id, activity_id, record, result=result)
        if _should_record_problem(result):
            for source_article_id in _load_json_ints(item.source_article_ids_json):
                self.problems.record(
                    discovery_run_id=run.discovery_run_id,
                    source_article_id=source_article_id,
                    problem_url=item.canonical_url,
                    page_type="activity",
                    stage="official_participation",
                    problem_code=result.code,
                    safe_detail=result.message,
                )
        return {
            "runId": run_id,
            "activityId": activity_id,
            "state": state,
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "write": record,
        }

    def reconcile_expired_from_panel_evidence(
        self,
        run_id: int,
        activity_id: int,
        *,
        panel_text: str,
    ) -> dict[str, Any]:
        """Persist an explicit iframe expiry without reopening or clicking it."""

        run, item = self._get_target(run_id, activity_id)
        existing = self._existing_write(run, activity_id)
        if (
            existing is None
            or str(existing.get("state", "")) not in {"blocked_unknown", "blocked_failed"}
            or str(existing.get("resultCode", "")) not in _PRE_CLICK_RECONCILABLE_CODES
        ):
            raise ValueError("OFFICIAL_EXPIRY_RECONCILIATION_NOT_ALLOWED")
        result = classify_official_panel_text(panel_text)
        if result is None or result.state is not OfficialParticipationOutcomeState.EXPIRED:
            raise ValueError("OFFICIAL_EXPIRY_EVIDENCE_NOT_EXPLICIT")
        checkpoint = {
            "status": "completed",
            "unknownResultPolicy": "manual_review_no_retry",
            "checkpoint": {
                "state": "confirmed",
                "attempts": 0,
                "resultCode": result.code,
                "resultMessage": result.message,
            },
        }
        record = {
            "state": "completed",
            "activityId": activity_id,
            "dynamicId": item.dynamic_id,
            "targetUrl": item.canonical_url,
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "startedAt": _now(),
            "finishedAt": _now(),
            "authorizationMode": "confirmed_run_automation",
            "externalRetry": False,
            "reconciledFromPanelEvidence": {
                "selectorVersion": LOTTERY_SELECTOR_VERSION,
                "panelTextExcerpt": " ".join(panel_text.split())[:1000],
            },
            "previousPreClickAttempt": existing,
        }
        self._save_record(run_id, activity_id, record, result=result)
        return {
            "runId": run_id,
            "activityId": activity_id,
            "state": "completed",
            "resultState": result.state.value,
            "resultCode": result.code,
            "resultMessage": result.message,
            "checkpoint": checkpoint,
            "write": record,
        }

    def validate_run_scope(self, run_id: int) -> tuple[str, ...]:
        """Fail closed before browsing if the confirmed run scope is invalid."""

        if not self.settings.official_automation_enabled:
            raise ValueError("OFFICIAL_PARTICIPATION_AUTOMATION_DISABLED")
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            items = list(
                session.exec(
                    select(RunItem)
                    .where(RunItem.run_id == run_id, RunItem.family == "official")
                    .order_by(RunItem.__table__.c.sequence)  # type: ignore[attr-defined]
                ).all()
            )
        try:
            return OfficialParticipationAutomationPolicy().authorize_run(
                [
                    item.dynamic_id
                    for item in items
                    if item.state in {"planned", "running", "waiting_user"}
                ]
            )
        except OfficialParticipationAutomationError as exc:
            raise ValueError(str(exc)) from exc

    def _official_dynamic_ids(self, run_id: int) -> list[str]:
        with open_session(self.engine) as session:
            return list(
                session.exec(
                    select(RunItem.dynamic_id).where(
                        RunItem.run_id == run_id,
                        RunItem.family == "official",
                        RunItem.__table__.c.state.in_(  # type: ignore[attr-defined]
                            ["planned", "running", "waiting_user"]
                        ),
                    )
                ).all()
            )

    def _get_target(self, run_id: int, activity_id: int) -> tuple[Run, RunItem]:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            return run, item

    def _existing_write(self, run: Run, activity_id: int) -> dict[str, Any] | None:
        stats = _load_object(run.stats_json)
        writes = stats.get("officialParticipationWrites")
        if not isinstance(writes, dict):
            return None
        record = writes.get(str(activity_id))
        return record if isinstance(record, dict) else None

    def _reuse_or_reject(
        self,
        run_id: int,
        activity_id: int,
        item: RunItem,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        state = str(record.get("state", ""))
        if state == "completed":
            return {
                "runId": run_id,
                "activityId": activity_id,
                "state": state,
                "resultState": record.get("resultState", "already_participated"),
                "resultCode": record.get("resultCode", "ALREADY_PARTICIPATED"),
                "resultMessage": record.get("resultMessage", "official target already completed"),
                "checkpoint": record.get("checkpoint"),
                "write": record,
            }
        if state in {"running", "blocked_unknown", "blocked_failed"}:
            raise ValueError("OFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY")
        del item
        raise ValueError("OFFICIAL_PARTICIPATION_WRITE_STATE_INVALID")

    def _save_record(
        self,
        run_id: int,
        activity_id: int,
        record: dict[str, Any],
        *,
        result: OfficialParticipationWriteResult | None = None,
    ) -> None:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            item = session.get(RunItem, (run_id, activity_id))
            if item is None:
                raise ValueError("RUN_ITEM_NOT_FOUND")
            stats = _load_object(run.stats_json)
            writes = stats.get("officialParticipationWrites")
            if not isinstance(writes, dict):
                writes = {}
            writes[str(activity_id)] = record
            stats["officialParticipationWrites"] = writes
            if result is not None:
                if result.state is OfficialParticipationOutcomeState.SUCCESS:
                    item.state = "completed"
                    item.platform_status = "participated"
                    item.block_reason = None
                elif result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED:
                    item.state = "skipped"
                    item.platform_status = "already_participated"
                    item.block_reason = None
                elif result.state is OfficialParticipationOutcomeState.EXPIRED:
                    item.state = "skipped"
                    item.platform_status = "expired"
                    item.block_reason = None
                else:
                    item.state = "waiting_user"
                    item.platform_status = "manual_review"
                    item.block_reason = result.message
                item.result_code = result.code
                item.result_message = result.message
                stats["officialParticipationLastResult"] = result.code
                session.add(item)
                session.flush()
                items = list(
                    session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
                )
                stats = reconcile_run_item_stats(stats, items)
                stats["requiresManualReview"] = any(
                    row.state in {"blocked", "waiting_user"} for row in items
                )
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()


def _result_state(state: OfficialParticipationOutcomeState) -> str:
    if state in {
        OfficialParticipationOutcomeState.SUCCESS,
        OfficialParticipationOutcomeState.ALREADY_PARTICIPATED,
        OfficialParticipationOutcomeState.EXPIRED,
    }:
        return "completed"
    if state is OfficialParticipationOutcomeState.UNKNOWN:
        return "blocked_unknown"
    return "blocked_failed"


def _load_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _should_record_problem(result: OfficialParticipationWriteResult) -> bool:
    return result.state in {
        OfficialParticipationOutcomeState.UNKNOWN,
        OfficialParticipationOutcomeState.FAILED,
    } and result.code != "LOTTERY_EXPIRED"


def _load_json_ints(value: str) -> list[int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, int)]


def _now() -> str:
    return datetime.now(UTC).isoformat()
