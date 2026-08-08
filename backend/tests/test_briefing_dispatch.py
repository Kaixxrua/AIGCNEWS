from __future__ import annotations

import unittest
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.briefing import dispatch


class _FakeBriefingService:
    """按维度回放预设流载荷并记录调用参数的简报服务替身。"""

    def __init__(self, streams: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        self._streams = streams
        self.calls: list[dict[str, Any]] = []

    async def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        period: str = "daily",
        force_regenerate: bool = True,
        locale: str = "zh-CN",
        generate_bilingual: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(
            {
                "target_date": target_date,
                "source": source,
                "period": period,
                "force_regenerate": force_regenerate,
                "generate_bilingual": generate_bilingual,
            }
        )
        for payload in self._streams[(source, period)]:
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
            {"email": "subscriber@example.com"}
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=email_service,
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="github",
                period="daily",
                date_str="2026-07-22",
                content="briefing content",
                subscriptions=repository,
            )

        self.assertEqual(sent, 1)
        repository.get_active_subscribers.assert_called_once_with(
            source="github",
            period="daily",
        )
        factory.assert_called_once_with(None)
        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="briefing content",
            source="github",
            period="daily",
            date_str="2026-07-22",
        )

    async def test_no_subscribers_skips_email_factory(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = []

        with patch(
            "backend.app.services.email_service.build_email_service"
        ) as factory:
            sent = await dispatch.send_briefing_to_subscribers(
                source="arxiv",
                period="daily",
                date_str="2026-08-08",
                content="content",
                subscriptions=repository,
            )

        self.assertEqual(sent, 0)
        factory.assert_not_called()

    async def test_skips_blank_email_and_continues_after_send_failure(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {"email": ""},
            {"email": "broken@example.com"},
            {"email": "ok@example.com"},
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
                period="daily",
                date_str="2026-08-08",
                content="content",
                subscriptions=repository,
            )

        self.assertEqual(sent, 1)
        self.assertEqual(email_service.send_briefing.await_count, 2)


class RunDailyBriefingDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_stream_and_sends_joined_content(self) -> None:
        streams = {
            ("github", "daily"): [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "Hello "},
                {"type": "content", "data": "World"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch.object(dispatch, "BRIEFING_TASKS", [{"source": "github", "period": "daily"}]),
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
                    "period": "daily",
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

    async def test_skips_email_when_not_persisted_empty_or_undated(self) -> None:
        streams = {
            ("arxiv", "daily"): [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": -1}},
            ],
            ("github", "daily"): [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "   "},
                {"type": "done", "data": {"briefing_id": 7}},
            ],
            ("news", "daily"): [
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 9}},
            ],
        }
        service = _FakeBriefingService(streams)
        repositories = _repositories_with_subscribers(
            [{"email": "subscriber@example.com"}]
        )

        with (
            patch.object(
                dispatch,
                "BRIEFING_TASKS",
                [
                    {"source": "arxiv", "period": "daily"},
                    {"source": "github", "period": "daily"},
                    {"source": "news", "period": "daily"},
                ],
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
            ("github", "daily"): [
                {"type": "start", "data": {"date": "2026-08-08"}},
                {"type": "content", "data": "正文"},
                {"type": "done", "data": {"briefing_id": 42}},
            ],
        }
        service = _FailingService(streams)
        repositories = _repositories_with_subscribers(
            [{"email": "subscriber@example.com"}]
        )
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch.object(
                dispatch,
                "BRIEFING_TASKS",
                [
                    {"source": "arxiv", "period": "daily"},
                    {"source": "github", "period": "daily"},
                ],
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


if __name__ == "__main__":
    unittest.main()
