from __future__ import annotations

"""x_media_urls 的契约测试：逐条镜像前端
frontend/src/features/xboard/xBoardViewModel.test.ts 的 URL 形态断言
（权威源）。预热请求的代理路径必须与看板渲染逐字节一致，否则边缘
缓存 key 错位 = 白预热。前端规则变更时本文件与 x_media_urls.py 须同步。
"""

from backend.app.services.x_media_urls import (
    PHOTO_INLINE_TARGET_WIDTH,
    avatar_variant_url,
    collect_doc_warmup_paths,
    collect_poster_backfill_candidates,
    collect_warmup_paths,
    is_twimg_url,
    photo_box_variant_name,
    photo_variant_url,
    proxied_media_url,
)

# 前端 lightbox 目标宽（TS PHOTO_LIGHTBOX_TARGET_WIDTH）；后端只预热内联变体，
# 此处仅为镜像 TS 同表用例、钉住两侧算式一致。
_LIGHTBOX = 2048

# --- is_twimg_url / proxied_media_url --------------------------------------


def test_avatar_variants_match_rendering_and_warmup_for_historical_documents():
    for size in ['normal', 'bigger', 'mini']:
        url = f'https://pbs.twimg.com/profile_images/123/name__{size}.jpg?tag=1'
        expected = 'https://pbs.twimg.com/profile_images/123/name__400x400.jpg?tag=1'
        assert avatar_variant_url(url) == expected
        assert collect_doc_warmup_paths({
            'author_avatar_url': url, 'quote': {'author_avatar_url': url},
        }) == [proxied_media_url(expected)] * 2
    for url in [
        'https://pbs.twimg.com/media/photo_normal.jpg',
        'https://pbs.twimg.com/profile_images/123/name_400x400.png',
        'https://pbs.twimg.com/profile_images/123/name.jpg',
        'https://elsewhere.test/profile_images/123/name_normal.jpg', 'invalid',
    ]:
        assert avatar_variant_url(url) == url


def test_is_twimg_url_whitelist_only() -> None:
    assert is_twimg_url("https://pbs.twimg.com/media/a.jpg")
    assert is_twimg_url("https://video.twimg.com/a.mp4")
    assert is_twimg_url("https://abs.twimg.com/a.png")
    assert not is_twimg_url("https://example.com/media/a.jpg")
    assert not is_twimg_url("https://pbs.twimg.com.evil.com/a.jpg")
    assert not is_twimg_url("not-a-url")
    assert not is_twimg_url("")


def test_proxied_media_url_path_form() -> None:
    # 路径式形态：/api/media/x/img/<host><path>?<query>
    assert proxied_media_url("https://video.twimg.com/a.mp4") == (
        "/api/media/x/img/video.twimg.com/a.mp4"
    )
    assert proxied_media_url("https://pbs.twimg.com/media/a.jpg?format=jpg") == (
        "/api/media/x/img/pbs.twimg.com/media/a.jpg?format=jpg"
    )
    # 非 twimg 原样透传
    assert proxied_media_url("https://example.com/b.jpg") == "https://example.com/b.jpg"


# --- photo_variant_url（镜像 TS 同名用例） ----------------------------------


def test_photo_variant_url_rewrites_name_only_on_supported_paths() -> None:
    assert photo_variant_url("https://pbs.twimg.com/media/a.jpg", "small") == (
        "https://pbs.twimg.com/media/a.jpg?name=small"
    )
    # 已有 name 参数时原位覆盖，其余查询参数保留
    assert photo_variant_url(
        "https://pbs.twimg.com/media/a.jpg?format=jpg&name=large", "small"
    ) == "https://pbs.twimg.com/media/a.jpg?format=jpg&name=small"
    assert photo_variant_url(
        "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg", "small"
    ) == "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg?name=small"
    # 头像/视频文件/外站路径不支持变体（下发只会 404），回退空串
    assert photo_variant_url("https://pbs.twimg.com/profile_images/a.jpg", "small") == ""
    assert photo_variant_url("https://video.twimg.com/a.mp4", "small") == ""
    assert photo_variant_url("https://example.com/media/a.jpg", "small") == ""
    assert photo_variant_url("not-a-url", "small") == ""
    assert photo_variant_url("", "small") == ""


# --- photo_box_variant_name（镜像 TS BOX_VARIANT_CASES 同表） ---------------

BOX_VARIANT_CASES = [
    (PHOTO_INLINE_TARGET_WIDTH, 2048, 1152, "small"),
    (PHOTO_INLINE_TARGET_WIDTH, 2342, 2064, "small"),
    (PHOTO_INLINE_TARGET_WIDTH, 1200, 1200, "small"),
    (PHOTO_INLINE_TARGET_WIDTH, 400, 300, "small"),
    (PHOTO_INLINE_TARGET_WIDTH, 1080, 1350, "900x900"),
    (PHOTO_INLINE_TARGET_WIDTH, 600, 900, "900x900"),
    (PHOTO_INLINE_TARGET_WIDTH, 500, 1300, "large"),
    (PHOTO_INLINE_TARGET_WIDTH, 1170, 2532, "large"),
    (PHOTO_INLINE_TARGET_WIDTH, 1316, 4096, "4096x4096"),
    (PHOTO_INLINE_TARGET_WIDTH, None, None, "small"),
    (PHOTO_INLINE_TARGET_WIDTH, 0, 4096, "small"),
    (_LIGHTBOX, 2048, 1152, "large"),
    (_LIGHTBOX, 3536, 1839, "large"),
    (_LIGHTBOX, 800, 600, "900x900"),
    (_LIGHTBOX, 1080, 1350, "large"),
    (_LIGHTBOX, 1316, 4096, "4096x4096"),
    (_LIGHTBOX, None, None, "large"),
]


