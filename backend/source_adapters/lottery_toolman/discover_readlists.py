
from backend.domain.entities import ReadlistCandidate

from .http_client import get_json
from .title_rules import normalize_text, parse_title_family

API_URL = "https://api.bilibili.com/x/article/up/lists"


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
