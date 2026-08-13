from enum import StrEnum


class SourceFamily(StrEnum):
    NORMAL = "normal"
    OFFICIAL = "official"


class LikeState(StrEnum):
    LIKED = "liked"
    UNLIKED = "unliked"
    UNKNOWN = "unknown"


class DiscoveryDecision(StrEnum):
    SKIP_PROCESSED = "skip_processed"
    PROCESS = "process"
    MANUAL_REVIEW = "manual_review"


class DiscoveryState(StrEnum):
    RUNNING = "running"
    PREVIEW_READY = "preview_ready"
    FAILED = "failed"

