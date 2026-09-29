from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.services.briefing.daily_briefing import (
    _BLOCK_RESPONSE_ERROR,
    _BOARD_SOURCES,
    _CONTINUATION_PROMPT,
    _MAX_CONTINUATION_ROUNDS,
    _PROMPT_GITHUB,
    _PROMPT_X,
    _SOURCE_CONFIG,
    DailyBriefingService,
    _count_briefing_items,
    _format_articles,
    _looks_like_block_response,
    _truncate_summary,
    _unescape_backticks,
)
from backend.app.services.briefing.preparation import (
    BoardSlice,
    describe_board_dates,
    finalized_board_date,
    interleave_documents_by_source,
    normalize_briefing_context,
    order_snapshot_documents,
    prepare_briefing,
    remove_blocked_documents,
    render_briefing_prompt,
)
from backend.app.services.dashboard.policy import github_metric_to_doc


class BriefingPurePreparationTests(unittest.TestCase):
    def test_context_normalization_reads_each_board_on_its_finalized_date(self) -> None:
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="invalid",
            source_config=_SOURCE_CONFIG,
            board_sources=_BOARD_SOURCES,
        )

        self.assertEqual(context.source, "all")
        # 期号（缓存键）仍是发布日；内容读的是 08:00 前已定稿的榜：北京日界源
        # 01:00 关榜 → 前一日；太平洋日界源 17:00 才定稿 → 前两日。
        self.assertEqual(context.cache_date, "2026-07-22")
        self.assertEqual(
            context.boards,
            (
                BoardSlice("arxiv", "2026-07-20", "PT"),
                BoardSlice("github", "2026-07-21", "CST"),
                BoardSlice("news", "2026-07-21", "CST"),
                BoardSlice("producthunt", "2026-07-20", "PT"),
                BoardSlice("hackernews", "2026-07-21", "CST"),
                BoardSlice("dailyhot", "2026-07-21", "CST"),
            ),
        )
        self.assertEqual(context.rolling_sources, ("x",))

    def test_context_normalization_for_x_uses_fixed_anchor_cache_key(self) -> None:
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="x",
            source_config=_SOURCE_CONFIG,
            board_sources=_BOARD_SOURCES,
        )

        self.assertEqual(context.source, "x")
        self.assertEqual(context.cache_date, "2026-07-22_0800_x")
        self.assertEqual(context.boards, ())
        self.assertEqual(context.rolling_sources, ("x",))

    def test_finalized_board_date_depends_only_on_publish_date(self) -> None:
        cases = {
            "github": "2026-09-28",
            "news": "2026-09-28",
            "hackernews": "2026-09-28",
            "dailyhot": "2026-09-28",
            "arxiv": "2026-09-27",
            "producthunt": "2026-09-27",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(finalized_board_date("2026-09-29", source), expected)
        # 跨月、非法期号原样透传（读榜为空，走无数据分支）
        self.assertEqual(finalized_board_date("2026-10-01", "producthunt"), "2026-09-29")
        self.assertEqual(finalized_board_date("not-a-date", "github"), "not-a-date")

    def test_describe_board_dates_single_source_and_grouped_all(self) -> None:
        def describe(source: str) -> str:
            return describe_board_dates(
                normalize_briefing_context(
                    target_date="2026-09-29",
                    source=source,
                    source_config=_SOURCE_CONFIG,
                    board_sources=_BOARD_SOURCES,
                )
            )

        self.assertEqual(describe("github"), "2026-09-28")
        self.assertEqual(describe("producthunt"), "2026-09-27（太平洋时间）")
        self.assertEqual(
            describe("all"),
            "2026-09-27（太平洋时间）：论文、Product Hunt；"
            "2026-09-28：GitHub、新闻、Hacker News、中文站点；"
            "X：2026-09-28 08:00 至 2026-09-29 08:00（北京时间）",
        )
        self.assertEqual(
            describe("x"), "X：2026-09-28 08:00 至 2026-09-29 08:00（北京时间）"
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
            board_sources=_BOARD_SOURCES,
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
                board_date="2026-07-21",
            ),
        )

    def test_all_briefing_sources_hide_evaluation_metrics(self) -> None:
        metric_fields = {
            "score": 4321.0,
            "raw_score": 9876.0,
            "stars": 12345,
            "votes": 678,
            "points": 543,
            "likes": 210,
        }
        sources = (
            "arxiv",
            "github",
            "news",
            "producthunt",
            "hackernews",
            "x",
            "dailyhot",
        )
        forbidden = (
            "评分",
            "Stars",
            "points",
            "votes",
            "likes",
            "点赞",
            "转发",
            "互动指标",
            "热度分析",
            "增长趋势",
            "排名",
            "热榜",
        )

        docs = [
            {
                **metric_fields,
                "source": source,
                "source_channel": f"{source}_daily",
                "title": f"{source}-entry",
                "summary": "content summary",
                "url": f"https://example.test/{source}",
                "author_name": "@OpenAI" if source == "x" else "",
                "feed_name": "Techmeme" if source == "news" else "",
            }
            for source in sources
        ]
        articles = _format_articles(docs, "all")

        for source in sources:
            with self.subTest(source=source):
                self.assertIn(f"{source}-entry", articles)
        for value in ("4321", "9876", "12345", "678", "543", "210"):
            self.assertNotIn(value, articles)
        for term in forbidden:
            self.assertNotIn(term, articles)

        for source, (template, _suffix) in _SOURCE_CONFIG.items():
            with self.subTest(prompt_source=source):
                for term in forbidden:
                    self.assertNotIn(term, template)

    def test_every_briefing_prompt_targets_a_three_minute_read(self) -> None:
        # "At least N sentences per item" produced 10k+ character briefings that
        # readers skipped and that pushed single streams past the upstream cap.
        for source, (template, _suffix) in _SOURCE_CONFIG.items():
            with self.subTest(source=source):
                prompt = template.format(
                    count=3, articles="ARTICLES", date="2026-09-28", board_date="2026-09-27"
                )
                self.assertIn("约 3 分钟读完", prompt)
                self.assertIn("1000-1500 字", prompt)
                self.assertIn("不删条目", prompt)
                self.assertNotIn("内容详尽", prompt)
                self.assertNotIn("至少", prompt)

    def test_board_prompts_state_board_date_and_avoid_today_wording(self) -> None:
        # 期号 P 的简报读的是已定稿的前一日（太平洋日界源为前两日）榜单，
        # 提示词不能再把条目称为"今日"；X 仍是截至 08:00 的 24h 窗口，不改。
        for source in _BOARD_SOURCES + ("all",):
            template, _suffix = _SOURCE_CONFIG[source]
            with self.subTest(source=source):
                prompt = template.format(
                    count=3, articles="ARTICLES", date="2026-09-29", board_date="BOARD"
                )
                self.assertIn("**榜单日期：** BOARD", prompt)
                self.assertIn("榜单日期纪律", prompt)
                self.assertNotIn("今日内容", prompt)
                self.assertNotIn("今日报", prompt)
        self.assertNotIn("{board_date}", _PROMPT_X)
        self.assertNotIn("榜单日期纪律", _PROMPT_X)


