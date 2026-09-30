from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from backend.app.domain.document_search_intent import (
    DateWindow,
    parse_query_intent,
    strip_ask_fillers,
)
from backend.app.repositories.postgres_document_repository import (
    _document_search_plan,
)

_VECTORS = Path(__file__).resolve().parent / "fixtures" / "document_search_intent_vectors.json"
_TODAY = date(2026, 9, 30)  # 周三


class SharedVectorTests(unittest.TestCase):
    """共享向量同时被 mcp-go/internal/postgres/document_intent_test.go 读取。"""

    def test_plan_matches_shared_vectors(self) -> None:
        cases = json.loads(_VECTORS.read_text(encoding="utf-8"))["cases"]
        self.assertGreater(len(cases), 20)
        for case in cases:
            with self.subTest(query=case["query"], today=case["today"]):
                plan = _document_search_plan(case["query"], today=date.fromisoformat(case["today"]))
                window = None if plan.window is None else [plan.window.since, plan.window.until]
                self.assertEqual(plan.candidates, case["candidates"])
                self.assertEqual(window, case["window"])


class QueryIntentTests(unittest.TestCase):
    def test_question_about_last_night_keeps_only_the_entity(self) -> None:
        plan = _document_search_plan("简洁总结昨晚openai发布了什么", today=_TODAY)
        self.assertEqual(plan.candidates[1:], ["openai"])
        self.assertEqual(plan.window, DateWindow("2026-09-29", "2026-10-01"))

    def test_time_only_question_filters_by_date_without_keywords(self) -> None:
        plan = _document_search_plan("今天有什么新闻", today=_TODAY)
        self.assertEqual(plan.candidates, [])
        self.assertIsNotNone(plan.window)

    def test_focused_queries_are_untouched(self) -> None:
        for query in ("OpenAI", "RAG 教程", "学习 python", "gpt-4o mini", "whatsapp", "Todayfeed"):
            with self.subTest(query=query):
                plan = _document_search_plan(query, today=_TODAY)
                self.assertEqual(plan.candidates, [query])
                self.assertIsNone(plan.window)

    def test_ascii_phrases_need_word_boundaries(self) -> None:
        self.assertIsNone(parse_query_intent("todayfeed recentness", _TODAY).window)
        self.assertFalse(parse_query_intent("whatsapp", _TODAY).asks)
        self.assertIsNotNone(parse_query_intent("OpenAI today", _TODAY).window)

    def test_relative_windows(self) -> None:
        cases = {
            "最近3天": ("2026-09-27", "2026-10-01"),
            "近三天": ("2026-09-27", "2026-10-01"),
            "过去二十天": ("2026-09-10", "2026-10-01"),
            "7天内": ("2026-09-23", "2026-10-01"),
            "过去24小时": ("2026-09-29", "2026-10-01"),
            "最近2周": ("2026-09-16", "2026-10-01"),
            "past 3 days": ("2026-09-27", "2026-10-01"),
            "last 2 weeks": ("2026-09-16", "2026-10-01"),
            "上周": ("2026-09-20", "2026-09-28"),
            "本周": ("2026-09-27", "2026-10-01"),
            "本月": ("2026-08-31", "2026-10-01"),
            "上个月": ("2026-07-31", "2026-09-01"),
            "前天": ("2026-09-28", "2026-09-30"),
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(parse_query_intent(query, _TODAY).window, DateWindow(*expected))

    def test_digits_glued_to_model_names_are_not_durations(self) -> None:
        self.assertIsNone(parse_query_intent("llama3个月内", _TODAY).window)
        self.assertIsNone(parse_query_intent("9月30日", _TODAY).window)

    def test_earliest_time_expression_wins(self) -> None:
        self.assertEqual(
            parse_query_intent("上周和今天", _TODAY).window, DateWindow("2026-09-20", "2026-09-28")
        )

    def test_huge_counts_are_clamped(self) -> None:
        window = parse_query_intent("最近99999999999999999999999天", _TODAY).window
        self.assertEqual(window, DateWindow("2025-09-30", "2026-10-01"))

    def test_fillers_strip_longest_first(self) -> None:
        self.assertEqual(" ".join(strip_ask_fillers("OpenAI 都发布了什么").split()), "OpenAI")
        self.assertEqual(" ".join(strip_ask_fillers("what's new in the Codex CLI").split()), "Codex CLI")


if __name__ == "__main__":
    unittest.main()
