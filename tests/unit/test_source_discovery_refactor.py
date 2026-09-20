"""Contract and browser regressions for the stage 4/5 discovery refactor."""

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.config import Settings
from backend.domain.entities import MarkerInspection, ReadlistCandidate, SourceArticleCandidate
from backend.domain.enums import LikeState, SourceFamily
from backend.source_adapters.compatibility import SourceAdapterCompatibility
from backend.source_adapters.lottery_collection import LotteryCollectionSourceAdapter
from backend.source_adapters.lottery_toolman import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman import discover_readlists as api
from backend.source_adapters.nuomi_backpack import NuomiBackpackSourceAdapter
from backend.source_adapters.tomato_fries import TomatoFriesSourceAdapter

ARTICLE = SourceArticleCandidate("123", "https://www.bilibili.com/read/cv123", "test", 1)
HTML = """
<article class="opus-module-content">
<p>充电抽奖</p><p><a href="/opus/400000001">充电</a></p>
<p>预约抽奖</p><p><a href="/opus/400000002">预约</a></p>
<p>互动抽奖</p><p><a href="/opus/400000003">互动</a></p>
</article>
"""


def candidate(title, family, suffix=1):
    return ReadlistCandidate("1", "https://x/rl1", title, title, family, suffix, None, None, None)


@pytest.mark.parametrize(
    "adapter,title,family,suffix",
    [
        (LotteryToolmanSourceAdapter, "抽奖合集", SourceFamily.NORMAL, 1),
        (NuomiBackpackSourceAdapter, "2026", SourceFamily.OFFICIAL, 2026),
        (TomatoFriesSourceAdapter, "互动抽奖", SourceFamily.OFFICIAL, 0),
        (LotteryCollectionSourceAdapter, "抽奖合集", SourceFamily.NORMAL, 1),
    ],
)
def test_builtins_return_sequences(adapter, title, family, suffix):
    row = candidate(title, family, suffix)
    selected = adapter.select_readlists((row,))
    assert isinstance(selected, Sequence)
    assert list(selected) == [row]
    assert selected[0] == row
    assert list(selected[:1]) == [row]
    if adapter is not LotteryToolmanSourceAdapter:
        assert selected[family] == row  # Historical public call shape.


@pytest.mark.asyncio
async def test_shared_http_conversion_preserves_strategy_semantics(monkeypatch):
    rows = [
        {"id": 1, "name": " 抽奖合集② ", "articles_count": "3", "update_time": 1700000000000},
        {"id": 2, "name": "互 动 抽 奖", "update_time": "invalid"},
        {"id": 3, "title": "2000", "update_time": 100},
        {"id": 4, "name": "2100"},
        {"id": 5, "name": "1999"},
        {"id": 6, "name": "2101"},
        {"id": 7, "name": "２０２６"},
        {"id": "bad", "name": "抽奖合集"},
        {"id": 8, "name": "2 026"},
    ]
    get = AsyncMock(return_value={"code": 0, "data": {"lists": rows}})
    monkeypatch.setattr(api, "get_json", get)
    families = await api.discover_readlists_api("42", 3)
    exact = await api.discover_named_readlists_api("42", 3, {"互动抽奖"})
    years = await api.discover_year_readlist_api("42", 3)
    assert [(r.rl_id, r.family, r.suffix_value) for r in families] == [
        ("1", SourceFamily.NORMAL, 2)
    ]
    assert families[0].title == "抽奖合集②"
    assert families[0].normalized_title == "抽奖合集2"
    assert families[0].item_count == 3
    assert families[0].observed_updated_at == 1700000000
    assert exact[0].family == SourceFamily.OFFICIAL
    assert exact[0].suffix_value == 0
    assert exact[0].observed_updated_at is None
    assert [r.suffix_value for r in years] == [2000, 2100, 2026]
    assert get.await_count == 3
    get.assert_awaited_with(
        api.API_URL, {"mid": "42", "sort": 0}, 3,
        "https://space.bilibili.com/42/upload/opus",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["families", "exact", "year"])
async def test_http_errors_and_missing_data_keep_existing_behavior(monkeypatch, strategy):
    get = AsyncMock(return_value={"code": -403})
    monkeypatch.setattr(api, "get_json", get)

    async def discover():
        if strategy == "exact":
            return await api.discover_named_readlists_api("42", 3, {"互动抽奖"})
        if strategy == "year":
            return await api.discover_year_readlist_api("42", 3)
        return await api.discover_readlists_api("42", 3)

    with pytest.raises(RuntimeError, match="READLIST_API_CODE:-403"):
        await discover()
    get.return_value = {"code": 0, "data": None}
    assert await discover() == []


