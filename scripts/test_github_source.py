#!/usr/bin/env python3
"""
GitHub 数据源连通性测试脚本
用法：
    python scripts/test_github_source.py

功能：
    1. 检测 GITHUB_TOKEN 是否已配置
    2. 测试带时间过滤的 pushed:>7days 查询
    3. 测试无时间限制的兜底查询
    4. 打印返回字段结构和前 3 条数据摘要
    5. 展示 API Rate Limit 剩余次数
"""

import os
import sys
import json

# 确保项目根目录在 PATH 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta

import httpx

# ── 从 .env 加载配置 ─────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass  # 没有 python-dotenv 时忽略，手动设置 GITHUB_TOKEN 环境变量

GITHUB_API_BASE = "https://api.github.com"
_TOPICS = ["llm", "ai", "agent", "generative-ai", "large-language-model"]


def _get_token() -> str:
    # 优先读环境变量，再读 settings
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        try:
            from backend.app.core.config import settings

            token = settings.github_token.strip()
        except Exception:
            pass
    return token


def _build_headers(token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _print_rate_limit(resp: httpx.Response) -> None:
    remaining = resp.headers.get("x-ratelimit-remaining", "?")
    limit = resp.headers.get("x-ratelimit-limit", "?")
    reset_ts = resp.headers.get("x-ratelimit-reset", "")
    if reset_ts.isdigit():
        from datetime import datetime, timezone

        reset_dt = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc).strftime(
            "%H:%M:%S UTC"
        )
    else:
        reset_dt = reset_ts
    print(f"  📊 Rate Limit: {remaining}/{limit} 剩余，重置于 {reset_dt}")


def test_search(query: str, limit: int, headers: dict, label: str) -> list:
    """执行一次搜索并打印结果摘要，返回 items 列表。"""
    print(f"\n{'='*60}")
    print(f"🔍 [{label}] 查询: {query!r}")
    print(f"{'='*60}")

    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 10),
        "page": 1,
    }

    try:
        with httpx.Client(timeout=30, trust_env=True) as client:
            resp = client.get(
                f"{GITHUB_API_BASE}/search/repositories",
                headers=headers,
                params=params,
            )
            _print_rate_limit(resp)

            if resp.status_code == 403:
                print(f"  ❌ HTTP 403 Forbidden — 可能触发限流或 Token 权限不足")
                print(f"     响应: {resp.text[:300]}")
                return []
            if resp.status_code == 422:
                print(f"  ❌ HTTP 422 Unprocessable — 查询语法错误")
                print(f"     响应: {resp.text[:300]}")
                return []

            resp.raise_for_status()
            data = resp.json()

    except httpx.ConnectError as e:
        print(f"  ❌ 网络连接失败: {e}")
        print("     提示：检查网络或设置 HTTPS_PROXY 环境变量")
        return []
    except httpx.TimeoutException:
        print("  ❌ 请求超时（30s）")
        return []
    except Exception as e:
        print(f"  ❌ 未知错误: {e}")
        return []

    total_count = data.get("total_count", 0)
    items = data.get("items", [])
    print(f"  ✅ 命中 {total_count} 个仓库，本次返回 {len(items)} 条")

    if not items:
        print("  ⚠️  结果为空！请尝试放宽查询条件。")
        return []

    print(f"\n  📋 前 {min(3, len(items))} 条结果：")
    for i, item in enumerate(items[:3], 1):
        name = item.get("full_name", "")
        stars = item.get("stargazers_count", 0)
        lang = item.get("language", "N/A")
        pushed = (item.get("pushed_at") or "")[:10]
        url = item.get("html_url", "")
        print(f"    {i}. {name}")
        print(f"       ⭐ {stars:,} stars | 语言: {lang} | 最近 push: {pushed}")
        print(f"       🔗 {url}")

    return items


