from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate

from .http_client import get_json

API_URL = "https://api.bilibili.com/x/article/list/web/articles"


async def discover_entries_api(
    readlist: ReadlistCandidate, timeout: float
) -> list[SourceArticleCandidate]:
    payload = await get_json(
        API_URL,
        {"id": readlist.rl_id},
        timeout,
        readlist.canonical_url,
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"ARTICLE_LIST_API_CODE:{payload.get('code')}")
    data = payload.get("data") or {}
    rows = data.get("articles") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise RuntimeError("ARTICLE_LIST_SCHEMA_INVALID")
    candidates: list[SourceArticleCandidate] = []
    for position, row in enumerate(rows, start=1):
        article_id = str(row.get("id") or "").strip()
        if not article_id.isdecimal():
            continue
        candidates.append(
            SourceArticleCandidate(
                article_id=article_id,
                canonical_url=f"https://www.bilibili.com/read/cv{article_id}",
                title=str(row.get("title") or "").strip(),
                position=position,
                published_at=_int_or_none(row.get("publish_time")),
            )
        )
    return candidates


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None
