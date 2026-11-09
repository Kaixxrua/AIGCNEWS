"""Bounded on-demand descriptions using the existing model, outside the public catalog.

Redis is required: it owns cache, leases and the shared programmatic quota. No
request can submit generation after a failed Redis operation. Workers use fenced
leases so an expired worker cannot overwrite a newer result.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from backend.app.models.schema_project_descriptions import normalize_description_repo
from backend.app.repositories.postgres_project_descriptions import PostgresProjectDescriptionRepository
from backend.app.services.api_access import quota
from backend.app.services.auth.rate_limit import RATE_LIMIT_PREFIX, hit_rate_limit
from backend.app.services.ingestion.source_github import _build_headers
from backend.app.services.mcp.inbound.context import McpAuthorizationContext

READY_TTL = 7 * 86400
RETRY_SECONDS = 60
JOB_SECONDS = 90
LEASE_SECONDS = 120
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


async def fetch_public_repository(repo: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
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
        if not description.strip():
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
        repository: Any = None,
        fetch: Callable[[str], Awaitable[dict[str, Any]]] = fetch_public_repository,
        clock: Callable[[], float] = time.time,
        job_seconds: float = JOB_SECONDS,
    ) -> None:
        self.repository = repository or PostgresProjectDescriptionRepository()
        self.describe = describe
        self.fetch = fetch
        self.clock = clock
        self.job_seconds = min(float(job_seconds), JOB_SECONDS)

    async def _lookup(self, repos: list[str], redis: Any) -> tuple[list[dict[str, Any]], set[str]]:
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        catalog = await asyncio.wait_for(asyncio.to_thread(self.repository.lookup, repos), timeout=4)
        values = await redis.mget([PREFIX + "cache:" + repo for repo in repos])
        items, blocked = [], set()
        for repo, value in zip(repos, values, strict=True):
            known = catalog.get(repo, {})
            if known.get("blocked"):
                blocked.add(repo)
                items.append(_item(repo, "missing"))
                continue
            description = _chinese(known.get("descriptionZh"))
            if description:
                items.append(_item(repo, "ready", descriptionZh=description))
                continue
            try:
                cached = json.loads(value) if value else {}
            except (ValueError, TypeError):
                cached = {}
            if not isinstance(cached, dict) or cached.get("repo") != repo:
                cached = {}
            status = cached.get("status")
            if status == "ready" and _chinese(cached.get("descriptionZh")):
                items.append(_item(repo, "ready", descriptionZh=cached["descriptionZh"]))
            elif status == "pending":
                deadline = cached.get("deadline", 0)
                if isinstance(deadline, (int, float)) and deadline > self.clock():
                    items.append(_item(repo, "pending", retryAfter=3))
                else:
                    items.append(_item(repo, "failed", error="生成超时，请重试。", retryAfter=0))
            elif status == "failed":
                retry_at = cached.get("retryAt", 0)
                retry = max(0, math.ceil(retry_at - self.clock())) if isinstance(retry_at, (int, float)) else 0
                items.append(_item(repo, "failed", error=str(cached.get("error") or "生成失败，请重试。")[:200], retryAfter=retry))
            else:
                items.append(_item(repo, "missing"))
        return items, blocked

    async def read(self, repos: list[str], *, redis: Any, client_ip: str) -> list[dict[str, Any]]:
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        await hit_rate_limit(redis, action="projects.descriptions.read", identity=f"ip:{client_ip}", limit=READS_PER_MINUTE, window_seconds=60)
        return (await self._lookup(repos, redis))[0]

    async def _release(self, redis: Any, key: str, token: str) -> None:
        try:
            await redis.eval(_RELEASE, 1, key, token)
        except Exception:
            # Bounded leases expire even if Redis disappears during cleanup.
            pass

    async def request(self, repo: str, *, redis: Any, authorization: McpAuthorizationContext, operations: Any) -> dict[str, Any]:
        if redis is None:
            raise DescriptionsUnavailable("中文简介服务暂时不可用。")
        await hit_rate_limit(redis, action="projects.descriptions.request", identity=f"user:{authorization.user_id}", limit=POSTS_PER_MINUTE, window_seconds=60)
        existing, blocked = await self._lookup([repo], redis)
        if blocked:
            raise DescriptionNotPublic("无法读取此公开仓库。")
        item = existing[0]
        if item["status"] in {"ready", "pending"} or item.get("retryAfter", 0) > 0:
            return item
        token = secrets.token_hex(16)
        lock_key = PREFIX + "lock:" + repo
        if not await redis.set(lock_key, token, nx=True, ex=LEASE_SECONDS):
            return _item(repo, "pending", retryAfter=3)
        slot, submitted = "", False
        try:
            # Another worker may have finished between the first lookup and NX.
            second_items, second_blocked = await self._lookup([repo], redis)
            if second_blocked:
                raise DescriptionNotPublic("无法读取此公开仓库。")
            second = second_items[0]
            if second["status"] in {"ready", "pending"} or second.get("retryAfter", 0) > 0:
                return second
            for index in range(MAX_CONCURRENT_GENERATIONS):
                candidate = PREFIX + f"slot:{index}"
                if await redis.set(candidate, token, nx=True, ex=LEASE_SECONDS):
                    slot = candidate
                    break
            if not slot:
                raise DescriptionBusy()
            await charge_generation(redis, authorization)
            pending = {**_item(repo, "pending"), "token": token, "deadline": self.clock() + self.job_seconds + 5}
            if not await redis.set(PREFIX + "cache:" + repo, json.dumps(pending), ex=READY_TTL):
                raise DescriptionsUnavailable("无法保存生成任务，请稍后重试。")
            submitted = bool(operations.submit(self._generate, repo, token, slot, redis))
            if not submitted:
                await self._finish(redis, repo, token, _item(repo, "failed", error="后台正在停止，请稍后重试。", retryAt=self.clock() + RETRY_SECONDS))
                raise DescriptionsUnavailable("后台正在停止，请稍后重试。")
            return _item(repo, "pending", retryAfter=3)
        finally:
            if not submitted:
                await self._release(redis, lock_key, token)
                if slot:
                    await self._release(redis, slot, token)

    async def _finish(self, redis: Any, repo: str, token: str, item: dict[str, Any]) -> None:
        await redis.eval(_FINISH, 2, PREFIX + "lock:" + repo, PREFIX + "cache:" + repo, token, json.dumps(item, ensure_ascii=False), READY_TTL)

    async def _generate(self, repo: str, token: str, slot: str, redis: Any) -> None:
        async def generate() -> str:
            metadata = await self.fetch(repo)
            description = _chinese(await self.describe(metadata))
            if not description:
                raise DescriptionInputUnavailable("未生成可靠的中文简介，请稍后重试。")
            return description

        try:
            description = await asyncio.wait_for(generate(), timeout=self.job_seconds)
            item = _item(repo, "ready", descriptionZh=description)
        except asyncio.CancelledError:
            item = _item(repo, "failed", error="生成已中断，请重试。", retryAt=self.clock() + RETRY_SECONDS)
            raise
        except (DescriptionInputUnavailable, DescriptionNotPublic) as exc:
            item = _item(repo, "failed", error=str(exc), retryAt=self.clock() + RETRY_SECONDS)
        except TimeoutError:
            item = _item(repo, "failed", error="生成超时，请重试。", retryAt=self.clock() + RETRY_SECONDS)
        except Exception:
            # Provider failures can include credentials/URLs; never return them.
            item = _item(repo, "failed", error="中文简介生成暂时失败，请稍后重试。", retryAt=self.clock() + RETRY_SECONDS)
        finally:
            try:
                await self._finish(redis, repo, token, item)
            except Exception:
                pass
            await self._release(redis, slot, token)
