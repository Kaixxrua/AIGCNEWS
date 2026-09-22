#!/usr/bin/env python3
"""Agent end-to-end latency benchmark: AIGC Radar MCP tools vs WebSearch.

For each of 10 distinct prompt pairs, spawns two headless `claude -p` runs
(stream-json): one restricted to the target MCP tool, one restricted to
WebSearch. Both sides use the same model/effort and are instructed to answer
in at most two short sentences, so the answer-generation phase is comparable.

Recorded per run (seconds, wall clock from process spawn):
- total:      spawn -> final `result/success` event (end-to-end task time)
- tool_call:  assistant `tool_use` event -> matching user `tool_result` event
              (pure client-observed tool execution; for WebSearch this window
              is often ~0 because the search executes inside the API turn)
"""
from __future__ import annotations

import argparse
import json
import selectors
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PAIRS = [
    {"id": "llm_observability", "mcp_tool": "search_github_ai_projects",
     "mcp_args": {"q": "self-hosted LLM observability platform open source", "limit": 10},
     "ws_query": "self-hosted LLM observability platform open source"},
    {"id": "screenshot_tool", "mcp_tool": "search_github_projects",
     "mcp_args": {"q": "open source screenshot tool for Windows with rounded corners", "limit": 10},
     "ws_query": "open source screenshot tool for Windows with rounded corners"},
    {"id": "moe_paper", "mcp_tool": "search_papers",
     "mcp_args": {"q": "mixture of experts load balancing", "limit": 10},
     "ws_query": "mixture of experts load balancing paper"},
    {"id": "sora_news", "mcp_tool": "search_documents",
     "mcp_args": {"q": "Sora video generation model", "limit": 10},
     "ws_query": "Sora video generation model"},
    {"id": "github_weekly", "mcp_tool": "get_top_items",
     "mcp_args": {"source": "github", "period": "weekly", "limit": 10},
     "ws_query": "trending GitHub repositories this week"},
    {"id": "mcp_database", "mcp_tool": "search_github_ai_projects",
     "mcp_args": {"q": "MCP server for database access", "limit": 10},
     "ws_query": "MCP server for database access"},
    {"id": "photo_management", "mcp_tool": "search_github_projects",
     "mcp_args": {"q": "self-hosted photo management like Google Photos", "limit": 10},
     "ws_query": "self-hosted photo management like Google Photos"},
    {"id": "rlhf_paper", "mcp_tool": "search_papers",
     "mcp_args": {"q": "RLHF reward model overoptimization", "limit": 10},
     "ws_query": "RLHF reward model overoptimization paper"},
    {"id": "hn_monthly", "mcp_tool": "get_top_items",
     "mcp_args": {"source": "hackernews", "period": "monthly", "limit": 10},
     "ws_query": "top Hacker News stories this month"},
    {"id": "agent_skills", "mcp_tool": "search_documents",
     "mcp_args": {"q": "Claude Code agent skills", "limit": 10},
     "ws_query": "Claude Code agent skills"},
]

ANSWER_RULE = "Then answer in at most two short sentences."


