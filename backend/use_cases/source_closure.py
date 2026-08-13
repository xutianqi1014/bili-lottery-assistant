"""Determine whether a source article is safe to mark as processed.

This module only calculates local state and never clicks.  The run-scoped
source-like automation service may consume ``ready_to_mark`` rows after every
related activity reaches a terminal state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle

_TERMINAL_ITEM_STATES = frozenset({"completed", "skipped"})


@dataclass(frozen=True, slots=True)
class SourceClosureRow:
    source_article_id: int
    title: str
    url: str
    status: str
    activity_count: int
    terminal_activity_count: int
    pending_activity_count: int
    open_problem_count: int
    problem_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def ready_to_mark(self) -> bool:
        return self.status == "ready_to_mark"

    def to_payload(self) -> dict[str, Any]:
        return {
            "sourceArticleId": self.source_article_id,
            "title": self.title,
            "url": self.url,
            "status": self.status,
            "readyToMark": self.ready_to_mark,
            "activityCount": self.activity_count,
            "terminalActivityCount": self.terminal_activity_count,
            "pendingActivityCount": self.pending_activity_count,
            "openProblemCount": self.open_problem_count,
            "problemCodes": list(self.problem_codes),
            "reasonCodes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class SourceClosureSummary:
    run_id: int
    rows: tuple[SourceClosureRow, ...]

    @property
    def ready_to_mark_count(self) -> int:
        return sum(row.ready_to_mark for row in self.rows)

    @property
    def already_liked_count(self) -> int:
        return sum(row.status == "already_liked" for row in self.rows)

    @property
    def blocked_count(self) -> int:
        return sum(row.status == "blocked_not_marked" for row in self.rows)

    def to_payload(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "readyToMarkCount": self.ready_to_mark_count,
            "alreadyLikedCount": self.already_liked_count,
            "blockedCount": self.blocked_count,
            "items": [row.to_payload() for row in self.rows],
        }


class SourceClosureService:
    """Calculate per-source completion without performing a source like."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def calculate(self, session: Session, run: Run) -> SourceClosureSummary:
        return calculate_source_closure(session, run)

    def get(self, run_id: int) -> SourceClosureSummary:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return self.calculate(session, run)


def calculate_source_closure(session: Session, run: Run) -> SourceClosureSummary:
    """Build a deterministic closure summary from the current run ledger."""

    assert run.id is not None
    source_ids = list(dict.fromkeys(_load_json_ints(run.source_article_ids_json)))
    if not source_ids:
        return SourceClosureSummary(run_id=run.id, rows=())

    articles = {
        article.id: article
        for article in session.exec(
            select(SourceArticle).where(
                SourceArticle.__table__.c.id.in_(source_ids)  # type: ignore[attr-defined]
            )
        ).all()
        if article.id is not None
    }
    item_rows = list(
        session.exec(select(RunItem).where(RunItem.run_id == run.id)).all()
    )
    problems = list(
        session.exec(
            select(ProblemRecord).where(
                ProblemRecord.discovery_run_id == run.discovery_run_id,
                ProblemRecord.status == "open",
            )
        ).all()
    )
    problems_by_source: dict[int, list[ProblemRecord]] = {}
    for problem in problems:
        if problem.source_article_id is not None:
            problems_by_source.setdefault(problem.source_article_id, []).append(problem)

    rows: list[SourceClosureRow] = []
    for source_id in source_ids:
        article = articles.get(source_id)
        related_items = [
            item for item in item_rows if source_id in _load_json_ints(item.source_article_ids_json)
        ]
        source_problems = problems_by_source.get(source_id, [])
        terminal_count = sum(item.state in _TERMINAL_ITEM_STATES for item in related_items)
        pending_count = len(related_items) - terminal_count
        reason_codes: list[str] = []

        if article is None:
            status = "blocked_not_marked"
            reason_codes.append("SOURCE_ARTICLE_NOT_FOUND")
            title = ""
            url = ""
        elif article.like_state == "liked":
            status = "already_liked"
            reason_codes.append("SOURCE_ALREADY_LIKED")
            title = article.title
            url = article.canonical_url
        elif article.like_state != "unliked":
            status = "blocked_not_marked"
            reason_codes.append("SOURCE_LIKE_STATE_UNKNOWN")
            title = article.title
            url = article.canonical_url
        else:
            title = article.title
            url = article.canonical_url
            if not related_items:
                status = "blocked_not_marked"
                reason_codes.append("NO_ACTIVITY_ITEMS")
            elif pending_count:
                status = "blocked_not_marked"
                reason_codes.append("ITEMS_NOT_TERMINAL")
                if any(item.state == "waiting_user" for item in related_items):
                    reason_codes.append("WAITING_USER")
                if any(item.state == "blocked" for item in related_items):
                    reason_codes.append("ITEM_BLOCKED")
            elif source_problems:
                status = "blocked_not_marked"
                reason_codes.append("OPEN_PROBLEMS")
            else:
                status = "ready_to_mark"

        problem_codes = tuple(sorted({problem.problem_code for problem in source_problems}))
        if (
            source_problems
            and status != "already_liked"
            and "OPEN_PROBLEMS" not in reason_codes
        ):
            reason_codes.append("OPEN_PROBLEMS")
            status = "blocked_not_marked"
        rows.append(
            SourceClosureRow(
                source_article_id=source_id,
                title=title,
                url=url,
                status=status,
                activity_count=len(related_items),
                terminal_activity_count=terminal_count,
                pending_activity_count=pending_count,
                open_problem_count=len(source_problems),
                problem_codes=problem_codes,
                reason_codes=tuple(reason_codes),
            )
        )
    return SourceClosureSummary(run_id=run.id, rows=tuple(rows))


def _load_json_ints(value: str) -> list[int]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, int)]
