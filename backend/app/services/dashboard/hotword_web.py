"""Bounded public search and dated original-page evidence for homepage hotwords."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from curl_cffi import CurlOpt, ffi, lib
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import AsyncSession

from backend.app.core.config import settings
from backend.app.services.dashboard.hotword_sources import AI_CONTEXT, FEEDS, on_domain, parse_feed
from backend.app.services.outbound_target_policy import pin_http_target

logger = logging.getLogger(__name__)
MAX_PAGE_BYTES = 1024 * 1024
MAX_PAGES = 128
MAX_REDIRECTS = 4
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "ScholarlyArticle", "TechArticle"}
_ORIGINAL_HOSTS = {"openai.com", "anthropic.com", "blog.google", "deepmind.google", "mistral.ai",
                   "huggingface.co", "qwenlm.github.io", "qwen.ai", "moonshot.ai"}


def canonical_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            return ""
        query = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
        return urlunsplit((url.scheme, url.netloc.lower(), url.path.rstrip("/"), urlencode(query), ""))
    except ValueError:
        return ""


def web_id(url: str) -> str:
    return "web:" + hashlib.sha256(canonical_url(url).encode()).hexdigest()[:32]


def timestamp(value: Any) -> datetime | None:
    # Never invent a date from a search snippet, HTTP header, crawl time or dateModified.
    if not isinstance(value, str) or not re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:$|[T ])", value.strip()):
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("/", "-").replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except ValueError:
        return None


def _article_dates(node: Any) -> list[datetime]:
    if isinstance(node, list):
        return [stamp for item in node for stamp in _article_dates(item)]
    if not isinstance(node, dict):
        return []
    types = node.get("@type", [])
    types = [types] if isinstance(types, str) else types
    result = []
    if isinstance(types, list) and _ARTICLE_TYPES.intersection(t for t in types if isinstance(t, str)):
        stamp = timestamp(node.get("datePublished"))
        if stamp:
            result.append(stamp)
    # Only article entities, not publication dates on comments or recommended links.
    for key in ("@graph", "mainEntity"):
        result.extend(_article_dates(node.get(key)))
    return result


def parse_page(url: str, html: str | bytes, now: datetime) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    dates = []
    for meta in soup.find_all("meta"):
        name = str(meta.get("property") or meta.get("name") or "").lower()
        if name in {"article:published_time", "citation_date", "citation_publication_date", "datepublished", "pubdate"}:
            stamp = timestamp(meta.get("content"))
            if stamp:
                dates.append(stamp)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            dates.extend(_article_dates(json.loads(script.get_text())))
        except (ValueError, TypeError, RecursionError):
            continue
    for element in soup.select('[itemprop="datePublished"]'):
        stamp = timestamp(element.get("datetime") or element.get("content") or element.get_text(strip=True))
        if stamp:
            dates.append(stamp)
    # arXiv v2+ pages retain their original v1 submission date in this history.
    history = soup.select_one(".submission-history")
    if urlsplit(url).hostname in {"arxiv.org", "export.arxiv.org"} and history:
        first = re.search(r"\[v1\]\s*(?:\w+,\s*)?(\d{1,2} \w{3} \d{4})(?:\s+(\d{2}:\d{2}:\d{2}))?",
                          history.get_text(" ", strip=True))
        if first:
            try:
                value = first[1] + (" " + first[2] if first[2] else "")
                pattern = "%d %b %Y %H:%M:%S" if first[2] else "%d %b %Y"
                dates = [datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)]
            except ValueError:
                pass
    if not dates or min(dates) > now:
        return None
    title_node = soup.find("meta", attrs={"name": "citation_title"})
    title = str(title_node.get("content") or "") if title_node else ""
    if not title:
        title_node = soup.find("h1") or soup.title
        title = title_node.get_text(" ", strip=True) if title_node else ""
    # The abstract is the original source text, not an aggregator/search summary.
    body = soup.select_one("blockquote.abstract") or soup.find("article") or soup.find("main") or soup
    for node in body.select('script, style, nav, header, footer, aside, form, button, noscript, iframe, '
                            '[class*="related"], [id*="related"], [class*="recommend"], [id*="recommend"], '
                            '.comments, .comment-list'):
        if node.parent is not None:
            node.decompose()
    primary_urls = []
    for link in body.select("a[href]"):
        address = canonical_url(urljoin(url, str(link.get("href") or "")))
        parts = urlsplit(address)
        if parts.hostname in {"arxiv.org", "export.arxiv.org"}:
            match = re.fullmatch(r"/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", parts.path)
            if match:
                primary_urls.append("https://arxiv.org/abs/" + match[1])
        elif parts.hostname in {"doi.org", "openreview.net"}:
            primary_urls.append(address)
        elif parts.hostname and parts.hostname.removeprefix("www.") in _ORIGINAL_HOSTS and len(parts.path.strip("/").split("/")) >= 2:
            primary_urls.append(address)
    content = " ".join(body.get_text(" ", strip=True).split())[:16000]
    content = re.sub(r"^Abstract\s*[:：]\s*", "", content, flags=re.I)
    if not title.strip() or len(content) < 80:
        return None
    return {"id": web_id(url), "source": "web", "title": title.strip()[:300], "url": canonical_url(url),
            "summary": content, "published_at": min(dates).isoformat(), "verified_at": now.isoformat(),
            "primary_urls": list(dict.fromkeys(primary_urls))[:2]}


def verified_citation(doc: dict[str, Any], generated_at: datetime) -> bool:
    url = canonical_url(str(doc.get("url") or ""))
    verified, published = timestamp(doc.get("verified_at")), timestamp(doc.get("published_at"))
    if doc.get("evidence_kind") == "feed" and not any(
        doc.get("feed_url") == feed.url and on_domain(urlsplit(url).hostname or "", feed.domains) for feed in FEEDS
    ):
        return False
    return bool(url and doc.get("source") == "web" and doc.get("id") == web_id(url)
                and verified and published and generated_at - timedelta(days=7) <= published <= verified <= generated_at)


async def fetch_resource(url: str, *, feed: bool = False) -> tuple[str, bytes] | None:
    """Pin every redirect, limit decompressed bytes, and never forward credentials."""
    try:
        async with asyncio.timeout(15):
            for _ in range(MAX_REDIRECTS + 1):
                target = await asyncio.to_thread(pin_http_target, url, allowed_ports={80, 443}, reject_mixed=True)
                parsed = urlsplit(target.logical_url)
                if not parsed.hostname.isascii():
                    # Reject ambiguous IDNA rewriting until the shared URL policy
                    # supplies an ASCII logical host matching libcurl's URL host.
                    return None
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
                ip = f"[{target.selected_ip}]" if ":" in target.selected_ip else target.selected_ip
                # CONNECT_TO pins the TCP/SOCKS/HTTP CONNECT destination while the
                # original URL continues to supply SNI and certificate verification.
                # IP-address request URLs lose hostname validation through proxy tunnels.
                connections = lib.curl_slist_append(ffi.NULL, f"{host}:{port}:{ip}:{port}".encode())
                if connections == ffi.NULL:
                    return None
                body = bytearray()

                def receive(chunk: bytes) -> int:
                    if len(body) + len(chunk) > MAX_PAGE_BYTES:
                        return CURL_WRITEFUNC_ERROR
                    body.extend(chunk)
                    return len(chunk)

                try:
                    # curl_cffi accepts this libcurl slist pointer for CONNECT_TO;
                    # it must outlive the request and be freed after the session.
                    async with AsyncSession(
                        proxy=settings.outbound_proxy or None, verify=True, trust_env=True,
                        headers={"User-Agent": "AIGCNEWS-Hotwords/1.0", "Accept":
                                 "application/rss+xml, application/atom+xml, application/xml, text/xml" if feed else "text/html"},
                        curl_options={CurlOpt.CONNECT_TO: connections, CurlOpt.HTTPPROXYTUNNEL: 1,
                                      CurlOpt.MAXFILESIZE_LARGE: MAX_PAGE_BYTES},
                    ) as client:
                        response = await client.get(target.logical_url, allow_redirects=False,
                                                    timeout=12, content_callback=receive)
                finally:
                    lib.curl_slist_free_all(connections)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    url = urljoin(target.logical_url, location)
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if response.status_code != 200 or ("xml" if feed else "html") not in content_type:
                    return None
                return target.logical_url, bytes(body)
    except Exception as exc:
        # Proxy addresses may contain secrets; never log exception text or fetched bodies.
        logger.debug("Hotword original-page fetch failed: %s", type(exc).__name__)
    return None


async def fetch_page(url: str, now: datetime) -> dict[str, Any] | None:
    resource = await fetch_resource(url)
    try:
        return parse_page(resource[0], resource[1], now) if resource else None
    except Exception as exc:
        logger.debug("Hotword original-page parsing failed: %s", type(exc).__name__)
        return None


@dataclass
class WebEvidence:
    documents: list[dict[str, Any]] = field(default_factory=list)
    available: bool = False
    channels: list[dict[str, Any]] = field(default_factory=list)


class PublicWebResearch:
    """One refresh owns bounded search/page caches; no request-time web/LLM calls."""

    def __init__(self) -> None:
        self._search_slots = asyncio.Semaphore(2)
        self._page_slots = asyncio.Semaphore(4)
        self._pages: dict[str, asyncio.Task] = {}

    async def _search(self, query: str, recent: bool) -> list[str]:
        from ddgs import DDGS

        def run() -> list[str]:
            # These public engines were verified through the deployed outbound proxy.
            with DDGS(proxy=settings.outbound_proxy or None, timeout=10) as search:
                region = "cn-zh" if re.search(r"[\u4e00-\u9fff]", query) else "us-en"
                rows = search.text(query, backend="bing,yahoo", region=region,
                                   timelimit="w" if recent else None, max_results=6)
            return [str(row.get("href") or "") for row in rows[:6]]

        async with self._search_slots:
            async with asyncio.timeout(25):
                return await asyncio.to_thread(run)

    async def _scan(self, queries: list[str], now: datetime, *, recent: bool,
                    seed_urls: list[str] | None = None, page_limit: int | None = None) -> WebEvidence:
        result = WebEvidence()

        async def fetch(url: str) -> dict[str, Any] | None:
            async with self._page_slots:
                return await fetch_page(url, now)

        def page_tasks(urls: list[str]) -> list[asyncio.Task]:
            tasks = []
            for raw in urls:
                url = canonical_url(raw)
                if not url:
                    continue
                if url not in self._pages and len(self._pages) < min(MAX_PAGES, page_limit or MAX_PAGES):
                    self._pages[url] = asyncio.create_task(fetch(url))
                if url in self._pages:
                    tasks.append(self._pages[url])
            return tasks

        async def read_pages(urls: list[str]) -> None:
            documents = await asyncio.gather(*page_tasks(urls))
            result.documents.extend(doc for doc in documents if doc)
            originals = [link for doc in documents if doc for link in doc.get("primary_urls", [])]
            primary_docs = await asyncio.gather(*page_tasks(originals))
            result.documents.extend(doc for doc in primary_docs if doc)

        async def search(query: str) -> None:
            try:
                urls = await self._search(query, recent)
                result.available = True
                await read_pages(urls)
            except Exception as exc:
                logger.debug("Hotword public search failed: %s", type(exc).__name__)

        try:
            async with asyncio.timeout(100):
                await asyncio.gather(read_pages(seed_urls or []), *(search(query) for query in queries))
        except TimeoutError:
            logger.warning("Hotword public search reached its time budget")
        finally:
            pending = [task for task in self._pages.values() if not task.done()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self._pages = {url: task for url, task in self._pages.items() if not task.cancelled()}
        result.documents = list({doc["id"]: doc for doc in result.documents}.values())
        logger.info("Hotword public evidence: available=%s verified_pages=%d", result.available, len(result.documents))
        return result

    async def discover(self, now: datetime, *, seed_urls: list[str] | None = None) -> WebEvidence:
        feeds = await self.read_feeds(now)
        # Round-robin publisher feeds before taking a second article from any.
        buckets = [[doc for doc in feeds.documents if doc["feed_url"] == feed.url] for feed in FEEDS]
        firsts = [bucket[0]["url"] for bucket in buckets if bucket]
        seconds = [bucket[1]["url"] for bucket in buckets if len(bucket) > 1]
        urls = list(dict.fromkeys([*firsts, *(seed_urls or []), *seconds]))[:max(1, MAX_PAGES // 3)]
        result = await self._scan([
            f'AI new features developer tools {now:%B %Y}',
            f'AI 新模型 新产品 新功能 发布 {now:%Y年%m月}',
            f'site:openai.com/index/ OR site:anthropic.com/news/ AI {now:%B %Y}',
            f'site:blog.google OR site:deepmind.google AI new {now:%B %Y}',
            f'site:qwen.ai OR site:deepseek.com OR site:moonshot.ai AI {now:%B %Y}',
            f'site:mistral.ai OR site:x.ai OR site:ai.meta.com AI {now:%B %Y}',
            f'site:ithome.com OR site:qbitai.com AI 大模型 发布 {now:%Y年%m月}',
            f'site:jiqizhixin.com OR site:infoq.cn AI 模型 新功能 {now:%Y年%m月}',
            f'site:venturebeat.com OR site:latent.space AI launch {now:%B %Y}',
        ], now, recent=True, seed_urls=urls, page_limit=max(2, MAX_PAGES // 2))
        # Full pages precede their own feed excerpts during document dedup.
        result.documents.extend(feeds.documents)
        result.channels = feeds.channels
        result.available = result.available or feeds.available
        return result

    async def read_feeds(self, now: datetime) -> WebEvidence:
        result = WebEvidence()

        async def read(feed) -> None:
            try:
                async with self._page_slots:
                    resource = await fetch_resource(feed.url, feed=True)
                rows = await asyncio.to_thread(parse_feed, resource[1], feed, now) if resource else None
            except Exception:
                rows = None
            result.channels.append({"name": feed.name, "url": feed.url, "group": feed.group,
                                    "available": rows is not None, "recent_items": len(rows or [])})
            if rows is not None:
                result.available = True
                result.documents.extend({**doc, "source": "web", "id": web_id(doc["url"]),
                                         "verified_at": now.isoformat()} for doc in rows
                                        if AI_CONTEXT.search(doc["title"] + " " + doc["summary"]))

        await asyncio.gather(*(read(feed) for feed in FEEDS))
        logger.info("Hotword feed coverage: %s", json.dumps(result.channels, ensure_ascii=False))
        return result

    async def investigate(self, terms: list[str], now: datetime, *, contexts: dict[str, str] | None = None) -> WebEvidence:
        cutoff = (now - timedelta(days=7)).date().isoformat()
        queries = []
        for term in terms[:8]:
            quoted = '"' + term.replace('"', ' ').strip()[:80] + '"'
            # Preserve the primary title's subject: a short method acronym may
            # also name an airline route or an unrelated, much older project.
            context = re.sub(r"[^\w\s-]", " ", (contexts or {}).get(term, "AI"))[:180]
            queries.extend([quoted + " " + context, quoted + " " + context + " before:" + cutoff])
        return await self._scan(queries, now, recent=False) if queries else WebEvidence(available=True)