def test_fetch_github_repos(limit: int = 10) -> None:
    """调用 source_github.fetch_github_repos() 验证集成路径。"""
    print(f"\n{'='*60}")
    print("🧪 集成测试：调用 fetch_github_repos()")
    print(f"{'='*60}")
    try:
        from backend.app.services.ingestion.source_github import fetch_github_repos

        results = fetch_github_repos(limit=limit)
        print(f"  ✅ 返回 {len(results)} 条结果")
        if results:
            first = results[0]
            print(f"  📌 第一条字段检查：")
            expected_fields = [
                "title",
                "abstract",
                "summary",
                "url",
                "source",
                "score",
                "tags",
                "published_date",
                "language",
                "stars",
            ]
            for field in expected_fields:
                val = first.get(field)
                status = "✅" if val is not None else "⚠️ 缺失"
                display = str(val)[:60] if isinstance(val, str) else str(val)
                print(f"     {status} {field}: {display}")
    except Exception as e:
        print(f"  ❌ 调用失败: {e}")
        import traceback

        traceback.print_exc()


def main():
    print("=" * 60)
    print("  GitHub 数据源连通性测试")
    print("=" * 60)

    # ── 1. Token 状态 ────────────────────────────────────────────
    token = _get_token()
    if token:
        masked = token[:8] + "..." + token[-4:]
        print(f"\n✅ GITHUB_TOKEN 已配置: {masked}")
        print("   （认证用户 API 限制：每小时 5000 次）")
    else:
        print("\n⚠️  GITHUB_TOKEN 未配置，使用匿名访问（每小时 60 次）")
        print("   建议在 .env 中设置 GITHUB_TOKEN=ghp_xxx")

    # ── 2. 代理检查 ───────────────────────────────────────────────
    proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("http_proxy")
    )
    if proxy:
        print(f"\n🌐 检测到代理: {proxy}")
    else:
        print("\n🌐 无代理配置（直连 GitHub API）")

    headers = _build_headers(token)

    # ── 3. 测试带时间过滤的单 topic 查询（Phase 1 策略）──────────
    since_7d = (date.today() - timedelta(days=7)).isoformat()
    # 使用单 topic 查询，与 source_github.py 策略一致
    sample_topic = _TOPICS[0]
    timed_query = f"topic:{sample_topic} pushed:>{since_7d}"
    items_timed = test_search(
        timed_query,
        limit=10,
        headers=headers,
        label=f"Phase-1: topic:{sample_topic} 带时间过滤",
    )

    # ── 4. 测试兜底单 topic 查询（Phase 2 策略）──────────────────
    fallback_query = f"topic:{sample_topic} stars:>50"
    items_fallback = test_search(
        fallback_query,
        limit=10,
        headers=headers,
        label=f"Phase-2: topic:{sample_topic} 兜底查询",
    )

    # ── 5. 集成测试 ───────────────────────────────────────────────
    test_fetch_github_repos(limit=5)

    # ── 6. 总结 ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📊 测试总结")
    print(f"{'='*60}")
    print(
        f"  Phase-1 带时间过滤查询:  {'✅ 有数据' if items_timed else '⚠️  无数据（将触发 Phase-2 兜底）'}"
    )
    print(
        f"  Phase-2 兜底查询:        {'✅ 有数据' if items_fallback else '❌ 无数据/失败'}"
    )

    if not items_timed and not items_fallback:
        print("\n  🔧 排查建议：")
        print("     1. 检查网络，尝试 curl https://api.github.com/zen")
        print("     2. 设置代理：export HTTPS_PROXY=http://127.0.0.1:7890")
        print("     3. 若 Token 导致 401，清空 .env 中的 GITHUB_TOKEN= 改用匿名访问")
    elif not items_timed:
        print("\n  ℹ️  Phase-1 无近期更新数据，将自动降级到 Phase-2 兜底策略，正常。")
        print("  🎉 GitHub 数据源工作正常！")
    else:
        print("\n  🎉 GitHub 数据源工作正常！两阶段策略均可获取数据。")


if __name__ == "__main__":
    main()
