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
from twitter_cli.models import Author, Metrics, Tweet, UserProfile

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
                "published_date": "2026-08-02",
                "tweet_id": "1002",
                "author": "openai",
                "author_name": "OpenAI",
                "rank_in_period": 1,
                "tags": ["x", "daily", "openai"],
            },
        )

    def test_project_tweets_limit_and_title_truncation(self) -> None:
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
            self.assertEqual(len(item["title"]), 100)
            self.assertTrue(item["title"].endswith("..."))
            self.assertNotIn("\n", item["title"])
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


if __name__ == "__main__":
    unittest.main()
