import json
from unittest.mock import AsyncMock

import pytest

import backend.source_adapters.lottery_toolman.adapter as lottery_toolman_adapter
from backend.config import Settings
from backend.db.models.source import SourceProfile
from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate
from backend.domain.enums import SourceFamily
from backend.source_adapters.lottery_collection import LotteryCollectionSourceAdapter
from backend.source_adapters.lottery_toolman.adapter import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman.title_rules import (
    select_latest_entries,
    select_latest_readlist_per_family,
)
from backend.source_adapters.nuomi_backpack import NuomiBackpackSourceAdapter
from backend.source_adapters.tomato_fries import TomatoFriesSourceAdapter


def candidate(title, family, suffix, rl_id, updated=None, source_mid=None):
    return ReadlistCandidate(
        rl_id=rl_id,
        canonical_url=f"https://www.bilibili.com/read/readlist/rl{rl_id}",
        title=title,
        normalized_title=title,
        family=family,
        suffix_value=suffix,
        item_count=None,
        updated_text=None,
        observed_updated_at=updated,
        source_mid=source_mid,
    )


@pytest.mark.parametrize("adapter,title,error", [
    (LotteryCollectionSourceAdapter, "抽奖合集", "READLIST_LOTTERY_COLLECTION_NOT_FOUND"),
    (TomatoFriesSourceAdapter, "互动抽奖", "READLIST_INTERACTIVE_NOT_FOUND"),
])
def test_named_selection_keeps_normalization_ties_and_error_codes(adapter, title, error):
    rows = [
        candidate(title + "2", SourceFamily.NORMAL, 1, "99", updated=999),
        candidate(" ".join(title), SourceFamily.NORMAL, 1, "9", updated=10),
        candidate(title, SourceFamily.NORMAL, 1, "10", updated=10),
        candidate(title, SourceFamily.NORMAL, 1, "90", updated=None),
    ]
    for ordered in (rows, list(reversed(rows))):
        selected = adapter.select_readlists(ordered)
        assert selected[0] is rows[1]
        assert selected[SourceFamily.NORMAL] is rows[1]
    with pytest.raises(ValueError, match=f"^{error}$"):
        adapter.select_readlists([rows[0]])


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [NuomiBackpackSourceAdapter, LotteryCollectionSourceAdapter])
@pytest.mark.parametrize("limit", [0, 3, 20])
async def test_inherited_article_discovery_keeps_limits_order_and_timeout(
    adapter, limit, monkeypatch,
):
    rows = [SourceArticleCandidate(str(i), f"https://x/{i}", str(i), i) for i in [2, 5, 1, 4, 3]]
    fetch = AsyncMock(return_value=rows)
    monkeypatch.setattr(lottery_toolman_adapter, "discover_entries_api", fetch)
    readlist = candidate("抽奖合集", SourceFamily.NORMAL, 1, "9")
    result = await adapter(Settings(request_timeout_sec=17)).discover_entries(readlist, limit, None)
    assert [row.position for row in result] == [5, 4, 3, 2, 1][:limit]
    fetch.assert_awaited_once_with(readlist, 17)
    assert [row.position for row in rows] == [2, 5, 1, 4, 3]


def test_selects_maximum_suffix_per_family():
    selected = select_latest_readlist_per_family(
        [
            candidate("抽奖合集③", SourceFamily.NORMAL, 3, "1"),
            candidate("抽奖合集④", SourceFamily.NORMAL, 4, "2"),
            candidate("官方抽奖合集②", SourceFamily.OFFICIAL, 2, "3"),
            candidate("官方抽奖合集③", SourceFamily.OFFICIAL, 3, "4"),
        ]
    )
    assert selected[SourceFamily.NORMAL].rl_id == "2"
    assert selected[SourceFamily.OFFICIAL].rl_id == "4"


def test_latest_entries_are_position_descending():
    rows = [SourceArticleCandidate(str(i), f"https://x/{i}", str(i), i) for i in range(1, 8)]
    assert [row.position for row in select_latest_entries(rows, 5)] == [7, 6, 5, 4, 3]


def test_nuomi_selects_the_largest_year_collection_as_mixed_official_family():
    selected = NuomiBackpackSourceAdapter.select_readlists(
        [
            candidate("2024", SourceFamily.OFFICIAL, 2024, "788285"),
            candidate("2025", SourceFamily.OFFICIAL, 2025, "903110"),
            candidate("2026", SourceFamily.OFFICIAL, 2026, "1016769"),
        ]
    )

    assert selected[SourceFamily.OFFICIAL].rl_id == "1016769"
    assert selected[SourceFamily.OFFICIAL].title == "2026"


def test_nuomi_keeps_newest_three_articles_by_source_position():
    rows = [SourceArticleCandidate(str(i), f"https://x/{i}", str(i), i) for i in range(1, 202)]

    selected = select_latest_entries(rows, 3)

    assert [row.position for row in selected] == [201, 200, 199]


