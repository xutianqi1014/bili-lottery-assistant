"""Build and confirm a local source-like plan without performing a like."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine

from backend.db.engine import open_session
from backend.db.models.run import Run
from backend.use_cases.source_closure import (
    SourceClosureSummary,
    calculate_source_closure,
)


@dataclass(frozen=True, slots=True)
class SourceLikeTarget:
    source_article_id: int
    title: str
    url: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "sourceArticleId": self.source_article_id,
            "title": self.title,
            "url": self.url,
            "status": "ready_to_mark",
        }


@dataclass(frozen=True, slots=True)
class SourceLikePlan:
    run_id: int
    state: str
    direct_write_enabled: bool
    targets: tuple[SourceLikeTarget, ...]
    blocked_count: int
    already_liked_count: int
    confirmation_note: str | None = None
    confirmed_at: str | None = None
    reason: str | None = None
    write_state: str | None = None
    write_result_code: str | None = None
    write_result_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "state": self.state,
            "directWriteEnabled": self.direct_write_enabled,
            "targetCount": len(self.targets),
            "targets": [target.to_payload() for target in self.targets],
            "blockedCount": self.blocked_count,
            "alreadyLikedCount": self.already_liked_count,
            "confirmationNote": self.confirmation_note,
            "confirmedAt": self.confirmed_at,
            "reason": self.reason,
            "writeState": self.write_state,
            "writeResultCode": self.write_result_code,
            "writeResultMessage": self.write_result_message,
            "unknownResultPolicy": "manual_review_no_retry",
        }


class SourceLikePlanService:
    """Persist only a local confirmation for future source-like execution."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, run_id: int) -> SourceLikePlan:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            summary = calculate_source_closure(session, run)
            return self._build(run, summary)

    def confirm(self, run_id: int, note: str = "用户已确认来源收尾计划") -> SourceLikePlan:
        with open_session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            summary = calculate_source_closure(session, run)
            targets = _ready_targets(summary)
            if not targets:
                raise ValueError("NO_SOURCE_LIKE_TARGETS")
            stats = _load_json_object(run.stats_json)
            stats["sourceLikePlan"] = {
                "state": "confirmed_waiting_write",
                "directWriteEnabled": False,
                "targetSourceArticleIds": [target.source_article_id for target in targets],
                "confirmationNote": note[:500],
                "confirmedAt": datetime.now(UTC).isoformat(),
            }
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            session.add(run)
            session.commit()
            session.refresh(run)
            return self._build(run, summary)

    def _build(self, run: Run, summary: SourceClosureSummary) -> SourceLikePlan:
        assert run.id is not None
        targets = _ready_targets(summary)
        saved = _saved_plan(run.stats_json)
        write = _saved_write(run.stats_json)
        saved_ids = set(_load_json_ints(saved.get("targetSourceArticleIds")))
        ready_ids = {target.source_article_id for target in targets}
        saved_state = saved.get("state")
        saved_already_liked_ids = {
            row.source_article_id
            for row in summary.rows
            if row.status == "already_liked"
        }
        if saved_state in {"confirmed_waiting_write", "completed"}:
            if saved_ids and saved_ids <= saved_already_liked_ids:
                state = "completed"
                reason = "SOURCE_LIKE_CONFIRMED"
            elif saved_state == "confirmed_waiting_write" and saved_ids == ready_ids and ready_ids:
                state = "confirmed_waiting_write"
                reason = "SOURCE_LIKE_WRITE_DISABLED"
            else:
                state = "stale"
                reason = "SOURCE_CLOSURE_CHANGED"
        elif targets:
            state = "awaiting_confirmation"
            reason = None
        elif summary.blocked_count:
            state = "blocked"
            reason = "SOURCE_CLOSURE_BLOCKED"
        else:
            state = "no_targets"
            reason = "ALL_SOURCES_ALREADY_LIKED"
        return SourceLikePlan(
            run_id=run.id,
            state=state,
            direct_write_enabled=False,
            targets=tuple(targets),
            blocked_count=summary.blocked_count,
            already_liked_count=summary.already_liked_count,
            confirmation_note=(
                str(saved.get("confirmationNote"))
                if saved.get("confirmationNote") is not None
                else None
            ),
            confirmed_at=(
                str(saved.get("confirmedAt")) if saved.get("confirmedAt") is not None else None
            ),
            reason=reason,
            write_state=(
                str(write.get("state")) if write.get("state") is not None else None
            ),
            write_result_code=(
                str(write.get("resultCode")) if write.get("resultCode") is not None else None
            ),
            write_result_message=(
                str(write.get("resultMessage"))
                if write.get("resultMessage") is not None
                else None
            ),
        )


def _ready_targets(summary: SourceClosureSummary) -> list[SourceLikeTarget]:
    return [
        SourceLikeTarget(
            source_article_id=row.source_article_id,
            title=row.title,
            url=row.url,
        )
        for row in summary.rows
        if row.ready_to_mark
    ]


def _saved_plan(value: str) -> dict[str, Any]:
    stats = _load_json_object(value)
    saved = stats.get("sourceLikePlan")
    return saved if isinstance(saved, dict) else {}


def _saved_write(value: str) -> dict[str, Any]:
    stats = _load_json_object(value)
    saved = stats.get("sourceLikeWrite")
    return saved if isinstance(saved, dict) else {}


def _load_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_json_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]
