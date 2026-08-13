from __future__ import annotations

import pytest

from backend.activity_engine.unofficial.actions import UnofficialAction, WriteOutcomeState
from backend.activity_engine.unofficial.transport import (
    AUTHOR_PROFILE_SELECTOR,
    COMMENT_EDITOR_SELECTOR,
    COMMENT_PUBLISH_SELECTOR,
    COMMENT_REPOST_SELECTOR,
    FORWARD_SELECTOR,
    LIKE_ACTIVE_SELECTOR,
    LIKE_SCOPED_SELECTOR,
    LIKE_SELECTOR,
    PROFILE_FOLLOW_SELECTOR,
    SHARE_EDITOR_SELECTOR,
    SHARE_PUBLISH_SELECTOR,
    SHARE_SELECTOR,
    DomUnofficialTransport,
)


class _Locator:
    def __init__(
        self, *, text: str = "", attrs: dict[str, str] | None = None, visible: bool = True
    ):
        self.text = text
        self.attrs = attrs or {}
        self.visible = visible
        self.filled: list[str] = []
        self.clicks = 0
        self.on_click = None

    async def is_visible(self):
        return self.visible

    async def inner_text(self, **_kwargs):
        return self.text

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def fill(self, value):
        self.filled.append(value)

    async def click(self, **_kwargs):
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    async def is_checked(self):
        return self.attrs.get("checked") == "true"


class _LocatorSet:
    def __init__(self, values):
        self.values = values

    async def count(self):
        return len(self.values)

    def nth(self, index):
        return self.values[index]

    async def inner_text(self, **kwargs):
        del kwargs
        if not self.values:
            return ""
        return await self.values[0].inner_text()


class _Page:
    def __init__(self):
        self.body = ""
        self.active = False
        self.share_open = False
        self.author = ""
        self.like = _Locator()
        self.like.on_click = lambda: setattr(self, "active", True)
        self.editor = _Locator()
        self.checkbox = _Locator(attrs={"checked": "false"})
        self.checkbox.on_click = lambda: self.checkbox.attrs.__setitem__("checked", "true")
        self.comment_publish = _Locator(text="发布")
        self.comment_publish.on_click = lambda: setattr(self, "body", "评论成功")
        self.forward = _Locator()
        self.forward.on_click = lambda: setattr(self, "share_open", True)
        self.share = _Locator(visible=False)
        self.share_editor = _Locator(visible=False)
        self.share_publish = _Locator(visible=False)
        self.share_publish.on_click = self._publish_share
        self.author_locator = _Locator()
        self.follow = _Locator(text="关注")
        self.follow.on_click = lambda: setattr(self.follow, "text", "已关注")

    def _publish_share(self):
        self.share_open = False
        self.body = "转发成功"

    def locator(self, selector):
        if selector == "body":
            return _LocatorSet([_Locator(text=self.body)])
        if selector == LIKE_SELECTOR:
            return _LocatorSet([self.like])
        if selector == LIKE_ACTIVE_SELECTOR:
            return _LocatorSet([_Locator(visible=self.active)]) if self.active else _LocatorSet([])
        if selector == COMMENT_EDITOR_SELECTOR:
            return _LocatorSet([self.editor])
        if selector == COMMENT_REPOST_SELECTOR:
            return _LocatorSet([self.checkbox])
        if selector == COMMENT_PUBLISH_SELECTOR:
            return _LocatorSet([self.comment_publish])
        if selector == FORWARD_SELECTOR:
            return _LocatorSet([self.forward])
        if selector == SHARE_SELECTOR:
            self.share.visible = self.share_open
            return _LocatorSet([self.share] if self.share_open else [])
        if selector == SHARE_EDITOR_SELECTOR:
            self.share_editor.visible = self.share_open
            return _LocatorSet([self.share_editor] if self.share_open else [])
        if selector == SHARE_PUBLISH_SELECTOR:
            self.share_publish.visible = self.share_open
            return _LocatorSet([self.share_publish] if self.share_open else [])
        if selector == 'a[href*="space.bilibili.com/"]':
            return _LocatorSet([])
        if selector == PROFILE_FOLLOW_SELECTOR:
            return _LocatorSet([self.follow])
        if selector == ".opus-module-author__name":
            return _LocatorSet([self.author_locator] if self.author else [])
        if selector == "bili-comments":
            return _LocatorSet([_Locator(text=self.body)])
        return _LocatorSet([])

    async def wait_for_timeout(self, _milliseconds):
        return None


class _TransientDuplicateEditorPage(_Page):
    def __init__(self):
        super().__init__()
        self.editor_lookups = 0

    def locator(self, selector):
        if selector == COMMENT_EDITOR_SELECTOR:
            self.editor_lookups += 1
            if self.editor_lookups == 1:
                return _LocatorSet([self.editor, _Locator()])
        return super().locator(selector)


