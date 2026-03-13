"""测试 ProductHunt 数据抓取方案 v4 - 解析 Apollo SSR Transport"""

from __future__ import annotations

import re
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

from curl_cffi import requests as cf_requests


def fetch_homepage():
    resp = cf_requests.get(
        "https://www.producthunt.com/",
        impersonate="chrome124",
        timeout=30,
    )
    print(f"Status: {resp.status_code}, Len: {len(resp.text)}")
    return resp.text


def extract_apollo_ssr_data(html: str) -> list[dict]:
    """从 PH 主页提取 Apollo SSR Transport 中的 homefeed 产品数据"""

    # 找所有 Apollo SSR 数据块
    # 格式: (window[Symbol.for("ApolloSSRDataTransport")] ??= []).push({...})
    push_blocks = re.findall(
        r'window\[Symbol\.for\("ApolloSSRDataTransport"\)\][^.]*\.push\((\{.*?\})\)',
        html,
        re.DOTALL,
    )
    print(f"Apollo SSR push blocks: {len(push_blocks)}")

    # 也试另一种方法：直接搜索含 homefeed 的 JSON 块
    # 先找 "homefeed" 出现的位置
    homefeed_positions = [m.start() for m in re.finditer(r'"homefeed"', html)]
    print(f"homefeed occurrences: {len(homefeed_positions)}")

    # 找包含 items 数组的 homefeed
    posts = []
    seen_ids = set()

    # 直接用正则提取所有 Post 条目（从 items 数组里）
    # 格式: {"__typename":"Post","id":"1083354","name":"Timelaps",...}
    # 找到 "items":[... 数组中的所有 Post 对象

    # 方案：找 "items":[ 然后提取数组内容
    items_matches = re.finditer(r'"items":\[', html)
    for m in items_matches:
        start = m.end()
        # 找到数组结束位置
        depth = 1
        pos = start
        while pos < len(html) and depth > 0:
            c = html[pos]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            pos += 1
        array_str = html[start : pos - 1]

        # 检查是否含有 Post 数据
        if '"__typename":"Post"' not in array_str:
            continue

        print(f"Found items array at pos {m.start()}, len={len(array_str)}")
        print(f"Preview: {array_str[:200]}")

        # 尝试解析为 JSON
        try:
            items_data = json.loads("[" + array_str + "]")
            print(f"Parsed {len(items_data)} items")
            for item in items_data:
                if item.get("__typename") == "Post":
                    post_id = item.get("id", "")
                    if post_id not in seen_ids:
                        seen_ids.add(post_id)
                        posts.append(item)
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            # 手动提取每个 Post 对象
            for post_match in re.finditer(
                r'\{"__typename":"Post","id":"(\d+)"', array_str
            ):
                pid = post_match.group(1)
                if pid in seen_ids:
                    continue
                # 提取完整对象
                obj_start = post_match.start()
                depth = 0
                for i, c in enumerate(array_str[obj_start : obj_start + 3000]):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            obj_str = array_str[obj_start : obj_start + i + 1]
                            try:
                                obj = json.loads(obj_str)
                                seen_ids.add(pid)
                                posts.append(obj)
                            except:
                                pass
                            break

    return posts


def parse_posts(posts: list[dict]) -> list[dict]:
    """将 Post 对象转换为标准格式"""
    items = []
    for post in posts:
        featured_at = post.get("featuredAt", "")
        launch_score = post.get("launchDayScore", 0) or 0
        latest_score = post.get("latestScore", 0) or 0
        name = post.get("name", "")
        tagline = post.get("tagline", "")
        slug = post.get("slug", "")
        daily_rank = post.get("dailyRank", "")
        weekly_rank = post.get("weeklyRank", "")

        if not name:
            continue

        # 提取 topic 标签
        topics = []
        topics_data = post.get("topics", {})
        if topics_data and isinstance(topics_data, dict):
            for edge in topics_data.get("edges", []):
                node = edge.get("node", {})
                if node.get("name"):
                    topics.append(node["name"])

        # URL
        url = f"https://www.producthunt.com/posts/{slug}" if slug else ""

        items.append(
            {
                "id": post.get("id", ""),
                "name": name,
                "tagline": tagline,
                "featured_at": featured_at,
                "launch_day_score": launch_score,
                "latest_score": latest_score,
                "url": url,
                "slug": slug,
                "daily_rank": daily_rank,
                "weekly_rank": weekly_rank,
                "topics": topics,
            }
        )

    items.sort(
        key=lambda x: int(x["daily_rank"]) if str(x["daily_rank"]).isdigit() else 999
    )
    return items


if __name__ == "__main__":
    print("=== Testing ProductHunt Scraping v4 ===\n")
    html = fetch_homepage()
    posts = extract_apollo_ssr_data(html)
    print(f"\nTotal posts found: {len(posts)}")

    items = parse_posts(posts)
    print(f"\nAll products (sorted by rank):")
    for i, item in enumerate(items):
        print(
            f"  {i+1:2d}. [Rank #{item['daily_rank']}] [{item['launch_day_score']} votes] {item['name']}"
        )
        print(f"       tagline: {item['tagline'][:70]}")
        print(f"       featuredAt: {item['featured_at']}, topics: {item['topics'][:3]}")
        print(f"       url: {item['url']}")
