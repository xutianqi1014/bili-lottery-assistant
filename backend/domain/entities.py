from dataclasses import dataclass

from .enums import DiscoveryDecision, LikeState, SourceFamily


@dataclass(frozen=True)
class ReadlistCandidate:
    rl_id: str
    canonical_url: str
    title: str
    normalized_title: str
    family: SourceFamily
    suffix_value: int
    item_count: int | None
    updated_text: str | None
    observed_updated_at: int | None
    source_mid: str | None = None
    source_upload_url: str | None = None
    readlist_strategy: str | None = None


@dataclass(frozen=True)
class SourceArticleCandidate:
    article_id: str
    canonical_url: str
    title: str
    position: int
    published_at: int | None = None


@dataclass(frozen=True)
class MarkerInspection:
    state: LikeState
    reason_code: str
    selector_version: str


@dataclass(frozen=True)
class ActivityRef:
    dynamic_id: str
    canonical_url: str
    source_position: int
    title: str = ""
    # A source article may explicitly group its links into charge,
    # reservation, or interactive sections.  This is a discovery-time hint;
    # the opened dynamic still gets a runtime classification before writes.
    source_section: str | None = None


@dataclass(frozen=True)
class ActivityExtractionStats:
    """Deterministic evidence collected while parsing one source article."""

    aggregate_excluded: int = 0
    started_after_pinned: bool = False
    start_mode: str = "not_checked"
    links_seen: int = 0
    unique_links: int = 0
    content_fingerprint: str = ""


@dataclass(frozen=True)
class ActivityExtractionResult:
    """Read-only extraction result; it never implies that a write is allowed."""

    refs: tuple[ActivityRef, ...] = ()
    stats: ActivityExtractionStats = ActivityExtractionStats()
    status: str = "ok"
    reason_code: str | None = None
    safe_detail: str = ""


@dataclass(frozen=True)
class SelectionDecision:
    like_state: LikeState
    decision: DiscoveryDecision
    reason: str
