from datetime import UTC, datetime

from sqlmodel import Session, select

from backend.db.models.activity import Activity, ActivityOrigin
from backend.db.models.discovery import DiscoverySelection
from backend.db.models.source import SourceArticle
from backend.domain.entities import ActivityRef


def _now() -> datetime:
    return datetime.now(UTC)


def upsert_activity(session: Session, ref: ActivityRef) -> Activity:
    activity = session.exec(select(Activity).where(Activity.dynamic_id == ref.dynamic_id)).first()
    if activity is None:
        activity = Activity(
            dynamic_id=ref.dynamic_id,
            canonical_url=ref.canonical_url,
            title=ref.title,
        )
    activity.canonical_url = ref.canonical_url
    if ref.title:
        activity.title = ref.title
    activity.updated_at = _now()
    session.add(activity)
    session.flush()
    return activity


def add_origin(
    session: Session,
    source_article_id: int,
    activity: Activity,
    source_position: int,
    discovery_id: int,
    source_section: str | None = None,
) -> bool:
    assert activity.id is not None
    origin = session.get(ActivityOrigin, (source_article_id, activity.id, discovery_id))
    created = origin is None
    if origin is None:
        origin = ActivityOrigin(
            source_article_id=source_article_id,
            activity_id=activity.id,
            source_position=source_position,
            source_section=source_section,
            discovered_in_run_id=discovery_id,
        )
    origin.source_position = source_position
    origin.source_section = source_section
    origin.discovered_in_run_id = discovery_id
    session.add(origin)
    return created


def list_for_discovery(session: Session, discovery_id: int) -> list[Activity]:
    rows = session.exec(
        select(Activity)
        .join(
            ActivityOrigin,
            ActivityOrigin.__table__.c.activity_id == Activity.__table__.c.id,  # type: ignore[attr-defined]
        )
        .where(ActivityOrigin.__table__.c.discovered_in_run_id == discovery_id)  # type: ignore[attr-defined]
        .distinct()
        .order_by(Activity.__table__.c.id)  # type: ignore[attr-defined]
    ).all()
    return list(rows)


def list_origins_for_discovery(
    session: Session, discovery_id: int
) -> list[ActivityOrigin]:
    return list(
        session.exec(
            select(ActivityOrigin).where(ActivityOrigin.discovered_in_run_id == discovery_id)
        ).all()
    )


def list_origins_for_activity(
    session: Session, discovery_id: int, activity_id: int
) -> list[ActivityOrigin]:
    return list(
        session.exec(
            select(ActivityOrigin).where(
                ActivityOrigin.discovered_in_run_id == discovery_id,
                ActivityOrigin.activity_id == activity_id,
            )
        ).all()
    )


OriginContext = tuple[ActivityOrigin, DiscoverySelection, SourceArticle]


def list_origin_contexts(
    session: Session, discovery_id: int, activity_id: int
) -> list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]]:
    return list_origin_contexts_by_activity(session, discovery_id, activity_id).get(activity_id, [])


def list_origin_contexts_by_activity(
    session: Session, discovery_id: int, activity_id: int | None = None
) -> dict[int, list[OriginContext]]:
    """Load a discovery's contexts once, retaining every readlist membership."""
    statement = (
        select(ActivityOrigin, DiscoverySelection, SourceArticle)
        .join(
            DiscoverySelection,
            (DiscoverySelection.__table__.c.source_article_id  # type: ignore[attr-defined]
             == ActivityOrigin.__table__.c.source_article_id)  # type: ignore[attr-defined]
            & (DiscoverySelection.__table__.c.discovery_run_id == discovery_id),  # type: ignore[attr-defined]
        )
        .join(
            SourceArticle,
            SourceArticle.__table__.c.id  # type: ignore[attr-defined]
            == ActivityOrigin.__table__.c.source_article_id,  # type: ignore[attr-defined]
        )
        .where(
            ActivityOrigin.discovered_in_run_id == discovery_id,
        )
    )
    if activity_id is not None:
        statement = statement.where(ActivityOrigin.activity_id == activity_id)
    grouped: dict[int, list[OriginContext]] = {}
    for origin, selection, article in session.exec(statement).all():
        grouped.setdefault(origin.activity_id, []).append((origin, selection, article))
    return grouped
