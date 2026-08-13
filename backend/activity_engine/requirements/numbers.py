"""Chinese/Arabic count parsing for public participation requirements."""

from __future__ import annotations

_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "壹": 1,
    "二": 2,
    "两": 2,
    "貳": 2,
    "贰": 2,
    "三": 3,
    "叁": 3,
    "四": 4,
    "肆": 4,
    "五": 5,
    "伍": 5,
    "六": 6,
    "陆": 6,
    "陸": 6,
    "七": 7,
    "柒": 7,
    "八": 8,
    "捌": 8,
    "九": 9,
    "玖": 9,
}
_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}


def parse_count(value: str) -> int:
    """Parse the small counts used by ``@三名好友`` style requirements.

    Invalid or mixed text returns ``0``.  The caller owns the product safety
    limit, because a syntactically valid count can still be unsafe to append.
    """

    normalized = "".join(value.split())
    if not normalized:
        return 0
    if normalized.isdecimal():
        return int(normalized)

    total = 0
    section = 0
    number = 0
    for character in normalized:
        if character in _DIGITS:
            number = _DIGITS[character]
            continue
        unit = _UNITS.get(character)
        if unit is None:
            return 0
        if unit >= 1000:
            section += number
            total += (section or 1) * unit
            section = 0
            number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return total + section + number
