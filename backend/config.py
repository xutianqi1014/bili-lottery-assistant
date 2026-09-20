from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BILI_", env_file=".env", extra="ignore")

    app_name: str = "Bili Lottery Assistant"
    version: str = "1.6.0"
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path(user_data_dir("BiliLotteryAssistant", "OpenAI"))
    browser_profile_dir: Path | None = None
    browser_channel: str = "msedge"
    browser_headless: bool = False
    request_timeout_sec: float = 30.0
    enable_direct_write_api: bool = False
    official_automation_enabled: bool = True
    official_automation_delay_min_sec: float = 3.0
    official_automation_delay_max_sec: float = 5.0
    source_like_automation_enabled: bool = True
    source_like_automation_delay_min_sec: float = 3.0
    source_like_automation_delay_max_sec: float = 5.0
    source_like_automation_max_items_per_run: int = 15
    source_like_write_allowlist_path: Path | None = None
    unofficial_automation_enabled: bool = True
    unofficial_automation_delay_min_sec: float = 1.0
    unofficial_automation_delay_max_sec: float = 2.0
    unofficial_comment_default: str = "参与抽奖，感谢分享！"
    unofficial_comment_repost_with_comment: bool = True
    # DeepSeek drafts only the non-official comment.  The key is read from
    # the local environment and is never returned by an API response or
    # persisted in the run database.
    deepseek_api_key: str = ""
    deepseek_api_url: str = "https://api.deepseek.com/chat/completions"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_sec: float = 30.0
    deepseek_max_attempts: int = 3
    unofficial_mention_names: str = "你的抽奖工具人,哔哩哔哩弹幕网,哔哩哔哩足球赛事"
    frontend_dist_dir: Path = Path(__file__).resolve().parents[1] / "web_static" / "dist"

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_path.mkdir(parents=True, exist_ok=True)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'assistant.sqlite3').as_posix()}"

    @property
    def browser_profile_path(self) -> Path:
        return self.browser_profile_dir or (self.data_dir / "browser-profile")

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def unofficial_mention_name_list(self) -> tuple[str, ...]:
        """Return at most three fixed, operator-configured mention names."""

        names = tuple(
            name.strip()
            for name in self.unofficial_mention_names.split(",")
            if name.strip()
        )
        return names[:3]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
