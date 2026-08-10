from __future__ import annotations

"""X/Twitter 传输层：包装 twitter-cli 同步客户端的异步门面。

设计要点：
  - twitter-cli（curl_cffi + time.sleep）是同步库，所有调用经
    asyncio.to_thread 转入线程池，不阻塞事件循环
  - 账号顺序处理 + 账号间抖动延迟：凭据为主账号 cookie，
    温和节奏优先于吞吐（不并发 gather）
  - screen_name → user_id 模块级 24h 缓存：请求量减半
  - 异常分级：认证失效/限流 → 中止整轮（不拿死凭据锤其余账号）；
    单账号 NotFound/其他异常 → 记录并跳过
  - 支持注入 credential_provider：按启用顺序构造独立 TwitterClient，
    认证失败时丢弃 partial result 并从完整 watchlist 用下一凭据重试；
    429 不切换账号以避免扩大 IP 级限流

凭据来源优先级：
  1. 注入的 ``credential_provider``（生产数据库事实源）
  2. 显式的 ``client_factory``（测试/旧调用兼容，读取 env）
"""

import asyncio
import logging
import os
import random
import time
from typing import Any, Awaitable, Callable, Iterable, MutableMapping

from twitter_cli.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

USER_ID_CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_INTER_ACCOUNT_DELAY = 5.0

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


class XAuthNotConfigured(Exception):
    """缺少可用 X 凭据。"""


class XAuthAbort(Exception):
    """认证失效，中止整轮采集（避免死凭据连续锤击触发风控）。"""


class XRateLimitAbort(Exception):
    """触发限流（twitter-cli 内部退避后仍 429），中止整轮采集。"""


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
        """使用单个 client 抓取，传播原始 AuthenticationError / RateLimitError。"""
        result: dict[str, list[Any]] = {}
        for index, handle in enumerate(handles):
            if index > 0:
                await self._sleep(self._jittered_delay())
            try:
                user_id = await self._resolve_user_id(client, handle)
                result[handle] = await asyncio.to_thread(
                    client.fetch_user_tweets, user_id, count_per_user
                )
            except AuthenticationError:
                raise
            except RateLimitError:
                raise
            except NotFoundError:
                logger.warning(
                    "[XTransport] 账号不存在/已注销/已改名，跳过: %s",
                    handle,
                )
            except Exception:
                logger.exception("[XTransport] 账号 %s 抓取失败，跳过", handle)
        return result

    async def _fetch_with_credential_provider(
        self,
        handles: Iterable[str],
        count_per_user: int,
    ) -> dict[str, list[Any]]:
        """按顺序尝试 credential_provider 返回的凭据，认证失败时 fallback。"""
        credentials = self._credential_provider()
        if not credentials:
            raise XAuthNotConfigured("x_auth_not_configured: no enabled X credentials")

        # A provider may return a generator or another one-shot iterable. Keep
        # one immutable watchlist for every credential attempt so fallback
        # retries the complete list rather than the unconsumed suffix.
        watchlist = tuple(handles)
        last_auth_error: AuthenticationError | None = None
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
                raise XRateLimitAbort("x_rate_limited") from exc

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
