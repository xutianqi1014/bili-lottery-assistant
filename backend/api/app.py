import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.dependencies import AppState
from backend.api.routes import (
    desktop,
    discoveries,
    events,
    health,
    preflight,
    problems,
    runs,
    settings,
    sources,
)
from backend.browser.manager import BrowserManager
from backend.config import get_settings
from backend.db.engine import build_engine, init_database, open_session
from backend.db.repositories.profiles import seed_builtin_profiles
from backend.integrations.deepseek import DeepSeekCommentGenerator
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = build_engine(settings)
    init_database(engine)
    with open_session(engine) as session:
        seed_builtin_profiles(session)
    events_hub = EventHub()
    browser = BrowserManager(settings)
    jobs = JobRunner(events_hub)
    service = DiscoveryService(settings, engine, browser, events_hub)
    plan_service = ExecutionPlanService(settings, engine, events_hub)
    automatic_plan_service = AutomaticExecutionPlanService(
        engine,
        events_hub,
        plan_service,
    )
    official_participation_execution_service = OfficialParticipationExecutionService(
        settings,
        engine,
        browser,
    )
    source_like_automation_service = SourceLikeAutomationService(
        settings,
        engine,
        browser,
    )
    deepseek_comment_generator = DeepSeekCommentGenerator(settings)
    unofficial_participation_execution_service = UnofficialParticipationExecutionService(
        settings,
        engine,
        browser,
        comment_generator=deepseek_comment_generator,
    )
    execution_service = RunExecutionService(
        engine,
        browser,
        events_hub,
        settings=settings,
        official_participation_service=official_participation_execution_service,
        source_like_automation_service=source_like_automation_service,
        unofficial_participation_service=unofficial_participation_execution_service,
    )
    desktop_lifecycle: DesktopLifecycle = app.state.desktop_lifecycle
    app.state.app_state = AppState(
        settings=settings,
        engine=engine,
        browser=browser,
        events=events_hub,
        jobs=jobs,
        discovery_service=service,
        automatic_plan_service=automatic_plan_service,
        plan_service=plan_service,
        execution_service=execution_service,
        official_participation_execution_service=official_participation_execution_service,
        source_like_automation_service=source_like_automation_service,
        unofficial_participation_execution_service=unofficial_participation_execution_service,
        desktop_lifecycle=desktop_lifecycle,
        csrf_token=secrets.token_urlsafe(32),
    )
    try:
        yield
    finally:
        await desktop_lifecycle.close()
        await jobs.shutdown()
        await browser.close()
        engine.dispose()


def create_app(*, desktop_lifecycle: DesktopLifecycle | None = None) -> FastAPI:
    app = FastAPI(title="B站互动抽奖助手", version=get_settings().version, lifespan=lifespan)
    app.state.desktop_lifecycle = desktop_lifecycle or DesktopLifecycle(enabled=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.include_router(health.router)
    app.include_router(desktop.router)
    app.include_router(sources.router)
    app.include_router(discoveries.router)
    app.include_router(preflight.router)
    app.include_router(runs.router)
    app.include_router(events.router)
    app.include_router(problems.router)
    app.include_router(settings.router)
    dist = get_settings().frontend_dist_dir
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

    return app


app = create_app()
