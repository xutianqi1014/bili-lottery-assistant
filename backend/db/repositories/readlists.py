import json
from datetime import UTC, datetime

from sqlmodel import Session, select

from backend.db.models.source import Readlist, ReadlistEntry, SourceArticle
from backend.domain.entities import (
    ActivityExtractionResult,
    ReadlistCandidate,
    SourceArticleCandidate,
)


def _now() -> datetime:
    return datetime.now(UTC)


def upsert_readlist(session: Session, profile_id: int, candidate: ReadlistCandidate) -> Readlist:
    readlist = session.exec(
        select(Readlist).where(
            Readlist.source_profile_id == profile_id,
            Readlist.rl_id == candidate.rl_id,
        )
    ).first()
    if readlist is None:
        readlist = Readlist(
            source_profile_id=profile_id,
            rl_id=candidate.rl_id,
            canonical_url=candidate.canonical_url,
            family=candidate.family.value,
            title=candidate.title,
            normalized_title=candidate.normalized_title,
            suffix_value=candidate.suffix_value,
        )
    readlist.canonical_url = candidate.canonical_url
    readlist.family = candidate.family.value
    readlist.title = candidate.title
    readlist.normalized_title = candidate.normalized_title
    readlist.suffix_value = candidate.suffix_value
    readlist.item_count = candidate.item_count
    readlist.display_updated_text = candidate.updated_text
    readlist.source_mid = candidate.source_mid
    readlist.last_seen_at = _now()
    session.add(readlist)
    session.flush()
    return readlist


def upsert_article(session: Session, candidate: SourceArticleCandidate) -> SourceArticle:
    article = session.exec(
        select(SourceArticle).where(SourceArticle.article_id == candidate.article_id)
    ).first()
    if article is None:
        article = SourceArticle(
            article_id=candidate.article_id,
            canonical_url=candidate.canonical_url,
            title=candidate.title,
        )
    article.canonical_url = candidate.canonical_url
    article.title = candidate.title
    session.add(article)
    session.flush()
    return article


def upsert_entry(
    session: Session,
    readlist: Readlist,
    article: SourceArticle,
    candidate: SourceArticleCandidate,
) -> ReadlistEntry:
    assert readlist.id is not None
    assert article.id is not None
    entry = session.get(ReadlistEntry, (readlist.id, article.id))
    if entry is None:
        entry = ReadlistEntry(
            readlist_id=readlist.id,
            source_article_id=article.id,
            position=candidate.position,
        )
    entry.position = candidate.position
    entry.last_seen_at = _now()
    session.add(entry)
    session.flush()
    return entry


def get_article(session: Session, article_id: int) -> SourceArticle | None:
    return session.get(SourceArticle, article_id)


def save_activity_extraction(
    session: Session,
    article: SourceArticle,
    result: ActivityExtractionResult,
) -> None:
    stats = {
        "aggregateExcluded": result.stats.aggregate_excluded,
        "startedAfterPinned": result.stats.started_after_pinned,
        "startMode": result.stats.start_mode,
        "linksSeen": result.stats.links_seen,
        "uniqueLinks": result.stats.unique_links,
    }
    article.content_fingerprint = result.stats.content_fingerprint or None
    article.parse_stats_json = json.dumps(stats, ensure_ascii=False)
    article.parse_status = result.status
    article.parse_error_code = result.reason_code
    article.parse_checked_at = _now()
    session.add(article)