class BriefingPreparationAdapterTests(unittest.TestCase):
    @staticmethod
    def _prepare(context, *, top_k, read_board, document_feed=None):
        return prepare_briefing(
            context=context,
            top_k=top_k,
            read_board=read_board,
            document_feed=document_feed or MagicMock(),
            source_config=_SOURCE_CONFIG,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

    @staticmethod
    def _context(source: str, target_date: str = "2026-07-22"):
        return normalize_briefing_context(
            target_date=target_date,
            source=source,
            source_config=_SOURCE_CONFIG,
            board_sources=_BOARD_SOURCES,
        )

    def test_adapter_reads_finalized_board_and_preserves_prompt(self) -> None:
        read_board = MagicMock(
            return_value=[
                _github_doc("second", rank=2, score=200),
                _github_doc("first", rank=1, score=100),
            ]
        )
        document_feed = MagicMock()

        prepared = self._prepare(
            self._context("github"),
            top_k=1,
            read_board=read_board,
            document_feed=document_feed,
        )

        read_board.assert_called_once_with("github", "2026-07-21", 1)
        self.assertEqual([document["title"] for document in prepared.documents], ["first"])
        self.assertFalse(prepared.milvus_used)
        self.assertEqual(
            prepared.prompt,
            _PROMPT_GITHUB.format(
                count=1,
                articles=_format_articles([_github_doc("first", rank=1, score=100)], "github"),
                date="2026-07-22",
                board_date="2026-07-21",
            ),
        )
        document_feed.list_recent_by_source.assert_not_called()

    def test_missing_board_is_not_backfilled_from_document_table(self) -> None:
        # 旧实现在快照缺失时按入库时间取近 ~32 小时条目兜底，与任何一张榜都
        # 对不上；定稿榜口径下榜缺失即该源缺席。
        document_feed = MagicMock()

        prepared = self._prepare(
            self._context("github"),
            top_k=2,
            read_board=MagicMock(return_value=[]),
            document_feed=document_feed,
        )

        self.assertEqual(prepared.documents, ())
        self.assertIsNone(prepared.prompt)
        document_feed.get_recent_top_documents.assert_not_called()
        document_feed.get_latest_documents.assert_not_called()

    def test_all_source_reads_every_board_on_its_finalized_date(self) -> None:
        calls: list[tuple[str, str, int]] = []

        def read_board(source: str, board_date: str, limit: int):
            calls.append((source, board_date, limit))
            return [{"source": source, "title": source, "raw_score": 1}]

        prepared = self._prepare(
            self._context("all"), top_k=3, read_board=read_board
        )

        self.assertEqual(
            calls,
            [
                ("arxiv", "2026-07-20", 3),
                ("github", "2026-07-21", 3),
                ("news", "2026-07-21", 3),
                ("producthunt", "2026-07-20", 3),
                ("hackernews", "2026-07-21", 3),
                ("dailyhot", "2026-07-21", 3),
            ],
        )
        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["arxiv", "github", "news"],
        )

    def test_adapter_all_source_interleaves_boards_instead_of_global_score_cut(self) -> None:
        # dailyhot 分数量级远高于 news/github，按全局 raw_score 截断会只留下
        # dailyhot；轮询保证每个有数据的源都入选。
        def read_board(source: str, board_date: str, limit: int):
            del board_date, limit
            return {
                "github": [
                    {
                        "source": "github",
                        "title": "gh",
                        "rank_in_period": 1,
                        "raw_score": 800,
                    }
                ],
                "news": [{"source": "news", "title": "news", "raw_score": 1.5}],
                "dailyhot": [
                    {
                        "source": "dailyhot",
                        "title": f"hot-{index}",
                        "raw_score": 9000 - index,
                    }
                    for index in range(5)
                ],
            }.get(source, [])

        prepared = self._prepare(
            self._context("all"), top_k=3, read_board=read_board
        )

        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["gh", "news", "hot-0"],
        )

    def test_adapter_x_source_uses_rolling_window_not_boards(self) -> None:
        read_board = MagicMock()
        document_feed = MagicMock()
        document_feed.list_recent_by_source.return_value = [
            {"source": "x", "title": "x-1", "raw_score": 100, "published_at": "2026-07-22T07:00:00+08:00"},
            {"source": "x", "title": "x-2", "raw_score": 90, "published_at": "2026-07-22T06:00:00+08:00"},
        ]

        prepared = self._prepare(
            self._context("x"),
            top_k=3,
            read_board=read_board,
            document_feed=document_feed,
        )

        read_board.assert_not_called()
        document_feed.list_recent_by_source.assert_called_once_with(
            source="x",
            since_iso="2026-07-21T08:00:00+08:00",
            until_iso="2026-07-22T08:00:00+08:00",
            limit=9,
        )
        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["x-1", "x-2"],
        )

    def test_adapter_all_source_merges_boards_and_rolling_x(self) -> None:
        def read_board(source: str, board_date: str, limit: int):
            del board_date, limit
            return {
                "github": [
                    {"source": "github", "title": "gh", "rank_in_period": 1, "raw_score": 800}
                ],
            }.get(source, [])

        document_feed = MagicMock()
        document_feed.list_recent_by_source.return_value = [
            {"source": "x", "title": "x-1", "raw_score": 100, "published_at": "2026-07-22T07:00:00+08:00"},
        ]

        prepared = self._prepare(
            self._context("all"),
            top_k=2,
            read_board=read_board,
            document_feed=document_feed,
        )

        self.assertEqual(
            [document["title"] for document in prepared.documents],
            ["gh", "x-1"],
        )
        document_feed.list_recent_by_source.assert_called_once_with(
            source="x",
            since_iso="2026-07-21T08:00:00+08:00",
            until_iso="2026-07-22T08:00:00+08:00",
            limit=6,
        )

    def test_all_source_without_any_board_does_not_publish_x_only(self) -> None:
        document_feed = MagicMock()
        document_feed.list_recent_by_source.return_value = [
            {"source": "x", "title": "x-1", "raw_score": 100},
        ]

        prepared = self._prepare(
            self._context("all"),
            top_k=3,
            read_board=MagicMock(return_value=[]),
            document_feed=document_feed,
        )

        self.assertEqual(prepared.documents, ())
        self.assertIsNone(prepared.prompt)


