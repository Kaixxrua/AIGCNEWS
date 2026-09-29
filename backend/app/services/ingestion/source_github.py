from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Set

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TRENDING_BASE = "https://github.com/trending"

_TOPICS = [
    "llm",
    "ai",
    "agent",
    "large-language-model",
    "generative-ai",
]

_PER_TOPIC_LIMIT = 10

# GraphQL 批量指标：单批遇网络抖动或上游 499/5xx 时退避重试；连续多批
# 重试后仍失败视为 GitHub 侧故障，停止批量抓取。
_GRAPHQL_BATCH_MAX_ATTEMPTS = 3
_GRAPHQL_RETRY_BACKOFF = 5.0
_GRAPHQL_TRANSIENT_STATUS_CODES = frozenset({499, 500, 502, 503, 504})
_GRAPHQL_MAX_CONSECUTIVE_FAILED_CHUNKS = 3
# GraphQL 已应答但节点为空的仓库（下架/改名，日刷约数百个）总是退 REST
# 判定 404 与改名；整批失败没抓到的仓库只在量小时退 REST 补抓——上万个
# 仓库逐个 REST 既超 5000 次/小时配额，又要占 GitHub 锁几十分钟。
_REST_FALLBACK_MAX_UNFETCHED = 200


def _get_token() -> str:
    # settings.github_token 由 pydantic-settings 自动读取 GITHUB_TOKEN 环境变量。
    return settings.github_token.strip()


def _build_headers(use_token: bool = True) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if use_token:
        token = _get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _search_repos(
    query: str,
    limit: int,
    client: httpx.Client,
    use_token: bool = True,
    sort: str = "stars",
) -> List[dict]:
    params = {
        "q": query,
        "sort": sort,
        "order": "desc",
        "per_page": min(limit, 30),
        "page": 1,
    }

    resp = client.get(
        f"{GITHUB_API_BASE}/search/repositories",
        headers=_build_headers(use_token=use_token),
        params=params,
    )

    if resp.status_code == 401 and use_token:
        logger.warning("[GitHub] Token 401，降级匿名重试 (query=%s)...", query[:60])
        return _search_repos(query, limit, client, use_token=False, sort=sort)

    if resp.status_code in (403, 429):
        logger.warning(
            "[GitHub] 限流 %d (query=%s)，跳过。", resp.status_code, query[:60]
        )
        return []

    try:
        resp.raise_for_status()
    except Exception:
        logger.warning(
            "[GitHub] HTTP %d (query=%s)，跳过。", resp.status_code, query[:60]
        )
        return []

    items = resp.json().get("items", [])
    logger.debug("[GitHub] query=%s，命中 %d 条。", query[:60], len(items))
    return items


