from __future__ import annotations

import base64
import unittest

import httpx

from backend.app.services.ingestion.source_github import fetch_github_readme_snapshot


class GitHubReadmeSnapshotTests(unittest.TestCase):
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_success_decodes_cleans_and_hashes_readme(self) -> None:
        encoded = base64.b64encode(b"# Demo\n[Guide](https://example.com)\n```py\nsecret()\n```").decode()

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/repos/owner/repo/readme")
            return httpx.Response(
                200,
                headers={"ETag": '"v1"', "X-RateLimit-Remaining": "42"},
                json={"encoding": "base64", "content": encoded},
            )

        with self._client(handler) as client:
            result = fetch_github_readme_snapshot("owner/repo", client)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.text, "Demo")
        self.assertEqual(result.etag, '"v1"')
        self.assertEqual(result.rate_limit_remaining, 42)
        self.assertEqual(len(result.sha256), 64)

    def test_etag_not_modified_preserves_content_at_caller(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["if-none-match"], '"v1"')
            return httpx.Response(304, headers={"ETag": '"v1"'})

        with self._client(handler) as client:
            result = fetch_github_readme_snapshot("owner/repo", client, etag='"v1"')

        self.assertEqual(result.status, "not_modified")
        self.assertEqual(result.text, "")
        self.assertEqual(result.etag, '"v1"')

    def test_unauthorized_token_retries_anonymously(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(401)
            encoded = base64.b64encode(b"README").decode()
            return httpx.Response(200, json={"encoding": "base64", "content": encoded})

        with self._client(handler) as client:
            result = fetch_github_readme_snapshot("owner/repo", client)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(requests), 2)
        self.assertNotIn("authorization", requests[1].headers)

    def test_not_found_and_rate_limit_have_distinct_statuses(self) -> None:
        for status_code, expected in ((404, "not_found"), (429, "rate_limited")):
            with self.subTest(status_code=status_code):
                with self._client(lambda _request: httpx.Response(status_code)) as client:
                    result = fetch_github_readme_snapshot("owner/repo", client)
                self.assertEqual(result.status, expected)


if __name__ == "__main__":
    unittest.main()
