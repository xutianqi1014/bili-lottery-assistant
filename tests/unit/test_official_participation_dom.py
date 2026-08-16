import pytest

from backend.activity_engine.official.activity_like_marker import (
    ACTIVITY_LIKE_ACTIVE_SELECTOR,
    ACTIVITY_LIKE_SELECTOR,
)
from backend.activity_engine.official.participation import OfficialParticipationOutcomeState
from backend.activity_engine.official.participation_dom import (
    LOTTERY_ENTRY_SELECTOR,
    LOTTERY_IFRAME_SELECTOR,
    LOTTERY_PANEL_CLOSE_SELECTOR,
    LOTTERY_PARTICIPATION_CONTROLS_SELECTOR,
    DomOfficialParticipationTransport,
    classify_official_panel_text,
)


class _Locator:
    def __init__(
        self,
        text: str = "",
        *,
        count: int = 1,
        on_click=None,
        enabled: bool = True,
        href: str = "",
    ) -> None:
        self.text = text
        self._count = count
        self.on_click = on_click
        self.enabled = enabled
        self.href = href
        self.clicks = 0

    async def count(self) -> int:
        return self._count

    def nth(self, index: int):
        assert index == 0
        return self

    async def inner_text(self, *, timeout: int) -> str:
        del timeout
        return self.text

    async def click(self, *, timeout: int, force: bool = False) -> None:
        del timeout, force
        self.clicks += 1
        if callable(self.on_click):
            self.on_click()

    async def is_enabled(self) -> bool:
        return self.enabled

    async def is_visible(self) -> bool:
        return True

    async def get_attribute(self, name: str) -> str | None:
        return self.href if name == "href" else None

    async def scroll_into_view_if_needed(self, *, timeout: int) -> None:
        del timeout


class _Controls:
    def __init__(self, items: list[_Locator]) -> None:
        self.items = items

    async def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _Locator:
        return self.items[index]


class _Panel:
    def __init__(
        self,
        text: str,
        candidate_texts: list[str],
        *,
        done_after_click: bool,
        empty_body_reads: int = 0,
        body_texts: list[str] | None = None,
    ):
        self.text = text
        self.done_after_click = done_after_click
        self.empty_body_reads = empty_body_reads
        self.body_texts = list(body_texts or [])
        self.body = _Locator(on_click=None)
        self.candidates: list[_Locator] = []
        for candidate_text in candidate_texts:
            self.candidates.append(_Locator(candidate_text, on_click=self._clicked))

    def _clicked(self) -> None:
        if self.done_after_click:
            self.text = "已成功参与"

    def locator(self, selector: str):
        if selector == "body":
            if self.empty_body_reads:
                self.empty_body_reads -= 1
                self.body.text = ""
            elif self.body_texts:
                self.body.text = self.body_texts.pop(0)
            else:
                self.body.text = self.text
            return self.body
        return _Controls(self.candidates)


class _Page:
    def __init__(
        self,
        panel: _Panel,
        *,
        liked: bool = False,
        close_available: bool = True,
    ):
        self.panel = panel
        self.entry = _Locator(on_click=self._open_popup)
        self.liked = liked
        self.close_available = close_available
        self.popup_open = False
        self.close_clicks = 0
        self.like_clicks = 0

    def _open_popup(self) -> None:
        self.popup_open = True

    def _close_popup(self) -> None:
        self.close_clicks += 1
        self.popup_open = False

    def _click_like(self) -> None:
        assert self.popup_open is False
        self.like_clicks += 1
        self.liked = True

    def locator(self, selector: str):
        if selector == LOTTERY_ENTRY_SELECTOR:
            return self.entry
        if selector == ACTIVITY_LIKE_SELECTOR:
            return _Locator(on_click=self._click_like)
        if selector == ACTIVITY_LIKE_ACTIVE_SELECTOR:
            return _Locator(count=1 if self.liked else 0)
        if selector == LOTTERY_IFRAME_SELECTOR:
            return _Locator(count=1 if self.popup_open else 0)
        if selector == LOTTERY_PANEL_CLOSE_SELECTOR:
            return _Locator(
                count=1 if self.popup_open and self.close_available else 0,
                on_click=self._close_popup,
            )
        raise AssertionError(selector)

    def frame_locator(self, selector: str):
        assert selector == LOTTERY_IFRAME_SELECTOR
        return self.panel

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        del timeout
        assert selector in {LOTTERY_IFRAME_SELECTOR, ACTIVITY_LIKE_SELECTOR}

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout


class _Browser:
    def __init__(self, page: _Page):
        self.page = page

    async def open(self, url: str) -> _Page:
        assert url.startswith("https://www.bilibili.com/opus/")
        return self.page


