import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from backend.db.models.run import Run, RunItem


def _now() -> datetime:
    return datetime.now(UTC)


def create_run(
    session: Session,
    *,
    discovery_run_id: int,
    execution_policy: str,
    family_order: list[str],
    source_article_ids: list[int],
    activity_ids: list[int],
    stats: dict[str, object],
    direct_write_enabled: bool,
) -> Run:
    row = Run(
        discovery_run_id=discovery_run_id,
        execution_policy=execution_policy,
        family_order_json=json.dumps(family_order, ensure_ascii=False),
        source_article_ids_json=json.dumps(source_article_ids),
        activity_ids_json=json.dumps(activity_ids),
        stats_json=json.dumps(stats, ensure_ascii=False),
        direct_write_enabled_snapshot=direct_write_enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def add_item(
    session: Session,
    *,
    run_id: int,
    activity_id: int,
    sequence: int,
    dynamic_id: str,
    canonical_url: str,
    title: str,
    family: str,
    source_section: str | None,
    mode: str,
    unofficial_type: str,
    platform_status: str,
    source_article_ids: list[int],
    action_plan: list[str],
    state: str,
    block_reason: str | None,
) -> RunItem:
    item = RunItem(
        run_id=run_id,
        activity_id=activity_id,
        sequence=sequence,
        dynamic_id=dynamic_id,
        canonical_url=canonical_url,
        title=title,
        family=family,
        source_section=source_section,
        mode=mode,
        unofficial_type=unofficial_type,
        platform_status=platform_status,
        source_article_ids_json=json.dumps(source_article_ids),
        action_plan_json=json.dumps(action_plan, ensure_ascii=False),
        state=state,
        block_reason=block_reason,
    )
    session.add(item)
    return item


def get_run(session: Session, run_id: int) -> Run | None:
    return session.get(Run, run_id)


def list_items(session: Session, run_id: int) -> list[RunItem]:
    return list(
        session.exec(
            select(RunItem)
            .where(RunItem.run_id == run_id)
            .order_by(text("sequence"))
        ).all()
    )


def confirm_run(session: Session, run: Run, note: str) -> Run:
    run.state = "confirmed_waiting_user"
    run.confirmation_note = note[:500]
    run.confirmed_at = _now()
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def set_run_state(
    session: Session,
    run: Run,
    *,
    expected: str | tuple[str, ...],
    next_state: str,
    status_detail: str | None = None,
) -> Run:
    expected_states = (expected,) if isinstance(expected, str) else expected
    if run.state not in expected_states:
        raise ValueError("RUN_STATE_CONFLICT")
    run.state = next_state
    run.status_detail = status_detail
    if next_state == "queued":
        run.started_at = None
        run.finished_at = None
    if next_state == "running":
        run.started_at = _now()
    if next_state in {"completed", "failed", "interrupted", "cancelled"}:
        run.finished_at = _now()
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def update_run_stats(session: Session, run: Run, stats: dict[str, Any]) -> Run:
    run.stats_json = json.dumps(stats, ensure_ascii=False)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def update_item_runtime(
    session: Session,
    item: RunItem,
    *,
    mode: str,
    unofficial_type: str,
    platform_status: str,
    runtime_inspected_at: datetime,
    runtime_selector_version: str,
    runtime_inspection: dict[str, Any],
    state: str,
    result_code: str,
    result_message: str,
    block_reason: str | None,
) -> RunItem:
    item.mode = mode
    item.unofficial_type = unofficial_type
    item.platform_status = platform_status
    item.runtime_inspected_at = runtime_inspected_at
    item.runtime_selector_version = runtime_selector_version
    item.runtime_inspection_json = json.dumps(runtime_inspection, ensure_ascii=False)
    item.state = state
    item.result_code = result_code
    item.result_message = result_message
    item.block_reason = block_reason
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
