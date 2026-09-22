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

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "mcp-first-guard.py"
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

    def test_technical_selection_triggers_proactive_check(self) -> None:
        self.assert_route("PDF 解析技术怎么选？", "non_ai_projects")
        self.assert_route("数据库还有什么要推荐的吗？", "non_ai_projects")
        self.assert_route("RAG 文档导入用什么框架比较合适？", "ai_projects")
        self.assert_route("你推荐什么 Agent 框架来做知识库？", "ai_projects")

    def test_ai_messaging_integration_advice_routes_to_ai_projects(self) -> None:
        prompts = (
            "我想把AI接入一个QQ账号用来回群友消息，有什么好办法吗",
            "把ai接入微信群聊应该怎么做？",
            "如何集成 LLM 到 Discord 消息机器人？",
            "What approach should I use to connect AI to a Slack bot?",
            "有没有把智能体对接 Telegram 私聊的方案？",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assert_route(prompt, "ai_projects")

    def test_cjk_adjacent_ai_is_detected_for_explicit_discovery(self) -> None:
        self.assert_route("推荐一个把AI接入QQ的开源框架", "ai_projects")

    def test_integration_words_do_not_over_trigger_unrelated_requests(self) -> None:
        for prompt in (
            "QQ账号登录失败怎么办",
            "把 API 接入 QQ 的字段怎么映射",
            "解释一下这个 AI 字段",
            "修复 AI 群聊机器人 CSS 样式",
        ):
            with self.subTest(prompt=prompt):
                self.assertNotEqual(GUARD.classify_prompt(prompt)["classification"], "required")

    def test_feed_queries_route_to_their_dedicated_tools(self) -> None:
        self.assert_route("今天 GitHub 日榜前五名是哪些 AI 项目？", "ranking")
        self.assert_route("最近有什么关于 OpenAI 的 AI 行业新闻？", "documents")
        self.assert_route("这个项目库里都有哪些 AI 项目分类？给我列一下", "categories")
        self.assert_route("我收藏的项目里有没有和 MCP 相关的？帮我找找", "favorites")

    def test_feed_words_do_not_arm_local_changes(self) -> None:
        for prompt in (
            "实现一个新闻榜单页面",
            "新闻页面 CSS 改一下",
            "哪些字段需要校验",
            "项目分类字段如何映射",
            "收藏按钮显示异常",
        ):
            self.assertNotEqual(GUARD.classify_prompt(prompt)["classification"], "required")

    def test_everyday_build_tasks_trigger_proactive_check(self) -> None:
        # "碰见合适任务就先搜" 的日常形态：小工具/脚本/爬虫/插件/服务都算
        # 成规模构建，不能只有"完整系统/子系统"才触发
        self.assert_route("帮我写个网页截图工具", "non_ai_projects")
        self.assert_route("写一个定时备份脚本，把 postgres 数据库每天备份到对象存储", "non_ai_projects")
        self.assert_route("给我做个微信公众号文章爬虫", "non_ai_projects")
        self.assert_route("实现一个本地文件同步模块", "non_ai_projects")
        self.assert_route("帮我搭建一个 RSS 订阅聚合服务", "non_ai_projects")
        self.assert_route("开发一个 VS Code 插件，选中代码一键生成流程图", "non_ai_projects")
        self.assert_route("写个命令行 JSON 转 CSV 的小工具", "non_ai_projects")
        self.assert_route("帮我做个 TG bot 每天推送 HN 热榜", "non_ai_projects")
        self.assert_route("帮我写一个 RAG 检索增强脚本", "ai_projects")

    def test_scope_substring_traps_stay_ambiguous(self) -> None:
        # description 含 script、async 含 sync、client 含 cli：子串误伤回归
        self.assertEqual(
            GUARD.classify_prompt("create a description for the release")["classification"], "ambiguous"
        )
        self.assertEqual(
            GUARD.classify_prompt("implement an async client for the queue")["classification"], "ambiguous"
        )

    def test_action_without_scale_stays_ambiguous(self) -> None:
        # 孤立函数/文档类小动作不算成规模构建
        self.assertEqual(GUARD.classify_prompt("手写一个 LRU 缓存")["classification"], "ambiguous")
        self.assertEqual(GUARD.classify_prompt("帮我写一下项目 README")["classification"], "ambiguous")

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
        self.assertEqual(
            self.decision(self.call("PreToolUse", tool_name="web__run", tool_input={"search_query": [{"q": "agents"}]})),
            "deny",
        )
        self.assertEqual(self.decision(self.call("PreToolUse", tool_name="Bash", tool_input={"command": "curl https://github.com"})), "deny")
        self.assertEqual(self.call("PreToolUse", tool_name="Bash", tool_input={"command": "git status --short"}), {})

    def test_wrong_route_is_denied_and_matching_route_enters_flight(self) -> None:
        self.arm_ai()
        wrong = self.call("PreToolUse", tool_name="mcp__aigc_news__search_papers", tool_input={"q": "agent"})
        self.assertEqual(self.decision(wrong), "deny")
        correct = self.call(
            "PreToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_input={"q": "agent sdk"},
        )
        self.assertEqual(self.decision(correct), "allow")
        repeated = self.call(
            "PreToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-2",
            tool_input={"q": "agent sdk"},
        )
        self.assertEqual(self.decision(repeated), "deny")

    def start_mcp(self) -> None:
        self.arm_ai()
        self.call(
            "PreToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_input={"q": "agent sdk"},
        )

    def test_usable_response_blocks_broad_web_but_allows_named_fact(self) -> None:
        self.start_mcp()
        response = self.call(
            "PostToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
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
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"structuredContent": {"items": [], "total": 0}},
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"}), {})

        self.session = "failure-session"
        self.start_mcp()
        self.call(
            "PostToolUseFailure",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            error="unavailable",
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebFetch", tool_input={"url": "https://example.com"}), {})

        self.session = "interrupt-session"
        self.start_mcp()
        self.call(
            "PostToolUseFailure",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            is_interrupt=True,
        )
        blocked = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"})
        self.assertEqual(self.decision(blocked), "deny")

    def test_tool_level_error_in_post_event_opens_fallback(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"isError": True, "content": [{"text": "hidden"}]},
        )
        self.assertEqual(self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"}), {})

    def test_stale_attempt_is_ignored(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="stale",
            tool_response={"structuredContent": {"items": []}},
        )
        blocked = self.call("PreToolUse", tool_name="WebSearch", tool_input={"query": "agent sdk"})
        self.assertEqual(self.decision(blocked), "deny")

    def test_new_requirement_resets_authorization_and_referential_followup_reuses_success(self) -> None:
        self.start_mcp()
        self.call(
            "PostToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
            tool_use_id="attempt-1",
            tool_response={"structuredContent": {"items": [{"repo_id": "a/b"}]}},
        )
        self.call("UserPromptSubmit", prompt="第二个详细说一下")
        duplicate = self.call(
            "PreToolUse",
            tool_name="mcp__aigc_news__search_github_ai_projects",
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
                "tool_name": "mcp__aigc_news__search_github_ai_projects",
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
    def test_settings_register_guard_for_every_state_transition(self) -> None:
        settings = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        hooks = settings["hooks"]
        for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
            commands = [hook["command"] for group in hooks[event] for hook in group["hooks"]]
            self.assertIn('"$(git rev-parse --show-toplevel)/.codex/hooks/mcp-first-guard.py"', commands)
            self.assertTrue(all(group_hook.get("timeout", 0) <= 10 for group in hooks[event] for group_hook in group["hooks"] if "mcp-first-guard" in group_hook["command"]))
        self.assertTrue(HOOK.exists())

    def test_settings_cover_every_mcp_first_route(self) -> None:
        settings = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        hooks = settings["hooks"]
        expected_tools = set(GUARD.ROUTE_TO_TOOL.values())
        for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            matchers = " ".join(group.get("matcher", "") for group in hooks[event])
            for tool in expected_tools:
                with self.subTest(event=event, tool=tool):
                    self.assertIn(tool, matchers)


if __name__ == "__main__":
    unittest.main()
