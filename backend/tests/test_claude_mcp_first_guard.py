from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "mcp-first-guard.py"
SPEC = importlib.util.spec_from_file_location("mcp_first_guard", HOOK)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class ClassifierTests(unittest.TestCase):
    def assert_route(self, prompt: str, route: str) -> None:
        result = GUARD.classify_prompt(prompt)
        self.assertEqual(result["classification"], "required")
        self.assertEqual(result["route"], route)

    def test_routes_explicit_discovery(self) -> None:
        self.assert_route("帮我找几个开源的 Agent MCP SDK 项目", "ai_projects")
        self.assert_route("Find an open source Windows screenshot project", "non_ai_projects")
        self.assert_route("请找几篇 RAG 论文和综述并给出引用", "papers")
        self.assert_route("从 AIGC_NEWS 已索引内容搜索跨来源新闻", "documents")

    def test_mixed_requests_use_dominant_deliverable(self) -> None:
        self.assert_route("以 Agent 示例项目和 SDK 实现为主，也可附论文", "ai_projects")
        self.assert_route("以 Agent 论文、survey 和引用为主，项目只作补充", "papers")

    def test_major_subsystem_triggers_proactive_check(self) -> None:
        self.assert_route("实现一个完整的 RAG 独立子系统", "ai_projects")
        self.assert_route("Build a complete screenshot platform", "non_ai_projects")

    def test_narrow_and_approved_changes_are_exempt(self) -> None:
        self.assertEqual(GUARD.classify_prompt("修复 Agent 页面 CSS 样式")["classification"], "exempt")
        self.assertEqual(GUARD.classify_prompt("按照方案继续实施当前修改")["classification"], "exempt")
        self.assertEqual(GUARD.classify_prompt("Add unit tests for the MCP field validation")["classification"], "exempt")

    def test_explicit_discovery_overrides_local_words(self) -> None:
        self.assert_route("帮我找一个开源项目来修复 Agent 页面 CSS", "ai_projects")

    def test_ambiguous_local_request_does_not_arm_guard(self) -> None:
        self.assertEqual(GUARD.classify_prompt("Improve this function")["classification"], "ambiguous")


class HookSubprocessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.env = os.environ.copy()
        self.env["AIGCNEWS_MCP_GUARD_STATE_DIR"] = self.temporary.name
        self.env["AIGCNEWS_MCP_FIRST_MODE"] = "enforce"
        self.session = "../../unsafe/session"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call(self, event: str, **values: object) -> dict[str, object]:
        payload = {"hook_event_name": event, "session_id": self.session, **values}
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
        return json.loads(completed.stdout)

    @staticmethod
    def decision(response: dict[str, object]) -> str | None:
        output = response.get("hookSpecificOutput")
        return output.get("permissionDecision") if isinstance(output, dict) else None

    def arm_ai(self) -> None:
        response = self.call("UserPromptSubmit", prompt="帮我找几个开源 Agent MCP SDK 项目")
        self.assertIn("additionalContext", response["hookSpecificOutput"])

    def test_pending_blocks_agent_web_and_network_bash_but_allows_local_bash(self) -> None:
        self.arm_ai()
        self.assertEqual(self.decision(self.call("PreToolUse", tool_name="Agent", tool_input={})), "deny")
        self.assertEqual(self.decision(self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agents"})), "deny")
        self.assertEqual(self.decision(self.call("PreToolUse", tool_name="Bash", tool_input={"command": "curl https://github.com"})), "deny")
        self.assertEqual(self.call("PreToolUse", tool_name="Bash", tool_input={"command": "git status --short"}), {})

    def test_wrong_route_is_denied_and_matching_route_enters_flight(self) -> None:
        self.arm_ai()
        wrong = self.call("PreToolUse", tool_name="mcp__aigc-news__search_papers", tool_input={"q": "agent"})
        self.assertEqual(self.decision(wrong), "deny")
        correct = self.call(
            "PreToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_input={"q": "agent sdk"},
        )
        self.assertEqual(self.decision(correct), "allow")
        repeated = self.call(
            "PreToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-2",
            tool_input={"q": "agent sdk"},
        )
        self.assertEqual(self.decision(repeated), "deny")

    def start_mcp(self) -> None:
        self.arm_ai()
        self.call(
            "PreToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_input={"q": "agent sdk"},
        )

    def test_usable_response_blocks_broad_web_but_allows_named_fact(self) -> None:
        self.start_mcp()
        response = self.call(
            "PostToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"structuredContent": {"items": [{"repo_id": "acme/agent"}]}},
        )
        self.assertIn("usable", response["hookSpecificOutput"]["additionalContext"])
        broad = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "best agent SDK projects"})
        self.assertEqual(self.decision(broad), "deny")
        fact = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "acme/agent license"})
        self.assertEqual(fact, {})
        self.assertEqual(self.call("PreToolUse", tool_name="Bash", tool_input={"command": "python -m pytest -q"}), {})

    def test_empty_failure_and_interrupt_transitions(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"structuredContent": {"items": [], "total": 0}},
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"}), {})

        self.session = "failure-session"
        self.start_mcp()
        self.call(
            "PostToolUseFailure",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            error="unavailable",
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebFetch", tool_input={"url": "https://example.com"}), {})

        self.session = "interrupt-session"
        self.start_mcp()
        self.call(
            "PostToolUseFailure",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            is_interrupt=True,
        )
        blocked = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"})
        self.assertEqual(self.decision(blocked), "deny")

    def test_tool_level_error_in_post_event_opens_fallback(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"isError": True, "content": [{"text": "hidden"}]},
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"}), {})

    def test_stale_attempt_is_ignored(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="stale",
            tool_response={"structuredContent": {"items": []}},
        )
        blocked = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"})
        self.assertEqual(self.decision(blocked), "deny")

    def test_new_requirement_resets_authorization_and_referential_followup_reuses_success(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"structuredContent": {"items": [{"repo_id": "a/b"}]}},
        )
        self.call("UserPromptSubmit", prompt="第二个详细说一下")
        duplicate = self.call(
            "PreToolUse",
            tool_name="mcp__aigc-news__search_github_ai_projects",
            tool_input={"q": "again"},
        )
        self.assertEqual(duplicate, {})
        self.call("UserPromptSubmit", prompt="帮我找一个开源 Windows 截图项目")
        blocked = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "screenshot"})
        self.assertEqual(self.decision(blocked), "deny")

    def test_observe_and_off_modes_do_not_deny(self) -> None:
        self.env["AIGCNEWS_MCP_FIRST_MODE"] = "observe"
        self.arm_ai()
        observed = self.call("PreToolUse", tool_name="Agent", tool_input={})
        self.assertIsNone(self.decision(observed))
        self.env["AIGCNEWS_MCP_FIRST_MODE"] = "off"
        self.assertEqual(self.call("PreToolUse", tool_name="WebSearch", tool_input={}), {})

    def test_malformed_input_returns_one_json_object(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not-json",
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {})

    def test_state_paths_are_hashed_and_concurrent_initial_calls_allow_one(self) -> None:
        self.arm_ai()
        requests = [
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session,
                "tool_name": "mcp__aigc-news__search_github_ai_projects",
                "tool_use_id": f"attempt-{index}",
                "tool_input": {"q": "agent sdk"},
            }
            for index in range(4)
        ]

        def invoke(payload: dict[str, object]) -> str | None:
            completed = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=self.env
            )
            return self.decision(json.loads(completed.stdout))

        with ThreadPoolExecutor(max_workers=4) as executor:
            decisions = list(executor.map(invoke, requests))
        self.assertEqual(decisions.count("allow"), 1)
        self.assertEqual(decisions.count("deny"), 3)
        names = [path.name for path in Path(self.temporary.name).iterdir()]
        self.assertTrue(names)
        self.assertFalse(any("unsafe" in name or ".." in name for name in names))


class SettingsTests(unittest.TestCase):
    def test_settings_register_guard_and_preserve_auto_push(self) -> None:
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        hooks = settings["hooks"]
        for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
            commands = [hook["command"] for group in hooks[event] for hook in group["hooks"]]
            self.assertIn(".claude/hooks/mcp-first-guard.py", commands)
            self.assertTrue(all(group_hook.get("timeout", 0) <= 10 for group in hooks[event] for group_hook in group["hooks"] if "mcp-first-guard" in group_hook["command"]))
        bash_commands = [hook["command"] for group in hooks["PostToolUse"] if group["matcher"] == "Bash" for hook in group["hooks"]]
        self.assertIn(".claude/hooks/auto-push-after-commit.sh", bash_commands)
        self.assertTrue(HOOK.exists())


if __name__ == "__main__":
    unittest.main()
