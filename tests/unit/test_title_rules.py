import pytest

from backend.domain.enums import SourceFamily
from backend.source_adapters.lottery_toolman.title_rules import (
    normalize_text,
    parse_chinese_number,
    parse_title_family,
)


@pytest.mark.parametrize(
    ("title", "family", "suffix"),
    [
        ("抽奖合集④", SourceFamily.NORMAL, 4),
        ("官方抽奖合集③", SourceFamily.OFFICIAL, 3),
        ("抽奖合集系列二", SourceFamily.NORMAL, 2),
        ("官方抽奖合集", SourceFamily.OFFICIAL, 1),
    ],
)
def test_parse_title_family(title, family, suffix):
    assert parse_title_family(title) == (family, suffix)


def test_official_title_is_not_normal_family():
    assert parse_title_family("官方抽奖合集③")[0] is SourceFamily.OFFICIAL


def test_normalize_text_nfkc_and_whitespace():
    assert normalize_text(" 抽奖合集 ４ ") == "抽奖合集4"


@pytest.mark.parametrize(("value", "expected"), [("十一", 11), ("二十", 20), ("一百零二", 102)])
def test_parse_chinese_number(value, expected):
    assert parse_chinese_number(value) == expected

