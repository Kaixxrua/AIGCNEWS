"""Bounded on-demand descriptions using the existing model, outside the public catalog.

Redis is required: it owns cache, leases and the shared programmatic quota. No
request can submit generation after a failed Redis operation. Workers use fenced
leases so an expired worker cannot overwrite a newer result.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import math
import posixpath
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from backend.app.models.schema_project_descriptions import normalize_description_repo
from backend.app.repositories.postgres_project_descriptions import PostgresProjectDescriptionRepository
from backend.app.services.api_access import quota
from backend.app.services.auth.rate_limit import RATE_LIMIT_PREFIX, hit_rate_limit
from backend.app.services.ingestion.source_github import _build_headers
from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.project_catalog.game_details import (
    image_candidates,
    normalize_game_details,
    safe_repository_path,
)
from backend.app.services.project_catalog.game_poster_agent import (
    SEARCH_MISSING_SECONDS,
    SEARCH_READY_SECONDS,
    research_game_poster,
)
from backend.app.services.project_catalog.game_poster_resources import cached_poster_exists, is_cached_poster_url
from backend.app.services.project_catalog.game_posters import (
    POSTER_MISSING_SECONDS,
    POSTER_UNAVAILABLE_SECONDS,
)

READY_TTL = 7 * 86400
RETRY_SECONDS = 60
# Identity enrichment and web research share the job, but not a ninety-second
# budget that can expire after the poster has already been downloaded. The
# agent has its own 180-second deadline, including visual image review, and
# returns its trace before this fence. The lease also covers job finalization.
JOB_SECONDS = 240
LEASE_SECONDS = 270
READS_PER_MINUTE = 60
POSTS_PER_MINUTE = 30
MAX_CONCURRENT_GENERATIONS = 4
PREFIX = "projects:descriptions:v1:"

_RELEASE = """-- descriptions release lease
if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end
return 0
"""
_FINISH = """-- descriptions fenced finish
if redis.call('GET',KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET',KEYS[2],ARGV[2],'EX',ARGV[3])
redis.call('DEL',KEYS[1])
return 1
"""
# Same keys, limits and windows as the existing REST/MCP search pool. Atomic
# check+charge, strict errors, and no partial daily charge when monthly is full.
_CHARGE = """-- descriptions shared quota charge
for i=1,2 do
  local count=tonumber(redis.call('GET',KEYS[i]) or '0')
  local limit=tonumber(ARGV[(i-1)*2+1])
  local window=tonumber(ARGV[(i-1)*2+2])
  if count>=limit then
    local ttl=redis.call('TTL',KEYS[i])
    if ttl<0 then redis.call('EXPIRE',KEYS[i],window); ttl=window end
    return {0,i,ttl}
  end
end
for i=1,2 do
  redis.call('INCR',KEYS[i])
  if redis.call('TTL',KEYS[i])<0 then redis.call('EXPIRE',KEYS[i],ARGV[(i-1)*2+2]) end
end
return {1,0,0}
"""


class DescriptionsUnavailable(RuntimeError):
    pass


class DescriptionBusy(RuntimeError):
    def __init__(self, retry_after: int = 5) -> None:
        self.retry_after = retry_after


class DescriptionNotPublic(RuntimeError):
    pass


class DescriptionInputUnavailable(RuntimeError):
    pass


def _item(repo: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"repo": repo, "status": status, "descriptionZh": "", "source": "aigcnews", **extra}


def _profile(repo: str, game_details: bool) -> str:
    return "game-v1:" + repo if game_details else repo


def _cached(value: Any, repo: str) -> dict[str, Any]:
    try:
        result = json.loads(value) if value else {}
    except (ValueError, TypeError):
        return {}
    return result if isinstance(result, dict) and result.get("repo") == repo else {}


def _game_fields(cached: dict[str, Any], now: float) -> dict[str, Any]:
    result = {key: cached.get(key, "") for key in ("gameNameZh", "gameNameOriginal", "posterUrl", "posterSourceUrl", "posterKind")}
    result["detailsVersion"] = 1
    # Internal cache revision; response models intentionally omit this field.
    result["identityEvidenceVersion"] = 2 if cached.get("identityEvidenceVersion") == 2 else 0
    result["posterSearchVersion"] = 1 if cached.get("posterSearchVersion") == 1 else 0
    status = cached.get("posterStatus", "ready" if result["posterUrl"] else "missing")
    result["posterStatus"] = status if status in {"ready", "missing", "unavailable"} else "missing"
    retry_at = cached.get("posterRetryAt", 0)
    result["posterRetryAfter"] = max(0, math.ceil(retry_at - now)) if isinstance(retry_at, (int, float)) and math.isfinite(retry_at) else 0
    # Earlier web-poster releases marked multi-game projects as "searched"
    # without executing a single tool. Let those records enter the project
    # artwork lookup once, instead of preserving a misleading one-hour wait.
    if result["posterStatus"] == "missing" and not result["gameNameOriginal"] and not cached.get("posterTrace"):
        result.update(posterSearchVersion=0, posterRetryAfter=0)
    return result


def _needs_poster(item: dict[str, Any], refresh: bool = False, web: bool = True) -> bool:
    if item.get("status") != "ready" or item.get("detailsVersion") != 1:
        return False
    if not item.get("gameNameOriginal"):
        if not web or not _chinese(item.get("descriptionZh")):
            return False
        try:
            normalize_description_repo(item.get("repo"))
        except ValueError:
            return False
    if item.get("posterSearchVersion", 0) == 0 and (refresh or (web and not item.get("posterUrl"))):
        return True
    return bool(item.get("posterRetryAfter", 0) <= 0 and (refresh or not item.get("posterUrl")))


def _cached_request(item: dict[str, Any], game_details: bool, refresh: bool = False, web: bool = True) -> bool:
    return bool((item["status"] in {"ready", "pending"} or item.get("retryAfter", 0) > 0) and not (game_details and _needs_poster(item, refresh, web)))


def _chinese(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) > 512 or not re.search(r"[\u3400-\u9fff]", text) or re.search(r"[\u3040-\u30ff]", text):
        return ""
    return text


async def _bounded_response(client: httpx.AsyncClient, path: str, *, raw: bool = False) -> bytes | None:
    headers = _build_headers()
    if raw:
        headers["Accept"] = "application/vnd.github.raw+json"
    async with client.stream("GET", "https://api.github.com" + path, headers=headers) as response:
        if response.status_code == 404:
            return None
        # Even redirects to another GitHub URL are not followed. Private or
        # renamed repositories cannot turn a caller-supplied name into a proxy.
        if response.status_code != 200:
            raise DescriptionInputUnavailable("GitHub 暂时无法读取，请稍后重试。")
        body = bytearray()
        limit = 65536 if raw else 262144
        async for part in response.aiter_bytes():
            body.extend(part)
            if len(body) > limit:
                raise DescriptionInputUnavailable("仓库资料过大，暂时无法生成简介。")
        return bytes(body)


def _readme_document(raw: bytes, *, allow_excerpt: bool = False) -> tuple[str, str]:
    try:
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("encoding") != "base64" or not isinstance(document.get("content"), str):
            raise ValueError("invalid README encoding")
        path = safe_repository_path(document.get("path"))
        if not path or document.get("type", "file") != "file":
            raise ValueError("invalid README path")
        content = base64.b64decode("".join(document["content"].split()), validate=True)
        if len(content) > 65536:
            if not allow_excerpt:
                raise ValueError("oversized README")
            # The JSON response is already capped at 256 KiB. Keep a bounded
            # primary excerpt rather than rejecting an otherwise valid game.
            content = content[:65536]
    except (ValueError, UnicodeError) as exc:
        raise DescriptionInputUnavailable("GitHub 返回的 README 资料无效或过大。") from exc
    return path, content.decode("utf-8", errors="replace")[:12000]


class _ReadmeLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.links.extend(value for name, value in attrs if name.lower() == "href" and value)


def _localized_readme_link(repo: str, branch: str, readme_path: str, text: str) -> str:
    # Follow an evidenced translation only when the default document lacks
    # enough prose to establish the game. Never enumerate repository contents.
    if len(text.strip()) >= 1500 or not branch:
        return ""
    visible = re.sub(r"<!--[\s\S]*?-->|```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`", "", text)
    prose = re.sub(r"\]\([^\n)]*\)|<[^>]*>|https?://\S+", " ", visible)
    if re.search(r"\b(?:games?|gameplay)\b|游戏", prose, re.I):
        return ""
    links = [match[1].strip("<>") for match in re.finditer(r"(?<!!)\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[\"'][^\n]*?[\"'])?\s*\)", visible)]
    parser = _ReadmeLinks()
    parser.feed(visible)
    links.extend(parser.links)
    paths = []
    for value in links:
        value = html.unescape(value)
        if re.search(r"[\x00-\x20\x7f\\%]", value):
            continue
        try:
            parts = urlsplit(value)
        except ValueError:
            continue
        if parts.query or parts.fragment:
            continue
        if parts.scheme or parts.netloc:
            prefix = f"/{repo}/blob/"
            if parts.scheme != "https" or parts.netloc != "github.com" or not parts.path.casefold().startswith(prefix.casefold()):
                continue
            remainder = parts.path[len(prefix):]
            if not remainder.startswith(branch + "/"):
                continue
            path = remainder[len(branch) + 1:]
        else:
            if parts.path.startswith("/"):
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(readme_path), parts.path))
        if not safe_repository_path(path) or path.casefold() == readme_path.casefold():
            continue
        name = posixpath.basename(path)
        if not re.fullmatch(r"readme[._-][a-z]{2,3}(?:[._-][a-z]{2,4})?\.(?:md|markdown|rst|txt)", name, re.I):
            # Some repositories put translations in docs/zh/README.md.
            if not re.fullmatch(r"readme\.(?:md|markdown|rst|txt)", name, re.I) or not any(
                re.fullmatch(r"[a-z]{2}(?:[-_][a-z]{2,4})?", part, re.I) for part in path.split("/")[:-1]
            ):
                continue
        paths.append(path)
    # Prefer Chinese evidence for Chinese identity enrichment, retaining the
    # document's order within each language group. At most one path is fetched.
    return next(iter(sorted(paths, key=lambda path: not re.search(r"(?:^|[./_-])(?:zh|cn)(?:[./_-]|$)", path, re.I))), "")


async def _supplement_localized_readme(client: httpx.AsyncClient, metadata: dict[str, Any]) -> None:
    repo, branch = metadata["full_name"], metadata["default_branch"]
    path = _localized_readme_link(repo, branch, metadata["readme_path"], metadata["readme_text"])
    if not path:
        return
    try:
        raw = await _bounded_response(client, f"/repos/{repo}/contents/{quote(path, safe='/')}?ref={quote(branch, safe='')}")
        if raw is None:
            return
        actual_path, text = _readme_document(raw)
        if actual_path != path:
            return
    except (DescriptionInputUnavailable, httpx.HTTPError):
        # An optional translation must not erase a useful primary README.
        return
    metadata["readme_localized_path"] = path
    metadata["readme_text"] = (metadata["readme_text"] + f"\n\nLinked README: {path}\n\n" + text)[:12000]


async def fetch_public_repository(repo: str, *, game_details: bool = False, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    repo = normalize_description_repo(repo)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False,
        trust_env=True, transport=transport,
    ) as client:
        raw = await _bounded_response(client, "/repos/" + repo)
        if raw is None:
            raise DescriptionNotPublic("无法读取此公开仓库。")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise DescriptionInputUnavailable("GitHub 返回的仓库资料无效。") from exc
        if not isinstance(data, dict) or data.get("private") is not False or data.get("visibility", "public") != "public":
            raise DescriptionNotPublic("无法读取此公开仓库。")
        if str(data.get("full_name") or "").lower() != repo:
            raise DescriptionNotPublic("仓库名称已变化，请使用当前的公开仓库地址。")
        description = data.get("description")
        description = description[:4096] if isinstance(description, str) else ""
        topics = data.get("topics")
        topics = [topic[:80] for topic in topics[:30] if isinstance(topic, str)] if isinstance(topics, list) else []
        metadata = {"full_name": repo, "description": description, "topics": topics}
        if game_details:
            branch = safe_repository_path(data.get("default_branch"))
            metadata.update(default_branch=branch, image_candidates=[])
            path = "/repos/" + repo + "/readme"
            if branch:
                path += "?ref=" + quote(branch, safe="")
            raw_readme = await _bounded_response(client, path)
            if raw_readme:
                readme_path, text = _readme_document(raw_readme, allow_excerpt=True)
                metadata.update(readme_status="succeeded", readme_text=text, readme_path=readme_path)
                metadata["image_candidates"] = image_candidates(repo, branch, readme_path, text)
                await _supplement_localized_readme(client, metadata)
        elif not description.strip():
            readme = await _bounded_response(client, "/repos/" + repo + "/readme", raw=True)
            if readme:
                metadata.update(readme_status="succeeded", readme_text=readme.decode("utf-8", errors="replace")[:12000])
        if not description.strip() and not metadata.get("readme_text", "").strip():
            raise DescriptionInputUnavailable("上游没有足够的简介或 README，暂时无法生成可靠的中文说明。")
        return metadata


async def charge_generation(redis: Any, authorization: McpAuthorizationContext) -> None:
    if authorization.role == "admin":
        return
    member = authorization.membership_tier == "member"
    limits = (
        quota.API_MEMBER_DAILY_SEARCH_QUOTA if member else quota.API_FREE_DAILY_SEARCH_QUOTA,
        quota.API_MEMBER_MONTHLY_SEARCH_QUOTA if member else quota.API_FREE_MONTHLY_SEARCH_QUOTA,
    )
    identity = f"user:{authorization.user_id}"
    result = await redis.eval(
        _CHARGE, 2,
        f"{RATE_LIMIT_PREFIX}{quota.API_QUOTA_DAILY_BUCKET}:{identity}",
        f"{RATE_LIMIT_PREFIX}{quota.API_QUOTA_MONTHLY_BUCKET}:{identity}",
        limits[0], quota.API_QUOTA_DAILY_WINDOW_SECONDS,
        limits[1], quota.API_QUOTA_MONTHLY_WINDOW_SECONDS,
    )
    if not isinstance(result, (list, tuple)) or len(result) != 3:
        raise DescriptionsUnavailable("中文简介服务暂时不可用。")
    if int(result[0]) != 1:
        index = int(result[1]) - 1
        if index not in (0, 1):
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        raise quota.ApiQuotaExceededError(
            quota_scope="daily" if index == 0 else "monthly", tier=authorization.membership_tier,
            limit=limits[index], retry_after=max(1, int(result[2])), identity_kind="user",
        )


class ProjectDescriptionsService:
    def __init__(
        self, describe: Callable[[dict[str, Any]], Awaitable[str]], *,
        describe_game: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        repository: Any = None,
        fetch: Callable[..., Awaitable[dict[str, Any]]] = fetch_public_repository,
        fetch_poster: Callable[[str], Awaitable[dict[str, str] | None]] | None = None,
        research_poster: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        poster_exists: Callable[[str], bool] = cached_poster_exists,
        clock: Callable[[], float] = time.time,
        job_seconds: float = JOB_SECONDS,
    ) -> None:
        self.repository = repository or PostgresProjectDescriptionRepository()
        self.describe = describe
        self.describe_game = describe_game
        self.fetch = fetch
        self.fetch_poster = fetch_poster
        # Explicit legacy fetch injection retains the old pure lookup test
        # contract. Production defaults to the executed web-research agent.
        self.research_poster = research_poster or (research_game_poster if fetch_poster is None else None)
        self.poster_exists = poster_exists
        self.clock = clock
        self.job_seconds = min(float(job_seconds), JOB_SECONDS)

    async def _lookup(self, repos: list[str], redis: Any, game_details: bool = False) -> tuple[list[dict[str, Any]], set[str]]:
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        catalog = await asyncio.wait_for(asyncio.to_thread(self.repository.lookup, repos), timeout=4)
        values = await redis.mget([PREFIX + "cache:" + _profile(repo, game_details) for repo in repos])
        legacy = await redis.mget([PREFIX + "cache:" + repo for repo in repos]) if game_details else [None] * len(repos)
        items, blocked = [], set()
        for repo, value, old in zip(repos, values, legacy, strict=True):
            known = catalog.get(repo, {})
            if known.get("blocked"):
                blocked.add(repo)
                items.append(_item(repo, "missing"))
                continue
            description = _chinese(known.get("descriptionZh"))
            if description and not game_details:
                items.append(_item(repo, "ready", descriptionZh=description))
                continue
            cached = _cached(value, repo)
            if game_details and is_cached_poster_url(cached.get("posterUrl")) and not await asyncio.to_thread(self.poster_exists, cached["posterUrl"]):
                # GET performs only a local stat, never searches/downloads or
                # charges quota. Cache expiry must not leave a forever-ready
                # broken image; POST can repair it after the current cooldown.
                cached = {**cached, "posterUrl": "", "posterSourceUrl": "", "posterKind": "",
                          "posterStatus": "missing" if cached.get("posterStatus") == "ready" else cached.get("posterStatus", "missing")}
            if game_details and not description:
                previous = _cached(old, repo)
                if previous.get("status") == "ready":
                    description = _chinese(previous.get("descriptionZh"))
            status = cached.get("status")
            if status == "ready" and _chinese(cached.get("descriptionZh")) and (not game_details or cached.get("detailsVersion") == 1):
                details = _game_fields(cached, self.clock()) if game_details else {}
                items.append(_item(repo, "ready", descriptionZh=cached["descriptionZh"], **details))
            elif game_details and status == "pending" and cached.get("posterOnly") is True and cached.get("detailsVersion") == 1 and _chinese(cached.get("descriptionZh")):
                deadline = cached.get("deadline", 0)
                deadline = deadline if isinstance(deadline, (int, float)) and math.isfinite(deadline) else 0
                if deadline > self.clock():
                    details = {**_game_fields(cached, self.clock()), "posterStatus": "unavailable", "posterRetryAfter": 3}
                    items.append(_item(repo, "pending", descriptionZh=cached["descriptionZh"], retryAfter=3, **details))
                else:
                    # A process can die without finalizing its lease. Preserve
                    # verified text and allow a later poster-only retry after
                    # a bounded cooldown, never a fresh model generation.
                    details = _game_fields({**cached, "posterStatus": "unavailable", "posterRetryAt": deadline + POSTER_UNAVAILABLE_SECONDS}, self.clock())
                    items.append(_item(repo, "ready", descriptionZh=cached["descriptionZh"], **details))
            elif status == "pending":
                deadline = cached.get("deadline", 0)
                if isinstance(deadline, (int, float)) and deadline > self.clock():
                    items.append(_item(repo, "pending", descriptionZh=description, retryAfter=3))
                else:
                    items.append(_item(repo, "failed", descriptionZh=description, error="生成超时，请重试。", retryAfter=0))
            elif status == "failed":
                retry_at = cached.get("retryAt", 0)
                retry = max(0, math.ceil(retry_at - self.clock())) if isinstance(retry_at, (int, float)) else 0
                items.append(_item(repo, "failed", descriptionZh=description, error=str(cached.get("error") or "生成失败，请重试。")[:200], retryAfter=retry))
            else:
                items.append(_item(repo, "missing", descriptionZh=description))
        return items, blocked

    async def read(self, repos: list[str], *, redis: Any, client_ip: str, game_details: bool = False) -> list[dict[str, Any]]:
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        await hit_rate_limit(redis, action="projects.descriptions.read", identity=f"ip:{client_ip}", limit=READS_PER_MINUTE, window_seconds=60)
        return (await self._lookup(repos, redis, game_details))[0]

    async def _release(self, redis: Any, key: str, token: str) -> None:
        try:
            await redis.eval(_RELEASE, 1, key, token)
        except Exception:
            # Bounded leases expire even if Redis disappears during cleanup.
            pass

    async def request(self, repo: str, *, redis: Any, authorization: McpAuthorizationContext, operations: Any, game_details: bool = False, refresh_poster: bool = False) -> dict[str, Any]:
        if refresh_poster and not game_details:
            raise ValueError("refresh_poster requires game_details")
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        await hit_rate_limit(redis, action="projects.descriptions.request", identity=f"user:{authorization.user_id}", limit=POSTS_PER_MINUTE, window_seconds=60)
        existing, blocked = await self._lookup([repo], redis, game_details)
        if blocked:
            raise DescriptionNotPublic("无法读取此公开仓库。")
        item = existing[0]
        web = self.research_poster is not None
        if _cached_request(item, game_details, refresh_poster, web):
            return item
        token = secrets.token_hex(16)
        profile = _profile(repo, game_details)
        lock_key = PREFIX + "lock:" + profile
        if not await redis.set(lock_key, token, nx=True, ex=LEASE_SECONDS):
            return {**item, "status": "pending", "retryAfter": 3} if game_details and _needs_poster(item, refresh_poster, web) else _item(repo, "pending", retryAfter=3)
        slot, submitted = "", False
        try:
            # Another worker may have finished between the first lookup and NX.
            second_items, second_blocked = await self._lookup([repo], redis, game_details)
            if second_blocked:
                raise DescriptionNotPublic("无法读取此公开仓库。")
            second = second_items[0]
            if _cached_request(second, game_details, refresh_poster, web):
                return second
            for index in range(MAX_CONCURRENT_GENERATIONS):
                candidate = PREFIX + f"slot:{index}"
                if await redis.set(candidate, token, nx=True, ex=LEASE_SECONDS):
                    slot = candidate
                    break
            if not slot:
                raise DescriptionBusy()
            poster_only = game_details and _needs_poster(second, refresh_poster, web)
            if not poster_only or self.research_poster is not None:
                await charge_generation(redis, authorization)
            pending_item = {**second, "status": "pending", "posterStatus": "unavailable", "posterRetryAfter": 3} if poster_only else _item(repo, "pending")
            pending = {**pending_item, "token": token, "deadline": self.clock() + self.job_seconds + 5}
            if poster_only:
                pending["posterOnly"] = True
                if self.research_poster is not None:
                    pending["posterSearchVersion"] = 1
            if not await redis.set(PREFIX + "cache:" + profile, json.dumps(pending), ex=READY_TTL):
                raise DescriptionsUnavailable("无法保存生成任务，请稍后重试。")
            if poster_only:
                repair_identity = bool(refresh_poster and self.research_poster is not None and not second.get("gameNameOriginal")
                                       and second.get("identityEvidenceVersion", 0) < 2)
                submitted = bool(operations.submit(self._generate_poster, repo, token, slot, redis, second, repair_identity))
            else:
                submitted = bool(operations.submit(self._generate, repo, token, slot, redis, game_details, second.get("descriptionZh", "")))
            if not submitted:
                failed = self._poster_failure(second) if poster_only else _item(repo, "failed", error="后台正在停止，请稍后重试。", retryAt=self.clock() + RETRY_SECONDS)
                await self._finish(redis, repo, token, failed, game_details)
                raise DescriptionsUnavailable("后台正在停止，请稍后重试。")
            return {**pending_item, "retryAfter": 3}
        finally:
            if not submitted:
                await self._release(redis, lock_key, token)
                if slot:
                    await self._release(redis, slot, token)

    async def _finish(self, redis: Any, repo: str, token: str, item: dict[str, Any], game_details: bool = False) -> None:
        profile = _profile(repo, game_details)
        await redis.eval(_FINISH, 2, PREFIX + "lock:" + profile, PREFIX + "cache:" + profile, token, json.dumps(item, ensure_ascii=False), READY_TTL)

    def _poster_failure(self, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "status": "ready", "posterStatus": "unavailable", "posterRetryAt": self.clock() + POSTER_UNAVAILABLE_SECONDS,
                **({"posterSearchVersion": 1} if self.research_poster is not None else {})}

    async def _fill_poster(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.research_poster is not None:
            try:
                result = await self.research_poster(item)
                status = result.get("posterStatus")
                if status not in {"ready", "missing", "unavailable"}:
                    return self._poster_failure(item)
                fields = {}
                if status == "ready":
                    if not re.fullmatch(r"https://aigcnews\.cn/api/media/site/game-posters/[0-9a-f]{64}\.jpg", str(result.get("posterUrl") or "")):
                        return self._poster_failure(item)
                    fields = {key: result[key] for key in ("posterUrl", "posterSourceUrl", "posterKind")}
                delay = {"ready": SEARCH_READY_SECONDS, "missing": SEARCH_MISSING_SECONDS, "unavailable": POSTER_UNAVAILABLE_SECONDS}[status]
                return {**item, **fields, "posterStatus": status, "posterSearchVersion": 1,
                        "posterRetryAt": self.clock() + delay, "posterTrace": result.get("posterTrace", [])}
            except asyncio.CancelledError:
                raise
            except Exception:
                return self._poster_failure(item)
        if item.get("posterUrl"):
            return {**item, "posterStatus": "ready", "posterRetryAt": 0}
        try:
            poster = await self.fetch_poster(item["gameNameOriginal"]) if item.get("gameNameOriginal") else None
            if poster:
                return {**item, **{key: poster[key] for key in ("posterUrl", "posterSourceUrl", "posterKind")}, "posterStatus": "ready", "posterRetryAt": 0}
        except Exception:
            # External service failures must never erase verified names/text or
            # expose its response, query URL or transport credentials.
            return self._poster_failure(item)
        return {**item, "posterStatus": "missing", "posterRetryAt": self.clock() + POSTER_MISSING_SECONDS}

    async def _refresh_missing_identity(self, existing: dict[str, Any]) -> dict[str, Any]:
        """One user-requested repair for names rejected by old evidence checks."""
        if self.describe_game is None:
            return existing
        try:
            async with asyncio.timeout(40):
                metadata = await self.fetch(existing["repo"], game_details=True)
                data = await self.describe_game(metadata)
                if not isinstance(data, dict):
                    return existing
                details = normalize_game_details(data, metadata)
                # Retain the verified description and image even when identity
                # remains a multi-game project. Do not restore README hotlinks.
                return {**existing, **{key: details[key] for key in ("gameNameOriginal", "gameNameZh", "identityEvidenceVersion")}}
        except asyncio.CancelledError:
            raise
        except Exception:
            return existing

    async def _generate_poster(self, repo: str, token: str, slot: str, redis: Any, existing: dict[str, Any], repair_identity: bool = False) -> None:
        item = self._poster_failure(existing)

        async def generate() -> dict[str, Any]:
            nonlocal item
            current = await self._refresh_missing_identity(existing) if repair_identity else existing
            item = self._poster_failure(current)
            return await self._fill_poster(current)

        try:
            item = await asyncio.wait_for(generate(), timeout=self.job_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            try:
                await self._finish(redis, repo, token, item, True)
            except Exception:
                pass
            await self._release(redis, slot, token)

    async def _generate(self, repo: str, token: str, slot: str, redis: Any, game_details: bool = False, previous_description: str = "") -> None:
        generated_item: dict[str, Any] | None = None

        async def generate() -> dict[str, Any]:
            nonlocal generated_item
            if game_details:
                metadata = await self.fetch(repo, game_details=True)
                if self.describe_game is None:
                    raise DescriptionsUnavailable("游戏资料富化暂时不可用。")
                data = await self.describe_game(metadata)
                if not isinstance(data, dict) or not isinstance(data.get("description_zh"), str):
                    raise DescriptionInputUnavailable("未生成可靠的游戏资料，请稍后重试。")
                description = _chinese(data["description_zh"]) or _chinese(previous_description)
                details = normalize_game_details(data, metadata)
            else:
                metadata = await self.fetch(repo)
                description = _chinese(await self.describe(metadata))
                details = {}
            if not description:
                raise DescriptionInputUnavailable("未生成可靠的中文简介，请稍后重试。")
            generated_item = _item(repo, "ready", descriptionZh=description, **details)
            return await self._fill_poster(generated_item) if game_details else generated_item

        try:
            item = await asyncio.wait_for(generate(), timeout=self.job_seconds)
        except asyncio.CancelledError:
            item = self._poster_failure(generated_item) if game_details and generated_item else _item(repo, "failed", error="生成已中断，请重试。", retryAt=self.clock() + RETRY_SECONDS)
            raise
        except (DescriptionInputUnavailable, DescriptionNotPublic) as exc:
            item = _item(repo, "failed", error=str(exc), retryAt=self.clock() + RETRY_SECONDS)
        except TimeoutError:
            item = self._poster_failure(generated_item) if game_details and generated_item else _item(repo, "failed", error="生成超时，请重试。", retryAt=self.clock() + RETRY_SECONDS)
        except Exception:
            # Provider failures can include credentials/URLs; never return them.
            item = _item(repo, "failed", error="中文简介生成暂时失败，请稍后重试。", retryAt=self.clock() + RETRY_SECONDS)
        finally:
            try:
                await self._finish(redis, repo, token, item, game_details)
            except Exception:
                pass
            await self._release(redis, slot, token)