def _clean_readme_text(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^\)]*\)", " ", text)
    text = re.sub(r"[#>*_\-]{1,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass(frozen=True)
class GitHubReadmeSnapshot:
    status: Literal["succeeded", "not_modified", "not_found", "rate_limited", "failed"]
    text: str = ""
    etag: str = ""
    sha256: str = ""
    error: str = ""
    rate_limit_remaining: int | None = None
    rate_limit_reset: str = ""
    logo_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitHubRepoMetricsResult:
    full_name: str
    status: Literal["succeeded", "not_found", "unknown"]
    metrics: dict[str, Any] | None = None
    http_status: int | None = None
    error: str = ""
    # True 表示本次成功响应经过了 GitHub 改名重定向（301/302）；
    # 此时 metrics["full_name"] 是改名后的权威名称，full_name 仍是请求名。
    was_redirected: bool = False
    # 成功响应到达的 UTC 时刻（ISO 8601）。一轮日刷要抓一到数小时，
    # 快照时间轴须按实际观测时刻而非开轮时刻；空串由调用方回退开轮时刻。
    observed_at: str = ""
    # True 表示本次 403/429 是配额限流（而非仓库级 403 如访问被封），
    # 批量补抓据此停止，不再逐个撞限流。
    rate_limited: bool = False


def _observed_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_github_readme_snapshot(
    full_name: str,
    client: httpx.Client,
    *,
    etag: str = "",
    max_chars: int = 40_000,
    use_token: bool = True,
) -> GitHubReadmeSnapshot:
    if not full_name or "/" not in full_name:
        return GitHubReadmeSnapshot(status="failed", error="invalid repository name")
    headers = _build_headers(use_token=use_token)
    if etag:
        headers["If-None-Match"] = etag
    try:
        resp = client.get(
            f"{GITHUB_API_BASE}/repos/{full_name}/readme",
            headers=headers,
        )
        if resp.status_code == 401 and use_token:
            return fetch_github_readme_snapshot(
                full_name,
                client,
                etag=etag,
                max_chars=max_chars,
                use_token=False,
            )
        remaining_raw = resp.headers.get("x-ratelimit-remaining")
        try:
            remaining = int(remaining_raw) if remaining_raw is not None else None
        except ValueError:
            remaining = None
        rate_limit_reset = resp.headers.get("x-ratelimit-reset", "")
        if resp.status_code == 304:
            return GitHubReadmeSnapshot(
                status="not_modified",
                etag=resp.headers.get("etag", etag),
                rate_limit_remaining=remaining,
                rate_limit_reset=rate_limit_reset,
            )
        if resp.status_code == 404:
            return GitHubReadmeSnapshot(
                status="not_found",
                rate_limit_remaining=remaining,
                rate_limit_reset=rate_limit_reset,
            )
        if resp.status_code in (403, 429):
            return GitHubReadmeSnapshot(
                status="rate_limited",
                error=f"GitHub API returned {resp.status_code}",
                rate_limit_remaining=remaining,
                rate_limit_reset=rate_limit_reset,
            )
        resp.raise_for_status()
        payload = resp.json()
        content = payload.get("content", "")
        if not content or payload.get("encoding") != "base64":
            return GitHubReadmeSnapshot(status="failed", error="README content is not base64")
        decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        from backend.app.services.ingestion.github_project_logos import discover_logos

        logos = discover_logos(decoded, str(payload.get("download_url") or ""))
        cleaned = _clean_readme_text(decoded)[: max(1, int(max_chars))]
        return GitHubReadmeSnapshot(
            status="succeeded",
            text=cleaned,
            etag=resp.headers.get("etag", ""),
            sha256=hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
            logo_candidates=logos,
            rate_limit_remaining=remaining,
            rate_limit_reset=rate_limit_reset,
        )
    except Exception as exc:
        logger.debug("[GitHub] README 抓取失败 %s: %s", full_name, exc)
        return GitHubReadmeSnapshot(status="failed", error=str(exc)[:1000])


def _fetch_readme(
    full_name: str,
    client: httpx.Client,
    use_token: bool = True,
) -> str:
    snapshot = fetch_github_readme_snapshot(
        full_name,
        client,
        max_chars=20_000,
        use_token=use_token,
    )
    return snapshot.text if snapshot.status == "succeeded" else ""


def _rest_community_metrics(item: Dict[str, Any]) -> tuple[int, bool]:
    if "subscribers_count" not in item:
        return 0, False
    return int(item.get("subscribers_count") or 0), True


def _parse_item(item: dict, client: httpx.Client, use_token: bool = True) -> dict:
    lang = item.get("language") or ""
    desc = item.get("description") or ""
    summary = f"{desc}  [Language: {lang}]".strip() if lang else desc
    topics = item.get("topics", [])
    full_name = item.get("full_name", item.get("name", ""))
    readme_text = (
        _fetch_readme(full_name, client, use_token=use_token) if full_name else ""
    )

    combined_abstract = summary
    if readme_text:
        combined_abstract = f"{summary}\n\nREADME:\n{readme_text}".strip()

    repo_id = str(item.get("node_id") or item.get("id", "") or full_name)
    watchers, community_metrics_complete = _rest_community_metrics(item)
    return {
        "repo_id": repo_id,
        "full_name": full_name,
        "title": full_name,
        "abstract": combined_abstract,
        "summary": summary,
        "description": desc,
        "readme": readme_text,
        "url": item.get("html_url", ""),
        "pdf_url": "",
        "source": "github",
        "score": float(item.get("stargazers_count", 0)),
        "tags": ([lang] if lang else []) + topics[:5],
        "topics": topics[:10],
        "published_date": (item.get("created_at") or "")[:10],
        "language": lang,
        "stars": int(item.get("stargazers_count", 0) or 0),
        "forks": int(item.get("forks_count", 0) or 0),
        "watchers": watchers,
        "community_metrics_complete": community_metrics_complete,
        "open_issues": int(item.get("open_issues_count", 0) or 0),
        "created_at": (item.get("created_at") or "")[:10],
        "pushed_at": (item.get("pushed_at") or "")[:10],
    }


def _check_token_valid(client: httpx.Client) -> bool:
    """仅在 token 缺失或探测请求明确 401 时判定无效。

    探测走 Search API（30 次/分钟），被限流或遇网络抖动说明不了 token 真伪；
    此前一律判无效，随后整轮 REST 请求改为匿名（60 次/小时）几乎全部 403。
    各调用方逐请求遇 401 仍会自行降级匿名。
    """
    token = _get_token()
    if not token:
        return False
    try:
        resp = client.get(
            f"{GITHUB_API_BASE}/search/repositories",
            headers=_build_headers(use_token=True),
            params={"q": "topic:llm", "per_page": 1},
        )
    except Exception as exc:
        logger.warning("[GitHub] Token 探测请求失败，仍按 token 有效访问: %s", exc)
        return True
    if resp.status_code == 401:
        logger.warning(
            "[GitHub] Token 对 Search API 无效（401），全程使用匿名访问。"
        )
        return False
    return True


def _is_rate_limited(resp: httpx.Response) -> bool:
    """区分配额限流与仓库级 403（如 Repository access blocked）。"""
    if resp.status_code == 429:
        return True
    if resp.status_code != 403:
        return False
    if resp.headers.get("x-ratelimit-remaining") == "0" or resp.headers.get("retry-after"):
        return True
    return "rate limit" in resp.text.lower()


def _fetch_trending_page(
    period: str,
    client: httpx.Client,
    language: Optional[str] = None,
) -> str:
    params = {"since": period}
    if language:
        params["l"] = language
    resp = client.get(
        GITHUB_TRENDING_BASE,
        params=params,
        headers={"User-Agent": "RAG-AIGC-Agent/1.0"},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def _parse_trending_repos(
    html: str, period: str, limit: int = 25
) -> List[Dict[str, object]]:
    from backend.app.services.ingestion.source_github_trending import (
        parse_github_trending_html,
    )

    return parse_github_trending_html(html, period=period, limit=limit)


def fetch_github_trending_repos(
    period: str = "daily", limit: int = 25
) -> List[Dict[str, object]]:
    period = period.lower().strip()
    if period not in {"daily", "weekly", "monthly"}:
        raise ValueError(f"Unsupported period: {period}")

    with httpx.Client(timeout=30, trust_env=True, follow_redirects=True) as client:
        html = _fetch_trending_page(period, client)
        repos = _parse_trending_repos(html, period=period, limit=limit)
        logger.info("[GitHub][Trending] period=%s -> %d repos", period, len(repos))
        return repos


def _parse_metrics_item(item: Dict[str, Any]) -> Dict[str, Any]:
    full_name = str(item.get("full_name") or item.get("name") or "").strip()
    lang = item.get("language") or ""
    topics = item.get("topics") if isinstance(item.get("topics"), list) else []
    watchers, community_metrics_complete = _rest_community_metrics(item)
    return {
        "repo_id": str(item.get("node_id") or item.get("id") or full_name),
        "full_name": full_name,
        "title": full_name,
        "url": item.get("html_url") or (f"https://github.com/{full_name}" if full_name else ""),
        "description": item.get("description") or "",
        "summary": item.get("description") or "",
        "language": lang,
        "topics": topics[:10],
        "tags": ([lang] if lang else []) + topics[:5],
        "stars": int(item.get("stargazers_count") or 0),
        "forks": int(item.get("forks_count") or 0),
        "watchers": watchers,
        "community_metrics_complete": community_metrics_complete,
        "open_issues": int(item.get("open_issues_count") or 0),
        "license_spdx_id": str((item.get("license") or {}).get("spdx_id") or ""),
        "created_at": (item.get("created_at") or "")[:10],
        "pushed_at": (item.get("pushed_at") or "")[:10],
    }


def fetch_github_repo_metrics(
    full_name: str,
    *,
    client: httpx.Client | None = None,
    use_token: bool | None = None,
) -> GitHubRepoMetricsResult:
    """Fetch lightweight metrics while preserving repository availability outcomes."""

    clean_name = str(full_name or "").strip()
    if not clean_name:
        return GitHubRepoMetricsResult(full_name="", status="unknown", error="invalid repository name")

    def _fetch(active_client: httpx.Client, active_use_token: bool) -> GitHubRepoMetricsResult:
        url = f"{GITHUB_API_BASE}/repos/{clean_name}"
        was_redirected = False
        # 最多跟随一次改名重定向。GitHub 仅在旧名未被占用时保留 301，
        # 因此跟随成功的响应必然属于同一仓库；旧名被他人重新注册时
        # 重定向消失（直接 200 新仓库或 404），绝不误判。
        for _ in range(2):
            resp = active_client.get(url, headers=_build_headers(use_token=active_use_token))
            if resp.status_code == 401 and active_use_token:
                return _fetch(active_client, False)
            if resp.status_code in (301, 302, 307, 308):
                location = resp.headers.get("location", "").strip()
                # 可跟随形态：/repos/{owner}/{new}（常规改名）与
                # /repositories/{id}（部分改名返回 ID 形态），均同 host 且一跳
                followable = location.startswith(f"{GITHUB_API_BASE}/repos/") or location.startswith(
                    f"{GITHUB_API_BASE}/repositories/"
                )
                if not was_redirected and followable:
                    url = location
                    was_redirected = True
                    continue
                logger.warning(
                    "[GitHub] 仓库指标抓取跳过 %s: HTTP %s 重定向不可跟随（location=%s）",
                    clean_name, resp.status_code, location[:120],
                )
                return GitHubRepoMetricsResult(
                    full_name=clean_name,
                    status="unknown",
                    http_status=resp.status_code,
                )
            if resp.status_code == 404:
                logger.warning("[GitHub] 仓库指标抓取未找到 %s: HTTP 404", clean_name)
                return GitHubRepoMetricsResult(
                    full_name=clean_name,
                    status="not_found",
                    http_status=404,
                )
            if resp.status_code in (403, 429):
                logger.warning("[GitHub] 仓库指标抓取跳过 %s: HTTP %s", clean_name, resp.status_code)
                return GitHubRepoMetricsResult(
                    full_name=clean_name,
                    status="unknown",
                    http_status=resp.status_code,
                    rate_limited=_is_rate_limited(resp),
                )
            resp.raise_for_status()
            metrics = _parse_metrics_item(resp.json())
            if was_redirected:
                logger.info(
                    "[GitHub] 仓库 %s 已改名为 %s（HTTP 301 跟随成功）",
                    clean_name, metrics.get("full_name") or "?",
                )
            return GitHubRepoMetricsResult(
                full_name=clean_name,
                status="succeeded",
                metrics=metrics,
                http_status=resp.status_code,
                was_redirected=was_redirected,
                observed_at=_observed_now(),
            )
        # 循环必然在两次迭代内返回；此处仅为满足类型检查
        return GitHubRepoMetricsResult(full_name=clean_name, status="unknown", error="unreachable")

    if client is not None:
        try:
            return _fetch(client, bool(use_token))
        except Exception as exc:
            logger.warning("[GitHub] 仓库指标抓取失败 %s: %s", clean_name, exc)
            return GitHubRepoMetricsResult(full_name=clean_name, status="unknown", error=str(exc))

    with httpx.Client(timeout=30, trust_env=True) as local_client:
        active_use_token = _check_token_valid(local_client) if use_token is None else bool(use_token)
        try:
            return _fetch(local_client, active_use_token)
        except Exception as exc:
            logger.warning("[GitHub] 仓库指标抓取失败 %s: %s", clean_name, exc)
            return GitHubRepoMetricsResult(full_name=clean_name, status="unknown", error=str(exc))


def _graphql_repo_alias(index: int) -> str:
    return f"r{index}"


def _graphql_escape(value: str) -> str:
    return json.dumps(value)[1:-1]


def _parse_graphql_repo(node: Dict[str, Any]) -> Dict[str, Any]:
    owner = (node.get("owner") or {}).get("login") or ""
    name = node.get("name") or ""
    full_name = f"{owner}/{name}" if owner and name else str(node.get("nameWithOwner") or "")
    topics = [
        edge.get("node", {}).get("topic", {}).get("name", "")
        for edge in ((node.get("repositoryTopics") or {}).get("edges") or [])
        if edge.get("node", {}).get("topic", {}).get("name")
    ]
    lang = (node.get("primaryLanguage") or {}).get("name") or ""
    return {
        "repo_id": str(node.get("id") or full_name),
        "full_name": full_name,
        "title": full_name,
        "url": node.get("url") or (f"https://github.com/{full_name}" if full_name else ""),
        "description": node.get("description") or "",
        "summary": node.get("description") or "",
        "language": lang,
        "topics": topics[:10],
        "tags": ([lang] if lang else []) + topics[:5],
        "stars": int((node.get("stargazerCount") or 0)),
        "forks": int((node.get("forkCount") or 0)),
        "watchers": int(((node.get("watchers") or {}).get("totalCount") or 0)),
        "community_metrics_complete": isinstance(node.get("watchers"), dict)
        and "totalCount" in node["watchers"],
        "open_issues": int(((node.get("issues") or {}).get("totalCount") or 0)),
        "license_spdx_id": str((node.get("licenseInfo") or {}).get("spdxId") or ""),
        "created_at": str(node.get("createdAt") or "")[:10],
        "pushed_at": str(node.get("pushedAt") or "")[:10],
    }


def _post_graphql_metrics_chunk(
    client: httpx.Client,
    headers: dict,
    query: str,
) -> tuple[Literal["ok", "failed", "stop"], Dict[str, Any]]:
    """提交一批 GraphQL 指标查询，网络抖动与上游 499/5xx 退避重试。

    返回 ("ok", data)；("failed", {}) 表示本批放弃、后续批次照常；
    ("stop", {}) 表示 token 无效或限流，整轮停止批量抓取。
    """
    for attempt in range(_GRAPHQL_BATCH_MAX_ATTEMPTS):
        if attempt:
            time.sleep(_GRAPHQL_RETRY_BACKOFF * 2 ** (attempt - 1))
        try:
            resp = client.post(f"{GITHUB_API_BASE}/graphql", headers=headers, json={"query": query})
        except httpx.TransportError as exc:
            logger.warning(
                "[GitHub] GraphQL 指标批量抓取网络异常（第 %d/%d 次）: %s",
                attempt + 1, _GRAPHQL_BATCH_MAX_ATTEMPTS, exc,
            )
            continue
        if resp.status_code == 401:
            logger.warning("[GitHub] GraphQL token 401，停止批量抓取。")
            return "stop", {}
        if resp.status_code in (403, 429):
            logger.warning("[GitHub] GraphQL 指标抓取限流 HTTP %s，停止批量抓取。", resp.status_code)
            return "stop", {}
        if resp.status_code in _GRAPHQL_TRANSIENT_STATUS_CODES:
            logger.warning(
                "[GitHub] GraphQL 指标批量抓取 HTTP %s（第 %d/%d 次）",
                resp.status_code, attempt + 1, _GRAPHQL_BATCH_MAX_ATTEMPTS,
            )
            continue
        try:
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("[GitHub] GraphQL 指标批量抓取失败: %s", exc)
            return "failed", {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            errors = payload.get("errors") if isinstance(payload, dict) else payload
            logger.warning("[GitHub] GraphQL 指标批量抓取无数据: %s", str(errors)[:200])
            return "failed", {}
        return "ok", data
    return "failed", {}


def fetch_github_repo_metrics_batch(
    full_names: List[str],
    *,
    batch_size: int = 40,
) -> List[GitHubRepoMetricsResult]:
    """Fetch lightweight metrics and return one classified result per repository."""

    names: List[str] = []
    seen: Set[str] = set()
    for full_name in full_names:
        clean_name = str(full_name or "").strip()
        if not clean_name or "/" not in clean_name or clean_name.lower() in seen:
            continue
        seen.add(clean_name.lower())
        names.append(clean_name)

    if not names:
        return []

    token = _get_token()
    metrics_by_name: Dict[str, dict] = {}
    observed_by_name: Dict[str, str] = {}
    # GraphQL 已应答（含节点为空）的仓库；其余是整批失败或中止时没抓到的
    answered: Set[str] = set()
    if token:
        headers = _build_headers(use_token=True)
        headers["Accept"] = "application/vnd.github+json"
        consecutive_failures = 0
        with httpx.Client(timeout=40, trust_env=True) as client:
            for start in range(0, len(names), max(1, min(batch_size, 50))):
                chunk = names[start : start + max(1, min(batch_size, 50))]
                fields: List[str] = []
                alias_to_name: Dict[str, str] = {}
                for index, full_name in enumerate(chunk):
                    owner, repo_name = full_name.split("/", 1)
                    alias = _graphql_repo_alias(index)
                    alias_to_name[alias] = full_name
                    fields.append(
                        f'''{alias}: repository(owner: "{_graphql_escape(owner)}", name: "{_graphql_escape(repo_name)}") {{
                          id
                          name
                          owner {{ login }}
                          url
                          description
                          primaryLanguage {{ name }}
                          stargazerCount
                          forkCount
                          watchers(first: 1) {{ totalCount }}
                          issues(states: OPEN) {{ totalCount }}
                          createdAt
                          pushedAt
                          licenseInfo {{ spdxId }}
                          repositoryTopics(first: 10) {{ edges {{ node {{ topic {{ name }} }} }} }}
                        }}'''
                    )
                query = "query {\n" + "\n".join(fields) + "\n}"
                status, data = _post_graphql_metrics_chunk(client, headers, query)
                if status == "stop":
                    break
                if status == "failed":
                    # 单批放弃不连坐整轮；连续多批失败才视为 GitHub 侧故障
                    consecutive_failures += 1
                    if consecutive_failures >= _GRAPHQL_MAX_CONSECUTIVE_FAILED_CHUNKS:
                        logger.warning(
                            "[GitHub] GraphQL 连续 %d 批失败，停止批量抓取。", consecutive_failures
                        )
                        break
                    continue
                consecutive_failures = 0
                chunk_observed_at = _observed_now()
                for alias, full_name in alias_to_name.items():
                    answered.add(full_name.lower())
                    node = data.get(alias)
                    if isinstance(node, dict):
                        metrics_by_name[full_name.lower()] = _parse_graphql_repo(node)
                        observed_by_name[full_name.lower()] = chunk_observed_at
                    else:
                        logger.debug("[GitHub] GraphQL 未返回仓库 %s", full_name)
        if len(metrics_by_name) >= len(names):
            return [
                GitHubRepoMetricsResult(
                    full_name=full_name,
                    status="succeeded",
                    metrics=metrics_by_name[full_name.lower()],
                    http_status=200,
                    observed_at=observed_by_name[full_name.lower()],
                )
                for full_name in names
            ]

    outcomes: Dict[str, GitHubRepoMetricsResult] = {
        full_name.lower(): GitHubRepoMetricsResult(
            full_name=full_name,
            status="succeeded",
            metrics=metrics_by_name[full_name.lower()],
            http_status=200,
            observed_at=observed_by_name[full_name.lower()],
        )
        for full_name in names
        if full_name.lower() in metrics_by_name
    }
    missing_names = [full_name for full_name in names if full_name.lower() not in outcomes]
    unfetched = [full_name for full_name in missing_names if full_name.lower() not in answered]
    if token and len(unfetched) > _REST_FALLBACK_MAX_UNFETCHED:
        logger.warning(
            "[GitHub] GraphQL 批量抓取有 %d 个仓库未抓到，超过 REST 补抓上限 %d，本轮记为未知。",
            len(unfetched),
            _REST_FALLBACK_MAX_UNFETCHED,
        )
        for full_name in unfetched:
            outcomes[full_name.lower()] = GitHubRepoMetricsResult(
                full_name=full_name,
                status="unknown",
                error="GraphQL batch unavailable",
            )
        missing_names = [full_name for full_name in missing_names if full_name.lower() in answered]
    if missing_names:
        with httpx.Client(timeout=30, trust_env=True) as client:
            use_token = _check_token_valid(client)
            limited: GitHubRepoMetricsResult | None = None
            for index, full_name in enumerate(missing_names):
                if limited is not None:
                    outcomes[full_name.lower()] = GitHubRepoMetricsResult(
                        full_name=full_name,
                        status="unknown",
                        http_status=limited.http_status,
                        error="rate limited",
                        rate_limited=True,
                    )
                    continue
                result = fetch_github_repo_metrics(full_name, client=client, use_token=use_token)
                outcomes[full_name.lower()] = result
                if result.rate_limited:
                    # 配额耗尽后逐个再撞只会秒回 403/429，还白占 GitHub 锁
                    limited = result
                    logger.warning(
                        "[GitHub] REST 指标补抓遇限流 HTTP %s，剩余 %d 个仓库本轮记为未知。",
                        result.http_status,
                        len(missing_names) - index - 1,
                    )
    return [outcomes[full_name.lower()] for full_name in names]


def fetch_github_candidate_repos(limit: int = 60) -> List[dict]:
    today = date.today()
    recent_cutoff = (today - timedelta(days=7)).isoformat()
    active_cutoff = (today - timedelta(days=30)).isoformat()

    seen_ids: Set[str] = set()
    parsed: List[dict] = []

    with httpx.Client(timeout=30, trust_env=True) as client:
        use_token = _check_token_valid(client)
        if _get_token() and not use_token:
            logger.info("[GitHub] Token 无效，本次全程使用匿名访问。")

        queries = [
            *(f"topic:{topic} created:>{recent_cutoff}" for topic in _TOPICS),
            f"created:>{recent_cutoff} stars:>10",
            f"pushed:>{active_cutoff} stars:>1000",
        ]

        for query in queries:
            items = _search_repos(
                query,
                min(max(limit, 20), 30),
                client,
                use_token=use_token,
                sort="stars",
            )
            for item in items:
                node_id = str(item.get("node_id") or item.get("id") or "")
                if not node_id or node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
                parsed.append(_parse_item(item, client, use_token=use_token))
                if len(parsed) >= limit:
                    break
            if len(parsed) >= limit:
                break

    logger.info("[GitHub][Candidates] 最终返回 %d 个候选仓库。", len(parsed))
    return parsed

