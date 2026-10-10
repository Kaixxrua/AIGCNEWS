"""一次性安装码与 get_my_quota 的跨语言契约。

安装码由 Python 签发与兑换，提示词由前端拼（兑换地址、占位符、有效期文案），Agent 照着跑的命令依赖
Token 的字符集；get_my_quota 在 mcp-go 里注册、免计配额，提示词让 Agent 用它确认接通。各方都写死了
同一组字面量，这里双向钉住，任何一侧改名、改路径或改有效期都会在 CI 里失败。
"""

from __future__ import annotations

import re
import typing
import unittest
from pathlib import Path

from fastapi.routing import APIRoute

from backend.app.api import routes_auth
from backend.app.monitoring.mcp_tools import MCP_TOOL_NAMES
from backend.app.services.auth import mcp_install_codes

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _REPO_ROOT / "frontend" / "src"
_MCPAPP = _REPO_ROOT / "mcp-go" / "internal" / "mcpapp"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _route_path(endpoint: object) -> str:
    for route in routes_auth.router.routes:
        if isinstance(route, APIRoute) and route.endpoint is endpoint:
            return route.path
    raise AssertionError(f"route for {endpoint!r} not registered")


def _ts_string_constant(source: str, name: str) -> str:
    match = re.search(rf"export const {name} = '([^']*)'", source)
    if match is None:
        raise AssertionError(f"{name} not found")
    return match.group(1)


class InstallCodeEndpointContractTests(unittest.TestCase):
    def test_auth_routes_are_mounted_under_api(self) -> None:
        main = _read(_REPO_ROOT / "backend" / "app" / "main.py")
        self.assertIn('app.include_router(routes_auth.router, prefix="/api", tags=["Auth"])', main)
        api_client = _read(_FRONTEND / "services" / "http" / "apiClient.ts")
        self.assertIn("baseURL: '/api',", api_client)

    def test_frontend_issues_codes_on_the_backend_route(self) -> None:
        self.assertEqual(_route_path(routes_auth.issue_mcp_install_code), "/auth/me/mcp-install-codes")
        token_api = _read(_FRONTEND / "services" / "mcp" / "mcpTokenApi.ts")
        self.assertIn("api.post<McpInstallCode>('/auth/me/mcp-install-codes', { purpose })", token_api)

    def test_prompts_redeem_on_the_backend_route(self) -> None:
        install_code = _read(_FRONTEND / "features" / "mcp" / "installCode.ts")
        self.assertEqual(
            _ts_string_constant(install_code, "MCP_INSTALL_CODE_REDEEM_PATH"),
            "/api" + _route_path(routes_auth.redeem_mcp_install_code),
        )
        self.assertEqual(_route_path(routes_auth.redeem_mcp_install_code), "/auth/mcp-install-codes/redeem")

    def test_purposes_match(self) -> None:
        self.assertEqual(typing.get_args(mcp_install_codes.InstallCodePurpose), ("mcp", "dsh"))
        token_api = _read(_FRONTEND / "services" / "mcp" / "mcpTokenApi.ts")
        self.assertIn("export type McpInstallCodePurpose = 'mcp' | 'dsh'", token_api)


class InstallCodeLifetimeContractTests(unittest.TestCase):
    def test_prompts_promise_the_backend_lifetime(self) -> None:
        self.assertEqual(mcp_install_codes.INSTALL_CODE_TTL_SECONDS, 600)
        prompt = _read(_FRONTEND / "features" / "mcp" / "agentSetupPrompt.ts")
        self.assertIn("10 分钟内有效，只能兑换一次", prompt)
        self.assertIn("valid for 10 minutes, redeemable once", prompt)
        self.assertIn("安装码 10 分钟内有效、只能兑换一次", prompt)
        self.assertIn("The code is valid for 10 minutes and can be redeemed once", prompt)
        locales = _read(_FRONTEND / "i18n" / "locales" / "agentSetup.ts")
        self.assertIn("一次性安装码（10 分钟内有效）", locales)
        self.assertIn("安装码 10 分钟内有效、只能用一次", locales)
        self.assertIn("valid for 10 minutes", locales)

    def test_page_leaves_the_agent_time_to_redeem(self) -> None:
        composable = _read(_FRONTEND / "composables" / "useMcpInstallCode.ts")
        match = re.search(r"export const INSTALL_CODE_MIN_REMAINING_MS = (\d+) \* 60_000", composable)
        self.assertIsNotNone(match)
        assert match is not None
        min_remaining_seconds = int(match.group(1)) * 60
        # 只在前一半有效期里写进提示词：复制出去的码至少还有一半时间给 Agent 兑换。
        self.assertEqual(min_remaining_seconds * 2, mcp_install_codes.INSTALL_CODE_TTL_SECONDS)


