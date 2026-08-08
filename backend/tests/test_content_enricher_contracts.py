from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.services.ingestion import content_enricher, content_fetch_port
from backend.app.services.ingestion.content_fetch_port import DEFAULT_PAGE_HEADERS


class _AsyncClient:
    def __init__(self, response: object = None, error: Exception | None = None, **kwargs: object):
        self.response = response
        self.error = error
        self.kwargs = kwargs
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> object:
        self.requested_urls.append(url)
        if self.error is not None:
            raise self.error
        return self.response


class ContentEnricherHtmlAndFetchContractTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_html_text_removes_noise_and_collapses_blank_lines(self) -> None:
        html = """
        <html><head><style>.hidden { display: none; }</style><script>bad()</script></head>
        <body>
          <header>Header noise</header><nav>Navigation</nav>
          <main><h1>Title</h1><p>First <strong>paragraph</strong>.</p>\n\n<p>Second.</p></main>
          <aside>Aside noise</aside><form>Form noise</form><button>Button noise</button>
          <noscript>No script noise</noscript><iframe>Frame noise</iframe><footer>Footer noise</footer>
        </body></html>
        """

        self.assertEqual(
            content_enricher._clean_html_text(html),
            "Title\nFirst\nparagraph\n.\nSecond.",
        )

    async def test_fetch_url_text_rejects_missing_and_non_http_urls_without_client(self) -> None:
        with patch.object(content_fetch_port.httpx, "AsyncClient") as client:
            self.assertEqual(await content_enricher._fetch_url_text(""), "")
            self.assertEqual(await content_enricher._fetch_url_text("ftp://example.test/a"), "")
        client.assert_not_called()

    async def test_fetch_url_text_uses_current_url_options_and_accepts_html_or_text(self) -> None:
        for content_type in ("text/html; charset=utf-8", "text/plain"):
            with self.subTest(content_type=content_type):
                response = MagicMock()
                response.headers = {"content-type": content_type}
                response.text = "<main><p>Body</p></main>"
                client = _AsyncClient(response=response)
                with patch.object(content_fetch_port.httpx, "AsyncClient", return_value=client) as factory:
                    result = await content_enricher._fetch_url_text(
                        "https://public.example.test/current", timeout=7
                    )

                self.assertEqual(result, "Body")
                self.assertEqual(client.requested_urls, ["https://public.example.test/current"])
                factory.assert_called_once_with(
                    timeout=7,
                    follow_redirects=True,
                    headers=DEFAULT_PAGE_HEADERS,
                    trust_env=True,
                )
                response.raise_for_status.assert_called_once_with()

    async def test_fetch_url_text_rejects_other_content_types_and_swallows_fetch_errors(self) -> None:
        response = MagicMock()
        response.headers = {"content-type": "application/json"}
        response.text = '<p>Not page text</p>'
        with patch.object(
            content_fetch_port.httpx,
            "AsyncClient",
            return_value=_AsyncClient(response=response),
        ):
            self.assertEqual(
                await content_enricher._fetch_url_text("https://public.example.test/data"),
                "",
            )

        for error in (httpx.HTTPError("network failed"), RuntimeError("client failed")):
            with self.subTest(error=type(error).__name__):
                with patch.object(
                    content_fetch_port.httpx,
                    "AsyncClient",
                    return_value=_AsyncClient(error=error),
                ):
                    self.assertEqual(
                        await content_enricher._fetch_url_text("https://public.example.test/error"),
                        "",
                    )


class ContentEnricherSourceCompositionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_huggingface_composes_metadata_and_falls_back_to_title(self) -> None:
        rich = {
            "title": "Model",
            "pipeline_tag": "text-generation",
            "likes": 1234,
            "downloads": 56789,
            "summary": "Model summary",
        }
        empty = {"title": "Title only"}

        self.assertIs(content_enricher.enrich_huggingface(rich), rich)
        self.assertEqual(
            rich["full_text"],
            "# Model\n\nPipeline: text-generation | Likes: 1,234 | Downloads: 56,789\n\nModel summary",
        )
        self.assertFalse(rich["pdf_pending"])
        content_enricher.enrich_huggingface(empty)
        self.assertEqual(empty["full_text"], "# Title only")

    async def test_github_uses_existing_abstract_only_above_500_chars(self) -> None:
        sufficient = {"title": "owner/repo", "abstract": "a" * 501}
        boundary = {
            "title": "owner/repo",
            "abstract": "a" * 500,
            "description": "Description",
        }

        with patch.object(
            content_enricher, "_fetch_github_readme", new=AsyncMock(return_value="README body")
        ) as fetch:
            self.assertIs(await content_enricher.enrich_github(sufficient), sufficient)
            fetch.assert_not_awaited()
            self.assertEqual(sufficient["full_text"], "a" * 501)

            await content_enricher.enrich_github(boundary)
            fetch.assert_awaited_once_with("owner/repo")
            self.assertEqual(boundary["full_text"], "Description\n\nREADME:\nREADME body")

    async def test_github_readme_failure_falls_back_without_fetching_invalid_name(self) -> None:
        paper = {"title": "not-a-full-name", "summary": "Summary"}
        with patch.object(
            content_enricher, "_fetch_github_readme", new=AsyncMock(return_value="")
        ) as fetch:
            await content_enricher.enrich_github(paper)
        fetch.assert_not_awaited()
        self.assertEqual(paper["full_text"], "Summary")

    async def test_news_requires_page_to_exceed_summary_by_more_than_200_chars(self) -> None:
        summary = "s" * 20
        accepted = {"title": "News", "url": "https://public.example.test/news", "summary": summary}
        rejected = dict(accepted)

        with patch.object(
            content_enricher, "_fetch_url_text", new=AsyncMock(return_value="p" * 221)
        ):
            await content_enricher.enrich_news(accepted)
        self.assertEqual(accepted["full_text"], f"# News\n\n{'p' * 221}")

        with patch.object(
            content_enricher, "_fetch_url_text", new=AsyncMock(return_value="p" * 220)
        ):
            await content_enricher.enrich_news(rejected)
        self.assertEqual(rejected["full_text"], f"# News\n\n{summary}")

    async def test_news_without_usable_page_falls_back_to_summary_then_title(self) -> None:
        summary = {"title": "News", "summary": "RSS summary"}
        title = {"title": "Title only", "url": "https://public.example.test/news"}
        with patch.object(
            content_enricher, "_fetch_url_text", new=AsyncMock(return_value="")
        ) as fetch:
            await content_enricher.enrich_news(summary)
            await content_enricher.enrich_news(title)
        fetch.assert_awaited_once_with("https://public.example.test/news")
        self.assertEqual(summary["full_text"], "# News\n\nRSS summary")
        self.assertEqual(title["full_text"], "Title only")

    async def test_producthunt_composes_abstract_or_summary_and_falls_back_to_title(self) -> None:
        for field in ("abstract", "summary"):
            with self.subTest(field=field):
                paper = {"title": "Launch", field: "Description"}
                self.assertIs(content_enricher.enrich_producthunt(paper), paper)
                self.assertEqual(paper["full_text"], "# Launch\n\nDescription")

        title = {"title": "Launch only"}
        content_enricher.enrich_producthunt(title)
        self.assertEqual(title["full_text"], "Launch only")

    async def test_x_composes_author_header_with_full_text(self) -> None:
        paper = {
            "title": "truncated title",
            "summary": "full tweet text",
            "author": "openai",
        }
        self.assertIs(content_enricher.enrich_x(paper), paper)
        self.assertEqual(paper["full_text"], "# @openai\n\nfull tweet text")

        no_author = {"title": "only title"}
        content_enricher.enrich_x(no_author)
        self.assertEqual(no_author["full_text"], "# X 推文\n\nonly title")

        empty = {"author": "openai"}
        content_enricher.enrich_x(empty)
        self.assertEqual(empty["full_text"], "# @openai")

    async def test_hackernews_external_page_requires_more_than_200_chars(self) -> None:
        accepted = {
            "title": "Story",
            "url": "https://public.example.test/story",
            "abstract": "Story text",
        }
        rejected = dict(accepted)

        with patch.object(
            content_enricher, "_fetch_url_text", new=AsyncMock(return_value="p" * 201)
        ):
            await content_enricher.enrich_hackernews(accepted)
        self.assertEqual(accepted["full_text"], f"# Story\n\n{'p' * 201}")

        with patch.object(
            content_enricher, "_fetch_url_text", new=AsyncMock(return_value="p" * 200)
        ):
            await content_enricher.enrich_hackernews(rejected)
        self.assertEqual(rejected["full_text"], "# Story\n\nStory text")

    async def test_hackernews_internal_story_avoids_fetch_and_falls_back_to_title(self) -> None:
        internal = {
            "title": "Ask HN",
            "hn_id": "42",
            "url": "https://news.ycombinator.com/item?id=42",
            "summary": "Question body",
        }
        title_only = {"title": "Same", "abstract": "Same"}
        with patch.object(content_enricher, "_fetch_url_text", new=AsyncMock()) as fetch:
            await content_enricher.enrich_hackernews(internal)
            await content_enricher.enrich_hackernews(title_only)
        fetch.assert_not_awaited()
        self.assertEqual(internal["full_text"], "# Ask HN\n\nQuestion body")
        self.assertEqual(title_only["full_text"], "Same")

    async def test_fetching_sources_accept_injected_ports_without_using_module_seams(self) -> None:
        page_fetcher = MagicMock()
        page_fetcher.fetch = AsyncMock(return_value="p" * 221)
        readme_fetcher = MagicMock()
        readme_fetcher.fetch = AsyncMock(return_value="README body")
        github = {"title": "owner/repo", "description": "Description"}
        news = {
            "title": "News",
            "url": "https://public.example.test/news",
            "summary": "s" * 20,
        }
        hackernews = {
            "title": "Story",
            "url": "https://public.example.test/story",
        }

        with (
            patch.object(content_enricher, "_fetch_url_text", new=AsyncMock()) as page_seam,
            patch.object(
                content_enricher, "_fetch_github_readme", new=AsyncMock()
            ) as readme_seam,
        ):
            self.assertIs(
                await content_enricher.enrich_github(github, readme_fetcher), github
            )
            self.assertIs(await content_enricher.enrich_news(news, page_fetcher), news)
            self.assertIs(
                await content_enricher.enrich_hackernews(hackernews, page_fetcher),
                hackernews,
            )

        readme_fetcher.fetch.assert_awaited_once_with("owner/repo")
        self.assertEqual(
            [call.args for call in page_fetcher.fetch.await_args_list],
            [
                ("https://public.example.test/news",),
                ("https://public.example.test/story",),
            ],
        )
        readme_seam.assert_not_awaited()
        page_seam.assert_not_awaited()
        self.assertEqual(github["full_text"], "Description\n\nREADME:\nREADME body")
        self.assertEqual(news["full_text"], f"# News\n\n{'p' * 221}")
        self.assertEqual(hackernews["full_text"], f"# Story\n\n{'p' * 221}")

    async def test_all_non_pdf_sources_truncate_full_text_in_place(self) -> None:
        cases = [
            (content_enricher.enrich_huggingface, {"abstract": "x" * 40_001}),
            (content_enricher.enrich_github, {"abstract": "x" * 40_001}),
            (content_enricher.enrich_news, {"title": "T", "summary": "x" * 40_001}),
            (content_enricher.enrich_producthunt, {"title": "T", "abstract": "x" * 40_001}),
            (content_enricher.enrich_hackernews, {"title": "T", "abstract": "x" * 40_001}),
        ]
        with (
            patch.object(content_enricher, "_fetch_url_text", new=AsyncMock()),
            patch.object(content_enricher, "_fetch_github_readme", new=AsyncMock()),
        ):
            for enricher, paper in cases:
                with self.subTest(enricher=enricher.__name__):
                    identity = id(paper)
                    result = enricher(paper)
                    if hasattr(result, "__await__"):
                        result = await result
                    self.assertEqual(id(result), identity)
                    self.assertEqual(len(paper["full_text"]), content_enricher._MAX_CONTENT_CHARS)


class ContentEnricherBatchContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_returns_same_list_and_dicts_and_delays_between_non_arxiv_items(self) -> None:
        papers = [{"title": "One"}, {"title": "Two"}, {"title": "Three"}]
        identities = [id(paper) for paper in papers]
        enricher = MagicMock(side_effect=lambda paper: paper.update(full_text=paper["title"]))

        with (
            patch.dict(content_enricher._ENRICH_MAP, {"contract-source": enricher}),
            patch.object(content_enricher.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            result = await content_enricher.enrich_papers(papers, "contract-source", delay=0.25)

        self.assertIs(result, papers)
        self.assertEqual([id(paper) for paper in result], identities)
        self.assertEqual([paper["full_text"] for paper in papers], ["One", "Two", "Three"])
        self.assertEqual(enricher.call_count, 3)
        self.assertEqual([call.args for call in sleep.await_args_list], [(0.25,), (0.25,)])

    async def test_skip_preserves_existing_text_or_sets_fallback_and_does_not_delay(self) -> None:
        papers = [
            {"title": "Existing", "skip_enrich": True, "full_text": "Keep me"},
            {"title": "Skipped", "skip_enrich": True, "summary": "Cached summary"},
            {"title": "Run"},
        ]
        enricher = MagicMock(side_effect=lambda paper: paper.update(full_text="enriched"))

        with (
            patch.dict(content_enricher._ENRICH_MAP, {"contract-source": enricher}),
            patch.object(content_enricher.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            await content_enricher.enrich_papers(papers, "contract-source", delay=1.0)

        self.assertEqual(papers[0]["full_text"], "Keep me")
        self.assertEqual(papers[1]["full_text"], "Cached summary")
        self.assertEqual(papers[2]["full_text"], "enriched")
        enricher.assert_called_once_with(papers[2])
        sleep.assert_not_awaited()

    async def test_unknown_source_returns_input_unchanged_without_sleep(self) -> None:
        papers = [{"title": "Untouched"}]
        with patch.object(content_enricher.asyncio, "sleep", new=AsyncMock()) as sleep:
            result = await content_enricher.enrich_papers(papers, "unknown-source", delay=1.0)
        self.assertIs(result, papers)
        self.assertEqual(papers, [{"title": "Untouched"}])
        sleep.assert_not_awaited()

    async def test_one_item_failure_uses_fallback_and_does_not_stop_later_items(self) -> None:
        papers = [
            {"title": "Broken", "abstract": "Original abstract"},
            {"title": "Healthy"},
        ]

        async def enrich(paper: dict[str, object]) -> None:
            if paper["title"] == "Broken":
                raise RuntimeError("boom")
            paper["full_text"] = "Healthy content"

        with (
            patch.dict(content_enricher._ENRICH_MAP, {"contract-source": enrich}),
            patch.object(content_enricher.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            result = await content_enricher.enrich_papers(papers, "contract-source", delay=0.4)

        self.assertIs(result, papers)
        self.assertEqual(papers[0]["full_text"], "Original abstract")
        self.assertEqual(papers[1]["full_text"], "Healthy content")
        sleep.assert_awaited_once_with(0.4)

    async def test_batch_dispatches_injected_ports_only_to_matching_sources(self) -> None:
        page_fetcher = MagicMock()
        page_fetcher.fetch = AsyncMock(return_value="p" * 201)
        readme_fetcher = MagicMock()
        readme_fetcher.fetch = AsyncMock(return_value="README")
        news = [{"title": "News", "url": "https://public.example.test/news"}]
        github = [{"title": "owner/repo", "description": "Description"}]

        self.assertIs(
            await content_enricher.enrich_papers(
                news,
                "news",
                delay=0,
                page_fetcher=page_fetcher,
                readme_fetcher=readme_fetcher,
            ),
            news,
        )
        self.assertIs(
            await content_enricher.enrich_papers(
                github,
                "github",
                delay=0,
                page_fetcher=page_fetcher,
                readme_fetcher=readme_fetcher,
            ),
            github,
        )

        page_fetcher.fetch.assert_awaited_once_with(
            "https://public.example.test/news"
        )
        readme_fetcher.fetch.assert_awaited_once_with("owner/repo")
        self.assertEqual(news[0]["full_text"], f"# News\n\n{'p' * 201}")
        self.assertEqual(github[0]["full_text"], "Description\n\nREADME:\nREADME")

    async def test_arxiv_batch_never_delays_even_when_delay_requested(self) -> None:
        papers = [{"title": "One"}, {"title": "Two"}]
        with patch.object(content_enricher.asyncio, "sleep", new=AsyncMock()) as sleep:
            await content_enricher.enrich_papers(papers, "arxiv", delay=9.0)
        sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
