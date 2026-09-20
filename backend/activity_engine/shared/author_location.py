"""Identify visible author links without navigating or performing writes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .dom_read import attribute, inner_text, normalize, visible_candidates


@dataclass(frozen=True, slots=True)
class AuthorIdentityPolicy:
    """Keep each flow's historical name and profile-path recognition rules."""

    name_matches: Callable[[str, str], bool]
    profile_id_from_href: Callable[[str], str]


async def author_profile_ids(
    page: Any,
    author: str,
    *,
    selector: str,
    policy: AuthorIdentityPolicy,
) -> set[str]:
    """Collect all exact-author identities, deduplicating links, not authors.

    Both direct-page and search-page discovery use the same evidence rules.
    Distinct matching IDs remain ambiguous; callers must require exactly one.
    """
    result: set[str] = set()
    for candidate in await visible_candidates(page, selector):
        href = await attribute(candidate, "href")
        if not href or not policy.name_matches(normalize(await inner_text(candidate)), author):
            continue
        profile_id = policy.profile_id_from_href(href)
        if profile_id:
            result.add(profile_id)
    return result
