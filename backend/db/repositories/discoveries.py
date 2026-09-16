import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import Session, select

from backend.db.models.discovery import DiscoveryRun, DiscoverySelection
from backend.db.models.source import Readlist, SourceArticle


def _now() -> datetime:
    return datetime.now(UTC)


def create_discovery(session: Session, profile_id: int, latest_per_family: int) -> DiscoveryRun:
    discovery = DiscoveryRun(
        source_profile_id=profile_id,
        latest_per_family=latest_per_family,
        state="running",
    )
    session.add(discovery)
    session.commit()
    session.refresh(discovery)
    return discovery


def get_discovery(session: Session, discovery_id: int) -> DiscoveryRun | None:
    return session.get(DiscoveryRun, discovery_id)


def save_preview(
    session: Session,
    discovery: DiscoveryRun,
    selected_readlists: list[Readlist],
    stats: dict,
) -> None:
    discovery.selected_readlists_json = json.dumps(
        [
            {
                "id": row.id,
                "rl_id": row.rl_id,
                "title": row.title,
                "url": row.canonical_url,
                "family": row.family,
                "suffix_value": row.suffix_value,
                "item_count": row.item_count,
                "source_mid": row.source_mid,
            }
            for row in selected_readlists
        ],
        ensure_ascii=False,
    )
    discovery.stats_json = json.dumps(stats, ensure_ascii=False)
    discovery.state = "preview_ready"
    discovery.finished_at = _now()
    session.add(discovery)
    session.commit()


def update_stats(session: Session, discovery: DiscoveryRun, stats: dict) -> None:
    discovery.stats_json = json.dumps(stats, ensure_ascii=False)
    session.add(discovery)
    session.commit()


def mark_failed(session: Session, discovery: DiscoveryRun, code: str, detail: str) -> None:
    discovery.state = "failed"
    discovery.error_code = code
    discovery.error_detail = detail[:1000]
    discovery.finished_at = _now()
    session.add(discovery)
    session.commit()


def add_selection(
    session: Session,
    discovery_id: int,
    article: SourceArticle,
    readlist: Readlist,
    rank: int,
    source_position: int,
    like_state: str,
    decision: str,
    reason: str,
) -> None:
    assert article.id is not None
    assert readlist.id is not None
    session.add(
        DiscoverySelection(
            discovery_run_id=discovery_id,
            source_article_id=article.id,
            readlist_id=readlist.id,
            family=readlist.family,
            selected_rank=rank,
            source_position=source_position,
            like_state_snapshot=like_state,
            decision=decision,
            decision_reason=reason,
        )
    )


def list_selections(session: Session, discovery_id: int) -> list[DiscoverySelection]:
    return list(
        session.exec(
            select(DiscoverySelection)
            .where(DiscoverySelection.discovery_run_id == discovery_id)
            .order_by(text("family"), text("selected_rank"))
        ).all()
    )
