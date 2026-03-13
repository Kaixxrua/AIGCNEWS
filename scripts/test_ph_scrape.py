"""测试 ProductHunt 数据抓取方案"""

from __future__ import annotations

import re
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

try:
    from curl_cffi import requests as cf_requests

    CURL_CFFI_OK = True
except ImportError:
    CURL_CFFI_OK = False
    print("curl_cffi not available")


def fetch_homepage():
    resp = cf_requests.get(
        "https://www.producthunt.com/",
        impersonate="chrome124",
        timeout=30,
    )
    print(f"Status: {resp.status_code}, Len: {len(resp.text)}")
    return resp.text


def parse_products_from_html(html: str):
    """从 PH 主页 HTML 解析今日产品列表"""

    today_cst = datetime.now(CST).date().isoformat()
    print(f"Today CST: {today_cst}")

    # PH 使用 PST/PDT（UTC-8/UTC-7），找今天或昨天（PST）的产品
    # featuredAt 格式: "2026-03-09T00:01:00-08:00"

    # 方案1：用正则提取所有产品条目（包含 featuredAt + launchDayScore + name + tagline）
    # 先找所有 script tags
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    print(f"Total scripts: {len(scripts)}")

    # 找含有产品数据的 script
    product_script = None
    for i, s in enumerate(scripts):
        if "featuredAt" in s and "launchDayScore" in s:
            print(f"Script {i} has featuredAt + launchDayScore, len={len(s)}")
            product_script = s
            break

    if not product_script:
        print("No product script found, searching in full HTML")
        product_script = html

    # 方案2：正则提取所有 Post 对象
    # 格式示例: {"__typename":"Post","id":"123","featuredAt":"2026-03-09T00:01:00-08:00","launchDayScore":460,...}
    # 先用简单模式提取 featuredAt 和附近的 launchDayScore
    items = []

    # 找所有带有 featuredAt 的产品 JSON 块
    # 提取更完整的结构：寻找 "Post" 对象
    post_segments = re.findall(
        r'"__typename":"Post"[^}]{0,2000}?"name":"([^"]+)"[^}]{0,500}?"tagline":"([^"]+)"',
        product_script,
        re.DOTALL,
    )
    print(f"Post segments with name+tagline: {len(post_segments)}")
    for seg in post_segments[:5]:
        print(f"  name={seg[0]}, tagline={seg[1][:60]}")

    # 更全面的提取
    # 找所有 featuredAt 位置
    featured_positions = [
        m.start() for m in re.finditer(r'"featuredAt"', product_script)
    ]
    print(f"\nTotal featuredAt positions: {len(featured_positions)}")

    seen_names = set()
    for pos in featured_positions:
        # 取前后 2000 字节的上下文
        start = max(0, pos - 1500)
        end = min(len(product_script), pos + 500)
        ctx = product_script[start:end]

        # 提取 featuredAt 日期
        feat_m = re.search(r'"featuredAt":"([^"]+)"', ctx)
        featured_at = feat_m.group(1) if feat_m else ""

        # 提取 launchDayScore（投票数）
        score_m = re.search(r'"launchDayScore":(\d+)', ctx)
        launch_score = int(score_m.group(1)) if score_m else 0

        # 提取 latestScore
        latest_m = re.search(r'"latestScore":(\d+)', ctx)
        latest_score = int(latest_m.group(1)) if latest_m else 0

        # 提取 name（产品名）
        name_m = re.search(r'"name":"([^"]+)"', ctx)
        name = name_m.group(1) if name_m else ""

        # 提取 tagline
        tag_m = re.search(r'"tagline":"([^"]+)"', ctx)
        tagline = tag_m.group(1) if tag_m else ""

        # 提取 url（产品页面路径）
        url_m = re.search(r'"url":"(/posts/[^"]+)"', ctx)
        url = url_m.group(1) if url_m else ""

        # 提取 slug
        slug_m = re.search(r'"slug":"([^"]+)"', ctx)
        slug = slug_m.group(1) if slug_m else ""

        if name and name not in seen_names and launch_score > 0:
            seen_names.add(name)
            items.append(
                {
                    "name": name,
                    "tagline": tagline,
                    "featured_at": featured_at,
                    "launch_day_score": launch_score,
                    "latest_score": latest_score,
                    "url": url or f"/posts/{slug}" if slug else "",
                    "slug": slug,
                }
            )

    # 按投票数排序
    items.sort(key=lambda x: x["launch_day_score"], reverse=True)

    print(f"\nTotal unique products: {len(items)}")
    print("\nTop 20 products:")
    for i, item in enumerate(items[:20]):
        print(
            f"  {i+1:2d}. [{item['launch_day_score']} votes] {item['name']} - {item['tagline'][:50]}"
        )
        print(f"       featuredAt={item['featured_at']}, url={item['url']}")

    return items


if __name__ == "__main__":
    print("=== Testing ProductHunt Scraping ===\n")
    html = fetch_homepage()
    items = parse_products_from_html(html)
