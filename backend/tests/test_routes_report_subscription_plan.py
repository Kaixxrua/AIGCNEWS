from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import routes_report
from backend.app.api.dependencies import get_report_subscription_plan_service
from backend.app.core.auth import RequireUser
from backend.app.services.membership.subscription_quota import (
    SubscriptionQuotaExceededError,
)
from backend.app.services.report.subscription_plan_service import (
    ReportSubscriptionPlanService,
)


def _run(coro):
    return asyncio.run(coro)


class TestSubscriptionPlanRoute:
    def test_get_plan_endpoint_calls_service(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        service.get_plan.return_value = {
            "can_select_multiple_sources": False,
            "max_sources": 1,
            "active_sources": ["github"],
            "capabilities": [
                {
                    "kind": "rss",
                    "key": "rss-briefing",
                    "selectable": True,
                    "disabled_reason": None,
                },
                {
                    "kind": "account_email",
                    "key": "account-email",
                    "selectable": True,
                    "disabled_reason": None,
                },
            ],
        }

        result = _run(
            routes_report.get_subscription_plan(
                user={"user_id": 7, "email": "reader@example.com"},
                service=service,
            )
        )

        assert result["can_select_multiple_sources"] is False
        assert result["max_sources"] == 1
        assert result["active_sources"] == ["github"]
        assert len(result["capabilities"]) == 2
        service.get_plan.assert_called_once_with(
            user={"user_id": 7, "email": "reader@example.com"}, user_id=7
        )

    def test_get_plan_endpoint_rejects_invalid_user_id(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)

        with pytest.raises(HTTPException) as exc_info:
            _run(
                routes_report.get_subscription_plan(
                    user={"user_id": 0, "email": "reader@example.com"},
                    service=service,
                )
            )

        assert exc_info.value.status_code == 401

    def test_apply_plan_endpoint_requires_email(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        body = routes_report.SubscriptionPlanRequest(
            sources=["github"],
            deliveries=[routes_report.PlanDeliveryRequest(kind="account_email")],
        )

        with pytest.raises(HTTPException) as exc_info:
            _run(
                routes_report.apply_subscription_plan(
                    body=body,
                    user={"user_id": 7, "email": ""},
                    service=service,
                )
            )

        assert exc_info.value.status_code == 400

    def test_apply_plan_endpoint_rejects_invalid_frequency(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        body = routes_report.SubscriptionPlanRequest(
            sources=["github"],
            deliveries=[routes_report.PlanDeliveryRequest(kind="account_email")],
            frequency="weekly",
        )

        with pytest.raises(HTTPException) as exc_info:
            _run(
                routes_report.apply_subscription_plan(
                    body=body,
                    user={"user_id": 7, "email": "reader@example.com"},
                    service=service,
                )
            )

        assert exc_info.value.status_code == 422

    def test_apply_plan_endpoint_maps_quota_exceeded(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        service.apply_plan.side_effect = SubscriptionQuotaExceededError()
        body = routes_report.SubscriptionPlanRequest(
            sources=["github", "news"],
            deliveries=[routes_report.PlanDeliveryRequest(kind="account_email")],
        )

        with pytest.raises(HTTPException) as exc_info:
            _run(
                routes_report.apply_subscription_plan(
                    body=body,
                    user={"user_id": 7, "email": "reader@example.com"},
                    service=service,
                )
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "quota-exceeded"

    def test_apply_plan_endpoint_success(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        service.apply_plan.return_value = {
            "sources": ["github"],
            "deliveries": [
                {"kind": "account_email", "status": "applied"},
                {"kind": "rss", "feed": "briefing", "status": "applied"},
            ],
            "idempotency_key": "key-1",
        }
        body = routes_report.SubscriptionPlanRequest(
            sources=["github"],
            deliveries=[
                routes_report.PlanDeliveryRequest(kind="account_email"),
                routes_report.PlanDeliveryRequest(kind="rss", feed="briefing"),
            ],
            idempotency_key="key-1",
        )

        result = _run(
            routes_report.apply_subscription_plan(
                body=body,
                user={"user_id": 7, "email": "reader@example.com"},
                service=service,
            )
        )

        assert result["sources"] == ["github"]
        assert len(result["deliveries"]) == 2
        assert result["idempotency_key"] == "key-1"
        service.apply_plan.assert_called_once()
        call = service.apply_plan.call_args
        assert call.kwargs["sources"] == ["github"]
        assert len(call.kwargs["deliveries"]) == 2
        assert call.kwargs["idempotency_key"] == "key-1"

    def test_apply_plan_endpoint_maps_invalid_plan_error(self) -> None:
        from backend.app.services.report.subscription_plan_service import (
            InvalidSubscriptionPlanError,
        )

        service = MagicMock(spec=ReportSubscriptionPlanService)
        service.apply_plan.side_effect = InvalidSubscriptionPlanError("bad request")
        body = routes_report.SubscriptionPlanRequest(
            sources=["github"],
            deliveries=[routes_report.PlanDeliveryRequest(kind="account_email")],
        )

        with pytest.raises(HTTPException) as exc_info:
            _run(
                routes_report.apply_subscription_plan(
                    body=body,
                    user={"user_id": 7, "email": "reader@example.com"},
                    service=service,
                )
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "bad request"


class TestSubscriptionPlanRouteOrder:
    """字面量路由 subscription-plan 必须优先于 /report/{briefing_id}（int 路径参数）。

    历史事故：subscription-plan 注册在 {briefing_id} 之后，ASGI 层被 int 解析
    拦截返回 422，直调 handler 的单测无法发现，仅生产探测可见。
    """

    def _build_client(self, service) -> TestClient:
        app = FastAPI()
        app.include_router(routes_report.router, prefix="/api")
        app.dependency_overrides[get_report_subscription_plan_service] = (
            lambda: service
        )
        return TestClient(app)

    def test_get_subscription_plan_not_shadowed_by_briefing_id(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        service.get_plan.return_value = {
            "can_select_multiple_sources": False,
            "max_sources": 1,
            "active_sources": [],
            "capabilities": [],
        }
        client = self._build_client(service)
        client.app.dependency_overrides[RequireUser] = lambda: {
            "user_id": 7,
            "email": "reader@example.com",
        }

        response = client.get("/api/report/subscription-plan")

        assert response.status_code == 200
        service.get_plan.assert_called_once()

    def test_get_subscription_plan_anonymous_rejected(self) -> None:
        service = MagicMock(spec=ReportSubscriptionPlanService)
        client = self._build_client(service)

        response = client.get("/api/report/subscription-plan")

        assert response.status_code in (401, 403)
        service.get_plan.assert_not_called()
