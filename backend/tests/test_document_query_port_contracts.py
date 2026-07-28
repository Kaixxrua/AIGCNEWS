from __future__ import annotations

import asyncio
import re
import sys
import types
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request


# Keep this contract file isolated from runtime model/database configuration and .env.
config_module = types.ModuleType("backend.app.core.config")
config_module.settings = types.SimpleNamespace(
    mcp_github_fallback_enabled=False,
    mcp_github_fallback_use_token=False,
    mcp_github_fallback_timeout_seconds=8.0,
    project_semantic_search_enabled=False,
    project_semantic_query_timeout_seconds=1.5,
    github_token="",
    ACCESS_TOKEN_EXPIRE_MINUTES=60,
    JWT_SECRET_KEY="test-secret",
    JWT_ALGORITHM="HS256",
    SMTP_HOST="",
    SMTP_PORT=587,
    SMTP_USERNAME="",
    SMTP_PASSWORD="",
    SMTP_FROM_EMAIL="",
    SMTP_FROM_NAME="",
    SMTP_USE_TLS=True,
)
sys.modules.setdefault("backend.app.core.config", config_module)

model_factory_module = types.ModuleType("backend.app.core.model_factory")
model_factory_module.get_chat_model = MagicMock
model_factory_module.get_embedding_model = MagicMock
sys.modules.setdefault("backend.app.core.model_factory", model_factory_module)

mysql_module = types.ModuleType("backend.app.repositories.mysql_repo")


class _RepositoryPlaceholder:
    pass


mysql_module.MySQLRepository = _RepositoryPlaceholder
sys.modules.setdefault("backend.app.repositories.mysql_repo", mysql_module)

for module_name, class_name in (
    ("backend.app.repositories.graph_repo", "GraphRepository"),
    ("backend.app.repositories.milvus_repo", "MilvusRepository"),
):
    module = types.ModuleType(module_name)
    setattr(module, class_name, type(class_name, (), {}))
    sys.modules.setdefault(module_name, module)

from backend.app.api import routes_mcp
from backend.app.services.rag import database_tools
from backend.app.services.rag.retriever import HybridRetriever


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.split())


def _query_fixture(*, rows=(), source_counts=None):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = list(rows)
    connection = MagicMock()
    connection.cursor.return_value = cursor
    repository = MagicMock()
    repository._connect.return_value = connection
    repository.documents.get_source_counts.return_value = source_counts or {}
    return repository, connection, cursor


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


def test_mysql_id_match_binds_ids_twice_to_preserve_caller_order() -> None:
    first = "abcdef0123456789abcdef0123456789"
    second = "0123456789abcdef0123456789abcdef"
    repository, connection, cursor = _query_fixture()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._mysql_repo = repository

    assert retriever._mysql_id_match_documents(f"{first} {second} {first}", top_k=4) == []

    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    assert "WHERE id IN (%s, %s)" in normalized
    assert "ORDER BY FIELD(id, %s, %s) LIMIT %s" in normalized
    assert params == (first, second, first, second, 4)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_mysql_id_match_with_no_id_does_not_open_database_connection() -> None:
    repository = MagicMock()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._mysql_repo = repository

    assert retriever._mysql_id_match_documents("explain this paper") == []
    repository._connect.assert_not_called()


