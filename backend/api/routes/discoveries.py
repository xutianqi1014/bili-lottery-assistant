import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from backend.api.dependencies import get_state, require_csrf
from backend.db.models.discovery import DiscoverySelection
from backend.db.models.run import Run
from backend.db.models.source import Readlist, SourceArticle
from backend.db.repositories import activities as activity_repo

router = APIRouter(tags=["discoveries"])


@router.post("/api/source-profiles/{profile_id}/discoveries", status_code=status.HTTP_202_ACCEPTED)
async def create_discovery(
    profile_id: int,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    state = get_state(request)
    if not state.jobs.can_submit(str(profile_id)):
        raise HTTPException(status_code=409, detail="JOB_SLOT_BUSY")
    try:
        row = state.discovery_service.create(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    discovery_id = row.id
    assert discovery_id is not None
    try:
        state.jobs.submit(
            str(discovery_id),
            lambda: _execute_discovery_and_plan(state, discovery_id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"discoveryId": discovery_id, "jobId": str(discovery_id), "state": row.state}


async def _execute_discovery_and_plan(state: Any, discovery_id: int) -> None:
    await state.discovery_service.execute(discovery_id)
    await state.automatic_plan_service.create_if_needed(discovery_id)


@router.get("/api/discoveries/{discovery_id}")
def get_discovery(discovery_id: int, request: Request) -> dict[str, Any]:
    state = get_state(request)
    with Session(state.engine) as session:
        from backend.db.models.discovery import DiscoveryRun

        discovery = session.get(DiscoveryRun, discovery_id)
        if discovery is None:
            raise HTTPException(status_code=404, detail="DISCOVERY_NOT_FOUND")
        selections = list(
            session.exec(
                select(DiscoverySelection).where(
                    DiscoverySelection.discovery_run_id == discovery_id
                )
            ).all()
        )
        article_ids = [row.source_article_id for row in selections]
        articles = {
            row.id: row
            for row in session.exec(
                select(SourceArticle).where(
                    SourceArticle.__table__.c.id.in_(article_ids)  # type: ignore[attr-defined]
                )
            ).all()
        } if article_ids else {}
        readlists = {
            row.id: row
            for row in session.exec(
                select(Readlist).where(
                    Readlist.__table__.c.id.in_(  # type: ignore[attr-defined]
                        [row.readlist_id for row in selections]
                    )
                )
            ).all()
        } if selections else {}
        activity_rows = activity_repo.list_for_discovery(session, discovery_id)
        run_plan_id = session.exec(
            select(Run.id)
            .where(Run.discovery_run_id == discovery_id)
            .order_by(Run.__table__.c.id.desc())  # type: ignore[attr-defined]
        ).first()
        activity_payload: list[dict[str, Any]] = []
        for activity in activity_rows:
            contexts = activity_repo.list_origin_contexts(session, discovery_id, activity.id or 0)
            activity_payload.append(
                {
                    "id": activity.id,
                    "dynamicId": activity.dynamic_id,
                    "url": activity.canonical_url,
                    "title": activity.title,
                    "bodyExcerpt": activity.body_excerpt,
                    "mode": "unknown",
                    "unofficialType": "unknown",
                    "platformStatus": "unchecked",
                    "classification": {},
                    "origins": [
                        {
                            "sourceArticleId": article.id,
                            "sourceArticleTitle": article.title,
                            "family": selection.family,
                            "sourcePosition": origin.source_position,
                        }
                        for origin, selection, article in contexts
                    ],
                    "runtimeInspectedAt": (
                        activity.runtime_inspected_at.isoformat()
                        if activity.runtime_inspected_at
                        else None
                    ),
                }
            )
    return {
        "id": discovery.id,
        "profileId": discovery.source_profile_id,
        "state": discovery.state,
        "latestPerFamily": discovery.latest_per_family,
        "selectedReadlists": json.loads(discovery.selected_readlists_json),
        "stats": json.loads(discovery.stats_json),
        "errorCode": discovery.error_code,
        "errorDetail": discovery.error_detail,
        "runPlanId": run_plan_id,
        "selections": [
            {
                "sourceArticleId": row.source_article_id,
                "articleId": articles[row.source_article_id].article_id,
                "title": articles[row.source_article_id].title,
                "url": articles[row.source_article_id].canonical_url,
                "readlistId": row.readlist_id,
                "readlistTitle": readlists[row.readlist_id].title,
                "family": row.family,
                "rank": row.selected_rank,
                "position": row.source_position,
                "likeState": row.like_state_snapshot,
                "decision": row.decision,
                "reason": row.decision_reason,
                "parseStatus": articles[row.source_article_id].parse_status,
                "parseStats": _parse_json(articles[row.source_article_id].parse_stats_json),
            }
            for row in selections
            if row.source_article_id in articles and row.readlist_id in readlists
        ],
        "activities": activity_payload,
    }


def _parse_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
