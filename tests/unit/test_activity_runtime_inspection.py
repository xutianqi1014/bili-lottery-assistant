import pytest

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.requirements import RequirementParser
from backend.activity_engine.runtime_inspection import RuntimeActivityReader


class _Locator:
    def __init__(
        self,
        count: int,
        text: str = "",
        on_click=None,
        visible: bool | None = None,
        on_inner_text=None,
    ) -> None:
        self._count = count
        self._text = text
        self._on_click = on_click
        self._visible = visible
        self._on_inner_text = on_inner_text

    async def count(self) -> int:
        return self._count

    async def inner_text(self, timeout: int = 0) -> str:
        if self._on_inner_text is not None:
            return self._on_inner_text()
        return self._text

    async def click(self, timeout: int = 0) -> None:
        if self._on_click is not None:
            self._on_click()

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        return None

    async def is_visible(self) -> bool:
        return self._visible if self._visible is not None else bool(self._count)


class _FrameLocator:
    def __init__(self, text_or_provider) -> None:
        self._text = text_or_provider

    def locator(self, selector: str) -> _Locator:
        if callable(self._text):
            return _Locator(1, on_inner_text=self._text)
        return _Locator(1, self._text)


class _Page:
    url = "https://www.bilibili.com/opus/400000001"

    def __init__(
        self,
        panel_text: str = "",
        show_panel: bool = True,
        panel_ready_after_waits: int = 0,
        body: str = "互动抽奖 评论 #抽奖# @2名好友",
        liked: bool = False,
    ) -> None:
        self.panel_text = panel_text
        self.show_panel = show_panel
        self.panel_ready_after_waits = panel_ready_after_waits
        self.panel_waits = 0
        self.body = body
        self.liked = liked
        self.clicked = False

    async def content(self) -> str:
        return '<a data-type="lottery" href="#">互动抽奖</a>'

    async def title(self) -> str:
        return "测试动态"

    def locator(self, selector: str) -> _Locator:
        if selector == "body":
            return _Locator(1, self.body)
        if selector == 'a[data-type="lottery"]':
            return _Locator(1, on_click=lambda: setattr(self, "clicked", True))
        if selector == 'iframe[src*="/h5/lottery/result"]':
            return _Locator(1 if self.clicked and self.show_panel else 0)
        if selector == ".side-toolbar__action.like.is-active":
            return _Locator(1 if self.liked else 0)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like.is-active",
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[aria-pressed="true"]',
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[data-state="active"]',
            '.content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > '
            '.side-toolbar__action.like[data-liked="true"]',
        }:
            return _Locator(1 if self.liked else 0)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like",
            ".content .sidebar-wrap .side-toolbar__action.like",
            ".side-toolbar__action.like",
            ".bili-dyn-action.like",
        }:
            return _Locator(1)
        return _Locator(0)

    def frame_locator(self, selector: str) -> _FrameLocator:
        return _FrameLocator(
            lambda: self.panel_text
            if self.panel_waits >= self.panel_ready_after_waits
            else ""
        )

    async def wait_for_timeout(self, timeout: int) -> None:
        self.panel_waits += 1


class _Browser:
    def __init__(
        self,
        panel_text: str = "",
        show_panel: bool = True,
        panel_ready_after_waits: int = 0,
        body: str = "互动抽奖 评论 #抽奖# @2名好友",
        liked: bool = False,
    ) -> None:
        self.panel_text = panel_text
        self.show_panel = show_panel
        self.panel_ready_after_waits = panel_ready_after_waits
        self.body = body
        self.liked = liked
        self.page: _Page | None = None

    async def open(self, url: str) -> _Page:
        self.page = _Page(
            self.panel_text,
            self.show_panel,
            self.panel_ready_after_waits,
            self.body,
            self.liked,
        )
        return self.page