class _ReservationPage:
    def __init__(self, label: str = "预约", *, followed: bool = False, liked: bool = False) -> None:
        self.label = label
        self.button = _Locator(on_click=self._reserve)
        self.body = _Locator("预约有奖：周年私皮回")
        self.button.text = label
        self.liked = liked
        self.like_button = _Locator(on_click=self._like)
        self.author = _Locator(
            "糯米是个背包",
            href="https://space.bilibili.com/492426375",
        )
        self.profile_page = _ProfilePage(followed=followed)

    def _reserve(self) -> None:
        self.label = "已预约"
        self.button.text = self.label
        self.body.text = "预约成功，已参与抽奖"

    def _like(self) -> None:
        self.liked = True

    def locator(self, selector: str):
        if selector in {"button", ".bili-dyn-card-reserve__card button"}:
            return _Controls([self.button])
        if selector == "body":
            return self.body
        if selector == ACTIVITY_LIKE_SELECTOR:
            return self.like_button
        if selector == ACTIVITY_LIKE_ACTIVE_SELECTOR:
            return _Controls([self.like_button]) if self.liked else _Controls([])
        if selector in {
            ".opus-module-author__name",
            ".bili-dyn-item__author",
            ".bili-dyn-item__author-name",
            '.bili-dyn-item__header .bili-dyn-title__text',
            'a[href*="space.bilibili.com/"]',
        }:
            return _Controls([self.author])
        return _Locator(count=0)

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        del timeout
        assert selector == ACTIVITY_LIKE_SELECTOR

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout


class _ProfilePage:
    def __init__(self, *, followed: bool = False) -> None:
        self.followed = followed
        self.button = _Locator(
            "已关注" if followed else "关注",
            on_click=self._follow,
        )

    def _follow(self) -> None:
        self.followed = True
        self.button.text = "已关注"

    def locator(self, selector: str):
        if selector == ".space-follow-btn":
            return _Controls([self.button])
        return _Controls([])


class _ReservationBrowser:
    def __init__(self, page: _ReservationPage) -> None:
        self.page = page
        self.opened_urls: list[str] = []

    async def open(self, url: str) -> _ReservationPage:
        self.opened_urls.append(url)
        if url.startswith("https://space.bilibili.com/"):
            return self.page.profile_page
        assert url.startswith("https://www.bilibili.com/opus/")
        return self.page


def test_live_selector_includes_the_verified_join_button_shape() -> None:
    assert "div.join-button" in LOTTERY_PARTICIPATION_CONTROLS_SELECTOR


@pytest.mark.asyncio
async def test_dom_transport_preserves_legacy_already_participated_without_any_click() -> None:
    panel = _Panel(
        "已成功参与",
        ["关注我并转发抽奖动态"],
        done_after_click=True,
    )
    page = _Page(panel)
    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED
    assert result.code == "ALREADY_PARTICIPATED"
    assert page.entry.clicks == 1
    assert panel.candidates[0].clicks == 0
    assert page.like_clicks == 0
    assert page.liked is False


@pytest.mark.asyncio
async def test_dom_transport_uses_liked_marker_before_opening_panel() -> None:
    panel = _Panel(
        "开奖时间：2026年08月14日 00:00",
        ["关注我并转发抽奖动态"],
        done_after_click=True,
    )
    page = _Page(panel, liked=True)
    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED
    assert result.code == "ALREADY_PARTICIPATED_LIKED"
    assert page.entry.clicks == 0
    assert page.like_clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_waits_for_delayed_iframe_hydration() -> None:
    panel = _Panel(
        "开奖时间：2026年08月14日 00:00 已成功参与",
        ["关注我并转发抽奖动态"],
        done_after_click=True,
        empty_body_reads=2,
    )
    page = _Page(panel)
    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED
    assert result.code == "ALREADY_PARTICIPATED"
    assert panel.candidates[0].clicks == 0
    assert page.like_clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_checks_delayed_success_before_searching_for_button() -> None:
    draw_time = "\u5f00\u5956\u65f6\u95f4\uff1a2026\u5e7408\u670814\u65e500:00"
    panel = _Panel(
        draw_time,
        [],
        done_after_click=False,
        body_texts=[draw_time, f"{draw_time} \u5df2\u6210\u529f\u53c2\u4e0e"],
    )
    page = _Page(panel)

    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/1234029204674183171",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED
    assert result.code == "ALREADY_PARTICIPATED"
    assert page.entry.clicks == 1
    assert page.like_clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_clicks_one_validated_control_and_confirms() -> None:
    panel = _Panel(
        "开奖时间：2026年08月14日 00:00",
        ["关注UP主并转发抽奖动态"],
        done_after_click=True,
    )
    page = _Page(panel)
    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert result.state is OfficialParticipationOutcomeState.SUCCESS
    assert result.code == "OFFICIAL_PARTICIPATION_CONFIRMED"
    assert panel.candidates[0].clicks == 1
    assert page.close_clicks == 1
    assert page.popup_open is False
    assert page.like_clicks == 1
    assert page.liked is True


