"""Bounded visible evidence around images and later article/thread corrections."""
from __future__ import annotations

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_CONTENT_CLASSES = frozenset({"markdown-body", "comment-body", "article-body", "entry-content", "post-content"})
_HIDDEN = frozenset({"script", "style", "noscript", "nav", "footer", "header", "form", "iframe"})
IMAGE_CONTEXT_CHARS = 1400
SOURCE_EXCERPT_CHARS = 2400


def _content(node: Tag) -> bool:
    return (node.name == "article" or node.get("role") == "article" or node.get("itemprop") == "articleBody"
            or bool(_CONTENT_CLASSES.intersection(node.get("class", []))))


def _excerpt(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    # Preserve late corrections and disclaimers instead of trusting only the
    # opening of a long article. The separator is not source text.
    half = (limit - 5) // 2
    return text[:half] + " ... " + text[-half:]


def image_context(image: Tag) -> str:
    """Read nearby rendered text, excluding other pictures and hidden markup."""
    boundary = next((node for node in image.parents if isinstance(node, Tag) and
                     (_content(node) or node.name in {"figure", "section", "main", "body"})), None)

    def side(nodes, before: bool) -> str:
        parts, size = [], 0
        for index, node in enumerate(nodes):
            if index >= 250 or node is boundary:
                break
            if boundary is not None and boundary not in node.parents:
                break
            if isinstance(node, Tag) and node.name == "img":
                break
            if not isinstance(node, NavigableString) or isinstance(node, Comment):
                continue
            if any(parent.name in _HIDDEN for parent in node.parents):
                continue
            text = " ".join(str(node).split())
            if not text:
                continue
            remaining = IMAGE_CONTEXT_CHARS // 2 - size
            parts.append(text[-remaining:] if before else text[:remaining])
            size += min(len(text), remaining) + 1
            if size >= IMAGE_CONTEXT_CHARS // 2:
                break
        return " ".join(reversed(parts) if before else parts)

    before, after = side(image.previous_elements, True), side(image.next_elements, False)
    return (before + " " + after).strip()[:IMAGE_CONTEXT_CHARS]


def page_source_excerpt(soup: BeautifulSoup) -> str:
    """Keep article/comment content, including later replies, without nav text."""
    sections = [node for node in soup.find_all(_content) if not any(
        isinstance(parent, Tag) and _content(parent) for parent in node.parents)]
    if not sections:
        sections = [soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup]
    text = " ".join(node.get_text(" ", strip=True) for node in sections)
    return _excerpt(text, SOURCE_EXCERPT_CHARS)
