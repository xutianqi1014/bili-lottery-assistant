import json
from dataclasses import replace

from backend.config import Settings
from backend.db.models.source import SourceProfile
from backend.domain.entities import (
    ActivityExtractionResult,
    ActivityRef,
    MarkerInspection,
    ReadlistCandidate,
    SourceArticleCandidate,
)
from backend.domain.enums import SourceFamily
from backend.domain.ports import BrowserGateway

from .discover_entries import discover_entries_api
from .discover_readlists import discover_named_readlists_api, discover_readlists_api
from .extract_activities import extract_activities, extract_activity_refs
from .inspect_marker import inspect_like_state
from .source_like_dom import DomSourceLikeTransport
from .title_rules import normalize_text, select_latest_entries


class LotteryToolmanSourceAdapter:
    key = "lottery_toolman_v1"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def discover_readlists(
        self, profile: SourceProfile, browser: BrowserGateway | None
    ) -> list[ReadlistCandidate]:
        del browser
        candidates: list[ReadlistCandidate] = []
        for page in self._source_pages(profile):
            strategy = page.get("readlistStrategy", "families")
            if strategy == "named_exact":
                names = {normalize_text(page.get("readlistName") or "抽奖合集")}
                discovered = await discover_named_readlists_api(
                    page["mid"],
                    self.settings.request_timeout_sec,
                    names,
                )
            else:
                discovered = await discover_readlists_api(
                    page["mid"],
                    self.settings.request_timeout_sec,
                )
            for candidate in discovered:
                family = candidate.family
                configured_family = page.get("family")
                if configured_family == SourceFamily.NORMAL.value:
                    family = SourceFamily.NORMAL
                elif configured_family == SourceFamily.OFFICIAL.value:
                    family = SourceFamily.OFFICIAL
                candidates.append(
                    replace(
                        candidate,
                        family=family,
                        source_mid=page["mid"],
                        source_upload_url=page["uploadUrl"],
                        readlist_strategy=strategy,
                    )
                )
        return candidates

    @staticmethod
    def _source_pages(profile: SourceProfile) -> list[dict[str, str]]:
        try:
            config = json.loads(profile.config_json)
        except json.JSONDecodeError:
            config = {}
        raw_pages = config.get("sourcePages") if isinstance(config, dict) else None
        pages: list[dict[str, str]] = []
        if isinstance(raw_pages, list):
            for raw_page in raw_pages:
                if not isinstance(raw_page, dict):
                    continue
                mid = str(raw_page.get("mid") or "").strip()
                upload_url = str(raw_page.get("uploadUrl") or "").strip()
                if not mid or not upload_url:
                    continue
                page = {
                    "mid": mid,
                    "uploadUrl": upload_url,
                    "readlistStrategy": str(
                        raw_page.get("readlistStrategy") or "families"
                    ),
                }
                for key in ("readlistName", "family"):
                    value = str(raw_page.get(key) or "").strip()
                    if value:
                        page[key] = value
                pages.append(page)
        if pages:
            return pages
        return [
            {
                "mid": profile.mid,
                "uploadUrl": profile.upload_url,
                "readlistStrategy": "families",
            }
        ]

    @staticmethod
    def select_readlists(
        candidates: list[ReadlistCandidate],
    ) -> list[ReadlistCandidate] | dict[SourceFamily, ReadlistCandidate]:
        """Keep the newest collection for each family on every configured page."""

        selected: dict[tuple[str, SourceFamily], ReadlistCandidate] = {}
        for candidate in candidates:
            key = (candidate.source_mid or "", candidate.family)
            current = selected.get(key)
            if current is None or _readlist_key(candidate) > _readlist_key(current):
                selected[key] = candidate
        return sorted(
            selected.values(),
            key=lambda candidate: (
                candidate.source_mid or "",
                candidate.family.value,
                -candidate.suffix_value,
                candidate.rl_id,
            ),
        )

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

        The application does not call this method while "enable_direct_write_api"
        is false. Keeping construction here lets a later, separately reviewed
        write workflow reuse the adapter's selectors without mixing it into
        source discovery or activity execution.
        """

        return DomSourceLikeTransport(browser)


def _readlist_key(candidate: ReadlistCandidate) -> tuple[int, int, str]:
    return (
        candidate.suffix_value,
        candidate.observed_updated_at or -1,
        candidate.rl_id,
    )