class DailyBriefingPreparationContractTests(unittest.TestCase):
    def test_board_is_sorted_limited_and_blocked_docs_are_removed(self) -> None:
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
            snapshot_date="2026-07-21",
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
                board_date="2026-07-21",
            )
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github", "x" * 201 + "。"
        )

    def test_github_reads_homepage_hot_board_not_trending_snapshot(self) -> None:
        # 日报 GitHub 与首页 GitHub 榜同一来源：项目库日度热度（hot_score 序）。
        github_hot = MagicMock()
        rows = [
            {"repo_id": "r1", "full_name": "acme/first", "url": "https://github.com/acme/first",
             "description": "first repo", "stars": 10, "daily_star_growth": 900,
             "hot_score": 9.0, "metric_date": "2026-07-21"},
            {"repo_id": "r2", "full_name": "acme/second", "url": "https://github.com/acme/second",
             "description": "second repo", "stars": 20, "daily_star_growth": 800,
             "hot_score": 8.0, "metric_date": "2026-07-21"},
        ]
        github_hot.list_github_hot_for_date.return_value = rows
        service = self._service(top_k=2, github_hot_board=github_hot)
        service._llm.astream.side_effect = self._astream_side_effect(["y" * 201 + "。"])

        events = self._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertFalse(events[0]["data"]["fallback"])
        github_hot.list_github_hot_for_date.assert_called_once_with(
            metric_date="2026-07-21", limit=2
        )
        service._rank_snapshots.get_snapshot_documents.assert_not_called()
        expected_docs = [
            github_metric_to_doc(row, rank=index + 1) for index, row in enumerate(rows)
        ]
        service._llm.astream.assert_called_once_with(
            _PROMPT_GITHUB.format(
                count=2,
                articles=_format_articles(expected_docs, "github"),
                date="2026-07-22",
                board_date="2026-07-21",
            )
        )

    def test_pacific_source_reads_board_finalized_before_publish_anchor(self) -> None:
        service = self._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            {"id": "ph", "source": "producthunt", "title": "Launch", "summary": "s",
             "url": "https://www.producthunt.com/posts/launch", "raw_score": 300},
        ]
        service._llm.astream.side_effect = self._astream_side_effect(["z" * 201 + "。"])

        self._collect(service.stream_generate("2026-07-22", source="producthunt"))

        service._rank_snapshots.get_snapshot_documents.assert_called_once_with(
            snapshot_date="2026-07-20",
            source_channel="producthunt_daily_html",
            source_type="producthunt",
            limit=10,
        )
        prompt = service._llm.astream.call_args.args[0]
        self.assertIn("**榜单日期：** 2026-07-20（太平洋时间）", prompt)

    def test_hackernews_applies_homepage_previous_day_dedup(self) -> None:
        service = self._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            {"id": "seen", "source": "hackernews", "title": "Seen", "raw_score": 500},
            {"id": "fresh", "source": "hackernews", "title": "Fresh", "raw_score": 100},
        ]
        service._rank_snapshots.get_snapshot_doc_ids.return_value = {"seen"}
        service._llm.astream.side_effect = self._astream_side_effect(["h" * 201 + "。"])

        events = self._collect(
            service.stream_generate("2026-07-22", source="hackernews")
        )

        self.assertEqual(events[0]["data"]["doc_count"], 1)
        service._rank_snapshots.get_snapshot_doc_ids.assert_called_once_with(
            snapshot_date="2026-07-20", source_channel="hn_daily_html"
        )
        prompt = service._llm.astream.call_args.args[0]
        self.assertIn("Fresh", prompt)
        self.assertNotIn("Seen", prompt)

    def test_dailyhot_reads_its_snapshot_channel_directly(self) -> None:
        service = self._service()
        service._rank_snapshots.get_snapshot_documents.return_value = []

        self._collect(service.stream_generate("2026-07-22", source="dailyhot"))

        service._rank_snapshots.get_snapshot_documents.assert_called_once_with(
            snapshot_date="2026-07-21",
            source_channel="dailyhot_daily",
            source_type="dailyhot",
            limit=10,
        )

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

        events = self._collect(
            service.stream_generate("2026-07-22", source="news")
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[0]["data"]["source"], "news")
        self.assertEqual(events[0]["data"]["doc_count"], 0)
        self.assertFalse(events[0]["data"]["fallback"])
        self.assertIn("# 2026-07-22 今日简报", events[1]["data"])
        self.assertIn("本期数据范围（2026-07-21）", events[1]["data"])
        self.assertEqual(events[2]["data"], {"briefing_id": -1})
        service._document_feed.get_recent_top_documents.assert_not_called()
        service._document_feed.get_latest_documents.assert_not_called()
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
        service._document_feed.list_recent_by_source.return_value = [
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
        self.assertEqual(saved.args[0], "2026-07-22_0800_x")
        self.assertEqual(saved.args[1], "# X 动态今日报\n\n完整正文。")
        self.assertNotIn("<CPA_DONE>", saved.args[1])
        self.assertFalse(saved.args[1].startswith('{"answer":'))

    def test_unparseable_relay_envelope_emits_error_and_skips_persistence(self) -> None:
        # 形似信封但 JSON 无法解析（如传输截断）：按拦截页同等级处理，
        # 报错且不落库，避免半个包装层进入缓存。
        service = DailyBriefingPreparationContractTests._service()
        service._document_feed.list_recent_by_source.return_value = [
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

    def test_x_source_groups_articles_by_account(self) -> None:
        # X 简报输入以账号为单位：同账号推文聚合为一个编号条目，
        # 组内推文再编号；分组顺序 = 账号首次出现顺序（输入已按热度降序）。
        docs = [
            _x_doc("t1", handle="OpenAI", author="OpenAI", score=100),
            _x_doc("t2", handle="OpenAI", author="OpenAI", score=90),
            _x_doc("t3", handle="sama", author="Sam Altman", score=80),
        ]

        articles = _format_articles(docs, "x")

        self.assertIn("1. 📣 @OpenAI（2 条推文）", articles)
        self.assertIn("2. 📣 Sam Altman (@sama)（1 条推文）", articles)
        self.assertIn("1) **t1**", articles)
        self.assertIn("2) **t2**", articles)
        self.assertIn("1) **t3**", articles)
        self.assertIn("🔗 https://x.com/OpenAI/status/t1", articles)
        self.assertNotIn("3. 📣", articles)

    def test_x_grouping_is_case_insensitive_and_falls_back_to_nickname(self) -> None:
        # handle 大小写差异归并同账号；无 URL 可解析时按昵称归并，
        # 两者皆无归入"官方账号动态"兜底组（不静默丢弃）。
        docs = [
            _x_doc("t1", handle="OpenAI", author="OpenAI"),
            _x_doc("t2", handle="openai", author="OpenAI"),
            {"source": "x", "title": "t3", "summary": "s", "url": "", "author_name": "alibaba_Qwen"},
            {"source": "x", "title": "t4", "summary": "s", "url": "", "author_name": ""},
            {"source": "x", "title": "t5", "summary": "s", "url": "", "author_name": None},
        ]

        articles = _format_articles(docs, "x")

        self.assertIn("1. 📣 @OpenAI（2 条推文）", articles)
        self.assertIn("2. 📣 @alibaba_Qwen（1 条推文）", articles)
        self.assertIn("3. 📣 官方账号动态（2 条推文）", articles)

    def test_x_prompt_counts_accounts_not_tweets(self) -> None:
        docs = [
            _x_doc("t1", handle="OpenAI", author="OpenAI", score=100),
            _x_doc("t2", handle="openai", author="OpenAI", score=90),
            _x_doc("t3", handle="sama", author="Sam Altman", score=80),
        ]
        context = normalize_briefing_context(
            target_date="2026-07-22",
            source="x",
            source_config=_SOURCE_CONFIG,
            board_sources=_BOARD_SOURCES,
        )

        prompt = render_briefing_prompt(
            context=context,
            documents=docs,
            source_config=_SOURCE_CONFIG,
            format_articles=_format_articles,
            count_items=_count_briefing_items,
        )

        self.assertEqual(
            prompt,
            _PROMPT_X.format(
                count=2,
                articles=_format_articles(docs, "x"),
                date="2026-07-22",
            ),
        )
        # 非 x 来源计数口径不变：仍以条目为单位。
        self.assertEqual(_count_briefing_items(docs, "all"), 3)
        self.assertEqual(_count_briefing_items(docs, "github"), 3)

    def test_x_streaming_prompt_is_grouped_by_account(self) -> None:
        # 端到端契约：x 源送给 LLM 的 prompt 以账号为单位（count=账号数，
        # articles 为分组渲染），而非逐条推文。
        service = DailyBriefingPreparationContractTests._service()
        docs = [
            _x_doc("t1", handle="OpenAI", author="OpenAI", score=100),
            _x_doc("t2", handle="OpenAI", author="OpenAI", score=90),
            _x_doc("t3", handle="sama", author="Sam Altman", score=80),
        ]
        service._document_feed.list_recent_by_source.return_value = docs
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect(["完整简报。"])
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="x")
        )

        self.assertEqual(events[0]["data"]["doc_count"], 3)
        service._document_feed.list_recent_by_source.assert_called_once()
        service._rank_snapshots.get_snapshot_documents.assert_not_called()
        service._llm.astream.assert_called_once_with(
            _PROMPT_X.format(
                count=2,
                articles=_format_articles(docs, "x"),
                date="2026-07-22",
            )
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_0800_x", "完整简报。"
        )

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