def test_mysql_title_match_filters_deduplicates_caps_and_binds_wildcards() -> None:
    repository, connection, cursor = _query_fixture()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._mysql_repo = repository
    query = (
        "The alpha ALPHA b beta and gamma delta epsilon zeta eta theta "
        "iota kappa"
    )

    assert retriever._mysql_title_match_documents(query, top_k=6) == []

    expected_tokens = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    wildcards = tuple(f"%{token}%" for token in expected_tokens)
    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    assert normalized.count("(LOWER(title) LIKE %s)") == 8
    assert "WHERE (LOWER(title) LIKE %s OR LOWER(title) LIKE %s" in normalized
    assert "HAVING keyword_score >= %s" in normalized
    assert (
        "ORDER BY keyword_score DESC, CASE WHEN source = 'arxiv' THEN 0 ELSE 1 END ASC, "
        "COALESCE(raw_score, score, 0) DESC, published_date DESC LIMIT %s"
    ) in normalized
    assert params == wildcards + wildcards + (3, 6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_mysql_title_match_requires_three_filtered_tokens() -> None:
    repository = MagicMock()
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever._mysql_repo = repository

    assert retriever._mysql_title_match_documents("the alpha and beta b") == []
    repository._connect.assert_not_called()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is not None
        assert tz.utcoffset(None) == timedelta(hours=8)
        return cls(2026, 7, 28, 9, 30, tzinfo=tz)


@pytest.mark.parametrize(
    ("source", "expected_where", "expected_params"),
    [
        ("all", "WHERE LEFT(created_at, 10) = %s", ("2026-07-28", 5)),
        (
            "github",
            "WHERE LEFT(created_at, 10) = %s AND source = %s",
            ("2026-07-28", "github", 5),
        ),
    ],
)
def test_ranking_uses_cst_date_source_scope_and_stable_order(
    source: str, expected_where: str, expected_params: tuple[object, ...]
) -> None:
    repository, connection, cursor = _query_fixture()
    with (
        patch.object(database_tools, "datetime", _FixedDateTime),
        patch.object(mysql_module, "MySQLRepository", return_value=repository),
    ):
        result = database_tools.execute_query_ranking(source=source, period="weekly", limit=5)

    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    assert expected_where in normalized
    if source == "all":
        assert "source = %s" not in normalized
    assert "ORDER BY raw_score DESC, rank_in_period ASC LIMIT %s" in normalized
    assert params == expected_params
    assert result["docs"] == []
    assert result["count"] == 0
    assert "周榜排行（2026-07-28，共 0 条）" in result["formatted"]
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


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
    calls = []
    results = []
    for period in ("daily", "monthly"):
        repository, _, cursor = _query_fixture(rows=[row])
        with (
            patch.object(database_tools, "datetime", _FixedDateTime),
            patch.object(mysql_module, "MySQLRepository", return_value=repository),
        ):
            results.append(database_tools.execute_query_ranking(period=period, limit=3))
        calls.append((_normalized_sql(cursor.execute.call_args.args[0]), cursor.execute.call_args.args[1]))

    assert calls[0] == calls[1]
    assert results[0]["docs"] == results[1]["docs"] == [row]
    assert "日榜排行" in results[0]["formatted"]
    assert "月榜排行" in results[1]["formatted"]
    assert "第2名 [github] Project (Stars: 12)" in results[0]["formatted"]


@pytest.mark.parametrize(
    ("source", "expected_where", "expected_params"),
    [
        ("all", "FROM documents ORDER BY", (7,)),
        ("news", "FROM documents WHERE source = %s ORDER BY", ("news", 7)),
    ],
)
def test_knowledge_stats_uses_logical_counts_source_scope_and_stable_order(
    source: str, expected_where: str, expected_params: tuple[object, ...]
) -> None:
    counts = {"news": 3, "github": 5, "arxiv": 2}
    repository, connection, cursor = _query_fixture(source_counts=counts)
    with patch.object(mysql_module, "MySQLRepository", return_value=repository):
        result = database_tools.execute_query_knowledge_stats(source=source, limit=7)

    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    assert expected_where in normalized
    assert "ORDER BY raw_score DESC, created_at DESC LIMIT %s" in normalized
    assert params == expected_params
    assert result["docs"] == []
    assert result["source_counts"] == counts
    assert result["total"] == 10
    assert "知识库总文档数: 10" in result["formatted"]
    assert result["formatted"].index("github: 5 条") < result["formatted"].index("news: 3 条")
    assert result["formatted"].index("news: 3 条") < result["formatted"].index("arxiv: 2 条")
    if source == "news":
        assert "news 来源共 3 条，以下按热度排序前 7 条" in result["formatted"]
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_mcp_paper_detail_uses_exact_id_and_public_projection() -> None:
    repository, connection, cursor = _query_fixture()
    cursor.fetchone.return_value = {
        "id": "paper-1",
        "source": "arxiv",
        "title": "Paper",
        "published_date": date(2026, 7, 27),
        "local_pdf_path": "/srv/papers/paper-1.pdf",
    }
    with patch.object(routes_mcp, "MySQLRepository", return_value=repository):
        result = asyncio.run(
            routes_mcp._tool_get_paper_detail(
                _request(forwarded_proto="https"), {"paper_id": "paper-1"}
            )
        )

    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    assert "FROM documents WHERE id = %s LIMIT 1" in normalized
    assert params == ("paper-1",)
    assert result == {
        "item": {
            "id": "paper-1",
            "source": "arxiv",
            "title": "Paper",
            "published_date": "2026-07-27",
            "pdf_media_url": "https://testserver/api/media/papers/paper-1.pdf",
        }
    }
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_mcp_paper_detail_reports_missing_document() -> None:
    repository, connection, cursor = _query_fixture()
    cursor.fetchone.return_value = None
    with (
        patch.object(routes_mcp, "MySQLRepository", return_value=repository),
        pytest.raises(routes_mcp.McpToolInputError, match=re.escape("Document 'missing' not found.")),
    ):
        asyncio.run(routes_mcp._tool_get_paper_detail(_request(), {"paper_id": "missing"}))

    assert cursor.execute.call_args.args[1] == ("missing",)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
