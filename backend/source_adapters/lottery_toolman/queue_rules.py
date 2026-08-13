"""Pure queue rules migrated from the userscript.

This module deliberately knows nothing about Playwright, FastAPI or the
database.  It receives the minimal parsed HTML tree and returns a deterministic
read-only queue plus audit statistics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .html_parser import HtmlNode, nearest_line_node, text_before_node

_DYNAMIC_PATH_RE = re.compile(r"^/opus/(\d+)/?$", re.IGNORECASE)
_T_PATH_RE = re.compile(r"^/(\d+)/?$", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CollectedActivity:
    dynamic_id: str
    canonical_url: str
    title: str
    source_position: int


@dataclass(frozen=True)
class QueueStats:
    aggregate_excluded: int
    started_after_pinned: bool
    start_mode: str
    links_seen: int
    unique_links: int


@dataclass(frozen=True)
class CollectedQueue:
    items: tuple[CollectedActivity, ...]
    stats: QueueStats


def clean_text(value: str | None) -> str:
    normalized = (value or "").replace("\u200b", "").replace("\ufeff", "")
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def canonical_url(raw_url: str, base_url: str) -> str:
    """Normalize a URL for comparison while retaining only Bilibili paths."""

    from urllib.parse import urljoin

    absolute = urljoin(base_url, raw_url)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def dynamic_from_url(raw_url: str, base_url: str) -> tuple[str, str] | None:
    normalized = canonical_url(raw_url, base_url)
    parts = urlsplit(normalized)
    host = parts.netloc.lower()
    match: re.Match[str] | None = None
    if host == "www.bilibili.com":
        match = _DYNAMIC_PATH_RE.match(parts.path)
    elif host == "t.bilibili.com":
        match = _T_PATH_RE.match(parts.path)
    if match is None:
        return None
    dynamic_id = match.group(1)
    return dynamic_id, f"https://www.bilibili.com/opus/{dynamic_id}"


def _line_text(anchor: HtmlNode, fallback: HtmlNode) -> str:
    return clean_text(nearest_line_node(anchor, fallback).text_content())


def is_other_lottery_collection_link(anchor: HtmlNode, fallback: HtmlNode) -> bool:
    line_text = _line_text(anchor, fallback)
    anchor_text = clean_text(anchor.text_content())
    text = f"{anchor_text} {line_text}"
    has_collection_name = bool(re.search(r"(?:官方\s*)?抽奖(?:合集|汇总)|开奖(?:合集|汇总)", text))
    is_full_result_section = bool(
        re.search(r"开奖部分", text) and re.search(r"(?:全部版|全版)", text)
    )
    return has_collection_name or is_full_result_section


def start_kind_for_anchor(anchor: HtmlNode, fallback: HtmlNode) -> str:
    line = nearest_line_node(anchor, fallback)
    before = clean_text(text_before_node(line, anchor))
    full_text = clean_text(line.text_content())
    if re.search(r"(?:^|\s)新的\s*→", before):
        return "new-link"
    if re.search(r"(?:^|\s)\d+\s*[、.．)]\s*→", before):
        return "sequence-link"
    if not before:
        if re.search(r"(?:^|\s)新的\s*→", full_text):
            return "new-link"
        if re.search(r"(?:^|\s)\d+\s*[、.．)]\s*→", full_text):
            return "sequence-link"
    return ""


def is_lottery_entry_block(text: str) -> bool:
    value = clean_text(text)
    return bool(
        re.search(r"(?:^|\s)[^→\n]{0,24}→\s*\d{4}[年/-]", value)
        or re.search(r"(?:^|\s)\d+\s*[、.．)]\s*→", value)
    )


def find_pinned_end_index(blocks: list[HtmlNode]) -> int:
    last_pinned_index = -1
    for index, block in enumerate(blocks):
        if "置顶抽奖" in clean_text(block.text_content()):
            last_pinned_index = index
    if last_pinned_index < 0:
        return -1
    for index in range(last_pinned_index + 1, len(blocks)):
        if is_lottery_entry_block(blocks[index].text_content()):
            return index
    return last_pinned_index + 1


def collect_queue(
    content_root: HtmlNode,
    source_url: str,
    *,
    skip_pinned: bool = True,
) -> CollectedQueue:
    """Apply the userscript's queue rules to a parsed source article."""

    blocks = list(content_root.children)
    all_items: list[CollectedActivity] = []
    normal_items: list[CollectedActivity] = []
    excluded_keys: set[str] = set()
    new_start_index = -1
    sequence_start_index = -1
    pinned_end_index = find_pinned_end_index(blocks) if skip_pinned else 0
    saw_pinned = pinned_end_index >= 0
    start_index = pinned_end_index if saw_pinned else 0

    for block_index, block in enumerate(blocks):
        anchors = list(block.descendants("a"))
        for anchor in anchors:
            href = anchor.attrs.get("href", "")
            dynamic = dynamic_from_url(href, source_url)
            if dynamic is None:
                continue
            dynamic_id, url = dynamic
            if canonical_url(url, source_url) == canonical_url(source_url, source_url):
                continue
            if is_other_lottery_collection_link(anchor, block):
                excluded_keys.add(url)
                continue
            item = CollectedActivity(
                dynamic_id=dynamic_id,
                canonical_url=url,
                title=clean_text(anchor.text_content()) or url,
                source_position=len(all_items) + 1,
            )
            item_index = len(all_items)
            all_items.append(item)
            if skip_pinned and block_index >= start_index:
                kind = start_kind_for_anchor(anchor, block)
                if kind == "new-link" and new_start_index < 0:
                    new_start_index = item_index
                if kind == "sequence-link" and sequence_start_index < 0:
                    sequence_start_index = item_index
            if block_index >= start_index:
                normal_items.append(item)

    items = all_items
    start_mode = "all"
    if skip_pinned and new_start_index >= 0:
        items = all_items[new_start_index:]
        start_mode = "new-link"
    elif skip_pinned and sequence_start_index >= 0:
        items = all_items[sequence_start_index:]
        start_mode = "sequence-link"
    elif skip_pinned and not saw_pinned:
        start_mode = "from-first"
    elif skip_pinned:
        items = normal_items
        start_mode = "after-pinned"

    unique: list[CollectedActivity] = []
    seen: set[str] = set()
    for item in items:
        if item.dynamic_id in seen:
            continue
        seen.add(item.dynamic_id)
        unique.append(
            CollectedActivity(
                dynamic_id=item.dynamic_id,
                canonical_url=item.canonical_url,
                title=item.title,
                source_position=len(unique) + 1,
            )
        )
    return CollectedQueue(
        items=tuple(unique),
        stats=QueueStats(
            aggregate_excluded=len(excluded_keys),
            started_after_pinned=skip_pinned and saw_pinned,
            start_mode=start_mode,
            links_seen=len(items),
            unique_links=len(unique),
        ),
    )
