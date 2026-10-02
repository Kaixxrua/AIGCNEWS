"""项目库悬停速览的 README 开头几段：只摘读得下去的正文。

标题、徽章、图片、代码、表格、列表、导航与语言切换、告示框都略过；安装、用法、许可、目录这类章节整节跳过
（直到同级或更高一级的下一个标题）。行内的链接、强调、行内代码留下文字，HTML 只留正文。摘满
INTRO_PARAGRAPHS 段或 INTRO_CHARS 字为止（汉字按两个算，中英文摘出来差不多长），最后一段放不下就在句末截断，
找不到句末再在词边截断加省略号。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator

__all__ = ["INTRO_CHARS", "INTRO_PARAGRAPHS", "readme_intro"]

INTRO_PARAGRAPHS = 3
INTRO_CHARS = 640
# 一段至少这么长才算正文：更短的多半是标语、标题残片或「安装：」一类引子
_MIN_PROSE = 28
# 最后一段剩下的地方不到这么多，就不摆一截残句
_MIN_TAIL = 120
# 开头几段不会在更后面；超长的 README（awesome 清单）只扫这一截
_SCAN_CHARS = 60_000

_FRONT_MATTER = re.compile(r"\A---\n.*?\n---[ \t]*\n", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_FENCE = re.compile(r"(`{3,}|~{3,})")
_HTML_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.S | re.I)
# 整块不读的元素：表格、列表、折叠段、图片与代码块
_DROP_ELEMENTS = re.compile(
    r"<(table|ul|ol|dl|details|picture|svg|video|audio|pre|script|style|nav|iframe|object)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_VOID_TAGS = re.compile(r"<(?:img|source|input|meta|link|embed)\b[^>]*/?>", re.I)
_ANCHOR = re.compile(r"<a\b[^>]*>(.*?)</a\s*>", re.S | re.I)
_BREAK_TAG = re.compile(r"<br\s*/?>", re.I)
_BLOCK_TAGS = re.compile(
    r"</?(?:p|div|center|section|article|header|footer|blockquote|figure|figcaption|main|aside|hr)\b[^>]*/?>",
    re.I,
)
# 只剥认得的行内标签：Vec<T>、<YOUR_TOKEN> 这类正文里的尖括号留着
_INLINE_TAGS = re.compile(
    r"</?(?:b|strong|em|i|u|s|sup|sub|kbd|span|code|font|small|big|mark|samp|abbr|tt|ins|del|cite|q|var|wbr|nobr)\b[^>]*>",
    re.I,
)
_ANY_TAG = re.compile(r"<[^>]+>")

_HEADING = re.compile(r"(#{1,6})(?:\s+|$)(.*)")
_RULE = re.compile(r"([-*_])(?:\s*\1){2,}\s*$")
_UNDERLINE = re.compile(r"([=\-~^\"'`*+#:.])\1{2,}\s*$")
_TABLE_RULE = re.compile(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_ITEM = re.compile(r"(?:[-*+]|\d{1,3}[.)])\s+")
_LINK_DEF = re.compile(r"\[[^\]]+\]:\s*\S+")
_RST_DIRECTIVE = re.compile(r"\.\.\s")
_RST_FIELD = re.compile(r":[\w -]+:(?:\s|$)")
_ALERT = re.compile(r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.I)
_NOTE = re.compile(r"(?:note|tip|important|warning|caution|注意|提示|警告|重要)\s*[:：]", re.I)
# 这些章节讲的是怎么装、怎么用、怎么参与，不是项目是什么。只认标题开头（前面可以有编号或表情）：
# 「Build your own X」不是构建章节，「Building from source」才是。
_SKIP_SECTION = re.compile(
    r"^[^\w]*(?:\d+[.)]?\s*)?(?:"
    r"install|setup\b|set up\b|getting started|get started|quick ?start|usage\b|how to use"
    r"|build(?:ing)?(?:\s+(?:from source|locally|instructions|and run\w*)|\s*$)|develop|contribut|licen[cs]e"
    r"|table of contents|contents\s*$|toc\s*$|faq\b|changelog|release|requirements|prerequisites|configur|deploy"
    r"|docker\b|api reference|examples?\b|demo|screenshots?\b|sponsor|backers?\b|acknowledg|credits\b|citation"
    r"|cite\b|star history|contact|support\b|community|roadmap"
    r"|安装|部署|快速开始|快速上手|开始使用|使用|用法|开发|构建|编译|贡献|许可|协议|目录|常见问题|更新日志|配置"
    r"|示例|演示|截图|赞助|致谢|引用|联系|社区|路线图|インストール|使い方|ライセンス)",
    re.I,
)

_IMAGE = re.compile(r"!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>", re.I)
_CODE = re.compile(r"`+([^`]+)`+")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EM = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_LEFTOVER_MARKS = re.compile(r"(?<!\w)(?:\*{2,}|_{2,})(?!\w)")
_EMOJI = re.compile(r":[a-z0-9_+-]+:")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_SEPARATORS = re.compile(r"\s*[|·•]\s*")
_SENTENCE_END = re.compile(r"[。！？!?](?=\s|$)|\.(?=\s|$)")
_WORD = re.compile(r"\w")


def _wide(char: str) -> bool:
    return "⺀" <= char <= "鿿" or "가" <= char <= "힯" or "＀" <= char <= "￯"


def _weight(text: str) -> int:
    return sum(2 if _wide(char) else 1 for char in text)


def _letters(text: str) -> int:
    return len(_WORD.findall(text))


def _strip_fences(text: str) -> str:
    """去掉围栏代码块；没收尾的围栏一直去到结尾。"""
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        stripped = line.lstrip()
        if fence:
            closing = stripped.rstrip()
            if closing and set(closing) == {fence[0]} and len(closing) >= fence[1]:
                fence = None
            continue
        match = _FENCE.match(stripped)
        if match and len(line) - len(stripped) <= 3:
            fence = (match.group(1)[0], len(match.group(1)))
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def _flatten_html(text: str) -> str:
    """HTML 标题改写成 Markdown 标题、链接改写成 Markdown 链接，其余只留正文。"""
    text = _HTML_HEADING.sub(
        lambda match: f"\n\n{'#' * int(match.group(1))} {' '.join(_ANY_TAG.sub(' ', match.group(2)).split())}\n\n",
        text,
    )
    text = _DROP_ELEMENTS.sub("\n\n", text)
    text = _VOID_TAGS.sub("", text)
    text = _ANCHOR.sub(lambda match: f"[{' '.join(_ANY_TAG.sub(' ', match.group(1)).split()).replace(']', '')}](#)", text)
    text = _BREAK_TAG.sub("\n", text)
    text = _BLOCK_TAGS.sub("\n\n", text)
    return _INLINE_TAGS.sub("", text)


def _inline(text: str) -> str:
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _REF_LINK.sub(r"\1", text)
    text = _AUTOLINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _STRONG.sub(r"\2", text)
    text = _EM.sub(r"\2", text)
    text = _STRIKE.sub(r"\1", text)
    text = _LEFTOVER_MARKS.sub("", text)
    text = _EMOJI.sub("", text)
    text = _ESCAPE.sub(r"\1", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def _paragraph(lines: list[str]) -> str | None:
    """一块（空行隔开、标题之外）的几行若是正文，返回读得下去的文字；表格、列表、代码、告示与导航返回 None。"""
    stripped = [line.strip() for line in lines]
    if any(_TABLE_RULE.match(line) for line in stripped) or all(line.startswith("|") for line in stripped):
        return None
    if all(line.startswith(("    ", "\t")) for line in lines):
        return None
    if stripped[0].startswith(">") and (_ALERT.search(stripped[0]) or _NOTE.match(_inline(stripped[0].lstrip("> ")))):
        return None
    kept: list[str] = []
    for line in stripped:
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        if _LIST_ITEM.match(line):
            # 一段话后面直接接列表：话留下，列表不要；整块是列表就不算正文
            if not kept:
                return None
            break
        if _RULE.match(line) or _UNDERLINE.match(line) or _LINK_DEF.match(line):
            continue
        if _RST_DIRECTIVE.match(line) or _RST_FIELD.match(line):
            continue
        if line:
            kept.append(line)
    if not kept:
        return None
    raw = _IMAGE.sub("", " ".join(kept))
    text = _inline(raw)
    if _weight(text) < _MIN_PROSE or _NOTE.match(text):
        return None
    # 一排链接（文档 · 博客 · Discord）或整段就是一个链接：字几乎都在链接里
    link_letters = sum(_letters(_inline(label)) for label in _LINK.findall(raw) + _REF_LINK.findall(raw))
    if link_letters and link_letters > _letters(text) * 0.6:
        return None
    # 语言切换、导航：被 | · • 分成几截，每截都短
    parts = [part for part in _SEPARATORS.split(text) if part]
    if len(parts) >= 2 and max(_weight(part) for part in parts) <= 32:
        return None
    if _letters(text) < len(text) * 0.5:
        return None
    # 「安装：」「Quick start:」一类引子后面跟的是代码
    if text.endswith((":", "：")) and _weight(text) < _MIN_TAIL:
        return None
    return text


def _paragraphs(text: str, *, skip_sections: bool) -> Iterator[str]:
    """按阅读顺序给出正文段落；skip_sections 时跳过的章节到同级或更高一级的下一个标题为止。"""
    skip_level = 0

    def heading(level: int, title: str) -> None:
        nonlocal skip_level
        if skip_level and level > skip_level:
            return
        skip_level = level if skip_sections and _SKIP_SECTION.search(title) else 0

    for block in re.split(r"\n[ \t]*\n", text):
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        # Setext / reStructuredText 标题：一两行字配一道下划线（= 一级，其余二级）
        rule = next((line.strip() for line in lines if _UNDERLINE.match(line.strip())), None)
        if rule and len(lines) <= 3:
            title = " ".join(line.strip() for line in lines if not _UNDERLINE.match(line.strip()))
            heading(1 if rule[0] == "=" else 2, title)
            continue
        pending: list[str] = []
        for line in lines:
            match = _HEADING.match(line.strip())
            if not match:
                pending.append(line)
                continue
            if pending and not skip_level and (paragraph := _paragraph(pending)):
                yield paragraph
            pending = []
            heading(len(match.group(1)), match.group(2).strip().strip("#").strip())
        if pending and not skip_level and (paragraph := _paragraph(pending)):
            yield paragraph


def _truncate(text: str, room: int) -> str:
    """截到 room（汉字按两个算）以内：先找句末，太靠前就在词边截断加省略号。"""
    end = 0
    used = 0
    for index, char in enumerate(text):
        used += 2 if _wide(char) else 1
        if used > room:
            break
        end = index + 1
    head = text[:end]
    sentences = [match.end() for match in _SENTENCE_END.finditer(head)]
    if sentences and _weight(head[: sentences[-1]]) >= room * 0.4:
        return head[: sentences[-1]].strip()
    if end and not _wide(head[-1]):
        space = head.rfind(" ")
        if space >= len(head) * 0.6:
            head = head[:space]
    head = head.rstrip(" ,;:，；：、-–—(（[")
    return f"{head}…" if head else ""


def readme_intro(
    markdown: str | None,
    *,
    paragraphs: int = INTRO_PARAGRAPHS,
    limit: int = INTRO_CHARS,
) -> tuple[list[str], bool]:
    """README 开头最多 paragraphs 段正文，合计不超过 limit；第二项是后面还有没有摘进来的正文。"""
    if not markdown:
        return [], False
    text = markdown.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")[:_SCAN_CHARS]
    text = _FRONT_MATTER.sub("", text)
    text = _HTML_COMMENT.sub("", text)
    text = _flatten_html(_strip_fences(text))

    # 跳过章节后一段都没有（项目名恰好以 Docker、Install 开头之类），不跳章节再摘一遍
    for skip_sections in (True, False):
        out: list[str] = []
        used = 0
        for paragraph in _paragraphs(text, skip_sections=skip_sections):
            if len(out) >= paragraphs or used >= limit:
                return out, True
            weight = _weight(paragraph)
            if used + weight > limit:
                if out and limit - used < _MIN_TAIL:
                    return out, True
                cut = _truncate(paragraph, limit - used)
                if cut:
                    out.append(cut)
                return out, True
            out.append(paragraph)
            used += weight
        if out:
            return out, False
    return [], False
