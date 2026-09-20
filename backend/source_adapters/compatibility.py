"""Explicit bridges for older discovery adapters and family-keyed callers."""

from collections.abc import Sequence
from typing import Any, cast, overload

from backend.domain.entities import ReadlistCandidate, SourceArticleCandidate
from backend.domain.enums import LikeState, SourceFamily
from backend.domain.ports import BrowserGateway, SourceArticleObservation

from .lottery_toolman.title_rules import select_latest_readlist_per_family


class ReadlistSelection(Sequence[ReadlistCandidate]):
    """A sequence that also accepts the legacy family lookup."""

    def __init__(self, candidates: Sequence[ReadlistCandidate]) -> None:
        self._candidates = tuple(candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    @overload
    def __getitem__(self, key: int) -> ReadlistCandidate: ...

    @overload
    def __getitem__(self, key: slice) -> Sequence[ReadlistCandidate]: ...

    @overload
    def __getitem__(self, key: SourceFamily) -> ReadlistCandidate: ...

    def __getitem__(
        self, key: int | slice | SourceFamily
    ) -> ReadlistCandidate | Sequence[ReadlistCandidate]:
        if isinstance(key, SourceFamily):
            for candidate in self._candidates:
                if candidate.family == key:
                    return candidate
            raise KeyError(key)
        return self._candidates[key]


class SourceAdapterCompatibility:
    """Normalize legacy selectors and observation methods at one boundary."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def select_readlists(
        self, candidates: Sequence[ReadlistCandidate]
    ) -> Sequence[ReadlistCandidate]:
        selector = getattr(self._adapter, "select_readlists", None)
        selected = (
            selector(list(candidates))
            if callable(selector)
            else select_latest_readlist_per_family(candidates)
        )
        return list(selected.values()) if isinstance(selected, dict) else list(selected)

    async def observe_article(
        self, article: SourceArticleCandidate, browser: BrowserGateway | None
    ) -> SourceArticleObservation:
        observer = getattr(self._adapter, "observe_article", None)
        if callable(observer):
            return cast(SourceArticleObservation, await observer(article, browser))
        marker = await self._adapter.inspect_processed_marker(article, browser)
        extraction = None
        if marker.state == LikeState.UNLIKED:
            extraction = await self._adapter.extract_activities(article, browser)
        return SourceArticleObservation(marker, extraction)
