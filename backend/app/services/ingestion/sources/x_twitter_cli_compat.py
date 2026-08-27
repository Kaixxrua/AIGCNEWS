"""twitter-cli 上游兼容补丁（2026-08-22 起）。

`twitter-cli==0.8.5` 是由 ``backend/requirements.lock`` 精确锁定的公开
PyPI 运行依赖。本模块集中承载项目对其内部 API 的兼容补丁，并在
`x_transport` 导入时对加载进进程的 twitter_cli 0.8.5 原地应用；不要
直接修改第三方包安装目录。

补丁内容：

1. ``FALLBACK_QUERY_IDS`` 补 ``UserTweetsAndReplies`` 钉住项——
   ``_graphql_get`` 的 stale-retry（404/422 失效重解析）依赖此表判定
   using_fallback。值取自 2026-08-22 当前 bundle（main.7792f4fa.js）
   并实测 200。窗口抓取已于 2026-08-24 全局回退 UserTweets（见
   x_transport._WINDOW_TIMELINE_OPERATION 注释），该操作当前不被
   调用，钉住项作为回滚保险保留。
2. ``TwitterClient._ensure_client_transaction`` 修复 x-client-transaction-id
   初始化：上游只抓未登录 https://x.com，而 2026-08 起该页面只回
   x-web 壳（无 ondemand.s 引用）→ 初始化恒失败（日志特征：
   ``Failed to init ClientTransaction: 'NoneType' object has no attribute
   'group'``）。UserTweetsAndReplies 强制要求 X-Client-Transaction-Id，
   缺失时空体 404（2026-08-24 生产实测全账号中招）。修复：有凭证时
   优先抓登录态 https://x.com/home（纯浏览器导航头 + Cookie；API 头
   会 401），失败再退回上游路径。该补丁同样作为回滚保险保留。

上游升级后若内部结构漂移，``apply()`` 的断言在导入期响亮失败，
绝不静默退回旧行为。
"""
from __future__ import annotations

import logging

from twitter_cli import client as _tw_client, graphql as _tw_graphql

logger = logging.getLogger(__name__)

# 2026-08-22 从当前 bundle（main.7792f4fa.js）提取并实测 200。
# 注意：该操作的 404 空体多半不是 queryId 过期，而是缺
# X-Client-Transaction-Id（见本模块补丁 2）。
_USER_TWEETS_AND_REPLIES_QUERY_ID = "qUpkZU6eN8MbtQb7rC_pYg"


def _fetch_ct_home_text(self):
    # type: (object) -> str
    """抓取带 ondemand.s 引用的 x.com 页面 HTML（登录态 /home 优先）。

    未登录 https://x.com 自 2026-08 起只回 x-web 壳，无 ondemand.s
    链接；登录态 https://x.com/home 仍带完整引用。凭证缺失或 /home
    不可用时退回上游的未登录首页路径。
    """
    cookie = self._cookie_string or "auth_token=%s; ct0=%s" % (
        self._auth_token,
        self._ct0,
    )
    if cookie.strip(" =;"):
        try:
            resp = _tw_client._get_cffi_session().get(
                "https://x.com/home",
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                    "User-Agent": _tw_client.get_user_agent(),
                    "Cookie": cookie,
                },
                timeout=15,
            )
            if resp.status_code == 200 and "ondemand.s" in resp.text:
                return resp.text
            _tw_client.logger.debug(
                "authenticated /home unusable for ClientTransaction (HTTP %s)",
                resp.status_code,
            )
        except Exception as exc:
            _tw_client.logger.debug("authenticated /home fetch failed: %s", exc)
    resp = _tw_client._get_cffi_session().get(
        "https://x.com", headers=_tw_client._gen_ct_headers(), timeout=10,
    )
    return resp.text


def _ensure_client_transaction(self):
    # type: (object) -> None
    """上游同名方法的修复版：ondemand 来源改由 _fetch_ct_home_text 供给。

    语义与上游一致：1h 缓存优先；成功后提取页面 feature flags 并写缓存；
    全程失败仅记 warning（_client_transaction 留 None，下游按需退化）。
    """
    if self._ct_init_attempted:
        return
    self._ct_init_attempted = True

    if self._load_ct_cache():
        return

    try:
        home_text = self._fetch_ct_home_text()
        home_page_response = _tw_client.bs4.BeautifulSoup(home_text, "html.parser")
        ondemand_url = _tw_client.get_ondemand_file_url(response=home_page_response)
        ondemand_file = _tw_client._get_cffi_session().get(
            ondemand_url, headers=_tw_client._gen_ct_headers(), timeout=10,
        )
        self._client_transaction = _tw_client.ClientTransaction(
            home_page_response=home_page_response,
            ondemand_file_response=ondemand_file.text,
        )
        _tw_client.logger.info(
            "ClientTransaction initialized for x-client-transaction-id"
        )
        _tw_client._update_features_from_html(home_text)
        self._save_ct_cache(home_text, ondemand_file.text)
    except Exception as exc:
        _tw_client.logger.warning("Failed to init ClientTransaction: %s", exc)


def apply() -> None:
    """对加载中的 twitter_cli 应用全部补丁；上游漂移时断言响亮失败。"""
    for name in (
        "_get_cffi_session",
        "_gen_ct_headers",
        "get_ondemand_file_url",
        "ClientTransaction",
        "_update_features_from_html",
        "get_user_agent",
        "bs4",
    ):
        assert hasattr(_tw_client, name), (
            "twitter-cli 上游漂移：twitter_cli.client 缺 %s，"
            "x_twitter_cli_compat 补丁需跟随上游调整" % name
        )
    for name in ("_ensure_client_transaction", "_load_ct_cache", "_save_ct_cache"):
        assert hasattr(_tw_client.TwitterClient, name), (
            "twitter-cli 上游漂移：TwitterClient 缺 %s，"
            "x_twitter_cli_compat 补丁需跟随上游调整" % name
        )

    _tw_graphql.FALLBACK_QUERY_IDS.setdefault(
        "UserTweetsAndReplies", _USER_TWEETS_AND_REPLIES_QUERY_ID
    )
    _tw_client.TwitterClient._fetch_ct_home_text = _fetch_ct_home_text
    _tw_client.TwitterClient._ensure_client_transaction = _ensure_client_transaction


apply()
