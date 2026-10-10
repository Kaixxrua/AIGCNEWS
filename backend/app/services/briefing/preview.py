"""Bounded public excerpt; full briefing bodies stay behind authentication."""

from __future__ import annotations


def briefing_preview(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    # Never return an entire short issue. Prefer a complete Markdown paragraph,
    # but keep a hard bound even for reports consisting of one very long block.
    limit = min(1200, len(text) // 2)
    excerpt = text[:limit]
    boundary = excerpt.rfind("\n\n")
    if boundary >= 120:
        excerpt = excerpt[:boundary]
    return excerpt.rstrip() + "\n\n…"
