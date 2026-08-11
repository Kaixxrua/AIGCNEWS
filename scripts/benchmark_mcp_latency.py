#!/usr/bin/env python3
"""Latency benchmark for the AIGC Radar MCP endpoint (Streamable HTTP).

Performs one JSON-RPC ``initialize`` handshake, then times ``tools/call``
requests across the public read-only tools. Handles both ``application/json``
and ``text/event-stream`` response framings.

Usage:
    python3 scripts/benchmark_mcp_latency.py --url https://aigcnews.cn/api/mcp --trials 3
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request

CALLS = [
    ("search_github_ai_projects", {"q": "local RAG Web UI project", "limit": 10}),
    ("search_github_ai_projects", {"q": "MCP server evaluation benchmark", "limit": 10}),
    ("search_github_projects", {"q": "Windows clipboard manager open source", "limit": 10}),
    ("search_papers", {"q": "retrieval augmented generation survey", "limit": 10}),
    ("search_documents", {"q": "vLLM inference optimization news", "limit": 10}),
    ("get_top_items", {"source": "github", "period": "daily", "limit": 10}),
]


def post(url: str, payload: dict, session_id: str | None, timeout: float) -> tuple[dict, float, str | None]:
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "mcp-latency-bench/0.1",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        sid = resp.headers.get("Mcp-Session-Id")
        content_type = resp.headers.get("Content-Type", "")
    dt = time.perf_counter() - t0
    if "text/event-stream" in content_type:
        for line in raw.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    return json.loads(data), dt, sid
        raise RuntimeError(f"SSE response without data frame: {raw[:200]}")
    return json.loads(raw), dt, sid


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1))))
    return ordered[k]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://aigcnews.cn/api/mcp")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    init_payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mcp-latency-bench", "version": "0.1"},
        },
    }
    init_resp, init_dt, session_id = post(args.url, init_payload, None, args.timeout)
    server_info = init_resp.get("result", {}).get("serverInfo", {})
    print(
        f"initialize: {init_dt * 1000:.0f} ms | "
        f"server={server_info.get('name')} {server_info.get('version')} | session={session_id or 'none'}"
    )

    # notifications/initialized (best effort)
    try:
        post(args.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id, args.timeout)
    except Exception:
        pass

    results: dict[str, list[float]] = {}
    errors = 0
    for trial in range(1, args.trials + 1):
        for name, params in CALLS:
            payload = {
                "jsonrpc": "2.0",
                "id": trial * 100,
                "method": "tools/call",
                "params": {"name": name, "arguments": params},
            }
            try:
                resp, dt, _ = post(args.url, payload, session_id, args.timeout)
                if "error" in resp:
                    errors += 1
                    print(f"  trial{trial} {name}: RPC error {resp['error'].get('code')} {resp['error'].get('message', '')[:80]}")
                    continue
                results.setdefault(name, []).append(dt)
                print(f"  trial{trial} {name}: {dt * 1000:.0f} ms")
            except Exception as exc:
                errors += 1
                print(f"  trial{trial} {name}: FAILED {exc}")

    print("\n=== summary (seconds) ===")
    all_times: list[float] = []
    for name, times in results.items():
        all_times.extend(times)
        print(
            f"{name}: n={len(times)} p50={percentile(times, 50):.3f} p95={percentile(times, 95):.3f} "
            f"mean={statistics.mean(times):.3f} min={min(times):.3f} max={max(times):.3f}"
        )
    if all_times:
        print(
            f"ALL: n={len(all_times)} p50={percentile(all_times, 50):.3f} "
            f"p95={percentile(all_times, 95):.3f} mean={statistics.mean(all_times):.3f}"
        )
    print(f"errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
