"""简报 Markdown 的规则渲染与规则压缩（纯函数，无 I/O），供简报 RSS 使用。

两个入口：
  - render_briefing_markdown_html：行级规则把简报 Markdown 渲染为 HTML 片段
    （h1/h2/h3/li/blockquote/p + strong/code/a 行内）。与邮件渲染器
    （services/email/message_renderer.py）同一套行规则族，但产出无邮件骨架
    与内联样式的片段，且先做 HTML 转义再套行内规则——简报正文里的裸
    < > & 不会炸掉阅读器排版。
  - condense_briefing_markdown：注册用户「速览」M0 的规则压缩——保留 H1 与
    首个 ## 章节（即「本期/今日内容摘要」节）的全部内容，第二个 ## 章节起只留
    ##/### 标题，回扫丢弃没有任何保留内容的空章节（如尾部「日期与数据来源」），
    并剥掉标题里的 `#tag` 行内代码。只有一个章节的纯散文简报退化为原文
    （速览不删信息）。后续 LLM 精简管线替换本函数输出即可，RSS 端点为天然
    hook 点。
"""

from __future__ import annotations

import re
from html import unescape
from xml.sax.saxutils import escape

from backend.app.domain.public_content import (
    sanitize_public_resource_url,
    sanitize_public_text,
)

# 标题里的标签行内代码：如 `# 标题 `#news` `#LLM`` 中的 `` `#news` ``。
_TAG_CODE_SPAN = re.compile(r"\s*`#[^`]+`")
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
def _render_safe_inline_resources(body: str) -> str:
    """Render only allow-listed Markdown links/images after HTML escaping."""
    def image(match: re.Match[str]) -> str:
        url = sanitize_public_resource_url(match.group(2))
        if not url:
            return ""
        alt = escape(unescape(match.group(1)), {'"': "&quot;"})
        return f'<img src="{escape(url, {chr(34): "&quot;"})}" alt="{alt}" />'

    def link(match: re.Match[str]) -> str:
        url = sanitize_public_resource_url(match.group(2))
        return f'<a href="{escape(url, {chr(34): "&quot;"})}">{match.group(1)}</a>' if url else match.group(1)

    body = _MARKDOWN_IMAGE.sub(image, body)
    return _MARKDOWN_LINK.sub(link, body)


def _strip_heading_tags(line: str) -> str:
    """剥掉标题行里的 `#tag` 行内代码（速览里属噪声）。"""
    return _TAG_CODE_SPAN.sub("", line).rstrip()


def render_briefing_markdown_html(content: str) -> str:
    """简报 Markdown → HTML 片段（规则渲染，与邮件渲染器同规则族）。

    每行先整体 HTML 转义（含双引号，防止 href 属性被截断），再套行内
    **加粗** / `代码` / [链接](url) 替换；标题行内 <code> 不显示前导 #，
    与前端及邮件渲染约定一致。
    """
    html_lines: list[str] = []
    content = sanitize_public_text(content)
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        escaped = escape(stripped, {'"': "&quot;"})
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{escaped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{escaped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{escaped[2:]}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_lines.append(f"<li>{escaped[2:]}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s*", "", escaped)
            html_lines.append(f"<li>{text}</li>")
        elif stripped.startswith("> "):
            html_lines.append(f"<blockquote>{escaped[2:]}</blockquote>")
        else:
            html_lines.append(f"<p>{escaped}</p>")

    body = "\n".join(html_lines)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    # URL 语义校验必须在生成 href/src 前完成；XML/HTML escape 不是安全校验。
    body = _render_safe_inline_resources(body)
    # 标题内的标签行内代码不显示前导 #（与前端/邮件渲染约定一致）：
    # <h2>标题 <code>news</code></h2>；正文代码如 `#define` 不受影响。
    return "\n".join(
        re.sub(r"(<code>)#", r"\1", line) if line.startswith(("<h1", "<h2", "<h3")) else line
        for line in body.split("\n")
    )


def condense_briefing_markdown(content: str) -> str:
    """规则压缩为「速览」Markdown：内容摘要节全文 + 全条目标题一览。

    规则：
      1. 首个 ## 章节（「本期内容摘要」）及之前的内容全保留；
      2. 第二个 ## 章节起只保留 ## / ### 标题行（条目正文如「话题概述」段
         与章节导言全部丢弃）；
      3. 回扫丢弃没有任何保留内容的 ## 空章节（如尾部「日期与数据来源」）；
      4. 所有标题行剥掉 `#tag` 行内代码。
    """
    kept: list[str] = []
    section_count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # "### " 的第三个字符不是空格，不会被 "## " 误匹配，计数只认二级章节。
        if stripped.startswith("## "):
            section_count += 1
        if section_count < 2:
            kept.append(_strip_heading_tags(stripped) if stripped.startswith("#") else stripped)
        elif stripped.startswith("## ") or stripped.startswith("### "):
            kept.append(_strip_heading_tags(stripped))

    # 回扫：丢弃空 ## 章节（下一个保留行仍是 ## 标题或已到末尾）。
    compacted: list[str] = []
    for index, line in enumerate(kept):
        # "### " 的第三个字符不是空格，不会被 "## " 误匹配，无需额外排除。
        if line.startswith("## "):
            follower = kept[index + 1] if index + 1 < len(kept) else ""
            if not follower or follower.startswith("## "):
                continue
        compacted.append(line)
    return "\n".join(compacted)
