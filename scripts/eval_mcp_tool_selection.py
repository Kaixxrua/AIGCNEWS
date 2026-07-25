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
    "indexed_news": {
        "prompt": "从 AIGC_NEWS 已索引内容里搜索最近关于模型推理的新闻和跨来源资料。",
        "expected": "mcp__aigc-news__search_documents",
        "default_trials": 5,
    },
    "agent_learning": {
        "prompt": "我想系统学习 AI Agent 和 MCP，请从已有资源里找一些教程、示例和学习材料。",
        "expected": "mcp__aigc-news__search_github_ai_projects",
        "default_trials": 5,
    },
    "agent_learning_exact": {
        "prompt": "我想要学习Agent相关的内容，帮我找一点资料进行学习",
        "expected": "mcp__aigc-news__search_github_ai_projects",
        "default_trials": 5,
    },
    "agent_academic": {
        "prompt": "请找几篇关于 AI Agent memory 和 planning 的论文或综述，并给出引用和实验研究方向。",
        "expected": "mcp__aigc-news__search_papers",
        "default_trials": 5,
    },
    "agent_mixed_implementation": {
        "prompt": "以 Agent 示例项目、教程和 SDK 实现为主，也可以附几篇论文。",
        "expected": "mcp__aigc-news__search_github_ai_projects",
        "default_trials": 5,
    },
    "agent_mixed_academic": {
        "prompt": "以 Agent 论文、survey、引用和实验结果为主，项目只作为补充。",
        "expected": "mcp__aigc-news__search_papers",
        "default_trials": 5,
    },
    "agent_projects": {
        "prompt": "帮我找几个 GitHub 开源的 Agent/MCP 完整项目，用来学习工具调用和工作流编排。",
        "expected": "mcp__aigc-news__search_github_ai_projects",
        "default_trials": 5,
    },
}
MCP_TOOLS = [
    "mcp__aigc-news__search_papers",
    "mcp__aigc-news__search_documents",
    "mcp__aigc-news__get_paper_detail",
    "mcp__aigc-news__get_top_items",
    "mcp__aigc-news__search_github_projects",
    "mcp__aigc-news__search_github_ai_projects",
    "mcp__aigc-news__get_project_library",
    "mcp__aigc-news__get_project_categories",
]
HOST_TOOLS = ["Agent", "WebSearch", "WebFetch", "Bash", "Skill", "multi_tool_use.parallel"]


@dataclass
class TrialResult:
    probe: str
    trial: int
    expected: str
    first_tools: list[str]
    tool_timeline: list[list[str]]
    timeline_complete: bool
    initial_host_tool_violations: list[str]
    host_tool_before_expected: list[str]
    host_tools_after_mcp: list[str]
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
        else:
            for item in value.values():
                names.extend(_tool_names(item))
    elif isinstance(value, list):
        for item in value:
            names.extend(_tool_names(item))
    return names


def _assistant_tool_event(event: dict[str, Any]) -> tuple[str, list[str]] | None:
    message = event.get("message")
    if event.get("type") == "assistant" and isinstance(message, dict):
        message_id = message.get("id")
        if isinstance(message_id, str):
            return message_id, _tool_names(message)
    if isinstance(message, dict) and message.get("role") == "assistant":
        message_id = message.get("id")
        if isinstance(message_id, str):
            return message_id, _tool_names(message)
    return None


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
    tool_timeline: list[list[str]] = []
    timeline_by_message: dict[str, list[str]] = {}
    first_tool_message_id: str | None = None
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
            assistant_event = _assistant_tool_event(event)
            if assistant_event is not None:
                message_id, assistant_tools = assistant_event
                if assistant_tools:
                    if message_id not in timeline_by_message:
                        timeline_by_message[message_id] = []
                        tool_timeline.append(timeline_by_message[message_id])
                    timeline_by_message[message_id].extend(assistant_tools)
                    if first_tool_message_id is None:
                        first_tool_message_id = message_id
                        first_tools = timeline_by_message[message_id]
                elif first_tool_message_id is not None and message_id != first_tool_message_id and not complete_turn:
                    process.terminate()
                    break
        selector.close()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    expected = str(probe["expected"])
    initial_host_tool_violations = [name for name in first_tools if name in HOST_TOOLS]
    flattened_timeline = [name for tools in tool_timeline for name in tools]
    expected_index = flattened_timeline.index(expected) if expected in flattened_timeline else None
    host_tool_before_expected = [
        name
        for index, name in enumerate(flattened_timeline)
        if name in HOST_TOOLS and (expected_index is None or index < expected_index)
    ]
    host_tools_after_mcp = [
        name
        for index, name in enumerate(flattened_timeline)
        if name in HOST_TOOLS and expected_index is not None and index > expected_index
    ]
    competing_search = (
        "mcp__aigc-news__search_papers"
        if expected == "mcp__aigc-news__search_github_ai_projects"
        else "mcp__aigc-news__search_github_ai_projects"
        if expected == "mcp__aigc-news__search_papers"
        else ""
    )
    passed = (
        bool(first_tools)
        and first_tools[0] == expected
        and not initial_host_tool_violations
        and (not competing_search or competing_search not in first_tools)
    )
    return TrialResult(
        probe=probe_name,
        trial=trial,
        expected=expected,
        first_tools=first_tools,
        tool_timeline=tool_timeline,
        timeline_complete=complete_turn and not timed_out and process.returncode == 0,
        initial_host_tool_violations=initial_host_tool_violations,
        host_tool_before_expected=host_tool_before_expected,
        host_tools_after_mcp=host_tools_after_mcp,
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
            "complete_timelines": sum(result.timeline_complete for result in probe_results),
            "initial_host_tool_violations": sum(
                bool(result.initial_host_tool_violations) for result in probe_results
            ),
            "host_tool_before_expected": sum(
                bool(result.host_tool_before_expected) for result in probe_results
            ),
            "host_tools_after_mcp": sum(
                bool(result.host_tools_after_mcp) for result in probe_results
            ),
            "first_tool_counts": {
                name: sum(bool(result.first_tools) and result.first_tools[0] == name for result in probe_results)
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
