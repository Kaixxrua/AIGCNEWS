from __future__ import annotations

import ast
import asyncio
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from backend.app.services.mcp.inbound import tools as inbound_tools
from backend.app.services.rag import database_tools
from backend.app.services.rag.retriever import HybridRetriever

TARGETED_DOCUMENT_CONSUMERS = (
    Path(__file__).parents[1] / "app/services/rag/retriever.py",
    Path(__file__).parents[1] / "app/services/rag/database_tools.py",
    Path(__file__).parents[1] / "app/api/routes_mcp.py",
)


def test_document_query_consumers_use_ports_without_sql_or_mysql_facade() -> None:
    sql_keywords = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
    for path in TARGETED_DOCUMENT_CONSUMERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        assert "backend.app.repositories.mysql_repo" not in imported_names
        assert "MySQLRepository" not in imported_names
        assert "_connect" not in called_attributes
        assert not any(sql_keywords.search(value) for value in string_literals)


def _request(*, forwarded_proto: str | None = None) -> Request:
    headers = []
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/api/mcp",
            "root_path": "",
            "query_string": b"",
            "headers": headers,
        }
    )


def test_explicit_document_ids_are_lowercase_deduplicated_in_caller_order() -> None:
    first = "ABCDEF0123456789ABCDEF0123456789"
    second = "0123456789abcdef0123456789abcdef"

    assert HybridRetriever._extract_explicit_document_ids(
        f"open {first}, then {second}, then {first.lower()}"
    ) == [first.lower(), second]
    assert HybridRetriever._extract_explicit_document_ids("") == []
    assert HybridRetriever._extract_explicit_document_ids("no document id") == []


def test_id_match_delegates_ordered_ids_and_preserves_langchain_projection() -> None:
    first = "abcdef0123456789abcdef0123456789"
    second = "0123456789abcdef0123456789abcdef"
    reader = MagicMock()
    reader.get_documents_by_ids.return_value = [
        {
            "id": first,
            "source": "arxiv",
            "title": "Paper",
            "summary": "Summary",
            "score": 1.5,
            "raw_score": 2.5,
            "rank_in_period": 2,
        }
    ]
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._document_retrieval = reader

    docs = retriever._documents_id_match(f"{first} {second} {first}", top_k=4)

    reader.get_documents_by_ids.assert_called_once_with([first, second], limit=4)
    assert docs[0].page_content == f"Document ID: {first}\nTitle: Paper\nSummary (metadata excerpt): Summary"
    assert docs[0].metadata["match_type"] == "documents_id"
    assert docs[0].metadata["force_include"] is True


def test_id_match_with_no_id_does_not_call_reader() -> None:
    reader = MagicMock()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._document_retrieval = reader

    assert retriever._documents_id_match("explain this paper") == []
    reader.get_documents_by_ids.assert_not_called()


def test_title_match_filters_deduplicates_caps_and_delegates_tokens() -> None:
    reader = MagicMock()
    reader.get_documents_by_title_tokens.return_value = [
        {
            "id": "doc-1",
            "source": "news",
            "title": "Alpha Beta Gamma",
            "summary": "Summary",
            "keyword_score": 4,
        }
    ]
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._document_retrieval = reader
    query = (
        "The alpha ALPHA b beta and gamma delta epsilon zeta eta theta "
        "iota kappa"
    )

    docs = retriever._documents_title_match(query, top_k=6)

    expected_tokens = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    reader.get_documents_by_title_tokens.assert_called_once_with(
        expected_tokens, min_matches=3, limit=6
    )
    assert docs[0].page_content == "Title: Alpha Beta Gamma\nSummary (metadata excerpt): Summary"
    assert docs[0].metadata["match_type"] == "documents_title"
    assert docs[0].metadata["keyword_score"] == 4.0


def test_title_match_requires_three_filtered_tokens() -> None:
    reader = MagicMock()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._document_retrieval = reader

    assert retriever._documents_title_match("the alpha and beta b") == []
    reader.get_documents_by_title_tokens.assert_not_called()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is not None
        assert tz.utcoffset(None) == timedelta(hours=8)
        return cls(2026, 7, 28, 9, 30, tzinfo=tz)


