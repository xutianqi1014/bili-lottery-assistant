from backend.activity_engine.unofficial.page_evidence import (
    read_unofficial_page_evidence,
)


class _Locator:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    @property
    def first(self) -> "_Locator":
        return _Locator(self.values[:1])

    async def count(self) -> int:
        return len(self.values)

    async def inner_text(self, timeout: int = 0) -> str:
        del timeout
        return self.values[0] if self.values else ""

    def nth(self, index: int) -> "_Locator":
        return _Locator(self.values[index : index + 1])


class _Page:
    def __init__(self) -> None:
        self.values = {
            '.bili-dyn-content__forw__desc[data-orig="0"]': [
                "关注两个账号，转发+点赞+评论，8月19日抽奖"
            ],
            ".bili-dyn-content__orig.reference": [
                "内层原动态及其另一套参与要求"
            ],
            "bili-comments bili-comment-box bili-comment-rich-textarea .brt-editor": [
                ""
            ],
            "bili-comments bili-comment-box button": ["表情", "发布"],
            "bili-comments bili-comment-box bili-checkbox": ["同时转发到我的动态"],
            ".bili-dyn-item__header .bili-dyn-title__text": ["示例发布者"],
        }

    def locator(self, selector: str) -> _Locator:
        return _Locator(self.values.get(selector, []))


async def test_reads_outer_and_inner_layers_without_clicking():
    evidence = await read_unofficial_page_evidence(_Page())

    assert evidence.outer_text.startswith("关注两个账号")
    assert evidence.forwarded_original_text.startswith("内层原动态")
    assert evidence.has_forwarded_original is True
    assert evidence.comment_editor_present is True
    assert evidence.comment_publish_present is True
    assert evidence.comment_repost_control_present is True
    assert evidence.author_name == "示例发布者"
    assert "UNOFFICIAL_FORWARDED_ORIGINAL_FOUND" in evidence.evidence_codes
