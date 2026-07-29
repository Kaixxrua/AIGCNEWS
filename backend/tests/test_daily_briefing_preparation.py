from __future__ import annotations

import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "backend.app.core.model_factory" not in sys.modules:
    model_factory_module = types.ModuleType("backend.app.core.model_factory")
    model_factory_module.get_chat_model = MagicMock
    sys.modules["backend.app.core.model_factory"] = model_factory_module

if "backend.app.repositories.milvus_repo" not in sys.modules:
    milvus_module = types.ModuleType("backend.app.repositories.milvus_repo")
    milvus_module.MilvusRepository = MagicMock
    sys.modules["backend.app.repositories.milvus_repo"] = milvus_module

if "backend.app.repositories.mysql_repo" not in sys.modules:
    mysql_module = types.ModuleType("backend.app.repositories.mysql_repo")
    mysql_module.MySQLRepository = MagicMock
    sys.modules["backend.app.repositories.mysql_repo"] = mysql_module

from backend.app.services.briefing.daily_briefing import (
    _BLOCK_RESPONSE_ERROR,
    _CONTINUATION_PROMPT,
    _MAX_CONTINUATION_ROUNDS,
    _PERIOD_CHANNEL_MAP,
    _PERIOD_LABEL,
    _PROMPT_GITHUB,
    _SOURCE_CONFIG,
    DailyBriefingService,
    _format_articles,
    _looks_like_block_response,
)
from backend.app.services.briefing.preparation import (
    normalize_briefing_context,
    order_snapshot_documents,
    prepare_briefing,
    remove_blocked_documents,
    render_briefing_prompt,
)


class BriefingPurePreparationTests(unittest.TestCase):
    def test_context_normalization_preserves_fallback_cache_and_channels(self) -> None:
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="invalid",
            period="invalid",
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )

        self.assertEqual(context.source, "all")
        self.assertEqual(context.period, "daily")
        self.assertEqual(context.cache_date, "2026-07-22_daily")
        self.assertIsNone(context.source_type)
        self.assertEqual(
            context.expected_channels,
            (
                "huggingface_daily_html",
                "github_trending_daily",
                "techmeme_daily_rss",
                "producthunt_daily_html",
                "hn_daily_html",
            ),
        )

    def test_snapshot_ordering_and_top_k_are_pure(self) -> None:
        documents = [
            _github_doc("third", rank=3, score=300),
            _github_doc("first-low", rank=1, score=100),
            _github_doc("first-high", rank=1, score=200),
        ]

        ordered = order_snapshot_documents(documents, source="github", top_k=2)

        self.assertEqual(
            [document["title"] for document in ordered],
            ["first-high", "first-low"],
        )
        self.assertEqual(documents[0]["title"], "third")

    def test_block_filter_and_prompt_rendering_preserve_exact_text(self) -> None:
        documents = [
            _github_doc("blocked", summary="Cloudflare Ray ID"),
            _github_doc("usable"),
        ]
        clean = remove_blocked_documents(
            documents,
            is_blocked=_looks_like_block_response,
        )
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="github",
            period="daily",
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )

        prompt = render_briefing_prompt(
            context=context,
            documents=clean,
            source_config=_SOURCE_CONFIG,
            format_articles=_format_articles,
        )

        self.assertEqual(
            prompt,
            _PROMPT_GITHUB.format(
                count=1,
                articles=_format_articles([_github_doc("usable")], "github"),
                date="2026-07-22",
                period_label="今日",
            ),
        )


class BriefingPreparationAdapterTests(unittest.TestCase):
    def test_adapter_uses_snapshot_first_and_preserves_prompt(self) -> None:
        snapshot_reader = MagicMock()
        snapshot_reader.get_snapshot_documents.return_value = [
            _github_doc("second", rank=2, score=200),
            _github_doc("first", rank=1, score=100),
        ]
        document_feed = MagicMock()
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="github",
            period="daily",
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=1,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_period=lambda docs, _source, _period: docs,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        self.assertEqual([document["title"] for document in prepared.documents], ["first"])
        self.assertFalse(prepared.fallback_used)
        self.assertFalse(prepared.milvus_used)
        self.assertEqual(
            prepared.prompt,
            _PROMPT_GITHUB.format(
                count=1,
                articles=_format_articles([_github_doc("first", rank=1, score=100)], "github"),
                date="2026-07-22",
                period_label="今日",
            ),
        )
        document_feed.get_top_documents.assert_not_called()
        document_feed.get_latest_documents.assert_not_called()

    def test_adapter_filters_documents_then_uses_latest_fallback(self) -> None:
        snapshot_reader = MagicMock()
        snapshot_reader.get_snapshot_documents.return_value = []
        document_feed = MagicMock()
        document_feed.get_top_documents.return_value = [
            _github_doc("weekly", channel="github_trending_weekly")
        ]
        document_feed.get_latest_documents.return_value = [
            _github_doc("blocked", summary="Access Denied"),
            _github_doc("latest"),
        ]
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="github",
            period="daily",
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=2,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_period=lambda docs, _source, _period: [
                doc
                for doc in docs
                if doc["source_channel"] == "github_trending_daily"
            ],
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        document_feed.get_top_documents.assert_called_once_with(
            limit=6,
            source_type="github",
        )
        document_feed.get_latest_documents.assert_called_once_with(limit=2)
        self.assertTrue(prepared.fallback_used)
        self.assertEqual([document["title"] for document in prepared.documents], ["latest"])
        self.assertIsNotNone(prepared.prompt)

    def test_adapter_keeps_missing_channel_source_fallback_behavior(self) -> None:
        snapshot_reader = MagicMock()
        document_feed = MagicMock()
        document_feed.get_top_documents.return_value = []
        document_feed.get_latest_documents.return_value = []
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="news",
            period="weekly",
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=10,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_period=lambda _docs, _source, _period: [],
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        snapshot_reader.get_snapshot_documents.assert_not_called()
        self.assertEqual(prepared.documents, ())
        self.assertIsNone(prepared.prompt)
        self.assertTrue(prepared.fallback_used)


