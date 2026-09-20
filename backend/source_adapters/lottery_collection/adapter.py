"""Adapter for MID 280604312's exact 抽奖合集 collection."""

from collections.abc import Sequence

from backend.db.models.source import SourceProfile
from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate
from backend.domain.ports import BrowserGateway
from backend.source_adapters.compatibility import ReadlistSelection
from backend.source_adapters.lottery_toolman.adapter import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman.discover_entries import discover_entries_api
from backend.source_adapters.lottery_toolman.discover_readlists import discover_readlists_api
from backend.source_adapters.lottery_toolman.title_rules import (
    normalize_text,
    select_latest_entries,
)


class LotteryCollectionSourceAdapter(LotteryToolmanSourceAdapter):
    """Read the ten newest numbered articles from the exact lottery collection.

    This UP uses the same article-body extraction and marker inspection flow as
    lottery_toolman_v1. Only collection selection and the per-run limit differ;
    activity type classification still happens when each dynamic is opened
    during execution.
    """

    key = "lottery_collection_v1"
    READLIST_NAME = "抽奖合集"

    async def discover_readlists(
        self, profile: SourceProfile, browser: BrowserGateway | None
    ) -> list[ReadlistCandidate]:
        del browser
        return await discover_readlists_api(profile.mid, self.settings.request_timeout_sec)

    async def discover_entries(
        self,
        readlist: ReadlistCandidate,
        limit: int,
        browser: BrowserGateway | None,
    ) -> list[SourceArticleCandidate]:
        del browser
        entries = await discover_entries_api(readlist, self.settings.request_timeout_sec)
        return select_latest_entries(entries, limit)

    @classmethod
    def select_readlists(
        cls,
        candidates: Sequence[ReadlistCandidate],
    ) -> Sequence[ReadlistCandidate]:
        """Select only the exact 抽奖合集 collection."""

        matching = [
            candidate
            for candidate in candidates
            if normalize_text(candidate.title) == normalize_text(cls.READLIST_NAME)
        ]
        if not matching:
            raise ValueError("READLIST_LOTTERY_COLLECTION_NOT_FOUND")
        selected = max(
            matching,
            key=lambda candidate: (
                candidate.observed_updated_at or -1,
                candidate.rl_id,
            ),
        )
        return ReadlistSelection([selected])
