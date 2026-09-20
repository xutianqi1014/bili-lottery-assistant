"""Read-only runtime inspection and discovery-source policy resolution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.engine import Engine

from backend.activity_engine.classifier import ActivityClassifier
from backend.activity_engine.models import (
    ActionResult,
    ActionState,
    ActivityClassification,
    ActivityMode,
    UnofficialType,
)
from backend.activity_engine.official import OfficialFlow
from backend.activity_engine.requirements import RequirementParser
from backend.activity_engine.runtime_inspection import RuntimeActivityReader
from backend.activity_engine.shared import ManualGate
from backend.activity_engine.source_policy import (
    SourceActivityPolicy,
    fallback_policy_for_family,
    policy_from_profile,
)
from backend.activity_engine.unofficial import (
    ActionCheckpointLedger,
    UnofficialActionPlan,
    UnofficialFlow,
)
from backend.browser.manager import BrowserManager
from backend.db.engine import open_session
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceProfile
from backend.use_cases.run_execution_outcomes import (
    DYNAMIC_UNAVAILABLE_SKIP_CODE,
    RuntimeOutcome,
    _activity_like_state_unknown_runtime_outcome,
    _already_liked_runtime_outcome,
    _inspection_payload,
    _item_state_for,
    _platform_status,
)


class RunRuntimeInspector:
    """Inspect evidence without owning execution state or any write service."""

    def __init__(
        self,
        browser: BrowserManager,
        reader: RuntimeActivityReader,
        classifier: ActivityClassifier,
        requirements: RequirementParser,
        gate: ManualGate,
    ) -> None:
        self.browser = browser
        self.reader = reader
        self.classifier = classifier
        self.requirements = requirements
        self.gate = gate

    async def inspect(
        self,
        run: Run,
        item: RunItem,
        *,
        next_unofficial_delay: Callable[[], float],
        policy_for: Callable[[Run, RunItem], SourceActivityPolicy],
    ) -> RuntimeOutcome:
        # Non-official dynamics receive a short visible-page settling window
        # immediately after navigation and before the first scoped read.  The
        # same configured 1–2 second range is used for both automated and
        # read-only execution; official dynamics keep their existing timing.
        post_open_delay = (
            next_unofficial_delay()
            if (
                item.family != "official"
                or item.mode in {ActivityMode.UNOFFICIAL.value, "interactive"}
                or item.source_section == "interactive"
            )
            else 0.0
        )
        read = await self.reader.read(
            self.browser,
            item.dynamic_id,
            item.canonical_url,
            post_open_delay_sec=post_open_delay,
        )
        if not read.dynamic_unavailable and read.snapshot.activity_like_active:
            # A dynamic like is the participation marker shared by official,
            # reservation, and non-official activities. Short-circuit before
            # classification so a liked item is never blocked by a source
            # activity-type allow-list and no type-specific DOM is inspected.
            return _already_liked_runtime_outcome(read)
        if not read.dynamic_unavailable and read.activity_like_unknown:
            # The like state is the global participation marker.  If the
            # visible control is absent/ambiguous, never continue into type
            # classification or a comment/repost/official write: a later
            # writer could otherwise toggle an already-active like off.
            return _activity_like_state_unknown_runtime_outcome(read)

        source_policy = policy_for(run, item)
        classification = self.classifier.classify(
            read.snapshot,
            allowed_modes=source_policy.allowed_modes,
        )
        if read.dynamic_unavailable:
            # An error page is not a fourth activity type. Keep the runtime
            # type unknown for evidence, but bypass source allow-list checks
            # and turn it into a safe terminal skip below.
            classification = ActivityClassification(
                mode=ActivityMode.UNKNOWN,
                unofficial_type=UnofficialType.UNKNOWN,
                is_expired=True,
                is_participated=None,
                confidence="high",
                evidence_codes=("DYNAMIC_UNAVAILABLE_PAGE",),
            )
        # Non-official pages expose a scoped outer body separately from the
        # full visible page.  The full body also contains the comment tab,
        # like/repost counts and other users' text; parsing it can fabricate a
        # comment instruction such as "评论 2276 ...".  Always parse the
        # reader's actionable text so only the current dynamic's own
        # participation requirements reach the write planner.
        requirements = self.requirements.parse(read.snapshot.actionable_text)
        inspection = _inspection_payload(read, classification, requirements)
        inspection["sourceKey"] = source_policy.source_key
        inspection["allowedActivityTypes"] = list(source_policy.allowed_type_names)
        action_plan: UnofficialActionPlan | None = None

        if read.dynamic_unavailable:
            result = ActionResult(
                ActionState.EXPIRED,
                DYNAMIC_UNAVAILABLE_SKIP_CODE,
                "动态页面已消失或显示 B 站错误页，跳过本条且不执行写操作。",
            )
        elif classification.mode is ActivityMode.UNKNOWN:
            result = ActionResult(
                ActionState.WAITING_USER,
                "CLASSIFICATION_UNKNOWN",
                "动态页面未能稳定识别为官方或非官方抽奖，需要人工复核。",
                True,
            )
        elif not source_policy.allows(classification.mode):
            result = ActionResult(
                ActionState.WAITING_USER,
                "SOURCE_ACTIVITY_TYPE_NOT_ALLOWED",
                (
                    f"当前来源仅允许 {', '.join(source_policy.allowed_type_names)} 动态；"
                    f"页面被识别为 {classification.mode.value}，已停止本条且不执行写操作。"
                ),
                True,
            )
        else:
            if classification.mode in {
                ActivityMode.OFFICIAL,
                ActivityMode.RESERVATION,
            }:
                result = await OfficialFlow(self.gate).prepare(read.snapshot, classification)
            else:
                unofficial_flow = UnofficialFlow(self.gate)
                action_plan = unofficial_flow.action_plan(classification, requirements)
                inspection["unofficialActionPlan"] = action_plan.to_payload()
                inspection["unofficialCheckpoints"] = ActionCheckpointLedger(
                    action_plan.actions
                ).to_payload()
                result = await unofficial_flow.prepare(read.snapshot, classification)

        inspection["resultCode"] = result.code
        inspection["resultMessage"] = result.message
        item_state = _item_state_for(result.state)
        return RuntimeOutcome(
            item_state=item_state,
            mode=classification.mode.value,
            unofficial_type=classification.unofficial_type.value,
            platform_status=_platform_status(classification.mode, result.state, result.code),
            result_code=result.code,
            result_message=result.message,
            block_reason=result.message if item_state == "waiting_user" else None,
            inspection=inspection,
            selector_version=(
                read.nonofficial_selector_version
                if classification.mode is ActivityMode.UNOFFICIAL
                else read.selector_version
            ),
            inspected_at=datetime.now(UTC),
            requirements=requirements,
            unofficial_action_plan=action_plan,
            comment_context=read.snapshot.actionable_text,
        )


def source_activity_policy(engine: Engine, run: Run, item: RunItem) -> SourceActivityPolicy:
    """Load the allow-list for the discovery source behind this run."""

    with open_session(engine) as session:
        discovery = session.get(DiscoveryRun, run.discovery_run_id)
        if discovery is None:
            return fallback_policy_for_family(item.family)
        profile = session.get(SourceProfile, discovery.source_profile_id)
        if profile is None:
            return fallback_policy_for_family(item.family)
        return policy_from_profile(
            source_key=profile.source_key,
            adapter_key=profile.adapter_key,
            config_json=profile.config_json,
        )