class DailyBriefingSavedNotifierTests(unittest.TestCase):
    """保存后通知契约：只有真实 save_briefing() 成功才触发，且先于 done。"""

    @staticmethod
    def _service_with_notifier(notifier) -> DailyBriefingService:
        service = _service()
        service._briefing_saved = notifier
        return service

    def test_successful_generation_notifies_once_before_done(self) -> None:
        calls: list[dict] = []
        order: list[str] = []
        service = self._service_with_notifier(
            lambda **kwargs: (calls.append(kwargs), order.append("notify"))
        )
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        report = "x" * 201 + "。"
        service._llm.astream.side_effect = _astream_side_effect([report])

        async def collect():
            events = []
            async for event in service.stream_generate("2026-07-22", source="github"):
                order.append(event["type"])
                events.append(event)
            return events

        events = asyncio.run(collect())

        self.assertEqual(order, ["start", "content", "notify", "done"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            {
                "report_date": "2026-07-22",
                "source": "github",
                "cache_key": "2026-07-22_github",
                "briefing_id": 73,
                "content_zh": report,
            },
        )
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})

    def test_bilingual_notifies_with_canonical_chinese_content(self) -> None:
        calls: list[dict] = []
        service = self._service_with_notifier(lambda **kwargs: calls.append(kwargs))
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        chinese = "中" * 201 + "。"
        english = "English briefing " * 20 + "."
        service._llm.astream.side_effect = _astream_side_effect([english, chinese])

        events = _collect(
            service.stream_generate(
                "2026-07-22",
                source="github",
                locale="en-US",
                generate_bilingual=True,
            )
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["content_zh"], chinese)
        self.assertEqual(calls[0]["briefing_id"], 73)
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})

    def test_x_source_notifies_with_anchored_cache_key_and_bare_date(self) -> None:
        calls: list[dict] = []
        service = self._service_with_notifier(lambda **kwargs: calls.append(kwargs))
        service._document_feed.list_recent_by_source.return_value = [
            _x_doc("t1", handle="OpenAI", author="OpenAI")
        ]
        service._llm.astream.side_effect = _astream_side_effect(["完整简报。"])

        _collect(service.stream_generate("2026-07-22", source="x"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["report_date"], "2026-07-22")
        self.assertEqual(calls[0]["source"], "x")
        self.assertEqual(calls[0]["cache_key"], "2026-07-22_0800_x")

    def test_cache_hit_does_not_notify(self) -> None:
        notifier = MagicMock()
        service = self._service_with_notifier(notifier)
        service._briefings.get_briefing_by_date.return_value = {
            "id": 42,
            "content": "cached",
        }

        events = _collect(
            service.stream_generate("2026-07-22", source="github", force_regenerate=False)
        )

        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 42}})
        notifier.assert_not_called()

    def test_no_documents_does_not_notify(self) -> None:
        notifier = MagicMock()
        service = self._service_with_notifier(notifier)
        service._rank_snapshots.get_snapshot_documents.return_value = []

        events = _collect(service.stream_generate("2026-07-22", source="news"))

        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": -1}})
        notifier.assert_not_called()

    def test_empty_llm_output_does_not_notify(self) -> None:
        notifier = MagicMock()
        service = self._service_with_notifier(notifier)
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        service._llm.astream.side_effect = _astream_side_effect(["  "])

        events = _collect(service.stream_generate("2026-07-22", source="github"))

        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": -1}})
        service._briefings.save_briefing.assert_not_called()
        notifier.assert_not_called()

    def test_blocked_response_does_not_notify(self) -> None:
        notifier = MagicMock()
        service = self._service_with_notifier(notifier)
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        service._llm.astream.side_effect = _astream_side_effect(
            ["Access Denied: Cloudflare Ray ID"]
        )

        events = _collect(service.stream_generate("2026-07-22", source="github"))

        self.assertEqual(events[-1]["type"], "error")
        service._briefings.save_briefing.assert_not_called()
        notifier.assert_not_called()

    def test_bilingual_alternate_failure_does_not_notify(self) -> None:
        notifier = MagicMock()
        service = self._service_with_notifier(notifier)
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        chinese = "中" * 201 + "。"
        service._llm.astream.side_effect = _astream_side_effect([chinese, "  "])

        events = _collect(
            service.stream_generate(
                "2026-07-22", source="github", generate_bilingual=True
            )
        )

        self.assertEqual(events[-1]["type"], "error")
        service._briefings.save_briefing.assert_not_called()
        notifier.assert_not_called()

    def test_notifier_exception_is_isolated_from_generation(self) -> None:
        def broken_notifier(**_kwargs) -> None:
            raise RuntimeError("dispatcher exploded")

        service = self._service_with_notifier(broken_notifier)
        service._rank_snapshots.get_snapshot_documents.return_value = [
            _github_doc("project")
        ]
        service._llm.astream.side_effect = _astream_side_effect(["x" * 201 + "。"])

        with self.assertLogs("backend.app.services.briefing.daily_briefing", "ERROR"):
            events = _collect(service.stream_generate("2026-07-22", source="github"))

        # 通知失败不得把成功生成变成 error：简报已保存、事件流照常收尾。
        service._briefings.save_briefing.assert_called_once()
        self.assertEqual(events[-1], {"type": "done", "data": {"briefing_id": 73}})


