"""Automatically create one reviewable run plan after source discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlmodel import select

from backend.db.engine import open_session
from backend.db.models.run import Run
from backend.db.repositories import activities, discoveries
from backend.jobs.events import EventHub
from backend.use_cases.execution_plan import ExecutionPlanService, PlanRequest


@dataclass(frozen=True, slots=True)
class AutomaticPlanResult:
    state: str
    discovery_id: int
    candidate_count: int
    run_id: int | None = None
    error_code: str | None = None


class AutomaticExecutionPlanService:
    """Create at most one default plan when discovery has activity candidates."""

    def __init__(
        self,
        engine: Engine,
        events: EventHub,
        plan_service: ExecutionPlanService,
    ) -> None:
        self.engine = engine
        self.events = events
        self.plan_service = plan_service

    async def create_if_needed(self, discovery_id: int) -> AutomaticPlanResult:
        discovery_state, candidate_count, existing_run = self._read_scope(discovery_id)
        if discovery_state != "preview_ready":
            return AutomaticPlanResult(
                state="discovery_not_ready",
                discovery_id=discovery_id,
                candidate_count=candidate_count,
            )

        if existing_run is not None:
            assert existing_run.id is not None
            self._record_status(
                discovery_id,
                state="created",
                candidate_count=candidate_count,
                run_id=existing_run.id,
            )
            await self.plan_service.publish_created(existing_run)
            return AutomaticPlanResult(
                state="reused",
                discovery_id=discovery_id,
                candidate_count=candidate_count,
                run_id=existing_run.id,
            )

        if candidate_count == 0:
            self._record_status(
                discovery_id,
                state="skipped_no_candidates",
                candidate_count=0,
            )
            await self.events.publish(
                "discovery.plan_skipped",
                {
                    "discoveryId": discovery_id,
                    "state": "skipped_no_candidates",
                    "candidateCount": 0,
                },
            )
            return AutomaticPlanResult(
                state="skipped_no_candidates",
                discovery_id=discovery_id,
                candidate_count=0,
            )

        try:
            run = self.plan_service.create(PlanRequest(discovery_id=discovery_id))
        except Exception as exc:  # noqa: BLE001 - persist a safe local failure state
            error_code = (
                str(exc)
                if isinstance(exc, ValueError)
                else f"AUTOMATIC_PLAN_CREATION_{type(exc).__name__.upper()}"
            )
            self._record_status(
                discovery_id,
                state="failed",
                candidate_count=candidate_count,
                error_code=error_code,
            )
            await self.events.publish(
                "discovery.plan_failed",
                {
                    "discoveryId": discovery_id,
                    "state": "failed",
                    "candidateCount": candidate_count,
                    "errorCode": error_code,
                },
            )
            return AutomaticPlanResult(
                state="failed",
                discovery_id=discovery_id,
                candidate_count=candidate_count,
                error_code=error_code,
            )

        assert run.id is not None
        self._record_status(
            discovery_id,
            state="created",
            candidate_count=candidate_count,
            run_id=run.id,
        )
        await self.plan_service.publish_created(run)
        return AutomaticPlanResult(
            state="created",
            discovery_id=discovery_id,
            candidate_count=candidate_count,
            run_id=run.id,
        )

    def _read_scope(self, discovery_id: int) -> tuple[str, int, Run | None]:
        with open_session(self.engine) as session:
            discovery = discoveries.get_discovery(session, discovery_id)
            if discovery is None:
                raise ValueError("DISCOVERY_NOT_FOUND")
            candidate_count = len(
                activities.list_for_discovery(session, discovery_id)
            )
            existing_run = session.exec(
                select(Run)
                .where(Run.discovery_run_id == discovery_id)
                .order_by(Run.__table__.c.id.desc())  # type: ignore[attr-defined]
            ).first()
            return discovery.state, candidate_count, existing_run

    def _record_status(
        self,
        discovery_id: int,
        *,
        state: str,
        candidate_count: int,
        run_id: int | None = None,
        error_code: str | None = None,
    ) -> None:
        with open_session(self.engine) as session:
            discovery = discoveries.get_discovery(session, discovery_id)
            if discovery is None:
                raise ValueError("DISCOVERY_NOT_FOUND")
            stats = _load_json_object(discovery.stats_json)
            stats["automaticPlanState"] = state
            stats["automaticPlanCandidateCount"] = candidate_count
            if run_id is None:
                stats.pop("automaticPlanRunId", None)
            else:
                stats["automaticPlanRunId"] = run_id
            if error_code is None:
                stats.pop("automaticPlanErrorCode", None)
            else:
                stats["automaticPlanErrorCode"] = error_code
            discoveries.update_stats(session, discovery, stats)


def _load_json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
