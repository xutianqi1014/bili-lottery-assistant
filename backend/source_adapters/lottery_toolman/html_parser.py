"""Small, dependency-free HTML tree used by the lottery-toolman parser.

The source article layout is owned by Bilibili and can change independently of
the API response.  Keeping this parser tiny and testable makes selector changes
local to the adapter instead of coupling the discovery use case to a browser
implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: HtmlNode | None = None
    children: list[HtmlNode] = field(default_factory=list)
    content: list[str | HtmlNode] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text_content(self) -> str:
        return "".join(
            part if isinstance(part, str) else part.text_content() for part in self.content
        )

    def descendants(self, tag: str | None = None) -> Iterator[HtmlNode]:
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)

    def has_class(self, class_name: str) -> bool:
        return class_name in self.classes


class _TreeBuilder(HTMLParser):
    _void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self._stack: list[HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(
            tag=tag.lower(),
            attrs={key.lower(): value or "" for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        self._stack[-1].content.append(node)
        if node.tag not in self._void_tags:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack[-1].tag == tag.lower() and tag.lower() not in self._void_tags:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == target:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].content.append(data)


def parse_html(html: str) -> HtmlNode:
    parser = _TreeBuilder()
    parser.feed(html)
    parser.close()
    return parser.root


def find_content_root(document: HtmlNode) -> HtmlNode | None:
    for node in document.descendants():
        if node.has_class("opus-module-content"):
            return node
    return None


def nearest_line_node(node: HtmlNode, fallback: HtmlNode) -> HtmlNode:
    current: HtmlNode | None = node
    line_tags = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
    while current is not None:
        if current.tag in line_tags:
            return current
        current = current.parent
    return node.parent or fallback


def text_before_node(line: HtmlNode, target: HtmlNode) -> str:
    """Return text appearing before *target* in *line*'s document order."""

    parts: list[str] = []
    found = False

    def walk(node: HtmlNode) -> None:
        nonlocal found
        if found:
            return
        if node is target:
            found = True
            return
        for part in node.content:
            if isinstance(part, str):
                parts.append(part)
            else:
                walk(part)
                if found:
                    return

    walk(line)
    return "".join(parts)
