from __future__ import annotations

"""X/Twitter 传输层：包装 twitter-cli 同步客户端的异步门面。

设计要点：
  - twitter-cli（curl_cffi + time.sleep）是同步库，所有调用经
    asyncio.to_thread 转入线程池，不阻塞事件循环
  - 账号顺序处理 + 账号间抖动延迟：凭据为主账号 cookie，
    温和节奏优先于吞吐（不并发 gather）
  - screen_name → user_id 模块级 24h 缓存：请求量减半
  - 异常分级：认证失效/限流 → 中止当前凭据（不拿死凭据锤其余账号）；
    单账号 NotFound/其他异常 → 记录并跳过
  - 支持注入 credential_provider：按启用顺序构造独立 TwitterClient，
    认证失败或 429 时丢弃 partial result，并从完整 watchlist 用下一凭据重试；
    每个 watchlist 账号仍严格串行处理

凭据来源优先级：
  1. 注入的 ``credential_provider``（生产数据库事实源）
  2. 显式的 ``client_factory``（测试/旧调用兼容，读取 env）
"""

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from twitter_cli.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    TwitterAPIError,
)

# 上游 twitter-cli 本地补丁（FALLBACK queryId 钉住 + ClientTransaction
# 初始化修复），必须在任何 TwitterClient 构造/_graphql_get 调用前应用。
from aigcnews_private.sources import x_twitter_cli_compat as _x_twitter_cli_compat  # noqa: F401

from backend.app.services.source_plugins.x_source import (
    DEFAULT_INTER_ACCOUNT_DELAY,
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportUnavailable,
    XWindowFetchResult,
    XWindowHandleResult,
)

logger = logging.getLogger(__name__)

USER_ID_CACHE_TTL_SECONDS = 24 * 3600

# 单账号网络抖动重试：curl 层链路故障（代理拒连 7、DNS 5/6、超时 28、
# TLS 35、空应答 52、收发截断 55/56）按 15s/30s 退避各重试一次，
# 覆盖出口代理 ~1 分钟量级的抖动窗口（2026-08-14 实测 zai_org 超时、
# minimax_ai 代理拒连各丢一轮）。重试预算按轮封顶：代理硬故障时
# 前几个账号烧完预算，其余 fail-fast，整轮仍能及时升级为
# XTransportUnavailable，不会把故障轮拖长数倍。
_NETWORK_RETRY_DELAYS = (15.0, 30.0)
_NETWORK_RETRY_BUDGET_PER_ROUND = 6
_TRANSIENT_CURL_ERRNOS = frozenset({5, 6, 7, 28, 35, 52, 55, 56})

# ── rolling-window cursor 分页 ─────────────────────────────────────────
# twitter-cli 公开 timeline API 是 count 驱动的固定深度抓取（0.8.5 内部
# 分页但不暴露 cursor）。rolling 24h 完整性必须沿 Bottom cursor 翻到
# 「最早时间线外层条目 ≤ window_start」或「明确 timeline 耗尽」为止。
# 这里的常量只约束单页大小与页数安全预算，不再限制窗口总条数。
#
# 单页条数与 twitter-cli 内部一致（_fetch_timeline 的 min(remaining+5, 40)）。
_WINDOW_PAGE_SIZE = 40
# 高产账号兜底：40 条/页 × 50 页 = 2000 条/账号的硬上限；预算耗尽且
# 仍未证明窗口边界 → 该 handle 记 page_limit_reached incomplete，
# 绝不把 partial 当完整窗口入库。
_WINDOW_MAX_PAGES_PER_HANDLE = 50
# 窗口抓取操作：2026-08-22 起从 UserTweets 切到 UserTweetsAndReplies，
# 把「对他人的回复」纳入 rolling 窗口（此前结构性不采，见 2026-08-22
# 实证：UserTweets 只含原创/转贴/引用/自回复线程）。该操作强制要求
# X-Client-Transaction-Id 头（twitter_cli ClientTransaction 注入，
# 缺失时空体 404）。
_WINDOW_TIMELINE_OPERATION = "UserTweetsAndReplies"
# 不采回复贴的账号（screen_name 小写）：2026-08-22 用户决策——grok 的
# AndReplies 时间线被海量「@grok …」提问回复刷爆，页预算会被会话模块
# 耗尽（page_limit_reached 恒 fail-closed），且回复内容对站点无收录
# 价值；该账号退回 UserTweets（只含原创/转贴/引用/自回复线程）。
_REPLIES_EXCLUDED_HANDLES = frozenset({"grok"})
# 与网页端 fetchUserTweetsAndReplies 严格对齐的 variables 形状
# （2026-08-22 实测 200）。多余的 UserTweets 时代变量
# （withV2Timeline/latestControlAvailable/requestContext）不发送：
# withV2Timeline 被服务端忽略（响应固定 v1 结构），其余两个未在网页端
# 形状中出现，X 对未知变量历史上有过 404 先例，不冒这个险。
_WINDOW_BASE_VARIABLES = {
    "includePromotedContent": False,
}
_TWEET_CREATED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"


