from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_project_peek_service
from backend.app.services.ingestion import source_github
from backend.app.services.project_catalog import peek_service
from backend.app.services.project_catalog.peek_service import (
    FRESH_SECONDS,
    GLOBAL_FETCHES_PER_HOUR,
    IP_FETCHES_PER_WINDOW,
    MISSING_SECONDS,
    RESERVE_POINTS,
    RETRY_SECONDS,
    STALE_SECONDS,
    GitHubPeekFetch,
    ProjectPeekService,
    fetch_github_peek,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
COMMIT = {
    "sha": SHA,
    "message": "Fix the parser",
    "author": "octocat",
    "committed_at": "2026-10-01T08:00:00Z",
    "url": f"https://github.com/acme/alpha/commit/{SHA}",
}
OK_PEEK = {
    "repo_id": "acme/alpha",
    "status": "ok",
    "has_readme": True,
    "readme": ["Alpha indexes your notes and answers questions about them with citations."],
    "readme_more": True,
    "commit": COMMIT,
}
UNAVAILABLE = {
    "repo_id": "acme/alpha",
    "status": "unavailable",
    "has_readme": False,
    "readme": [],
    "readme_more": False,
    "commit": None,
}
README = """\
# Alpha

Alpha indexes your notes and answers questions about them with citations you can check.

## Install

pip install alpha and then run it once so it can create its configuration folder.
"""
NOW = 1_790_000_000.0


# --- route -------------------------------------------------------------------------------------


def _peek_client(service: Any, *, redis: Any = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[get_project_peek_service] = lambda: service
    app.state.redis = redis
    return TestClient(app)


def _fake_service(result: dict[str, Any] | None) -> AsyncMock:
    service = AsyncMock(spec=ProjectPeekService)
    service.peek.return_value = result
    return service


def test_peek_route_returns_the_peek_and_lets_browsers_keep_it() -> None:
    service = _fake_service(OK_PEEK)
    redis = object()

    response = _peek_client(service, redis=redis).get("/api/projects/github/peek", params={"repo": " acme/alpha "})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=600"
    assert response.json() == OK_PEEK
    service.peek.assert_awaited_once_with("acme/alpha", redis=redis, client_ip="testclient")


def test_peek_route_does_not_let_browsers_keep_unavailable_peeks() -> None:
    response = _peek_client(_fake_service(UNAVAILABLE)).get("/api/projects/github/peek?repo=acme/alpha")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == UNAVAILABLE


def test_peek_route_is_404_outside_the_public_catalog() -> None:
    response = _peek_client(_fake_service(None)).get("/api/projects/github/peek?repo=acme/nobody")

    assert response.status_code == 404


def test_peek_route_rejects_malformed_repos_before_any_lookup() -> None:
    service = _fake_service(OK_PEEK)
    client = _peek_client(service)

    for repo in ("ab", "acme", "acme/alpha/extra", "acme/al pha", "../etc", "acme/" + "a" * 200):
        assert client.get("/api/projects/github/peek", params={"repo": repo}).status_code == 422, repo
    assert client.get("/api/projects/github/peek").status_code == 422
    service.peek.assert_not_awaited()


# --- service -----------------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, *, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def exists(self, *keys: str) -> int:
        return sum(key in self.values for key in keys)

    async def incr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds

    async def ttl(self, key: str) -> int:
        if key not in self.values:
            return -2
        return self.expirations.get(key, -1)


class BrokenRedis:
    def __getattr__(self, name: str) -> Any:
        async def fail(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("redis is down")

        return fail


class FakeRepository:
    def __init__(self, sources: dict[str, dict[str, Any]]) -> None:
        self.sources = sources

    def peek_source(self, repo_id: str) -> dict[str, Any] | None:
        return self.sources.get(repo_id)


def _source(repo_id: str, *, status: str = "active") -> dict[str, Any]:
    owner, name = repo_id.split("/")
    return {"repo_id": repo_id, "full_name": f"{owner.title()}/{name.title()}", "availability_status": status}


class ProjectPeekServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = NOW
        self.redis = FakeRedis()
        self.repository = FakeRepository({repo: _source(repo) for repo in ("acme/alpha", "acme/beta")})
        self.fetch = AsyncMock(return_value=GitHubPeekFetch("ok", readme=README, commit=COMMIT, remaining=4000))
        self.service = ProjectPeekService(lambda: self.repository, fetch=self.fetch, clock=lambda: self.now)

    async def _peek(self, repo_id: str = "acme/alpha", *, ip: str = "203.0.113.7", redis: Any = ...) -> Any:
        return await self.service.peek(repo_id, redis=self.redis if redis is ... else redis, client_ip=ip)

    def _cache(self, repo_id: str, peek: dict[str, Any], *, age: float) -> None:
        entry = {"fetched_at": self.now - age, "peek": peek}
        self.redis.values[f"projects:peek:v1:cache:{repo_id}"] = json.dumps(entry).encode()

    async def test_repos_outside_the_catalog_are_never_read(self) -> None:
        self.assertIsNone(await self._peek("acme/nobody"))
        self.fetch.assert_not_awaited()
        self.assertEqual(self.redis.values, {})

    async def test_a_miss_reads_github_by_its_full_name_and_caches_the_intro(self) -> None:
        peek = await self._peek()

        self.fetch.assert_awaited_once_with("Acme/Alpha")
        self.assertEqual(peek, {
            "repo_id": "acme/alpha",
            "status": "ok",
            "has_readme": True,
            "readme": ["Alpha indexes your notes and answers questions about them with citations you can check."],
            "readme_more": False,
            "commit": COMMIT,
        })
        entry = json.loads(self.redis.values["projects:peek:v1:cache:acme/alpha"])
        self.assertEqual(entry, {"fetched_at": NOW, "peek": peek})
        self.assertEqual(self.redis.expirations["projects:peek:v1:cache:acme/alpha"], STALE_SECONDS)
        self.assertEqual(self.redis.values["ratelimit:projects.peek.github:ip:203.0.113.7"], 1)
        self.assertEqual(self.redis.values["ratelimit:projects.peek.github:all"], 1)

    async def test_readmes_without_prose_and_repos_without_readmes_are_told_apart(self) -> None:
        self.fetch.return_value = GitHubPeekFetch("ok", readme="# Alpha\n\n![demo](demo.gif)\n", commit=None)
        self.assertEqual(await self._peek(), {**UNAVAILABLE, "status": "ok", "has_readme": True})

        self.fetch.return_value = GitHubPeekFetch("ok", readme=None, commit=COMMIT)
        self.assertEqual(
            await self._peek("acme/beta"),
            {**UNAVAILABLE, "repo_id": "acme/beta", "status": "ok", "commit": COMMIT},
        )

    async def test_a_fresh_copy_is_served_without_reading_github(self) -> None:
        self._cache("acme/alpha", OK_PEEK, age=FRESH_SECONDS - 1)

        self.assertEqual(await self._peek(), OK_PEEK)
        self.fetch.assert_not_awaited()
        self.assertNotIn("ratelimit:projects.peek.github:all", self.redis.values)

    async def test_an_old_copy_is_refreshed_and_kept_while_github_fails(self) -> None:
        self._cache("acme/alpha", OK_PEEK, age=FRESH_SECONDS + 1)
        self.fetch.return_value = GitHubPeekFetch("failed")

        self.assertEqual(await self._peek(), OK_PEEK)
        self.assertEqual(self.redis.expirations["projects:peek:v1:retry:acme/alpha"], RETRY_SECONDS)
        # 重读间隔内不再去读，照样给上一份
        self.assertEqual(await self._peek(), OK_PEEK)
        self.fetch.assert_awaited_once()

    async def test_repos_gone_from_github_back_off_longer(self) -> None:
        self.fetch.return_value = GitHubPeekFetch("missing")

        self.assertEqual(await self._peek(), UNAVAILABLE)
        self.assertEqual(self.redis.expirations["projects:peek:v1:retry:acme/alpha"], MISSING_SECONDS)

    async def test_reads_are_capped_per_ip_and_site_wide(self) -> None:
        self.repository.sources.update({f"acme/r{index}": _source(f"acme/r{index}") for index in range(60)})
        for index in range(IP_FETCHES_PER_WINDOW):
            self.assertEqual((await self._peek(f"acme/r{index}"))["status"], "ok")

        self.assertEqual(await self._peek("acme/alpha"), UNAVAILABLE)
        self.assertEqual(self.fetch.await_count, IP_FETCHES_PER_WINDOW)
        self.assertEqual((await self._peek("acme/alpha", ip="198.51.100.2"))["status"], "ok")

        self.redis.values["ratelimit:projects.peek.github:all"] = GLOBAL_FETCHES_PER_HOUR
        self.assertEqual((await self._peek("acme/beta", ip="192.0.2.9"))["repo_id"], "acme/beta")
        self.assertEqual(self.fetch.await_count, IP_FETCHES_PER_WINDOW + 1)

    async def test_a_low_token_budget_pauses_every_read_until_the_reset(self) -> None:
        self.fetch.return_value = GitHubPeekFetch(
            "ok", readme=README, commit=COMMIT, remaining=RESERVE_POINTS - 1, reset_at=int(NOW) + 900,
        )

        self.assertEqual((await self._peek())["status"], "ok")
        self.assertEqual(self.redis.expirations["projects:peek:v1:paused"], 900)
        self.assertEqual(await self._peek("acme/beta"), {**UNAVAILABLE, "repo_id": "acme/beta"})
        self.fetch.assert_awaited_once()

    async def test_rate_limits_pause_for_the_time_github_asks_within_bounds(self) -> None:
        cases = [
            (GitHubPeekFetch("limited", retry_after=30), 60),
            (GitHubPeekFetch("limited", retry_after=120), 120),
            (GitHubPeekFetch("limited"), 600),
            (GitHubPeekFetch("limited", remaining=0, reset_at=int(NOW) + 100_000), 3600),
            (GitHubPeekFetch("failed", remaining=RESERVE_POINTS), None),
        ]
        for fetched, pause in cases:
            with self.subTest(fetched=fetched):
                self.redis = FakeRedis()
                self.fetch.return_value = fetched
                self.assertEqual(await self._peek(), UNAVAILABLE)
                self.assertEqual(self.redis.expirations.get("projects:peek:v1:paused"), pause)

    async def test_nothing_is_read_without_redis_or_for_repos_gone_from_the_catalog_feed(self) -> None:
        self.assertEqual(await self._peek(redis=None), UNAVAILABLE)

        self.repository.sources["acme/alpha"] = _source("acme/alpha", status="not_found")
        self.assertEqual(await self._peek(), UNAVAILABLE)
        self._cache("acme/alpha", OK_PEEK, age=FRESH_SECONDS * 4)
        self.assertEqual(await self._peek(), OK_PEEK)
        self.fetch.assert_not_awaited()

    async def test_a_broken_redis_fails_closed(self) -> None:
        self.assertEqual(await self._peek(redis=BrokenRedis()), UNAVAILABLE)
        self.fetch.assert_not_awaited()

    async def test_concurrent_lookups_of_one_repo_share_a_single_read(self) -> None:
        release = asyncio.Event()

        async def slow_fetch(full_name: str) -> GitHubPeekFetch:
            await release.wait()
            return GitHubPeekFetch("ok", readme=README, commit=COMMIT)

        self.fetch.side_effect = slow_fetch
        lookups = [asyncio.ensure_future(self._peek(ip=f"203.0.113.{index}")) for index in range(3)]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*lookups)

        self.assertEqual(self.fetch.await_count, 1)
        self.assertTrue(all(result == results[0] and result["status"] == "ok" for result in results))

    async def test_a_cancelled_lookup_still_fills_the_cache(self) -> None:
        release = asyncio.Event()

        async def slow_fetch(full_name: str) -> GitHubPeekFetch:
            await release.wait()
            return GitHubPeekFetch("ok", readme=README, commit=COMMIT)

        self.fetch.side_effect = slow_fetch
        lookup = asyncio.ensure_future(self._peek())
        for _ in range(5):
            await asyncio.sleep(0)
        lookup.cancel()
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)

        self.assertIn("projects:peek:v1:cache:acme/alpha", self.redis.values)
        self.assertEqual((await self._peek())["status"], "ok")
        self.fetch.assert_awaited_once()


# --- GitHub reader -----------------------------------------------------------------------------


def _repository(**overrides: Any) -> dict[str, Any]:
    repository: dict[str, Any] = {
        "nameWithOwner": "Acme/Alpha",
        "isPrivate": False,
        "defaultBranchRef": {"target": {
            "oid": SHA,
            "messageHeadline": "Fix  the\nparser",
            "committedDate": "2026-10-01T08:00:00Z",
            "author": {"name": "Octo Cat", "user": {"login": "octocat"}},
        }},
        "r0": None,
        "r1": {"text": README},
        "r2": {"text": "a lowercase readme that GitHub would not show first"},
    }
    repository.update(overrides)
    return repository


class FetchGitHubPeekTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        token = patch.object(source_github, "_get_token", return_value="test-token")
        token.start()
        self.addCleanup(token.stop)

    def _transport(self, status: int = 200, body: Any = None, headers: dict[str, str] | None = None) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            content = body if isinstance(body, bytes) else json.dumps(body).encode()
            return httpx.Response(status, content=content, headers=headers or {})

        return httpx.MockTransport(handler)

    async def test_reads_the_readme_github_shows_and_the_latest_commit(self) -> None:
        transport = self._transport(
            body={"data": {"repository": _repository()}},
            headers={"x-ratelimit-remaining": "4321", "x-ratelimit-reset": "1790003600"},
        )

        fetched = await fetch_github_peek("acme/alpha", transport=transport)

        self.assertEqual(fetched, GitHubPeekFetch(
            "ok",
            readme=README,
            commit={
                "sha": SHA,
                "message": "Fix the parser",
                "author": "octocat",
                "committed_at": "2026-10-01T08:00:00Z",
                "url": f"https://github.com/Acme/Alpha/commit/{SHA}",
            },
            remaining=4321,
            reset_at=1790003600,
        ))
        (request,) = self.requests
        self.assertEqual(str(request.url), "https://api.github.com/graphql")
        self.assertEqual(request.headers["authorization"], "Bearer test-token")
        payload = json.loads(request.content)
        self.assertEqual(payload["variables"], {"owner": "acme", "name": "alpha"})
        query = payload["query"]
        self.assertNotIn("acme", query)
        # GitHub 首页的次序：.github 目录、根目录、docs 目录
        self.assertLess(query.index('"HEAD:.github/README.md"'), query.index('"HEAD:README.md"'))
        self.assertLess(query.index('"HEAD:README.md"'), query.index('"HEAD:docs/README.md"'))

    async def test_commit_details_degrade_instead_of_failing(self) -> None:
        unlinked = _repository(defaultBranchRef={"target": {
            "oid": SHA, "messageHeadline": "x" * 300, "committedDate": "yesterday",
            "author": {"name": "  Octo   Cat ", "user": None},
        }})
        fetched = await fetch_github_peek("acme/alpha", transport=self._transport(body={"data": {"repository": unlinked}}))
        self.assertEqual(fetched.commit["author"], "Octo Cat")
        self.assertEqual(fetched.commit["message"], "x" * 200)
        self.assertEqual(fetched.commit["committed_at"], "")

        for target in (None, {"oid": "not-a-sha"}):
            body = {"data": {"repository": _repository(defaultBranchRef={"target": target}, r1=None, r2=None)}}
            fetched = await fetch_github_peek("acme/alpha", transport=self._transport(body=body))
            self.assertEqual((fetched.status, fetched.commit, fetched.readme), ("ok", None, None))

    async def test_missing_private_and_rate_limited_answers(self) -> None:
        cases = [
            ({"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "path": ["repository"]}]}, "missing"),
            ({"data": {"repository": _repository(isPrivate=True)}}, "missing"),
            ({"data": None, "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}, "limited"),
            ({"data": {"repository": None}, "errors": [{"type": "FORBIDDEN"}]}, "failed"),
            ({"data": {"repository": _repository(nameWithOwner="no slash")}}, "failed"),
            (["not", "an", "object"], "failed"),
        ]
        for body, status in cases:
            with self.subTest(status=status, body=body):
                fetched = await fetch_github_peek("acme/alpha", transport=self._transport(body=body))
                self.assertEqual(fetched.status, status)
                self.assertIsNone(fetched.readme)

    async def test_http_errors_carry_the_rate_limit_headers(self) -> None:
        fetched = await fetch_github_peek(
            "acme/alpha", transport=self._transport(403, {"message": "secondary rate limit"}, {"retry-after": "120"}),
        )
        self.assertEqual((fetched.status, fetched.retry_after), ("limited", 120))
        self.assertEqual((await fetch_github_peek("acme/alpha", transport=self._transport(401, {}))).status, "limited")
        self.assertEqual((await fetch_github_peek("acme/alpha", transport=self._transport(502, {}))).status, "failed")
        self.assertEqual((await fetch_github_peek("acme/alpha", transport=self._transport(200, b"{oops"))).status, "failed")

    async def test_oversized_slow_or_unreachable_answers_fail_quietly(self) -> None:
        with patch.object(peek_service, "_MAX_RESPONSE_BYTES", 64):
            fetched = await fetch_github_peek("acme/alpha", transport=self._transport(body={"data": {"repository": _repository()}}))
        self.assertEqual(fetched.status, "failed")

        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        self.assertEqual(
            (await fetch_github_peek("acme/alpha", transport=httpx.MockTransport(unreachable))).status, "failed",
        )

        async def slow(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, json={})

        fetched = await fetch_github_peek("acme/alpha", timeout=0.05, transport=httpx.MockTransport(slow))
        self.assertEqual(fetched.status, "failed")

    async def test_nothing_is_sent_without_a_token_or_for_odd_names(self) -> None:
        transport = self._transport(body={"data": {"repository": _repository()}})
        with patch.object(source_github, "_get_token", return_value=""):
            self.assertEqual((await fetch_github_peek("acme/alpha", transport=transport)).status, "failed")
        self.assertEqual((await fetch_github_peek("acme/alpha/extra", transport=transport)).status, "failed")
        self.assertEqual(self.requests, [])
