"""Killable DDGS worker, using the same engines as dashboard PublicWebResearch.

This module deliberately imports no application configuration. Public query and
proxy configuration arrive over stdin, never command arguments or log output.
"""
from __future__ import annotations

import json
import sys

SEARCH_ENGINES = frozenset({"yahoo", "duckduckgo", "google", "brave", "startpage", "mojeek", "wikipedia"})


def bounded_engines(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 2 or any(not isinstance(item, str) or item not in SEARCH_ENGINES for item in value):
        raise ValueError("invalid engines")
    return tuple(dict.fromkeys(value))


def main() -> None:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException

    data = json.loads(sys.stdin.buffer.read(8192))
    query = data.get("query")
    if not isinstance(query, str) or not 3 <= len(query) <= 300:
        raise ValueError("invalid query")
    failed = False
    with DDGS(proxy=data.get("proxy") or None, timeout=8) as search:
        for engine in bounded_engines(data.get("engines", ["yahoo", "duckduckgo"])):
            try:
                rows = search.text(query, backend=engine, region="us-en", max_results=6)
            except DDGSException:
                failed = True
                continue
            if rows:
                result = [{"url": str(row.get("href") or "")[:2048],
                           "title": str(row.get("title") or "")[:300],
                           "snippet": str(row.get("body") or "")[:600]} for row in rows[:6]]
                print(json.dumps({"engine": engine, "results": result}))
                return
    print(json.dumps({"engine": "ddgs", "results": [], "unavailable": failed}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Provider exceptions can include proxy credentials; never print them.
        print('{"unavailable":true,"results":[]}')
