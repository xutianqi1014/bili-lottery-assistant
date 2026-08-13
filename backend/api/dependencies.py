import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.engine import Engine
from starlette.requests import HTTPConnection

from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.jobs.events import EventHub
from backend.jobs.runner import JobRunner
from backend.runtime import DesktopLifecycle
from backend.use_cases.automatic_execution_plan import AutomaticExecutionPlanService
from backend.use_cases.discover_source import DiscoveryService
from backend.use_cases.execution_plan import ExecutionPlanService
from backend.use_cases.official_participation_execution import (
    OfficialParticipationExecutionService,
)
from backend.use_cases.run_execution import RunExecutionService
from backend.use_cases.source_like_automation import SourceLikeAutomationService
from backend.use_cases.unofficial_participation_execution import (
    UnofficialParticipationExecutionService,
)


@dataclass
class AppState:
    settings: Settings
    engine: Engine
    browser: BrowserManager
    events: EventHub
    jobs: JobRunner
    discovery_service: DiscoveryService
    automatic_plan_service: AutomaticExecutionPlanService
    plan_service: ExecutionPlanService
    execution_service: RunExecutionService
    official_participation_execution_service: OfficialParticipationExecutionService
    source_like_automation_service: SourceLikeAutomationService
    unofficial_participation_execution_service: UnofficialParticipationExecutionService
    desktop_lifecycle: DesktopLifecycle
    csrf_token: str


def get_state(request: HTTPConnection) -> AppState:
    state: Any = getattr(request.app.state, "app_state", None)
    if not isinstance(state, AppState):
        raise RuntimeError("APP_STATE_NOT_READY")
    return state


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    state = get_state(request)
    if x_csrf_token is None or not secrets.compare_digest(x_csrf_token, state.csrf_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="CSRF_REQUIRED")
