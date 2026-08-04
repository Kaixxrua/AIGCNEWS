from __future__ import annotations

import asyncio

from backend.app.services.briefing_admin import (
    BRIEFING_DIMENSIONS,
    BriefingAdminService,
)


class RecordingBriefingGenerator:
    def __init__(self, failed_source: str | None = None) -> None:
        self.failed_source = failed_source
        self.calls: list[dict[str, object]] = []

    async def stream_generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["source"] == self.failed_source:
            raise RuntimeError("generation failed")
        yield {"type": "done"}


def test_generate_all_forwards_force_flag_in_canonical_order() -> None:
    generator = RecordingBriefingGenerator()
    service = BriefingAdminService(generator)

    asyncio.run(service.generate_all(False))

    assert [(call["source"], call["period"]) for call in generator.calls] == list(
        BRIEFING_DIMENSIONS
    )
    assert all(call["target_date"] is None for call in generator.calls)
    assert all(call["force_regenerate"] is False for call in generator.calls)


def test_generate_all_reuses_generator_and_isolates_dimension_failures() -> None:
    generator = RecordingBriefingGenerator(failed_source="github")
    service = BriefingAdminService(generator)

    asyncio.run(service.generate_all(True))

    assert [call["source"] for call in generator.calls] == [
        "all",
        "arxiv",
        "github",
        "news",
        "producthunt",
        "hackernews",
        "x",
    ]
    assert all(call["force_regenerate"] is True for call in generator.calls)
