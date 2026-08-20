import pytest

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.models import (
    ActionState,
    ActivityMode,
    ActivitySnapshot,
    UnofficialType,
)
from backend.activity_engine.official import OfficialFlow
from backend.activity_engine.requirements import RequirementParser
from backend.activity_engine.shared import ManualGate
from backend.activity_engine.unofficial import UnofficialFlow


def test_classifies_official_iframe_signal():
    result = ActivityClassifier().classify(
        ActivitySnapshot(
            "1",
            "https://www.bilibili.com/opus/1",
            "",
            has_official_lottery_entry=True,
        )
    )
    assert result.mode is ActivityMode.OFFICIAL
    assert result.confidence == "high"


def test_classifies_reservation_control_as_distinct_official_automation_type():
    result = ActivityClassifier().classify(
        ActivitySnapshot(
            "1221942213171216387",
            "https://www.bilibili.com/opus/1221942213171216387",
            "直播预约：周年私皮回",
            has_reservation_entry=True,
            reservation_control_text="预约",
        )
    )

    assert result.mode is ActivityMode.RESERVATION
    assert result.is_participated is False
    assert result.evidence_codes == (
        "RESERVATION_ENTRY",
        "RESERVATION_ACTIVITY_UNLIKED_MARKER",
        "RESERVATION_UNBOOKED",
    )


@pytest.mark.asyncio
async def test_reservation_flow_does_not_use_reservation_button_as_participation_marker():
    snapshot = ActivitySnapshot(
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
        "直播预约：周年私皮回",
        has_reservation_entry=True,
        reservation_active=True,
        reservation_control_text="已预约",
    )

    result = await OfficialFlow(ManualGate(True)).prepare(
        snapshot,
        ActivityClassifier().classify(snapshot),
    )

    assert result.state is ActionState.WAITING_USER
    assert result.code == "MANUAL_GATE_REQUIRED"


@pytest.mark.asyncio
async def test_reservation_flow_skips_when_dynamic_like_is_active():
    snapshot = ActivitySnapshot(
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
        "直播预约：周年私皮回",
        has_reservation_entry=True,
        reservation_active=False,
        activity_like_active=True,
    )

    result = await OfficialFlow(ManualGate(True)).prepare(
        snapshot,
        ActivityClassifier().classify(snapshot),
    )

    assert result.state is ActionState.ALREADY_LIKED_SKIPPED
    assert result.code == "ALREADY_PARTICIPATED_LIKED"


@pytest.mark.asyncio
async def test_reservation_flow_skips_watch_only_card_without_writes():
    snapshot = ActivitySnapshot(
        "1236223920055517329",
        "https://www.bilibili.com/opus/1236223920055517329",
        "预约有奖：直播回放",
        has_reservation_entry=True,
        reservation_control_text="去观看",
    )

    result = await OfficialFlow(ManualGate(True)).prepare(
        snapshot,
        ActivityClassifier().classify(snapshot),
    )

    assert result.state is ActionState.EXPIRED
    assert result.code == "RESERVATION_WATCH_ONLY_SKIPPED"


@pytest.mark.asyncio
async def test_reservation_flow_skips_revoked_live_without_writes():
    snapshot = ActivitySnapshot(
        "1237497060024909832",
        "https://www.bilibili.com/opus/1237497060024909832",
        "直播预约：试胆大会 已撤销",
        has_reservation_entry=True,
        reservation_control_text="已撤销",
        expired_text=True,
    )

    result = await OfficialFlow(ManualGate(True)).prepare(
        snapshot,
        ActivityClassifier().classify(snapshot),
    )

    assert result.state is ActionState.EXPIRED
    assert result.code == "RESERVATION_EXPIRED"


def test_missing_official_entry_falls_back_to_unofficial():
    result = ActivityClassifier().classify(
        ActivitySnapshot("1", "https://www.bilibili.com/opus/1", "")
    )

    assert result.mode is ActivityMode.UNOFFICIAL
    assert result.unofficial_type is UnofficialType.NORMAL
    assert result.confidence == "low"
    assert result.evidence_codes == ("NON_OFFICIAL_FALLBACK_NO_OFFICIAL_ENTRY",)


def test_classifies_boosted_unofficial_text():
    result = ActivityClassifier().classify(
        ActivitySnapshot("1", "https://www.bilibili.com/opus/1", "评论转发关注，完成后加码奖励")
    )
    assert result.mode is ActivityMode.UNOFFICIAL
    assert result.unofficial_type.value == "boosted"


