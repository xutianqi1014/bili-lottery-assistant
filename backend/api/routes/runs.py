import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.api.dependencies import get_state, require_csrf
from backend.db.models.run import Run, RunItem
from backend.use_cases.execution_plan import PlanRequest
from backend.use_cases.run_stats import reconcile_run_item_stats
from backend.use_cases.source_closure import SourceClosureSummary

router = APIRouter(tags=["runs"])


class CreateRunRequest(BaseModel):
    discovery_run_id: int = Field(alias="discoveryRunId")
    source_article_ids: list[int] = Field(default_factory=list, alias="sourceArticleIds")
    activity_ids: list[int] = Field(default_factory=list, alias="activityIds")
    family_order: list[str] = Field(
        default_factory=lambda: ["normal", "official"], alias="familyOrder"
    )
    execution_policy: Literal["confirm_each"] = Field(
        default="confirm_each", alias="executionPolicy"
    )

    model_config = {"populate_by_name": True}


class ConfirmRunRequest(BaseModel):
    note: str = "用户已确认计划"


@router.post("/api/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: CreateRunRequest,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    state = get_state(request)
    try:
        run = state.plan_service.create(
            PlanRequest(
                discovery_id=payload.discovery_run_id,
                activity_ids=tuple(payload.activity_ids),
                source_article_ids=tuple(payload.source_article_ids),
                family_order=tuple(payload.family_order),
                execution_policy=payload.execution_policy,
            )
        )
        await state.plan_service.publish_created(run)
        return _serialize_run_for_state(state, *state.plan_service.get_snapshot(run.id or 0))
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code in {"DISCOVERY_NOT_FOUND", "RUN_NOT_FOUND"} else 409
        raise HTTPException(status_code=status_code, detail=code) from exc


@router.get("/api/runs/{run_id}")
def get_run(run_id: int, request: Request) -> dict[str, Any]:
    state = get_state(request)
    try:
        snapshot = state.plan_service.get_snapshot(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_run_for_state(state, *snapshot)


@router.get("/api/runs/{run_id}/source-closure")
def get_source_closure(run_id: int, request: Request) -> dict[str, Any]:
    state = get_state(request)
    try:
        return state.execution_service.get_source_closure(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/runs/{run_id}/confirm")
async def confirm_run(
    run_id: int,
    payload: ConfirmRunRequest,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    state = get_state(request)
    try:
        run = state.plan_service.confirm(run_id, payload.note)
        await state.plan_service.publish_confirmed(run)
        return _serialize_run_for_state(state, *state.plan_service.get_snapshot(run_id))
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code == "RUN_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=code) from exc


@router.post("/api/runs/{run_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    run_id: int,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    return await _queue_execution(request, run_id, resume=False)


@router.post("/api/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_run(
    run_id: int,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    return await _queue_execution(request, run_id, resume=True)


@router.post("/api/runs/{run_id}/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart_run(
    run_id: int,
    request: Request,
    _csrf: Any = Depends(require_csrf),
) -> dict[str, Any]:
    """Re-check the current item after the user fixes it manually.

    Unlike ``resume``, this endpoint first clears the current item-level
    manual-review result and then queues the same immutable run.  Terminal
    items are left untouched, so a restart cannot replay already completed
    or skipped dynamics.
    """

    state = get_state(request)
    try:
        current, _items = state.plan_service.get(run_id)
        previous_state = current.state
        state.execution_service.prepare_restart(run_id)
        state.execution_service.queue(run_id, resume=True)
        try:
            state.jobs.submit(
                f"run:{run_id}", lambda: state.execution_service.execute(run_id)
            )
        except RuntimeError as exc:
            state.execution_service.rollback_queue(run_id, previous_state)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await state.events.publish(
            "run.restarted",
            {
                "runId": run_id,
                "state": "queued",
                "previousState": previous_state,
            },
        )
        return _serialize_run_for_state(state, *state.plan_service.get_snapshot(run_id))
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code == "RUN_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=code) from exc


async def _queue_execution(
    request: Request,
    run_id: int,
    *,
    resume: bool,
) -> dict[str, Any]:
    state = get_state(request)
    previous_state = "waiting_user" if resume else "confirmed_waiting_user"
    if resume:
        try:
            current, _items = state.plan_service.get(run_id)
            previous_state = current.state
        except ValueError:
            previous_state = "waiting_user"
    try:
        state.execution_service.queue(run_id, resume=resume)
        try:
            state.jobs.submit(
                f"run:{run_id}", lambda: state.execution_service.execute(run_id)
            )
        except RuntimeError as exc:
            state.execution_service.rollback_queue(run_id, previous_state)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _serialize_run_for_state(state, *state.plan_service.get_snapshot(run_id))
    except ValueError as exc:
        code = str(exc)
        status_code = 404 if code == "RUN_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=code) from exc


def _serialize_run(
    run: Run,
    items: list[RunItem],
    *,
    source_closure: dict[str, Any] | None = None,
    official_automation_enabled: bool = False,
    official_automation_delay_min_sec: float = 3.0,
    official_automation_delay_max_sec: float = 5.0,
    source_like_automation_enabled: bool = False,
    source_like_automation_max_items_per_run: int = 15,
    source_like_automation_delay_min_sec: float = 3.0,
    source_like_automation_delay_max_sec: float = 5.0,
    unofficial_automation_enabled: bool = False,
    unofficial_automation_delay_min_sec: float = 1.0,
    unofficial_automation_delay_max_sec: float = 2.0,
    deepseek_configured: bool = False,
) -> dict[str, Any]:
    loaded_stats = _load_json(run.stats_json)
    stats = reconcile_run_item_stats(
        loaded_stats if isinstance(loaded_stats, dict) else {},
        items,
    )
    if source_closure is not None:
        stats["sourceClosure"] = source_closure
    return {
        "id": run.id,
        "discoveryRunId": run.discovery_run_id,
        "state": run.state,
        "executionPolicy": run.execution_policy,
        "familyOrder": _load_json(run.family_order_json),
        "stats": stats,
        "directWriteEnabled": run.direct_write_enabled_snapshot,
        "officialAutomationEnabled": official_automation_enabled,
        "officialAutomationDelayMinSec": official_automation_delay_min_sec,
        "officialAutomationDelayMaxSec": official_automation_delay_max_sec,
        "sourceLikeAutomationEnabled": source_like_automation_enabled,
        "sourceLikeAutomationMaxItemsPerRun": source_like_automation_max_items_per_run,
        "sourceLikeAutomationDelayMinSec": source_like_automation_delay_min_sec,
        "sourceLikeAutomationDelayMaxSec": source_like_automation_delay_max_sec,
        "unofficialAutomationEnabled": unofficial_automation_enabled,
        "unofficialAutomationDelayMinSec": unofficial_automation_delay_min_sec,
        "unofficialAutomationDelayMaxSec": unofficial_automation_delay_max_sec,
        "deepseekConfigured": deepseek_configured,
        "confirmationNote": run.confirmation_note,
        "statusDetail": run.status_detail,
        "createdAt": run.created_at.isoformat(),
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "confirmedAt": run.confirmed_at.isoformat() if run.confirmed_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        "items": [
            {
                "activityId": item.activity_id,
                "sequence": item.sequence,
                "dynamicId": item.dynamic_id,
                "url": item.canonical_url,
                "title": item.title,
                "family": item.family,
                "sourceSection": item.source_section,
                "mode": item.mode,
                "unofficialType": item.unofficial_type,
                "platformStatus": item.platform_status,
                "sourceArticleIds": _load_json(item.source_article_ids_json),
                "actionPlan": _load_json(item.action_plan_json),
                "state": item.state,
                "blockReason": item.block_reason,
                "runtimeInspectedAt": (
                    item.runtime_inspected_at.isoformat()
                    if item.runtime_inspected_at
                    else None
                ),
                "runtimeSelectorVersion": item.runtime_selector_version,
                "runtimeInspection": _load_json(item.runtime_inspection_json),
                "resultCode": item.result_code,
                "resultMessage": item.result_message,
            }
            for item in items
        ],
    }


def _serialize_run_for_state(
    state: Any, run: Run, items: list[RunItem], source_closure: SourceClosureSummary,
) -> dict[str, Any]:
    assert run.id is not None
    return _serialize_run(
        run,
        items,
        source_closure=source_closure.to_payload(),
        official_automation_enabled=state.settings.official_automation_enabled,
        official_automation_delay_min_sec=state.settings.official_automation_delay_min_sec,
        official_automation_delay_max_sec=state.settings.official_automation_delay_max_sec,
        source_like_automation_enabled=state.settings.source_like_automation_enabled,
        source_like_automation_max_items_per_run=(
            state.settings.source_like_automation_max_items_per_run
        ),
        source_like_automation_delay_min_sec=(
            state.settings.source_like_automation_delay_min_sec
        ),
        source_like_automation_delay_max_sec=(
            state.settings.source_like_automation_delay_max_sec
        ),
        unofficial_automation_enabled=state.settings.unofficial_automation_enabled,
        unofficial_automation_delay_min_sec=state.settings.unofficial_automation_delay_min_sec,
        unofficial_automation_delay_max_sec=state.settings.unofficial_automation_delay_max_sec,
        deepseek_configured=state.settings.deepseek_configured,
    )


def _load_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []
