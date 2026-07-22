from __future__ import annotations

from typing import Any, Protocol


class BriefingWriter(Protocol):
    """Write boundary for generated briefing content."""

    def save_briefing(self, date_str: str, content: str) -> int: ...


class BriefingReader(Protocol):
    """Read boundary for generated briefing content."""

    def get_latest_briefing(self) -> dict[str, Any] | None: ...

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None: ...

    def list_briefings(self, limit: int = 30) -> list[dict[str, Any]]: ...


class BriefingContentRepository(BriefingWriter, BriefingReader, Protocol):
    """Combined content boundary used by briefing generation services."""
