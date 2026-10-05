from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCPAPP = ROOT / "mcp-go" / "internal" / "mcpapp"
CORPUS = Path(__file__).resolve().parent / "parity" / "corpus"

# Claude Code 只保留服务器说明和每个工具描述的前 2048 个字符（按 JS 字符串长度，
# 即 UTF-16 码元计），这里统一按 2000 留余量。
_BUDGET = 2000

# 说明由 Go 网关持有：项目发现段（hostInstructions）已逐字冻结在语料的
# initialize 用例里；UI 段只在挂了 UI 库时追加，语料覆盖不到，在此逐字冻结。
# 改任何一段都要先用 scripts/eval_mcp_tool_selection.py 前后对比工具选择。
_FROZEN_UI_INSTRUCTIONS = (
    "Frontend UI: before coding new, redesigned, or restyled UI (colors, spacing, typography, states, "
    "themes, shaders, animation), always call search_ui_templates, even if unasked; it overrides project "
    "discovery for visual work. For a new page, redesign, or reusable component, open the best match with "
    "get_ui_template before coding and reuse its source, adapting only integration; for small tweaks, only "
    "if directly reusable. Skip copy-only and behavior-only fixes. Icons: search_ui_icons, then get_ui_icon; "
    "never redraw them."
)


def _go_string_const(path: Path, name: str) -> str:
    match = re.search(rf'\bconst {name} = "((?:[^"\\]|\\.)*)"', path.read_text(encoding="utf-8"))
    assert match, f"{name} not found in {path}"
    return json.loads(f'"{match.group(1)}"')


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _corpus_cases(file_name: str) -> dict[str, dict]:
    cases: dict[str, dict] = {}
    # 不能用 splitlines()：语料里的原文可能含 U+2028 等它也会断开的字符。
    for raw in (CORPUS / file_name).read_text(encoding="utf-8").split("\n"):
        if raw.strip():
            case = json.loads(raw)
            cases[case["name"]] = case
    return cases


def _result(case: dict) -> dict:
    return json.loads(case["response"]["body"])["result"]


class ServerInstructionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = _go_string_const(MCPAPP / "catalog.go", "hostInstructions")
        cls.ui = _go_string_const(MCPAPP / "ui_template_tools.go", "uiHostInstructions")
        cls.protocol = _corpus_cases("protocol.jsonl")

    def test_corpus_initialize_freezes_the_go_host_instructions(self) -> None:
        for name in ("initialize", "initialize-without-params"):
            with self.subTest(case=name):
                self.assertEqual(_result(self.protocol[name])["instructions"], self.host)

    def test_ui_instructions_match_frozen_literal(self) -> None:
        self.assertEqual(self.ui, _FROZEN_UI_INSTRUCTIONS)

    def test_project_discovery_comes_first_within_budget(self) -> None:
        source = (MCPAPP / "ui_template_tools.go").read_text(encoding="utf-8")
        self.assertIn('return hostInstructions + " " + uiHostInstructions', source)
        self.assertTrue(self.host.startswith("Project discovery: "))
        self.assertLessEqual(_utf16_len(f"{self.host} {self.ui}"), _BUDGET)

    def test_tool_descriptions_fit_budget(self) -> None:
        tools = _result(self.protocol["tools-list-authenticated"])["tools"]
        self.assertEqual(len(tools), 9)
        for tool in tools:
            with self.subTest(tool=tool["name"]):
                self.assertLessEqual(_utf16_len(tool["description"]), _BUDGET)

    def test_corpus_content_length_matches_body_bytes(self) -> None:
        for path in sorted(CORPUS.glob("*.jsonl")):
            for name, case in _corpus_cases(path.name).items():
                length = case["response"].get("headers", {}).get("content-length")
                if length is None:
                    continue
                with self.subTest(corpus=path.name, case=name):
                    self.assertEqual(int(length), len(case["response"]["body"].encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
