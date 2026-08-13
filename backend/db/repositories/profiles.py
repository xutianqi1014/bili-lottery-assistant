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
    existing = session.exec(
        select(SourceProfile).where(SourceProfile.source_key == "lottery_toolman")
    ).first()
    if existing:
        return existing
    profile = SourceProfile(
        source_key="lottery_toolman",
        platform="bilibili",
        mid="100680137",
        upload_url="https://space.bilibili.com/100680137/upload/opus",
        adapter_key="lottery_toolman_v1",
        config_json=(
            '{"families":{"normal":{"execution_mode":"unofficial"},'
            '"official":{"execution_mode":"official"}}}'
        ),
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile
