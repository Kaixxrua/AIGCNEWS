from __future__ import annotations

"""X/Twitter 采集 transport + policy 契约测试。

模式对齐 test_hackernews_source_contracts.py：
  - unittest.IsolatedAsyncioTestCase
  - fake client（同步方法，经 asyncio.to_thread 调用无需 AsyncMock）
  - 精确 dict 断言投影结果
"""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from twitter_cli.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    TwitterAPIError,
)
from twitter_cli.models import Author, Metrics, Tweet, TweetMedia, UserProfile

from aigcnews_private.sources import x_transport
from backend.app.services.ingestion.crawlers import x_crawler
from backend.app.services.ingestion.sources import x_policy


def _tweet(
    tweet_id: str = "1001",
    *,
    screen_name: str = "openai",
    author_name: str = "OpenAI",
    text: str = "GPT-6 is now available.",
    created_at: str = "Sat Aug 02 16:10:51 +0000 2026",
    likes: int = 10,
    retweets: int = 2,
    replies: int = 1,
    quotes: int = 0,
    views: int = 100,
    bookmarks: int = 3,
    is_retweet: bool = False,
    is_promoted: bool = False,
    is_subscriber_only: bool = False,
) -> Tweet:
    tweet = Tweet(
        id=tweet_id,
        text=text,
        author=Author(id="u1", name=author_name, screen_name=screen_name),
        metrics=Metrics(
            likes=likes,
            retweets=retweets,
            replies=replies,
            quotes=quotes,
            views=views,
            bookmarks=bookmarks,
        ),
        created_at=created_at,
        is_retweet=is_retweet,
    )
    # 0.8.5 的 Tweet 尚无这两个字段（0.8.6-dev 新增），后置赋值模拟；
    # policy 用 getattr 访问，对无字段的旧版对象自然放行
    tweet.is_promoted = is_promoted
    tweet.is_subscriber_only = is_subscriber_only
    return tweet


class XPolicyContracts(unittest.TestCase):
    def test_parse_watch_handles_normalizes_and_dedupes(self) -> None:
        raw = " @OpenAI, sama\nKARPATHY,,openai ,  @SAMA "
        self.assertEqual(
            x_policy.parse_watch_handles(raw),
            ["openai", "sama", "karpathy"],
        )
        self.assertEqual(x_policy.parse_watch_handles(""), [])

    def test_compute_engagement_score_exact_formula(self) -> None:
        # 10 + 3*2 + 2*1 + 5*3 + 0.5*log10(100) = 10+6+2+15+1.0
        score = x_policy.compute_engagement_score(
            likes=10, retweets=2, replies=1, bookmarks=3, views=100
        )
        self.assertAlmostEqual(score, 34.0)
        # views=0 时 log10 取 max(views,1)=1 → 0
        self.assertEqual(x_policy.compute_engagement_score(likes=1, views=0), 1.0)

    def test_parse_tweet_date(self) -> None:
        self.assertEqual(
            x_policy.parse_tweet_date("Sat Aug 02 16:10:51 +0000 2026"),
            "2026-08-02",
        )
        self.assertEqual(x_policy.parse_tweet_date("not a date"), "")
        self.assertEqual(x_policy.parse_tweet_date(""), "")

    def test_project_tweets_filters_sorts_and_projects_exactly(self) -> None:
        tweets = [
            _tweet("1001", text="low score", likes=1, retweets=0, replies=0, bookmarks=0, views=1),
            _tweet("1002", text="high score", likes=10, retweets=2, replies=1, bookmarks=3, views=100),
            _tweet("1003", is_promoted=True, text="ad", likes=99999),
            # 纯转贴自 2026-08-13 起保留（按原贴归属收录），仅推广/订阅专属/空正文被过滤
            _tweet("1004", is_retweet=True, text="rt", likes=0, retweets=0, replies=0, bookmarks=0, views=0),
            _tweet("1005", is_subscriber_only=True, text="sub", likes=99999),
            _tweet("1006", text="", likes=99999),
        ]
        items = x_policy.project_tweets(tweets, limit=10)
        self.assertEqual([item["tweet_id"] for item in items], ["1002", "1001", "1004"])
        self.assertEqual([item["rank_in_period"] for item in items], [1, 2, 3])
        self.assertEqual(
            items[0],
            {
                "title": "high score",
                "url": "https://x.com/openai/status/1002",
                "abstract": "high score",
                "summary": "high score",
                "source": "x",
                "source_channel": "x_daily_watchlist",
                "channel": "x_daily_watchlist",
                "score": 34.0,
                "raw_score": 34.0,
                "likes": 10,
                "retweets": 2,
                "replies": 1,
                "quotes": 0,
                "views": 100,
                "bookmarks": 3,
                "published_at": "2026-08-02T16:10:51+00:00",
                "published_date": "2026-08-02",
                "tweet_id": "1002",
                "author": "openai",
                "author_name": "OpenAI",
                "author_avatar_url": "",
                "rank_in_period": 1,
                "tags": ["x", "daily", "openai"],
                "media": [],
                "quote": None,
                "link_card": None,
            },
        )

    def test_project_tweets_keeps_retweet_attributed_to_original(self) -> None:
        # 纯转贴保留：parser 已把 id/作者/正文/指标换为被转原贴，条目按原贴归属入库
        rt = _tweet(
            "2001", screen_name="originalauthor", author_name="Original Author",
            text="original content", likes=50, is_retweet=True,
        )
        items = x_policy.project_tweets([rt], limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://x.com/originalauthor/status/2001")
        self.assertEqual(items[0]["author"], "originalauthor")
        self.assertEqual(items[0]["tags"], ["x", "daily", "originalauthor"])

    def test_project_tweets_dedupes_same_original_across_accounts(self) -> None:
        # 多账号转同一贴（或账号转自己旧贴）：原贴 id 相同，仅保留一条，不占截断名额
        rt_a = _tweet("3001", text="same original", likes=10, is_retweet=True)
        rt_b = _tweet("3001", text="same original", likes=10, is_retweet=True)
        unique = _tweet("3002", text="unique", likes=5)
        items = x_policy.project_tweets([rt_a, rt_b, unique], limit=10)
        self.assertEqual([item["tweet_id"] for item in items], ["3001", "3002"])

    def test_project_tweets_extracts_avatar_url(self) -> None:
        tweet = _tweet("1010", text="avatar")
        tweet.author.profile_image_url = "https://pbs.twimg.com/profile_images/a.jpg"
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(items[0]["author_avatar_url"], "https://pbs.twimg.com/profile_images/a.jpg")

    def test_project_tweets_extracts_published_at(self) -> None:
        items = x_policy.project_tweets(
            [_tweet("1011", text="ts", created_at="Sun Aug 03 08:30:00 +0000 2026")], limit=5
        )
        self.assertEqual(items[0]["published_at"], "2026-08-03T08:30:00+00:00")
        self.assertEqual(items[0]["published_date"], "2026-08-03")

    def test_project_tweets_extracts_media_metadata(self) -> None:
        tweet = _tweet("1008", text="with media")
        tweet.media = [
            TweetMedia(type="photo", url="https://pbs.twimg.com/media/a.jpg", width=1200, height=800),
            TweetMedia(type="video", url="https://video.twimg.com/b.mp4", width=640, height=360),
        ]
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["media"],
            [
                {"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg", "width": 1200, "height": 800},
                {"type": "video", "url": "https://video.twimg.com/b.mp4", "width": 640, "height": 360},
            ],
        )

    def test_project_tweets_skips_media_without_url(self) -> None:
        tweet = _tweet("1009", text="empty media")
        tweet.media = [TweetMedia(type="photo", url="", width=0, height=0)]
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(items[0]["media"], [])

    def test_project_tweets_projects_quoted_tweet_card(self) -> None:
        tweet = _tweet("2001", text="going live")
        quoted = _tweet(
            "2000",
            screen_name="comfyui",
            author_name="ComfyUI",
            # 媒体推：正文链接在中部，尾部 t.co 是媒体尾巴（X 真实形状）
            text="Livestream update https://t.co/abc123 see you https://t.co/med9",
            created_at="Fri Aug 07 01:00:00 +0000 2026",
        )
        quoted.media = [
            TweetMedia(type="photo", url="https://pbs.twimg.com/media/q.jpg", width=800, height=450)
        ]
        quoted.urls = ["https://example.com/live"]
        quoted.author.profile_image_url = "https://pbs.twimg.com/profile_images/q.jpg"
        tweet.quoted_tweet = quoted
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(
            items[0]["quote"],
            {
                "url": "https://x.com/comfyui/status/2000",
                "author": "comfyui",
                "author_name": "ComfyUI",
                "author_avatar_url": "https://pbs.twimg.com/profile_images/q.jpg",
                "text": "Livestream update https://example.com/live see you",
                "media": [
                    {
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/q.jpg",
                        "width": 800,
                        "height": 450,
                    }
                ],
                "published_at": "2026-08-07T01:00:00+00:00",
            },
        )

    def test_project_tweets_quoted_media_tail_is_stripped(self) -> None:
        tweet = _tweet("2002", text="quote with media")
        quoted = _tweet("2003", text="look at this https://t.co/xyz789")
        quoted.media = [
            TweetMedia(type="photo", url="https://pbs.twimg.com/media/m.jpg", width=1, height=1)
        ]
        tweet.quoted_tweet = quoted
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(items[0]["quote"]["text"], "look at this")

    def test_project_tweets_quote_none_or_unusable(self) -> None:
        # 无引用 → None
        self.assertIsNone(x_policy.project_tweets([_tweet("2010")], limit=5)[0]["quote"])
        # 引用缺 id → None（无法构成卡片链接）
        tweet = _tweet("2011", text="q")
        tweet.quoted_tweet = _tweet("", text="no id")
        self.assertIsNone(x_policy.project_tweets([tweet], limit=5)[0]["quote"])
        # 引用既无正文又无媒体 → None（渲染层无可展示内容）
        tweet2 = _tweet("2012", text="q")
        tweet2.quoted_tweet = _tweet("2013", text="")
        self.assertIsNone(x_policy.project_tweets([tweet2], limit=5)[0]["quote"])
        # 引用仅媒体无正文仍可成卡
        tweet3 = _tweet("2014", text="q")
        media_only = _tweet("2015", text="")
        media_only.media = [
            TweetMedia(type="photo", url="https://pbs.twimg.com/media/only.jpg", width=1, height=1)
        ]
        tweet3.quoted_tweet = media_only
        quote = x_policy.project_tweets([tweet3], limit=5)[0]["quote"]
        self.assertEqual(quote["text"], "")
        self.assertEqual(len(quote["media"]), 1)

    def test_project_tweets_media_includes_poster_url_when_present(self) -> None:
        tweet = _tweet("1010", text="video with poster")
        video = TweetMedia(
            type="video", url="https://video.twimg.com/b.mp4", width=640, height=360
        )
        # 与 x_transport 封面补丁同一姿势：无 slots dataclass 后置赋值
        video.poster_url = "https://pbs.twimg.com/amplify_video_thumb/b.jpg"
        photo = TweetMedia(
            type="photo", url="https://pbs.twimg.com/media/a.jpg", width=1, height=1
        )
        tweet.media = [video, photo]
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(
            items[0]["media"],
            [
                {
                    "type": "video",
                    "url": "https://video.twimg.com/b.mp4",
                    "width": 640,
                    "height": 360,
                    "poster_url": "https://pbs.twimg.com/amplify_video_thumb/b.jpg",
                },
                # 照片无 poster_url 属性 → 不带该键，旧形状不变
                {
                    "type": "photo",
                    "url": "https://pbs.twimg.com/media/a.jpg",
                    "width": 1,
                    "height": 1,
                },
            ],
        )

    def test_project_tweets_preserves_full_text(self) -> None:
        long_text = "line one\n" + "x" * 200
        tweets = [
            _tweet(str(2000 + i), text=long_text, likes=i)
            for i in range(5)
        ]
        items = x_policy.project_tweets(tweets, limit=3)
        self.assertEqual(len(items), 3)
        # 按 likes 降序（其余指标为 0，log10(max(1,1))=0）
        self.assertEqual([item["likes"] for item in items], [4, 3, 2])
        for item in items:
            # 标题折叠空白但不截断，summary 保留原文
            self.assertNotIn("\n", item["title"])
            self.assertEqual(len(item["title"]), len(long_text.replace("\n", " ")))
        # 全文保留在 summary/abstract
        self.assertEqual(items[0]["summary"], long_text)

    def test_project_tweets_bad_date_kept_with_empty_published_date(self) -> None:
        items = x_policy.project_tweets(
            [_tweet("1007", created_at="garbage")], limit=5
        )
        self.assertEqual(items[0]["published_date"], "")

    def test_project_tweets_projects_link_card(self) -> None:
        tweet = _tweet("3001", text="watch https://t.co/abc123")
        # 与 x_transport 卡片补丁同一姿势：无 slots dataclass 后置赋值
        tweet.link_card = {
            "url": "https://www.youtube.com/watch?v=S9O3FPumX4Q",
            "title": "MiniMax H3: A New Open-Weight Video Model",
            "description": "MiniMax H3 is an open-weight video model",
            "domain": "youtube.com",
            "image_url": "https://pbs.twimg.com/card_img/2085/orig.jpg",
            "image_width": 1280,
            "image_height": 720,
            "card_type": "player",
        }
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(
            items[0]["link_card"],
            {
                "url": "https://www.youtube.com/watch?v=S9O3FPumX4Q",
                "title": "MiniMax H3: A New Open-Weight Video Model",
                "description": "MiniMax H3 is an open-weight video model",
                "domain": "youtube.com",
                "image_url": "https://pbs.twimg.com/card_img/2085/orig.jpg",
                "image_width": 1280,
                "image_height": 720,
                "card_type": "player",
            },
        )

    def test_project_tweets_link_card_none_or_unusable(self) -> None:
        # 无卡 → None
        self.assertIsNone(
            x_policy.project_tweets([_tweet("3010")], limit=5)[0]["link_card"]
        )
        # 缺 title → None（无可看内容）
        tweet = _tweet("3011")
        tweet.link_card = {"url": "https://example.com/x", "title": ""}
        self.assertIsNone(x_policy.project_tweets([tweet], limit=5)[0]["link_card"])
        # 缺 url → None（卡片无法跳转）
        tweet2 = _tweet("3012")
        tweet2.link_card = {"url": " ", "title": "has title"}
        self.assertIsNone(x_policy.project_tweets([tweet2], limit=5)[0]["link_card"])
        # 非 dict（防御坏数据）→ None
        tweet3 = _tweet("3013")
        tweet3.link_card = "not-a-dict"
        self.assertIsNone(x_policy.project_tweets([tweet3], limit=5)[0]["link_card"])

    def test_project_tweets_link_card_without_image_degrades_to_text_card(self) -> None:
        tweet = _tweet("3014")
        tweet.link_card = {
            "url": "https://example.com/blog",
            "title": "Text only card",
            "description": "",
            "domain": "example.com",
            "image_url": "",
            "image_width": None,
            "image_height": None,
            "card_type": "summary",
        }
        card = x_policy.project_tweets([tweet], limit=5)[0]["link_card"]
        # 缩略图缺失不阻断成卡：image_url 归一为 None，由渲染层降级为纯文本卡
        self.assertIsNone(card["image_url"])
        self.assertEqual(card["title"], "Text only card")

    def test_filter_tweets_to_snapshot_date_keeps_only_cst_same_day(self) -> None:
        tweets = [
            # UTC 08-03 16:30 = CST 08-04 00:30（当天，保留）
            _tweet("2001", created_at="Mon Aug 03 16:30:00 +0000 2026"),
            # UTC 08-04 15:59:59 = CST 08-04 23:59:59（当天边界，保留）
            _tweet("2002", created_at="Tue Aug 04 15:59:59 +0000 2026"),
            # UTC 08-04 16:00 = CST 08-05 00:00（次日，剔除）
            _tweet("2003", created_at="Tue Aug 04 16:00:00 +0000 2026"),
            # UTC 08-03 15:59 = CST 08-03 23:59（前一日，剔除）
            _tweet("2004", created_at="Mon Aug 03 15:59:00 +0000 2026"),
            # 更早的旧推文（剔除）
            _tweet("2005", created_at="Sat Aug 01 12:00:00 +0000 2026"),
        ]
        kept = x_policy.filter_tweets_to_snapshot_date(tweets, "2026-08-04")
        self.assertEqual([str(t.id) for t in kept], ["2001", "2002"])

    def test_filter_tweets_to_snapshot_date_drops_unparseable_dates(self) -> None:
        tweets = [
            _tweet("2006", created_at="garbage"),
            _tweet("2007", created_at=""),
            _tweet("2008", created_at="Tue Aug 04 02:00:00 +0000 2026"),
        ]
        kept = x_policy.filter_tweets_to_snapshot_date(tweets, "2026-08-04")
        self.assertEqual([str(t.id) for t in kept], ["2008"])

    def test_filter_tweets_to_snapshot_date_empty_date_passes_through(self) -> None:
        tweets = [_tweet("2009"), _tweet("2010")]
        kept = x_policy.filter_tweets_to_snapshot_date(tweets, "")
        self.assertEqual(len(kept), 2)

    def test_clean_display_text_strips_media_tco_tail_only_with_media(self) -> None:
        text = "look at this https://t.co/AbCdEf"
        media = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
        self.assertEqual(x_policy.clean_tweet_display_text(text, media, []), "look at this")
        # 无媒体时尾部 t.co 是普通链接，保留
        self.assertEqual(x_policy.clean_tweet_display_text(text, [], []), text)

    def test_clean_display_text_expands_tco_positionally(self) -> None:
        text = "read https://t.co/LinkOne and https://t.co/LinkTwo now https://t.co/MediaTail"
        media = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
        urls = ["https://openai.com/a", "https://example.org/b"]
        out = x_policy.clean_tweet_display_text(text, media, urls)
        self.assertEqual(out, "read https://openai.com/a and https://example.org/b now")

    def test_clean_display_text_keeps_unpaired_tco_when_urls_short(self) -> None:
        text = "see https://t.co/One or https://t.co/Two"
        out = x_policy.clean_tweet_display_text(text, [], ["https://openai.com/a"])
        # 数量不齐：能配对的展开，未配对的原样保留 t.co，不静默丢链接
        self.assertEqual(out, "see https://openai.com/a or https://t.co/Two")

    def test_decode_tweet_html_entities(self) -> None:
        # X 对 & < > 的转义随端点/条目不一致，统一解码还原页面显示文本
        self.assertEqual(
            x_policy.decode_tweet_html_entities(
                "Plus &amp; Pro &lt;beta&gt; &quot;q&quot; &#39;s"
            ),
            "Plus & Pro <beta> \"q\" 's",
        )
        self.assertEqual(x_policy.decode_tweet_html_entities(""), "")
        # 非实体片段原样保留，不误判
        self.assertEqual(x_policy.decode_tweet_html_entities("R&D <3"), "R&D <3")

    def test_clean_display_text_decodes_html_entities(self) -> None:
        # 实体解码在最前，t.co 位置配对展开不受影响
        text = "Codex &amp; ChatGPT desktop https://t.co/LinkOne"
        out = x_policy.clean_tweet_display_text(text, [], ["https://openai.com/codex"])
        self.assertEqual(out, "Codex & ChatGPT desktop https://openai.com/codex")

    def test_project_tweets_stores_cleaned_display_text(self) -> None:
        tweet = _tweet("1015", text="new model https://t.co/Post https://t.co/MediaTail")
        tweet.media = [TweetMedia(type="photo", url="https://pbs.twimg.com/a.jpg", width=1, height=1)]
        tweet.urls = ["https://openai.com/index/new-model/"]
        items = x_policy.project_tweets([tweet], limit=5)
        self.assertEqual(items[0]["summary"], "new model https://openai.com/index/new-model/")
        self.assertEqual(items[0]["title"], "new model https://openai.com/index/new-model/")

    def test_restore_translation_urls_appends_missing_links(self) -> None:
        source = "More info on eligibility: https://t.co/jzWCbyaIdg"
        out = x_policy.restore_translation_urls(
            "更多资格信息：", source, [], ["https://gemini.google/eligibility"]
        )
        self.assertEqual(out, "更多资格信息：\nhttps://gemini.google/eligibility")

    def test_restore_translation_urls_skips_links_present_in_translation(self) -> None:
        source = "read https://t.co/One and https://t.co/Two"
        urls = ["https://openai.com/a", "https://example.org/b"]
        # 译文保留 t.co 形态 → 不补；另一个被剥 → 补展开式
        out = x_policy.restore_translation_urls(
            "阅读 https://t.co/One 与另一篇", source, [], urls
        )
        self.assertEqual(out, "阅读 https://t.co/One 与另一篇\nhttps://example.org/b")
        # 译文含展开式 → 也不重复补
        out2 = x_policy.restore_translation_urls(
            "阅读 https://openai.com/a 与 https://example.org/b", source, [], urls
        )
        self.assertEqual(out2, "阅读 https://openai.com/a 与 https://example.org/b")

    def test_restore_translation_urls_never_appends_media_tail(self) -> None:
        source = "好看 https://t.co/MediaTail"
        media = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
        out = x_policy.restore_translation_urls("好看", source, media, [])
        self.assertEqual(out, "好看")

    def test_restore_translation_mentions_prepends_dropped_reply_prefix(self) -> None:
        out = x_policy.restore_translation_mentions(
            "请在此处回复：", "@VictorSuOrtiz @alexinexxx RSVP here:"
        )
        self.assertEqual(out, "@VictorSuOrtiz @alexinexxx 请在此处回复：")

    def test_restore_translation_mentions_skips_when_translation_keeps_prefix(self) -> None:
        # 译文已带同一前缀（X 偶发保留）不重复补
        out = x_policy.restore_translation_mentions(
            "@GoogleDeepMind 团队分享幕后", "@GoogleDeepMind behind the scenes"
        )
        self.assertEqual(out, "@GoogleDeepMind 团队分享幕后")

    def test_restore_translation_mentions_ignores_inline_mentions(self) -> None:
        # 行内提及不是回复前缀，X 译文保留；即使丢失也不追加（会破坏语序）
        out = x_policy.restore_translation_mentions(
            "机器人应该能打鸡蛋吗？", "Should robots crack eggs @GoogleDeepMind?"
        )
        self.assertEqual(out, "机器人应该能打鸡蛋吗？")

    def test_restore_translation_mentions_empty_inputs(self) -> None:
        self.assertEqual(x_policy.restore_translation_mentions("", "@a hi"), "")
        self.assertEqual(x_policy.restore_translation_mentions("你好", ""), "你好")


class _FakeClient:
    """同步 fake：transport 经 asyncio.to_thread 调用，Mock 即可。"""

    def __init__(self) -> None:
        self.fetch_user = Mock()
        self.fetch_user_tweets = Mock()


class XTransportContracts(unittest.IsolatedAsyncioTestCase):
    def _transport(self, client: _FakeClient, **kwargs) -> x_transport.XTransport:
        kwargs.setdefault("inter_account_delay", 1.0)
        kwargs.setdefault("id_cache", {})
        kwargs.setdefault("sleep", AsyncMock())
        return x_transport.XTransport(lambda: client, **kwargs)

    async def test_sequential_fetch_with_delay_and_id_cache(self) -> None:
        client = _FakeClient()
        client.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Karpathy", screen_name="karpathy"),
        ]
        client.fetch_user_tweets.side_effect = [
            [_tweet("a1", screen_name="openai")],
            [_tweet("b1", screen_name="karpathy")],
        ]
        sleep = AsyncMock()
        transport = self._transport(client, sleep=sleep)

        result = await transport.fetch_watchlist_tweets(
            ["openai", "karpathy"], count_per_user=5
        )

        self.assertEqual([t.id for t in result["openai"]], ["a1"])
        self.assertEqual([t.id for t in result["karpathy"]], ["b1"])
        client.fetch_user.assert_has_calls(
            [unittest.mock.call("openai"), unittest.mock.call("karpathy")]
        )
        client.fetch_user_tweets.assert_has_calls(
            [unittest.mock.call("11", 5), unittest.mock.call("22", 5)]
        )
        # 两个账号之间恰好一次延迟，且带抖动（基线 1.0 × [0.8, 1.6)）
        sleep.assert_awaited_once()
        delay = sleep.await_args.args[0]
        self.assertGreaterEqual(delay, 0.8)
        self.assertLess(delay, 1.6)

        # 第二轮命中 user_id 缓存：不再调 fetch_user
        client.fetch_user.reset_mock()
        client.fetch_user_tweets.side_effect = [[_tweet("a2")], [_tweet("b2")]]
        await transport.fetch_watchlist_tweets(["openai", "karpathy"])
        client.fetch_user.assert_not_called()

    async def test_auth_error_aborts_whole_run(self) -> None:
        client = _FakeClient()
        client.fetch_user.side_effect = AuthenticationError("expired")
        transport = self._transport(client)

        with self.assertRaises(x_transport.XAuthAbort) as ctx:
            await transport.fetch_watchlist_tweets(["openai", "karpathy"])

        self.assertIn("x_auth_expired", str(ctx.exception))
        # 中止：第二个账号不再请求，推文接口从未调用
        self.assertEqual(client.fetch_user.call_count, 1)
        client.fetch_user_tweets.assert_not_called()

    async def test_rate_limit_aborts_whole_run(self) -> None:
        client = _FakeClient()
        client.fetch_user.return_value = UserProfile(
            id="11", name="OpenAI", screen_name="openai"
        )
        client.fetch_user_tweets.side_effect = RateLimitError("429")
        transport = self._transport(client)

        with self.assertRaises(x_transport.XRateLimitAbort) as ctx:
            await transport.fetch_watchlist_tweets(["openai", "karpathy"])

        self.assertIn("x_rate_limited", str(ctx.exception))
        self.assertEqual(client.fetch_user_tweets.call_count, 1)

    async def test_not_found_and_generic_errors_skip_handle(self) -> None:
        client = _FakeClient()
        client.fetch_user.side_effect = [
            NotFoundError("suspended"),
            UserProfile(id="22", name="Karpathy", screen_name="karpathy"),
            UserProfile(id="33", name="Sama", screen_name="sama"),
        ]
        client.fetch_user_tweets.side_effect = [
            [_tweet("b1", screen_name="karpathy")],
            RuntimeError("boom"),
        ]
        transport = self._transport(client)

        result = await transport.fetch_watchlist_tweets(
            ["ghost", "karpathy", "sama"]
        )

        self.assertNotIn("ghost", result)  # NotFound → 跳过
        self.assertEqual([t.id for t in result["karpathy"]], ["b1"])
        self.assertNotIn("sama", result)  # 其他异常 → 跳过

    async def test_twitter_api_429_skips_account_but_keeps_partial_coverage(self) -> None:
        """twitter-cli 把 429 包成 TwitterAPIError（内部退避后仍限流）。

        部分账号限流时跳过该账号、保住本轮其余覆盖（生产观测：部分
        限流轮仍能收到 7/12）；不升级为中止。
        """
        client = _FakeClient()
        client.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Kimi", screen_name="kimi_moonshot"),
        ]
        client.fetch_user_tweets.side_effect = [
            TwitterAPIError(429, "Rate limited after 3 retries"),
            [_tweet("k1", screen_name="kimi_moonshot")],
        ]
        transport = self._transport(client)

        result = await transport.fetch_watchlist_tweets(
            ["openai", "kimi_moonshot"], count_per_user=5
        )

        self.assertNotIn("openai", result)
        self.assertEqual([t.id for t in result["kimi_moonshot"]], ["k1"])
        self.assertEqual(client.fetch_user_tweets.call_count, 2)

    async def test_all_accounts_429_raises_rate_limit_abort(self) -> None:
        """整轮零成功且发生限流 → XRateLimitAbort（不让限流静默成空结果）。"""
        client = _FakeClient()
        client.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Kimi", screen_name="kimi_moonshot"),
        ]
        client.fetch_user_tweets.side_effect = TwitterAPIError(
            429, "Rate limited after 3 retries"
        )
        transport = self._transport(client)

        with self.assertRaises(x_transport.XRateLimitAbort) as ctx:
            await transport.fetch_watchlist_tweets(["openai", "kimi_moonshot"])

        self.assertIn("x_rate_limited", str(ctx.exception))

    async def test_all_accounts_network_failure_raises_transport_unavailable(self) -> None:
        """整轮零成功且为系统性故障（HTTP 0 代理断连）→ XTransportUnavailable。

        2026-08-09 教训：代理断连 16.5h、199 轮以「空结果成功」静默收场，
        调度失败面完全无感知。
        """
        client = _FakeClient()
        client.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Kimi", screen_name="kimi_moonshot"),
        ]
        client.fetch_user_tweets.side_effect = TwitterAPIError(
            0, "Twitter API network error: curl: (7) Could not connect"
        )
        transport = self._transport(client)

        with self.assertRaises(x_transport.XTransportUnavailable) as ctx:
            await transport.fetch_watchlist_tweets(["openai", "kimi_moonshot"])

        self.assertIn("x_transport_unavailable", str(ctx.exception))

    async def test_all_accounts_not_found_returns_empty_without_alarm(self) -> None:
        """全部账号 NotFound（集体消失）非基础设施故障：返回空表不上抛。

        单账号探测路径依赖此契约输出「handle 不存在」友好提示。
        """
        client = _FakeClient()
        client.fetch_user.side_effect = NotFoundError("suspended")
        transport = self._transport(client)

        result = await transport.fetch_watchlist_tweets(["ghost"])

        self.assertEqual(result, {})

    async def test_mixed_not_found_and_network_zero_success_raises(self) -> None:
        """零成功轮中存在系统性故障（即使混有 NotFound）→ XTransportUnavailable。"""
        client = _FakeClient()
        client.fetch_user.side_effect = [
            NotFoundError("suspended"),
            UserProfile(id="22", name="Kimi", screen_name="kimi_moonshot"),
        ]
        client.fetch_user_tweets.side_effect = TwitterAPIError(
            0, "Twitter API network error"
        )
        transport = self._transport(client)

        with self.assertRaises(x_transport.XTransportUnavailable):
            await transport.fetch_watchlist_tweets(["ghost", "kimi_moonshot"])

    async def test_partial_network_failure_keeps_partial_result(self) -> None:
        """部分账号网络故障：跳过故障账号，返回成功账号，不上抛。"""
        client = _FakeClient()
        client.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Kimi", screen_name="kimi_moonshot"),
        ]
        client.fetch_user_tweets.side_effect = [
            TwitterAPIError(0, "Twitter API network error"),
            [_tweet("k1", screen_name="kimi_moonshot")],
        ]
        transport = self._transport(client)

        result = await transport.fetch_watchlist_tweets(["openai", "kimi_moonshot"])

        self.assertNotIn("openai", result)
        self.assertEqual([t.id for t in result["kimi_moonshot"]], ["k1"])

    async def test_auth_fallback_retries_complete_generator_watchlist(self) -> None:
        primary = _FakeClient()
        primary.fetch_user.side_effect = [
            UserProfile(id="11", name="OpenAI", screen_name="openai"),
            UserProfile(id="22", name="Karpathy", screen_name="karpathy"),
        ]
        primary.fetch_user_tweets.side_effect = [
            [_tweet("primary-partial", screen_name="openai")],
            AuthenticationError("expired"),
        ]
        backup = _FakeClient()
        backup.fetch_user_tweets.side_effect = [
            [_tweet("backup-openai", screen_name="openai")],
            [_tweet("backup-karpathy", screen_name="karpathy")],
        ]
        factory = Mock(side_effect=[primary, backup])
        transport = x_transport.XTransport(
            credential_provider=lambda: [
                {"display_name": "primary", "auth_token": "auth-1", "ct0": "ct0-1", "enabled": True},
                {"display_name": "backup", "auth_token": "auth-2", "ct0": "ct0-2", "enabled": True},
            ],
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        result = await transport.fetch_watchlist_tweets(
            (handle for handle in ("openai", "karpathy")),
            count_per_user=5,
        )

        self.assertEqual([tweet.id for tweet in result["openai"]], ["backup-openai"])
        self.assertEqual([tweet.id for tweet in result["karpathy"]], ["backup-karpathy"])
        self.assertNotIn("primary-partial", [tweet.id for tweets in result.values() for tweet in tweets])
        self.assertEqual(factory.call_args_list, [
            unittest.mock.call("auth-1", "ct0-1"),
            unittest.mock.call("auth-2", "ct0-2"),
        ])
        backup.fetch_user_tweets.assert_has_calls([
            unittest.mock.call("11", 5),
            unittest.mock.call("22", 5),
        ])

    async def test_rate_limit_does_not_rotate_to_backup_credential(self) -> None:
        primary = _FakeClient()
        primary.fetch_user.return_value = UserProfile(
            id="11", name="OpenAI", screen_name="openai"
        )
        primary.fetch_user_tweets.side_effect = RateLimitError("429")
        backup = _FakeClient()
        factory = Mock(side_effect=[primary, backup])
        transport = x_transport.XTransport(
            credential_provider=lambda: [
                {"auth_token": "auth-1", "ct0": "ct0-1", "enabled": True},
                {"auth_token": "auth-2", "ct0": "ct0-2", "enabled": True},
            ],
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        with self.assertRaisesRegex(x_transport.XRateLimitAbort, "x_rate_limited"):
            await transport.fetch_watchlist_tweets(["openai"])

        factory.assert_called_once_with("auth-1", "ct0-1")
        backup.fetch_user.assert_not_called()
        backup.fetch_user_tweets.assert_not_called()

    async def test_all_auth_failures_raise_stable_pool_marker(self) -> None:
        clients = [_FakeClient(), _FakeClient()]
        for client in clients:
            client.fetch_user.side_effect = AuthenticationError("secret-bearing failure")
        transport = x_transport.XTransport(
            credential_provider=lambda: [
                {"auth_token": "auth-1", "ct0": "ct0-1", "enabled": True},
                {"auth_token": "auth-2", "ct0": "ct0-2", "enabled": True},
            ],
            credential_factory=Mock(side_effect=clients),
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        with self.assertRaisesRegex(
            x_transport.XAuthAbort,
            "^x_auth_all_credentials_failed$",
        ):
            await transport.fetch_watchlist_tweets(["openai"])

    async def test_default_factory_requires_credentials(self) -> None:
        transport = x_transport.XTransport()  # 默认工厂
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(x_transport.XAuthNotConfigured) as ctx:
                await transport.fetch_watchlist_tweets(["openai"])
        self.assertIn("x_auth_not_configured", str(ctx.exception))

    async def test_default_factory_constructs_client_from_env(self) -> None:
        transport = x_transport.XTransport()
        env = {"TWITTER_AUTH_TOKEN": " tok ", "TWITTER_CT0": " ct0 "}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("twitter_cli.client.TwitterClient") as client_type,
        ):
            client_type.return_value.fetch_user.side_effect = NotFoundError(
                "stop here"
            )
            await transport.fetch_watchlist_tweets(["openai"])
        client_type.assert_called_once_with("tok", "ct0")


class _FakeTransport:
    """crawler 测试用 fake transport（async 方法）。"""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result if result is not None else {}
        self._error = error
        self.calls: list[tuple] = []

    async def fetch_watchlist_tweets(self, handles, count_per_user):
        self.calls.append((list(handles), count_per_user))
        if self._error is not None:
            raise self._error
        return self._result


class XCrawlerContracts(unittest.IsolatedAsyncioTestCase):
    def _crawler(self, transport, handles=("openai",)):
        from backend.app.services.ingestion.crawlers import x_crawler

        return x_crawler.XCrawler(
            transport=transport,
            watchlist_provider=lambda: list(handles),
            tweets_per_account=7,
        )

    async def test_fetch_projects_tweets_with_fixed_channel_and_snapshot(self) -> None:
        from backend.app.services.ingestion.crawlers import x_crawler

        transport = _FakeTransport(
            result={"openai": [_tweet("1002", created_at="Tue Aug 04 02:10:51 +0000 2026", likes=10, retweets=2, replies=1, bookmarks=3, views=100)]}
        )
        crawler = self._crawler(transport)

        with patch.object(x_crawler, "today_cst", return_value="2026-08-04"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(transport.calls, [(["openai"], 7)])
        self.assertIsNone(result.error)
        self.assertEqual(result.source, "x")
        self.assertEqual(result.source_channel, "x_daily_watchlist")
        self.assertEqual(result.snapshot_date, "2026-08-04")
        self.assertEqual(result.period, "daily")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["tweet_id"], "1002")
        self.assertEqual(result.items[0]["source"], "x")
        self.assertEqual(result.items[0]["source_channel"], "x_daily_watchlist")
        self.assertEqual(result.items[0]["channel"], "x_daily_watchlist")

    async def test_fetch_filters_tweets_to_snapshot_date(self) -> None:
        from backend.app.services.ingestion.crawlers import x_crawler

        transport = _FakeTransport(
            result={
                "openai": [
                    # 当天（CST 08-04）
                    _tweet("3001", created_at="Tue Aug 04 02:10:51 +0000 2026", likes=1),
                    # 高分但发布于数周前——不得混入当天快照
                    _tweet("3002", created_at="Sat Jul 18 12:00:00 +0000 2026", likes=99999),
                    # CST 边界：UTC 08-04 16:00 已是 CST 08-05
                    _tweet("3003", created_at="Tue Aug 04 16:00:00 +0000 2026", likes=99999),
                ]
            }
        )
        crawler = self._crawler(transport)

        with patch.object(x_crawler, "today_cst", return_value="2026-08-04"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertIsNone(result.error)
        self.assertEqual([item["tweet_id"] for item in result.items], ["3001"])

    async def test_empty_watchlist_returns_ok_zero_items(self) -> None:
        transport = _FakeTransport()
        crawler = self._crawler(transport, handles=())

        result = await crawler._do_fetch(period="daily", limit=25)

        self.assertIsNone(result.error)
        self.assertEqual(result.items, [])
        self.assertEqual(transport.calls, [])  # 未触碰 transport

    async def test_auth_failures_become_error_result_with_channel(self) -> None:
        for error, marker in (
            (x_transport.XAuthNotConfigured("x_auth_not_configured: set ..."), "x_auth_not_configured"),
            (x_transport.XAuthAbort("x_auth_expired: dead cookie"), "x_auth_expired"),
            (x_transport.XRateLimitAbort("x_rate_limited: 429"), "x_rate_limited"),
            (x_transport.XTransportUnavailable("x_transport_unavailable"), "x_transport_unavailable"),
        ):
            with self.subTest(marker=marker):
                crawler = self._crawler(_FakeTransport(error=error))
                result = await crawler._do_fetch(period="daily", limit=25)
                self.assertEqual(result.items, [])
                self.assertEqual(result.source_channel, "x_daily_watchlist")
                self.assertIn(marker, result.error)

    async def test_env_driven_defaults_for_count_delay_and_watchlist(self) -> None:
        from backend.app.core.config import settings
        from backend.app.services.ingestion.crawlers import x_crawler

        # 无注入 transport 时 XCrawler 经 loader 构造真实 XTransport：需开关开启
        with patch.object(settings, "x_source_enabled", True):
            env = {
                "TWITTER_WATCH_HANDLES": " @OpenAI, karpathy ",
                "TWITTER_TWEETS_PER_ACCOUNT": "33",
                "TWITTER_INTER_ACCOUNT_DELAY_SECONDS": "9.5",
            }
            with patch.dict("os.environ", env, clear=True):
                crawler = x_crawler.XCrawler()
                # watchlist 惰性读取：每次 fetch 时取最新 env
                watchlist = crawler._watchlist_provider()

            self.assertEqual(crawler._tweets_per_account, 33)
            self.assertEqual(crawler._transport._inter_account_delay, 9.5)
            self.assertEqual(watchlist, ["openai", "karpathy"])

            # 缺省/非法值回落常量默认
            with patch.dict("os.environ", {}, clear=True):
                crawler = x_crawler.XCrawler()
                empty_watchlist = crawler._watchlist_provider()
            self.assertEqual(
                crawler._tweets_per_account, x_crawler.DEFAULT_TWEETS_PER_ACCOUNT
            )
            self.assertEqual(
                crawler._transport._inter_account_delay,
                x_transport.DEFAULT_INTER_ACCOUNT_DELAY,
            )
            self.assertEqual(empty_watchlist, [])

            bad_env = {
                "TWITTER_TWEETS_PER_ACCOUNT": "abc",
                "TWITTER_INTER_ACCOUNT_DELAY_SECONDS": "-1",
            }
            with patch.dict("os.environ", bad_env, clear=True):
                crawler = x_crawler.XCrawler()
            self.assertEqual(
                crawler._tweets_per_account, x_crawler.DEFAULT_TWEETS_PER_ACCOUNT
            )
            self.assertEqual(
                crawler._transport._inter_account_delay,
                x_transport.DEFAULT_INTER_ACCOUNT_DELAY,
            )

    async def test_fetch_isolates_unexpected_exceptions(self) -> None:
        def _boom():
            raise RuntimeError("provider exploded")

        from backend.app.services.ingestion.crawlers import x_crawler

        crawler = x_crawler.XCrawler(
            transport=_FakeTransport(),
            watchlist_provider=_boom,
        )
        result = await crawler.fetch(period="daily", limit=25)
        self.assertIsNotNone(result.error)
        self.assertIn("provider exploded", result.error)
        self.assertEqual(result.source_channel, "x_daily_error")


class XTransportCredentialProviderContracts(unittest.IsolatedAsyncioTestCase):
    async def test_primary_success_avoids_backup(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            client.fetch_user.return_value = UserProfile(
                id="11", name="OpenAI", screen_name="openai"
            )
            client.fetch_user_tweets.return_value = [_tweet("1001")]
            return client

        def provider():
            return [
                {"id": 1, "enabled": True, "auth_token": "primary", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "backup", "ct0": "c2"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        result = await transport.fetch_watchlist_tweets(["openai"])

        self.assertEqual(calls, [("primary", "c1")])
        self.assertIn("openai", result)

    async def test_auth_fallback_retries_complete_watchlist_and_discards_partial(self) -> None:
        calls: list[tuple[str, str]] = []
        tweets_for_backup = [_tweet("backup-tweet")]

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            if auth_token == "primary":
                client.fetch_user.side_effect = [
                    UserProfile(id="11", name="OpenAI", screen_name="openai"),
                    AuthenticationError("dead"),
                ]
                client.fetch_user_tweets.return_value = [_tweet("primary-tweet")]
            else:
                client.fetch_user.side_effect = [
                    UserProfile(id="22", name="OpenAI", screen_name="openai"),
                    UserProfile(id="33", name="Karpathy", screen_name="karpathy"),
                ]
                client.fetch_user_tweets.side_effect = [
                    tweets_for_backup,
                    [_tweet("karpathy-backup")],
                ]
            return client

        def provider():
            return [
                {"id": 1, "enabled": True, "auth_token": "primary", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "backup", "ct0": "c2"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        result = await transport.fetch_watchlist_tweets(["openai", "karpathy"])

        self.assertEqual(calls, [("primary", "c1"), ("backup", "c2")])
        self.assertEqual([t.id for t in result["openai"]], ["backup-tweet"])
        self.assertEqual([t.id for t in result["karpathy"]], ["karpathy-backup"])

    async def test_rate_limit_does_not_rotate_account(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            client.fetch_user.return_value = UserProfile(
                id="11", name="OpenAI", screen_name="openai"
            )
            client.fetch_user_tweets.side_effect = RateLimitError("429")
            return client

        def provider():
            return [
                {"id": 1, "enabled": True, "auth_token": "primary", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "backup", "ct0": "c2"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        with self.assertRaises(x_transport.XRateLimitAbort):
            await transport.fetch_watchlist_tweets(["openai"])

        self.assertEqual(calls, [("primary", "c1")])

    async def test_all_credentials_authentication_failed(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            client.fetch_user.side_effect = AuthenticationError("dead")
            return client

        def provider():
            return [
                {"id": 1, "enabled": True, "auth_token": "first", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "second", "ct0": "c2"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        with self.assertRaises(x_transport.XAuthAbort) as ctx:
            await transport.fetch_watchlist_tweets(["openai"])

        self.assertIn("x_auth_all_credentials_failed", str(ctx.exception))
        self.assertEqual(calls, [("first", "c1"), ("second", "c2")])

    async def test_disabled_or_incomplete_credentials_are_skipped(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            client.fetch_user.return_value = UserProfile(
                id="11", name="OpenAI", screen_name="openai"
            )
            client.fetch_user_tweets.return_value = [_tweet("ok")]
            return client

        def provider():
            return [
                {"id": 1, "enabled": False, "auth_token": "disabled", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "", "ct0": "c2"},
                {"id": 3, "enabled": True, "auth_token": "valid", "ct0": "c3"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        result = await transport.fetch_watchlist_tweets(["openai"])

        self.assertEqual(calls, [("valid", "c3")])
        self.assertIn("openai", result)

    async def test_empty_provider_raises_auth_not_configured(self) -> None:
        transport = x_transport.XTransport(
            credential_provider=lambda: [],
            credential_factory=_FakeClient,
            inter_account_delay=0.0,
        )

        with self.assertRaises(x_transport.XAuthNotConfigured) as ctx:
            await transport.fetch_watchlist_tweets(["openai"])

        self.assertIn("x_auth_not_configured", str(ctx.exception))

    async def test_generator_watchlist_is_re_materialized_on_fallback(self) -> None:
        calls: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> _FakeClient:
            client = _FakeClient()
            calls.append((auth_token, ct0))
            if auth_token == "primary":
                client.fetch_user.side_effect = AuthenticationError("dead")
            else:
                client.fetch_user.return_value = UserProfile(
                    id="11", name="OpenAI", screen_name="openai"
                )
                client.fetch_user_tweets.return_value = [_tweet("ok")]
            return client

        def provider():
            return [
                {"id": 1, "enabled": True, "auth_token": "primary", "ct0": "c1"},
                {"id": 2, "enabled": True, "auth_token": "backup", "ct0": "c2"},
            ]

        transport = x_transport.XTransport(
            credential_provider=provider,
            credential_factory=factory,
            inter_account_delay=0.0,
            id_cache={},
            sleep=AsyncMock(),
        )

        def handle_generator():
            yield "openai"

        result = await transport.fetch_watchlist_tweets(handle_generator())

        self.assertEqual(calls, [("primary", "c1"), ("backup", "c2")])
        self.assertIn("openai", result)


def _legacy_with_media(media: list[dict]) -> dict:
    return {"extended_entities": {"media": media}}


def _video_media_item(media_id: str) -> dict:
    return {
        "type": "video",
        "media_url_https": f"https://pbs.twimg.com/amplify_video_thumb/{media_id}.jpg",
        "original_info": {"width": 1280, "height": 720},
        "video_info": {
            "variants": [
                {
                    "content_type": "video/mp4",
                    "bitrate": 2176000,
                    "url": f"https://video.twimg.com/amplify_video/{media_id}/vid/1280x720/a.mp4?tag=29",
                },
                {
                    "content_type": "video/mp4",
                    "bitrate": 832000,
                    "url": f"https://video.twimg.com/amplify_video/{media_id}/vid/640x360/b.mp4?tag=29",
                },
                {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/x.m3u8"},
            ]
        },
    }


class XMediaPosterPatchContracts(unittest.TestCase):
    """x_transport 封面补丁：包装 twitter-cli 真实 _extract_media 的契约。

    每个用例装补丁前记录现场、结束后恢复，避免污染同进程其他用例。
    """

    def setUp(self) -> None:
        from twitter_cli import parser as tw_parser

        self._tw_parser = tw_parser
        self._saved_extract = tw_parser._extract_media
        self._saved_flag = x_transport._ORIGINAL_EXTRACT_MEDIA

    def tearDown(self) -> None:
        self._tw_parser._extract_media = self._saved_extract
        x_transport._ORIGINAL_EXTRACT_MEDIA = self._saved_flag

    def _install(self) -> None:
        # 从干净状态安装：模拟生产首次构造真实 client 的路径
        self._tw_parser._extract_media = self._saved_extract
        x_transport._ORIGINAL_EXTRACT_MEDIA = None
        x_transport._install_media_poster_patch()

    def test_patch_backfills_poster_for_video_and_gif_not_photo(self) -> None:
        self._install()
        legacy = _legacy_with_media(
            [
                {
                    "type": "photo",
                    "media_url_https": "https://pbs.twimg.com/media/p.jpg",
                    "original_info": {"width": 1200, "height": 800},
                },
                _video_media_item("v1"),
                {**_video_media_item("g1"), "type": "animated_gif"},
            ]
        )

        items = self._tw_parser._extract_media(legacy)

        self.assertEqual([item.type for item in items], ["photo", "video", "animated_gif"])
        # 原行为保留：视频 url 仍取最高码率 mp4
        self.assertEqual(items[1].url, "https://video.twimg.com/amplify_video/v1/vid/1280x720/a.mp4?tag=29")
        self.assertFalse(hasattr(items[0], "poster_url"))
        self.assertEqual(
            items[1].poster_url, "https://pbs.twimg.com/amplify_video_thumb/v1.jpg"
        )
        self.assertEqual(
            items[2].poster_url, "https://pbs.twimg.com/amplify_video_thumb/g1.jpg"
        )

    def test_patch_skips_backfill_when_poster_missing(self) -> None:
        self._install()
        item = _video_media_item("v2")
        del item["media_url_https"]
        items = self._tw_parser._extract_media(_legacy_with_media([item]))
        self.assertFalse(hasattr(items[0], "poster_url"))

    def test_patch_install_is_idempotent(self) -> None:
        self._install()
        wrapped = self._tw_parser._extract_media
        original = x_transport._ORIGINAL_EXTRACT_MEDIA
        self.assertIsNotNone(original)

        x_transport._install_media_poster_patch()  # 第二次安装：不重复包装
        self.assertIs(self._tw_parser._extract_media, wrapped)
        self.assertIs(x_transport._ORIGINAL_EXTRACT_MEDIA, original)

    def test_credential_factory_installs_patch(self) -> None:
        x_transport._ORIGINAL_EXTRACT_MEDIA = None
        client = x_transport._default_credential_factory("tok", "ct0")
        self.assertIsNotNone(client)
        self.assertIsNotNone(x_transport._ORIGINAL_EXTRACT_MEDIA)


def _raw_tweet_result_with_card() -> dict:
    """MiniMax YouTube 卡推文的真实负载形状（player 卡 + t.co card_url 实体展开）。"""
    return {
        "__typename": "Tweet",
        "rest_id": "2086685611835245038",
        "core": {
            "user_results": {
                "result": {
                    "rest_id": "u1",
                    "legacy": {"name": "MiniMax", "screen_name": "MiniMax_AI"},
                }
            }
        },
        "card": {
            "rest_id": "card://2085994579514519552",
            "legacy": {
                "name": "player",
                "binding_values": [
                    {
                        "key": "title",
                        "value": {"string_value": "MiniMax H3: A New Open-Weight Video Model"},
                    },
                    {
                        "key": "description",
                        "value": {"string_value": "MiniMax H3 is an open-weight video model"},
                    },
                    {"key": "card_url", "value": {"string_value": "https://t.co/AqfZGExV1n"}},
                    {"key": "domain", "value": {"string_value": "www.youtube.com"}},
                    {"key": "vanity_url", "value": {"string_value": "youtube.com"}},
                    {
                        "key": "player_image",
                        "value": {
                            "image_value": {
                                "url": "https://pbs.twimg.com/card_img/2085/small.jpg",
                                "width": 280,
                                "height": 158,
                            }
                        },
                    },
                    {
                        "key": "player_image_large",
                        "value": {
                            "image_value": {
                                "url": "https://pbs.twimg.com/card_img/2085/large.jpg",
                                "width": 569,
                                "height": 320,
                            }
                        },
                    },
                    {
                        "key": "player_image_original",
                        "value": {
                            "image_value": {
                                "url": "https://pbs.twimg.com/card_img/2085/orig.jpg",
                                "width": 1280,
                                "height": 720,
                            }
                        },
                    },
                ],
            },
        },
        "legacy": {
            "full_text": "Watch: https://t.co/AqfZGExV1n",
            "created_at": "Sun Aug 09 03:00:00 +0000 2026",
            "entities": {
                "urls": [
                    {
                        "url": "https://t.co/AqfZGExV1n",
                        "expanded_url": "https://www.youtube.com/watch?v=S9O3FPumX4Q",
                        "display_url": "youtube.com/watch?v=S9O3FPumX4Q",
                        "indices": [7, 30],
                    }
                ]
            },
            "favorite_count": 10,
            "retweet_count": 0,
            "reply_count": 0,
            "quote_count": 0,
            "bookmark_count": 0,
            "lang": "en",
        },
    }


class XLinkCardPatchContracts(unittest.TestCase):
    """x_transport 链接卡片补丁：包装 twitter-cli 真实 parse_tweet_result 的契约。

    每个用例装补丁前记录现场、结束后恢复，避免污染同进程其他用例
    （与 XMediaPosterPatchContracts 同一纪律）。
    """

    def setUp(self) -> None:
        from twitter_cli import parser as tw_parser

        self._tw_parser = tw_parser
        self._saved_parse = tw_parser.parse_tweet_result
        self._saved_flag = x_transport._ORIGINAL_PARSE_TWEET_RESULT

    def tearDown(self) -> None:
        self._tw_parser.parse_tweet_result = self._saved_parse
        x_transport._ORIGINAL_PARSE_TWEET_RESULT = self._saved_flag

    def _install(self) -> None:
        # 从干净状态安装：模拟生产首次构造真实 client 的路径
        self._tw_parser.parse_tweet_result = self._saved_parse
        x_transport._ORIGINAL_PARSE_TWEET_RESULT = None
        x_transport._install_link_card_patch()

    def test_patch_backfills_card_with_expanded_url_and_best_image(self) -> None:
        self._install()
        tweet = self._tw_parser.parse_tweet_result(_raw_tweet_result_with_card())
        self.assertEqual(
            tweet.link_card,
            {
                # t.co card_url 经 legacy.entities.urls 展开为目标页
                "url": "https://www.youtube.com/watch?v=S9O3FPumX4Q",
                "title": "MiniMax H3: A New Open-Weight Video Model",
                "description": "MiniMax H3 is an open-weight video model",
                # vanity_url（展示域名）优先于 domain
                "domain": "youtube.com",
                # *original 优先级最高：取 1280x720 原图而非 large/small
                "image_url": "https://pbs.twimg.com/card_img/2085/orig.jpg",
                "image_width": 1280,
                "image_height": 720,
                "card_type": "player",
            },
        )

    def test_patch_falls_back_to_tco_and_smaller_image(self) -> None:
        self._install()
        raw = _raw_tweet_result_with_card()
        raw["legacy"]["entities"]["urls"] = []  # 无实体可展开
        raw["card"]["legacy"]["binding_values"] = [
            entry
            for entry in raw["card"]["legacy"]["binding_values"]
            if entry["key"] not in ("player_image_original", "player_image_large")
        ]
        tweet = self._tw_parser.parse_tweet_result(raw)
        # 展开失败保留 t.co 原值（仍可经 X 重定向跳转），缩略图逐档回退
        self.assertEqual(tweet.link_card["url"], "https://t.co/AqfZGExV1n")
        self.assertEqual(
            tweet.link_card["image_url"], "https://pbs.twimg.com/card_img/2085/small.jpg"
        )
        self.assertEqual(tweet.link_card["image_width"], 280)

    def test_patch_unwraps_visibility_results(self) -> None:
        self._install()
        wrapped = {
            "__typename": "TweetWithVisibilityResults",
            "tweet": _raw_tweet_result_with_card(),
        }
        tweet = self._tw_parser.parse_tweet_result(wrapped)
        self.assertEqual(tweet.link_card["card_type"], "player")

    def test_patch_takes_card_from_retweeted_original(self) -> None:
        self._install()
        original = _raw_tweet_result_with_card()
        retweet = {
            "__typename": "Tweet",
            "rest_id": "9999",
            "core": original["core"],
            "legacy": {
                "full_text": "RT @MiniMax_AI Watch: https://t.co/AqfZGExV1n",
                "created_at": "Sun Aug 09 04:00:00 +0000 2026",
                "retweeted_status_result": {"result": original},
                "favorite_count": 0,
                "retweet_count": 0,
                "reply_count": 0,
                "quote_count": 0,
                "bookmark_count": 0,
            },
        }
        tweet = self._tw_parser.parse_tweet_result(retweet)
        # 卡片与媒体同一数据源语义：取自被转推文
        self.assertEqual(tweet.link_card["card_type"], "player")

    def test_patch_no_card_or_unusable_card(self) -> None:
        self._install()
        raw = _raw_tweet_result_with_card()
        del raw["card"]
        tweet = self._tw_parser.parse_tweet_result(raw)
        self.assertFalse(hasattr(tweet, "link_card"))
        # 缺 title → 不赋值（无可看内容）
        raw2 = _raw_tweet_result_with_card()
        raw2["card"]["legacy"]["binding_values"] = [
            entry
            for entry in raw2["card"]["legacy"]["binding_values"]
            if entry["key"] != "title"
        ]
        tweet2 = self._tw_parser.parse_tweet_result(raw2)
        self.assertFalse(hasattr(tweet2, "link_card"))

    def test_patch_install_is_idempotent(self) -> None:
        self._install()
        wrapped = self._tw_parser.parse_tweet_result
        original = x_transport._ORIGINAL_PARSE_TWEET_RESULT
        self.assertIsNotNone(original)

        x_transport._install_link_card_patch()  # 第二次安装：不重复包装
        self.assertIs(self._tw_parser.parse_tweet_result, wrapped)
        self.assertIs(x_transport._ORIGINAL_PARSE_TWEET_RESULT, original)

    def test_credential_factory_installs_patch(self) -> None:
        x_transport._ORIGINAL_PARSE_TWEET_RESULT = None
        client = x_transport._default_credential_factory("tok", "ct0")
        self.assertIsNotNone(client)
        self.assertIsNotNone(x_transport._ORIGINAL_PARSE_TWEET_RESULT)


class XTranslationTransportContracts(unittest.TestCase):
    """transport.fetch_tweet_translations：只保留 Success 且目标语言 zh 的响应。"""

    def _transport(self, client: object | None = None) -> x_transport.XTransport:
        return x_transport.XTransport(client_factory=lambda: client or Mock())

    @staticmethod
    def _payload(text: str = "中文译文", state: str = "Success", dest: str = "zh") -> dict:
        return {
            "translation": text,
            "translationState": state,
            "destinationLanguage": dest,
        }

    def test_success_zh_payload_is_kept(self) -> None:
        transport = self._transport()
        with patch.object(
            x_transport, "_fetch_translation_payload", return_value=self._payload()
        ) as fetch:
            out = transport.fetch_tweet_translations(["3001"])
        self.assertEqual(out, {"3001": "中文译文"})
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], "3001")

    def test_failed_state_non_zh_destination_and_blank_text_are_dropped(self) -> None:
        transport = self._transport()
        payloads = iter([
            self._payload(state="Failed"),
            self._payload(dest="en"),
            self._payload(text="   "),
        ])
        with patch.object(
            x_transport,
            "_fetch_translation_payload",
            side_effect=lambda client, tid: next(payloads),
        ), patch.object(x_transport.time, "sleep"):
            out = transport.fetch_tweet_translations(["a", "b", "c"])
        self.assertEqual(out, {})

    def test_per_tweet_exception_skips_and_continues(self) -> None:
        transport = self._transport()

        def fake_fetch(client: object, tid: str) -> dict:
            if tid == "x1":
                raise RuntimeError("HTTP 429")
            return self._payload(text=f"译:{tid}")

        with patch.object(
            x_transport, "_fetch_translation_payload", side_effect=fake_fetch
        ), patch.object(x_transport.time, "sleep") as sleep_mock:
            out = transport.fetch_tweet_translations(["x1", "x2"])
        self.assertEqual(out, {"x2": "译:x2"})
        sleep_mock.assert_called_once_with(x_transport._TRANSLATION_INTER_DELAY)

    def test_client_construction_failure_returns_empty(self) -> None:
        def broken_factory() -> object:
            raise x_transport.XAuthNotConfigured("x_auth_not_configured: nope")

        transport = x_transport.XTransport(client_factory=broken_factory)
        self.assertEqual(transport.fetch_tweet_translations(["z1"]), {})

    def test_credential_provider_path_uses_first_enabled_valid_credential(self) -> None:
        made: list[tuple[str, str]] = []

        def factory(auth_token: str, ct0: str) -> object:
            made.append((auth_token, ct0))
            return Mock()

        transport = x_transport.XTransport(
            credential_provider=lambda: [
                {"auth_token": "", "ct0": "", "enabled": True},
                {"auth_token": "a", "ct0": "b", "enabled": False},
                {"auth_token": "tok", "ct0": "ct", "enabled": True},
            ],
            credential_factory=factory,
        )
        with patch.object(
            x_transport, "_fetch_translation_payload", return_value=self._payload()
        ), patch.object(x_transport.time, "sleep"):
            out = transport.fetch_tweet_translations(["q1"])
        self.assertEqual(made, [("tok", "ct")])
        self.assertEqual(out, {"q1": "中文译文"})

    def test_empty_ids_short_circuits_before_client_construction(self) -> None:
        def forbidden_factory() -> object:
            raise AssertionError("空 id 列表不应构造客户端")

        transport = x_transport.XTransport(client_factory=forbidden_factory)
        self.assertEqual(transport.fetch_tweet_translations(["", "   "]), {})


class XCrawlerTranslationContracts(unittest.IsolatedAsyncioTestCase):
    """翻译附着：非中文入选推文补 translation_zh，失败不影响入库。"""

    def _crawler(self, transport, fetcher=None, handles=("openai",)):
        from backend.app.services.ingestion.crawlers import x_crawler

        return x_crawler.XCrawler(
            transport=transport,
            watchlist_provider=lambda: list(handles),
            tweets_per_account=7,
            translation_fetcher=fetcher,
        )

    @staticmethod
    def _lang_tweet(tweet_id: str, lang: str) -> Tweet:
        tweet = _tweet(tweet_id)
        tweet.lang = lang  # 0.8.5 已有 lang 字段，显式设置覆盖默认 ""
        return tweet

    async def test_attaches_translation_only_for_non_zh_selected_tweets(self) -> None:
        transport = _FakeTransport(
            result={
                "openai": [
                    self._lang_tweet("2001", "en"),
                    self._lang_tweet("2002", "zh"),
                    self._lang_tweet("2003", "zxx"),
                ]
            }
        )
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {"2001": "中文译文"}

        crawler = self._crawler(transport, fetcher=fetcher)
        # 默认推文日期 = CST 2026-08-03：快照日过滤按此对齐
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2001"]])  # zh/zxx 不发起翻译请求
        by_id = {item["tweet_id"]: item for item in result.items}
        self.assertEqual(by_id["2001"].get("translation_zh"), "中文译文")
        self.assertNotIn("translation_zh", by_id["2002"])
        self.assertNotIn("translation_zh", by_id["2003"])

    async def test_translation_missing_links_are_restored_on_attach(self) -> None:
        tweet = self._lang_tweet("2007", "en")
        tweet.text = "More info on eligibility: https://t.co/jzWCbyaIdg"
        tweet.urls = ["https://gemini.google/eligibility"]
        transport = _FakeTransport(result={"openai": [tweet]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            # X translateTweet 会剥掉链接
            return {"2007": "更多资格信息："}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(
            result.items[0].get("translation_zh"),
            "更多资格信息：\nhttps://gemini.google/eligibility",
        )
        # 正文同样被清洗为展开式
        self.assertEqual(
            result.items[0]["summary"],
            "More info on eligibility: https://gemini.google/eligibility",
        )

    async def test_translation_html_entities_decoded_on_attach(self) -> None:
        # translateTweet 译文带 HTML 实体（2026-08 线上报障：&amp; 直接露出页面）
        tweet = self._lang_tweet("2009", "en")
        tweet.text = "Daybreak Blue & Red access tiers"
        transport = _FakeTransport(result={"openai": [tweet]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            return {"2009": "Daybreak Blue &amp; Red 访问层级"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(
            result.items[0].get("translation_zh"),
            "Daybreak Blue & Red 访问层级",
        )

    async def test_quoted_translation_html_entities_decoded(self) -> None:
        # 被引译文同口径解码 HTML 实体
        outer = self._lang_tweet("2060", "en")
        quoted = self._lang_tweet("2061", "en")
        quoted.text = "Free & Go users get unlimited chats"
        outer.quoted_tweet = quoted
        transport = _FakeTransport(result={"openai": [outer]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            return {"2060": "外推译文", "2061": "Free &amp; Go 用户可无限聊天"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        item = result.items[0]
        self.assertEqual(item.get("translation_zh"), "外推译文")
        self.assertEqual(item["quote"].get("translation_zh"), "Free & Go 用户可无限聊天")

    async def test_translation_dropped_reply_mentions_are_restored_on_attach(self) -> None:
        tweet = self._lang_tweet("2008", "en")
        tweet.text = "@VictorSuOrtiz @alexinexxx RSVP here: https://t.co/LuMa"
        tweet.urls = ["https://luma.com/cboi9km9"]
        transport = _FakeTransport(result={"openai": [tweet]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            # X translateTweet 剥掉回复 @ 前缀与全部链接
            return {"2008": "请在此处回复："}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(
            result.items[0].get("translation_zh"),
            "@VictorSuOrtiz @alexinexxx 请在此处回复：\nhttps://luma.com/cboi9km9",
        )

    async def test_empty_lang_still_attempts_translation(self) -> None:
        transport = _FakeTransport(result={"openai": [self._lang_tweet("2006", "")]})
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2006"]])
        self.assertNotIn("translation_zh", result.items[0])

    async def test_translation_fetch_failure_does_not_fail_crawl(self) -> None:
        transport = _FakeTransport(result={"openai": [self._lang_tweet("2004", "en")]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            raise RuntimeError("boom")

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertIsNone(result.error)
        self.assertEqual(len(result.items), 1)
        self.assertNotIn("translation_zh", result.items[0])

    async def test_transport_fetcher_fallback_and_legacy_fake_skipped(self) -> None:
        # 真实 transport 形态：自带 fetch_tweet_translations，无需注入 fetcher
        en_tweet = self._lang_tweet("2005", "en")

        class TransportWithTranslation(_FakeTransport):
            def fetch_tweet_translations(self, ids: list[str]) -> dict[str, str]:
                return {tid: f"译:{tid}" for tid in ids}

        crawler = self._crawler(TransportWithTranslation(result={"openai": [en_tweet]}))
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)
        self.assertEqual(result.items[0].get("translation_zh"), "译:2005")

        # 旧版 duck-typed fake 无此方法：静默跳过，不报错
        crawler = self._crawler(_FakeTransport(result={"openai": [en_tweet]}))
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)
        self.assertIsNone(result.error)
        self.assertNotIn("translation_zh", result.items[0])

    def test_needs_zh_translation_lang_filter(self) -> None:
        from backend.app.services.ingestion.crawlers.x_crawler import _needs_zh_translation

        self.assertTrue(_needs_zh_translation("en"))
        self.assertTrue(_needs_zh_translation("ja"))
        self.assertTrue(_needs_zh_translation(""))  # 未知语言仍尝试，X 服务端自行判定
        self.assertFalse(_needs_zh_translation("zh"))
        self.assertFalse(_needs_zh_translation("zh-cn"))
        self.assertFalse(_needs_zh_translation("zh-TW"))
        self.assertFalse(_needs_zh_translation("zxx"))  # 无语言内容（纯媒体）

    async def test_attaches_translation_for_non_zh_quoted_tweet(self) -> None:
        # 中文外推引用英文推文：仅被引需要翻译（引文切中文仍显示原文的报障场景）
        outer = self._lang_tweet("2010", "zh")
        outer.quoted_tweet = self._lang_tweet("2011", "en")
        transport = _FakeTransport(result={"openai": [outer]})
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {"2011": "被引中文译文"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2011"]])  # 中文外推不请求翻译
        item = result.items[0]
        self.assertNotIn("translation_zh", item)
        self.assertEqual(item["quote"].get("translation_zh"), "被引中文译文")

    async def test_quoted_translation_merges_targets_and_restores_links(self) -> None:
        # 英文外推 + 英文被引：两个 id 合并为一次抓取；被引译文补回丢失链接
        outer = self._lang_tweet("2020", "en")
        quoted = self._lang_tweet("2021", "en")
        quoted.text = "read this https://t.co/abc123"
        quoted.urls = ["https://example.com/report"]
        outer.quoted_tweet = quoted
        transport = _FakeTransport(result={"openai": [outer]})
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {"2020": "外推译文", "2021": "被引译文："}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2020", "2021"]])
        item = result.items[0]
        self.assertEqual(item.get("translation_zh"), "外推译文")
        # X 译文剥掉链接：按被引实体补回（被引正文同口径已展开 t.co）
        self.assertEqual(
            item["quote"].get("translation_zh"),
            "被引译文：\nhttps://example.com/report",
        )
        self.assertEqual(item["quote"]["text"], "read this https://example.com/report")

    async def test_quoted_translation_dropped_reply_mentions_are_restored(self) -> None:
        outer = self._lang_tweet("2050", "en")
        quoted = self._lang_tweet("2051", "en")
        quoted.text = "@AnthropicAI congrats on the launch!"
        outer.quoted_tweet = quoted
        transport = _FakeTransport(result={"openai": [outer]})

        def fetcher(ids: list[str]) -> dict[str, str]:
            return {"2050": "外推译文", "2051": "祝贺发布！"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(
            result.items[0]["quote"].get("translation_zh"),
            "@AnthropicAI 祝贺发布！",
        )

    async def test_zh_quoted_tweet_skips_translation(self) -> None:
        # 中文被引不发起翻译请求；外推英文仍正常补译
        outer = self._lang_tweet("2030", "en")
        outer.quoted_tweet = self._lang_tweet("2031", "zh")
        transport = _FakeTransport(result={"openai": [outer]})
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {"2030": "外推译文"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2030"]])
        self.assertNotIn("translation_zh", result.items[0]["quote"])

    async def test_quoted_tweet_shared_with_outer_is_fetched_once(self) -> None:
        # 被引推文同时是另一条入选外推：同一 id 去重后只请求一次
        quoted = self._lang_tweet("2041", "en")
        outer = self._lang_tweet("2040", "zh")
        outer.quoted_tweet = quoted
        transport = _FakeTransport(result={"openai": [outer, quoted]})
        seen: list[list[str]] = []

        def fetcher(ids: list[str]) -> dict[str, str]:
            seen.append(list(ids))
            return {"2041": "共享推文译文"}

        crawler = self._crawler(transport, fetcher=fetcher)
        with patch.object(x_crawler, "today_cst", return_value="2026-08-03"):
            result = await crawler._do_fetch(period="daily", limit=25)

        self.assertEqual(seen, [["2041"]])
        by_id = {item["tweet_id"]: item for item in result.items}
        self.assertEqual(by_id["2041"].get("translation_zh"), "共享推文译文")
        self.assertEqual(by_id["2040"]["quote"].get("translation_zh"), "共享推文译文")


if __name__ == "__main__":
    unittest.main()