class _BoostedForwardPage(_Page):
    """A boosted outer dynamic whose quoted original exposes a lottery link."""

    url = "https://t.bilibili.com/1238160555189993490"

    async def content(self) -> str:
        return (
            '<div class="bili-dyn-content__forw__desc" data-orig="0">'
            "转发并关注，完成评论后加码奖励"
            "</div>"
            '<div class="bili-dyn-content__orig reference" data-orig="1">'
            '<a data-type="lottery" href="#">内层互动抽奖</a>'
            "</div>"
        )

    def locator(self, selector: str) -> _Locator:
        if selector == "body":
            return _Locator(1, "转发并关注，完成评论后加码奖励 内层互动抽奖")
        if selector == '.bili-dyn-content__forw__desc[data-orig="0"]':
            return _Locator(1, "转发并关注，完成评论后加码奖励")
        if selector == ".bili-dyn-content__orig.reference":
            return _Locator(1, "内层互动抽奖")
        if selector == '.bili-dyn-content__orig.reference a[data-type="lottery"]':
            return _Locator(1)
        if selector == 'a[data-type="lottery"]':
            return _Locator(1, on_click=lambda: setattr(self, "clicked", True))
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like",
            ".content .sidebar-wrap .side-toolbar__action.like",
            ".side-toolbar__action.like",
            ".bili-dyn-action.like",
        }:
            return _Locator(1)
        return _Locator(0)


class _BoostedForwardBrowser(_Browser):
    async def open(self, url: str) -> _BoostedForwardPage:
        del url
        self.page = _BoostedForwardPage()
        return self.page


class _ReservationLocator:
    def __init__(
        self,
        page: "_ReservationPage",
        count: int = 1,
        *,
        body: bool = False,
    ) -> None:
        self.page = page
        self._count = count
        self._body = body

    async def count(self) -> int:
        return self._count

    def nth(self, index: int) -> "_ReservationLocator":
        assert index == 0
        return self

    async def inner_text(self, timeout: int = 0) -> str:
        del timeout
        return self.page.body_text if self._body else self.page.reservation_label

    async def is_visible(self) -> bool:
        return True


class _ReservationPage:
    url = "https://www.bilibili.com/opus/1221942213171216387"
    reservation_label = "预约"
    body_text = "预约有奖：周年私皮回"

    async def content(self) -> str:
        return "<main>预约有奖：周年私皮回</main>"

    async def title(self) -> str:
        return "预约有奖：周年私皮回"

    def locator(self, selector: str) -> _ReservationLocator:
        if selector in {"button", ".bili-dyn-card-reserve__card button"}:
            return _ReservationLocator(self)
        if selector in {
            ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
            ".side-toolbar__action.like",
            ".content .sidebar-wrap .side-toolbar__action.like",
            ".side-toolbar__action.like",
            ".bili-dyn-action.like",
        }:
            return _ReservationLocator(self)
        if selector == "body":
            return _ReservationLocator(self, body=True)
        return _ReservationLocator(self, count=0)

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout


class _ReservationBrowser:
    async def open(self, url: str) -> _ReservationPage:
        del url
        return _ReservationPage()


@pytest.mark.asyncio
async def test_reader_and_shared_classifier_are_single_item_read_only():
    result = await RuntimeActivityReader().read(
        _Browser("开奖时间：2026年08月09日 18:00 已成功参与"),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )
    classification = ActivityClassifier().classify(result.snapshot)
    requirements = RequirementParser().parse(result.snapshot.body_text)
    assert classification.mode.value == "official"
    assert "OFFICIAL_IFRAME_ENTRY" in classification.evidence_codes
    assert "OFFICIAL_LOTTERY_PANEL_OPENED" in classification.evidence_codes
    assert result.lottery_entry_opened is True
    assert result.snapshot.already_participated_text is True
    assert requirements.required_topics == ("#抽奖#",)
    assert requirements.required_mention_count == 2


@pytest.mark.asyncio
async def test_reader_ignores_nested_official_entry_in_boosted_outer_dynamic():
    browser = _BoostedForwardBrowser()

    result = await RuntimeActivityReader().read(
        browser,
        "1238160555189993490",
        "https://t.bilibili.com/1238160555189993490",
    )
    classification = ActivityClassifier().classify(result.snapshot)

    assert classification.mode.value == "unofficial"
    assert classification.unofficial_type.value == "boosted"
    assert result.snapshot.has_forwarded_original is True
    assert result.snapshot.has_official_lottery_entry is False
    assert result.lottery_entry_opened is False
    assert browser.page is not None and browser.page.clicked is False
    assert "BOOSTED_NESTED_OFFICIAL_ENTRY_IGNORED" in result.snapshot.nonofficial_dom_evidence