def test_tomato_fries_selects_only_the_named_interactive_collection():
    selected = TomatoFriesSourceAdapter.select_readlists(
        [
            candidate("互动抽奖", SourceFamily.OFFICIAL, 0, "954367", updated=10),
            candidate("转盘合集", SourceFamily.OFFICIAL, 0, "942325", updated=99),
        ]
    )

    assert selected[SourceFamily.OFFICIAL].rl_id == "954367"


def test_tomato_fries_selects_newest_three_by_published_at():
    rows = [
        SourceArticleCandidate("old", "https://x/old", "old", 99, published_at=100),
        SourceArticleCandidate("newest", "https://x/newest", "newest", 1, published_at=300),
        SourceArticleCandidate("middle", "https://x/middle", "middle", 2, published_at=200),
        SourceArticleCandidate("unknown", "https://x/unknown", "unknown", 100),
    ]

    selected = TomatoFriesSourceAdapter.select_latest_entries_by_published_at(rows, 3)

    assert [row.article_id for row in selected] == ["newest", "middle", "old"]


def test_lottery_collection_selects_only_exact_collection_name():
    selected = LotteryCollectionSourceAdapter.select_readlists(
        [
            candidate("抽奖合集", SourceFamily.NORMAL, 1, "970564", updated=20),
            candidate("抽奖合集2", SourceFamily.NORMAL, 2, "970565", updated=30),
            candidate("官方抽奖合集", SourceFamily.OFFICIAL, 1, "970566", updated=40),
        ]
    )

    assert selected[SourceFamily.NORMAL].rl_id == "970564"


def test_lottery_collection_keeps_the_five_largest_article_numbers():
    rows = [
        SourceArticleCandidate(str(article_id), f"https://x/{article_id}", "", article_id)
        for article_id in range(1, 136)
    ]

    selected = select_latest_entries(rows, 5)

    assert [row.article_id for row in selected] == [str(value) for value in range(135, 130, -1)]


def test_lottery_toolman_selects_latest_collection_per_family_per_page():
    selected = LotteryToolmanSourceAdapter.select_readlists(
        [
            candidate("抽奖合集③", SourceFamily.NORMAL, 3, "100-normal-3", source_mid="100"),
            candidate("抽奖合集④", SourceFamily.NORMAL, 4, "100-normal-4", source_mid="100"),
            candidate(
                "官方抽奖合集③", SourceFamily.OFFICIAL, 3, "100-official-3", source_mid="100"
            ),
            candidate("抽奖合集", SourceFamily.NORMAL, 0, "280-normal", source_mid="280"),
        ]
    )
    assert {(row.source_mid, row.family) for row in selected} == {
        ("100", SourceFamily.NORMAL),
        ("100", SourceFamily.OFFICIAL),
        ("280", SourceFamily.NORMAL),
    }
    assert (
        next(
            row for row in selected if row.source_mid == "100" and row.family is SourceFamily.NORMAL
        ).rl_id
        == "100-normal-4"
    )


@pytest.mark.asyncio
async def test_lottery_toolman_discovery_checks_both_source_pages(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def discover_families(mid: str, timeout: float):
        del timeout
        calls.append(("families", mid))
        return [candidate("抽奖合集④", SourceFamily.NORMAL, 4, "100-normal", source_mid=mid)]

    async def discover_exact(mid: str, timeout: float, names: set[str]):
        del timeout, names
        calls.append(("named_exact", mid))
        return [candidate("抽奖合集", SourceFamily.OFFICIAL, 0, "280-normal", source_mid=mid)]

    monkeypatch.setattr(lottery_toolman_adapter, "discover_readlists_api", discover_families)
    monkeypatch.setattr(lottery_toolman_adapter, "discover_named_readlists_api", discover_exact)
    first_url = "https://space.bilibili.com/100680137/upload/opus"
    second_url = "https://space.bilibili.com/280604312/upload/opus"
    profile_config = {
        "sourcePages": [
            {
                "mid": "100680137",
                "uploadUrl": first_url,
                "readlistStrategy": "families",
            },
            {
                "mid": "280604312",
                "uploadUrl": second_url,
                "readlistStrategy": "named_exact",
                "readlistName": "抽奖合集",
                "family": "normal",
            },
        ]
    }
    profile = SourceProfile(
        source_key="lottery_toolman",
        mid="100680137",
        upload_url=first_url,
        adapter_key="lottery_toolman_v1",
        config_json=json.dumps(profile_config),
    )
    result = await LotteryToolmanSourceAdapter(Settings()).discover_readlists(profile, None)

    assert calls == [("families", "100680137"), ("named_exact", "280604312")]
    assert [row.source_mid for row in result] == ["100680137", "280604312"]
    assert result[-1].family is SourceFamily.NORMAL
