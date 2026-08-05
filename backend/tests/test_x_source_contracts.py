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
)
from twitter_cli.models import Author, Metrics, Tweet, TweetMedia, UserProfile

from backend.app.services.ingestion.sources import x_policy, x_transport


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
            _tweet("1004", is_retweet=True, text="rt", likes=99999),
            _tweet("1005", is_subscriber_only=True, text="sub", likes=99999),
            _tweet("1006", text="", likes=99999),
        ]
        items = x_policy.project_tweets(tweets, limit=10)
        self.assertEqual([item["tweet_id"] for item in items], ["1002", "1001"])
        self.assertEqual([item["rank_in_period"] for item in items], [1, 2])
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
            },
        )

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
            result={"openai": [_tweet("1002", likes=10, retweets=2, replies=1, bookmarks=3, views=100)]}
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
        ):
            with self.subTest(marker=marker):
                crawler = self._crawler(_FakeTransport(error=error))
                result = await crawler._do_fetch(period="daily", limit=25)
                self.assertEqual(result.items, [])
                self.assertEqual(result.source_channel, "x_daily_watchlist")
                self.assertIn(marker, result.error)

    async def test_env_driven_defaults_for_count_delay_and_watchlist(self) -> None:
        from backend.app.services.ingestion.crawlers import x_crawler

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


if __name__ == "__main__":
    unittest.main()