@pytest.mark.asyncio
async def test_dom_transport_does_not_like_through_an_open_lottery_popup() -> None:
    panel = _Panel(
        "开奖时间：2026年08月14日 00:00",
        ["关注UP主并转发抽奖动态"],
        done_after_click=True,
    )
    page = _Page(panel, close_available=False)

    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/1233672735227379797",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.UNKNOWN
    assert result.code == "OFFICIAL_LOTTERY_PANEL_CLOSE_NOT_UNIQUE"
    assert panel.candidates[0].clicks == 1
    assert page.popup_open is True
    assert page.like_clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_rejects_ambiguous_or_missing_controls_without_click() -> None:
    ambiguous = _Panel(
        "开奖时间：2026年08月14日 00:00",
        ["关注我并转发抽奖动态", "转发抽奖动态"],
        done_after_click=True,
    )
    ambiguous_page = _Page(ambiguous)
    ambiguous_result = await DomOfficialParticipationTransport(_Browser(ambiguous_page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert ambiguous_result.code == "OFFICIAL_PARTICIPATION_BUTTON_AMBIGUOUS"
    assert all(item.clicks == 0 for item in ambiguous.candidates)

    missing = _Panel("开奖时间：2026年08月14日 00:00", ["查看规则"], done_after_click=True)
    missing_page = _Page(missing)
    missing_result = await DomOfficialParticipationTransport(_Browser(missing_page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert missing_result.code == "OFFICIAL_PARTICIPATION_BUTTON_NOT_FOUND"


@pytest.mark.asyncio
async def test_dom_transport_marks_expired_panel_without_click() -> None:
    panel = _Panel("抽奖已结束", ["关注我并转发抽奖动态"], done_after_click=True)
    page = _Page(panel)
    result = await DomOfficialParticipationTransport(_Browser(page)).perform(
        target_url="https://www.bilibili.com/opus/12345",
        payload={},
    )
    assert result.code == "LOTTERY_EXPIRED"
    assert panel.candidates[0].clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_confirms_reservation_and_does_not_open_lottery_panel():
    page = _ReservationPage()
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1221942213171216387",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.SUCCESS
    assert result.code == "RESERVATION_CONFIRMED"
    assert page.button.clicks == 1
    assert page.like_button.clicks == 1
    assert page.profile_page.button.clicks == 1


@pytest.mark.asyncio
async def test_dom_transport_processes_already_reserved_unliked_dynamic_and_marks_like():
    page = _ReservationPage(label="已预约")
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1221942213171216387",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.SUCCESS
    assert result.code == "RESERVATION_CONFIRMED"
    assert page.button.clicks == 0
    assert page.like_button.clicks == 1


@pytest.mark.asyncio
async def test_dom_transport_skips_liked_reservation_without_any_write():
    page = _ReservationPage(liked=True)
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1221942213171216387",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.ALREADY_PARTICIPATED
    assert result.code == "ALREADY_PARTICIPATED_LIKED"
    assert page.button.clicks == 0
    assert page.like_button.clicks == 0
    assert page.profile_page.button.clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_marks_ended_reservation_card_without_writes():
    page = _ReservationPage(label="已结束")
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1236314913256767520",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.EXPIRED
    assert result.code == "RESERVATION_EXPIRED"
    assert page.button.clicks == 0
    assert page.like_button.clicks == 0
    assert page.profile_page.button.clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_skips_watch_only_reservation_card_without_writes():
    page = _ReservationPage(label="去观看")
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1236223920055517329",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.EXPIRED
    assert result.code == "RESERVATION_WATCH_ONLY_SKIPPED"
    assert page.button.clicks == 0
    assert page.like_button.clicks == 0
    assert page.profile_page.button.clicks == 0


@pytest.mark.asyncio
async def test_dom_transport_skips_reservation_that_expires_after_click():
    class ExpiredAfterClickPage(_ReservationPage):
        def __init__(self) -> None:
            super().__init__()
            self.alert = ""

        def _reserve(self) -> None:
            self.alert = "预约已过期"

        def locator(self, selector: str):
            if selector == '[role="alert"]':
                return _Locator(self.alert, count=1 if self.alert else 0)
            return super().locator(selector)

    page = ExpiredAfterClickPage()
    result = await DomOfficialParticipationTransport(_ReservationBrowser(page)).perform(
        target_url="https://www.bilibili.com/opus/1235086118820511764",
        payload={},
    )

    assert result.state is OfficialParticipationOutcomeState.EXPIRED
    assert result.code == "RESERVATION_EXPIRED"
    assert page.button.clicks == 1
    assert page.like_button.clicks == 0
    assert page.profile_page.button.clicks == 0


def test_draw_time_field_wins_over_explicit_expiry_copy() -> None:
    result = classify_official_panel_text(
        "开奖倒计时 04 天 10 时 41 分 开奖时间 2026年08月14日 抽奖已失效"
    )

    assert result is None


def test_missing_draw_time_field_is_expired() -> None:
    result = classify_official_panel_text("抽奖已结束 一等奖名单")

    assert result is not None
    assert result.state is OfficialParticipationOutcomeState.EXPIRED
    assert result.code == "LOTTERY_EXPIRED"
