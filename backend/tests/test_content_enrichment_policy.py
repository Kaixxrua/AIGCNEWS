from __future__ import annotations

import unittest

from backend.app.services.ingestion.content_enrichment_policy import (
    MAX_CONTENT_CHARS,
    clean_html_text,
    compose_huggingface_content,
    compose_producthunt_content,
    select_github_content,
    select_hackernews_content,
    select_news_content,
)


class ContentEnrichmentHtmlPolicyTests(unittest.TestCase):
    def test_clean_html_text_removes_exact_noise_tags_and_blank_lines(self) -> None:
        html = """
        <html><head><style>hidden</style><script>bad()</script></head>
        <body>
          <header>Header</header><nav>Navigation</nav>
          <main><h1>Title</h1><p>First <strong>paragraph</strong>.</p>\n\n<p>Second.</p></main>
          <aside>Aside</aside><form>Form</form><button>Button</button>
          <noscript>No script</noscript><iframe>Frame</iframe><footer>Footer</footer>
        </body></html>
        """

        self.assertEqual(
            clean_html_text(html),
            "Title\nFirst\nparagraph\n.\nSecond.",
        )


class ContentEnrichmentSourcePolicyTests(unittest.TestCase):
    def test_huggingface_preserves_metadata_format_fallback_and_update(self) -> None:
        result = compose_huggingface_content(
            {
                "title": "Model",
                "pipeline_tag": "text-generation",
                "likes": 1234,
                "downloads": 56789,
                "summary": "Model summary",
            }
        )

        self.assertEqual(
            result.full_text,
            "# Model\n\nPipeline: text-generation | Likes: 1,234 | Downloads: 56,789\n\nModel summary",
        )
        self.assertFalse(result.pdf_pending)
        self.assertEqual(
            compose_huggingface_content({"title": "Title only"}).full_text,
            "# Title only",
        )

    def test_github_uses_abstract_only_above_500_and_requests_valid_name(self) -> None:
        self.assertEqual(
            select_github_content({"abstract": "a" * 501}).full_text,
            "a" * 501,
        )

        boundary = {
            "title": "owner/repo",
            "abstract": "a" * 500,
            "description": "Description",
        }
        request = select_github_content(boundary)
        self.assertEqual(request.fetch_github_readme, "owner/repo")
        self.assertEqual(request.full_text, "")
        self.assertEqual(
            select_github_content(boundary, "README body").full_text,
            "Description\n\nREADME:\nREADME body",
        )
        self.assertEqual(
            select_github_content(
                {"title": "not-a-full-name", "summary": "Summary"}
            ).full_text,
            "Summary",
        )

    def test_news_requests_url_and_preserves_strict_relative_threshold(self) -> None:
        paper = {
            "title": "News",
            "url": "https://public.example.test/news",
            "summary": "s" * 20,
        }
        self.assertEqual(select_news_content(paper).fetch_url, paper["url"])
        self.assertEqual(
            select_news_content(paper, "p" * 221).full_text,
            f"# News\n\n{'p' * 221}",
        )
        self.assertEqual(
            select_news_content(paper, "p" * 220).full_text,
            f"# News\n\n{'s' * 20}",
        )
        self.assertEqual(
            select_news_content({"title": "Title only"}).full_text,
            "Title only",
        )

    def test_producthunt_preserves_abstract_summary_and_title_fallbacks(self) -> None:
        self.assertEqual(
            compose_producthunt_content(
                {"title": "Launch", "abstract": "Description"}
            ).full_text,
            "# Launch\n\nDescription",
        )
        self.assertEqual(
            compose_producthunt_content(
                {"title": "Launch", "summary": "Description"}
            ).full_text,
            "# Launch\n\nDescription",
        )
        self.assertEqual(
            compose_producthunt_content({"title": "Launch only"}).full_text,
            "Launch only",
        )

    def test_hackernews_requests_external_and_preserves_strict_threshold(self) -> None:
        paper = {
            "title": "Story",
            "url": "https://public.example.test/story",
            "abstract": "Story text",
        }
        self.assertEqual(select_hackernews_content(paper).fetch_url, paper["url"])
        self.assertEqual(
            select_hackernews_content(paper, "p" * 201).full_text,
            f"# Story\n\n{'p' * 201}",
        )
        self.assertEqual(
            select_hackernews_content(paper, "p" * 200).full_text,
            "# Story\n\nStory text",
        )

        internal = {
            "title": "Ask HN",
            "hn_id": "42",
            "url": "https://news.ycombinator.com/item?id=42",
            "summary": "Question body",
        }
        self.assertEqual(
            select_hackernews_content(internal).full_text,
            "# Ask HN\n\nQuestion body",
        )
        self.assertEqual(
            select_hackernews_content(
                {"title": "Same", "abstract": "Same"}
            ).full_text,
            "Same",
        )

    def test_all_five_source_policies_truncate_to_existing_limit(self) -> None:
        results = [
            compose_huggingface_content({"abstract": "x" * (MAX_CONTENT_CHARS + 1)}),
            select_github_content({"abstract": "x" * (MAX_CONTENT_CHARS + 1)}),
            select_news_content(
                {"title": "T", "summary": "x" * (MAX_CONTENT_CHARS + 1)}
            ),
            compose_producthunt_content(
                {"title": "T", "abstract": "x" * (MAX_CONTENT_CHARS + 1)}
            ),
            select_hackernews_content(
                {"title": "T", "abstract": "x" * (MAX_CONTENT_CHARS + 1)}
            ),
        ]

        self.assertTrue(all(len(result.full_text) == MAX_CONTENT_CHARS for result in results))

    def test_policy_evaluation_does_not_mutate_input_mapping(self) -> None:
        paper = {
            "title": "owner/repo",
            "description": "Description",
        }
        before = dict(paper)

        select_github_content(paper, "README")

        self.assertEqual(paper, before)


if __name__ == "__main__":
    unittest.main()
