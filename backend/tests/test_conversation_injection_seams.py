from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import MagicMock, patch

from fastapi.params import Depends

from backend.app.api import routes_chat
from backend.app.api.dependencies import (
    get_conversation_repository,
    get_conversation_service,
)
from backend.app.core import scheduler
from backend.app.services.chat.conversation_service import ConversationService


class ConversationInjectionSeamTests(unittest.TestCase):
    def test_all_conversation_routes_use_the_application_service_dependency(self) -> None:
        route_functions = (
            routes_chat.stream_chat,
            routes_chat.ensure_conversation,
            routes_chat.create_conversation,
            routes_chat.delete_conversation,
            routes_chat.get_conversations,
            routes_chat.get_conversation_detail,
            routes_chat.delete_message,
            routes_chat.regenerate_message,
        )

        for route_function in route_functions:
            with self.subTest(route=route_function.__name__):
                parameter = inspect.signature(route_function).parameters[
                    "conversation_service"
                ]
                self.assertIsInstance(parameter.default, Depends)
                self.assertIs(parameter.default.dependency, get_conversation_service)

    def test_quota_routes_keep_the_repository_reader_dependency(self) -> None:
        for route_function in (routes_chat.stream_chat, routes_chat.regenerate_message):
            with self.subTest(route=route_function.__name__):
                parameter = inspect.signature(route_function).parameters["conversations"]
                self.assertIsInstance(parameter.default, Depends)
                self.assertIs(
                    parameter.default.dependency,
                    get_conversation_repository,
                )

    def test_service_requires_an_explicit_repository(self) -> None:
        with self.assertRaises(TypeError):
            ConversationService()  # type: ignore[call-arg]

    def test_cleanup_job_uses_injected_repository(self) -> None:
        repository = MagicMock()
        repository.cleanup_stale_conversations.return_value = 3

        asyncio.run(scheduler._run_conversation_cleanup_job(repository))

        repository.cleanup_stale_conversations.assert_called_once_with(
            stale_days=7,
            limit=5,
        )

    def test_cleanup_job_requires_repository(self) -> None:
        with self.assertRaises(TypeError):
            asyncio.run(scheduler._run_conversation_cleanup_job())


if __name__ == "__main__":
    unittest.main()
