"""Cross-flow regressions for shared author identification and read helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.activity_engine.shared import author_follow as shared
from backend.activity_engine.shared import dom_read
from backend.activity_engine.unofficial import transport as unofficial
from backend.activity_engine.unofficial.actions import UnofficialAction

DYNAMIC = "https://www.bilibili.com/opus/123"
PROFILE = "https://space.bilibili.com/42"


class Node:
    def __init__(self, text="", href="", visible=True):
        self.text = text
        self.href = href
        self.visible = visible
        self.click = AsyncMock(side_effect=self.follow)

    def follow(self, **kwargs):
        self.text = "已关注"

    async def inner_text(self, **kwargs):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None

    async def is_visible(self):
        return self.visible


class Nodes:
    def __init__(self, values):
        self.values = values

    async def count(self):
        return len(self.values)

    def nth(self, index):
        return self.values[index]

    async def inner_text(self, **kwargs):
        return self.values[0].text if self.values else ""


class Page:
    def __init__(self, mapping):
        self.mapping = mapping
        self.wait_for_timeout = AsyncMock()

    def locator(self, selector):
        return Nodes(self.mapping.get(selector, []))


def setup_flow(label="关注", body=""):
    button = Node(label)
    dynamic = Page({
        ".opus-module-author__name": [Node("Alice")],
        shared.AUTHOR_PROFILE_SELECTOR: [Node("@Alice", PROFILE)],
    })
    profile = Page({shared.PROFILE_FOLLOW_SELECTOR: [button], "body": [Node(body)]})
    pages = {DYNAMIC: dynamic, PROFILE: profile}
    browser = SimpleNamespace(open=AsyncMock(side_effect=lambda url: pages[url]))
    return browser, dynamic, profile, button


async def run_flow(flow, browser, dynamic):
    if flow == "shared":
        return await shared.ensure_author_follow(
            browser, dynamic, poll_attempts=2, poll_interval_ms=0
        )
    return await unofficial.DomUnofficialTransport(
        browser, poll_attempts=2, poll_interval_ms=0
    ).perform(UnofficialAction.FOLLOW, target_url=DYNAMIC, payload={})


@pytest.mark.parametrize("flow", ["shared", "unofficial"])
@pytest.mark.parametrize("label", ["已关注", "互相关注"])
async def test_already_followed_never_clicks(flow, label):
    browser, dynamic, _, button = setup_flow(label)
    result = await run_flow(flow, browser, dynamic)
    assert result.code == "FOLLOW_ALREADY_DONE"
    button.click.assert_not_awaited()


@pytest.mark.parametrize("flow", ["shared", "unofficial"])
@pytest.mark.parametrize("failure", ["click", "terminal"])
async def test_uncertain_write_is_unknown_with_exactly_one_click(flow, failure):
    browser, dynamic, _, button = setup_flow()
    button.click.side_effect = RuntimeError("uncertain") if failure == "click" else None
    result = await run_flow(flow, browser, dynamic)
    assert result.state.value == "unknown"
    assert result.code == (
        "FOLLOW_CLICK_UNKNOWN" if failure == "click" else "FOLLOW_TERMINAL_UNKNOWN"
    )
    button.click.assert_awaited_once()


@pytest.mark.parametrize("flow", ["shared", "unofficial"])
async def test_multiple_author_ids_stop_before_profile_or_search(flow):
    browser, dynamic, _, button = setup_flow()
    dynamic.mapping[shared.AUTHOR_PROFILE_SELECTOR].append(
        Node("Alice", "https://space.bilibili.com/43")
    )
    result = await run_flow(flow, browser, dynamic)
    assert result.code == "FOLLOW_PROFILE_NOT_UNIQUE"
    assert all(call.args[0] == DYNAMIC for call in browser.open.await_args_list)
    button.click.assert_not_awaited()


@pytest.mark.parametrize("flow", ["shared", "unofficial"])
async def test_persistent_duplicate_controls_never_click(flow):
    browser, dynamic, profile, button = setup_flow()
    other = Node("关注")
    profile.mapping[shared.PROFILE_FOLLOW_SELECTOR].append(other)
    result = await run_flow(flow, browser, dynamic)
    assert result.code == "FOLLOW_CONTROL_NOT_UNIQUE"
    button.click.assert_not_awaited()
    other.click.assert_not_awaited()


@pytest.mark.parametrize("flow", ["shared", "unofficial"])
async def test_navigation_failure_is_unknown(flow):
    browser, dynamic, _, button = setup_flow()
    browser.open.side_effect = RuntimeError("navigation failed")
    result = await run_flow(flow, browser, dynamic)
    assert result.state.value == "unknown"
    button.click.assert_not_awaited()


@pytest.mark.parametrize(
    "label,body,shared_code,unofficial_code",
    [
        ("+ 关注", "", "FOLLOW_STATUS_UNRECOGNIZED", "FOLLOW_CONFIRMED"),
        ("关注", "已关注", "FOLLOW_ALREADY_DONE", "FOLLOW_CONFIRMED"),
    ],
)
async def test_follow_label_and_body_policies_remain_distinct(
    label, body, shared_code, unofficial_code
):
    for flow, code in [("shared", shared_code), ("unofficial", unofficial_code)]:
        browser, dynamic, _, button = setup_flow(label, body)
        result = await run_flow(flow, browser, dynamic)
        assert result.code == code
        assert button.click.await_count == (1 if flow == "unofficial" else 0)


@pytest.mark.parametrize("module", [shared, unofficial])
async def test_author_candidates_require_visible_exact_names_and_deduplicate_ids(module):
    page = Page({shared.AUTHOR_PROFILE_SELECTOR: [
        Node("@Alice", PROFILE),
        Node("Alice", PROFILE + "?from=search"),
        Node("Alice", "https://space.bilibili.com/99", visible=False),
        Node("Alice extra", "https://space.bilibili.com/100"),
        Node("Alice", "https://space.bilibili.com/not-numeric"),
    ]})
    assert await module._author_profile_ids(page, "Alice") == {"42"}


@pytest.mark.parametrize(
    "name,author,shared_match,unofficial_match",
    [("@@", "@", True, False), ("@A B", "A\u200b  B", False, True)],
)
def test_name_policy_differences(name, author, shared_match, unofficial_match):
    assert shared._author_name_matches(name, author) is shared_match
    assert unofficial._author_name_matches(name, author) is unofficial_match


@pytest.mark.parametrize(
    "href,shared_id,unofficial_id",
    [
        ("//space.bilibili.com/42?x=1", "42", "42"),
        ("https://space.bilibili.com/other/42", "", "42"),
        ("/nested/space/42/", "42", "42"),
        ("/not-numeric", "", ""),
    ],
)
def test_profile_path_policy_differences(href, shared_id, unofficial_id):
    assert shared._profile_id_from_href(href) == shared_id
    assert unofficial._profile_id_from_href(href) == unofficial_id


async def test_dom_read_fallbacks_and_normalization():
    assert await dom_read.inner_text(object()) == ""
    assert await dom_read.attribute(object(), "href") == ""
    assert await dom_read.page_text(object()) == ""
    legacy = SimpleNamespace(inner_text=AsyncMock(side_effect=[TypeError(), "legacy"]))
    assert await dom_read.inner_text(legacy) == "legacy"
    broken = SimpleNamespace(inner_text=AsyncMock(side_effect=RuntimeError()))
    assert await dom_read.inner_text(broken) == ""
    page = Page({"body": [Node(" \u200bA\n B\ufeff ")]})
    assert await dom_read.page_text(page) == "A B"


async def test_first_text_keeps_first_candidate_and_selector_precedence():
    page = Page({"first": [Node(""), Node("ignored")], "second": [Node(" chosen ")]})
    assert await dom_read.first_text(page, ("first", "second")) == "chosen"


async def test_unique_poll_waits_for_hydration_and_filters_exact_text():
    chosen = Node(" 发布 ")
    page = Page({"buttons": [chosen, Node("发布"), Node("取消")]})

    async def settle(_milliseconds):
        page.mapping["buttons"] = [chosen, Node("取消"), Node("发布", visible=False)]

    page.wait_for_timeout.side_effect = settle
    result = await dom_read.wait_for_unique_candidates(
        page, "buttons", text="发布", poll_attempts=3,
        poll_interval_ms=7, wait=dom_read.browser_wait,
    )
    assert result == [chosen]
    page.wait_for_timeout.assert_awaited_once_with(7)
    chosen.click.assert_not_awaited()


async def test_poll_wait_policy_preserves_sleep_fallback_difference(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(shared.asyncio, "sleep", sleep)
    await dom_read.browser_wait(object(), 7)
    sleep.assert_not_awaited()
    await shared._wait_for_timeout(object(), 7)
    sleep.assert_awaited_once_with(0.007)