class BriefingBacktickSanitizeTests(unittest.TestCase):
    """2026-08-14_news/_producthunt/_x 事故回归：提示词示例中的 \\` 转义写法
    被模型照搬进正文，Markdown 将其渲染为字面反引号，标签失去行内代码样式。
    提示词不得再含该写法；入库前的整文净化必须兜底还原。"""

    def test_prompt_templates_do_not_contain_escaped_backtick_examples(self) -> None:
        for key, (template, _suffix) in _SOURCE_CONFIG.items():
            with self.subTest(source=key):
                self.assertNotIn("\\`", template)

    def test_unescape_backticks_restores_tag_spans_in_headings(self) -> None:
        text = "# 标题 \\`#news\\` \\`#企业AI\\`\n\n正文 \\`#LLM\\`。\n"
        self.assertEqual(
            _unescape_backticks(text),
            "# 标题 `#news` `#企业AI`\n\n正文 `#LLM`。\n",
        )

    def test_unescape_backticks_preserves_fenced_code_blocks(self) -> None:
        text = "标题 \\`#news\\`\n\n```sh\necho \\`date\\`\n```\n\n尾部 \\`#x\\`\n"
        self.assertEqual(
            _unescape_backticks(text),
            "标题 `#news`\n\n```sh\necho \\`date\\`\n```\n\n尾部 `#x`\n",
        )

    def test_unescape_backticks_treats_unclosed_fence_as_code_to_eof(self) -> None:
        text = "前文 \\`#news\\`\n\n```python\nprint(\\`x\\`)\n"
        self.assertEqual(
            _unescape_backticks(text),
            "前文 `#news`\n\n```python\nprint(\\`x\\`)\n",
        )

    def test_unescape_backticks_noop_without_escaped_backticks(self) -> None:
        text = "# 标题 `#news`\n\n普通正文。\n"
        self.assertEqual(_unescape_backticks(text), text)

    def test_sanitize_parts_rewrites_parts_with_unescaped_text(self) -> None:
        parts = ["## 章节 \\`#news\\` \\`#Agent\\`\n"]
        result = DailyBriefingService._sanitize_parts(parts)
        self.assertEqual(result, "## 章节 `#news` `#Agent`\n")
        self.assertEqual(parts, ["## 章节 `#news` `#Agent`\n"])

    def test_streamed_generation_persists_unescaped_content(self) -> None:
        # 流式 token 原样下发（与信封剥离同一契约），入库缓存必须是还原后的文本。
        service = DailyBriefingPreparationContractTests._service()
        service._rank_snapshots.get_snapshot_documents.return_value = [
            DailyBriefingPreparationContractTests._github_doc("project")
        ]
        report = "## 今日明星项目 \\`#github\\` \\`#AI基础设施\\`\n\n完整正文。"
        service._llm.astream.side_effect = (
            DailyBriefingPreparationContractTests._astream_side_effect([report])
        )

        events = DailyBriefingPreparationContractTests._collect(
            service.stream_generate("2026-07-22", source="github")
        )

        self.assertEqual(
            [event["data"] for event in events if event["type"] == "content"],
            [report],
        )
        service._briefings.save_briefing.assert_called_once_with(
            "2026-07-22_github",
            "## 今日明星项目 `#github` `#AI基础设施`\n\n完整正文。",
        )


