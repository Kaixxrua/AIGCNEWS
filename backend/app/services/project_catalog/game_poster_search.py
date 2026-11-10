"""Killable DDGS worker, using the same engines as dashboard PublicWebResearch.

This module deliberately imports no application configuration. Public query and
proxy configuration arrive over stdin, never command arguments or log output.
"""
from __future__ import annotations

import json
import re
import sys
import time
from urllib.parse import unquote, urlsplit

SEARCH_ENGINES = frozenset({"yahoo", "duckduckgo", "google", "brave", "startpage", "mojeek", "wikipedia"})
SEARCH_PAGE_BYTES = 1024 * 1024
SEARCH_OUTPUT_BYTES = 32000


def bounded_engines(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 2 or any(not isinstance(item, str) or item not in SEARCH_ENGINES for item in value):
        raise ValueError("invalid engines")
    return tuple(dict.fromkeys(value))


def _yahoo_result_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.hostname == "r.search.yahoo.com":
            match = re.search(r"/RU=(.*?)/(?:RK|RS)=", value)
            if not match:
                return ""
            value = unquote(match[1])
            parts = urlsplit(value)
        host = parts.hostname or ""
        if (parts.scheme != "https" or not host or parts.username is not None or parts.password is not None
                or parts.port is not None or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value)
                or host == "yahoo.com" or host.endswith(".yahoo.com")
                or ((host == "bing.com" or host.endswith(".bing.com")) and parts.path.startswith("/aclick"))):
            return ""
    except (ValueError, UnicodeError):
        return ""
    return value


def parse_yahoo_results(body: str) -> list[dict[str, str]]:
    """Parse both Yahoo organic layouts from one actually fetched response."""
    from bs4 import BeautifulSoup

    if not isinstance(body, str) or len(body.encode("utf-8")) > SEARCH_PAGE_BYTES:
        return []
    soup = BeautifulSoup(body, "html.parser")
    results, seen = [], set()
    for heading in soup.select("h3.title")[:100]:
        container = heading.find_parent(lambda tag: bool(set(tag.get("class", [])) & {"algo", "algo-sr", "relsrch"}))
        if container is None:
            continue
        anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
        if anchor is None or not (url := _yahoo_result_url(str(anchor.get("href") or ""))) or url in seen:
            continue
        text = container.select_one(".compText")
        title = " ".join(heading.get_text(" ", strip=True).split())[:300]
        if not title:
            continue
        seen.add(url)
        results.append({"url": url, "title": title,
                        "snippet": " ".join(text.get_text(" ", strip=True).split())[:600] if text else ""})
        if len(results) == 6:
            break
    return results


def _yahoo_challenge(body: str) -> bool:
    """Do not retry a provider challenge or consent page as an empty search."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    if soup.select_one(".g-recaptcha, .h-captcha, #captcha, #recaptcha, #challenge-form, input[name='captcha']"):
        return True
    for tag in soup.find_all(["form", "iframe"])[:50]:
        address = str(tag.get("action") or tag.get("src") or "").lower()
        if any(marker in address for marker in ("captcha", "/challenge", "consent.yahoo.com")):
            return True
    for tag in soup(["script", "style"]):
        tag.decompose()
    visible = " ".join(soup.get_text(" ", strip=True).lower().split())
    return any(phrase in visible for phrase in (
        "verify you are human", "verify that you are human", "verify you're human", "complete the captcha",
        "prove you're not a robot", "unusual traffic", "automated requests", "verify your identity to continue",
    ))


def _search_yahoo(query: str, proxy: str | None, timeout: int, attempt: dict, *, deadline: float) -> list[dict[str, str]]:
    # DDGS 9.16 only recognizes relsrch. Reuse its same endpoint and transport,
    # but parse its alternate algo layout too. Only a normal 200 empty response
    # receives one retry, within the original worker deadline, not a new budget.
    from ddgs.engines.yahoo import Yahoo

    for retry in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            attempt.update(status="unavailable", reason="worker_deadline")
            return []
        engine = Yahoo(proxy=proxy, timeout=min(timeout, int(remaining)))
        payload = engine.build_payload(query, region="us-en", safesearch="moderate", timelimit=None)
        attempt["retryCount"] = retry
        response = engine.http_client.request("GET", engine.search_url, params=payload)
        attempt.update(httpStatus=response.status_code, parser="yahoo_headings")
        if response.status_code != 200:
            attempt.update(status="unavailable", reason="provider_http")
            return []
        body = response.text
        if len(body.encode("utf-8")) > SEARCH_PAGE_BYTES:
            attempt.update(status="unavailable", reason="provider_response_oversize")
            return []
        if rows := parse_yahoo_results(body):
            return rows
        if _yahoo_challenge(body):
            attempt.update(status="unavailable", reason="provider_challenge")
            return []
    return []


def _search_ddgs(query: str, proxy: str | None, timeout: int, engine: str) -> list[dict[str, str]]:
    from ddgs import DDGS

    with DDGS(proxy=proxy, timeout=timeout) as search:
        rows = search.text(query, backend=engine, region="us-en", max_results=6)
    return [{"url": str(row.get("href") or "")[:2048],
             "title": str(row.get("title") or "")[:300],
             "snippet": str(row.get("body") or "")[:600]} for row in rows[:6]]


def search_results(query: str, proxy: str | None, engines: tuple[str, ...]) -> dict:
    attempts = []
    deadline = time.monotonic() + 20
    for engine in bounded_engines(engines):
        started = time.monotonic()
        remaining = deadline - started
        if remaining < 1:
            attempts.append({"engine": engine, "status": "unavailable", "reason": "worker_deadline"})
            break
        attempt = {"engine": engine, "status": "empty"}
        attempts.append(attempt)
        try:
            timeout = min(8, max(1, int(remaining)))
            rows = _search_yahoo(query, proxy, timeout, attempt, deadline=deadline) if engine == "yahoo" else _search_ddgs(query, proxy, timeout, engine)
            attempt["resultCount"] = len(rows)
            if rows:
                attempt["status"] = "succeeded"
                return {"engine": engine, "results": rows, "attempts": attempts}
        except Exception as exc:
            # Messages can contain proxy credentials or response bodies.
            attempt.update(status="unavailable", errorType=type(exc).__name__)
        finally:
            attempt["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return {"engine": "ddgs", "results": [], "unavailable": any(row["status"] == "unavailable" for row in attempts), "attempts": attempts}


def encode_result(result: dict) -> str:
    # UTF-8 result text must fit the parent's 32 KiB output limit.
    payload = json.dumps(result, ensure_ascii=False)
    while len(payload.encode("utf-8")) > SEARCH_OUTPUT_BYTES and result.get("results"):
        result["results"].pop()
        payload = json.dumps(result, ensure_ascii=False)
    if len(payload.encode("utf-8")) > SEARCH_OUTPUT_BYTES:
        return '{"unavailable":true,"results":[]}'
    return payload


def main() -> None:

    data = json.loads(sys.stdin.buffer.read(8192))
    query = data.get("query")
    if not isinstance(query, str) or not 3 <= len(query) <= 300 or re.search(r"[\x00-\x1f\x7f]", query):
        raise ValueError("invalid query")
    result = search_results(query, data.get("proxy") or None, bounded_engines(data.get("engines", ["google", "yahoo"])))
    print(encode_result(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Provider exceptions can include proxy credentials; never print them.
        print('{"unavailable":true,"results":[]}')
