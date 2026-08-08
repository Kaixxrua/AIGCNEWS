from __future__ import annotations

import ast
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.api import routes_report
from backend.app.api.dependencies import get_evaluation_repository
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.repositories.briefing_repository import (
    BriefingReader,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.services.email_service import EmailService


class ReportRouteArchitectureTests(unittest.TestCase):
    def test_report_routes_do_not_construct_briefing_infrastructure(self) -> None:
        source = Path(routes_report.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertNotIn("DailyBriefingService", calls)
        self.assertNotIn("get_chat_model", calls)
        self.assertNotIn("MilvusRepository", calls)


class ReportEmailServiceWiringTests(unittest.TestCase):
    def test_get_email_service_passes_application_redis_to_factory(self) -> None:
        app = FastAPI()
        redis_client = object()
        app.state.redis = redis_client
        request = MagicMock(spec=Request)
        request.app = app
        service = MagicMock(spec=EmailService)

        with patch.object(
            routes_report,
            "build_email_service",
            return_value=service,
        ) as factory:
            result = routes_report._get_email_service(request)

        self.assertIs(result, service)
        factory.assert_called_once_with(redis_client)


class ReportBriefingRepositoryTests(unittest.TestCase):
    def test_latest_uses_repository_and_preserves_cache_key(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = {
            "id": 42,
            "date": "2026-07-22_github",
            "content": "cached",
        }

        result = asyncio.run(
            routes_report.get_latest_briefing(
                source="github",
                date="2026-07-22",
                repository=repository,
            )
        )

        repository.get_briefing_by_date.assert_called_once_with(
            "2026-07-22_github"
        )
        self.assertEqual(
            result,
            {
                "id": 42,
                "date": "2026-07-22_github",
                "content": "cached",
                "source": "github",
                "cache_key": "2026-07-22_github",
            },
        )

    def test_latest_missing_preserves_response(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = None

        response = asyncio.run(
            routes_report.get_latest_briefing(
                source="invalid",
                date="2026-07-22",
                repository=repository,
            )
        )

        repository.get_briefing_by_date.assert_called_once_with("2026-07-22")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.body.decode(),
            '{"detail":"对应简报尚未生成","cache_key":"2026-07-22"}',
        )

    def test_history_uses_repository(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.list_briefings.return_value = [{"id": 42}]

        result = asyncio.run(
            routes_report.list_briefings(limit=7, repository=repository)
        )

        self.assertEqual(result, {"items": [{"id": 42}], "total": 1})
        repository.list_briefings.assert_called_once_with(limit=7)

    def test_by_id_uses_repository(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing.return_value = {"id": 42, "content": "briefing"}

        result = asyncio.run(
            routes_report.get_briefing(42, repository=repository)
        )

        self.assertEqual(result, {"id": 42, "content": "briefing"})
        repository.get_briefing.assert_called_once_with(42)

    def test_by_id_missing_preserves_response(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing.return_value = None

        response = asyncio.run(
            routes_report.get_briefing(42, repository=repository)
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.body.decode(),
            '{"detail":"Briefing 42 not found"}',
        )

    def test_email_helper_uses_explicit_repository(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = {"content": "cached"}
        request = MagicMock(spec=Request)
        email_service = MagicMock(spec=EmailService)
        email_service.send_briefing = AsyncMock()

        with patch.object(
            routes_report,
            "_get_email_service",
            return_value=email_service,
        ):
            result = asyncio.run(
                routes_report._send_cached_briefing_to_email(
                    request=request,
                    repository=repository,
                    email="reader@example.com",
                    source="all",
                    date_str="2026-07-22",
                )
            )

        self.assertEqual(result, "2026-07-22")
        repository.get_briefing_by_date.assert_called_once_with(
            "2026-07-22"
        )
        email_service.send_briefing.assert_awaited_once_with(
            to_email="reader@example.com",
            briefing_content="cached",
            source="all",
            period="daily",
            date_str="2026-07-22",
        )


class ReportEvaluationRepositoryTests(unittest.TestCase):
    def test_summary_uses_repository(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        repository.get_eval_summary.return_value = {"total": 2}

        result = asyncio.run(routes_report.eval_summary(repository=repository))

        self.assertEqual(result, {"total": 2})
        repository.get_eval_summary.assert_called_once_with()

    def test_list_uses_repository_and_preserves_response(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        repository.list_evaluations.return_value = [{"id": 2}]

        result = asyncio.run(
            routes_report.eval_list(limit=7, repository=repository)
        )

        self.assertEqual(result, {"items": [{"id": 2}], "total": 1})
        repository.list_evaluations.assert_called_once_with(limit=7)


class ReportEvaluationAdminGateTests(unittest.TestCase):
    """内部评估明细仅管理员可见（口径与 /monitor 一致）。"""

    def _build_client(self, repository) -> TestClient:
        app = FastAPI()
        app.include_router(routes_report.router, prefix="/api")
        app.dependency_overrides[get_evaluation_repository] = lambda: repository
        return TestClient(app)

    def test_eval_endpoints_reject_anonymous(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        client = self._build_client(repository)

        for path in ("/api/report/eval/summary", "/api/report/eval/list"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertIn(response.status_code, (401, 403))
        repository.get_eval_summary.assert_not_called()
        repository.list_evaluations.assert_not_called()

    def test_eval_endpoints_reject_authenticated_non_admin(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        client = self._build_client(repository)
        client.app.dependency_overrides[RequireUser] = lambda: {"role": "user"}

        for path in ("/api/report/eval/summary", "/api/report/eval/list"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 403)
        repository.get_eval_summary.assert_not_called()
        repository.list_evaluations.assert_not_called()

    def test_eval_endpoints_serve_admin(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        repository.get_eval_summary.return_value = {"total": 2}
        repository.list_evaluations.return_value = [{"id": 2}]
        client = self._build_client(repository)
        client.app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}

        summary = client.get("/api/report/eval/summary")
        listing = client.get("/api/report/eval/list")

        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json(), {"total": 2})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), {"items": [{"id": 2}], "total": 1})


class ReportBriefingSubscriptionRepositoryTests(unittest.TestCase):
    def test_subscribe_uses_authenticated_user_and_repository(self) -> None:
        repository = MagicMock(spec=BriefingSubscriptionRepository)
        repository.upsert_briefing_subscription.return_value = {"id": 42}

        result = asyncio.run(
            routes_report.subscribe_briefing(
                routes_report.SubscribeRequest(source="github"),
                user={"user_id": 7, "email": "reader@example.com"},
                repository=repository,
            )
        )

        repository.upsert_briefing_subscription.assert_called_once_with(
            user_id=7,
            email="reader@example.com",
            source="github",
        )
        self.assertEqual(result["subscription"], {"id": 42})

    def test_subscribe_without_email_performs_no_write(self) -> None:
        repository = MagicMock(spec=BriefingSubscriptionRepository)

        response = asyncio.run(
            routes_report.subscribe_briefing(
                routes_report.SubscribeRequest(),
                user={"user_id": 7, "email": ""},
                repository=repository,
            )
        )

        self.assertEqual(response.status_code, 400)
        repository.upsert_briefing_subscription.assert_not_called()

    def test_unsubscribe_preserves_not_found_response(self) -> None:
        repository = MagicMock(spec=BriefingSubscriptionRepository)
        repository.cancel_briefing_subscription.return_value = False

        response = asyncio.run(
            routes_report.unsubscribe_briefing(
                routes_report.SubscribeRequest(source="news"),
                user={"user_id": 7},
                repository=repository,
            )
        )

        repository.cancel_briefing_subscription.assert_called_once_with(
            user_id=7,
            source="news",
        )
        self.assertEqual(response.status_code, 404)

    def test_list_subscriptions_is_scoped_to_authenticated_user(self) -> None:
        repository = MagicMock(spec=BriefingSubscriptionRepository)
        repository.get_user_briefing_subscriptions.return_value = [{"id": 42}]

        result = asyncio.run(
            routes_report.get_my_subscriptions(
                user={"user_id": 7},
                repository=repository,
            )
        )

        self.assertEqual(result, {"items": [{"id": 42}]})
        repository.get_user_briefing_subscriptions.assert_called_once_with(user_id=7)

    def test_batch_deduplicates_sources(self) -> None:
        repository = MagicMock(spec=BriefingSubscriptionRepository)
        repository.upsert_briefing_subscription.side_effect = [
            {"id": 1},
            {"id": 2},
        ]

        result = asyncio.run(
            routes_report.batch_subscribe_briefings(
                routes_report.BatchSubscribeRequest(
                    sources=["github", "invalid", "github", "news"],
                ),
                user={"user_id": 7, "email": "reader@example.com"},
                repository=repository,
            )
        )

        self.assertEqual(result["sources"], ["github", "news"])
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            [call.kwargs for call in repository.upsert_briefing_subscription.call_args_list],
            [
                {
                    "user_id": 7,
                    "email": "reader@example.com",
                    "source": "github",
                },
                {
                    "user_id": 7,
                    "email": "reader@example.com",
                    "source": "news",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
