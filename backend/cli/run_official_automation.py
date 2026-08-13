"""Execute one confirmed official run using the application safety policy."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlmodel import select

from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import build_engine, init_database, open_session
from backend.db.models.run import Run, RunItem
from backend.jobs.events import EventHub
from backend.use_cases.official_participation_execution import (
    OfficialParticipationExecutionService,
)
from backend.use_cases.run_execution import RunExecutionService
from backend.use_cases.source_like_automation import SourceLikeAutomationService


class ConsoleEventHub(EventHub):
    """Publish normal application events and mirror safe progress to stdout."""

    async def publish(self, name: str, data: dict[str, Any]) -> None:
        await super().publish(name, data)
        print(
            json.dumps({"event": name, **data}, ensure_ascii=False, sort_keys=True),
            flush=True,
        )


async def execute_confirmed_run(run_id: int) -> dict[str, Any]:
    settings = Settings()
    settings.prepare_directories()
    engine = build_engine(settings)
    init_database(engine)
    browser = BrowserManager(settings)
    events = ConsoleEventHub()
    official_service = OfficialParticipationExecutionService(settings, engine, browser)
    source_like_service = SourceLikeAutomationService(settings, engine, browser)
    runner = RunExecutionService(
        engine,
        browser,
        events,
        settings=settings,
        official_participation_service=official_service,
        source_like_automation_service=source_like_service,
    )

    try:
        run = _load_run(engine, run_id)
        if run.state == "confirmed_waiting_user":
            runner.queue(run_id)
        elif run.state == "waiting_user":
            runner.queue(run_id, resume=True)
        elif run.state != "queued":
            raise ValueError(f"OFFICIAL_AUTOMATION_RUN_NOT_FRESH:{run.state}")
        targets = official_service.validate_run_scope(run_id)
        print(
            json.dumps(
                {
                    "event": "official_automation.scope_validated",
                    "runId": run_id,
                    "targetCount": len(targets),
                    "dynamicIds": list(targets),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        await runner.execute(run_id)
        return _snapshot(engine, run_id)
    finally:
        await browser.close()


def _load_run(engine: Any, run_id: int) -> Run:
    with open_session(engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError("RUN_NOT_FOUND")
        return run


def _snapshot(engine: Any, run_id: int) -> dict[str, Any]:
    with open_session(engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError("RUN_NOT_FOUND")
        items = list(
            session.exec(
                select(RunItem)
                .where(RunItem.run_id == run_id)
                .order_by(RunItem.__table__.c.sequence)  # type: ignore[attr-defined]
            ).all()
        )
        return {
            "event": "official_automation.final_snapshot",
            "runId": run_id,
            "runState": run.state,
            "statusDetail": run.status_detail,
            "items": [
                {
                    "sequence": item.sequence,
                    "dynamicId": item.dynamic_id,
                    "state": item.state,
                    "platformStatus": item.platform_status,
                    "resultCode": item.result_code,
                    "resultMessage": item.result_message,
                }
                for item in items
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute one already-confirmed, allowlisted official run."
    )
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    try:
        snapshot = asyncio.run(execute_confirmed_run(args.run_id))
    except Exception as exc:  # noqa: BLE001 - command must emit a safe failure code
        print(
            json.dumps(
                {
                    "event": "official_automation.command_failed",
                    "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(2) from exc
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)
    if snapshot["runState"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
