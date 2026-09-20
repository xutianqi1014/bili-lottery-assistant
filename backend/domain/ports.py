from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .entities import (
    ActivityExtractionResult,
    ActivityRef,
    MarkerInspection,
    ReadlistCandidate,
    SourceArticleCandidate,
)


class BrowserGateway(Protocol):
    async def open(self, url: str) -> Any: ...


@dataclass(frozen=True)
class SourceArticleObservation:
    """Read-only evidence; extraction is absent unless the marker is unliked."""

    marker: MarkerInspection
    extraction: ActivityExtractionResult | None = None


class SourceDiscoveryAdapter(Protocol):
    key: str

    def select_readlists(
        self, candidates: Sequence[ReadlistCandidate]
    ) -> Sequence[ReadlistCandidate]: ...

    async def observe_article(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> SourceArticleObservation: ...

    async def discover_readlists(
        self, profile: Any, browser: BrowserGateway | None
    ) -> Sequence[ReadlistCandidate]: ...

    async def discover_entries(
        self, readlist: ReadlistCandidate, limit: int, browser: BrowserGateway | None
    ) -> Sequence[SourceArticleCandidate]: ...

    async def inspect_processed_marker(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> MarkerInspection: ...

    async def extract_activity_refs(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> Sequence[ActivityRef]: ...

    async def extract_activities(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> ActivityExtractionResult: ...
