#!/usr/bin/env python3
"""Enforce AIGC_NEWS MCP-first routing for Claude Code discovery requests."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
STATE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MODE = "observe"
VALID_MODES = {"off", "observe", "enforce"}

ROUTE_TO_TOOL = {
    "ai_projects": "mcp__aigc-news__search_github_ai_projects",
    "non_ai_projects": "mcp__aigc-news__search_github_projects",
    "papers": "mcp__aigc-news__search_papers",
    "documents": "mcp__aigc-news__search_documents",
}
PUBLIC_SEARCH_TOOLS = frozenset(ROUTE_TO_TOOL.values())
GUARDED_TOOLS = frozenset({"Agent", "WebSearch", "WebFetch", "Skill"})
WRAPPER_PREFIXES = ("multi_tool_use.", "Task", "Batch")

DISCOVERY = (
    "find", "search", "recommend", "compare", "reuse", "look for", "discover",
    "找", "查找", "搜索", "推荐", "对比", "比较", "复用", "有没有", "资料", "调研", "为主",
)
MAJOR_ACTIONS = (
    "build", "implement", "develop", "design", "add", "create", "from scratch",
    "实现", "开发", "设计", "新增", "搭建", "构建", "从零", "从头",
)
MAJOR_SCOPE = (
    "complete product", "platform", "full system", "subsystem", "architecture", "module",
    "完整产品", "完整平台", "完整系统", "独立子系统", "架构", "重大模块", "完整能力",
)
AI_MARKERS = (
    " ai ", "agent", "mcp", "rag", "llm", "model context protocol", "模型", "智能体", "知识库",
)
ARTIFACTS = (
    "project", "repository", "repo", "open source", "github", "sdk", "framework", "component",
    "template", "example", "tutorial", "server", "client", "workflow", "implementation", "library",
    "项目", "仓库", "开源", "框架", "组件", "模板", "示例", "教程", "服务端", "客户端",
    "工作流", "实现", "资料",
)
SCHOLARLY = (
    "paper", "papers", "literature", "survey", "citation", "author", "venue", "academic benchmark",
    "method theory", "experiment results", "论文", "文献", "综述", "引用", "作者", "期刊", "学术",
    "实验结果", "研究结果", "方法理论",
)
DOCUMENTS = (
    "aigc_news", "aigc news", "indexed news", "indexed content", "cross-source", "news feed",
    "已索引", "跨来源", "跨源", "新闻", "资讯流",
)
LOCAL_EXEMPTIONS = (
    "copy", "css", "style", "label", "rename", "validation", "field", "mapping", "serialize",
    "unit test", "logging", "type hint", "simple crud", "localized bug", "isolated function",
    "isolated component", "isolated endpoint", "文案", "样式", "按钮", "重命名", "校验", "字段",
    "映射", "序列化", "单元测试", "日志", "类型", "局部 bug", "局部修复", "简单 crud", "孤立函数",
    "孤立组件", "单个端点",
)
APPROVED_CONTINUATION = (
    "approved plan", "continue the plan", "implement the plan", "continue current", "按照方案", "按方案",
    "继续实施", "继续实现", "继续当前", "执行计划",
)
REFERENTIAL = (
    "the first", "the second", "that one", "those", "show me", "more detail", "第一个", "第二个",
    "那个", "这些", "展开", "详细说", "继续", "接着",
)
FACT_TERMS = (
    "license", "stars", "platform", "support", "documentation", "security advisory", "release",
    "许可证", "星数", "平台支持", "文档", "安全公告", "版本",
)


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def classify_prompt(prompt: str) -> dict[str, str]:
    text = f" {re.sub(r'\s+', ' ', prompt.strip().lower())} "
    digest = hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()
    explicit_discovery = _contains(text, DISCOVERY) and (
        _contains(text, ARTIFACTS) or _contains(text, SCHOLARLY) or _contains(text, DOCUMENTS)
    )
    proactive_major = _contains(text, MAJOR_ACTIONS) and _contains(text, MAJOR_SCOPE)

    if not explicit_discovery and _contains(text, APPROVED_CONTINUATION):
        return {"classification": "exempt", "route": "none", "reason": "approved_continuation", "digest": digest}
    if not explicit_discovery and _contains(text, LOCAL_EXEMPTIONS):
        return {"classification": "exempt", "route": "none", "reason": "narrow_local_change", "digest": digest}
    if explicit_discovery and _contains(text, DOCUMENTS):
        route = "documents"
    elif explicit_discovery and _contains(text, SCHOLARLY):
        academic_dominant = _contains(text, ("以论文", "papers first", "survey", "综述", "citation", "引用"))
        engineering_dominant = _contains(text, ("以 agent 示例", "projects first", "implementation first", "项目为主", "实现为主"))
        route = "ai_projects" if engineering_dominant and not academic_dominant else "papers"
    elif explicit_discovery:
        route = "ai_projects" if _contains(text, AI_MARKERS) else "non_ai_projects"
    elif proactive_major:
        route = "ai_projects" if _contains(text, AI_MARKERS) else "non_ai_projects"
    else:
        return {"classification": "ambiguous", "route": "none", "reason": "no_high_confidence_discovery", "digest": digest}
    return {"classification": "required", "route": route, "reason": "mcp_first_required", "digest": digest}


def _mode() -> str:
    value = os.environ.get("AIGCNEWS_MCP_FIRST_MODE", DEFAULT_MODE).strip().lower()
    return value if value in VALID_MODES else "observe"


def _session_key(payload: dict[str, Any]) -> str:
    raw = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID") or str(payload.get("session_id") or "unknown")
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:40]


def _state_root() -> Path:
    override = os.environ.get("AIGCNEWS_MCP_GUARD_STATE_DIR")
    if override:
        return Path(override)
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    return runtime / "aigcnews-claude-mcp-guard" / str(os.getuid())


def _safe_root() -> Path:
    root = _state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(PermissionError):
        root.chmod(0o700)
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("unsafe state directory")
    return root


def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if data.get("schema_version") != SCHEMA_VERSION:
        return {}
    if time.time() - float(data.get("updated_at", 0)) > STATE_TTL_SECONDS:
        return {}
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = time.time()
    encoded = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _with_state(payload: dict[str, Any], action: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    root = _safe_root()
    key = _session_key(payload)
    state_path = root / f"{key}.json"
    lock_path = root / f"{key}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _read_state(state_path)
        updated, response = action(state)
        _write_state(state_path, updated)
        return response


def _additional(event: str, message: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def _tool_id(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_use_id") or payload.get("toolUseID") or "")


def _prompt(payload: dict[str, Any]) -> str:
    return str(payload.get("prompt") or payload.get("user_prompt") or "")


def _is_referential(prompt: str) -> bool:
    return _contains(prompt.lower(), REFERENTIAL) and len(prompt.split()) <= 30


def _on_prompt(payload: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = _prompt(payload)
    result = classify_prompt(prompt)
    previous_usable = state.get("phase") == "succeeded_usable"
    if result["classification"] == "ambiguous" and previous_usable and _is_referential(prompt):
        state.update({"generation": int(state.get("generation", 0)) + 1, "phase": "succeeded_usable", "continuation": True})
        return state, _additional("UserPromptSubmit", "This appears to continue the prior MCP-backed requirement; reuse the inspected results instead of repeating broad discovery.")
    generation = int(state.get("generation", 0)) + 1
    phase = result["classification"]
    state = {
        "schema_version": SCHEMA_VERSION,
        "generation": generation,
        "requirement_digest": result["digest"],
        "route": result["route"],
        "expected_tool": ROUTE_TO_TOOL.get(result["route"], ""),
        "phase": phase,
        "attempt_count": 0,
        "attempt_id": "",
        "outcome": "",
        "updated_at": time.time(),
    }
    if phase == "required":
        message = f"MCP-first routing requires {state['expected_tool']} before external discovery or delegation."
    elif phase == "exempt":
        message = "This requirement is exempt from proactive MCP discovery; proceed with the local or already-approved change."
    else:
        message = "No high-confidence discovery route was inferred. Apply MCP-first guidance if the task becomes project, paper, or indexed-feed discovery."
    return state, _additional("UserPromptSubmit", message)


def _network_bash(command: str) -> tuple[bool, bool]:
    command = command.strip()
    if not command:
        return False, False
    try:
        import shlex
        tokens = shlex.split(command)
    except ValueError:
        return False, True
    lowered = [token.lower() for token in tokens]
    if any(re.match(r"https?://", token, re.I) for token in tokens):
        return True, False
    network_bins = {"curl", "wget", "ssh", "scp", "sftp", "ftp"}
    if any(Path(token).name in network_bins for token in lowered):
        return True, False
    for index, token in enumerate(lowered):
        base = Path(token).name
        following = lowered[index + 1] if index + 1 < len(lowered) else ""
        if base == "gh" and following in {"api", "search", "repo", "release"}:
            return True, False
        if base == "git" and following in {"clone", "fetch", "pull", "push", "ls-remote"}:
            return True, False
        if base in {"npm", "pnpm", "yarn", "pip", "pip3", "cargo"} and following in {"install", "add", "update", "search"}:
            return True, False
        if base == "go" and following in {"get", "install"}:
            return True, False
    return False, False


def _guarded_kind(tool: str, tool_input: dict[str, Any]) -> tuple[bool, bool]:
    if tool in GUARDED_TOOLS or tool.startswith(WRAPPER_PREFIXES):
        return True, False
    if tool == "Bash":
        return _network_bash(str(tool_input.get("command") or ""))
    return False, False


def _specific_fact(tool_input: dict[str, Any]) -> bool:
    value = " ".join(str(item) for item in tool_input.values()).lower()
    named_candidate = bool(re.search(r"(?:github\.com/)?[\w.-]+/[\w.-]+", value))
    return named_candidate and _contains(value, FACT_TERMS)


def _on_pre(payload: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    mode = _mode()
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    phase = str(state.get("phase") or "ambiguous")
    expected = str(state.get("expected_tool") or "")

    if mode == "off":
        return state, {}
    if tool == expected and phase == "required":
        state.update({"phase": "mcp_in_flight", "attempt_count": int(state.get("attempt_count", 0)) + 1, "attempt_id": _tool_id(payload), "outcome": ""})
        return state, _decision("allow", f"Starting the required MCP-first route {expected}.") if mode == "enforce" else _additional("PreToolUse", f"Observe: allowing required MCP route {expected}.")
    if tool in PUBLIC_SEARCH_TOOLS and phase in {"required", "mcp_in_flight"}:
        reason = f"This requirement must start with {expected}; {tool} does not satisfy that route."
        return state, _decision("deny", reason) if mode == "enforce" else _additional("PreToolUse", f"Observe: would deny. {reason}")

    guarded, uncertain = _guarded_kind(tool, tool_input)
    if not guarded and not uncertain:
        return state, {}
    if phase in {"required", "mcp_in_flight"}:
        reason = f"Run and await {expected} before {tool or 'this external tool'}."
        if mode == "observe":
            return state, _additional("PreToolUse", f"Observe: would block. {reason}")
        return state, _decision("ask" if uncertain else "deny", reason)
    if phase == "succeeded_usable" and tool in {"WebSearch", "WebFetch"} and not _specific_fact(tool_input):
        reason = "MCP returned usable results; broad native Web discovery may not repeat the original search. Limit fallback to a named candidate and a concrete missing fact."
        return state, _decision("deny", reason) if mode == "enforce" else _additional("PreToolUse", f"Observe: would deny. {reason}")
    return state, {}


def _response_value(payload: dict[str, Any]) -> Any:
    return payload.get("tool_response", payload.get("tool_result"))


def _response_outcome(value: Any) -> str:
    if value is None:
        return "failed"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return "usable" if value.strip() else "empty"
    if isinstance(value, dict):
        if value.get("isError") is True or value.get("error"):
            return "failed"
        structured = value.get("structuredContent", value)
        for key in ("items", "projects", "results", "data"):
            if isinstance(structured, dict) and key in structured:
                candidate = structured[key]
                if isinstance(candidate, list):
                    return "usable" if candidate else "empty"
                if isinstance(candidate, dict):
                    return "usable" if candidate else "empty"
        if isinstance(structured, dict) and structured.get("total") == 0:
            return "empty"
        return "usable" if structured else "empty"
    if isinstance(value, list):
        return "usable" if value else "empty"
    return "usable"


def _matching_attempt(payload: dict[str, Any], state: dict[str, Any]) -> bool:
    if str(payload.get("tool_name") or "") != state.get("expected_tool"):
        return False
    stored = str(state.get("attempt_id") or "")
    incoming = _tool_id(payload)
    return not stored or not incoming or stored == incoming


def _on_post(payload: dict[str, Any], state: dict[str, Any], *, failed_event: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    event = "PostToolUseFailure" if failed_event else "PostToolUse"
    if state.get("phase") != "mcp_in_flight" or not _matching_attempt(payload, state):
        return state, {}
    if failed_event and payload.get("is_interrupt") is True:
        state.update({"phase": "required", "outcome": "interrupted", "attempt_id": ""})
        return state, _additional(event, "The MCP attempt was interrupted. Retry the required MCP route; interruption does not authorize Web fallback.")
    outcome = "failed" if failed_event else _response_outcome(_response_value(payload))
    phase = {"usable": "succeeded_usable", "empty": "succeeded_empty", "failed": "failed"}[outcome]
    state.update({"phase": phase, "outcome": outcome})
    if outcome == "usable":
        message = "MCP returned usable results. Inspect and use them first; native Web access is limited to a named candidate's concrete missing fact."
    else:
        message = f"MCP outcome was {outcome}; a narrow host fallback is now eligible."
    return state, _additional(event, message)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("hook_event_name") or "")

    def action(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if event == "UserPromptSubmit":
            return _on_prompt(payload, state)
        if event == "PreToolUse":
            return _on_pre(payload, state)
        if event == "PostToolUse":
            return _on_post(payload, state, failed_event=False)
        if event == "PostToolUseFailure":
            return _on_post(payload, state, failed_event=True)
        return state, {}

    try:
        return _with_state(payload, action)
    except Exception as exc:
        print(f"mcp-first-guard internal error: {type(exc).__name__}", file=sys.stderr)
        if event == "PreToolUse" and _mode() == "enforce":
            tool = str(payload.get("tool_name") or "")
            tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
            guarded, uncertain = _guarded_kind(tool, tool_input)
            if tool in PUBLIC_SEARCH_TOOLS:
                return _decision("allow", "Guard state is unavailable; allow the AIGC_NEWS MCP route to recover.")
            if guarded or uncertain:
                return _decision("ask", "MCP-first guard state is unavailable; confirm this external tool use.")
        return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except Exception as exc:
        print(f"mcp-first-guard input error: {type(exc).__name__}", file=sys.stderr)
        print("{}")
        return 0
    print(json.dumps(handle(payload), ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
