"""Extract comment semantics without mixing navigation or comment-list text."""

from __future__ import annotations

import re

_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"[\r\n。！？；;]+")
_COMMENT_MARKER_RE = re.compile(
    r"评论区|评论(?:一句|内容)?|留言|(?:转发并)?分享|聊聊|说说|谈谈"
)
_COMMENT_START_RE = re.compile(
    r"(?:请|欢迎|记得|并|同时|转发并)?\s*"
    r"(?:在评论区)?\s*(?:评论(?:一句|内容)?|留言|分享|聊聊|说说|谈谈)"
)
_RESULT_CLAUSE_RE = re.compile(
    r"(?:，|,)?\s*(?:我们将|将会|届时|即可|就有机会|抽取|开奖|送出).*$"
)


def extract_comment_instruction(text: str) -> str:
    """Return the shortest visible clause that describes what to comment.

    The source examples use both explicit words (``评论区``) and implicit
    social verbs (``分享你的……``/``聊聊……``).  Only the already-scoped dynamic
    body may be passed here; this function intentionally knows nothing about
    the surrounding page.
    """

    normalized = _SPACE_RE.sub(" ", text.replace("\u200b", "")).strip()
    for sentence in _SENTENCE_SPLIT_RE.split(normalized):
        sentence = sentence.strip(" ，,")
        marker = _COMMENT_MARKER_RE.search(sentence)
        if marker is None:
            continue
        start = _COMMENT_START_RE.search(sentence)
        fragment = sentence[start.start() if start else marker.start() :]
        fragment = _RESULT_CLAUSE_RE.sub("", fragment).strip(" ，,")
        return fragment[:240]
    return ""
