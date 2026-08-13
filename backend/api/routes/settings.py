from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.dependencies import get_state, require_csrf

router = APIRouter(tags=["settings"])

_MAX_MENTION_NAMES = 3


class UpdateSettingsRequest(BaseModel):
    deepseek_api_key: str | None = Field(default=None, alias="deepseekApiKey", max_length=512)
    clear_deepseek_api_key: bool = Field(default=False, alias="clearDeepseekApiKey")
    deepseek_api_url: str | None = Field(default=None, alias="deepseekApiUrl", max_length=500)
    deepseek_model: str | None = Field(default=None, alias="deepseekModel", max_length=120)
    mention_names: list[str] | None = Field(default=None, alias="mentionNames")

    model_config = {"populate_by_name": True}

    @field_validator("deepseek_api_url")
    @classmethod
    def validate_api_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return value
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("DEEPSEEK_API_URL_INVALID")
        if parsed.username or parsed.password:
            raise ValueError("DEEPSEEK_API_URL_CREDENTIALS_NOT_ALLOWED")
        return value.strip()

    @field_validator("deepseek_model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("DEEPSEEK_MODEL_EMPTY")
        return cleaned

    @field_validator("mention_names")
    @classmethod
    def validate_mention_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(value) > _MAX_MENTION_NAMES:
            raise ValueError("MENTION_NAMES_MAX_THREE")
        cleaned = [name.strip().lstrip("@") for name in value if name.strip().lstrip("@")]
        if any("," in name or "，" in name for name in cleaned):
            raise ValueError("MENTION_NAME_MUST_BE_SINGLE_ACCOUNT")
        return cleaned


def _serialize_settings(state: Any) -> dict[str, object]:
    settings = state.settings
    return {
        "deepseekConfigured": settings.deepseek_configured,
        "deepseekApiUrl": settings.deepseek_api_url,
        "deepseekModel": settings.deepseek_model,
        "mentionNames": list(settings.unofficial_mention_name_list),
        "unofficialAutomationEnabled": settings.unofficial_automation_enabled,
        "unofficialAutomationDelayMinSec": settings.unofficial_automation_delay_min_sec,
        "unofficialAutomationDelayMaxSec": settings.unofficial_automation_delay_max_sec,
    }


@router.get("/api/settings")
def get_settings(request: Request) -> dict[str, object]:
    return _serialize_settings(get_state(request))


@router.post("/api/settings", dependencies=[Depends(require_csrf)])
def update_settings(payload: UpdateSettingsRequest, request: Request) -> dict[str, object]:
    state = get_state(request)
    settings = state.settings
    if payload.clear_deepseek_api_key:
        settings.deepseek_api_key = ""
    elif payload.deepseek_api_key is not None and payload.deepseek_api_key.strip():
        settings.deepseek_api_key = payload.deepseek_api_key.strip()
    if payload.deepseek_api_url is not None:
        settings.deepseek_api_url = payload.deepseek_api_url
    if payload.deepseek_model is not None:
        settings.deepseek_model = payload.deepseek_model
    if payload.mention_names is not None:
        settings.unofficial_mention_names = ",".join(payload.mention_names[:_MAX_MENTION_NAMES])
    return _serialize_settings(state)


__all__ = ["router"]
