"""Compatibility imports for the isolated legacy source-like workflow.

The application uses source_like_automation; these names remain importable for
older controlled tools and their persisted plan/checkpoint formats.
"""

from backend.legacy.source_like_plan import (
    SourceLikePlan as SourceLikePlan,
)
from backend.legacy.source_like_plan import (
    SourceLikePlanService as SourceLikePlanService,
)
from backend.legacy.source_like_plan import (
    SourceLikeTarget as SourceLikeTarget,
)

__all__ = ["SourceLikeTarget","SourceLikePlan","SourceLikePlanService"]
