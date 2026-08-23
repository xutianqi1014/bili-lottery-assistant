
from collections.abc import Collection

from backend.domain.entities import ReadlistCandidate
from backend.domain.enums import SourceFamily

from .http_client import get_json
from .title_rules import normalize_text, parse_title_family

API_URL = "https://api.bilibili.com/x/article/up/lists"


async def discover_named_readlists_api(
    mid: str,
    timeout: float,
    names: Collection[str],
) -> list[ReadlistCandidate]:
    """Return readlists whose displayed names are explicitly allowed.

    The default adapter intentionally only understands the two conventional
    ``抽奖合集`` names.  Some UPs use a mixed collection name instead (for
    example ``互动抽奖``), so those adapters call this narrow helper rather
    than weakening the default title parser.  Matching is NFKC/whitespace
    normalized and the returned candidates are always stored as the mixed
    official family; runtime classification still distinguishes official,
    reservation and unofficial dynamics inside the article.
    """

    normalized_names = {normalize_text(name) for name in names if normalize_text(name)}
    if not normalized_names:
        return []
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
        if normalize_text(title) not in normalized_names:
            continue
        rl_id = str(row.get("id") or "")
        if not rl_id.isdecimal():
            continue
        candidates.append(
            ReadlistCandidate(
                rl_id=rl_id,
                canonical_url=f"https://www.bilibili.com/read/readlist/rl{rl_id}",
                title=title,
                normalized_title=normalize_text(title),
                family=SourceFamily.OFFICIAL,
                suffix_value=0,
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


async def discover_readlists_api(mid: str, timeout: float) -> list[ReadlistCandidate]:
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
        family_suffix = parse_title_family(title)
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


async def discover_year_readlist_api(
    mid: str, timeout: float
) -> list[ReadlistCandidate]:
    """Return year-named collections for adapters with a custom strategy.

    Some UPs do not use the shared ``抽奖合集``/``官方抽奖合集`` naming
    convention.  This function intentionally keeps the API read and parsing
    logic separate so those adapters can select their own collection without
    weakening the default two-family rules.
    """

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
        if not title.isdecimal() or len(title) != 4:
            continue
        year = int(title)
        if year < 2000 or year > 2100:
            continue
        rl_id = str(row.get("id") or "")
        if not rl_id.isdecimal():
            continue
        candidates.append(
            ReadlistCandidate(
                rl_id=rl_id,
                canonical_url=f"https://www.bilibili.com/read/readlist/rl{rl_id}",
                title=title,
                normalized_title=normalize_text(title),
                # The mixed year collection is handled by the confirmed
                # official automation family; runtime classification still
                # distinguishes interactive and reserve cards.
                family=SourceFamily.OFFICIAL,
                suffix_value=year,
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
