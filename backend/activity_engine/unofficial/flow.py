from backend.activity_engine.models import (
    ActionResult,
    ActionState,
    ActivityClassification,
    ActivityMode,
    ActivitySnapshot,
    ParticipationRequirements,
    UnofficialType,
)
from backend.activity_engine.shared.manual_gate import ManualGate

from .actions import UnofficialActionPlan, UnofficialActionPlanner


class UnofficialFlow:
    """Read/prepare comment-repost-like-follow action plans."""

    def __init__(
        self,
        gate: ManualGate,
        planner: UnofficialActionPlanner | None = None,
    ):
        self.gate = gate
        self.planner = planner or UnofficialActionPlanner()

    def action_plan(
        self,
        classification: ActivityClassification | None = None,
        requirements: ParticipationRequirements | None = None,
    ) -> UnofficialActionPlan:
        """Return the non-writing action sequence for the current run."""

        return self.planner.build(
            unofficial_type=(
                classification.unofficial_type
                if classification is not None
                else UnofficialType.UNKNOWN
            ),
            requirements=requirements,
            direct_write_enabled=self.gate.direct_write_enabled,
        )

    async def prepare(
        self,
        snapshot: ActivitySnapshot,
        classification: ActivityClassification,
    ) -> ActionResult:
        if classification.mode is not ActivityMode.UNOFFICIAL:
            return ActionResult(
                ActionState.MODE_MISMATCH,
                "MODE_MISMATCH",
                "来源预期非官方流程，但目标动态未被稳定识别为非官方抽奖。",
                True,
            )
        if snapshot.expired_text:
            return ActionResult(ActionState.EXPIRED, "ACTIVITY_EXPIRED", "页面明确显示动态已结束。")
        if snapshot.activity_like_active:
            return ActionResult(
                ActionState.ALREADY_LIKED_SKIPPED,
                "ALREADY_LIKED_SKIPPED",
                "动态已经点赞，按当前流程跳过重复操作。",
            )
        return self.gate.waiting(
            "非官方抽奖已识别，等待用户确认评论、转发、点赞和关注步骤；"
            "每一步必须记录确定结果，未知结果不得自动重试。"
        )