class _ScopedDuplicateLikePage(_Page):
    """The generic class has two visible matches, but the outer toolbar is unique."""

    def locator(self, selector):
        if selector == LIKE_SCOPED_SELECTOR:
            return _LocatorSet([self.like])
        if selector == LIKE_SELECTOR:
            return _LocatorSet([self.like, _Locator()])
        return super().locator(selector)


class _TransientDuplicateRepostPage(_Page):
    def __init__(self):
        super().__init__()
        self.repost_lookups = 0

    def locator(self, selector):
        if selector == COMMENT_REPOST_SELECTOR:
            self.repost_lookups += 1
            if self.repost_lookups == 1:
                return _LocatorSet([self.checkbox, _Locator(attrs={"checked": "false"})])
        return super().locator(selector)


class _TransientDuplicateFollowPage(_Page):
    def __init__(self):
        super().__init__()
        self.follow_lookups = 0

    def locator(self, selector):
        if selector == PROFILE_FOLLOW_SELECTOR:
            self.follow_lookups += 1
            if self.follow_lookups == 1:
                return _LocatorSet([self.follow, _Locator(text="follow")])
        return super().locator(selector)


class _SearchPage(_Page):
    def __init__(self, author: str):
        super().__init__()
        self.author_link = _Locator(text=author, attrs={"href": "//space.bilibili.com/386837540"})

    def locator(self, selector):
        if selector == 'a[href*="space.bilibili.com/"]':
            return _LocatorSet([self.author_link])
        return super().locator(selector)


class _HydratingSearchPage(_SearchPage):
    def __init__(self, author: str):
        super().__init__(author)
        self.ready = False
        self.waits: list[int] = []

    async def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        self.ready = True

    def locator(self, selector):
        if selector == AUTHOR_PROFILE_SELECTOR and not self.ready:
            return _LocatorSet([])
        return super().locator(selector)


class _DirectAuthorPage(_Page):
    def __init__(self, author: str, profile_id: str):
        super().__init__()
        self.author = author
        self.author_locator.text = author
        self.author_link = _Locator(
            text="@" + author,
            attrs={"href": f"//space.bilibili.com/{profile_id}?spm_id_from=333.1369.0.0"},
        )

    def locator(self, selector):
        if selector == AUTHOR_PROFILE_SELECTOR:
            return _LocatorSet([self.author_link])
        return super().locator(selector)


class _HeaderTitleAuthorPage(_Page):
    def __init__(self, author: str):
        super().__init__()
        self.header_author = _Locator(text=author)

    def locator(self, selector):
        if selector == ".bili-dyn-item__header .bili-dyn-title__text":
            return _LocatorSet([self.header_author])
        return super().locator(selector)


class _Browser:
    def __init__(self, pages):
        self.pages = pages
        self.opened: list[str] = []

    async def open(self, url):
        self.opened.append(url)
        return self.pages[url]


def test_comment_editor_selector_targets_only_editable_component():
    assert '[contenteditable="true"]' in COMMENT_EDITOR_SELECTOR


@pytest.mark.asyncio
async def test_like_requires_active_terminal_marker():
    page = _Page()
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.LIKE,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "DYNAMIC_LIKE_CONFIRMED"
    assert page.like.clicks == 1


@pytest.mark.asyncio
async def test_like_prefers_unique_outer_toolbar_when_generic_selector_is_duplicated():
    page = _ScopedDuplicateLikePage()
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.LIKE,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "DYNAMIC_LIKE_CONFIRMED"
    assert page.like.clicks == 1


@pytest.mark.asyncio
async def test_comment_checkbox_confirms_repost_without_second_share_click():
    page = _Page()
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.COMMENT,
        target_url="https://www.bilibili.com/opus/123",
        payload={"commentText": "参与抽奖", "repostWithComment": True},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.confirmed_actions == ("repost",)
    assert page.editor.filled == ["参与抽奖"]
    assert page.checkbox.attrs["checked"] == "true"


@pytest.mark.asyncio
async def test_comment_waits_for_transient_duplicate_editor_to_settle():
    page = _TransientDuplicateEditorPage()
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=3, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.COMMENT,
        target_url="https://www.bilibili.com/opus/123",
        payload={"commentText": "参与抽奖"},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "COMMENT_SUBMIT_ACCEPTED"
    assert page.editor_lookups >= 2


@pytest.mark.asyncio
async def test_comment_waits_for_transient_duplicate_repost_checkbox_to_settle():
    page = _TransientDuplicateRepostPage()
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=3, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.COMMENT,
        target_url="https://www.bilibili.com/opus/123",
        payload={"commentText": "参加抽奖", "repostWithComment": True},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.confirmed_actions == ("repost",)
    assert page.repost_lookups >= 2
    assert page.checkbox.attrs["checked"] == "true"


