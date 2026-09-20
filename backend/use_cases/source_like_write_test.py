"""Compatibility imports for the isolated legacy source-like workflow.

The application uses source_like_automation; these names remain importable for
older controlled tools and their persisted plan/checkpoint formats.
"""

from backend.legacy.source_like_write_test import (
    LIVE_WRITE_CONFIRMATION as LIVE_WRITE_CONFIRMATION,
)
from backend.legacy.source_like_write_test import (
    LIVE_WRITE_ENV as LIVE_WRITE_ENV,
)
from backend.legacy.source_like_write_test import (
    LIVE_WRITE_ENV_ACK as LIVE_WRITE_ENV_ACK,
)
from backend.legacy.source_like_write_test import (
    ControlledSourceLikeWriteTest as ControlledSourceLikeWriteTest,
)
from backend.legacy.source_like_write_test import (
    SourceLikeWriteAllowlist as SourceLikeWriteAllowlist,
)
from backend.legacy.source_like_write_test import (
    SourceLikeWriteAuthorization as SourceLikeWriteAuthorization,
)
from backend.legacy.source_like_write_test import (
    SourceLikeWriteTestAllowlistError as SourceLikeWriteTestAllowlistError,
)
from backend.legacy.source_like_write_test import (
    SourceLikeWriteTestAuthorizationError as SourceLikeWriteTestAuthorizationError,
)
from backend.legacy.source_like_write_test import (
    SourceLikeWriteTestError as SourceLikeWriteTestError,
)

__all__ = [
    "LIVE_WRITE_ENV",
    "LIVE_WRITE_ENV_ACK",
    "LIVE_WRITE_CONFIRMATION",
    "SourceLikeWriteTestError",
    "SourceLikeWriteTestAllowlistError",
    "SourceLikeWriteTestAuthorizationError",
    "SourceLikeWriteAllowlist",
    "SourceLikeWriteAuthorization",
    "ControlledSourceLikeWriteTest",
]