@pytest.mark.asyncio
async def test_empty_exact_names_do_not_request_http(monkeypatch):
    get = AsyncMock()
    monkeypatch.setattr(api, "get_json", get)
    assert await api.discover_named_readlists_api("42", 3, {"", " "}) == []
    get.assert_not_awaited()


class Page:
    def __init__(self, *, active=0, buttons=1, html=HTML, wait_error=None):
        self.active = active
        self.buttons = buttons
        self.wait_for_selector = AsyncMock(side_effect=wait_error)
        self.content = AsyncMock(return_value=html)

    def locator(self, selector):
        count = self.active if selector.endswith(".is-active") else self.buttons
        return SimpleNamespace(count=AsyncMock(return_value=count))


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_cls", [
    LotteryToolmanSourceAdapter, NuomiBackpackSourceAdapter,
    LotteryCollectionSourceAdapter, TomatoFriesSourceAdapter,
])
async def test_observation_navigates_once_and_matches_standalone_extraction(adapter_cls):
    adapter = adapter_cls(Settings())
    page = Page()
    browser = SimpleNamespace(open=AsyncMock(return_value=page), ready=True)
    observation = await adapter.observe_article(ARTICLE, browser)
    browser.open.assert_awaited_once_with(ARTICLE.canonical_url)
    assert observation.marker.state == LikeState.UNLIKED
    assert observation.extraction.status == "ok"
    standalone = await adapter.extract_activities(ARTICLE, browser)
    assert observation.extraction == standalone
    assert browser.open.await_count == 2
    if adapter_cls is TomatoFriesSourceAdapter:
        assert [r.dynamic_id for r in standalone.refs] == ["400000002", "400000003"]
    marker = await adapter.inspect_processed_marker(ARTICLE, browser)
    assert marker == observation.marker
    assert browser.open.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page,state,reason",
    [
        (Page(active=1), LikeState.LIKED, "DOM_ACTIVE_CLASS"),
        (Page(buttons=2), LikeState.UNKNOWN, "DOM_BUTTON_AMBIGUOUS"),
        (Page(wait_error=TimeoutError()), LikeState.UNKNOWN, "MARKER_READ_FAILED:TimeoutError"),
    ],
)
async def test_observation_does_not_read_content_when_marker_blocks(page, state, reason):
    browser = SimpleNamespace(open=AsyncMock(return_value=page))
    result = await LotteryToolmanSourceAdapter(Settings()).observe_article(ARTICLE, browser)
    assert result.marker.state == state
    assert result.marker.reason_code == reason
    assert result.extraction is None
    page.content.assert_not_awaited()
    browser.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_observation_handles_unready_browser_navigation_and_content_failures():
    adapter = LotteryToolmanSourceAdapter(Settings())
    browser = SimpleNamespace(ready=False, open=AsyncMock(side_effect=OSError()))
    result = await adapter.observe_article(ARTICLE, browser)
    assert result.marker.reason_code == "BROWSER_NOT_READY"
    browser.open.assert_not_awaited()
    browser.ready = True
    result = await adapter.observe_article(ARTICLE, browser)
    assert result.marker.reason_code == "MARKER_READ_FAILED:OSError"
    assert result.extraction is None
    page = Page()
    page.content.side_effect = OSError()
    browser.open = AsyncMock(return_value=page)
    result = await adapter.observe_article(ARTICLE, browser)
    assert result.marker.state == LikeState.UNLIKED
    assert result.extraction.status == "failed"
    assert result.extraction.reason_code == "SOURCE_ARTICLE_NAVIGATION_FAILED"


@pytest.mark.asyncio
async def test_legacy_compatibility_centralizes_selection_and_marker_gate():
    normal = candidate("抽奖合集", SourceFamily.NORMAL)
    official = candidate("官方抽奖合集", SourceFamily.OFFICIAL)
    legacy = SimpleNamespace(
        inspect_processed_marker=AsyncMock(
            return_value=MarkerInspection(LikeState.UNKNOWN, "test", "test")
        ),
        extract_activities=AsyncMock(),
    )
    bridge = SourceAdapterCompatibility(legacy)
    assert list(bridge.select_readlists([normal, official])) == [normal, official]
    with pytest.raises(ValueError, match="READLIST_FAMILY_MISSING"):
        bridge.select_readlists([normal])
    legacy.select_readlists = lambda rows: {SourceFamily.NORMAL: rows[0]}
    assert list(bridge.select_readlists([normal])) == [normal]
    observation = await bridge.observe_article(ARTICLE, None)
    assert observation.extraction is None
    legacy.extract_activities.assert_not_awaited()
