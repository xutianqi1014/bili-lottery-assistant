from typing import Any

from fastapi import APIRouter, Request
from sqlmodel import Session

from backend.api.dependencies import get_state
from backend.db.models.problem import ProblemRecord
from backend.db.repositories.problems import list_all, list_for_discovery

router = APIRouter(tags=["problems"])


def _serialize(row: ProblemRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "discoveryRunId": row.discovery_run_id,
        "sourceArticleId": row.source_article_id,
        "problemUrl": row.problem_url,
        "pageType": row.page_type,
        "stage": row.stage,
        "problemCode": row.problem_code,
        "safeDetail": row.safe_detail,
        "occurrenceCount": row.occurrence_count,
        "status": row.status,
        "createdAt": row.created_at.isoformat(),
    }


@router.get("/api/problems")
def problems(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    state = get_state(request)
    with Session(state.engine) as session:
        rows = list_all(session, min(max(limit, 1), 500))
    return [_serialize(row) for row in rows]


@router.get("/api/discoveries/{discovery_id}/problems")
def discovery_problems(discovery_id: int, request: Request) -> list[dict[str, Any]]:
    state = get_state(request)
    with Session(state.engine) as session:
        rows = list_for_discovery(session, discovery_id)
    return [_serialize(row) for row in rows]
