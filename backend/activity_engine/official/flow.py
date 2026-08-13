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
        if classification.mode is not ActivityMode.OFFICIAL:
            return ActionResult(
                ActionState.MODE_MISMATCH,
                "MODE_MISMATCH",
                "来源预期官方流程，但目标动态未被稳定识别为官方抽奖。",
                True,
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
