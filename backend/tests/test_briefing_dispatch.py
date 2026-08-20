from __future__ import annotations

import unittest
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.briefing import dispatch


class _FakeBriefingService:
    """按维度回放预设流载荷并记录调用参数的简报服务替身。"""

    def __init__(self, streams: dict[str, list[dict[str, Any]]]) -> None:
        self._streams = streams
        self.calls: list[dict[str, Any]] = []

    async def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        force_regenerate: bool = True,
        locale: str = "zh-CN",
        generate_bilingual: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(
            {
                "target_date": target_date,
                "source": source,
                "force_regenerate": force_regenerate,
                "generate_bilingual": generate_bilingual,
            }
        )
        for payload in self._streams[source]:
            yield payload


def _repositories_with_subscribers(
    subscribers: list[dict[str, Any]],
) -> MagicMock:
    repositories = MagicMock()
    repositories.briefing_subscriptions.get_active_subscribers.return_value = (
        subscribers
    )
    return repositories


class SendBriefingToSubscribersTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_briefing_uses_factory_without_redis(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {"id": 11, "email": "subscriber@example.com"}
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=email_service,
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="github",
                date_str="2026-07-22",
                content="briefing content",
                briefing_id=42,
                subscriptions=repository,
            )

        self.assertEqual(sent, 1)
        repository.get_active_subscribers.assert_called_once_with(
            source="github",
        )
        factory.assert_called_once_with(None)
        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="briefing content",
            source="github",
            period="daily",
            date_str="2026-07-22",
        )
        repository.mark_briefing_delivered.assert_called_once_with([11], 42)

    async def test_no_subscribers_skips_email_factory(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = []

        with patch(
            "backend.app.services.email_service.build_email_service"
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="arxiv",
                date_str="2026-08-08",
                content="content",
                briefing_id=1,
                subscriptions=repository,
            )

        self.assertEqual(sent, 0)
        factory.assert_not_called()
        repository.mark_briefing_delivered.assert_not_called()

    async def test_skips_blank_email_and_continues_after_send_failure(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {"id": 1, "email": ""},
            {"id": 2, "email": "broken@example.com"},
            {"id": 3, "email": "ok@example.com"},
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock(
            side_effect=[RuntimeError("smtp down"), None]
        )

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=email_service,
        ):
            sent = await dispatch.send_briefing_to_subscribers(
                source="news",
                date_str="2026-08-08",
                content="content",
                briefing_id=9,
                subscriptions=repository,
            )

        self.assertEqual(sent, 1)
        self.assertEqual(email_service.send_briefing.await_count, 2)
        # 仅成功投递的订阅回写投递标记，失败的订阅留待下一轮重试。
        repository.mark_briefing_delivered.assert_called_once_with([3], 9)

    async def test_skips_subscribers_already_delivered_for_briefing(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {
                "id": 1,
                "email": "fresh@example.com",
                "last_delivered_briefing_id": 7,
            },
            {
                "id": 2,
                "email": "repeat@example.com",
                "last_delivered_briefing_id": 42,
            },
            {
                "id": 3,
                "email": "ahead@example.com",
                "last_delivered_briefing_id": 100,
            },
            {"id": 4, "email": "new@example.com"},
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=email_service,
        ):
            sent = await dispatch.send_briefing_to_subscribers(
                source="github",
                date_str="2026-08-08",
                content="content",
                briefing_id=42,
                subscriptions=repository,
            )

        self.assertEqual(sent, 2)
        sent_emails = [
            call.kwargs["to_email"]
            for call in email_service.send_briefing.await_args_list
        ]
        self.assertEqual(sent_emails, ["fresh@example.com", "new@example.com"])
        repository.mark_briefing_delivered.assert_called_once_with([1, 4], 42)

    async def test_all_subscribers_up_to_date_skips_email_factory(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {
                "id": 1,
                "email": "repeat@example.com",
                "last_delivered_briefing_id": 42,
            }
        ]

        with patch(
            "backend.app.services.email_service.build_email_service"
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="github",
                date_str="2026-08-08",
                content="content",
                briefing_id=42,
                subscriptions=repository,
            )

        self.assertEqual(sent, 0)
        factory.assert_not_called()
        repository.mark_briefing_delivered.assert_not_called()

    async def test_send_briefing_threads_redis_client_to_factory(self) -> None:
        """调度器注入的 redis 透传至工厂：启用邮件池配额计数与熔断护栏。"""
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {"id": 11, "email": "subscriber@example.com"}
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()
        sentinel = object()

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=email_service,
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="github",
                date_str="2026-08-20",
                content="briefing content",
                briefing_id=7,
                subscriptions=repository,
                redis_client=sentinel,
            )

        self.assertEqual(sent, 1)
        factory.assert_called_once_with(sentinel)


class RunDailyBriefingDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_stream_and_sends_joined_content(self) -> None:
        streams = {
            "github": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "Hello "},
                {"type": "content", "data": "World"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"id": 5, "email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch.object(dispatch, "BRIEFING_SOURCES", ["github"]),
            patch.object(
                dispatch, "provide_daily_briefing_service", return_value=service
            ) as provide,
            patch(
                "backend.app.services.email_service.build_email_service",
                return_value=email_service,
            ),
        ):
            await dispatch.run_daily_briefing_dispatch(repositories)

        provide.assert_called_once_with(repositories=repositories)
        self.assertEqual(
            service.calls,
            [
                {
                    "target_date": None,
                    "source": "github",
                    "force_regenerate": False,
                    "generate_bilingual": True,
                }
            ],
        )
        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="Hello World",
            source="github",
            period="daily",
            date_str="2026-08-08",
        )
        repositories.briefing_subscriptions.mark_briefing_delivered.assert_called_once_with(
            [5], 42
        )

    async def test_error_payload_skips_dimension_without_counting_success(
        self,
    ) -> None:
        streams = {
            "arxiv": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "error", "data": "llm exploded"},
            ],
            "github": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"id": 5, "email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch.object(
                dispatch,
                "BRIEFING_SOURCES",
                ["arxiv", "github"],
            ),
            patch.object(
                dispatch, "provide_daily_briefing_service", return_value=service
            ),
            patch(
                "backend.app.services.email_service.build_email_service",
                return_value=email_service,
            ),
            patch.object(dispatch.logger, "info") as log_info,
        ):
            await dispatch.run_daily_briefing_dispatch(repositories)

        # arxiv 维度 error 载荷：不派发、不计成功；github 维度照常投递。
        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="正文",
            source="github",
            period="daily",
            date_str="2026-08-08",
        )
        repositories.briefing_subscriptions.get_active_subscribers.assert_called_once_with(
            source="github"
        )
        summary_calls = [
            call
            for call in log_info.call_args_list
            if "每日简报生成完毕" in str(call)
        ]
        self.assertEqual(len(summary_calls), 1)
        self.assertEqual(summary_calls[0].args[1:], (1, 2))

    async def test_skips_email_when_not_persisted_empty_or_undated(self) -> None:
        streams = {
            "arxiv": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": -1}},
            ],
            "github": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "   "},
                {"type": "done", "data": {"briefing_id": 7}},
            ],
            "news": [
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 9}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"id": 5, "email": "subscriber@example.com"}]
        )

        with (
            patch.object(
                dispatch,
                "BRIEFING_SOURCES",
                ["arxiv", "github", "news"],
            ),
            patch.object(
                dispatch, "provide_daily_briefing_service", return_value=service
            ),
            patch(
                "backend.app.services.email_service.build_email_service"
            ) as factory,
        ):
            await dispatch.run_daily_briefing_dispatch(repositories)

        repositories.briefing_subscriptions.get_active_subscribers.assert_not_called()
        factory.assert_not_called()

    async def test_dimension_failure_does_not_stop_remaining_dimensions(self) -> None:
        class _FailingService(_FakeBriefingService):
            async def stream_generate(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
                source = kwargs.get("source", "all")
                if source == "arxiv":
                    raise RuntimeError("llm exploded")
                    yield  # pragma: no cover - 保持异步生成器形态
                async for payload in super().stream_generate(**kwargs):
                    yield payload

        streams = {
            "github": [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FailingService(streams)
        repositories = _repositories_with_subscribers(
            [{"id": 5, "email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch.object(
                dispatch,
                "BRIEFING_SOURCES",
                ["arxiv", "github"],
            ),
            patch.object(
                dispatch, "provide_daily_briefing_service", return_value=service
            ),
            patch(
                "backend.app.services.email_service.build_email_service",
                return_value=email_service,
            ),
        ):
            await dispatch.run_daily_briefing_dispatch(repositories)

        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="正文",
            source="github",
            period="daily",
            date_str="2026-08-08",
        )

    async def test_threads_redis_client_into_email_factory(self) -> None:
        """run 级入口把 redis_client 透传到每维度派发链路的邮件工厂。"""
        streams = {
            "github": [
                {"type": "start", "data": {"date": "2026-08-20"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"id": 5, "email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()
        sentinel = object()

        with (
            patch.object(dispatch, "BRIEFING_SOURCES", ["github"]),
            patch.object(
                dispatch, "provide_daily_briefing_service", return_value=service
            ),
            patch(
                "backend.app.services.email_service.build_email_service",
                return_value=email_service,
            ) as factory,
        ):
            await dispatch.run_daily_briefing_dispatch(
                repositories, redis_client=sentinel
            )

        factory.assert_called_once_with(sentinel)


if __name__ == "__main__":
    unittest.main()
