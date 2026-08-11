from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.services.briefing.daily_briefing import (
    _BLOCK_RESPONSE_ERROR,
    _CONTINUATION_PROMPT,
    _MAX_CONTINUATION_ROUNDS,
    _PROMPT_GITHUB,
    _SOURCE_CHANNELS,
    _SOURCE_CONFIG,
    DailyBriefingService,
    _format_articles,
    _looks_like_block_response,
    _truncate_summary,
)
from backend.app.services.briefing.preparation import (
    interleave_documents_by_source,
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
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        self.assertEqual(context.source, "all")
        self.assertEqual(context.cache_date, "2026-07-22")
        self.assertIsNone(context.source_type)
        self.assertEqual(
            context.expected_channels,
            (
                "huggingface_daily_html",
                "github_trending_daily",
                "techmeme_daily_rss",
                "producthunt_daily_html",
                "hn_daily_html",
                "x_daily_watchlist",
                "dailyhot_daily",
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

    def test_interleave_round_robins_sources_regardless_of_score_scale(self) -> None:
        # 量纲差异巨大时全局分数截断会让低分来源整源缺席；轮询按桶出现顺序逐源取。
        documents = [
            *[
                {"source": "dailyhot", "title": f"hot-{index}", "raw_score": 9000 - index}
                for index in range(5)
            ],
            # 桶内仍按该源规则排序：news-1 分高，应先于 news-0 出桶。
            {"source": "news", "title": "news-0", "raw_score": 1.0},
            {"source": "news", "title": "news-1", "raw_score": 2.0},
            {"source": "github", "title": "gh-1", "rank_in_period": 2, "raw_score": 900},
            {"source": "github", "title": "gh-0", "rank_in_period": 1, "raw_score": 100},
        ]

        selected = interleave_documents_by_source(documents, top_k=6)

        self.assertEqual(
            [document["title"] for document in selected],
            ["hot-0", "news-1", "gh-0", "hot-1", "news-0", "gh-1"],
        )

    def test_interleave_fills_remaining_slots_from_other_sources(self) -> None:
        documents = [
            {"source": "news", "title": "news-only", "raw_score": 2.0},
            *[
                {"source": "dailyhot", "title": f"hot-{index}", "raw_score": 9000 - index}
                for index in range(5)
            ],
        ]

        selected = interleave_documents_by_source(documents, top_k=4)

        self.assertEqual(
            [document["title"] for document in selected],
            ["news-only", "hot-0", "hot-1", "hot-2"],
        )

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
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
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
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=1,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=lambda docs, _source: docs,
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
            ),
        )
        document_feed.get_recent_top_documents.assert_not_called()
        document_feed.get_latest_documents.assert_not_called()

    def test_adapter_filters_documents_then_uses_latest_fallback(self) -> None:
        snapshot_reader = MagicMock()
        snapshot_reader.get_snapshot_documents.return_value = []
        document_feed = MagicMock()
        document_feed.get_recent_top_documents.return_value = [
            _github_doc("weekly", channel="github_trending_weekly")
        ]
        document_feed.get_latest_documents.return_value = [
            _github_doc("blocked", summary="Access Denied"),
            _github_doc("latest"),
        ]
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="github",
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=2,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=lambda docs, _source: [
                doc
                for doc in docs
                if doc["source_channel"] == "github_trending_daily"
            ],
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        document_feed.get_recent_top_documents.assert_called_once_with(
            source_type="github",
            since_date="2026-07-21",
            limit=6,
        )
        document_feed.get_latest_documents.assert_called_once_with(limit=2)
        self.assertTrue(prepared.fallback_used)
        self.assertEqual([document["title"] for document in prepared.documents], ["latest"])
        self.assertIsNotNone(prepared.prompt)

    def test_fallback_all_source_queries_recent_window_per_source(self) -> None:
        # 快照缺失的综合兜底：逐源按日期域取候选再轮询——旧实现全表按
        # raw_score 截断，低分量纲源（news 1-2 分）在 top_k*3 处整源缺席。
        snapshot_reader = MagicMock()
        snapshot_reader.get_snapshot_documents.return_value = []
        document_feed = MagicMock()

        def by_source(*, source_type, since_date, limit):
            assert since_date == "2026-07-21"
            assert limit == 3
            return {
                "github": [
                    {"source": "github", "title": "gh", "rank_in_period": 1, "raw_score": 800}
                ],
                "news": [{"source": "news", "title": "news", "raw_score": 1.5}],
            }.get(source_type, [])

        document_feed.get_recent_top_documents.side_effect = by_source
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="all",
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=3,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=lambda docs, _source: docs,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["gh", "news"],
        )
        called_sources = {
            call.kwargs["source_type"]
            for call in document_feed.get_recent_top_documents.call_args_list
        }
        self.assertEqual(called_sources, set(_SOURCE_CHANNELS.keys()))
        document_feed.get_latest_documents.assert_not_called()

    def test_adapter_all_source_interleaves_channels_instead_of_global_score_cut(self) -> None:
        # 综合简报快照路径：dailyhot 分数量级远高于 news/github，旧实现按全局
        # raw_score 截断会只留下 dailyhot；轮询保证每个有数据的渠道都入选。
        snapshot_reader = MagicMock()

        def by_channel(*, snapshot_date, source_channel, source_type, limit):
            del snapshot_date, source_type, limit
            return {
                "github_trending_daily": [
                    {
                        "source": "github",
                        "title": "gh",
                        "rank_in_period": 1,
                        "raw_score": 800,
                    }
                ],
                "techmeme_daily_rss": [
                    {"source": "news", "title": "news", "raw_score": 1.5}
                ],
                "dailyhot_daily": [
                    {
                        "source": "dailyhot",
                        "title": f"hot-{index}",
                        "raw_score": 9000 - index,
                    }
                    for index in range(5)
                ],
            }.get(source_channel, [])

        snapshot_reader.get_snapshot_documents.side_effect = by_channel
        document_feed = MagicMock()
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="all",
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=3,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=lambda docs, _source: docs,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["gh", "news", "hot-0"],
        )
        document_feed.get_top_documents.assert_not_called()
        document_feed.get_latest_documents.assert_not_called()

    def test_adapter_returns_empty_when_every_source_is_empty(self) -> None:
        snapshot_reader = MagicMock()
        snapshot_reader.get_snapshot_documents.return_value = []
        document_feed = MagicMock()
        document_feed.get_recent_top_documents.return_value = []
        document_feed.get_latest_documents.return_value = []
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="news",
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )

        prepared = prepare_briefing(
            context=context,
            top_k=10,
            snapshot_reader=snapshot_reader,
            document_feed=document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=lambda _docs, _source: [],
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

        snapshot_reader.get_snapshot_documents.assert_called_once_with(
            snapshot_date="2026-07-22",
            source_channel="techmeme_daily_rss",
            source_type="news",
            limit=10,
        )
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
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"], {
            "date": "2026-07-22",
            "doc_count": 1,
            "cached": False,
            "fallback": False,
            "milvus": False,
            "source": "github",
        })
        service._rank_snapshots.get_snapshot_documents.assert_called_once_with(
            snapshot_date="2026-07-22",
            source_channel="github_trending_daily",
            source_type="github",
            limit=2,
        )
        service._document_feed.get_recent_top_documents.assert_not_called()
        service._document_feed.get_latest_documents.assert_not_called()
        expected_docs = [self._github_doc("second", rank=2, score=200)]
        service._llm.astream.assert_called_once_with(
            _PROMPT_GITHUB.format(
                count=1,
                articles=_format_articles(expected_docs, "github"),
                date="2026-07-22",
            )
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github", "x" * 201 + "。"
        )

    def test_documents_then_latest_fallback_preserves_channel_and_event_contract(self) -> None:
        service = self._service(top_k=2)
        service._rank_snapshots.get_snapshot_documents.return_value = []
        service._document_feed.get_recent_top_documents.return_value = [
            self._github_doc("weekly", channel="github_trending_weekly"),
        ]
        service._document_feed.get_latest_documents.return_value = [
            {"id": "latest", "source": "news", "title": "Latest", "summary": "usable"}
        ]
        service._llm.astream.side_effect = self._astream_side_effect(["y" * 201 + "。"])

        events = self._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertTrue(events[0]["data"]["fallback"])
        self.assertEqual(events[0]["data"]["doc_count"], 1)
        service._document_feed.get_recent_top_documents.assert_called_once_with(
            source_type="github", since_date="2026-07-21", limit=6
        )
        service._document_feed.get_latest_documents.assert_called_once_with(limit=2)

    def test_invalid_source_falls_back_before_cache_lookup(self) -> None:
        service = self._service()
        service._briefings.get_briefing_by_date.return_value = {
            "id": 42,
            "content": "cached",
        }

        events = self._collect(
            service.stream_generate(
                "2026-07-22",
                source="invalid",
                force_regenerate=False,
            )
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"], {
            "date": "2026-07-22",
            "doc_count": 0,
            "cached": True,
            "source": "all",
        })
        service._briefings.get_briefing_by_date.assert_called_once_with(
            "2026-07-22"
        )
        service._rank_snapshots.get_snapshot_documents.assert_not_called()
        service._briefings.save_briefing.assert_not_called()

    def test_no_documents_streams_start_content_done_without_persistence(self) -> None:
        service = self._service()
        service._rank_snapshots.get_snapshot_documents.return_value = []
        service._document_feed.get_recent_top_documents.return_value = []
        service._document_feed.get_latest_documents.return_value = []

        events = self._collect(
            service.stream_generate("2026-07-22", source="news")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"]["source"], "news")
        self.assertEqual(events[0]["data"]["doc_count"], 0)
        self.assertIn("# 2026-07-22 今日简报", events[1]["data"])
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
            "2026-07-22_github", complete
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
            "2026-07-22_github",
            chinese,
            content_zh=chinese,
            content_en=english,
        )
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})

    def test_short_but_complete_report_does_not_trigger_continuation(self) -> None:
        # 篇幅不足 200 字符但结构完整的简报不得被误判截断而触发续写。
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        short_report = "# 今日简报\n\n仅一条快讯，内容完整。"
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect([short_report])
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual(service._llm.astream.call_count, 1)
        self.assertEqual(
            [event["data"] for event in events if event["type"] == "content"],
            [short_report],
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github", short_report
        )

    def test_is_truncated_only_flags_structural_signals(self) -> None:
        is_truncated = DailyBriefingService._is_truncated

        # 短但完整：不截断（原 <200 字符规则已移除）。
        self.assertFalse(is_truncated("简短短报，完整结束。"))
        self.assertFalse(is_truncated(""))
        self.assertFalse(is_truncated("   "))

        # 结构性截断信号仍然生效。
        self.assertTrue(is_truncated("x" * 300 + "\n```python"))
        self.assertTrue(is_truncated("x" * 300 + "\n## "))
        self.assertTrue(is_truncated("x" * 300 + "\n**未闭合粗体"))
        self.assertTrue(is_truncated("x" * 300 + "\n3."))

    def test_bilingual_alternate_locale_gets_continuation_rounds(self) -> None:
        # 另一语言与主语言走同一条续写路径：截断时同样多轮续写后再持久化。
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        chinese = "简短但完整的中文简报。"
        english_truncated = "English briefing " * 20 + "\n## "
        english_continuation = "continued section. " * 20
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect(
                [chinese, english_truncated, english_continuation]
            )
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate(
                "2026-07-22",
                source="github",
                locale="zh-CN",
                generate_bilingual=True,
            )
        )

        self.assertEqual(service._llm.astream.call_count, 3)
        # 另一语言的续写 prompt 携带其已生成内容（而非主语言内容）。
        self.assertEqual(
            service._llm.astream.call_args_list[-1].args[0],
            _CONTINUATION_PROMPT.format(previous_content=english_truncated),
        )
        english_full = english_truncated + english_continuation
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github",
            chinese,
            content_zh=chinese,
            content_en=english_full,
        )
        # 另一语言的续写过程不向客户端推流。
        self.assertEqual(
            [event["data"] for event in events if event["type"] == "content"],
            [chinese],
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
                    },
                },
                {"type": "content", "data": "Access Denied: Cloudflare Ray ID"},
                {"type": "error", "data": _BLOCK_RESPONSE_ERROR},
            ],
        )
        service._briefings.save_briefing.assert_not_called()

    def test_relay_json_envelope_is_stripped_before_persistence(self) -> None:
        # 上游协议漂移返回 {"answer": "..."}<CPA_DONE> 包装（2026-08-09_x
        # 缓存污染事故）：已推流 token 不可回收，但入库必须是剥离后的纯 Markdown。
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        envelope = json.dumps({"answer": "# X 动态今日报\n\n完整正文。<CPA_DONE>"})
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect([envelope])
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="x")
        )

        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})
        saved = service._briefings.save_briefing.call_args
        self.assertEqual(saved.args[0], "2026-07-22_x")
        self.assertEqual(saved.args[1], "# X 动态今日报\n\n完整正文。")
        self.assertNotIn("<CPA_DONE>", saved.args[1])
        self.assertFalse(saved.args[1].startswith('{"answer":'))

    def test_unparseable_relay_envelope_emits_error_and_skips_persistence(self) -> None:
        # 形似信封但 JSON 无法解析（如传输截断）：按拦截页同等级处理，
        # 报错且不落库，避免半个包装层进入缓存。
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect(
                ['{"answer":"# 未闭合的报告正文……']
            )
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="x")
        )

        self.assertEqual(events[-1], {"type": "error", "data": _BLOCK_RESPONSE_ERROR})
        service._briefings.save_briefing.assert_not_called()

    def test_x_source_shows_official_author_label_instead_of_zero_score(self) -> None:
        # X 关注清单均为官方账号，score 恒为 0：展示发布者身份而非"评分: 0.0"。
        with_author = _format_articles(
            [{"source": "x", "title": "t", "score": 0.0, "author_name": "@OpenAI"}],
            "x",
        )
        without_author = _format_articles(
            [{"source": "x", "title": "t", "score": 0.0}],
            "x",
        )

        self.assertIn("📣 @OpenAI", with_author)
        self.assertIn("📣 官方账号动态", without_author)
        self.assertNotIn("评分", with_author)
        self.assertNotIn("评分", without_author)

    def test_truncate_summary_breaks_on_boundary_and_marks_ellipsis(self) -> None:
        short = "简短摘要。"
        self.assertEqual(_truncate_summary(short), short)

        # 空格边界在后半段：截到边界处并补省略号，不产生半个单词。
        long_en = ("word " * 60).strip()
        truncated = _truncate_summary(long_en, limit=200)
        self.assertTrue(truncated.endswith("…"))
        self.assertLessEqual(len(truncated), 201)
        self.assertFalse(truncated[:-1].endswith("wor"))

        # 无可用边界的连续文本：硬截断但必须带省略号标记。
        long_cjk = "汉" * 300
        truncated_cjk = _truncate_summary(long_cjk, limit=200)
        self.assertTrue(truncated_cjk.endswith("…"))
        self.assertEqual(len(truncated_cjk), 201)

        # 折叠换行与多余空白，避免摘要里的换行打断 prompt 条目行。
        multiline = "第一行\n\n第二行   带有  多余空白"
        self.assertEqual(_truncate_summary(multiline), "第一行 第二行 带有 多余空白")

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
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=briefings,
        document_feed=document_feed,
        rank_snapshot_reader=rank_snapshots,
        model=MagicMock(astream=MagicMock()),
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
