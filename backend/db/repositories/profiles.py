import json

from sqlalchemy import text
from sqlmodel import Session, select

from backend.db.models.source import SourceProfile


def list_profiles(session: Session) -> list[SourceProfile]:
    return list(session.exec(select(SourceProfile).order_by(text("id"))).all())


def get_profile(session: Session, profile_id: int) -> SourceProfile | None:
    return session.get(SourceProfile, profile_id)


def get_enabled_profile(session: Session, profile_id: int) -> SourceProfile:
    profile = session.get(SourceProfile, profile_id)
    if profile is None or not profile.enabled:
        raise ValueError("SOURCE_PROFILE_NOT_ENABLED")
    return profile


def seed_default_profile(session: Session) -> SourceProfile:
    return _ensure_profile(
        session,
        source_key="lottery_toolman",
        mid="100680137",
        upload_url="https://space.bilibili.com/100680137/upload/opus",
        adapter_key="lottery_toolman_v1",
        latest_per_family=5,
        config={
            "displayName": "你的抽奖工具人",
            "activityTypes": ["official", "unofficial"],
            "families": {
                "normal": {"execution_mode": "unofficial"},
                "official": {"execution_mode": "official"},
            },
        },
    )


def seed_nuomi_backpack_profile(session: Session) -> SourceProfile:
    """Seed 糯米是个背包's year-collection source once per database."""

    return _ensure_profile(
        session,
        source_key="nuomi_backpack",
        mid="492426375",
        upload_url="https://space.bilibili.com/492426375/upload/opus",
        adapter_key="nuomi_backpack_v1",
        latest_per_family=3,
        config={
            "displayName": "糯米是个背包",
            "readlistStrategy": "largest_year",
            "readlistNamePattern": "^20\\d{2}$",
            "activityTypes": ["official", "reservation"],
            "referenceUrls": {
                "sourceArticle": "https://www.bilibili.com/opus/1236417468474327060/?from=readlist",
                "reservation": "https://t.bilibili.com/1221942213171216387?spm_id_from=333.1369.0.0",
            },
        },
    )


def seed_builtin_profiles(session: Session) -> list[SourceProfile]:
    """Ensure all built-in UP profiles exist without changing user settings."""

    return [seed_default_profile(session), seed_nuomi_backpack_profile(session)]


def _ensure_profile(
    session: Session,
    *,
    source_key: str,
    mid: str,
    upload_url: str,
    adapter_key: str,
    latest_per_family: int,
    config: dict[str, object],
) -> SourceProfile:
    existing = session.exec(
        select(SourceProfile).where(SourceProfile.source_key == source_key)
    ).first()
    if existing:
        try:
            current_config = json.loads(existing.config_json)
        except json.JSONDecodeError:
            current_config = {}
        if not isinstance(current_config, dict):
            current_config = {}
        missing = {key: value for key, value in config.items() if key not in current_config}
        # Rename the original built-in label for existing databases, but do
        # not overwrite a display name that the user explicitly customized.
        if (
            source_key == "lottery_toolman"
            and current_config.get("displayName") == "默认抽奖来源"
        ):
            current_config["displayName"] = config["displayName"]
            missing = {**missing, "displayName": config["displayName"]}
        if missing:
            existing.config_json = json.dumps(
                {**current_config, **missing}, ensure_ascii=False
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing
    profile = SourceProfile(
        source_key=source_key,
        platform="bilibili",
        mid=mid,
        upload_url=upload_url,
        adapter_key=adapter_key,
        latest_per_family=latest_per_family,
        config_json=json.dumps(config, ensure_ascii=False),
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile
