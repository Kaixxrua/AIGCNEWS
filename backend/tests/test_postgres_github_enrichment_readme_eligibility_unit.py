from __future__ import annotations

"""README-aware 富化准入契约：description 或成功 README 快照即可进入标准队列。

覆盖用户报告的缺口：GitHub 原始 description 为空但 README 有内容的仓库
必须被标准自动富化处理；已确认 404（availability_status='not_found'）的仓库
不得出现在「无法富化」名单。
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.postgres_project_enrichment_repository import (
    _GITHUB_ENRICHMENT_INPUT_SQL,
    PostgresGitHubProjectEnrichmentRepository,
    _has_github_enrichment_input,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = cursor
        self.connection.cursor.return_value = context

    @contextmanager
    def transaction(self):
        yield self.connection


class TestHasGithubEnrichmentInput:
    def test_description_only_repo_is_eligible(self) -> None:
        assert _has_github_enrichment_input({"description": "Agent framework"}) is True

    def test_readme_only_repo_is_eligible(self) -> None:
        # 用户报告的形态：没有 GitHub description，但有 README，必须可富化
        row = {
            "description": "",
            "readme_status": "succeeded",
            "readme_text": "Awesome QAI Papers list with many references",
        }
        assert _has_github_enrichment_input(row) is True

    def test_both_empty_is_not_eligible(self) -> None:
        row = {"description": "", "readme_status": "", "readme_text": ""}
        assert _has_github_enrichment_input(row) is False

    def test_non_succeeded_readme_does_not_unlock_enrichment(self) -> None:
        # pending/failed/rate_limited/not_found 或清洗后为空的 README 都不是输入
        for status in ("pending", "failed", "rate_limited", "not_found", "not_modified"):
            row = {"description": "", "readme_status": status, "readme_text": "content"}
            assert _has_github_enrichment_input(row) is False, status
        blank = {"description": "", "readme_status": "succeeded", "readme_text": "   "}
        assert _has_github_enrichment_input(blank) is False

    def test_whitespace_only_description_falls_back_to_readme(self) -> None:
        row = {
            "description": "   ",
            "readme_status": "succeeded",
            "readme_text": "real README body",
        }
        assert _has_github_enrichment_input(row) is True


class TestEnrichmentInputSqlShape:
    def test_sql_predicate_matches_python_helper(self) -> None:
        # SQL 与 _has_github_enrichment_input 同构：同一个 OR 结构，
        # 同一 BTRIM 空白语义，同一 readme_status='succeeded' 门槛
        assert "BTRIM(COALESCE(c.description, '')) <> ''" in _GITHUB_ENRICHMENT_INPUT_SQL
        assert "ss.readme_status = 'succeeded'" in _GITHUB_ENRICHMENT_INPUT_SQL
        assert "BTRIM(COALESCE(ss.readme_text, '')) <> ''" in _GITHUB_ENRICHMENT_INPUT_SQL
        assert _GITHUB_ENRICHMENT_INPUT_SQL.count("OR") == 1


class TestUnprocessableCteFilters:
    def _status_sql(self) -> str:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "eligible": 0,
                "succeeded": 0,
                "failed": 0,
            },
            {"count": 0},
        ]
        cursor.fetchall.return_value = []
        repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]
        repository.get_github_project_enrichment_status(min_stars=500)
        return "\n".join(str(call.args[0]) for call in cursor.execute.call_args_list)

    def test_unprocessable_excludes_repos_with_usable_readme(self) -> None:
        sql = self._status_sql()
        # unprocessable 仅保留：description 空 + 无有效 README + 未成功富化
        assert "BTRIM(COALESCE(c.description, '')) = ''" in sql
        assert "ss.readme_status = 'succeeded'" in sql
        assert "BTRIM(COALESCE(ss.readme_text, '')) <> ''" in sql
        assert "e.status IS DISTINCT FROM 'succeeded'" in sql

    def test_unprocessable_excludes_not_found_repos(self) -> None:
        # 已 2 次 404 确认的仓库（如 QAI-brain/awesome-QAI-Papers-QDiffusion）
        # 不得进入无法富化计数/列表；公共 catalog 保留它们不受影响
        sql = self._status_sql()
        assert "c.availability_status = 'active'" in sql

    def test_reason_label_kept_for_frontend_contract(self) -> None:
        sql = self._status_sql()
        assert "missing_description" in sql