def test_photo_box_variant_name_matches_frontend_table() -> None:
    for target, width, height, name in BOX_VARIANT_CASES:
        assert photo_box_variant_name(target, width, height) == name, (target, width, height)
    # JSON true 不算尺寸（TS typeof 同样排除），按目标宽取框
    assert photo_box_variant_name(PHOTO_INLINE_TARGET_WIDTH, True, 4096) == "small"


# --- collect_doc_warmup_paths ----------------------------------------------

_POSTER = "https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg"


def test_collect_photo_thumb_small_variant() -> None:
    doc = {
        "media": [
            {"type": "photo", "url": "https://pbs.twimg.com/media/abc.jpg"},
        ],
    }
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/media/abc.jpg?name=small"
    ]


def test_collect_long_photo_warms_the_box_variant_the_board_renders() -> None:
    # 长图内联升框保宽（镜像 TS 长图用例），预热同一缓存 key
    doc = {
        "media": [
            {
                "type": "photo",
                "url": "https://pbs.twimg.com/media/long.jpg",
                "width": 1316,
                "height": 4096,
            },
        ],
    }
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/media/long.jpg?name=4096x4096"
    ]


def test_collect_photo_without_derivable_variant_falls_back_to_original() -> None:
    # 变体不可派生的照片路径：前端内联渲染回退原图，预热同口径
    doc = {"media": [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]}
    assert collect_doc_warmup_paths(doc) == ["/api/media/x/img/pbs.twimg.com/a.jpg"]


def test_collect_video_with_poster_warms_small_poster_not_mp4() -> None:
    doc = {
        "media": [
            {
                "type": "video",
                "url": "https://video.twimg.com/a.mp4",
                "poster_url": _POSTER,
            },
        ],
    }
    # 只预热封面 small 变体；mp4 本体不进首屏不预热
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=small"
    ]


def test_collect_animated_gif_poster_same_rule() -> None:
    doc = {
        "media": [
            {
                "type": "animated_gif",
                "url": "https://video.twimg.com/g.mp4",
                "poster_url": _POSTER,
            },
        ],
    }
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=small"
    ]


def test_collect_video_without_poster_skipped_in_warmup() -> None:
    # 无 poster_url 的存量视频：前端回退抽帧端点（边缘不可缓存），归封面回填
    doc = {"media": [{"type": "video", "url": "https://video.twimg.com/a.mp4"}]}
    assert collect_doc_warmup_paths(doc) == []
    assert collect_poster_backfill_candidates([doc]) == ["https://video.twimg.com/a.mp4"]


def test_collect_non_twimg_media_skipped() -> None:
    doc = {
        "media": [
            {"type": "photo", "url": "https://elsewhere.cdn/b.jpg"},
            {
                "type": "video",
                "url": "https://elsewhere.cdn/v.mp4",
                "poster_url": "https://elsewhere.cdn/p.jpg",
            },
        ],
    }
    assert collect_doc_warmup_paths(doc) == []
    assert collect_poster_backfill_candidates([doc]) == []


def test_collect_avatar_and_link_card_as_is() -> None:
    doc = {
        "author_avatar_url": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
        "link_card": {
            "url": "https://example.com/a",
            "title": "t",
            "image_url": "https://pbs.twimg.com/card_img/1/c.jpg",
        },
        # 非 twimg 头像不进首屏代理，不预热
    }
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/profile_images/1/a_400x400.jpg",
        "/api/media/x/img/pbs.twimg.com/card_img/1/c.jpg",
    ]


def test_collect_quote_media_and_avatar() -> None:
    doc = {
        "quote": {
            "url": "https://x.com/a/status/1",
            "author_avatar_url": "https://pbs.twimg.com/profile_images/2/q_normal.jpg",
            "media": [
                {"type": "photo", "url": "https://pbs.twimg.com/media/q.jpg"},
                {"type": "video", "url": "https://video.twimg.com/qv.mp4"},
            ],
        },
    }
    assert collect_doc_warmup_paths(doc) == [
        "/api/media/x/img/pbs.twimg.com/profile_images/2/q_400x400.jpg",
        "/api/media/x/img/pbs.twimg.com/media/q.jpg?name=small",
    ]
    assert collect_poster_backfill_candidates([doc]) == [
        "https://video.twimg.com/qv.mp4"
    ]


def test_collect_bad_shapes_tolerated() -> None:
    assert collect_doc_warmup_paths({}) == []
    assert collect_doc_warmup_paths({"media": "not-a-list", "quote": "bad"}) == []
    assert collect_doc_warmup_paths({"media": [{"type": "photo"}, "junk", None]}) == []


def test_collect_warmup_paths_dedupes_and_truncates() -> None:
    avatar = "https://pbs.twimg.com/profile_images/1/a_normal.jpg"
    docs = [
        {"author_avatar_url": avatar, "media": [{"type": "photo", "url": "https://pbs.twimg.com/media/1.jpg"}]},
        {"author_avatar_url": avatar, "media": [{"type": "photo", "url": "https://pbs.twimg.com/media/2.jpg"}]},
    ]
    # 同作者头像跨推去重，保序
    assert collect_warmup_paths(docs, max_urls=10) == [
        "/api/media/x/img/pbs.twimg.com/profile_images/1/a_400x400.jpg",
        "/api/media/x/img/pbs.twimg.com/media/1.jpg?name=small",
        "/api/media/x/img/pbs.twimg.com/media/2.jpg?name=small",
    ]
    assert len(collect_warmup_paths(docs, max_urls=2)) == 2
