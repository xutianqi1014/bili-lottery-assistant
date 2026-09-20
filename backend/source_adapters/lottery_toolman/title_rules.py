import re
import unicodedata
from collections.abc import Iterable

from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate
from backend.domain.enums import SourceFamily

_CIRCLED = {
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
    "⑤": 5,
    "⑥": 6,
    "⑦": 7,
    "⑧": 8,
    "⑨": 9,
    "⑩": 10,
}
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def parse_chinese_number(value: str) -> int | None:
    if not value or any(
        char not in _CHINESE_DIGITS and char not in _CHINESE_UNITS for char in value
    ):
        return None
    total = 0
    current = 0
    for char in value:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        else:
            unit = _CHINESE_UNITS[char]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
    return total + current


def parse_suffix(value: str) -> int | None:
    suffix = normalize_text(value)
    if not suffix or suffix == "系列":
        return 1
    if suffix in _CIRCLED:
        return _CIRCLED[suffix]
    if suffix.isdecimal():
        return int(suffix)
    if suffix.startswith("系列"):
        suffix = suffix[2:]
        if not suffix:
            return 1
    return parse_chinese_number(suffix)


def parse_title_family(title: str) -> tuple[SourceFamily, int] | None:
    normalized = normalize_text(title)
    if normalized.startswith("官方抽奖合集"):
        suffix = parse_suffix(normalized[len("官方抽奖合集") :])
        return (SourceFamily.OFFICIAL, suffix) if suffix is not None else None
    if normalized.startswith("抽奖合集"):
        suffix = parse_suffix(normalized[len("抽奖合集") :])
        return (SourceFamily.NORMAL, suffix) if suffix is not None else None
    return None


def select_latest_readlist_per_family(
    candidates: Iterable[ReadlistCandidate],
) -> dict[SourceFamily, ReadlistCandidate]:
    selected: dict[SourceFamily, ReadlistCandidate] = {}
    for candidate in candidates:
        current = selected.get(candidate.family)
        if current is None:
            selected[candidate.family] = candidate
            continue
        current_key = (
            current.suffix_value,
            current.observed_updated_at or -1,
            current.rl_id,
        )
        candidate_key = (
            candidate.suffix_value,
            candidate.observed_updated_at or -1,
            candidate.rl_id,
        )
        if candidate_key > current_key:
            selected[candidate.family] = candidate
    missing = [family.value for family in SourceFamily if family not in selected]
    if missing:
        raise ValueError(f"READLIST_FAMILY_MISSING:{','.join(missing)}")
    return selected


def select_latest_entries(
    entries: Iterable[SourceArticleCandidate], limit: int,
) -> list[SourceArticleCandidate]:
    if limit < 1:
        return []
    return sorted(entries, key=lambda item: item.position, reverse=True)[:limit]
