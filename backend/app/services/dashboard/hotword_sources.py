"""First-party public feeds; a feed is a discovery channel, not an extra vote."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import feedparser
from bs4 import BeautifulSoup

AI_CONTEXT = re.compile(r"\b(AI|LLMs?|GPT[\w‑.-]*|ChatGPT|Claude|Gemini|Sonnet|Haiku|Qwen[\w.-]*|DeepSeek|Mistral|Llama|Grok|neural|machine learning|language models?|diffusion|transformers?)\b|人工智能|大模型|语言模型|神经网络|机器学习|生成式|智能体", re.I)
OFFICIAL_ACCOUNTS = {"openai": "openai.com", "chatgpt": "openai.com", "anthropicai": "anthropic.com",
                     "claudeai": "anthropic.com", "google": "google.com", "googleai": "google.com",
                     "googledeepmind": "google.com", "geminiapp": "google.com", "mistralai": "mistral.ai"}

@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    group: str
    domains: tuple[str, ...]


FEEDS = (
    Feed("OpenAI", "https://openai.com/news/rss.xml", "official", ("openai.com",)),
    Feed("Google AI", "https://blog.google/technology/ai/rss/", "official", ("blog.google",)),
    Feed("Google DeepMind", "https://deepmind.google/blog/rss.xml", "official", ("deepmind.google",)),
    Feed("Hugging Face", "https://huggingface.co/blog/feed.xml", "official", ("huggingface.co",)),
    Feed("NVIDIA", "https://blogs.nvidia.com/feed/", "official", ("nvidia.com",)),
    Feed("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "official", ("microsoft.com",)),
    Feed("Microsoft Blog", "https://blogs.microsoft.com/feed/", "official", ("microsoft.com",)),
    Feed("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/", "official", ("amazon.com",)),
    Feed("Google Research", "https://research.google/blog/rss/", "official", ("research.google",)),
    Feed("BAIR", "https://bair.berkeley.edu/blog/feed.xml", "research", ("berkeley.edu",)),
    Feed("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "media", ("techcrunch.com",)),
    Feed("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "media", ("theverge.com",)),
    Feed("Ars Technica AI", "https://arstechnica.com/tag/artificial-intelligence/feed/", "media", ("arstechnica.com",)),
    Feed("The Decoder", "https://the-decoder.com/feed/", "media", ("the-decoder.com",)),
    Feed("MarkTechPost", "https://www.marktechpost.com/feed/", "media", ("marktechpost.com",)),
    Feed("MIT Technology Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed/", "media", ("technologyreview.com",)),
    Feed("WIRED AI", "https://www.wired.com/feed/tag/ai/latest/rss", "media", ("wired.com",)),
    Feed("ZDNET AI", "https://www.zdnet.com/topic/artificial-intelligence/rss.xml", "media", ("zdnet.com",)),
    Feed("Unite.AI", "https://www.unite.ai/feed/", "media", ("unite.ai",)),
    Feed("TestingCatalog", "https://www.testingcatalog.com/rss/", "media", ("testingcatalog.com",)),
    Feed("InfoQ AI", "https://feed.infoq.com/ai-ml-data-eng", "media", ("infoq.com",)),
    Feed("Simon Willison", "https://simonwillison.net/atom/everything/", "community", ("simonwillison.net",)),
    Feed("Interconnects", "https://www.interconnects.ai/feed", "community", ("interconnects.ai",)),
    Feed("Import AI", "https://importai.substack.com/feed", "community", ("importai.substack.com",)),
    Feed("Ethan Mollick", "https://www.oneusefulthing.org/feed", "community", ("oneusefulthing.org",)),
    Feed("Lilian Weng", "https://lilianweng.github.io/index.xml", "community", ("lilianweng.github.io",)),
    Feed("Andrej Karpathy", "https://karpathy.bearblog.dev/feed/", "community", ("karpathy.bearblog.dev",)),
    Feed("IEEE Spectrum AI", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "media", ("ieee.org",)),
    Feed("Google Developers", "https://developers.googleblog.com/feeds/posts/default?alt=rss", "official", ("googleblog.com",)),
    Feed("Cloudflare AI", "https://blog.cloudflare.com/tag/ai/rss/", "official", ("cloudflare.com",)),
    Feed("Replicate", "https://replicate.com/blog/rss", "official", ("replicate.com",)),
)


def on_domain(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def source_group(doc: dict[str, Any]) -> str:
    host = (urlsplit(str(doc.get("url") or "")).hostname or "").removeprefix("www.")
    # Classify the actual publisher, not the transport that discovered its URL.
    for feed in FEEDS:
        if on_domain(host, feed.domains):
            return feed.group
    if on_domain(host, ("openai.com", "anthropic.com", "google.com", "mistral.ai", "qwen.ai", "qwenlm.github.io", "moonshot.ai")):
        return "official"
    if on_domain(host, ("arxiv.org", "openreview.net")) or doc.get("source") == "arxiv":
        return "research"
    if host in {"x.com", "twitter.com"} and urlsplit(str(doc["url"])).path.strip("/").split("/")[0].lower() in OFFICIAL_ACCOUNTS:
        return "official"
    if host in {"x.com", "twitter.com", "news.ycombinator.com"} or doc.get("source") in {"x", "hackernews"}:
        return "community"
    return "media"


def parse_feed(raw: bytes, feed: Feed, now: datetime) -> list[dict[str, Any]] | None:
    # Bytes only: feedparser must never fetch entry URLs or external entities.
    parsed = feedparser.parse(raw)
    if not parsed.version:
        return None
    result = []
    for entry in parsed.entries[:100]:
        stamp = entry.get("published_parsed")  # updated/crawl time never dates a launch
        if not stamp:
            continue
        try:
            published = datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc)
        except (ValueError, OverflowError):
            continue
        url = str(entry.get("link") or "")
        try:
            parts = urlsplit(url)
            if parts.port not in {None, 80, 443}:
                continue
        except ValueError:
            continue
        if (parts.scheme not in {"https", "http"} or parts.username or parts.password
                or not on_domain(parts.hostname or "", feed.domains)
                or not now - timedelta(days=7) <= published <= now):
            continue
        title = BeautifulSoup(str(entry.get("title") or ""), "html.parser").get_text(" ", strip=True)
        summary = BeautifulSoup(str(entry.get("summary") or ""), "html.parser").get_text(" ", strip=True)
        if title:
            result.append({"url": url, "title": title[:300], "summary": summary[:3000],
                           "published_at": published.isoformat(), "evidence_kind": "feed",
                           "feed_url": feed.url})
    return sorted(result, key=lambda doc: doc["published_at"], reverse=True)[:20]
