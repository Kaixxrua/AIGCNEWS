from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_project_catalog_query_service,
)
from backend.app.api.routes_search import router
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.repositories.briefing_repository import BriefingSearchReader
from backend.app.repositories.postgres_briefing_repository import PostgresBriefingRepository
from backend.app.services.search.quick_search import briefing_excerpt, quick_search

BRIEFING = """# AI 工程开源项目日报 `#github` `#AI基础设施`

生成日期：2026-10-01｜榜单日期：2026-09-30

## 本期明星项目 `#github` `#Agent`

1. **dots**（feder-cr/dots）：这是一个面向网页的开源 AI Agent，拥有自有浏览器。[来源](https://github.com/feder-cr/dots)

2. **magpie**（yetone/magpie）：把不同 Agent 使用的模型集中到一个位置，示例包括 Codex 使用 DeepSeek、Claude Code 使用 Kimi。[来源](https://github.com/yetone/magpie)
"""


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context

    @contextmanager
    def transaction(self):
        yield self.connection


class BriefingSearchRepositoryTests(unittest.TestCase):
    def test_every_term_must_appear_in_the_locale_body_newest_issue_first(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"id": 9, "date": "2026-10-01", "body": "正文", "total": 3},
            {"id": 8, "date": "2026-10-01_github", "body": "正文", "total": 3},
        ]
        repository = PostgresBriefingRepository(FakeDatabase(cursor))

        page = repository.search_briefings(["50%", "a_b"], locale="en", limit=99, exclude_suffixes=("_0800_x",))

        self.assertEqual(page, {
            "items": [
                {"id": 9, "date": "2026-10-01", "body": "正文"},
                {"id": 8, "date": "2026-10-01_github", "body": "正文"},
            ],
            "total": 3,
        })
        sql, params = cursor.execute.call_args.args
        # 英文读 content_en，缺了退回 content、再退回中文；空白不算有内容
        self.assertIn("WHEN btrim(COALESCE(content_en, '')) <> '' THEN content_en", sql)
        self.assertLess(sql.index("THEN content_en"), sql.index("THEN content "), sql)
        self.assertLess(sql.index("THEN content "), sql.index("THEN content_zh"), sql)
        self.assertEqual(sql.count("body ILIKE %s ESCAPE '='"), 2)
        self.assertIn("date NOT LIKE %s ESCAPE '='", sql)
        self.assertIn("ORDER BY LEFT(date, 10) DESC, position('_' in date) = 0 DESC, id DESC", sql)
        # LIKE 通配符当字面量；条数上限 20
        self.assertEqual(params, ("%50=%%", "%a=_b%", "%=_0800=_x", 20))

    def test_chinese_reads_content_zh_first_and_empty_terms_skip_the_query(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        repository = PostgresBriefingRepository(FakeDatabase(cursor))

        self.assertEqual(repository.search_briefings(["agent"], locale="zh-CN", limit=0), {"items": [], "total": 0})
        sql, params = cursor.execute.call_args.args
        self.assertLess(sql.index("THEN content_zh"), sql.index("THEN content_en"), sql)
        self.assertEqual(params, ("%agent%", 1))

        cursor.reset_mock()
        self.assertEqual(repository.search_briefings(["", ""], locale="zh-CN"), {"items": [], "total": 0})
        cursor.execute.assert_not_called()

    def test_postgres_repository_satisfies_the_search_protocol(self) -> None:
        repository: BriefingSearchReader = PostgresBriefingRepository(FakeDatabase(MagicMock()))
        self.assertTrue(callable(repository.search_briefings))


class BriefingExcerptTests(unittest.TestCase):
    def test_picks_the_item_matching_most_terms_and_splits_out_its_name(self) -> None:
        excerpt = briefing_excerpt(BRIEFING, ["agent", "deepseek"])

        self.assertEqual(excerpt["title"], "AI 工程开源项目日报")
        self.assertEqual(excerpt["lead"], "magpie")
        # 名称后的（owner/repo）与冒号、来源链接、Markdown 记号都不进摘录
        self.assertEqual(
            excerpt["snippet"],
            "把不同 Agent 使用的模型集中到一个位置，示例包括 Codex 使用 DeepSeek、Claude Code 使用 Kimi。",
        )

    def test_ties_go_to_the_earlier_item_and_note_only_hits_still_count(self) -> None:
        self.assertEqual(briefing_excerpt(BRIEFING, ["agent"])["lead"], "dots")
        self.assertEqual(briefing_excerpt(BRIEFING, ["yetone"])["lead"], "magpie")

    def test_long_text_is_cut_around_the_first_hit(self) -> None:
        body = "# 标题\n\n" + "前文" * 100 + "关键词" + "后文" * 100
        snippet = briefing_excerpt(body, ["关键词"])["snippet"]

        self.assertTrue(snippet.startswith("…") and snippet.endswith("…"), snippet)
        self.assertIn("关键词", snippet)
        self.assertLessEqual(len(snippet), 142)

    def test_headings_and_tags_alone_give_no_excerpt(self) -> None:
        self.assertEqual(
            briefing_excerpt(BRIEFING, ["github"]),
            {"title": "AI 工程开源项目日报", "lead": "", "snippet": ""},
        )
        self.assertEqual(briefing_excerpt("", ["x1"]), {"title": "", "lead": "", "snippet": ""})


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def list_public_projects(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            result={
                "total": 42,
                "items": [{
                    "full_name": "feder-cr/dots",
                    "url": "https://github.com/feder-cr/dots",
                    "description": "Web agent",
                    "description_zh": "网页智能体",
                    "description_en": None,
                    "stars": 1806,
                    "language": "Rust",
                    "hot_score": 1.0,
                }],
            },
            effective_sort="relevance",
        )


class FakeDocuments:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def search_document_page(self, query: str, *, source: str | None = None, page: int = 1, page_size: int = 20):
        self.calls.append((query, source, page_size))
        if source == "arxiv":
            return {"total": 7, "items": [{
                "id": "paper-1",
                "title": "DSec",
                "summary": "沙盒 " * 200,
                "published_date": "2026-04-23T14:22:42",
                "authors": '["A", "B", "C", "D"]',
                "tags": "[]",
            }]}
        return {"total": 3, "items": [
            {"id": "tweet-1", "title": "t", "summary": "We just released it", "url": "https://x.com/deepseek_ai/status/1", "published_date": "2026-10-02"},
            {"id": "tweet-2", "title": "t", "summary": "odd", "url": "javascript:alert(1)", "published_date": "2026-10-02"},
        ]}


class FakeBriefings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search_briefings(self, terms: list[str], *, locale: str, limit: int = 5, exclude_suffixes: tuple[str, ...] = ()):
        self.calls.append({"terms": terms, "locale": locale, "limit": limit, "exclude_suffixes": exclude_suffixes})
        return {"total": 4, "items": [
            {"id": 11, "date": "2026-10-01_github", "body": BRIEFING},
            {"id": 10, "date": "2026-10-01_0800_x", "body": BRIEFING},
            {"id": 9, "date": "2026-10-01_retired", "body": BRIEFING},
        ]}


class QuickSearchServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_groups_reuse_each_existing_search_and_shape_rows(self) -> None:
        catalog, documents, briefings = FakeCatalog(), FakeDocuments(), FakeBriefings()

        result = await quick_search(
            "magpie agent", limit=5, locale="en-US",
            catalog=catalog, documents=documents, briefings=briefings, include_tweets=True,
        )

        self.assertEqual(list(result["groups"]), ["projects", "papers", "briefings", "tweets"])
        self.assertEqual(result["q"], "magpie agent")
        self.assertEqual(result["failed"], [])
        self.assertEqual(catalog.calls, [{
            "scope": "all", "category": "", "subcategory": "", "q": "magpie agent", "language": "",
            "page": 1, "page_size": 5, "sort": None, "user_id": None,
        }])
        self.assertEqual(sorted(documents.calls), [("magpie agent", "arxiv", 5), ("magpie agent", "x", 5)])
        self.assertEqual(briefings.calls, [{"terms": ["magpie", "agent"], "locale": "en", "limit": 5, "exclude_suffixes": ()}])

        self.assertEqual(result["groups"]["projects"], {"total": 42, "items": [{
            "full_name": "feder-cr/dots", "url": "https://github.com/feder-cr/dots",
            "description": "Web agent", "description_zh": "网页智能体", "description_en": "",
            "stars": 1806, "language": "Rust",
        }]})
        paper = result["groups"]["papers"]["items"][0]
        self.assertEqual(result["groups"]["papers"]["total"], 7)
        self.assertEqual((paper["id"], paper["title"], paper["date"]), ("paper-1", "DSec", "2026-04-23"))
        self.assertEqual((paper["authors"], paper["author_count"]), (["A", "B", "C"], 4))
        self.assertTrue(paper["summary"].endswith("…") and len(paper["summary"]) <= 160)

        # 期键反查简报种类；认不出的后缀不出现
        self.assertEqual(
            [(item["id"], item["date"], item["type"], item["lead"]) for item in result["groups"]["briefings"]["items"]],
            [(11, "2026-10-01", "github", "magpie"), (10, "2026-10-01", "x", "magpie")],
        )
        self.assertEqual(result["groups"]["briefings"]["total"], 4)
        # 推文作者取自地址；不是网页地址的不给链接
        self.assertEqual(result["groups"]["tweets"]["items"], [
            {"id": "tweet-1", "text": "We just released it", "url": "https://x.com/deepseek_ai/status/1", "author": "deepseek_ai", "date": "2026-10-02"},
            {"id": "tweet-2", "text": "odd", "url": "", "author": "", "date": "2026-10-02"},
        ])

    async def test_without_x_there_is_no_tweet_group_and_x_briefings_are_excluded(self) -> None:
        documents, briefings = FakeDocuments(), FakeBriefings()

        result = await quick_search(
            "agent", limit=3, locale="zh-CN",
            catalog=FakeCatalog(), documents=documents, briefings=briefings, include_tweets=False,
        )

        self.assertEqual(list(result["groups"]), ["projects", "papers", "briefings"])
        self.assertEqual(documents.calls, [("agent", "arxiv", 3)])
        self.assertEqual(briefings.calls[0]["exclude_suffixes"], ("_0800_x",))
        self.assertEqual(briefings.calls[0]["locale"], "zh-CN")

    async def test_a_failing_group_is_reported_and_the_rest_still_return(self) -> None:
        catalog = FakeCatalog()
        catalog.list_public_projects = MagicMock(side_effect=RuntimeError("catalog down"))  # type: ignore[method-assign]
        briefings = FakeBriefings()

        with self.assertLogs("backend.app.services.search.quick_search", level="WARNING"):
            result = await quick_search(
                "agent", limit=5, locale="zh-CN",
                catalog=catalog, documents=FakeDocuments(), briefings=briefings, include_tweets=True,
            )

        self.assertEqual(result["failed"], ["projects"])
        self.assertEqual(list(result["groups"]), ["papers", "briefings", "tweets"])

    async def test_queries_without_usable_terms_skip_the_briefing_lookup(self) -> None:
        briefings = FakeBriefings()

        result = await quick_search(
            "a", limit=5, locale="zh-CN",
            catalog=FakeCatalog(), documents=FakeDocuments(), briefings=briefings, include_tweets=False,
        )

        self.assertEqual(result["groups"]["briefings"], {"total": 0, "items": []})
        self.assertEqual(briefings.calls, [])


class QuickSearchRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.app.dependency_overrides[RequireUser] = lambda: {"user_id": 42}
        self.documents = FakeDocuments()
        self.briefings = FakeBriefings()
        self.app.dependency_overrides[get_project_catalog_query_service] = FakeCatalog
        self.app.dependency_overrides[get_document_repository] = lambda: self.documents
        self.app.dependency_overrides[get_briefing_repository] = lambda: self.briefings
        self.client = TestClient(self.app)

    def test_normalizes_the_query_and_follows_the_x_switch(self) -> None:
        with patch.object(settings, "x_source_enabled", True):
            body = self.client.get("/api/search", params={"q": "  ｍagpie　 agent ", "limit": 2, "locale": "en"}).json()
        self.assertEqual(body["q"], "magpie agent")
        self.assertEqual(list(body["groups"]), ["projects", "papers", "briefings", "tweets"])
        self.assertEqual(self.briefings.calls[-1]["locale"], "en")

        with patch.object(settings, "x_source_enabled", False):
            body = self.client.get("/api/search", params={"q": "agent"}).json()
        self.assertNotIn("tweets", body["groups"])
        self.assertEqual(self.briefings.calls[-1]["exclude_suffixes"], ("_0800_x",))
        self.assertEqual(self.briefings.calls[-1]["limit"], 5)

    def test_rejects_blank_long_or_out_of_range_requests(self) -> None:
        self.assertEqual(self.client.get("/api/search", params={"q": " 　 "}).status_code, 422)
        self.assertEqual(self.client.get("/api/search").status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": "x" * 121}).status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": "agent", "limit": 9}).status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": "agent", "limit": 0}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
