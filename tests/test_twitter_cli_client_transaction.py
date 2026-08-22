"""ClientTransaction 初始化契约（x-client-transaction-id 头）。

2026-08 起未登录 https://x.com 只回 x-web 壳（无 client-web bundle、无
ondemand.s 引用），上游 twitter-cli 0.8.5 的 `_ensure_client_transaction`
恒失败——而 UserTweetsAndReplies 等操作强制要求
X-Client-Transaction-Id，缺失即空体 404。修复以运行时补丁承载于
`aigcnews_private.sources.x_twitter_cli_compat`（pylibs 是 pip --target
构建产物，直接改动不可入库）；本套件验证补丁应用后的客户端行为：
有凭证时优先抓登录态 https://x.com/home（仍带完整 ondemand.s 引用），
失败才退回未登录首页。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from aigcnews_private.sources import x_twitter_cli_compat  # noqa: F401  # 应用补丁
from twitter_cli import client as tw_client

_HOME_HTML = '<html><script src="https://abs.twimg.com/responsive-web/client-web/ondemand.s.abc123.js"></script></html>'
_XWEB_SHELL = '<html><script src="/assets/entry-client-logged-out.js"></script></html>'
_ONDEMAND_URL = "https://abs.twimg.com/responsive-web/client-web/ondemand.s.abc123.js"


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.content = text.encode()
        self.status_code = status_code


class _FakeSession:
    """按 URL 脚本应答的 curl_cffi session 替身，实录请求顺序与请求头。"""

    def __init__(self, routes: dict) -> None:
        self._routes = dict(routes)
        self.requests: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):
        self.requests.append((url, dict(headers or {})))
        route = self._routes.get(url)
        if route is None:
            raise AssertionError("未编排的请求: %s" % url)
        if isinstance(route, Exception):
            raise route
        return route


class ClientTransactionInitContracts(unittest.TestCase):
    def _build_client(self, session: _FakeSession) -> tw_client.TwitterClient:
        with (
            patch.object(tw_client, "_get_cffi_session", return_value=session),
            patch.object(
                tw_client.TwitterClient, "_load_ct_cache", return_value=False
            ),
            patch.object(
                tw_client.TwitterClient, "_save_ct_cache", lambda self, h, o: None
            ),
            patch.object(tw_client, "_update_features_from_html", lambda html: None),
            patch.object(
                tw_client, "get_ondemand_file_url", return_value=_ONDEMAND_URL
            ),
            patch.object(tw_client, "ClientTransaction", lambda **kw: object()),
        ):
            return tw_client.TwitterClient("auth-tok", "ct0-tok")

    def test_prefers_authenticated_home_when_cookie_present(self) -> None:
        session = _FakeSession(
            {
                "https://x.com/home": _FakeResponse(_HOME_HTML),
                _ONDEMAND_URL: _FakeResponse("ondemand-js"),
            }
        )

        client = self._build_client(session)

        self.assertIsNotNone(client._client_transaction)
        urls = [url for url, _ in session.requests]
        self.assertEqual(urls, ["https://x.com/home", _ONDEMAND_URL])
        # /home 请求必须带当前凭证 Cookie + 浏览器导航头（纯 API 头会 401）
        home_headers = session.requests[0][1]
        self.assertIn("auth_token=auth-tok", home_headers.get("Cookie", ""))
        self.assertIn("ct0=ct0-tok", home_headers.get("Cookie", ""))
        self.assertEqual(home_headers.get("Sec-Fetch-Mode"), "navigate")

    def test_falls_back_to_logged_out_home_when_auth_home_is_xweb_shell(self) -> None:
        # 登录态 /home 退化（未含 ondemand.s 引用）→ 退回未登录首页
        session = _FakeSession(
            {
                "https://x.com/home": _FakeResponse(_XWEB_SHELL),
                "https://x.com": _FakeResponse(_HOME_HTML),
                _ONDEMAND_URL: _FakeResponse("ondemand-js"),
            }
        )

        client = self._build_client(session)

        self.assertIsNotNone(client._client_transaction)
        urls = [url for url, _ in session.requests]
        self.assertEqual(urls, ["https://x.com/home", "https://x.com", _ONDEMAND_URL])

    def test_falls_back_to_logged_out_home_when_auth_home_fetch_fails(self) -> None:
        session = _FakeSession(
            {
                "https://x.com/home": RuntimeError("tunnel flapped"),
                "https://x.com": _FakeResponse(_HOME_HTML),
                _ONDEMAND_URL: _FakeResponse("ondemand-js"),
            }
        )

        client = self._build_client(session)

        self.assertIsNotNone(client._client_transaction)
        urls = [url for url, _ in session.requests]
        self.assertEqual(urls, ["https://x.com/home", "https://x.com", _ONDEMAND_URL])


if __name__ == "__main__":
    unittest.main()
