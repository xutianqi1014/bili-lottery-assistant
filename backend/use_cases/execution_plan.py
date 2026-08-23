"""Build and confirm an immutable, non-writing activity execution plan."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.activity import Activity, ActivityOrigin
from backend.db.models.discovery import DiscoverySelection
from backend.db.models.run import Run
from backend.db.models.source import SourceArticle
from backend.db.repositories import activities, discoveries, problems, runs
from backend.jobs.events import EventHub
from backend.use_cases.source_closure import calculate_source_closure


@dataclass(frozen=True)
class PlanRequest:
    discovery_id: int
    activity_ids: tuple[int, ...] = ()
    source_article_ids: tuple[int, ...] = ()
    family_order: tuple[str, ...] = ("normal", "official")
    execution_policy: str = "confirm_each"


@dataclass(frozen=True)
class PlannedItem:
    activity: Activity
    contexts: list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]]
    sequence: int
    source_article_ids: list[int]
    state: str
    block_reason: str | None
    action_plan: list[str]


class ExecutionPlanService:
    def __init__(self, settings: Settings, engine: Engine, events: EventHub) -> None:
        self.settings = settings
        self.engine = engine
        self.events = events

    def create(self, request: PlanRequest) -> Run:
        _validate_request(request)
        with open_session(self.engine) as session:
            discovery = discoveries.get_discovery(session, request.discovery_id)
            if discovery is None:
                raise ValueError("DISCOVERY_NOT_FOUND")
            if discovery.state != "preview_ready":
                raise ValueError("DISCOVERY_NOT_READY")

            all_activities = activities.list_for_discovery(session, request.discovery_id)
            if not all_activities:
                raise ValueError("NO_DISCOVERED_ACTIVITIES")
            selected = _select_activities(session, request, all_activities)
            if not selected:
                raise ValueError("NO_SELECTED_ACTIVITIES")
            problem_rows = problems.list_for_discovery(session, request.discovery_id)
            open_problem_articles = {
                row.source_article_id
                for row in problem_rows
                if row.status == "open" and row.source_article_id is not None
            }
            ordered = _order_activities(session, request, selected)
            item_rows: list[PlannedItem] = []
            source_ids: set[int] = set()
            planned_count = 0
            blocked_count = 0
            skipped_count = 0
            for sequence, (activity, contexts) in enumerate(ordered, start=1):
                context_source_ids = sorted(
                    {
                        article.id
                        for _origin, _selection, article in contexts
                        if article.id
                    }
                )
                source_ids.update(context_source_ids)
                blocked_sources = sorted(set(context_source_ids) & open_problem_articles)
                family = _primary_family(contexts, request.family_order)
                source_section = _primary_source_section(contexts, request.family_order)
                item_state, block_reason, action_plan = _item_state(
                    family,
                    blocked_sources,
                    source_section,
                )
                if item_state == "planned":
                    planned_count += 1
                elif item_state == "blocked":
                    blocked_count += 1
                else:
                    skipped_count += 1
                item_rows.append(
                    PlannedItem(
                        activity=activity,
                        contexts=contexts,
                        sequence=sequence,
                        source_article_ids=context_source_ids,
                        state=item_state,
                        block_reason=block_reason,
                        action_plan=action_plan,
                    )
                )

            run = runs.create_run(
                session,
                discovery_run_id=request.discovery_id,
                execution_policy=request.execution_policy,
                family_order=list(request.family_order),
                source_article_ids=sorted(source_ids),
                activity_ids=[
                    activity.id
                    for activity, _contexts in ordered
                    if activity.id is not None
                ],
                stats={
                    "totalActivities": len(item_rows),
                    "plannedActivities": planned_count,
                    "blockedActivities": blocked_count,
                    "skippedActivities": skipped_count,
                    "runtimeUncheckedActivities": planned_count,
                    "activityPreflightUsed": False,
                    "requiresManualReview": blocked_count > 0,
                },
                direct_write_enabled=False,
            )
            assert run.id is not None
            for item in item_rows:
                activity = item.activity
                contexts = item.contexts
                assert activity.id is not None
                runs.add_item(
                    session,
                    run_id=run.id,
                    activity_id=activity.id,
                    sequence=item.sequence,
                    dynamic_id=activity.dynamic_id,
                    canonical_url=activity.canonical_url,
                    title=activity.title,
                    family=_primary_family(contexts, request.family_order),
                    source_section=source_section,
                    mode=source_section or "unknown",
                    unofficial_type="unknown",
                    platform_status="unchecked",
                    source_article_ids=item.source_article_ids,
                    action_plan=item.action_plan,
                    state=item.state,
                    block_reason=item.block_reason,
                )
            session.flush()
            initial_stats = _load_json_object(run.stats_json)
            initial_stats["sourceClosure"] = calculate_source_closure(
                session, run
            ).to_payload()
            run.stats_json = json.dumps(initial_stats, ensure_ascii=False)
            session.add(run)
            session.commit()
            session.refresh(run)
        return run

    def get(self, run_id: int) -> tuple[Run, list]:
        with open_session(self.engine) as session:
            run = runs.get_run(session, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            return run, runs.list_items(session, run_id)

    def confirm(self, run_id: int, note: str = "用户已确认计划") -> Run:
        with open_session(self.engine) as session:
            run = runs.get_run(session, run_id)
            if run is None:
                raise ValueError("RUN_NOT_FOUND")
            if run.state != "awaiting_confirmation":
                raise ValueError("RUN_NOT_CONFIRMABLE")
            stats = _load_json_object(run.stats_json)
            if bool(stats.get("requiresManualReview")):
                raise ValueError("RUN_HAS_BLOCKED_ITEMS")
            confirmed = runs.confirm_run(session, run, note)
        return confirmed

    async def publish_created(self, run: Run) -> None:
        await self.events.publish(
            "run.plan_created",
            {"runId": run.id, "state": run.state, "discoveryId": run.discovery_run_id},
        )

    async def publish_confirmed(self, run: Run) -> None:
        await self.events.publish(
            "run.confirmed",
            {"runId": run.id, "state": run.state, "discoveryId": run.discovery_run_id},
        )


def _validate_request(request: PlanRequest) -> None:
    if request.execution_policy != "confirm_each":
        raise ValueError("ONLY_CONFIRM_EACH_IS_AVAILABLE")
    if tuple(request.family_order) not in (("normal", "official"), ("official", "normal")):
        raise ValueError("INVALID_FAMILY_ORDER")


def _select_activities(
    session: Session,
    request: PlanRequest,
    rows: Sequence[Activity],
) -> list[Activity]:
    activity_ids = set(request.activity_ids)
    source_article_ids = set(request.source_article_ids)
    selected: list[Activity] = []
    for activity in rows:
        if activity.id is None:
            continue
        if activity_ids and activity.id not in activity_ids:
            continue
        contexts = activities.list_origin_contexts(session, request.discovery_id, activity.id)
        context_ids = {article.id for _origin, _selection, article in contexts if article.id}
        if source_article_ids and not context_ids.intersection(source_article_ids):
            continue
        selected.append(activity)
    return selected


def _order_activities(
    session: Session,
    request: PlanRequest,
    rows: Sequence[Activity],
) -> list[tuple[Activity, list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]]]]:
    family_rank = {family: index for index, family in enumerate(request.family_order)}
    ordered: list[
        tuple[
            tuple[object, ...],
            Activity,
            list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]],
        ]
    ] = []
    for activity in rows:
        if activity.id is None:
            continue
        contexts = activities.list_origin_contexts(session, request.discovery_id, activity.id)
        if not contexts:
            continue
        key = min(
            (
                family_rank.get(selection.family, len(family_rank)),
                selection.selected_rank,
                origin.source_position,
                activity.dynamic_id,
            )
            for origin, selection, _article in contexts
        )
        ordered.append((key, activity, contexts))
    ordered.sort(key=lambda item: item[0])
    return [(activity, contexts) for _key, activity, contexts in ordered]


def _item_state(
    family: str,
    blocked_sources: list[int],
    source_section: str | None = None,
) -> tuple[str, str | None, list[str]]:
    if blocked_sources:
        return (
            "blocked",
            "来源专栏存在问题网址，需要人工复核；本轮不收尾点赞。",
            ["manual_review", "recheck_source_problems"],
        )
    if source_section == "interactive":
        # The source article has already told us this is an interactive
        # section, but that section intentionally contains both official and
        # non-official dynamics.  The opened page must still be classified;
        # its like state is checked before that classification.
        return "planned", None, [
            "open_dynamic",
            "inspect_activity_like_first",
            "classify_official_or_unofficial",
            "execute_if_eligible",
        ]
    if family == "official" or source_section == "reservation":
        return "planned", None, [
            "open_dynamic",
            "inspect_runtime_state",
            "execute_official_if_eligible",
        ]
    return "planned", None, [
        "open_dynamic",
        "inspect_runtime_state",
        "build_unofficial_action_plan",
        "checkpoint_comment",
        "checkpoint_repost",
        "checkpoint_like",
        "checkpoint_follow",
        "verify_terminal_state",
    ]


def _primary_family(
    contexts: list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]],
    family_order: tuple[str, ...],
) -> str:
    rank = {family: index for index, family in enumerate(family_order)}
    family = min(
        (selection.family for _origin, selection, _article in contexts),
        key=lambda family: rank.get(family, len(rank)),
    )
    return str(family)


def _primary_source_section(
    contexts: list[tuple[ActivityOrigin, DiscoverySelection, SourceArticle]],
    family_order: tuple[str, ...],
) -> str | None:
    """Return the first explicit section hint in deterministic source order.

    A globally de-duplicated dynamic can occur in more than one source
    article.  Use the same family/rank/position precedence as the plan order,
    then retain only the section names understood by the runtime UI.  This is
    a provisional label; runtime inspection may replace ``RunItem.mode`` with
    official, reservation, or unofficial.
    """

    family_rank = {family: index for index, family in enumerate(family_order)}
    ordered = sorted(
        contexts,
        key=lambda row: (
            family_rank.get(row[1].family, len(family_rank)),
            row[1].selected_rank,
            row[0].source_position,
            row[2].id or 0,
        ),
    )
    for origin, _selection, _article in ordered:
        if origin.source_section in {"reservation", "interactive"}:
            return origin.source_section
    return None


def _load_json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
