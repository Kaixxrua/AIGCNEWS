from __future__ import annotations

"""X 看板媒体 URL 规则的 Python 移植（纯函数，无 I/O）。

权威源是前端 `frontend/src/features/xboard/xBoardViewModel.ts` 的
proxiedMediaUrl / photoVariantUrl / proxyMediaList：预热必须请求与看板
渲染逐字节相同的路径式代理 URL，否则边缘缓存 key 不一致 = 白预热。
改动规则时两侧必须同步，backend/tests/test_x_media_urls.py 逐条镜像
frontend/src/features/xboard/xBoardViewModel.test.ts 的 URL 形态断言。
"""

import math
import re
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

X_MEDIA_IMG_PREFIX = "/api/media/x/img"

# 与 routes_x_media.ALLOWED_MEDIA_HOSTS 同一白名单（后端代理另有校验，
# 此处只做渲染层同源改写判定，与 TS 侧 X_MEDIA_HOSTS 对齐）。
TWIMG_HOSTS = frozenset({"pbs.twimg.com", "video.twimg.com", "abs.twimg.com"})

# twimg 支持 ?name= 派生尺寸的图片路径前缀（推文照片与三类视频封面图）。
TWIMG_VARIANT_PATH_RE = re.compile(
    r"^/(?:media|ext_tw_video_thumb|amplify_video_thumb|tweet_video_thumb)/"
)

_VIDEO_TYPES = frozenset({"video", "animated_gif"})

# twimg 具名尺寸是「长边约束框」（[框边长, name] 升序），与 TS 侧
# TWIMG_BOX_VARIANTS 同表；4096 是 X 照片上限，等同 orig。
TWIMG_BOX_VARIANTS: tuple[tuple[int, str], ...] = (
    (680, "small"),
    (900, "900x900"),
    (1200, "medium"),
    (2048, "large"),
    (4096, "4096x4096"),
)

# 看板内联目标宽（与 TS PHOTO_INLINE_TARGET_WIDTH 对齐）。
PHOTO_INLINE_TARGET_WIDTH = 680


def is_twimg_url(url: str) -> bool:
    try:
        return urlsplit(url).hostname in TWIMG_HOSTS
    except ValueError:
        return False


def proxied_media_url(url: str) -> str:
    """twimg URL → 路径式同源代理形态；非 twimg 或非法 URL 原样透传。"""
    if not is_twimg_url(url):
        return url
    parsed = urlsplit(url)  # is_twimg_url 已校验可解析；hostname 不含端口（校验见代理白名单）
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{X_MEDIA_IMG_PREFIX}/{parsed.hostname}{parsed.path}{query}"


def photo_variant_url(url: str, name: str) -> str:
    """twimg 图片尺寸变体：支持的路径重写/追加 ?name= 参数，其余返回空串。

    与 TS searchParams.set 语义对齐：已有 name 参数原位覆盖（保留参数顺序），
    没有则追加到末尾；twimg 查询参数全 ASCII，urlencode 无编码分歧。
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.hostname != "pbs.twimg.com" or not TWIMG_VARIANT_PATH_RE.match(parsed.path):
        return ""
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for index, (key, _value) in enumerate(pairs):
        if key == "name":
            pairs[index] = (key, name)
            break
    else:
        pairs.append(("name", name))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), ""))


def _positive_number(value: Any) -> bool:
    # bool 是 int 子类，JSON true 不算尺寸（TS 侧 typeof 同样排除）。
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def photo_box_variant_name(target_width: int, width: Any = None, height: Any = None) -> str:
    """最小的约束框使缩放后宽度 ≥ min(原宽, 目标宽)；与 TS photoBoxVariantName
    逐运算对齐（同一 IEEE 双精度算式），尺寸缺失/非法时按目标宽取框。"""
    if _positive_number(width) and _positive_number(height):
        needed = min(width, target_width) * max(width, height) / width
    else:
        needed = target_width
    for box, name in TWIMG_BOX_VARIANTS:
        if box >= needed:
            return name
    return TWIMG_BOX_VARIANTS[-1][1]


def _media_item_warmup_path(item: Mapping[str, Any]) -> str:
    """单个媒体项的首屏内联渲染路径；不在首屏消费的（mp4 本体、无封面视频的
    抽帧端点）返回空串——后者边缘不可缓存，归 x_poster_backfill 负责。"""
    url = item.get("url")
    if not isinstance(url, str) or not url:
        return ""
    if item.get("type") == "photo":
        # 内联渲染按宽高选约束框变体；变体不可派生时前端回退原图，与渲染层同口径。
        # 非 twimg 图片浏览器直连外站，不经本站代理，无需预热。
        if not is_twimg_url(url):
            return ""
        name = photo_box_variant_name(
            PHOTO_INLINE_TARGET_WIDTH, item.get("width"), item.get("height")
        )
        return proxied_media_url(photo_variant_url(url, name) or url)
    if item.get("type") in _VIDEO_TYPES:
        poster = item.get("poster_url")
        if not isinstance(poster, str) or not poster or not is_twimg_url(poster):
            return ""
        return proxied_media_url(photo_variant_url(poster, "small") or poster)
    return ""


def avatar_variant_url(url: str) -> str:
    """Match the UI's 400px avatar variant, including historical stored URLs."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if parsed.hostname != "pbs.twimg.com" or not parsed.path.startswith("/profile_images/"):
        return url
    path = re.sub(r"_(?:normal|bigger|mini)(\.[a-zA-Z0-9]+)$", r"_400x400\1", parsed.path)
    return urlunsplit(parsed._replace(path=path))


