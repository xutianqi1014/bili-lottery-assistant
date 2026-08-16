from dataclasses import dataclass
from enum import StrEnum


class ActivityMode(StrEnum):
    OFFICIAL = "official"
    RESERVATION = "reservation"
    UNOFFICIAL = "unofficial"
    UNKNOWN = "unknown"


class UnofficialType(StrEnum):
    NORMAL = "normal"
    BOOSTED = "boosted"
    UNKNOWN = "unknown"


class ActionState(StrEnum):
    SUCCESS = "success"
    ALREADY_PARTICIPATED = "already_participated"
    ALREADY_LIKED_SKIPPED = "already_liked_skipped"
    WAITING_USER = "waiting_user"
    MODE_MISMATCH = "mode_mismatch"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ActivitySnapshot:
    dynamic_id: str
    canonical_url: str
    body_text: str
    has_official_lottery_entry: bool = False
    has_reservation_entry: bool = False
    reservation_active: bool = False
    reservation_control_text: str = ""
    activity_like_active: bool = False
    already_participated_text: bool = False
    expired_text: bool = False
    official_lottery_panel_opened: bool = False
    official_lottery_panel_error: str | None = None
    actionable_text: str = ""
    forwarded_original_text: str = ""
    has_forwarded_original: bool = False
    nonofficial_dom_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActivityClassification:
    mode: ActivityMode
    unofficial_type: UnofficialType
    is_expired: bool | None
    is_participated: bool | None
    confidence: str
    evidence_codes: tuple[str, ...]


@dataclass(frozen=True)
class ParticipationRequirements:
    required_topics: tuple[str, ...] = ()
    required_mention_count: int = 0
    comment_instruction: str = ""
    required_actions: tuple[str, ...] = ()
    mention_limit_exceeded: bool = False
    evidence_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    state: ActionState
    code: str
    message: str
    requires_user: bool = False
