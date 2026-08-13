from fastapi import APIRouter, Request

from backend.api.dependencies import get_state

router = APIRouter(tags=["runtime"])


@router.get("/api/health")
def health(request: Request) -> dict[str, object]:
    state = get_state(request)
    return {
        "ok": True,
        "appName": "BiliLotteryAssistant",
        "version": state.settings.version,
        "browserReady": state.browser.ready,
        "desktopLifecycleEnabled": state.desktop_lifecycle.enabled,
    }


@router.get("/api/runtime")
def runtime(request: Request) -> dict[str, object]:
    state = get_state(request)
    return {
        "version": state.settings.version,
        "host": state.settings.host,
        "port": state.settings.port,
        "dataDir": str(state.settings.data_dir),
        "browserReady": state.browser.ready,
        "directWriteApiEnabled": state.settings.enable_direct_write_api,
        "desktopLifecycleEnabled": state.desktop_lifecycle.enabled,
        "desktopClients": state.desktop_lifecycle.active_clients,
    }


@router.get("/api/session")
def session_info(request: Request) -> dict[str, str]:
    state = get_state(request)
    return {"csrfToken": state.csrf_token}
