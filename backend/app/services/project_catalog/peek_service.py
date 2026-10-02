"""项目库悬停速览：README 开头几段正文与默认分支最近一次提交，现读 GitHub。

库里存的 README 是给检索清洗过的（链接文字已去、空白已并），读不成段，所以速览现读 GitHub：一次 GraphQL
（owner、name 走变量），拿默认分支最近一次提交和 GitHub 仓库首页展示的那份 README。读到的结果在 Redis 里
新鲜 FRESH_SECONDS，过了再有人看才重读；读不到（GitHub 出错、限流、额度见底）时退回上一份，上一份最多留
STALE_SECONDS。

GraphQL 额度与采集共用一个令牌，现读有几道闸：只读公开项目库里的仓库；单 IP 与全站的现读次数封顶；令牌剩余
额度低于 RESERVE_POINTS 或被 GitHub 限流时全站停读到额度重置；读失败的仓库 RETRY_SECONDS 内、GitHub 上已经
没有的仓库 MISSING_SECONDS 内不再重读。Redis 不可用时一律不现读。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from backend.app.repositories.postgres_github_project_peek import (
    PostgresGitHubProjectPeekRepository,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError, hit_rate_limit
from backend.app.services.ingestion import source_github
from backend.app.services.project_catalog.readme_intro import readme_intro

__all__ = [
    "FRESH_SECONDS",
    "GLOBAL_FETCHES_PER_HOUR",
    "IP_FETCHES_PER_WINDOW",
    "IP_WINDOW_SECONDS",
    "MISSING_SECONDS",
    "RESERVE_POINTS",
    "RETRY_SECONDS",
    "STALE_SECONDS",
    "GitHubPeekFetch",
    "ProjectPeekService",
    "fetch_github_peek",
]

logger = logging.getLogger(__name__)

FRESH_SECONDS = 12 * 3600
STALE_SECONDS = 7 * 86400
RETRY_SECONDS = 300
MISSING_SECONDS = 6 * 3600
GLOBAL_FETCHES_PER_HOUR = 300
IP_FETCHES_PER_WINDOW = 40
IP_WINDOW_SECONDS = 600
# 一次速览花 1 点（5000 点/小时）；剩余低于这么多就把额度留给采集。
RESERVE_POINTS = 1000

_CACHE_PREFIX = "projects:peek:v1:cache:"
_RETRY_PREFIX = "projects:peek:v1:retry:"
_PAUSE_KEY = "projects:peek:v1:paused"
_RATE_ACTION = "projects.peek.github"
_PAUSE_MIN_SECONDS = 60
_PAUSE_MAX_SECONDS = 3600
# 限流或令牌失效却没给重置时间：先停十分钟
_LIMITED_PAUSE_SECONDS = 600
_FETCH_TIMEOUT_SECONDS = 8.0
_MAX_RESPONSE_BYTES = 4_000_000

# GitHub 首页展示 README 的位置次序：.github 目录、仓库根目录、docs 目录。
_README_PATHS = (
    ".github/README.md",
    "README.md",
    "readme.md",
    "Readme.md",
    "README.MD",
    "README.markdown",
    "README.rst",
    "README.txt",
    "README",
    "docs/README.md",
)
_QUERY = (
    "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {"
    " nameWithOwner isPrivate"
    " defaultBranchRef { target { ... on Commit {"
    " oid messageHeadline committedDate author { name user { login } } } } }"
    + "".join(
        f" r{index}: object(expression: {json.dumps('HEAD:' + path)}) {{ ... on Blob {{ text }} }}"
        for index, path in enumerate(_README_PATHS)
    )
    + " } }"
)
_FULL_NAME = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:?\d{2})")


@dataclass(frozen=True)
class GitHubPeekFetch:
    """一次现读的结果；remaining、reset_at、retry_after 取自 GitHub 的限流响应头。"""

    status: Literal["ok", "missing", "failed", "limited"]
    # None：GitHub 首页那几个位置都没有 README
    readme: str | None = None
    commit: dict[str, str] | None = None
    remaining: int | None = None
    reset_at: int | None = None
    retry_after: int | None = None


def _header_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _parse_commit(target: Any, canonical: str) -> dict[str, str] | None:
    if not isinstance(target, dict):
        return None
    sha = str(target.get("oid") or "")
    if not _SHA.fullmatch(sha):
        return None
    author = target.get("author") if isinstance(target.get("author"), dict) else {}
    user = author.get("user") if isinstance(author.get("user"), dict) else {}
    committed_at = str(target.get("committedDate") or "")
    return {
        "sha": sha,
        "message": " ".join(str(target.get("messageHeadline") or "").split())[:200],
        "author": (str(user.get("login") or "").strip() or " ".join(str(author.get("name") or "").split()))[:80],
        "committed_at": committed_at if _TIMESTAMP.fullmatch(committed_at) else "",
        "url": f"https://github.com/{canonical}/commit/{sha}",
    }


def _parse_peek(payload: Any, budget: dict[str, int | None]) -> GitHubPeekFetch:
    if not isinstance(payload, dict):
        return GitHubPeekFetch("failed", **budget)
    errors = [error for error in payload.get("errors") or [] if isinstance(error, dict)]
    kinds = {str(error.get("type") or "") for error in errors}
    if "RATE_LIMITED" in kinds:
        return GitHubPeekFetch("limited", **budget)
    repository = (payload.get("data") or {}).get("repository") if isinstance(payload.get("data"), dict) else None
    if not isinstance(repository, dict):
        return GitHubPeekFetch("missing" if not errors or "NOT_FOUND" in kinds else "failed", **budget)
    # 令牌看得见的私有仓库不往公开页面上摆
    if repository.get("isPrivate") is not False:
        return GitHubPeekFetch("missing", **budget)
    canonical = str(repository.get("nameWithOwner") or "")
    if not _FULL_NAME.fullmatch(canonical):
        return GitHubPeekFetch("failed", **budget)
    readme = None
    for index in range(len(_README_PATHS)):
        blob = repository.get(f"r{index}")
        if isinstance(blob, dict) and isinstance(blob.get("text"), str):
            readme = blob["text"]
            break
    target = (repository.get("defaultBranchRef") or {}).get("target")
    return GitHubPeekFetch("ok", readme=readme, commit=_parse_commit(target, canonical), **budget)


async def _post_peek_query(owner: str, name: str, transport: httpx.AsyncBaseTransport | None) -> GitHubPeekFetch:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(6.0, connect=4.0),
        trust_env=True,
        follow_redirects=False,
        transport=transport,
    ) as client, client.stream(
        "POST",
        f"{source_github.GITHUB_API_BASE}/graphql",
        headers=source_github._build_headers(),
        json={"query": _QUERY, "variables": {"owner": owner, "name": name}},
    ) as response:
        budget = {
            "remaining": _header_int(response.headers.get("x-ratelimit-remaining")),
            "reset_at": _header_int(response.headers.get("x-ratelimit-reset")),
            "retry_after": _header_int(response.headers.get("retry-after")),
        }
        if response.status_code in (401, 403, 429):
            logger.warning("[ProjectPeek] GitHub 拒绝现读 %s/%s：HTTP %s", owner, name, response.status_code)
            return GitHubPeekFetch("limited", **budget)
        if response.status_code != 200:
            logger.warning("[ProjectPeek] GitHub 现读 %s/%s 出错：HTTP %s", owner, name, response.status_code)
            return GitHubPeekFetch("failed", **budget)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                logger.warning("[ProjectPeek] %s/%s 的响应超过 %d 字节，放弃", owner, name, _MAX_RESPONSE_BYTES)
                return GitHubPeekFetch("failed", **budget)
    return _parse_peek(json.loads(body), budget)


async def fetch_github_peek(
    full_name: str,
    *,
    timeout: float = _FETCH_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GitHubPeekFetch:
    """现读一个仓库的 README 与最近一次提交；没配令牌、网络或响应出错都记作 failed，不抛异常。"""
    if not source_github._get_token() or not _FULL_NAME.fullmatch(full_name):
        return GitHubPeekFetch("failed")
    owner, name = full_name.split("/")
    try:
        return await asyncio.wait_for(_post_peek_query(owner, name, transport), timeout)
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("[ProjectPeek] 现读 %s 失败：%s", full_name, type(exc).__name__)
        return GitHubPeekFetch("failed")


def _unavailable(repo_id: str) -> dict[str, Any]:
    return {
        "repo_id": repo_id,
        "status": "unavailable",
        "has_readme": False,
        "readme": [],
        "readme_more": False,
        "commit": None,
    }


def _build_peek(repo_id: str, fetched: GitHubPeekFetch) -> dict[str, Any]:
    paragraphs, more = readme_intro(fetched.readme)
    return {
        "repo_id": repo_id,
        "status": "ok",
        "has_readme": fetched.readme is not None,
        "readme": paragraphs,
        "readme_more": more,
        "commit": fetched.commit,
    }


class ProjectPeekService:
    def __init__(
        self,
        repository_factory: Callable[[], Any] = PostgresGitHubProjectPeekRepository,
        *,
        fetch: Callable[[str], Awaitable[GitHubPeekFetch]] = fetch_github_peek,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository_factory = repository_factory
        self._fetch = fetch
        self._clock = clock
        # 同一个仓库同时有几个人在看：进程里只读一次
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def peek(self, repo_id: str, *, redis: Any, client_ip: str) -> dict[str, Any] | None:
        """仓库不在公开项目库里返回 None；否则返回速览，读不到又没有上一份时 status=unavailable。"""
        source = await asyncio.to_thread(self._repository_factory().peek_source, repo_id)
        if source is None:
            return None
        cached = await self._read_cache(redis, repo_id)
        if cached is not None and self._clock() - cached[0] < FRESH_SECONDS:
            return cached[1]
        stale = cached[1] if cached is not None else None
        if redis is None or str(source.get("availability_status") or "active") != "active":
            return stale or _unavailable(repo_id)
        task = self._inflight.get(repo_id)
        if task is None:
            full_name = str(source.get("full_name") or repo_id)
            task = asyncio.ensure_future(self._refresh(repo_id, full_name, redis=redis, client_ip=client_ip))
            self._inflight[repo_id] = task
            task.add_done_callback(lambda done: self._forget(repo_id, done))
        # 看的人走了（请求取消）也读完、写进缓存，下一个人直接用
        fresh = await asyncio.shield(task)
        return fresh or stale or _unavailable(repo_id)

    def _forget(self, repo_id: str, task: asyncio.Future[dict[str, Any]]) -> None:
        if self._inflight.get(repo_id) is task:
            del self._inflight[repo_id]

    async def _refresh(self, repo_id: str, full_name: str, *, redis: Any, client_ip: str) -> dict[str, Any] | None:
        if not await self._may_fetch(redis, repo_id, client_ip):
            return None
        fetched = await self._fetch(full_name)
        await self._note_budget(redis, fetched)
        if fetched.status == "ok":
            peek = await asyncio.to_thread(_build_peek, repo_id, fetched)
            await self._write_cache(redis, repo_id, peek)
            return peek
        try:
            await redis.set(
                _RETRY_PREFIX + repo_id,
                b"1",
                ex=MISSING_SECONDS if fetched.status == "missing" else RETRY_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - 记不下重读时间不影响这次回应
            logger.warning("[ProjectPeek] 记 %s 的重读时间失败：%s", repo_id, type(exc).__name__)
        return None

    async def _may_fetch(self, redis: Any, repo_id: str, client_ip: str) -> bool:
        try:
            if await redis.exists(_PAUSE_KEY, _RETRY_PREFIX + repo_id):
                return False
            await hit_rate_limit(
                redis,
                action=_RATE_ACTION,
                identity=f"ip:{client_ip or 'unknown'}",
                limit=IP_FETCHES_PER_WINDOW,
                window_seconds=IP_WINDOW_SECONDS,
            )
            await hit_rate_limit(
                redis,
                action=_RATE_ACTION,
                identity="all",
                limit=GLOBAL_FETCHES_PER_HOUR,
                window_seconds=3600,
            )
        except RateLimitExceededError:
            return False
        except Exception as exc:  # noqa: BLE001 - 闸门读不了就不现读
            logger.warning("[ProjectPeek] 现读闸门不可用，%s 这次不读：%s", repo_id, type(exc).__name__)
            return False
        return True

    def _pause_seconds(self, fetched: GitHubPeekFetch) -> int:
        now = self._clock()
        if fetched.status == "limited":
            if fetched.retry_after:
                seconds = float(fetched.retry_after)
            elif fetched.remaining == 0 and fetched.reset_at:
                seconds = fetched.reset_at - now
            else:
                seconds = _LIMITED_PAUSE_SECONDS
        elif fetched.remaining is not None and fetched.remaining < RESERVE_POINTS:
            seconds = fetched.reset_at - now if fetched.reset_at else _LIMITED_PAUSE_SECONDS
        else:
            return 0
        return int(min(max(seconds, _PAUSE_MIN_SECONDS), _PAUSE_MAX_SECONDS))

    async def _note_budget(self, redis: Any, fetched: GitHubPeekFetch) -> None:
        seconds = self._pause_seconds(fetched)
        if not seconds:
            return
        logger.warning(
            "[ProjectPeek] GitHub 额度剩 %s 或被限流（%s），速览停读 %d 秒",
            fetched.remaining, fetched.status, seconds,
        )
        try:
            await redis.set(_PAUSE_KEY, b"1", ex=seconds)
        except Exception as exc:  # noqa: BLE001 - 停读记不下，还有全站次数封顶兜着
            logger.warning("[ProjectPeek] 记停读失败：%s", type(exc).__name__)

    async def _read_cache(self, redis: Any, repo_id: str) -> tuple[float, dict[str, Any]] | None:
        if redis is None:
            return None
        try:
            raw = await redis.get(_CACHE_PREFIX + repo_id)
        except Exception as exc:  # noqa: BLE001 - 缓存读不了当没有
            logger.warning("[ProjectPeek] 读 %s 的缓存失败：%s", repo_id, type(exc).__name__)
            return None
        if not raw:
            return None
        try:
            entry = json.loads(raw)
            return float(entry["fetched_at"]), dict(entry["peek"])
        except (ValueError, KeyError, TypeError):
            return None

    async def _write_cache(self, redis: Any, repo_id: str, peek: dict[str, Any]) -> None:
        entry = json.dumps({"fetched_at": self._clock(), "peek": peek}, ensure_ascii=False)
        try:
            await redis.set(_CACHE_PREFIX + repo_id, entry.encode("utf-8"), ex=STALE_SECONDS)
        except Exception as exc:  # noqa: BLE001 - 缓存写不进去，这次照样回应
            logger.warning("[ProjectPeek] 写 %s 的缓存失败：%s", repo_id, type(exc).__name__)