def run_once(*, claude: str, model: str, endpoint: str, target_tool: str, prompt: str,
             output_dir: Path, tag: str, timeout: float, cwd: Path) -> dict:
    servers = {}
    if target_tool.startswith("mcp__"):
        servers = {"aigc-news": {"type": "http", "url": endpoint}}
    config_file = output_dir / f"mcp-{tag}.json"
    config_file.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    trace_file = output_dir / f"{tag}.stream.jsonl"
    command = [
        claude, "-p", prompt,
        "--model", model,
        "--effort", "low",
        "--mcp-config", str(config_file),
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--output-format", "stream-json",
        "--verbose",
        "--tools", target_tool,
        "--allowedTools", target_tool,
        "--max-budget-usd", "0.50",
    ]
    t_use = t_result = t_final = None
    timed_out = False
    start = time.monotonic()
    with trace_file.open("w", encoding="utf-8") as trace:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            if time.monotonic() - start > timeout:
                timed_out = True
                process.terminate()
                break
            ready = selector.select(timeout=0.2)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            trace.write(line)
            trace.flush()
            now = time.monotonic()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "result":
                t_final = now
                break
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            role = etype or message.get("role")
            if role == "assistant":
                for block in content:
                    if isinstance(block, dict) and block.get("type") in {"tool_use", "server_tool_use"} \
                            and block.get("name") == target_tool and t_use is None:
                        t_use = now
            elif role == "user":
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result" and t_use is not None:
                        t_result = now
                        break
        selector.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    total = None if t_final is None else round(t_final - start, 3)
    tool_call = None if t_use is None or t_result is None else round(t_result - t_use, 3)
    return {"tool": target_tool, "total_s": total, "tool_call_s": tool_call,
            "timed_out": timed_out, "exit_code": process.returncode, "trace": str(trace_file)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/mcp")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--claude", default="claude")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path(tempfile.gettempdir()) / f"aigc-e2e-latency-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    cwd = Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1] / ".git").exists() else Path.cwd()

    rows = []
    for pair in PAIRS:
        mcp_tool = f"mcp__aigc_news__{pair['mcp_tool']}"
        mcp_prompt = (
            f"Call the tool {mcp_tool} exactly once with these arguments: "
            f"{json.dumps(pair['mcp_args'], ensure_ascii=False)}. Do not call any other tool. {ANSWER_RULE}"
        )
        mcp = run_once(claude=args.claude, model=args.model, endpoint=args.endpoint,
                       target_tool=mcp_tool, prompt=mcp_prompt, output_dir=output_dir,
                       tag=f"{pair['id']}-mcp", timeout=args.timeout, cwd=cwd)
        print(f"[mcp] {pair['id']}: total={mcp['total_s']} tool={mcp['tool_call_s']}", flush=True)

        ws_prompt = (
            f"Call the WebSearch tool exactly once with query: \"{pair['ws_query']}\". "
            f"Do not call any other tool. {ANSWER_RULE}"
        )
        ws = run_once(claude=args.claude, model=args.model, endpoint=args.endpoint,
                      target_tool="WebSearch", prompt=ws_prompt, output_dir=output_dir,
                      tag=f"{pair['id']}-ws", timeout=args.timeout, cwd=cwd)
        print(f"[web] {pair['id']}: total={ws['total_s']} tool={ws['tool_call_s']}", flush=True)
        rows.append({"id": pair["id"], "ws_query": pair["ws_query"], "mcp": mcp, "websearch": ws})

    report = output_dir / "report.json"
    report.write_text(json.dumps({"endpoint": args.endpoint, "model": args.model, "pairs": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== summary (seconds) ===")
    print(f"{'pair':<20} {'mcp_total':>10} {'ws_total':>10} {'mcp_tool':>9}")
    mcp_tot, ws_tot, mcp_tool = [], [], []
    for row in rows:
        mt, wt, mc = row["mcp"]["total_s"], row["websearch"]["total_s"], row["mcp"]["tool_call_s"]
        print(f"{row['id']:<20} {mt if mt is not None else 'FAIL':>10} {wt if wt is not None else 'FAIL':>10} "
              f"{mc if mc is not None else '-':>9}")
        if mt is not None:
            mcp_tot.append(mt)
        if wt is not None:
            ws_tot.append(wt)
        if mc is not None:
            mcp_tool.append(mc)

    def stats(vals: list[float]) -> str:
        return f"median={statistics.median(vals):.3f} mean={statistics.mean(vals):.3f} " \
               f"min={min(vals):.3f} max={max(vals):.3f}"

    if mcp_tot:
        print(f"mcp_total:      {stats(mcp_tot)}")
    if ws_tot:
        print(f"websearch_total:{stats(ws_tot)}")
    if mcp_tool:
        print(f"mcp_tool_call:  {stats(mcp_tool)}")
    print(f"Report: {report}")
    ok = all(r["mcp"]["total_s"] is not None and r["websearch"]["total_s"] is not None for r in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
