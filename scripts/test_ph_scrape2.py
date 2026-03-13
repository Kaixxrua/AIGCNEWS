"""测试 ProductHunt 数据抓取方案 v2 - 使用 JSON 解析"""

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
    """从 PH 主页 HTML 解析今日产品列表 - 精确提取 Post 对象"""

    # 找含有产品数据的 script
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    product_script = None
    for i, s in enumerate(scripts):
        if "featuredAt" in s and "launchDayScore" in s:
            print(f"Script {i} has featuredAt + launchDayScore, len={len(s)}")
            product_script = s
            break

    if not product_script:
        product_script = html

    # PH 将数据嵌入为 JS 对象，格式类似 Apollo cache
    # 尝试提取整个 JS 对象（可能是 self.__next_f.push 或 window.某变量）
    # 先看第40个 script 的内容
    print(f"\nTotal scripts: {len(scripts)}")

    # 找到包含 featuredAt 的 script 内容片段
    # 在该 script 中查找 Post 对象
    # 格式: "Post:123":{"__typename":"Post","id":"123",...}

    # 提取所有 Post 对象（以 "Post:数字" 为 key）
    # 在 Apollo cache 中，每个 Post 有独立的条目

    # 先尝试找到 JSON 对象的开始
    # 常见格式: self.__next_f.push([1,"[...json...]"])
    next_f_match = re.search(
        r"self\.__next_f\.push\(\[(\d+),(.*?)\]\)", product_script[:200], re.DOTALL
    )
    if next_f_match:
        print(f"Found self.__next_f.push format")

    # 直接解析：找到所有形如 "Post:ID" 的 Apollo cache 条目
    # 这些条目包含 id, name, tagline, featuredAt, launchDayScore 等

    # 提取方法：找 "\"id\":\"POST_ID\"" 和附近的产品信息
    # 先看一下实际的 Post 数据结构
    feat_idx = product_script.find('"featuredAt"')
    if feat_idx > 0:
        # 向前找 __typename:Post
        start = max(0, feat_idx - 3000)
        snippet = product_script[start : feat_idx + 200]
        # 找最后一个 __typename
        last_typename = snippet.rfind('"__typename"')
        if last_typename >= 0:
            print("\nPost structure snippet:")
            print(snippet[last_typename : last_typename + 500])

    # 正确方法：逐步解析 JSON 数据
    # 找所有以 "Post:" 开头的键（Apollo cache 格式）
    post_keys = re.findall(r'"(Post:\d+)":\{', product_script)
    print(f"\nPost cache keys found: {len(post_keys)}")
    print("Sample post keys:", post_keys[:5])

    # 对每个 Post key，提取对应的 JSON 对象
    items = []
    seen_ids = set()

    for key in post_keys:
        # 找到这个 key 对应的对象
        key_pattern = f'"{key}":'
        key_idx = product_script.find(key_pattern)
        if key_idx < 0:
            continue

        # 提取从 { 开始的 JSON 对象
        obj_start = product_script.find("{", key_idx)
        if obj_start < 0:
            continue

        # 手动匹配括号找到对象结尾
        depth = 0
        obj_end = obj_start
        for i, c in enumerate(product_script[obj_start : obj_start + 5000]):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    obj_end = obj_start + i + 1
                    break

        obj_str = product_script[obj_start:obj_end]
        try:
            obj = json.loads(obj_str)
        except json.JSONDecodeError:
            continue

        post_id = key.split(":")[1]
        if post_id in seen_ids:
            continue
        seen_ids.add(post_id)

        featured_at = obj.get("featuredAt", "")
        launch_score = obj.get("launchDayScore", 0)
        latest_score = obj.get("latestScore", 0)
        name = obj.get("name", "")
        tagline = obj.get("tagline", "")
        slug = obj.get("slug", "")
        url = obj.get("url", "")

        if name and featured_at:
            items.append(
                {
                    "id": post_id,
                    "name": name,
                    "tagline": tagline,
                    "featured_at": featured_at,
                    "launch_day_score": launch_score,
                    "latest_score": latest_score,
                    "url": url or f"/posts/{slug}",
                    "slug": slug,
                }
            )

    items.sort(key=lambda x: x["launch_day_score"], reverse=True)

    print(f"\nTotal unique products: {len(items)}")
    print("\nAll products (sorted by votes):")
    for i, item in enumerate(items):
        print(
            f"  {i+1:2d}. [{item['launch_day_score']} votes] {item['name']} - {item['tagline'][:60]}"
        )
        print(f"       featuredAt={item['featured_at']}, url={item['url']}")

    return items


if __name__ == "__main__":
    print("=== Testing ProductHunt Scraping v2 ===\n")
    html = fetch_homepage()
    items = parse_products_from_html(html)
