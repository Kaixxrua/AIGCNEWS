#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


EXACT_PROMPT = "帮我找一下有没有github开源的哪个Windows的截图软件截图效果和macos的ishot一样，截图出来的图片是可以自定义为圆角的"
PROBES = {
    "exact": {
        "prompt": EXACT_PROMPT,
        "expected": "mcp__aigc-news__search_github_projects",
        "default_trials": 10,
    },
    "generic": {
        "prompt": "帮我找一个 GitHub 开源的 Windows 剪贴板管理软件，最好支持历史搜索和图片。",
        "expected": "mcp__aigc-news__search_github_projects",
        "default_trials": 5,
    },
    "ai": {
        "prompt": "帮我找几个 GitHub 开源的本地 RAG Web UI 项目。",
        "expected": "mcp__aigc-news__search_github_ai_projects",
        "default_trials": 5,
    },
    "paper": {
        "prompt": "帮我找几篇关于 RAG 检索增强生成的论文。",
        "expected": "mcp__aigc-news__search_papers",
        "default_trials": 5,
    },
}
MCP_TOOLS = [
    "mcp__aigc-news__search_papers",
    "mcp__aigc-news__get_paper_detail",
    "mcp__aigc-news__get_top_items",
    "mcp__aigc-news__search_github_projects",
    "mcp__aigc-news__search_github_ai_projects",
    "mcp__aigc-news__get_project_library",
    "mcp__aigc-news__get_project_categories",
]
HOST_TOOLS = ["WebSearch", "WebFetch", "Bash"]


@dataclass
class TrialResult:
    probe: str
    trial: int
    expected: str
    first_tools: list[str]
    passed: bool
    elapsed_seconds: float
    exit_code: int | None
    timed_out: bool
    trace_file: str
    stderr_file: str


def _tool_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        if value.get("type") in {"tool_use", "server_tool_use"} and isinstance(value.get("name"), str):
            names.append(value["name"])
        for item in value.values():
            names.extend(_tool_names(item))
    elif isinstance(value, list):
        for item in value:
            names.extend(_tool_names(item))
    return list(dict.fromkeys(names))


def _is_assistant_event(event: dict[str, Any]) -> bool:
    if event.get("type") == "assistant":
        return True
    message = event.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def run_trial(
    *,
    claude: str,
    model: str,
    endpoint: str,
    probe_name: str,
    trial: int,
    output_dir: Path,
    timeout: float,
    complete_turn: bool,
    cwd: Path,
) -> TrialResult:
    probe = PROBES[probe_name]
    config = {"mcpServers": {"aigc-news": {"type": "http", "url": endpoint}}}
    config_file = output_dir / f"mcp-{probe_name}-{trial}.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    trace_file = output_dir / f"{probe_name}-{trial}.stream.jsonl"
    stderr_file = output_dir / f"{probe_name}-{trial}.stderr.log"
    command = [
        claude,
        "-p",
        probe["prompt"],
        "--model",
        model,
        "--effort",
        "high",
        "--mcp-config",
        str(config_file),
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        ",".join(HOST_TOOLS),
        "--allowedTools",
        ",".join(HOST_TOOLS + MCP_TOOLS),
        "--max-budget-usd",
        "2.00",
    ]

    first_tools: list[str] = []
    timed_out = False
    start = time.monotonic()
    with trace_file.open("w", encoding="utf-8") as trace, stderr_file.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
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
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not first_tools and _is_assistant_event(event):
                first_tools = _tool_names(event)
                if first_tools and not complete_turn:
                    process.terminate()
                    break
        selector.close()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    expected = str(probe["expected"])
    passed = first_tools == [expected]
    return TrialResult(
        probe=probe_name,
        trial=trial,
        expected=expected,
        first_tools=first_tools,
        passed=passed,
        elapsed_seconds=round(time.monotonic() - start, 3),
        exit_code=process.returncode,
        timed_out=timed_out,
        trace_file=str(trace_file),
        stderr_file=str(stderr_file),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate first-tool routing for the AIGC_NEWS MCP server.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/mcp")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--claude", default="claude")
    parser.add_argument("--probe", choices=["all", *PROBES], default="all")
    parser.add_argument("--trials", type=int, help="Override the trial count for every selected probe.")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--complete-turn", action="store_true", help="Let each child finish after recording its first tool call.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path(tempfile.gettempdir()) / f"aigc-mcp-selection-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([args.claude, "--version"], capture_output=True, text=True, check=False).stdout.strip()
    selected = list(PROBES) if args.probe == "all" else [args.probe]

    results: list[TrialResult] = []
    for probe_name in selected:
        trial_count = args.trials or int(PROBES[probe_name]["default_trials"])
        for trial in range(1, trial_count + 1):
            result = run_trial(
                claude=args.claude,
                model=args.model,
                endpoint=args.endpoint,
                probe_name=probe_name,
                trial=trial,
                output_dir=output_dir,
                timeout=args.timeout,
                complete_turn=args.complete_turn,
                cwd=args.cwd.resolve(),
            )
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {probe_name} {trial}/{trial_count}: {result.first_tools or ['<none>']}", flush=True)

    summary: dict[str, Any] = {
        "claude_code_version": version,
        "model": args.model,
        "endpoint": args.endpoint,
        "complete_turn": args.complete_turn,
        "output_dir": str(output_dir),
        "probes": {},
        "results": [asdict(result) for result in results],
    }
    for probe_name in selected:
        probe_results = [result for result in results if result.probe == probe_name]
        summary["probes"][probe_name] = {
            "expected": PROBES[probe_name]["expected"],
            "passed": sum(result.passed for result in probe_results),
            "total": len(probe_results),
            "first_tool_counts": {
                name: sum(result.first_tools == [name] for result in probe_results)
                for name in sorted({name for result in probe_results for name in result.first_tools})
            },
        }
    report_file = output_dir / "summary.json"
    report_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["probes"], ensure_ascii=False, indent=2))
    print(f"Report: {report_file}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
