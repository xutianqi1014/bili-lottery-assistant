"""Adapter for MID 3546836235193146 (番茄薯条喵).

This UP keeps a mixed collection named ``互动抽奖``.  The collection can
contain a previous-collection portal, charge lotteries, reservation lotteries
and interactive lotteries.  Only reservation and interactive rows are useful
to this application; charge rows are excluded during source-article parsing.
"""

from collections.abc import Sequence

from backend.db.models.source import SourceProfile
from backend.domain.entities import (
    ActivityExtractionResult,
    ActivityRef,
    ReadlistCandidate,
    SourceArticleCandidate,
)
from backend.domain.ports import BrowserGateway
from backend.source_adapters.compatibility import ReadlistSelection
from backend.source_adapters.lottery_toolman.adapter import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman.discover_entries import discover_entries_api
from backend.source_adapters.lottery_toolman.discover_readlists import (
    discover_named_readlists_api,
)
from backend.source_adapters.lottery_toolman.extract_activities import (
    extract_activities,
)
from backend.source_adapters.lottery_toolman.title_rules import normalize_text


class TomatoFriesSourceAdapter(LotteryToolmanSourceAdapter):
    """Discover the newest three articles from the ``互动抽奖`` collection."""

    key = "tomato_fries_v1"
    READLIST_NAME = "互动抽奖"
    INCLUDED_SECTIONS = frozenset({"reservation", "interactive"})

    async def discover_readlists(
        self, profile: SourceProfile, browser: BrowserGateway | None
    ) -> list[ReadlistCandidate]:
        del browser
        return await discover_named_readlists_api(
            profile.mid,
            self.settings.request_timeout_sec,
            {self.READLIST_NAME},
        )

    async def discover_entries(
        self,
        readlist: ReadlistCandidate,
        limit: int,
        browser: BrowserGateway | None,
    ) -> list[SourceArticleCandidate]:
        del browser
        entries = await discover_entries_api(readlist, self.settings.request_timeout_sec)
        return self.select_latest_entries_by_published_at(entries, limit)

    @classmethod
    def select_readlists(
        cls,
        candidates: Sequence[ReadlistCandidate],
    ) -> Sequence[ReadlistCandidate]:
        """Select only the named mixed collection, never ``转盘合集``."""

        matching = [
            candidate
            for candidate in candidates
            if normalize_text(candidate.title) == normalize_text(cls.READLIST_NAME)
        ]
        if not matching:
            raise ValueError("READLIST_INTERACTIVE_NOT_FOUND")
        selected = max(
            matching,
            key=lambda candidate: (
                candidate.observed_updated_at or -1,
                candidate.rl_id,
            ),
        )
        return ReadlistSelection([selected])

    @staticmethod
    def select_latest_entries_by_published_at(
        entries: list[SourceArticleCandidate], limit: int
    ) -> list[SourceArticleCandidate]:
        """Return the newest entries by publication timestamp.

        Bilibili's article-list endpoint is usually newest-last, but older
        rows can be inserted or reordered.  Timestamp-first ordering keeps
        “最新三个” deterministic even when that endpoint order changes.
        """

        if limit < 1:
            return []
        ordered = sorted(
            entries,
            key=lambda item: (
                item.published_at if item.published_at is not None else -1,
                _numeric_id(item.article_id),
                item.position,
            ),
            reverse=True,
        )
        return ordered[:limit]

    async def extract_activity_refs(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> list[ActivityRef]:
        result = await self.extract_activities(article, browser)
        return list(result.refs)

    async def extract_activities(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> ActivityExtractionResult:
        return await extract_activities(
            article,
            browser,
            include_sections=self.INCLUDED_SECTIONS,
        )


def _numeric_id(value: str) -> int:
    return int(value) if value.isdecimal() else -1
