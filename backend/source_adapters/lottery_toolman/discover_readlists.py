"""Readlist HTTP envelope and conversion shared by narrow title selectors."""

from collections.abc import Callable, Collection

from backend.domain.entities import ReadlistCandidate
from backend.domain.enums import SourceFamily

from .http_client import get_json
from .title_rules import normalize_text, parse_title_family

API_URL = "https://api.bilibili.com/x/article/up/lists"


async def discover_named_readlists_api(
    mid: str, timeout: float, names: Collection[str]
) -> list[ReadlistCandidate]:
    """Match normalized exact names, retaining the mixed official family."""
    normalized_names = {normalize_text(name) for name in names if normalize_text(name)}
    if not normalized_names:
        return []

    def select(title: str) -> tuple[SourceFamily, int] | None:
        return (SourceFamily.OFFICIAL, 0) if normalize_text(title) in normalized_names else None

    return await _discover_readlists(mid, timeout, select)


async def discover_readlists_api(mid: str, timeout: float) -> list[ReadlistCandidate]:
    return await _discover_readlists(mid, timeout, parse_title_family)


async def discover_year_readlist_api(mid: str, timeout: float) -> list[ReadlistCandidate]:
    """Match raw four-digit years in the inclusive 2000–2100 range."""
    def select(title: str) -> tuple[SourceFamily, int] | None:
        if title.isdecimal() and len(title) == 4 and 2000 <= int(title) <= 2100:
            return SourceFamily.OFFICIAL, int(title)
        return None

    return await _discover_readlists(mid, timeout, select)


async def _discover_readlists(
    mid: str,
    timeout: float,
    select: Callable[[str], tuple[SourceFamily, int] | None],
) -> list[ReadlistCandidate]:
    payload = await get_json(
        API_URL,
        {"mid": mid, "sort": 0},
        timeout,
        f"https://space.bilibili.com/{mid}/upload/opus",
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"READLIST_API_CODE:{payload.get('code')}")
    data = payload.get("data") or {}
    rows = data.get("lists") or []
    candidates: list[ReadlistCandidate] = []
    for row in rows:
        title = str(row.get("name") or row.get("title") or "").strip()
        family_suffix = select(title)
        if family_suffix is None:
            continue
        family, suffix = family_suffix
        rl_id = str(row.get("id") or "")
        if not rl_id.isdecimal():
            continue
        candidates.append(
            ReadlistCandidate(
                rl_id=rl_id,
                canonical_url=f"https://www.bilibili.com/read/readlist/rl{rl_id}",
                title=title,
                normalized_title=normalize_text(title),
                family=family,
                suffix_value=suffix,
                item_count=(
                    int(row["articles_count"])
                    if row.get("articles_count") is not None
                    else None
                ),
                updated_text=None,
                observed_updated_at=_timestamp(row.get("update_time")),
            )
        )
    return candidates


def _timestamp(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(str(value))
        if number > 10_000_000_000:
            number //= 1000
        return number
    except ValueError:
        return None
