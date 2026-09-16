import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from backend.api.dependencies import get_state, require_csrf
from backend.db.repositories.profiles import get_profile, list_profiles

router = APIRouter(tags=["sources"])


@router.get("/api/source-profiles")
def source_profiles(request: Request) -> list[dict[str, Any]]:
    state = get_state(request)
    with Session(state.engine) as session:
        rows = list_profiles(session)
    return [
        _serialize_profile(row)
        for row in rows
    ]


@router.get("/api/source-profiles/{profile_id}")
def source_profile(profile_id: int, request: Request) -> dict[str, Any]:
    state = get_state(request)
    with Session(state.engine) as session:
        row = get_profile(session, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SOURCE_PROFILE_NOT_FOUND")
    return {**_serialize_profile(row), "config": json.loads(row.config_json)}


def _serialize_profile(row: Any) -> dict[str, Any]:
    try:
        config = json.loads(row.config_json)
    except json.JSONDecodeError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    source_pages = _source_pages(config, row)
    return {
        "id": row.id,
        "sourceKey": row.source_key,
        "displayName": str(config.get("displayName") or row.source_key),
        "platform": row.platform,
        "mid": row.mid,
        "uploadUrl": row.upload_url,
        "adapterKey": row.adapter_key,
        "enabled": row.enabled,
        "latestPerFamily": row.latest_per_family,
        "sourcePages": source_pages,
        "activityTypes": [
            value
            for value in config.get("activityTypes", [])
            if isinstance(value, str)
        ],
        "lastDiscoveryAt": row.last_discovery_at.isoformat() if row.last_discovery_at else None,
    }



def _source_pages(config: dict[str, Any], row: Any) -> list[dict[str, str]]:
    raw_pages = config.get("sourcePages")
    pages: list[dict[str, str]] = []
    if isinstance(raw_pages, list):
        for raw_page in raw_pages:
            if not isinstance(raw_page, dict):
                continue
            mid = str(raw_page.get("mid") or "").strip()
            upload_url = str(raw_page.get("uploadUrl") or "").strip()
            if mid and upload_url:
                pages.append({"mid": mid, "uploadUrl": upload_url})
    if pages:
        return pages
    return [{"mid": str(row.mid), "uploadUrl": str(row.upload_url)}]

@router.post("/api/account/open-login", dependencies=[Depends(require_csrf)])
async def open_login(request: Request) -> dict[str, bool]:
    state = get_state(request)
    try:
        await state.browser.login_page()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="BROWSER_UNAVAILABLE") from exc
    return {"ok": True}
