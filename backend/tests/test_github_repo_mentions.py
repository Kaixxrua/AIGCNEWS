from __future__ import annotations

import unittest

from backend.app.repositories.postgres_document_repository import (
    extract_github_repo_slugs,
)


class ExtractGithubRepoSlugsTests(unittest.TestCase):
    def test_extracts_from_url_and_normalizes_case(self) -> None:
        self.assertEqual(
            extract_github_repo_slugs("https://github.com/Owner/Repo"),
            {"owner/repo"},
        )

    def test_extracts_from_text_and_strips_trailing_punctuation(self) -> None:
        text = "Show HN: https://github.com/foo/bar, plus github.com/baz/qux."
        self.assertEqual(extract_github_repo_slugs(text), {"foo/bar", "baz/qux"})

    def test_keeps_only_first_two_path_segments(self) -> None:
        self.assertEqual(
            extract_github_repo_slugs("https://github.com/owner/repo/issues/123"),
            {"owner/repo"},
        )

    def test_filters_non_repo_owner_paths(self) -> None:
        self.assertEqual(
            extract_github_repo_slugs(
                "https://github.com/trending https://github.com/apps/dependabot"
            ),
            set(),
        )

    def test_ignores_empty_and_non_github_text(self) -> None:
        self.assertEqual(extract_github_repo_slugs(None, "", "no link here"), set())

    def test_dedupes_across_texts(self) -> None:
        self.assertEqual(
            extract_github_repo_slugs(
                "github.com/a/b", "see https://github.com/A/B for details"
            ),
            {"a/b"},
        )


if __name__ == "__main__":
    unittest.main()
