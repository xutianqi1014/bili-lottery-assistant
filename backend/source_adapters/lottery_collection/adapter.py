"""Adapter for MID 280604312's exact 抽奖合集 collection."""

from collections.abc import Sequence

from backend.db.models.source import SourceProfile
from backend.domain.entities import ReadlistCandidate
from backend.domain.ports import BrowserGateway
from backend.source_adapters.compatibility import ReadlistSelection
from backend.source_adapters.lottery_toolman.adapter import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman.discover_readlists import discover_readlists_api
from backend.source_adapters.lottery_toolman.title_rules import select_latest_named_readlist


class LotteryCollectionSourceAdapter(LotteryToolmanSourceAdapter):
    """Read the configured number of newest articles from the exact collection.

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


    @classmethod
    def select_readlists(
        cls,
        candidates: Sequence[ReadlistCandidate],
    ) -> Sequence[ReadlistCandidate]:
        """Select only the exact 抽奖合集 collection."""

        selected = select_latest_named_readlist(
            candidates, cls.READLIST_NAME, not_found_code="READLIST_LOTTERY_COLLECTION_NOT_FOUND",
        )
        return ReadlistSelection([selected])