@pytest.mark.asyncio
async def test_comment_submit_is_accepted_without_comment_list_recheck():
    page = _Page()
    page.comment_publish.on_click = lambda: None
    browser = _Browser({"https://www.bilibili.com/opus/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.COMMENT,
        target_url="https://www.bilibili.com/opus/123",
        payload={"commentText": "参与抽奖"},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "COMMENT_SUBMIT_ACCEPTED"


@pytest.mark.asyncio
async def test_repost_requires_modal_close_and_success_marker():
    page = _Page()
    browser = _Browser({"https://t.bilibili.com/123": page})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.REPOST,
        target_url="https://t.bilibili.com/123",
        payload={"commentText": "转发"},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "REPOST_CONFIRMED"
    assert page.share_publish.clicks == 1


@pytest.mark.asyncio
async def test_follow_skips_when_profile_already_followed_and_clicks_when_not():
    dynamic = _Page()
    dynamic.author = "示例作者"
    dynamic.author_locator.text = dynamic.author
    search = _SearchPage(dynamic.author)
    profile = _Page()
    browser = _Browser(
        {
            "https://www.bilibili.com/opus/123": dynamic,
            (
                "https://search.bilibili.com/upuser?keyword=%E7%A4%BA%E4%BE%8B%E4%BD%9C%E8%80%85"
            ): search,
            "https://space.bilibili.com/386837540": profile,
        }
    )
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "FOLLOW_CONFIRMED"
    assert profile.follow.clicks == 1


@pytest.mark.asyncio
async def test_follow_reads_author_from_current_dynamic_header_title():
    dynamic = _HeaderTitleAuthorPage("HeaderAuthor")
    search = _SearchPage("HeaderAuthor")
    profile = _Page()
    browser = _Browser(
        {
            "https://www.bilibili.com/opus/123": dynamic,
            "https://search.bilibili.com/upuser?keyword=HeaderAuthor": search,
            "https://space.bilibili.com/386837540": profile,
        }
    )
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "FOLLOW_CONFIRMED"
    assert browser.opened == [
        "https://www.bilibili.com/opus/123",
        "https://search.bilibili.com/upuser?keyword=HeaderAuthor",
        "https://space.bilibili.com/386837540",
    ]


@pytest.mark.asyncio
async def test_follow_waits_random_delay_for_search_results_before_matching():
    dynamic = _Page()
    dynamic.author = "ExampleAuthor"
    dynamic.author_locator.text = dynamic.author
    search = _HydratingSearchPage(dynamic.author)
    profile = _Page()
    browser = _Browser(
        {
            "https://www.bilibili.com/opus/123": dynamic,
            "https://search.bilibili.com/upuser?keyword=ExampleAuthor": search,
            "https://space.bilibili.com/386837540": profile,
        }
    )
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "FOLLOW_CONFIRMED"
    assert search.waits
    assert 1_000 <= search.waits[0] <= 2_000
    assert profile.follow.clicks == 1


@pytest.mark.asyncio
async def test_follow_opus_uses_direct_author_profile_link_before_user_search():
    dynamic = _DirectAuthorPage("ExampleAuthor", "699204462")
    profile = _Page()
    dynamic_url = "https://www.bilibili.com/opus/1234866177788870690"
    profile_url = "https://space.bilibili.com/699204462"
    browser = _Browser({dynamic_url: dynamic, profile_url: profile})
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url=dynamic_url,
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "FOLLOW_CONFIRMED"
    assert browser.opened == [dynamic_url, profile_url]
    assert profile.follow.clicks == 1


@pytest.mark.asyncio
async def test_follow_waits_for_transient_duplicate_profile_controls():
    dynamic = _Page()
    dynamic.author = "ExampleAuthor"
    dynamic.author_locator.text = dynamic.author
    search = _SearchPage(dynamic.author)
    profile = _TransientDuplicateFollowPage()
    browser = _Browser(
        {
            "https://www.bilibili.com/opus/123": dynamic,
            (
                "https://search.bilibili.com/upuser?keyword=ExampleAuthor"
            ): search,
            "https://space.bilibili.com/386837540": profile,
        }
    )
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.SUCCESS
    assert result.code == "FOLLOW_CONFIRMED"
    assert profile.follow_lookups >= 2
    assert profile.follow.clicks == 1


@pytest.mark.asyncio
async def test_follow_returns_already_done_when_profile_is_already_followed():
    dynamic = _Page()
    dynamic.author = "ExampleAuthor"
    dynamic.author_locator.text = dynamic.author
    search = _SearchPage(dynamic.author)
    profile = _Page()
    profile.follow.text = "\u5df2\u5173\u6ce8"
    browser = _Browser(
        {
            "https://www.bilibili.com/opus/123": dynamic,
            "https://search.bilibili.com/upuser?keyword=ExampleAuthor": search,
            "https://space.bilibili.com/386837540": profile,
        }
    )
    transport = DomUnofficialTransport(browser, poll_attempts=2, poll_interval_ms=0)

    result = await transport.perform(
        UnofficialAction.FOLLOW,
        target_url="https://www.bilibili.com/opus/123",
        payload={},
    )

    assert result.state is WriteOutcomeState.ALREADY_DONE
    assert result.code == "FOLLOW_ALREADY_DONE"
    assert profile.follow.clicks == 0
