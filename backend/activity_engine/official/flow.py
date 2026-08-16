from backend.activity_engine.models import (
    ActionResult,
    ActionState,
    ActivityClassification,
    ActivityMode,
    ActivitySnapshot,
)
from backend.activity_engine.shared.manual_gate import ManualGate


class OfficialFlow:
    """Read/prepare official participation; mutation is intentionally gated."""

    def __init__(self, gate: ManualGate):
        self.gate = gate

    async def prepare(
        self,
        snapshot: ActivitySnapshot,
        classification: ActivityClassification,
    ) -> ActionResult:
        if classification.mode not in {
            ActivityMode.OFFICIAL,
            ActivityMode.RESERVATION,
        }:
            return ActionResult(
                ActionState.MODE_MISMATCH,
                "MODE_MISMATCH",
                "来源预期官方或预约流程，但目标动态未被稳定识别。",
                True,
            )
        if classification.mode is ActivityMode.RESERVATION:
            if snapshot.activity_like_active:
                return ActionResult(
                    ActionState.ALREADY_LIKED_SKIPPED,
                    "ALREADY_PARTICIPATED_LIKED",
                    "预约抽奖动态已经点赞，按动态点赞参与标记跳过。",
                )
            if snapshot.reservation_control_text == "去观看":
                return ActionResult(
                    ActionState.EXPIRED,
                    "RESERVATION_WATCH_ONLY_SKIPPED",
                    "预约卡片显示“去观看”，当前不可预约，跳过本条。",
                )
            if snapshot.expired_text:
                return ActionResult(
                    ActionState.EXPIRED,
                    "RESERVATION_EXPIRED",
                    "预约抽奖页面已明确显示活动结束。",
                )
            return self.gate.waiting(
                "预约抽奖已识别且动态未点赞，等待执行预约、点赞并确认作者关注终态。"
            )
        if snapshot.activity_like_active:
            return ActionResult(
                ActionState.ALREADY_LIKED_SKIPPED,
                "ALREADY_PARTICIPATED_LIKED",
                "官方动态已经点赞，按参与标记规则跳过。",
            )
        if snapshot.expired_text:
            return ActionResult(
                ActionState.EXPIRED,
                "LOTTERY_EXPIRED",
                "互动抽奖面板不存在“开奖时间”字段，按规则视为已结束。",
            )
        if snapshot.official_lottery_panel_error:
            return ActionResult(
                state=ActionState.WAITING_USER,
                code=snapshot.official_lottery_panel_error,
                message="已识别官方抽奖入口，但互动抽奖面板未能打开，需要人工复核。",
                requires_user=True,
            )
        return self.gate.waiting("官方抽奖已识别，等待用户在页面确认参与条件。")
