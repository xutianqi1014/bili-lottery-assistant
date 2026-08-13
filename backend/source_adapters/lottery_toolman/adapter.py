from backend.config import Settings
from backend.db.models.source import SourceProfile
from backend.domain.entities import (
    ActivityExtractionResult,
    ActivityRef,
    MarkerInspection,
    ReadlistCandidate,
    SourceArticleCandidate,
)
from backend.domain.ports import BrowserGateway

from .discover_entries import discover_entries_api
from .discover_readlists import discover_readlists_api
from .extract_activities import extract_activities, extract_activity_refs
from .inspect_marker import inspect_like_state
from .source_like_dom import DomSourceLikeTransport
from .title_rules import select_latest_entries


class LotteryToolmanSourceAdapter:
    key = "lottery_toolman_v1"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def discover_readlists(
        self, profile: SourceProfile, browser: BrowserGateway | None
    ) -> list[ReadlistCandidate]:
        return await discover_readlists_api(profile.mid, self.settings.request_timeout_sec)

    async def discover_entries(
        self,
        readlist: ReadlistCandidate,
        limit: int,
        browser: BrowserGateway | None,
    ) -> list[SourceArticleCandidate]:
        entries = await discover_entries_api(readlist, self.settings.request_timeout_sec)
        return select_latest_entries(entries, limit)

    async def inspect_processed_marker(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> MarkerInspection:
        return await inspect_like_state(article, browser)

    async def extract_activity_refs(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> list[ActivityRef]:
        return await extract_activity_refs(article, browser)

    async def extract_activities(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> ActivityExtractionResult:
        return await extract_activities(article, browser)

    def build_source_like_transport(self, browser: BrowserGateway) -> DomSourceLikeTransport:
        """Build the DOM writer for a future explicitly enabled write run.

        The application does not call this method while ``enable_direct_write_api``
        is false. Keeping construction here lets a later, separately reviewed
        write workflow reuse the adapter's selectors without mixing it into
        source discovery or activity execution.
        """

        return DomSourceLikeTransport(browser)
