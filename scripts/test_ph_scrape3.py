"""测试 ProductHunt 数据抓取方案 v3 - 分析实际 JSON 结构"""

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


def parse_products_from_html(html: str):
    """从 PH 主页 HTML 解析今日产品列表"""

    # 找含有产品数据的 script（script 40）
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    product_script = None
    for i, s in enumerate(scripts):
        if "featuredAt" in s and "launchDayScore" in s:
            product_script = s
            print(f"Using script {i}, len={len(s)}")
            break

    if not product_script:
        product_script = html

    # 看 featuredAt 附近的完整 JSON 结构
    feat_idx = product_script.find('"featuredAt"')
    if feat_idx > 0:
        # 往前找 2000 字节，看完整的 Post 结构
        start = max(0, feat_idx - 2000)
        snippet = product_script[start : feat_idx + 1000]
        print("\n=== Raw context around featuredAt ===")
        print(snippet[-2500:])

    # 检查是不是 Next.js RSC payload 格式（不是标准 JSON）
    print("\n=== Script prefix (first 200 chars) ===")
    print(repr(product_script[:200]))


if __name__ == "__main__":
    print("=== Testing ProductHunt Scraping v3 ===\n")
    html = fetch_homepage()
    parse_products_from_html(html)