@pytest.mark.asyncio
async def test_reader_reports_lottery_panel_open_failure_without_submitting():
    browser = _Browser(show_panel=False)
    result = await RuntimeActivityReader().read(
        browser, "400000001", "https://www.bilibili.com/opus/400000001"
    )

    assert browser.page is not None and browser.page.clicked is True
    assert result.lottery_entry_opened is False
    assert result.lottery_panel_error == "OFFICIAL_LOTTERY_PANEL_NOT_FOUND"
    assert result.snapshot.official_lottery_panel_error == "OFFICIAL_LOTTERY_PANEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_reader_waits_for_hydrated_panel_text_before_judging_participation():
    result = await RuntimeActivityReader().read(
        _Browser(panel_text="已成功参与", panel_ready_after_waits=2, body="互动抽奖"),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.snapshot.already_participated_text is True
    assert "已成功参与" in result.lottery_panel_text


@pytest.mark.asyncio
async def test_reader_does_not_treat_empty_panel_as_manual_gate_success():
    result = await RuntimeActivityReader().read(
        _Browser(panel_text="", body="互动抽奖"),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.lottery_entry_opened is True
    assert result.lottery_panel_error == "OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY"
    assert result.snapshot.official_lottery_panel_error == "OFFICIAL_LOTTERY_PANEL_TEXT_EMPTY"


@pytest.mark.asyncio
async def test_reader_uses_active_countdown_as_authoritative_not_expired_signal():
    result = await RuntimeActivityReader().read(
        _Browser(
            panel_text="抽奖已结束 开奖倒计时 03 天 19 时 22 分 开奖时间：2026年08月12日 18:00",
            body="互动抽奖 抽奖已结束",
        ),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.snapshot.official_lottery_panel_opened is True
    assert result.snapshot.expired_text is False


@pytest.mark.asyncio
async def test_reader_treats_missing_draw_time_field_as_expired():
    result = await RuntimeActivityReader().read(
        _Browser(panel_text="暂时无法参与"),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.snapshot.expired_text is True


@pytest.mark.asyncio
async def test_reader_uses_liked_marker_without_opening_lottery_panel():
    browser = _Browser(
        panel_text="开奖时间：2026年08月12日 18:00",
        liked=True,
    )
    result = await RuntimeActivityReader().read(
        browser,
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert browser.page is not None and browser.page.clicked is False
    assert result.snapshot.activity_like_active is True
    assert result.snapshot.has_official_lottery_entry is False
    assert result.snapshot.has_reservation_entry is False
    assert result.snapshot.nonofficial_dom_evidence == ()


@pytest.mark.asyncio
async def test_reader_checks_like_before_collecting_type_specific_evidence():
    class _TrackedPage(_Page):
        def __init__(self) -> None:
            super().__init__(
                panel_text="开奖时间：2026年08月12日 18:00",
                liked=True,
            )
            self.selectors: list[str] = []

        def locator(self, selector: str) -> _Locator:
            self.selectors.append(selector)
            return super().locator(selector)

    class _TrackedBrowser(_Browser):
        async def open(self, url: str) -> _TrackedPage:
            del url
            self.page = _TrackedPage()
            return self.page

    browser = _TrackedBrowser()
    result = await RuntimeActivityReader().read(
        browser,
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.snapshot.activity_like_active is True
    assert browser.page is not None
    assert any(selector.endswith(".like.is-active") for selector in browser.page.selectors)
    assert 'a[data-type="lottery"]' not in browser.page.selectors
    assert not any("reserve" in selector for selector in browser.page.selectors)


@pytest.mark.asyncio
async def test_reader_accepts_modern_active_like_marker_before_type_reads():
    class _ModernLikePage(_Page):
        def locator(self, selector: str) -> _Locator:
            if selector in {".bili-dyn-action.like.active", ".bili-dyn-action.like"}:
                return _Locator(1)
            return super().locator(selector)

    class _ModernLikeBrowser(_Browser):
        async def open(self, url: str) -> _ModernLikePage:
            del url
            self.page = _ModernLikePage(panel_text="开奖时间：2026年08月12日 18:00")
            return self.page

    browser = _ModernLikeBrowser()
    result = await RuntimeActivityReader().read(
        browser,
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.activity_like_state == "liked"
    assert result.snapshot.activity_like_active is True
    assert result.lottery_entry_opened is False


@pytest.mark.asyncio
async def test_reader_blocks_type_reads_when_like_control_is_unknown():
    class _NoLikePage(_Page):
        def locator(self, selector: str) -> _Locator:
            if selector in {
                ".content > .sidebar-wrap > .side-toolbar > .side-toolbar__box > "
                ".side-toolbar__action.like",
                ".content .sidebar-wrap .side-toolbar__action.like",
                ".side-toolbar__action.like",
                ".bili-dyn-action.like",
            }:
                return _Locator(0)
            return super().locator(selector)

    class _NoLikeBrowser(_Browser):
        async def open(self, url: str) -> _NoLikePage:
            del url
            self.page = _NoLikePage(panel_text="开奖时间：2026年08月12日 18:00")
            return self.page

    browser = _NoLikeBrowser()
    result = await RuntimeActivityReader().read(
        browser,
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.activity_like_unknown is True
    assert result.activity_like_reason_code == "ACTIVITY_LIKE_CONTROL_NOT_FOUND"
    assert result.lottery_entry_opened is False


@pytest.mark.asyncio
async def test_reader_waits_after_navigation_before_first_body_read(monkeypatch):
    events: list[object] = []

    class DelayedPage(_Page):
        async def content(self) -> str:
            events.append("content")
            return await super().content()

    class DelayedBrowser(_Browser):
        async def open(self, url: str) -> DelayedPage:
            del url
            events.append("open")
            self.page = DelayedPage(
                self.panel_text,
                self.show_panel,
                self.panel_ready_after_waits,
                self.body,
                self.liked,
            )
            return self.page

    async def fake_sleep(delay: float) -> None:
        events.append(delay)

    monkeypatch.setattr(
        "backend.activity_engine.runtime_inspection.reader.asyncio.sleep",
        fake_sleep,
    )

    await RuntimeActivityReader().read(
        DelayedBrowser(body="普通抽奖 评论 转发"),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
        post_open_delay_sec=1.25,
    )

    assert events[:3] == ["open", 1.25, "content"]


@pytest.mark.asyncio
async def test_reader_accepts_bilibili_t_subdomain_redirect():
    page = _Page()
    page.url = "https://t.bilibili.com/400000001"

    class Browser:
        async def open(self, url: str) -> _Page:
            del url
            return page

    result = await RuntimeActivityReader().read(
        Browser(), "400000001", "https://www.bilibili.com/opus/400000001"
    )

    assert result.snapshot.dynamic_id == "400000001"


@pytest.mark.asyncio
async def test_reader_rejects_redirect_to_another_activity():
    page = _Page()
    page.url = "https://www.bilibili.com/opus/400000002"

    class Browser:
        async def open(self, url: str) -> _Page:
            return page

    with pytest.raises(ValueError, match="ACTIVITY_ID_MISMATCH"):
        await RuntimeActivityReader().read(
            Browser(), "400000001", "https://www.bilibili.com/opus/400000001"
        )


@pytest.mark.asyncio
async def test_reader_marks_bilibili_error_shell_as_unavailable_dynamic():
    class UnavailablePage:
        url = "https://www.bilibili.com/opus/400000001"

        async def content(self) -> str:
            return "<main>返回上一页 <a href='#up'>换一张</a></main>"

        async def title(self) -> str:
            return "出错啦! - bilibili.com"

        def locator(self, selector: str) -> _Locator:
            if selector == "body":
                return _Locator(1, "返回上一页 换一张")
            return _Locator(0)

    class UnavailableBrowser:
        async def open(self, url: str) -> UnavailablePage:
            del url
            return UnavailablePage()

    result = await RuntimeActivityReader().read(
        UnavailableBrowser(),
        "400000001",
        "https://www.bilibili.com/opus/400000001",
    )

    assert result.dynamic_unavailable is True
    assert result.snapshot.expired_text is True
    assert result.snapshot.has_official_lottery_entry is False
    assert result.snapshot.has_reservation_entry is False


@pytest.mark.asyncio
async def test_reader_detects_reservation_button_without_opening_official_panel():
    result = await RuntimeActivityReader().read(
        _ReservationBrowser(),
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
    )

    assert result.snapshot.has_official_lottery_entry is False
    assert result.snapshot.has_reservation_entry is True
    assert result.snapshot.reservation_active is False
    assert result.snapshot.reservation_control_text == "预约"


@pytest.mark.asyncio
async def test_reader_uses_only_reservation_prize_marker_not_ended_button() -> None:
    class EndedReservationPage(_ReservationPage):
        reservation_label = "已结束"
        body_text = "直播预约：王者游戏回 预约有奖：甜水卡*1份"

        async def content(self) -> str:
            return "<main>直播预约：王者游戏回 预约有奖：甜水卡*1份</main>"

    class EndedReservationBrowser:
        async def open(self, url: str) -> EndedReservationPage:
            del url
            return EndedReservationPage()

    result = await RuntimeActivityReader().read(
        EndedReservationBrowser(),
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
    )

    assert result.snapshot.has_reservation_entry is True
    assert result.snapshot.reservation_control_text == "已结束"
    assert result.snapshot.expired_text is True


@pytest.mark.asyncio
async def test_reader_treats_watch_only_reservation_card_as_terminal() -> None:
    class WatchOnlyReservationPage(_ReservationPage):
        url = "https://www.bilibili.com/opus/1236223920055517329"
        reservation_label = "去观看"
        body_text = "预约有奖：直播回放"

        async def content(self) -> str:
            return "<main>预约有奖：直播回放</main>"

    class WatchOnlyReservationBrowser:
        async def open(self, url: str) -> WatchOnlyReservationPage:
            del url
            return WatchOnlyReservationPage()

    result = await RuntimeActivityReader().read(
        WatchOnlyReservationBrowser(),
        "1236223920055517329",
        "https://www.bilibili.com/opus/1236223920055517329",
    )

    assert result.snapshot.has_reservation_entry is True
    assert result.snapshot.reservation_control_text == "去观看"
    assert result.snapshot.expired_text is True


@pytest.mark.asyncio
async def test_reader_treats_expired_reservation_button_as_terminal() -> None:
    class ExpiredReservationPage(_ReservationPage):
        url = "https://www.bilibili.com/opus/1235086118820511764"
        reservation_label = "预约已过期"
        body_text = "预约有奖：直播回放 预约已过期"

    class ExpiredReservationBrowser:
        async def open(self, url: str) -> ExpiredReservationPage:
            del url
            return ExpiredReservationPage()

    result = await RuntimeActivityReader().read(
        ExpiredReservationBrowser(),
        "1235086118820511764",
        "https://www.bilibili.com/opus/1235086118820511764",
    )

    assert result.snapshot.has_reservation_entry is True
    assert result.snapshot.reservation_control_text == "预约已过期"
    assert result.snapshot.expired_text is True


@pytest.mark.asyncio
async def test_reader_detects_revoked_live_reservation_without_prize_marker() -> None:
    class RevokedReservationPage(_ReservationPage):
        url = "https://www.bilibili.com/opus/1237497060024909832"
        reservation_label = "已撤销"
        body_text = "直播预约：试胆大会 明天 05:00 直播 已撤销"

        async def content(self) -> str:
            return (
                "<main>直播预约：试胆大会 明天 05:00 直播 "
                "<div class='bili-dyn-card-reserve__card'><button>已撤销</button>"
                "</div></main>"
            )

    class RevokedReservationBrowser:
        async def open(self, url: str) -> RevokedReservationPage:
            del url
            return RevokedReservationPage()

    result = await RuntimeActivityReader().read(
        RevokedReservationBrowser(),
        "1237497060024909832",
        "https://www.bilibili.com/opus/1237497060024909832",
    )

    assert result.snapshot.has_official_lottery_entry is False
    assert result.snapshot.has_reservation_entry is True
    assert result.snapshot.reservation_control_text == "已撤销"
    assert result.snapshot.expired_text is True


@pytest.mark.asyncio
async def test_reader_does_not_classify_generic_reservation_word_as_reservation():
    class GenericReservationPage(_ReservationPage):
        def __init__(self) -> None:
            self.reservation_label = "查看详情"
            self.body_text = "直播预约：周年直播，请大家预约观看"

        async def content(self) -> str:
            return "<main>直播预约：周年直播，请大家预约观看</main>"

        async def title(self) -> str:
            return "直播预约：周年直播"

    class GenericReservationBrowser:
        async def open(self, url: str) -> GenericReservationPage:
            del url
            return GenericReservationPage()

    result = await RuntimeActivityReader().read(
        GenericReservationBrowser(),
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
    )

    assert result.snapshot.has_reservation_entry is False


@pytest.mark.asyncio
async def test_reader_does_not_classify_reservation_button_without_prize_marker():
    class ButtonOnlyPage(_ReservationPage):
        body_text = "普通动态正文"

    class ButtonOnlyBrowser:
        async def open(self, url: str) -> ButtonOnlyPage:
            del url
            return ButtonOnlyPage()

    result = await RuntimeActivityReader().read(
        ButtonOnlyBrowser(),
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
    )

    assert result.snapshot.has_reservation_entry is False
