from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate
from backend.domain.enums import SourceFamily
from backend.source_adapters.lottery_toolman.title_rules import (
    select_latest_entries,
    select_latest_readlist_per_family,
)
from backend.source_adapters.nuomi_backpack import NuomiBackpackSourceAdapter


def candidate(title, family, suffix, rl_id, updated=None):
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
    )


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