@pytest.mark.parametrize(("source", "reader_source"), [("all", None), ("github", "github")])
def test_ranking_uses_reader_source_scope_and_cst_label(
    source: str, reader_source: str | None
) -> None:
    reader = MagicMock()
    reader.get_today_ranked_documents.return_value = []
    with patch.object(database_tools, "datetime", _FixedDateTime):
        result = database_tools.execute_query_ranking(
            source=source, period="weekly", limit=5, ranking_reader=reader
        )

    reader.get_today_ranked_documents.assert_called_once_with(limit=5, source=reader_source)
    assert result["docs"] == []
    assert result["count"] == 0
    assert "周榜排行（2026-07-28，共 0 条）" in result["formatted"]


def test_ranking_period_is_presentation_only_and_preserves_rows() -> None:
    row = {
        "id": "doc-1",
        "source": "github",
        "title": "Project",
        "url": "https://example.test/project",
        "summary": "summary",
        "raw_score": 12,
        "rank_in_period": 2,
    }
    reader = MagicMock()
    reader.get_today_ranked_documents.return_value = [row]
    results = []
    for period in ("daily", "monthly"):
        with patch.object(database_tools, "datetime", _FixedDateTime):
            results.append(
                database_tools.execute_query_ranking(
                    period=period, limit=3, ranking_reader=reader
                )
            )

    assert reader.get_today_ranked_documents.call_args_list[0] == reader.get_today_ranked_documents.call_args_list[1]
    assert results[0]["docs"] == results[1]["docs"] == [row]
    assert "日榜排行" in results[0]["formatted"]
    assert "月榜排行" in results[1]["formatted"]
    assert "第2名 [github] Project (Stars: 12)" in results[0]["formatted"]


@pytest.mark.parametrize(("source", "reader_source"), [("all", None), ("news", "news")])
def test_knowledge_stats_uses_logical_counts_and_reader_source_scope(
    source: str, reader_source: str | None
) -> None:
    counts = {"news": 3, "github": 5, "arxiv": 2}
    ranking_reader = MagicMock()
    ranking_reader.get_knowledge_ranked_documents.return_value = []
    statistics_reader = MagicMock()
    statistics_reader.get_source_counts.return_value = counts
    result = database_tools.execute_query_knowledge_stats(
        source=source,
        limit=7,
        ranking_reader=ranking_reader,
        statistics_reader=statistics_reader,
    )

    ranking_reader.get_knowledge_ranked_documents.assert_called_once_with(
        limit=7, source=reader_source
    )
    statistics_reader.get_source_counts.assert_called_once_with()
    assert result["docs"] == []
    assert result["source_counts"] == counts
    assert result["total"] == 10
    assert "知识库总文档数: 10" in result["formatted"]
    assert result["formatted"].index("github: 5 条") < result["formatted"].index("news: 3 条")
    assert result["formatted"].index("news: 3 条") < result["formatted"].index("arxiv: 2 条")
    if source == "news":
        assert "news 来源共 3 条，以下按热度排序前 7 条" in result["formatted"]


def _mcp_tool_context(*, forwarded_proto: str | None = None):
    return inbound_tools.McpToolContext(
        user=None,
        documents=MagicMock(),
        papers=MagicMock(),
        rank_snapshots=MagicMock(),
        project_collection=MagicMock(),
        request=_request(forwarded_proto=forwarded_proto),
    )


def test_mcp_paper_detail_uses_reader_and_public_projection() -> None:
    repository = MagicMock()
    repository.get_paper_detail.return_value = {
        "id": "paper-1",
        "source": "arxiv",
        "title": "Paper",
        "published_date": date(2026, 7, 27),
        "local_pdf_path": "/srv/papers/paper-1.pdf",
    }
    result = asyncio.run(
        inbound_tools._tool_get_paper_detail(
            _mcp_tool_context(forwarded_proto="https"),
            {"paper_id": "paper-1"},
            repository,
        )
    )

    repository.get_paper_detail.assert_called_once_with("paper-1")
    assert result == {
        "item": {
            "id": "paper-1",
            "source": "arxiv",
            "title": "Paper",
            "published_date": "2026-07-27",
            "pdf_media_url": "https://testserver/api/media/papers/paper-1.pdf",
        }
    }


def test_mcp_paper_detail_reports_missing_document() -> None:
    repository = MagicMock()
    repository.get_paper_detail.return_value = None
    with pytest.raises(
        inbound_tools.McpToolInputError,
        match=re.escape("Document 'missing' not found."),
    ):
        asyncio.run(
            inbound_tools._tool_get_paper_detail(
                _mcp_tool_context(), {"paper_id": "missing"}, repository
            )
        )

    repository.get_paper_detail.assert_called_once_with("missing")