def _parse_tweet_timestamp(value: Any) -> datetime | None:
    """解析 X legacy.created_at（'Tue Aug 04 02:10:51 +0000 2026'）为 UTC。

    非法/缺失一律返回 None（调用方据此判 parser_drift，绝不伪造时间）。
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _TWEET_CREATED_AT_FORMAT).astimezone(
            timezone.utc
        )
    except (TypeError, ValueError):
        return None


def _is_transient_network_error(exc: BaseException) -> bool:
    """curl 层链路故障判定，区别于 X API 业务响应错误（不重试）。

    不 import curl_cffi 具体异常类：pylibs 供给路径在容器与测试环境间
    有差异；curl_cffi 的 RequestException 同时是 OSError 且带 curl
    errno（IntEnum，可与 int 直接比较），用公共特征判定即可。无 errno
    的内建 TimeoutError/ConnectionError 同属链路故障。
    """
    code = getattr(exc, "code", None)
    if code is not None:
        return code in _TRANSIENT_CURL_ERRNOS
    return isinstance(exc, (TimeoutError, ConnectionError))

# screen_name(lower) -> (user_id, 过期时间戳)
_USER_ID_CACHE: dict[str, tuple[str, float]] = {}

_MEDIA_VIDEO_TYPES = frozenset({"video", "animated_gif"})
_MEDIA_KNOWN_TYPES = _MEDIA_VIDEO_TYPES | {"photo"}

# 非 None 表示封面补丁已安装，值为被包装的原始函数（测试恢复用）
_ORIGINAL_EXTRACT_MEDIA: Any = None

# 非 None 表示链接卡片补丁已安装，值为被包装的原始函数（测试恢复用）
_ORIGINAL_PARSE_TWEET_RESULT: Any = None

# 卡片缩略图 key 优先级：*original 是全尺寸原图，逐档回退到小图。
# binding_values 的 image_value 形如 {"url": "...", "width": w, "height": h}。
_CARD_IMAGE_KEYS = (
    "player_image_original",
    "photo_image_full_size_original",
    "thumbnail_image_original",
    "player_image_x_large",
    "player_image_large",
    "photo_image_full_size_large",
    "thumbnail_image_large",
    "player_image",
    "photo_image_full_size",
    "thumbnail_image",
)


def _install_media_poster_patch() -> None:
    """给 twitter-cli 的 _extract_media 打补丁：视频/GIF 回填官方封面 URL。

    twitter-cli 0.8.5 的 TweetMedia 只有 url（视频取最高码率 mp4 直链），
    丢弃了 legacy.extended_entities.media[].media_url_https —— 即 X 官方
    封面图。前端点击播放占位优先用官方封面；本补丁让新采集数据直接落库，
    存量数据仍由服务端抽帧端点 /api/media/x/poster 兜底。

    补丁策略：包装原函数（调用点在 parser.py 内部，模块级查找可拦截），
    按序配对原始 media 列表回填 poster_url（TweetMedia 无 slots，可后置
    赋值，与测试模拟 is_promoted 同一先例）。原函数对每个已知类型恰好
    产出一条且保序；长度不一致（上游未来改版）时放弃回填，行为等同无
    补丁。安装失败仅记 warning，绝不阻断采集。
    """
    global _ORIGINAL_EXTRACT_MEDIA
    if _ORIGINAL_EXTRACT_MEDIA is not None:
        return
    try:
        from twitter_cli import parser as tw_parser

        original_extract = tw_parser._extract_media

        def extract_media_with_poster(legacy: Any) -> list[Any]:
            items = original_extract(legacy)
            raw_items = [
                m
                for m in (tw_parser._deep_get(legacy, "extended_entities", "media") or [])
                if m.get("type") in _MEDIA_KNOWN_TYPES
            ]
            if len(raw_items) != len(items):
                return items
            for item, raw in zip(items, raw_items):
                if item.type in _MEDIA_VIDEO_TYPES:
                    poster = str(raw.get("media_url_https") or "")
                    if poster:
                        item.poster_url = poster
            return items

        tw_parser._extract_media = extract_media_with_poster
        _ORIGINAL_EXTRACT_MEDIA = original_extract
    except Exception:
        logger.warning("[XTransport] media poster patch 安装失败", exc_info=True)


def _resolve_card_tweet_data(result: Any) -> Any:
    """复刻 parser 的 retweet/visibility 解包：卡片与媒体/urls 同一数据源。

    转推的卡片挂在被转推文上（parse_tweet_result 的 actual_data 语义）；
    TweetWithVisibilityResults 的 card 在内层 tweet 上。
    """
    if not isinstance(result, dict):
        return None
    tweet_data = result
    if result.get("__typename") == "TweetWithVisibilityResults" and isinstance(
        result.get("tweet"), dict
    ):
        tweet_data = result["tweet"]
    legacy = tweet_data.get("legacy")
    if not isinstance(legacy, dict):
        return tweet_data
    retweet_result = (legacy.get("retweeted_status_result") or {}).get("result")
    if isinstance(retweet_result, dict):
        if retweet_result.get(
            "__typename"
        ) == "TweetWithVisibilityResults" and isinstance(retweet_result.get("tweet"), dict):
            retweet_result = retweet_result["tweet"]
        if isinstance(retweet_result.get("legacy"), dict):
            return retweet_result
    return tweet_data


def _card_binding_values(card_legacy: Any) -> dict[str, Any]:
    """binding_values 列表 → {key: string|image dict} 映射（后者保留宽高）。"""
    values: dict[str, Any] = {}
    for entry in (card_legacy or {}).get("binding_values") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        value = entry.get("value")
        if not key or not isinstance(value, dict):
            continue
        if "string_value" in value:
            values[key] = value.get("string_value")
        elif isinstance(value.get("image_value"), dict):
            values[key] = value["image_value"]
    return values


def _resolve_card_url(card_url: str, tweet_data: Any) -> str:
    """card_url 是 t.co 短链：经 legacy.entities.urls 展开为目标页地址。

    展开失败保留 t.co 原值（仍可跳转，经 X 重定向到目标页），绝不置空链接。
    """
    entities = (tweet_data.get("legacy") or {}).get("entities") or {}
    for entity in entities.get("urls") or []:
        if isinstance(entity, dict) and entity.get("url") == card_url:
            expanded = str(entity.get("expanded_url") or "").strip()
            if expanded:
                return expanded
    return card_url


def _extract_link_card(tweet_data: Any) -> dict[str, Any] | None:
    """card.legacy.binding_values → 链接预览卡 dict；无可渲染内容返回 None。

    title 与 card_url 是卡片的可渲染下限（无标题无可看内容、无 URL 无法
    跳转）；description/domain/缩略图任一缺失不阻断。缩略图按
    _CARD_IMAGE_KEYS 逐档回退，全部缺失时 image_url 置空由渲染层降级为
    纯文本卡。
    """
    if not isinstance(tweet_data, dict):
        return None
    card = tweet_data.get("card")
    if not isinstance(card, dict):
        return None
    card_legacy = card.get("legacy")
    values = _card_binding_values(card_legacy)
    title = str(values.get("title") or "").strip()
    card_url = str(values.get("card_url") or "").strip()
    if not title or not card_url:
        return None
    image_url = ""
    image_width = None
    image_height = None
    for key in _CARD_IMAGE_KEYS:
        image = values.get(key)
        if isinstance(image, dict) and str(image.get("url") or "").strip():
            image_url = str(image["url"]).strip()
            image_width = image.get("width")
            image_height = image.get("height")
            break
    return {
        "url": _resolve_card_url(card_url, tweet_data),
        "title": title,
        "description": str(values.get("description") or "").strip(),
        "domain": str(values.get("vanity_url") or values.get("domain") or "").strip(),
        "image_url": image_url,
        "image_width": image_width,
        "image_height": image_height,
        "card_type": str((card_legacy or {}).get("name") or "").strip(),
    }


def _install_link_card_patch() -> None:
    """给 twitter-cli 的 parse_tweet_result 打补丁：回填 X 外链预览卡。

    twitter-cli 0.8.5 的 Tweet dataclass 丢弃 result.card 实体 —— 即 X
    页面对含外链推文渲染的预览卡（YouTube 等的标题/描述/域名/缩略图）。
    本补丁让新采集数据直接落库（documents.link_card），存量无卡推文
    维持现状不渲染，无破坏性。

    补丁策略与 _install_media_poster_patch 同一先例：模块级包装（parser
    内部经模块全局查找调用，引用推文的递归解析同样生效），Tweet 无
    slots 可后置赋值 link_card。卡片抽取缺失仅不赋值，绝不阻断采集；
    安装失败仅记 warning。
    """
    global _ORIGINAL_PARSE_TWEET_RESULT
    if _ORIGINAL_PARSE_TWEET_RESULT is not None:
        return
    try:
        from twitter_cli import parser as tw_parser

        original_parse = tw_parser.parse_tweet_result

        def parse_tweet_result_with_card(result: Any, depth: int = 0) -> Any:
            tweet = original_parse(result, depth=depth)
            if tweet is None:
                return None
            card = _extract_link_card(_resolve_card_tweet_data(result))
            if card:
                tweet.link_card = card
            return tweet

        tw_parser.parse_tweet_result = parse_tweet_result_with_card
        _ORIGINAL_PARSE_TWEET_RESULT = original_parse
    except Exception:
        logger.warning("[XTransport] link card patch 安装失败", exc_info=True)


def _install_parser_patches() -> None:
    """安装全部 twitter-cli parser 补丁（封面回填 + 链接卡片回填）。"""
    _install_media_poster_patch()
    _install_link_card_patch()


def clear_user_id_cache() -> None:
    """清空 user_id 缓存（测试缝 + 运维排障用）。"""
    _USER_ID_CACHE.clear()


def _default_client_factory() -> Any:
    """从环境变量构造真实 TwitterClient（延迟导入，测试注入 fake 时不触碰）。"""
    from twitter_cli.client import TwitterClient

    _install_parser_patches()
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.environ.get("TWITTER_CT0", "").strip()
    if not auth_token or not ct0:
        raise XAuthNotConfigured(
            "x_auth_not_configured: set TWITTER_AUTH_TOKEN and TWITTER_CT0"
        )
    return TwitterClient(auth_token, ct0)


def _default_credential_factory(auth_token: str, ct0: str) -> Any:
    """按给定 cookie pair 构造真实 TwitterClient（延迟导入）。"""
    from twitter_cli.client import TwitterClient

    _install_parser_patches()
    return TwitterClient(auth_token, ct0)


# X 网页端「翻译帖子」同款端点（client-web main.js fetchTranslation）：
# 目标语言由服务端按账号显示语言决定（destinationLanguage=None），
# 账号语言为中文时返回中文译文。目标语言非 zh 的响应会被调用方丢弃。
_TRANSLATION_URL_TEMPLATE = (
    "https://api.x.com/1.1/strato/column/None/"
    "tweetId={tweet_id},destinationLanguage=None,translationSource=Some(X),"
    "feature=None,timeout=None,onlyCached=None/translation/service/translateTweet"
)
_TRANSLATION_INTER_DELAY = 0.4

# ── 推文存活探测（janitor 用）────────────────────────────────────
# 探针 = TweetResultByRestId 原始 GraphQL（单结果、无分页，fetch_article
# 同款端点）。删除在 GraphQL 层返回 HTTP 200，只能靠原始载荷里的
# __typename/reason 判定；code 144 会被 twitter-cli 扁平化成
# TwitterAPIError(status_code=0, message="Twitter API returned errors:
# No status found with that ID.")，只能按 message 子串匹配（漂移落
# unknown，安全方向）。探测间隔与 client requestDelay 默认同口径。
_EXISTENCE_PROBE_INTER_DELAY = 2.5

# fetch_article（twitter_cli/client.py）同款 features；探测不关文章开关
_EXISTENCE_PROBE_FEATURES = {
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
}

# fetch_user（twitter_cli/client.py）同款 features，用于作者账号交叉验证
_USER_PROBE_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

# 墓碑文案跟随凭据账号显示语言：en + zh 本地化一并匹配
_AUTHOR_DELETED_TOMBSTONE_MARKERS = (
    "deleted by the Post author",
    "已被帖子作者删除",
    "已被作者删除",
)
# GraphQL code 144 扁平化后的存活 message（API 侧英文，与账号语言无关）
_NO_STATUS_FOUND_MESSAGE = "No status found with that ID"


def _fetch_tweet_result_raw(client: Any, tweet_id: str) -> dict[str, Any]:
    """TweetResultByRestId 原始 GraphQL 响应（不过 parser，保留 tombstone/typename）。

    经 client._graphql_get：自带共享会话、鉴权头、429 退避与 queryId
    失效后的 live 重取（404/422 重试一次）。
    """
    return client._graphql_get(
        "TweetResultByRestId",
        variables={
            "tweetId": tweet_id,
            "withCommunity": False,
            "includePromotedContent": False,
            "withVoice": False,
        },
        features=_EXISTENCE_PROBE_FEATURES,
        field_toggles={
            "withArticleRichContentState": False,
            "withArticlePlainText": False,
        },
    )


def _classify_probe_payload(payload: Any) -> str:
    """HTTP 200 载荷 → alive/deleted/unavailable/empty/unknown（纯函数，契约测试接缝）。

    口径（2026-08-13 用户拍板 + 当日实测修正）：只认作者删除——
    TweetUnavailable reason=="Deleted"、墓碑文案含作者删除标记 → deleted；
    其他不可用原因（Suspended/账号注销/protected 等）→ unavailable。

    实测（2026-08-13 对照 fxtwitter 404 与作者账号存活交叉验证）：作者删
    除/不存在的推文本端点返回 HTTP 200 且 ``{"data": {"tweetResult": {}}}``
    ——result 键整体缺失、无 errors 数组（非 code 144、非墓碑）。该形态
    单条无法区分「作者删帖」与「账号封禁/转私密连坐」，故单独标记
    "empty"，由 probe_tweet_existence 经作者账号探测定终态。其他结构性
    异常（data 缺失、result 非 dict 等）→ unknown（保守，不动）。
    """
    from twitter_cli.parser import _deep_get

    tweet_result = _deep_get(payload, "data", "tweetResult")
    if not isinstance(tweet_result, dict):
        return "unknown"
    result = tweet_result.get("result")
    if result is None:
        # tweetResult 空对象（无 result 键或显式 null）：推文本体已不可见
        return "empty"
    if not isinstance(result, dict):
        return "unknown"
    typename = str(result.get("__typename") or "")
    if typename == "TweetTombstone":
        reason = str(result.get("reason") or "")
        text = str(_deep_get(result, "tombstone", "text", "text") or "")
        if reason == "Deleted" or any(
            marker in text for marker in _AUTHOR_DELETED_TOMBSTONE_MARKERS
        ):
            return "deleted"
        return "unavailable"
    if typename == "TweetUnavailable":
        return "deleted" if str(result.get("reason") or "") == "Deleted" else "unavailable"
    # Tweet / TweetWithVisibilityResults / 其他可解析形态：存活
    return "alive"


def _fetch_user_raw(client: Any, screen_name: str) -> dict[str, Any]:
    """UserByScreenName 原始 GraphQL 响应（作者账号交叉验证用）。"""
    return client._graphql_get(
        "UserByScreenName",
        variables={"screen_name": screen_name, "withSafetyModeUserFields": True},
        features=_USER_PROBE_FEATURES,
    )


def _classify_user_payload(payload: Any) -> str:
    """作者账号载荷 → alive_public/unavailable/unknown（纯函数）。

    typename User 且未开启保护 → alive_public；UserUnavailable（封禁/注
    销）或 protected 账号 → unavailable（其推文不可见非「作者删帖」）；
    结构异常 → unknown（fail-closed）。
    """
    from twitter_cli.parser import _deep_get

    result = _deep_get(payload, "data", "user", "result")
    if not isinstance(result, dict):
        return "unknown"
    typename = str(result.get("__typename") or "")
    if typename == "UserUnavailable":
        return "unavailable"
    if typename == "User":
        legacy = result.get("legacy")
        protected = bool(isinstance(legacy, dict) and legacy.get("protected"))
        return "unavailable" if protected else "alive_public"
    return "unknown"




def _fetch_translation_payload(client: Any, tweet_id: str) -> dict[str, Any]:
    """调用 translateTweet 返回原始 JSON；非 200 抛异常由调用方吞掉。

    复用 twitter-cli 的共享 curl_cffi 会话（TLS 指纹）与 client 的鉴权
    头构造（bearer + cookie + ct0），与抓取链路同一身份出口。
    """
    from twitter_cli import client as tw_client_mod

    session = tw_client_mod._get_cffi_session()
    url = _TRANSLATION_URL_TEMPLATE.format(tweet_id=tweet_id)
    headers = client._build_headers(url, "GET")
    response = session.get(url, headers=headers, timeout=30)
    status = getattr(response, "status_code", 0)
    if status != 200:
        raise RuntimeError(f"translateTweet HTTP {status}")
    return response.json()


class XTransport:
    """X 关注账号推文抓取传输层。

    client_factory: 可注入的无参客户端工厂（默认 _default_client_factory），
        仅在未提供 credential_provider 时使用，保持旧调用方/测试兼容。
    credential_provider: 可注入的凭据提供者，返回包含 auth_token/ct0/enabled
        的字典列表；提供时优先使用，并按顺序 fallback。
    credential_factory: 凭据构造器，签名 (auth_token, ct0) -> client；
        默认延迟导入 TwitterClient。
    id_cache: 可注入的 user_id 缓存映射（默认模块级缓存）。
    sleep: 可注入的延迟函数（默认 asyncio.sleep）。
    """

    def __init__(
        self,
        client_factory: Callable[[], Any] | None = None,
        *,
        credential_provider: Callable[[], list[dict[str, Any]]] | None = None,
        credential_factory: Callable[[str, str], Any] | None = None,
        inter_account_delay: float = DEFAULT_INTER_ACCOUNT_DELAY,
        id_cache: MutableMapping[str, tuple[str, float]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._credential_provider = credential_provider
        self._credential_factory = credential_factory or _default_credential_factory
        self._inter_account_delay = inter_account_delay
        self._id_cache = id_cache if id_cache is not None else _USER_ID_CACHE
        self._sleep = sleep or asyncio.sleep

    async def fetch_watchlist_tweets_window(
        self,
        handles: Iterable[str],
        *,
        window_start: datetime,
        window_end: datetime,
        count_per_user: int = 20,
    ) -> XWindowFetchResult:
        """沿 Bottom cursor 分页抓取固定 UTC 半开窗口，直到证明覆盖完整。

        ``count_per_user`` 只是单页大小提示（封顶 twitter-cli 的页尺寸），
        不再是窗口总条数上限。任一凭据在任意分页遇到 429/认证失效即丢弃
        当前凭据全部 partial，按顺序换下一凭据从完整 watchlist 重试。
        """
        start = window_start.astimezone(timezone.utc)
        end = window_end.astimezone(timezone.utc)
        watchlist = tuple(handles)
        page_size = max(1, min(int(count_per_user or 20), _WINDOW_PAGE_SIZE))

        if self._credential_provider is not None:
            by_handle = await self._fetch_window_with_credential_provider(
                watchlist, window_start=start, window_end=end, page_size=page_size
            )
        else:
            by_handle = await self._fetch_window_with_client(
                self._client_factory(),
                watchlist,
                window_start=start,
                window_end=end,
                page_size=page_size,
            )
        return XWindowFetchResult(
            requested_handles=watchlist,
            window_start=start,
            window_end=end,
            by_handle=by_handle,
        )

    async def _fetch_window_with_client(
        self,
        client: Any,
        handles: tuple[str, ...],
        *,
        window_start: datetime,
        window_end: datetime,
        page_size: int,
    ) -> dict[str, XWindowHandleResult]:
        """单 client 路径：保留旧异常包装契约（auth/429 中止上抛）。"""
        try:
            return await self._raw_fetch_window_with_client(
                client,
                handles,
                window_start=window_start,
                window_end=window_end,
                page_size=page_size,
            )
        except AuthenticationError as exc:
            raise XAuthAbort("x_auth_expired") from exc
        except RateLimitError as exc:
            raise XRateLimitAbort("x_rate_limited") from exc

    async def _raw_fetch_window_with_client(
        self,
        client: Any,
        handles: tuple[str, ...],
        *,
        window_start: datetime,
        window_end: datetime,
        page_size: int,
    ) -> dict[str, XWindowHandleResult]:
        """逐账号串行 cursor 分页；传播原始 AuthenticationError/RateLimitError。

        故障分级与 ``_raw_fetch_with_client`` 同口径：
          - NotFound（账号消失/改名/保护）→ 该 handle 记 account_unavailable
            incomplete（外部原因，不是凭据轮换理由），整轮继续；
          - 401/403 → 归一 AuthenticationError；429 → RateLimitError（中止、
            丢弃本凭据 partial，交给凭据池或上抛）；
          - curl 瞬断 → 按 _NETWORK_RETRY_DELAYS 退避重试（共享每轮预算）；
          - 其余单账号故障 → transport_error incomplete。
        与 count 路径不同：账号级失败不再静默跳过——rolling 完整性要求
        每个 watchlist 账号都有 typed 结论（complete 或外部原因），整轮
        完整性由 crawler fail-closed 判定。
        """
        result: dict[str, XWindowHandleResult] = {}
        retry_budget = _NETWORK_RETRY_BUDGET_PER_ROUND
        for index, handle in enumerate(handles):
            if index > 0:
                await self._sleep(self._jittered_delay())
            try:
                user_id = await self._resolve_user_id(client, handle)
            except AuthenticationError:
                raise
            except RateLimitError:
                raise
            except NotFoundError:
                logger.warning(
                    "[XTransport] 账号不存在/已注销/已改名/保护，窗口记不完整: %s",
                    handle,
                )
                result[handle] = XWindowHandleResult(
                    complete=False, reason="account_unavailable"
                )
                continue
            except TwitterAPIError as exc:
                if exc.status_code in (401, 403):
                    raise AuthenticationError(
                        "Twitter API 认证失败 (HTTP %d)" % exc.status_code
                    ) from exc
                if exc.status_code == 429:
                    raise RateLimitError("Twitter API 限流 (HTTP 429)") from exc
                logger.exception("[XTransport] 账号 %s user-id 解析失败", handle)
                result[handle] = XWindowHandleResult(
                    complete=False, reason="transport_error"
                )
                continue
            except Exception as exc:
                if _is_transient_network_error(exc) and retry_budget > 0:
                    retry_budget -= 1
                    await self._sleep(_NETWORK_RETRY_DELAYS[0])
                    try:
                        user_id = await self._resolve_user_id(client, handle)
                    except Exception:
                        logger.exception(
                            "[XTransport] 账号 %s user-id 解析重试仍失败", handle
                        )
                        result[handle] = XWindowHandleResult(
                            complete=False, reason="transport_error"
                        )
                        continue
                else:
                    logger.exception("[XTransport] 账号 %s user-id 解析失败", handle)
                    result[handle] = XWindowHandleResult(
                        complete=False, reason="transport_error"
                    )
                    continue

            handle_result, retry_budget = await self._collect_window_for_handle(
                client,
                handle,
                user_id,
                window_start=window_start,
                window_end=window_end,
                page_size=page_size,
                retry_budget=retry_budget,
            )
            result[handle] = handle_result
        return result

    async def _fetch_window_with_credential_provider(
        self,
        handles: tuple[str, ...],
        *,
        window_start: datetime,
        window_end: datetime,
        page_size: int,
    ) -> dict[str, XWindowHandleResult]:
        """凭据池路径：任意分页 429/认证失效即换下一凭据从完整 watchlist 重试。"""
        credentials = self._credential_provider()
        if not credentials:
            raise XAuthNotConfigured("x_auth_not_configured: no enabled X credentials")

        last_auth_error: AuthenticationError | None = None
        last_rate_limit_error: RateLimitError | None = None
        tried = 0
        for index, credential in enumerate(credentials):
            if not credential.get("enabled", True):
                continue
            auth_token = str(credential.get("auth_token") or "").strip()
            ct0 = str(credential.get("ct0") or "").strip()
            if not auth_token or not ct0:
                continue

            tried += 1
            if tried > 1:
                await self._sleep(self._jittered_delay())

            client = self._credential_factory(auth_token, ct0)
            try:
                return await self._raw_fetch_window_with_client(
                    client,
                    handles,
                    window_start=window_start,
                    window_end=window_end,
                    page_size=page_size,
                )
            except AuthenticationError as exc:
                last_auth_error = exc
                logger.warning(
                    "[XTransport] 凭据 %s 认证失败，丢弃 partial 并尝试下一个",
                    credential.get("display_name") or f"#{index}",
                )
                continue
            except RateLimitError as exc:
                last_rate_limit_error = exc
                logger.warning(
                    "[XTransport] 凭据 %s 触发限流，丢弃 partial 并尝试下一个",
                    credential.get("display_name") or f"#{index}",
                )
                continue

        if last_rate_limit_error is not None:
            raise XRateLimitAbort("x_rate_limited") from last_rate_limit_error
        if last_auth_error is not None:
            raise XAuthAbort("x_auth_all_credentials_failed") from last_auth_error
        raise XAuthNotConfigured("x_auth_not_configured: no valid X credentials")

    async def _collect_window_for_handle(
        self,
        client: Any,
        handle: str,
        user_id: str,
        *,
        window_start: datetime,
        window_end: datetime,
        page_size: int,
        retry_budget: int,
    ) -> tuple[XWindowHandleResult, int]:
        """单账号沿 Bottom cursor 分页，返回 (结果, 剩余网络重试预算)。

        操作：UserTweetsAndReplies（2026-08-22 起，含对他人回复；
        需 X-Client-Transaction-Id，响应固定 v1 结构，见
        _WINDOW_TIMELINE_OPERATION 注释）；_REPLIES_EXCLUDED_HANDLES
        中的账号（grok）回退 UserTweets（不采回复贴，用户决策）。

        AndReplies 时间线的会话模块会把**回复对象的父贴**（作者多为非
        观察名单账号）一并下发，parse_timeline_response 会将其解析成独立
        文档——入库过滤只对作者 == 当前 handle 的条目与转贴豁免
        （转贴已由 parser 换成原贴作者，但属 2026-08-13 起刻意收录的
        「watchlist 账号转贴带入」路径，is_retweet 标记保留可识别）。

        complete 仅当满足以下之一：
          - boundary_reached：最早的**时间线外层条目**时间戳 ≤ window_start
            （纯转贴用外层条目时间判定，不用被替换成原贴的 created_at）；
          - timeline_exhausted：响应明确且结构完整地证明 timeline 到头
            （空 entries、或翻到页预算一半以后拿到空推文页）。
        其余一切形态（缺 instruction、cursor 停滞/缺失、无法证明边界的
        时间戳、页预算耗尽、传输故障）一律 fail-closed 记 incomplete。
        """
        from twitter_cli import graphql as tw_graphql, parser as tw_parser

        def get_instructions(data: Any) -> Any:
            # UserTweetsAndReplies 当前固定回 v1 结构
            # （data.user.result.timeline.timeline.instructions，
            # withV2Timeline 被服务端忽略）；保留 timeline_v2 优先探测，
            # 服务端日后升级到 v2 时无需改代码。
            instructions = tw_parser._deep_get(
                data,
                "data",
                "user",
                "result",
                "timeline_v2",
                "timeline",
                "instructions",
            )
            if isinstance(instructions, list):
                return instructions
            return tw_parser._deep_get(
                data,
                "data",
                "user",
                "result",
                "timeline",
                "timeline",
                "instructions",
            )

        tweets: list[Any] = []
        seen_ids: set[str] = set()
        cursor: str | None = None
        page_count = 0
        fetched_count = 0
        oldest_seen: datetime | None = None
        complete = False
        reason = "transport_error"
        replies_excluded = handle.lower() in _REPLIES_EXCLUDED_HANDLES
        # 被排除账号回退 UserTweets：沿用该操作实测 200 的旧变量形状
        # （含 withV2Timeline/latestControlAvailable/requestContext），
        # 不混用 AndReplies 的精简五键。
        operation = "UserTweets" if replies_excluded else _WINDOW_TIMELINE_OPERATION

        while page_count < _WINDOW_MAX_PAGES_PER_HANDLE:
            variables: dict[str, Any] = {
                "count": page_size,
                **_WINDOW_BASE_VARIABLES,
                "userId": user_id,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
            }
            if replies_excluded:
                variables["withV2Timeline"] = True
                variables["latestControlAvailable"] = True
                variables["requestContext"] = "launch"
            if cursor:
                variables["cursor"] = cursor

            try:
                data = await asyncio.to_thread(
                    client._graphql_get,
                    operation,
                    variables,
                    tw_graphql.FEATURES,
                )
            except AuthenticationError:
                raise
            except RateLimitError:
                raise
            except TwitterAPIError as exc:
                if exc.status_code in (401, 403):
                    raise AuthenticationError(
                        "Twitter API 认证失败 (HTTP %d)" % exc.status_code
                    ) from exc
                if exc.status_code == 429:
                    raise RateLimitError("Twitter API 限流 (HTTP 429)") from exc
                logger.exception("[XTransport] 账号 %s 第 %d 页抓取失败", handle, page_count + 1)
                reason = "transport_error"
                break
            except Exception as exc:
                if _is_transient_network_error(exc) and retry_budget > 0:
                    retry_budget -= 1
                    logger.warning(
                        "[XTransport] 账号 %s 第 %d 页网络故障(%s)，%.0fs 后重试",
                        handle,
                        page_count + 1,
                        exc,
                        _NETWORK_RETRY_DELAYS[0],
                    )
                    await self._sleep(_NETWORK_RETRY_DELAYS[0])
                    continue
                logger.exception("[XTransport] 账号 %s 第 %d 页抓取异常", handle, page_count + 1)
                reason = "transport_error"
                break

            page_count += 1
            instructions = get_instructions(data)
            if not isinstance(instructions, list):
                # 结构漂移：无法定位 timeline 指令，绝不能猜。
                logger.warning(
                    "[XTransport] 账号 %s 第 %d 页缺 timeline instructions，记 parser_drift",
                    handle,
                    page_count,
                )
                reason = "parser_drift"
                break

            page_tweets, next_cursor = tw_parser.parse_timeline_response(
                data, get_instructions
            )
            page_oldest = self._page_oldest_entry_timestamp(instructions)

            new_ids = 0
            for tweet in page_tweets:
                tweet_id = str(getattr(tweet, "id", "") or "")
                if not tweet_id or tweet_id in seen_ids:
                    continue
                # 会话祖先过滤：AndReplies 下发的父贴作者不是本账号，
                # 丢弃；转贴（parser 已换成原贴作者、保留 is_retweet）
                # 豁免，属刻意收录的转贴带入路径。
                author = str(
                    getattr(getattr(tweet, "author", None), "screen_name", "") or ""
                )
                if author.lower() != handle.lower() and not getattr(
                    tweet, "is_retweet", False
                ):
                    continue
                seen_ids.add(tweet_id)
                tweets.append(tweet)
                new_ids += 1
            fetched_count += len(page_tweets)

            if page_oldest is not None and (
                oldest_seen is None or page_oldest < oldest_seen
            ):
                oldest_seen = page_oldest

            # 边界证明优先：最早外层条目已越过窗口下界 → 覆盖完整。
            if page_oldest is not None and page_oldest <= window_start:
                complete = True
                reason = "boundary_reached"
                break

            # 明确耗尽：timeline 没有任何 entries（连 cursor 都没有）。
            has_entries = any(
                (instruction.get("entries") or instruction.get("moduleItems"))
                for instruction in instructions
                if isinstance(instruction, dict)
            )
            if not has_entries:
                complete = True
                reason = "timeline_exhausted"
                break

            if not next_cursor:
                # 有 entries 却没有 Bottom cursor：无法区分「真到头」与
                # 「解析漂移」，只有翻得足够深且本页零推文才敢按耗尽判。
                if not page_tweets and page_count >= max(2, _WINDOW_MAX_PAGES_PER_HANDLE // 2):
                    complete = True
                    reason = "timeline_exhausted"
                else:
                    reason = "pagination_metadata_missing"
                break

            if next_cursor == cursor:
                reason = "cursor_stalled"
                break

            cursor = next_cursor
            if page_oldest is None and not page_tweets:
                # 整页无推文也无外层时间戳，只有 cursor 推进：继续翻，
                # 但无法据此证明边界，耗尽判定交给后续页/页预算。
                continue

        else:
            # while 正常结束 = 页预算耗尽仍未证明边界。
            reason = "page_limit_reached"

        if not complete:
            logger.warning(
                "[XTransport] 账号 %s rolling 窗口不完整: reason=%s pages=%d fetched=%d oldest=%s",
                handle,
                reason,
                page_count,
                fetched_count,
                oldest_seen.isoformat() if oldest_seen else None,
            )

        return (
            XWindowHandleResult(
                tweets=tuple(tweets),
                complete=complete,
                reason=reason,
                page_count=page_count,
                fetched_count=fetched_count,
                oldest_seen=oldest_seen,
            ),
            retry_budget,
        )

    @staticmethod
    def _page_oldest_entry_timestamp(instructions: list[Any]) -> datetime | None:
        """本页最早的**时间线外层条目**时间戳（纯转贴用外层时间，不用原贴）。

        parser 会把纯转贴替换成被转原贴（created_at 是原贴时间，可能远
        早于窗口），若用它判边界会误判「已越过窗口」。这里直接读原始
        timeline entry 的 itemContent.tweet_results.result.legacy.created_at
        ——即外层条目（转发动作）的时间。无任何可解析时间戳返回 None。
        """
        from twitter_cli import parser as tw_parser

        oldest: datetime | None = None
        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            entries = instruction.get("entries") or instruction.get("moduleItems") or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                content = entry.get("content") or {}
                candidates: list[Any] = [
                    tw_parser._deep_get(
                        content, "itemContent", "tweet_results", "result"
                    )
                ]
                for nested in content.get("items") or []:
                    candidates.append(
                        tw_parser._deep_get(
                            nested, "item", "itemContent", "tweet_results", "result"
                        )
                    )
                for result in candidates:
                    created = XTransport._outer_entry_created_at(result)
                    if created is not None and (oldest is None or created < oldest):
                        oldest = created
        return oldest

    @staticmethod
    def _outer_entry_created_at(result: Any) -> datetime | None:
        """外层条目 tweetResult 的 legacy.created_at（不解包 retweet 原贴）。"""
        if not isinstance(result, dict):
            return None
        tweet_data = result
        if result.get("__typename") == "TweetWithVisibilityResults" and isinstance(
            result.get("tweet"), dict
        ):
            tweet_data = result["tweet"]
        legacy = tweet_data.get("legacy")
        if not isinstance(legacy, dict):
            return None
        return _parse_tweet_timestamp(legacy.get("created_at"))

    async def fetch_watchlist_tweets(
        self,
        handles: Iterable[str],
        count_per_user: int = 20,
    ) -> dict[str, list[Any]]:
        """按 watchlist 顺序抓取各账号近期推文。

        Returns:
            {handle: [Tweet, ...]}；被跳过的账号不出现在结果中。

        Raises:
            XAuthNotConfigured: 凭据未配置。
            XAuthAbort / XRateLimitAbort: 中止级故障，调用方应整轮失败。
        """
        watchlist = tuple(handles)
        if self._credential_provider is not None:
            return await self._fetch_with_credential_provider(
                watchlist,
                count_per_user,
            )

        client = self._client_factory()
        return await self._fetch_with_client(client, watchlist, count_per_user)

    def fetch_tweet_translations(self, tweet_ids: Iterable[str]) -> dict[str, str]:
        """尽力而为抓 X 自带中文翻译，返回 {tweet_id: 译文}。

        同步方法（内部走 curl_cffi），调用方应经 asyncio.to_thread 转入
        线程池。只保留 translationState=Success 且目标语言为 zh 的响应；
        单条失败记 debug 跳过，客户端构造失败记 warning 返回空表——
        任何异常都不上抛，翻译是增强不是阻断项。
        """
        ids = [str(tid).strip() for tid in tweet_ids if str(tid).strip()]
        if not ids:
            return {}
        try:
            client = self._translation_client()
        except Exception:
            logger.warning("[XTransport] 翻译客户端构造失败，本轮跳过翻译", exc_info=True)
            return {}
        result: dict[str, str] = {}
        for index, tweet_id in enumerate(ids):
            if index > 0:
                time.sleep(_TRANSLATION_INTER_DELAY)
            try:
                payload = _fetch_translation_payload(client, tweet_id)
            except Exception:
                logger.debug("[XTransport] 推文 %s 翻译抓取失败，跳过", tweet_id, exc_info=True)
                continue
            text = str(payload.get("translation") or "").strip()
            state = str(payload.get("translationState") or "")
            destination = str(payload.get("destinationLanguage") or "")
            if text and state == "Success" and destination.startswith("zh"):
                result[tweet_id] = text
        return result

    def probe_tweet_existence(
        self,
        tweet_ids: Iterable[str],
        authors: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """逐条探测推文是否被原作者删除，返回 {tweet_id: alive/deleted/unavailable/unknown}。

        同步方法（内部走 curl_cffi），调用方应经 asyncio.to_thread 转入
        线程池。串行探测、固定间隔，对限流友好。口径与调用方约定：
        deleted 才可删；unavailable（账号封禁/保护等）与 unknown（404/
        网络/解析漂移）一律视为存活（fail-closed）。

        authors: {tweet_id: 作者 screen_name}。推文探得 "empty"（本体不可
        见，实测作者删帖形态）时用作者账号交叉验证：账号存活且公开 →
        deleted（作者删帖）；账号封禁/注销/转私密 → unavailable；无作者信
        息或账号探测异常 → unknown。作者探测按 screen_name 去重缓存。

        Raises:
            XAuthNotConfigured: 无启用凭据（整轮中止）。
            XAuthAbort: 鉴权失效/401/403（整轮中止，已探测部分结果丢弃）。
            XRateLimitAbort: 429 限流（整轮中止，已探测部分结果丢弃）。
        """
        ids = [str(tid).strip() for tid in tweet_ids if str(tid).strip()]
        if not ids:
            return {}
        client = self._translation_client()
        author_status_cache: dict[str, str] = {}
        result: dict[str, str] = {}
        for index, tweet_id in enumerate(ids):
            if index > 0:
                time.sleep(_EXISTENCE_PROBE_INTER_DELAY * random.uniform(0.8, 1.2))
            try:
                payload = _fetch_tweet_result_raw(client, tweet_id)
                status = _classify_probe_payload(payload)
            except AuthenticationError as exc:
                raise XAuthAbort("x_auth_expired") from exc
            except TwitterAPIError as exc:
                status = getattr(exc, "status_code", 0)
                message = str(getattr(exc, "message", "") or exc)
                if status == 429:
                    raise XRateLimitAbort("x_rate_limited") from exc
                if status in (401, 403):
                    raise XAuthAbort("x_auth_expired") from exc
                if _NO_STATUS_FOUND_MESSAGE in message:
                    # GraphQL code 144 扁平化形态：明确"该 ID 不存在"=已删除
                    result[tweet_id] = "deleted"
                    continue
                logger.debug(
                    "[XTransport] 推文 %s 存活探测失败（HTTP %s），按 unknown 处理",
                    tweet_id,
                    status,
                    exc_info=True,
                )
                result[tweet_id] = "unknown"
                continue
            except Exception:
                logger.debug(
                    "[XTransport] 推文 %s 存活探测异常，按 unknown 处理",
                    tweet_id,
                    exc_info=True,
                )
                result[tweet_id] = "unknown"
                continue
            if status == "empty":
                status = self._resolve_empty_via_author(
                    client, tweet_id, authors or {}, author_status_cache
                )
            result[tweet_id] = status
        return result

    def _resolve_empty_via_author(
        self,
        client: Any,
        tweet_id: str,
        authors: Mapping[str, str],
        cache: dict[str, str],
    ) -> str:
        """"empty" 推文经作者账号状态定终态（见 probe_tweet_existence 口径）。"""
        screen_name = str(authors.get(tweet_id) or "").strip().lstrip("@")
        if not screen_name:
            return "unknown"
        if screen_name not in cache:
            try:
                time.sleep(_EXISTENCE_PROBE_INTER_DELAY * random.uniform(0.8, 1.2))
                cache[screen_name] = _classify_user_payload(
                    _fetch_user_raw(client, screen_name)
                )
            except AuthenticationError as exc:
                raise XAuthAbort("x_auth_expired") from exc
            except NotFoundError:
                # 账号本体查无（注销/封禁）：推文消失非作者删帖
                cache[screen_name] = "unavailable"
            except TwitterAPIError as exc:
                status = getattr(exc, "status_code", 0)
                if status == 429:
                    raise XRateLimitAbort("x_rate_limited") from exc
                if status in (401, 403):
                    raise XAuthAbort("x_auth_expired") from exc
                logger.debug(
                    "[XTransport] 作者 @%s 探测失败（HTTP %s），按 unknown 处理",
                    screen_name,
                    status,
                    exc_info=True,
                )
                cache[screen_name] = "unknown"
            except Exception:
                logger.debug(
                    "[XTransport] 作者 @%s 探测异常，按 unknown 处理",
                    screen_name,
                    exc_info=True,
                )
                cache[screen_name] = "unknown"
        author_state = cache[screen_name]
        if author_state == "alive_public":
            # 账号存活且公开而推文本体不可见：作者删除（fxtwitter 404 实测交叉验证）
            return "deleted"
        if author_state == "unavailable":
            return "unavailable"
        return "unknown"

    def _translation_client(self) -> Any:
        """翻译请求复用与抓取相同的凭据链：provider 首个启用凭据 > client_factory。"""
        if self._credential_provider is not None:
            for credential in self._credential_provider():
                if not credential.get("enabled", True):
                    continue
                auth_token = str(credential.get("auth_token") or "").strip()
                ct0 = str(credential.get("ct0") or "").strip()
                if auth_token and ct0:
                    return self._credential_factory(auth_token, ct0)
            raise XAuthNotConfigured("x_auth_not_configured: no valid X credentials")
        return self._client_factory()

    async def _fetch_with_client(
        self,
        client: Any,
        handles: Iterable[str],
        count_per_user: int,
    ) -> dict[str, list[Any]]:
        """使用单个 client 抓取，保留旧的异常包装契约。"""
        try:
            return await self._raw_fetch_with_client(client, handles, count_per_user)
        except AuthenticationError as exc:
            raise XAuthAbort("x_auth_expired") from exc
        except RateLimitError as exc:
            raise XRateLimitAbort("x_rate_limited") from exc

    async def _raw_fetch_with_client(
        self,
        client: Any,
        handles: Iterable[str],
        count_per_user: int,
    ) -> dict[str, list[Any]]:
        """使用单个 client 抓取，传播原始 AuthenticationError / RateLimitError。

        故障分级：
          - NotFoundError（账号消失）：个体问题，跳过，不计故障
          - TwitterAPIError(401/403)：twitter-cli 把 GraphQL 认证失效包成
            TwitterAPIError 而非 AuthenticationError（生产实证：HTTP 401
            code 32 "Could not authenticate you"）——凭证级失效，归一为
            AuthenticationError 立即中止本轮，交给凭证池 fallback 或上抛
            XAuthAbort；不拿死凭据锤其余账号，也绝不误计为基础设施故障
          - TwitterAPIError(429)：twitter-cli 内部退避后仍限流（它把 429 包成
            TwitterAPIError 而非 RateLimitError）——凭据级限流，立即中止当前
            凭据并丢弃 partial result；provider 路径交给下一凭据重试完整列表，
            单 client 路径升级为 XRateLimitAbort
          - curl 层网络故障（代理拒连/超时/截断）：按 _NETWORK_RETRY_DELAYS
            退避重试，骑过出口代理分钟级抖动；预算烧完或仍失败才计故障
          - 其他异常（解析漂移等）：跳过并计系统性故障；整轮零
            成功时升级为 XTransportUnavailable，让采集轮以 error 收场
        全部账号 NotFound（集体消失）不算基础设施故障，原样返回空表。
        """
        watchlist = tuple(handles)
        result: dict[str, list[Any]] = {}
        infra_failures = 0
        retry_budget = _NETWORK_RETRY_BUDGET_PER_ROUND
        for index, handle in enumerate(watchlist):
            if index > 0:
                await self._sleep(self._jittered_delay())
            attempt = 0
            while True:
                try:
                    user_id = await self._resolve_user_id(client, handle)
                    result[handle] = await asyncio.to_thread(
                        client.fetch_user_tweets, user_id, count_per_user
                    )
                    break
                except AuthenticationError:
                    raise
                except RateLimitError:
                    raise
                except NotFoundError:
                    logger.warning(
                        "[XTransport] 账号不存在/已注销/已改名，跳过: %s",
                        handle,
                    )
                    break
                except TwitterAPIError as exc:
                    if exc.status_code in (401, 403):
                        # 凭证级认证失效（twitter-cli 把 GraphQL 401/403 包成
                        # TwitterAPIError 而非 AuthenticationError）：归一为
                        # AuthenticationError，凭证池路径据此轮换备用凭据、
                        # 单 client 路径据此上抛 XAuthAbort("x_auth_expired")。
                        raise AuthenticationError(
                            "Twitter API 认证失败 (HTTP %d)" % exc.status_code
                        ) from exc
                    if exc.status_code == 429:
                        raise RateLimitError(
                            "Twitter API 限流 (HTTP 429)"
                        ) from exc
                    infra_failures += 1
                    logger.exception("[XTransport] 账号 %s 抓取失败，跳过", handle)
                    break
                except Exception as exc:
                    if (
                        _is_transient_network_error(exc)
                        and attempt < len(_NETWORK_RETRY_DELAYS)
                        and retry_budget > 0
                    ):
                        delay = _NETWORK_RETRY_DELAYS[attempt]
                        attempt += 1
                        retry_budget -= 1
                        logger.warning(
                            "[XTransport] 账号 %s 网络故障(%s)，%.0fs 后重试(%d/%d)",
                            handle,
                            exc,
                            delay,
                            attempt,
                            len(_NETWORK_RETRY_DELAYS),
                        )
                        await self._sleep(delay)
                        continue
                    infra_failures += 1
                    logger.exception("[XTransport] 账号 %s 抓取失败，跳过", handle)
                    break

        if result or not watchlist:
            return result
        # 零成功轮升级：绝不让基础设施级故障以「空结果成功」静默收场
        if infra_failures:
            raise XTransportUnavailable("x_transport_unavailable")
        return result

    async def _fetch_with_credential_provider(
        self,
        handles: Iterable[str],
        count_per_user: int,
    ) -> dict[str, list[Any]]:
        """按顺序尝试凭据，认证失败或 429 时从完整列表 fallback。"""
        credentials = self._credential_provider()
        if not credentials:
            raise XAuthNotConfigured("x_auth_not_configured: no enabled X credentials")

        # A provider may return a generator or another one-shot iterable. Keep
        # one immutable watchlist for every credential attempt so fallback
        # retries the complete list rather than the unconsumed suffix.
        watchlist = tuple(handles)
        last_auth_error: AuthenticationError | None = None
        last_rate_limit_error: RateLimitError | None = None
        tried = 0
        for index, credential in enumerate(credentials):
            if not credential.get("enabled", True):
                continue
            auth_token = str(credential.get("auth_token") or "").strip()
            ct0 = str(credential.get("ct0") or "").strip()
            if not auth_token or not ct0:
                continue

            tried += 1
            if tried > 1:
                await self._sleep(self._jittered_delay())

            client = self._credential_factory(auth_token, ct0)
            try:
                return await self._raw_fetch_with_client(
                    client, watchlist, count_per_user
                )
            except AuthenticationError as exc:
                last_auth_error = exc
                logger.warning(
                    "[XTransport] 凭据 %s 认证失败，尝试下一个",
                    credential.get("display_name") or f"#{index}",
                )
                continue
            except RateLimitError as exc:
                last_rate_limit_error = exc
                logger.warning(
                    "[XTransport] 凭据 %s 触发限流，丢弃 partial 并尝试下一个",
                    credential.get("display_name") or f"#{index}",
                )
                continue

        if last_rate_limit_error is not None:
            raise XRateLimitAbort("x_rate_limited") from last_rate_limit_error
        if last_auth_error is not None:
            raise XAuthAbort("x_auth_all_credentials_failed") from last_auth_error
        raise XAuthNotConfigured("x_auth_not_configured: no valid X credentials")

    async def _resolve_user_id(self, client: Any, handle: str) -> str:
        """screen_name → user_id，优先读 24h 缓存（省一次 UserByScreenName 请求）。"""
        key = handle.strip().lower()
        now = time.monotonic()
        cached = self._id_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
        profile = await asyncio.to_thread(client.fetch_user, handle)
        user_id = str(profile.id)
        self._id_cache[key] = (user_id, now + USER_ID_CACHE_TTL_SECONDS)
        return user_id

    def _jittered_delay(self) -> float:
        """账号间隔：基线 × [0.8, 1.6) 抖动，避免机械式固定节拍。"""
        return self._inter_account_delay * random.uniform(0.8, 1.6)