# Helpers live on the preparation contract class so both suites exercise identical wiring.
def _service(*, top_k: int = 10, github_hot_board=None) -> DailyBriefingService:
    # github_hot_board=None：github 按看板未注入口径读 trending 快照，流式契约
    # 用例沿用快照 fixture；热度榜口径由专门用例注入验证。
    briefings = MagicMock()
    briefings.save_briefing.return_value = 73
    document_feed = MagicMock()
    rank_snapshots = MagicMock()
    rank_snapshots.get_snapshot_doc_ids.return_value = set()
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=briefings,
        document_feed=document_feed,
        rank_snapshot_reader=rank_snapshots,
        github_hot_board=github_hot_board,
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


def _x_doc(
    title: str,
    *,
    handle: str = "OpenAI",
    author: str = "OpenAI",
    score: int = 100,
    summary: str = "summary",
) -> dict:
    return {
        "id": title,
        "source": "x",
        "source_channel": "x_daily_watchlist",
        "title": title,
        "summary": summary,
        "url": f"https://x.com/{handle}/status/{title}",
        "author_name": author,
        "raw_score": score,
        "score": 0.0,
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


def test_paper_pdf_text_and_figures_are_used_in_both_briefing_languages(monkeypatch):
    from backend.app.services.briefing import daily_briefing

    service = _service()
    service._briefings.get_briefing_by_date.return_value = None
    service._rank_snapshots.get_snapshot_documents.return_value = [{
        "id": "paper", "source": "arxiv", "source_channel": "huggingface_daily_html",
        "title": "Paper", "summary": "Abstract", "url": "https://arxiv.org/abs/2403.12345",
        "raw_score": 1,
    }]
    images = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,figure"}}]
    monkeypatch.setattr(daily_briefing, "paper_pdf_evidence", lambda docs, source: ("PDF method evidence", images))
    service._llm.astream.side_effect = _astream_side_effect(["完整中文报告。", "Complete English report."])

    events = _collect(service.stream_generate("2026-07-22", source="arxiv", generate_bilingual=True))

    assert events[-1]["type"] == "done"
    assert service._llm.astream.call_count == 2
    for call in service._llm.astream.call_args_list:
        content = call.args[0][0].content
        assert "PDF method evidence" in content[0]["text"]
        assert content[-1] == images[0]
    service._briefings.save_briefing.assert_called_once()


if __name__ == "__main__":
    unittest.main()
