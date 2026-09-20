"""Compatibility imports for the isolated legacy source-like workflow.

The application uses source_like_automation; these names remain importable for
older controlled tools and their persisted plan/checkpoint formats.
"""

from backend.legacy.source_like_execution import (
    SourceLikeExecutionService as SourceLikeExecutionService,
)

__all__ = ["SourceLikeExecutionService"]
