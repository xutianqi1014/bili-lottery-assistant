import json

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.models import ActivityMode, ActivitySnapshot
from backend.activity_engine.source_policy import (
    DEFAULT_ACTIVITY_MODES,
    NUOMI_ACTIVITY_MODES,
    TOMATO_FRIES_ACTIVITY_MODES,
    policy_from_profile,
)


def test_builtin_source_policies_have_disjoint_allowed_type_sets() -> None:
    default = policy_from_profile(
        source_key="lottery_toolman",
        adapter_key="lottery_toolman_v1",
        config_json=json.dumps({"activityTypes": ["official", "unofficial"]}),
    )
    nuomi = policy_from_profile(
        source_key="nuomi_backpack",
        adapter_key="nuomi_backpack_v1",
        config_json=json.dumps({"activityTypes": ["official", "reservation"]}),
    )

    assert default.allowed_modes == DEFAULT_ACTIVITY_MODES
    assert nuomi.allowed_modes == NUOMI_ACTIVITY_MODES
    assert default.allowed_type_names == ("official", "unofficial")
    assert nuomi.allowed_type_names == ("official", "reservation")

    tomato = policy_from_profile(
        source_key="tomato_fries",
        adapter_key="tomato_fries_v1",
        config_json=json.dumps({"activityTypes": ["official", "unofficial", "reservation"]}),
    )
    assert tomato.allowed_modes == TOMATO_FRIES_ACTIVITY_MODES
    assert tomato.allowed_type_names == ("official", "unofficial", "reservation")


def test_default_source_keeps_reservation_distinct_from_unofficial() -> None:
    snapshot = ActivitySnapshot(
        "1236380630515712009",
        "https://www.bilibili.com/opus/1236380630515712009",
        "预约抽奖 评论 转发 关注",
        has_reservation_entry=True,
        reservation_control_text="预约",
        actionable_text="评论转发关注，预约抽奖",
        nonofficial_dom_evidence=("UNOFFICIAL_SCOPED_BODY_FOUND",),
    )

    result = ActivityClassifier().classify(
        snapshot,
        allowed_modes=DEFAULT_ACTIVITY_MODES,
    )

    assert result.mode is ActivityMode.RESERVATION
    assert "SOURCE_POLICY_RESERVATION_AS_UNOFFICIAL" not in result.evidence_codes


def test_nuomi_source_keeps_reservation_card_as_reservation() -> None:
    snapshot = ActivitySnapshot(
        "1221942213171216387",
        "https://www.bilibili.com/opus/1221942213171216387",
        "预约抽奖",
        has_reservation_entry=True,
        reservation_control_text="预约",
    )

    result = ActivityClassifier().classify(
        snapshot,
        allowed_modes=NUOMI_ACTIVITY_MODES,
    )

    assert result.mode is ActivityMode.RESERVATION