class InstallCodeCommandContractTests(unittest.TestCase):
    """提示词里的兑换命令依赖 Token 只含 urlsafe 字符：perl 替换、Node 脚本、Shell 双引号都不用转义。"""

    def test_placeholder_needs_no_escaping(self) -> None:
        install_code = _read(_FRONTEND / "features" / "mcp" / "installCode.ts")
        placeholder = _ts_string_constant(install_code, "MCP_TOKEN_PLACEHOLDER")
        self.assertEqual(placeholder, "__AIGC_RADAR_TOKEN__")
        self.assertRegex(placeholder, r"^[A-Z_]+$")

    def test_redeemed_tokens_are_urlsafe_with_the_checked_prefix(self) -> None:
        routes = _read(_REPO_ROOT / "backend" / "app" / "api" / "routes_auth.py")
        redeem = routes[routes.index("async def redeem_mcp_install_code(") :]
        redeem = redeem[: redeem.index("\n# ----")]
        self.assertIn('token = "aigc_mcp_" + secrets.token_urlsafe(32)', redeem)
        self.assertIn("_ensure_dsh_mcp_token_item(dsh_tokens, payload.user_id)", redeem)
        # dsh 专用 Token 也由同一前缀加 urlsafe 随机串生成。
        self.assertEqual(routes.count('token = "aigc_mcp_" + secrets.token_urlsafe(32)'), 3)
        prompt = _read(_FRONTEND / "features" / "mcp" / "agentSetupPrompt.ts")
        self.assertIn("t.indexOf('aigc_mcp_')<0", prompt)

    def test_commands_ask_for_the_raw_token(self) -> None:
        prompt = _read(_FRONTEND / "features" / "mcp" / "agentSetupPrompt.ts")
        self.assertIn("-H 'Accept: text/plain'", prompt)
        self.assertIn("accept:'text/plain'", prompt)
        self.assertIn(
            '"text/plain" in accept and "application/json" not in accept',
            _read(_REPO_ROOT / "backend" / "app" / "api" / "routes_auth.py"),
        )


class QuotaToolContractTests(unittest.TestCase):
    def test_tool_is_registered_counted_and_quota_free_under_one_name(self) -> None:
        quota = _read(_MCPAPP / "quota.go")
        main = _read(_REPO_ROOT / "mcp-go" / "cmd" / "mcp-server" / "main.go")
        dispatch = _read(_MCPAPP / "dispatch.go")
        self.assertIn('const QuotaToolName = "get_my_quota"', quota)
        self.assertIn(
            "app.RegisterIdentityTool(mcpapp.QuotaToolName, mcpapp.NewQuotaService(limiter, publicBaseURL).Get)",
            main,
        )
        self.assertIn("knownToolNames[mcpapp.QuotaToolName] = struct{}{}", main)
        self.assertIn("if h.app.quotaFreeCall(req) {", dispatch)
        self.assertIn("enforce = h.limiter.EnforceBurst", dispatch)
        self.assertEqual(MCP_TOOL_NAMES[-1], "get_my_quota")

    def test_prompts_confirm_the_connection_with_the_tool(self) -> None:
        prompt = _read(_FRONTEND / "features" / "mcp" / "agentSetupPrompt.ts")
        self.assertIn("const QUOTA_TOOL = 'get_my_quota'", prompt)
        self.assertEqual(prompt.count("${QUOTA_TOOL}"), 4)


if __name__ == "__main__":
    unittest.main()
