from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def extract_posts_from_html(html: str) -> List[Dict[str, Any]]:
    """从 Product Hunt Apollo SSR Transport 提取所有 Post 对象。"""
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    target_script = ""
    for script in scripts:
        if "featuredAt" in script and "launchDayScore" in script:
            target_script = script
            break

    if not target_script:
        for script in scripts:
            if "ApolloSSRDataTransport" in script or "homefeed" in script:
                target_script = script
                break

    if not target_script:
        logger.error(
            "[ProductHunt] 未在页面找到含产品数据的 script 标签，"
            "页面长度=%d，script标签数=%d。"
            "可能原因：1) Cloudflare 拦截返回了挑战页面 2) PH 前端 DOM 结构变更 "
            "3) Apollo SSR Transport 数据格式变更",
            len(html),
            len(scripts),
        )
        logger.error("[ProductHunt] 页面前500字符: %s", html[:500].replace("\n", " "))
        return []

    posts: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for match in re.finditer(r'"items":\[', target_script):
        array_start = match.end()
        depth = 1
        pos = array_start
        while pos < len(target_script) and depth > 0:
            char = target_script[pos]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            pos += 1
        array_content = target_script[array_start : pos - 1]

        if '"__typename":"Post"' not in array_content:
            continue

        try:
            items_data: List[Any] = json.loads("[" + array_content + "]")
        except json.JSONDecodeError:
            items_data = []
            for post_match in re.finditer(
                r'\{"__typename":"Post","id":"(\d+)"', array_content
            ):
                post_id = post_match.group(1)
                if post_id in seen_ids:
                    continue
                object_start = post_match.start()
                object_depth = 0
                for offset, char in enumerate(
                    array_content[object_start : object_start + 4000]
                ):
                    if char == "{":
                        object_depth += 1
                    elif char == "}":
                        object_depth -= 1
                        if object_depth == 0:
                            try:
                                item = json.loads(
                                    array_content[
                                        object_start : object_start + offset + 1
                                    ]
                                )
                                seen_ids.add(post_id)
                                items_data.append(item)
                            except json.JSONDecodeError:
                                pass
                            break

        for item in items_data:
            if not isinstance(item, dict) or item.get("__typename") != "Post":
                continue
            post_id = str(item.get("id", ""))
            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            posts.append(item)

    if posts:
        logger.info("[ProductHunt] Apollo SSR 共提取 %d 个 Post 对象", len(posts))
    else:
        logger.error(
            "[ProductHunt] Apollo SSR 提取到 0 个 Post 对象。"
            "target_script 长度=%d，包含 'items' 匹配数=%d。"
            "可能原因：1) JSON 解析失败 2) __typename 字段名变更 3) 数据结构变更",
            len(target_script),
            len(list(re.finditer(r'"items":\[', target_script))),
        )

    return posts
