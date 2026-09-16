import json

from sqlalchemy import text, update
from sqlmodel import Session, select

from backend.db.models.source import Readlist, SourceProfile


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
            "sourcePages": [
                {
                    "mid": "100680137",
                    "uploadUrl": "https://space.bilibili.com/100680137/upload/opus",
                    "readlistStrategy": "families",
                },
                {
                    "mid": "280604312",
                    "uploadUrl": "https://space.bilibili.com/280604312/upload/opus",
                    "readlistStrategy": "named_exact",
                    "readlistName": "抽奖合集",
                    "family": "normal",
                },
            ],
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
            "readlistNamePattern": "^20\d{2}$",
            "activityTypes": ["official", "reservation"],
            "referenceUrls": {
                "sourceArticle": "https://www.bilibili.com/opus/1236417468474327060/?from=readlist",
                "reservation": "https://t.bilibili.com/1221942213171216387?spm_id_from=333.1369.0.0",
            },
        },
    )


def seed_tomato_fries_profile(session: Session) -> SourceProfile:
    """Seed 番茄薯条喵's mixed 互动抽奖 source once per database."""

    return _ensure_profile(
        session,
        source_key="tomato_fries",
        mid="3546836235193146",
        upload_url="https://space.bilibili.com/3546836235193146/upload/opus",
        adapter_key="tomato_fries_v1",
        latest_per_family=3,
        config={
            "displayName": "番茄薯条喵",
            "readlistStrategy": "named",
            "readlistName": "互动抽奖",
            "activityTypes": ["official", "unofficial", "reservation"],
            "excludedSections": ["charge"],
            "referenceUrls": {
                "sourceArticle": "https://www.bilibili.com/opus/1239314926435041298/?from=readlist",
                "upload": "https://space.bilibili.com/3546836235193146/upload/opus",
            },
        },
    )


def seed_builtin_profiles(session: Session) -> list[SourceProfile]:
    """Ensure built-in sources exist and migrate the former standalone 280604312 source."""

    legacy = session.exec(
        select(SourceProfile).where(
            SourceProfile.source_key == "lottery_collection_280604312"
        )
    ).first()
    default_profile = seed_default_profile(session)
    if legacy is not None and legacy.enabled:
        legacy.enabled = False
        session.add(legacy)
        session.commit()
    if legacy is not None and legacy.id is not None and default_profile.id is not None:
        session.exec(
            update(Readlist)
            .where(Readlist.__table__.c.source_profile_id == legacy.id)  # type: ignore[attr-defined]
            .values(source_profile_id=default_profile.id)
        )
        session.commit()

    return [
        default_profile,
        seed_nuomi_backpack_profile(session),
        seed_tomato_fries_profile(session),
    ]


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
        changed = False
        missing = {key: value for key, value in config.items() if key not in current_config}
        if (
            source_key == "lottery_toolman"
            and current_config.get("displayName") == "默认抽奖来源"
        ):
            current_config["displayName"] = config["displayName"]
            missing["displayName"] = config["displayName"]
        if source_key == "lottery_toolman" and existing.latest_per_family != latest_per_family:
            existing.latest_per_family = latest_per_family
            changed = True
        if missing:
            current_config.update(missing)
            existing.config_json = json.dumps(current_config, ensure_ascii=False)
            changed = True
        if changed:
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