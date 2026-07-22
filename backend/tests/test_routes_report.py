from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request

from backend.app.api import routes_report
from backend.app.services.email_service import EmailService


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


if __name__ == "__main__":
    unittest.main()