def test_classifies_forwarded_outer_dynamic_as_boosted_without_keyword():
    result = ActivityClassifier().classify(
        ActivitySnapshot(
            "1234423607216570384",
            "https://t.bilibili.com/1234423607216570384",
            "外层要求和内层原动态",
            actionable_text="关注两个账号，转发+点赞+评论，8月19日抽奖",
            has_forwarded_original=True,
            nonofficial_dom_evidence=("UNOFFICIAL_FORWARDED_ORIGINAL_FOUND",),
        )
    )

    assert result.mode is ActivityMode.UNOFFICIAL
    assert result.unofficial_type is UnofficialType.BOOSTED
    assert result.confidence == "high"
    assert "BOOSTED_FORWARDED_OUTER_DYNAMIC" in result.evidence_codes


def test_requirement_parser_deduplicates_topics_and_reads_mentions():
    result = RequirementParser().parse("评论 #抽奖# #抽奖#，@3名好友")
    assert result.required_topics == ("#抽奖#",)
    assert result.required_mention_count == 3


@pytest.mark.parametrize(
    ("text", "instruction"),
    [
        (
            "关注UP，转发并分享你的EC6清凉小妙招，我们将抽取1位朋友",
            "分享你的EC6清凉小妙招",
        ),
        ("欢迎在评论区聊聊入秋后最关心的空气问题", "聊聊入秋后最关心的空气问题"),
        ("在评论区分享你的蔚来ES9驾乘体验", "分享你的蔚来ES9驾乘体验"),
    ],
)
def test_requirement_parser_reads_implicit_comment_instructions(
    text: str, instruction: str
):
    result = RequirementParser().parse(text)

    assert instruction in result.comment_instruction
    assert "comment" in result.required_actions


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("请在评论区@三名好友", 3),
        ("艾特两位朋友", 2),
        ("at好友12人", 12),
    ],
)
def test_requirement_parser_reads_chinese_and_reversed_mention_counts(
    text: str, count: int
):
    assert RequirementParser().parse(text).required_mention_count == count


def test_requirement_parser_flags_unsafe_mention_count():
    result = RequirementParser().parse("评论并@21名好友")

    assert result.required_mention_count == 21
    assert result.mention_limit_exceeded is True
    assert "REQUIREMENT_MENTION_LIMIT_EXCEEDED" in result.evidence_codes


@pytest.mark.asyncio
async def test_flows_stop_at_manual_gate():
    gate = ManualGate(direct_write_enabled=False)
    official = await OfficialFlow(gate).prepare(
        ActivitySnapshot(
            "1",
            "https://www.bilibili.com/opus/1",
            "",
            has_official_lottery_entry=True,
        ),
        ActivityClassifier().classify(
            ActivitySnapshot(
                "1",
                "https://www.bilibili.com/opus/1",
                "",
                has_official_lottery_entry=True,
            )
        ),
    )
    assert official.state is ActionState.WAITING_USER
    unofficial = await UnofficialFlow(gate).prepare(
        ActivitySnapshot("2", "https://www.bilibili.com/opus/2", "评论转发关注"),
        ActivityClassifier().classify(
            ActivitySnapshot("2", "https://www.bilibili.com/opus/2", "评论转发关注")
        ),
    )
    assert unofficial.state is ActionState.WAITING_USER


def test_unofficial_flow_exposes_read_only_action_plan():
    plan = UnofficialFlow(ManualGate(False)).action_plan()
    assert [action.value for action in plan.actions] == [
        "comment",
        "repost",
        "like",
        "follow",
    ]
    assert plan.direct_write_enabled is False
    assert plan.unknown_result_policy == "manual_review_no_retry"


def test_boosted_plan_uses_comment_checkbox_repost_strategy():
    classification = ActivityClassifier().classify(
        ActivitySnapshot(
            "1",
            "https://t.bilibili.com/1",
            "关注、转发、点赞、评论",
            actionable_text="关注、转发、点赞、评论",
            has_forwarded_original=True,
        )
    )
    requirements = RequirementParser().parse("关注、转发、点赞、评论")
    plan = UnofficialFlow(ManualGate(False)).action_plan(
        classification, requirements
    )

    assert [action.value for action in plan.actions] == [
        "comment",
        "repost",
        "like",
        "follow",
    ]
    assert plan.interaction_strategy == "comment_with_repost_checkbox"
    assert plan.target_scope == "current_dynamic"
    assert plan.unofficial_type == "boosted"
