"""Single-target authorization harness for a future source-like write test.

This module only prepares and guards a deliberately narrow live-test session.
The normal application never constructs it, and the default configuration keeps
the live test disabled.  A caller must provide one enabled article allowlist,
the explicit environment acknowledgement, the exact target URL, and a second
human confirmation phrase before a guarded executor can be called.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]

from backend.source_adapters.lottery_toolman.source_like import (
    GuardedSourceLikeExecutor,
    InvalidSourceLikeTargetError,
    SourceLikeCheckpointLedger,
    SourceLikeWriteResult,
    validate_source_like_target,
)

LIVE_WRITE_ENV = "BILI_LIVE_WRITE_TEST"
LIVE_WRITE_ENV_ACK = "I_UNDERSTAND"
LIVE_WRITE_CONFIRMATION = "I_UNDERSTAND_SOURCE_LIKE_WRITE"


class SourceLikeWriteTestError(RuntimeError):
    """Base error for a rejected controlled-write-test request."""


class SourceLikeWriteTestAllowlistError(SourceLikeWriteTestError):
    """Raised when the allowlist file is missing or malformed."""


class SourceLikeWriteTestAuthorizationError(SourceLikeWriteTestError):
    """Raised when one of the explicit live-test gates is not satisfied."""


@dataclass(frozen=True, slots=True)
class SourceLikeWriteAllowlist:
    """Validated targets loaded from ``tests/live_contracts/write_allowlist.yaml``."""

    enabled: bool = False
    article_ids: tuple[str, ...] = ()
    dynamic_ids: tuple[str, ...] = ()
    author_ids: tuple[str, ...] = ()

    @classmethod
    def from_path(cls, path: Path) -> SourceLikeWriteAllowlist:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SourceLikeWriteTestAllowlistError(
                f"SOURCE_LIKE_WRITE_TEST_ALLOWLIST_READ_FAILED:{type(exc).__name__}"
            ) from exc
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise SourceLikeWriteTestAllowlistError(
                "SOURCE_LIKE_WRITE_TEST_ALLOWLIST_ROOT_INVALID"
            )
        enabled = payload.get("enabled", False)
        if not isinstance(enabled, bool):
            raise SourceLikeWriteTestAllowlistError(
                "SOURCE_LIKE_WRITE_TEST_ALLOWLIST_ENABLED_INVALID"
            )
        return cls(
            enabled=enabled,
            article_ids=_read_numeric_ids(payload, "article_ids"),
            dynamic_ids=_read_numeric_ids(payload, "dynamic_ids"),
            author_ids=_read_numeric_ids(payload, "author_ids"),
        )

    def require_single_article(self) -> str:
        if not self.enabled:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_ALLOWLIST_DISABLED"
            )
        if len(self.article_ids) != 1:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_MUST_HAVE_ONE_ARTICLE"
            )
        return self.article_ids[0]


@dataclass(frozen=True, slots=True)
class SourceLikeWriteAuthorization:
    target_url: str
    article_id: str
    environment_acknowledged: bool
    user_confirmed: bool
    confirmation_text: str


class ControlledSourceLikeWriteTest:
    """One-shot guard around :class:`GuardedSourceLikeExecutor`.

    This is intentionally not wired into FastAPI or the normal run executor.
    Once ``execute`` passes authorization, the session is consumed before the
    transport call; a timeout or unknown result therefore cannot be retried by
    this session.
    """

    def __init__(
        self,
        allowlist: SourceLikeWriteAllowlist,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.allowlist = allowlist
        env = environment if environment is not None else os.environ
        self._environment_ack = env.get(LIVE_WRITE_ENV, "")
        self._consumed = False
        self._ledger = SourceLikeCheckpointLedger()

    @property
    def ledger(self) -> SourceLikeCheckpointLedger:
        return self._ledger

    @property
    def consumed(self) -> bool:
        return self._consumed

    def authorize(
        self,
        target_url: str,
        *,
        user_confirmed: bool,
        confirmation_text: str,
    ) -> SourceLikeWriteAuthorization:
        if self._consumed:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_ALREADY_CONSUMED"
            )
        if self._environment_ack != LIVE_WRITE_ENV_ACK:
            raise SourceLikeWriteTestAuthorizationError(
                f"SOURCE_LIKE_WRITE_TEST_ENV_REQUIRED:{LIVE_WRITE_ENV}"
            )
        article_id = self.allowlist.require_single_article()
        if not user_confirmed or confirmation_text != LIVE_WRITE_CONFIRMATION:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_USER_CONFIRMATION_REQUIRED"
            )
        try:
            validate_source_like_target(target_url)
        except InvalidSourceLikeTargetError as exc:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_TARGET_INVALID"
            ) from exc
        parsed = urlparse(target_url)
        target_article_id = parsed.path.removeprefix("/read/cv")
        if target_article_id != article_id:
            raise SourceLikeWriteTestAuthorizationError(
                "SOURCE_LIKE_WRITE_TEST_TARGET_NOT_ALLOWLISTED"
            )
        return SourceLikeWriteAuthorization(
            target_url=target_url,
            article_id=article_id,
            environment_acknowledged=True,
            user_confirmed=True,
            confirmation_text=confirmation_text,
        )

    async def execute(
        self,
        executor: GuardedSourceLikeExecutor,
        *,
        target_url: str,
        payload: Mapping[str, object] | None = None,
        user_confirmed: bool,
        confirmation_text: str,
    ) -> SourceLikeWriteResult:
        self.authorize(
            target_url,
            user_confirmed=user_confirmed,
            confirmation_text=confirmation_text,
        )
        self._consumed = True
        return await executor.execute(
            self._ledger,
            target_url=target_url,
            payload=payload,
            user_confirmed=True,
        )


def _read_numeric_ids(payload: Mapping[str, Any], field: str) -> tuple[str, ...]:
    raw = payload.get(field, [])
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SourceLikeWriteTestAllowlistError(
            f"SOURCE_LIKE_WRITE_TEST_ALLOWLIST_{field.upper()}_INVALID"
        )
    values: list[str] = []
    for value in raw:
        text = str(value).strip()
        if not text.isdecimal():
            raise SourceLikeWriteTestAllowlistError(
                f"SOURCE_LIKE_WRITE_TEST_ALLOWLIST_{field.upper()}_ID_INVALID"
            )
        if text not in values:
            values.append(text)
    return tuple(values)