class DailyBriefingPreparationContractTests(unittest.TestCase):
    def test_snapshot_is_preferred_sorted_limited_and_blocked_docs_are_removed(self) -> None:
        service = self._service(top_k=2)
        service._rank_snapshots.get_snapshot_documents.return_value = [
            self._github_doc("third", rank=3, score=300),
            self._github_doc("blocked", rank=1, score=500, summary="Access Denied"),
            self._github_doc("second", rank=2, score=200),
        ]
        service._llm.astream.side_effect = self._astream_side_effect(["x" * 201 + "。"])

        events = self._collect(
            service.stream_generate("2026-07-22", source="github", period="daily")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"], {
            "date": "2026-07-22",
            "doc_count": 1,
            "cached": False,
            "fallback": False,
            "milvus": False,
            "source": "github",
            "period": "daily",
        })
        service._rank_snapshots.get_snapshot_documents.assert_called_once_with(
            snapshot_date="2026-07-22",
            source_channel="github_trending_daily",
            source_type="github",
            limit=2,
        )
        service._document_feed.get_top_documents.assert_not_called()
        service._document_feed.get_latest_documents.assert_not_called()
        expected_docs = [self._github_doc("second", rank=2, score=200)]
        service._llm.astream.assert_called_once_with(
            _PROMPT_GITHUB.format(
                count=1,
                articles=_format_articles(expected_docs, "github"),
                date="2026-07-22",
                period_label="今日",
            )
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github_daily", "x" * 201 + "。"
        )

    def test_documents_then_latest_fallback_preserves_channel_and_event_contract(self) -> None:
        service = self._service(top_k=2)
        service._rank_snapshots.get_snapshot_documents.return_value = []
        service._document_feed.get_top_documents.return_value = [
            self._github_doc("weekly", channel="github_trending_weekly"),
        ]
        service._document_feed.get_latest_documents.return_value = [
            {"id": "latest", "source": "news", "title": "Latest", "summary": "usable"}
        ]
        service._llm.astream.side_effect = self._astream_side_effect(["y" * 201 + "。"])

        events = self._collect(
            service.stream_generate("2026-07-22", source="github", period="daily")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertTrue(events[0]["data"]["fallback"])
        self.assertEqual(events[0]["data"]["doc_count"], 1)
        service._document_feed.get_top_documents.assert_called_once_with(
            limit=6, source_type="github"
        )
        service._document_feed.get_latest_documents.assert_called_once_with(limit=2)

    def test_invalid_source_and_period_fall_back_before_cache_lookup(self) -> None:
        service = self._service()
        service._briefings.get_briefing_by_date.return_value = {
            "id": 42,
            "content": "cached",
        }

        events = self._collect(
            service.stream_generate(
                "2026-07-22",
                source="invalid",
                period="invalid",
                force_regenerate=False,
            )
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"], {
            "date": "2026-07-22",
            "doc_count": 0,
            "cached": True,
            "source": "all",
            "period": "daily",
        })
        service._briefings.get_briefing_by_date.assert_called_once_with(
            "2026-07-22_daily"
        )
        service._rank_snapshots.get_snapshot_documents.assert_not_called()
        service._briefings.save_briefing.assert_not_called()

    def test_no_documents_streams_start_content_done_without_persistence(self) -> None:
        service = self._service()
        service._rank_snapshots.get_snapshot_documents.return_value = []
        service._document_feed.get_top_documents.return_value = []
        service._document_feed.get_latest_documents.return_value = []

        events = self._collect(
            service.stream_generate("2026-07-22", source="news", period="weekly")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"]["source"], "news")
        self.assertEqual(events[0]["data"]["period"], "weekly")
        self.assertEqual(events[0]["data"]["doc_count"], 0)
        self.assertIn("# 2026-07-22 本周简报", events[1]["data"])
        self.assertEqual(events[2]["data"], {"briefing_id": -1})
        service._briefings.save_briefing.assert_not_called()
        service._llm.astream.assert_not_called()


class DailyBriefingStreamingContractTests(unittest.TestCase):
    def test_continuation_is_limited_to_five_rounds_and_last_4000_characters(self) -> None:
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        fragments = [
            str(index) * 997 + "\n1."
            for index in range(_MAX_CONTINUATION_ROUNDS + 1)
        ]
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect(fragments)
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual(service._llm.astream.call_count, 1 + _MAX_CONTINUATION_ROUNDS)
        self.assertEqual(
            [event["data"] for event in events if event["type"] == "content"],
            [
                fragments[0],
                "",
                fragments[1],
                "",
                fragments[2],
                "",
                fragments[3],
                "",
                fragments[4],
                "",
                fragments[5],
            ],
        )
        expected_previous = "".join(fragments[:5])[-4000:]
        self.assertEqual(
            service._llm.astream.call_args_list[-1].args[0],
            _CONTINUATION_PROMPT.format(previous_content=expected_previous),
        )
        complete = "".join(fragments)
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github_daily", complete
        )
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})

    def test_bilingual_generation_streams_requested_locale_and_persists_both(self) -> None:
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        chinese = "中" * 201 + "。"
        english = "English briefing " * 20 + "."
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect([english, chinese])
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate(
                "2026-07-22",
                source="github",
                locale="en-US",
                generate_bilingual=True,
            )
        )

        self.assertEqual(
            [event["data"] for event in events if event["type"] == "content"],
            [english],
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github_daily",
            chinese,
            content_zh=chinese,
            content_en=english,
        )
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})

    def test_blocked_llm_response_emits_error_and_is_never_persisted(self) -> None:
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect(
                ["Access Denied: Cloudflare Ray ID"]
            )
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual(
            events,
            [
                {
                    "type": "start",
                    "data": {
                        "date": "2026-07-22",
                        "doc_count": 1,
                        "cached": False,
                        "fallback": False,
                        "milvus": False,
                        "source": "github",
                        "period": "daily",
                    },
                },
                {"type": "content", "data": "Access Denied: Cloudflare Ray ID"},
                {"type": "error", "data": _BLOCK_RESPONSE_ERROR},
            ],
        )
        service._briefings.save_briefing.assert_not_called()

    def test_persistence_occurs_after_all_content_events_and_before_done(self) -> None:
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]

        async def chunks():
            yield SimpleNamespace(content="first")
            yield SimpleNamespace(content="z" * 196 + "。")

        service._llm.astream.side_effect = lambda _prompt: chunks()
        timeline: list[str] = []
        service._briefings.save_briefing.side_effect = lambda *_args: (
            timeline.append("save") or 73
        )

        async def collect() -> list[dict]:
            events = []
            async for event in service.stream_generate("2026-07-22", source="github"):
                timeline.append(event["type"])
                events.append(event)
            return events

        events = asyncio.run(collect())

        self.assertEqual(timeline, ["start", "content", "content", "save", "done"])
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})


    def test_extended_thinking_blocks_preserve_text_order(self) -> None:
        service = DailyBriefingPreparationContractTests._service()

        async def chunks():
            yield SimpleNamespace(
                content=[
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "text", "text": "visible-1"},
                    "visible-2",
                ]
            )

        service._llm.astream.side_effect = lambda _prompt: chunks()

        async def collect():
            return [token async for token in service._stream_llm_round("prompt")]

        self.assertEqual(asyncio.run(collect()), ["visible-1visible-2"])


