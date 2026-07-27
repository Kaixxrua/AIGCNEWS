from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from bs4 import BeautifulSoup

MAX_CONTENT_CHARS = 40_000

_NOISE_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "noscript",
    "iframe",
)


@dataclass(frozen=True)
class ContentEnrichmentPolicy:
    """纯策略结果；由后续适配层写回原 paper 以保留就地变更语义。"""

    full_text: str = ""
    fetch_url: str = ""
    fetch_github_readme: str = ""
    pdf_pending: Optional[bool] = None


def clean_html_text(html: str) -> str:
    """从 HTML 提取可读纯文本，保留既有清洗规则。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def compose_huggingface_content(
    paper: Mapping[str, Any],
) -> ContentEnrichmentPolicy:
    """组合 HuggingFace 标题、指标与摘要正文。"""
    abstract = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")
    pipeline_tag = paper.get("pipeline_tag", "")
    likes = paper.get("likes", 0)
    downloads = paper.get("downloads", 0)

    parts = []
    if title:
        parts.append(f"# {title}")
    if pipeline_tag:
        parts.append(
            f"Pipeline: {pipeline_tag} | Likes: {likes:,} | Downloads: {downloads:,}"
        )
    if abstract:
        parts.append(abstract)

    full_text = "\n\n".join(parts) if parts else title
    return ContentEnrichmentPolicy(
        full_text=full_text[:MAX_CONTENT_CHARS],
        pdf_pending=False,
    )


def select_github_content(
    paper: Mapping[str, Any],
    readme: Optional[str] = None,
) -> ContentEnrichmentPolicy:
    """选择已有 GitHub 正文，或请求 README 后组合描述与 README。"""
    abstract = paper.get("abstract", "") or ""
    if len(abstract) > 500:
        return ContentEnrichmentPolicy(full_text=abstract[:MAX_CONTENT_CHARS])

    full_name = paper.get("full_name") or paper.get("title") or ""
    if readme is None and full_name and "/" in full_name:
        return ContentEnrichmentPolicy(fetch_github_readme=full_name)

    description = paper.get("description") or paper.get("summary") or abstract
    if readme:
        full_text = f"{description}\n\nREADME:\n{readme}".strip()
    else:
        full_text = description
    return ContentEnrichmentPolicy(full_text=full_text[:MAX_CONTENT_CHARS])


def select_news_content(
    paper: Mapping[str, Any],
    page_text: Optional[str] = None,
) -> ContentEnrichmentPolicy:
    """选择 News 详情页正文，或回退到 RSS 摘要与标题。"""
    url = paper.get("url", "")
    summary = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")

    if page_text is None and url:
        return ContentEnrichmentPolicy(fetch_url=url)

    full_text = ""
    if page_text is not None and len(page_text) > len(summary) + 200:
        full_text = f"# {title}\n\n{page_text}"
    if not full_text:
        full_text = f"# {title}\n\n{summary}" if summary else title
    return ContentEnrichmentPolicy(full_text=full_text[:MAX_CONTENT_CHARS])


def compose_producthunt_content(
    paper: Mapping[str, Any],
) -> ContentEnrichmentPolicy:
    """组合 Product Hunt 标题与 tagline/description。"""
    abstract = paper.get("abstract", "") or paper.get("summary", "") or ""
    title = paper.get("title", "")
    full_text = f"# {title}\n\n{abstract}" if abstract else title
    return ContentEnrichmentPolicy(full_text=full_text[:MAX_CONTENT_CHARS])


def select_hackernews_content(
    paper: Mapping[str, Any],
    page_text: Optional[str] = None,
) -> ContentEnrichmentPolicy:
    """选择 Hacker News 外链正文、story_text 或标题。"""
    url = paper.get("url", "")
    title = paper.get("title", "")
    story_text = paper.get("abstract", "") or paper.get("summary", "") or ""
    hn_id = paper.get("hn_id", "")

    hn_item_url = f"https://news.ycombinator.com/item?id={hn_id}"
    is_internal = not url or url == hn_item_url or "news.ycombinator.com" in url
    if page_text is None and not is_internal and url:
        return ContentEnrichmentPolicy(fetch_url=url)

    full_text = ""
    if not is_internal and page_text is not None and len(page_text) > 200:
        full_text = f"# {title}\n\n{page_text}"
    if not full_text and story_text and story_text != title:
        full_text = f"# {title}\n\n{story_text}"
    if not full_text:
        full_text = title
    return ContentEnrichmentPolicy(full_text=full_text[:MAX_CONTENT_CHARS])
