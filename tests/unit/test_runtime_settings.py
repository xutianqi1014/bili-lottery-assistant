from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import backend.api.routes.settings as settings_route
from backend.api.routes.settings import UpdateSettingsRequest, update_settings
from backend.config import Settings


def _request(settings: Settings) -> SimpleNamespace:
    app_state = SimpleNamespace(settings=settings)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_state=app_state)))


def test_unofficial_automation_is_enabled_by_default_and_script_accounts_are_seeded() -> None:
    settings = Settings()

    assert settings.unofficial_automation_enabled is True
    assert settings.unofficial_automation_delay_min_sec == 1.0
    assert settings.unofficial_automation_delay_max_sec == 2.0
    assert settings.unofficial_mention_name_list == (
        "你的抽奖工具人",
        "哔哩哔哩弹幕网",
        "哔哩哔哩足球赛事",
    )


def test_html_settings_update_changes_runtime_values_without_returning_api_key(monkeypatch) -> None:
    settings = Settings()
    payload = UpdateSettingsRequest(
        deepseekApiKey="sk-runtime-only",
        deepseekApiUrl="https://api.deepseek.com/chat/completions",
        deepseekModel="deepseek-chat",
        mentionNames=["账号甲", "@账号乙", "账号丙"],
    )

    monkeypatch.setattr(
        settings_route,
        "get_state",
        lambda _request: SimpleNamespace(settings=settings),
    )
    result = update_settings(payload, _request(settings))

    assert settings.deepseek_api_key == "sk-runtime-only"
    assert settings.deepseek_model == "deepseek-chat"
    assert settings.unofficial_mention_name_list == ("账号甲", "账号乙", "账号丙")
    assert result["deepseekConfigured"] is True
    assert "deepseekApiKey" not in result


def test_html_settings_reject_more_than_three_fixed_accounts() -> None:
    with pytest.raises(ValidationError, match="MENTION_NAMES_MAX_THREE"):
        UpdateSettingsRequest(mentionNames=["一", "二", "三", "四"])