# Helpers live on the preparation contract class so both suites exercise identical wiring.
def _service(*, top_k: int = 10) -> DailyBriefingService:
    briefings = MagicMock()
    briefings.save_briefing.return_value = 73
    document_feed = MagicMock()
    rank_snapshots = MagicMock()
    with patch(
        "backend.app.services.briefing.daily_briefing.get_chat_model",
        return_value=MagicMock(astream=MagicMock()),
    ):
        return DailyBriefingService(
            top_k=top_k,
            briefing_repository=briefings,
            document_feed=document_feed,
            rank_snapshot_reader=rank_snapshots,
        )


def _github_doc(
    title: str,
    *,
    rank: int = 1,
    score: int = 100,
    channel: str = "github_trending_daily",
    summary: str = "summary",
) -> dict:
    return {
        "id": title,
        "source": "github",
        "source_channel": channel,
        "title": title,
        "summary": summary,
        "url": f"https://github.com/example/{title}",
        "rank_in_period": rank,
        "raw_score": score,
        "score": score,
        "stars": 1000,
    }


def _astream_side_effect(outputs: list[str]):
    calls = iter(outputs)

    def make_stream(_prompt: str):
        output = next(calls)

        async def stream():
            yield SimpleNamespace(content=output)

        return stream()

    return make_stream


DailyBriefingPreparationContractTests._service = staticmethod(_service)
DailyBriefingPreparationContractTests._github_doc = staticmethod(_github_doc)
DailyBriefingPreparationContractTests._astream_side_effect = staticmethod(_astream_side_effect)


def _collect(generator):
    async def collect():
        return [event async for event in generator]

    return asyncio.run(collect())


DailyBriefingPreparationContractTests._collect = staticmethod(_collect)


if __name__ == "__main__":
    unittest.main()