def _append(paths: list[str], url: Any, *, avatar: bool = False) -> None:
    """Proxy allowlisted media; avatar variants must match the UI cache key."""
    if isinstance(url, str) and url and is_twimg_url(url):
        paths.append(proxied_media_url(avatar_variant_url(url) if avatar else url))


def collect_doc_warmup_paths(doc: Mapping[str, Any]) -> list[str]:
    """一条推文文档在 X 看板首屏会真实请求的同源代理路径（未去重）。

    覆盖：作者头像、链接卡片图、照片内联变体、视频/GIF 官方封面 small
    变体，以及引用卡片内的同规则项。mp4 视频本体不预热（点击才播放且整体
    GET 代价大）；无 poster_url 的存量视频归封面回填通道。
    """
    paths: list[str] = []
    _append(paths, doc.get("author_avatar_url"), avatar=True)
    link_card = doc.get("link_card")
    if isinstance(link_card, Mapping):
        _append(paths, link_card.get("image_url"))
    media = doc.get("media")
    if isinstance(media, list):
        for item in media:
            if isinstance(item, Mapping):
                path = _media_item_warmup_path(item)
                if path:
                    paths.append(path)
    quote = doc.get("quote")
    if isinstance(quote, Mapping):
        _append(paths, quote.get("author_avatar_url"), avatar=True)
        quote_media = quote.get("media")
        if isinstance(quote_media, list):
            for item in quote_media:
                if isinstance(item, Mapping):
                    path = _media_item_warmup_path(item)
                    if path:
                        paths.append(path)
    return paths


def collect_warmup_paths(
    docs: Iterable[Mapping[str, Any]], *, max_urls: int
) -> list[str]:
    """跨文档汇总：去重保序（同作者头像跨推复用），截断到 max_urls。"""
    seen: dict[str, None] = {}
    for doc in docs:
        for path in collect_doc_warmup_paths(doc):
            seen.setdefault(path)
            if len(seen) >= max_urls:
                return list(seen)
    return list(seen)


def collect_poster_backfill_candidates(
    docs: Iterable[Mapping[str, Any]],
) -> list[str]:
    """无 poster_url 的存量 video/animated_gif 的 twimg mp4 直链（去重保序）。

    这些视频在前端回退到 /api/media/x/poster?url= 服务端抽帧端点——查询
    形态边缘不可缓存，只能靠磁盘封面缓存预热（见 x_poster_backfill）。
    """
    seen: dict[str, None] = {}

    def _collect(media: Any) -> None:
        if not isinstance(media, list):
            return
        for item in media:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") not in _VIDEO_TYPES:
                continue
            if item.get("poster_url"):
                continue
            url = item.get("url")
            if isinstance(url, str) and url and is_twimg_url(url):
                seen.setdefault(url)

    for doc in docs:
        _collect(doc.get("media"))
        quote = doc.get("quote")
        if isinstance(quote, Mapping):
            _collect(quote.get("media"))
    return list(seen)
