from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.engine import Engine

from backend.browser.manager import BrowserManager
from backend.config import Settings
from backend.db.engine import open_session
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.source import Readlist
from backend.db.repositories import activities, discoveries, profiles, readlists
from backend.domain.entities import ActivityExtractionResult, SourceArticleCandidate
from backend.domain.enums import DiscoveryDecision, LikeState
from backend.domain.ports import SourceDiscoveryAdapter
from backend.jobs.events import EventHub
from backend.problems.registry import ProblemRegistry
from backend.source_adapters.lottery_toolman.title_rules import (
    select_latest_readlist_per_family,
)
from backend.source_adapters.registry import build_adapter_registry


@dataclass(frozen=True)
class DiscoverySummary:
    id: int
    state: str


class DiscoveryService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        browser: BrowserManager,
        events: EventHub,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.browser = browser
        self.events = events
        self.adapters = build_adapter_registry(settings)
        self.problems = ProblemRegistry(engine)

    def create(self, profile_id: int) -> DiscoveryRun:
        with open_session(self.engine) as session:
            profile = profiles.get_enabled_profile(session, profile_id)
            if profile.id is None:
                raise ValueError("SOURCE_PROFILE_ID_MISSING")
            return discoveries.create_discovery(session, profile.id, profile.latest_per_family)

    async def execute(self, discovery_id: int) -> None:
        with open_session(self.engine) as session:
            discovery = discoveries.get_discovery(session, discovery_id)
            if discovery is None:
                raise ValueError("DISCOVERY_NOT_FOUND")
            profile = profiles.get_enabled_profile(session, discovery.source_profile_id)
            if profile.id is None:
                raise ValueError("SOURCE_PROFILE_ID_MISSING")
        adapter = self.adapters.get(profile.adapter_key)
        if adapter is None:
            await self._fail(discovery_id, "ADAPTER_NOT_FOUND", profile.adapter_key)
            return
        await self.events.publish(
            "discovery.progress",
            {"discoveryId": discovery_id, "stage": "readlists"},
        )
        try:
            candidates = list(await adapter.discover_readlists(profile, self.browser))
            custom_selector = getattr(adapter, "select_readlists", None)
            if callable(custom_selector):
                selected = custom_selector(list(candidates))
            else:
                selected = select_latest_readlist_per_family(candidates)
            selected_rows = []
            stats = {
                "candidateReadlists": len(candidates),
                "selectedArticles": 0,
                "unknownMarkers": 0,
                "sourceArticlesParsed": 0,
                "activityRefsBeforeDedup": 0,
                "activityRefsUnique": 0,
                "activityDuplicateRefs": 0,
                "activityLinksExcluded": 0,
                "activityParseProblems": 0,
            }
            seen_activity_ids: set[str] = set()
            for family, candidate in selected.items():
                with open_session(self.engine) as session:
                    readlist = readlists.upsert_readlist(session, profile.id, candidate)
                    session.commit()
                    session.refresh(readlist)
                selected_rows.append(readlist)
                entries = list(
                    await adapter.discover_entries(
                        candidate,
                        profile.latest_per_family,
                        self.browser,
                    )
                )
                await self._save_family(
                    discovery_id,
                    readlist,
                    entries,
                    adapter,
                    stats,
                    seen_activity_ids,
                )
            with open_session(self.engine) as session:
                discovery_row = discoveries.get_discovery(session, discovery_id)
                if discovery_row is None:
                    raise ValueError("DISCOVERY_NOT_FOUND")
                discoveries.save_preview(session, discovery_row, selected_rows, stats)
                profile_row = profiles.get_profile(session, profile.id)
                if profile_row is not None:
                    from datetime import datetime

                    profile_row.last_discovery_at = datetime.now(UTC)
                    session.add(profile_row)
                    session.commit()
            await self.events.publish(
                "discovery.ready",
                {"discoveryId": discovery_id, "state": "preview_ready", "stats": stats},
            )
        except Exception as exc:
            await self._fail(discovery_id, type(exc).__name__, str(exc))

    async def _save_family(
        self,
        discovery_id: int,
        readlist: Readlist,
        entries: Sequence[SourceArticleCandidate],
        adapter: SourceDiscoveryAdapter,
        stats: dict[str, int],
        seen_activity_ids: set[str],
    ) -> None:
        if readlist.id is None:
            raise ValueError("READLIST_ID_MISSING")
        for rank, candidate in enumerate(entries, start=1):
            marker = await adapter.inspect_processed_marker(candidate, self.browser)
            decision, reason = decide_marker(marker.state)
            article_db_id: int | None = None
            with open_session(self.engine) as session:
                article = readlists.upsert_article(session, candidate)
                article.like_state = marker.state.value
                article.like_checked_at = datetime.now(UTC)
                readlists.upsert_entry(session, readlist, article, candidate)
                article_db_id = article.id
                discoveries.add_selection(
                    session,
                    discovery_id,
                    article,
                    readlist,
                    rank,
                    candidate.position,
                    marker.state.value,
                    decision.value,
                    reason,
                )
                extraction: ActivityExtractionResult | None = None
                if decision == DiscoveryDecision.PROCESS:
                    extraction = await adapter.extract_activities(candidate, self.browser)
                    readlists.save_activity_extraction(session, article, extraction)
                    if article.id is None:
                        raise ValueError("SOURCE_ARTICLE_ID_MISSING")
                    for ref in extraction.refs:
                        activity = activities.upsert_activity(session, ref)
                        activities.add_origin(
                            session,
                            article.id,
                            activity,
                            ref.source_position,
                            discovery_id,
                            ref.source_section,
                        )
                session.commit()
            stats["selectedArticles"] += 1
            if extraction is not None:
                stats["sourceArticlesParsed"] += 1
                stats["activityRefsBeforeDedup"] += len(extraction.refs)
                stats["activityLinksExcluded"] += extraction.stats.aggregate_excluded
                for ref in extraction.refs:
                    if ref.dynamic_id in seen_activity_ids:
                        stats["activityDuplicateRefs"] += 1
                    else:
                        seen_activity_ids.add(ref.dynamic_id)
                        stats["activityRefsUnique"] += 1
                if extraction.status != "ok":
                    stats["activityParseProblems"] += 1
                    self.problems.record(
                        discovery_run_id=discovery_id,
                        source_article_id=article_db_id,
                        problem_url=candidate.canonical_url,
                        page_type="source_article",
                        stage="extract_activities",
                        problem_code=extraction.reason_code or "SOURCE_PARSE_FAILED",
                        safe_detail=(
                            extraction.safe_detail
                            or "来源专栏动态解析未完成，本轮不标记来源专栏。"
                        ),
                    )
            if marker.state == LikeState.UNKNOWN:
                stats["unknownMarkers"] += 1
                self.problems.record(
                    discovery_run_id=discovery_id,
                    source_article_id=article_db_id,
                    problem_url=candidate.canonical_url,
                    page_type="source_article",
                    stage="inspect_marker",
                    problem_code=marker.reason_code,
                    safe_detail="无法可靠确认当前账号点赞状态，已进入人工复核。",
                )
            await self.events.publish(
                "discovery.article_checked",
                {
                    "discoveryId": discovery_id,
                    "articleId": candidate.article_id,
                    "likeState": marker.state.value,
                    "decision": decision.value,
                },
            )

    async def _fail(self, discovery_id: int, code: str, detail: str) -> None:
        with open_session(self.engine) as session:
            discovery = discoveries.get_discovery(session, discovery_id)
            if discovery is not None:
                discoveries.mark_failed(session, discovery, code, detail)
        await self.events.publish(
            "discovery.failed",
            {"discoveryId": discovery_id, "state": "failed", "errorCode": code},
        )


def decide_marker(state: LikeState) -> tuple[DiscoveryDecision, str]:
    if state == LikeState.LIKED:
        return DiscoveryDecision.SKIP_PROCESSED, "来源专栏已点赞，视为已处理。"
    if state == LikeState.UNLIKED:
        return DiscoveryDecision.PROCESS, "来源专栏未点赞，进入本轮处理候选。"
    return DiscoveryDecision.MANUAL_REVIEW, "点赞状态未知，不自动处理。"
