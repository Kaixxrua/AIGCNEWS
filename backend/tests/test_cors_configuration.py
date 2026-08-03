"""CORS 白名单配置契约测试：不再允许任意来源。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.main import app


class CorsConfigurationContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _preflight(self, origin: str):
        return self.client.options(
            "/api/ready",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    def test_arbitrary_origin_is_not_allowed(self) -> None:
        response = self._preflight("https://evil.example.com")
        allow_origin = response.headers.get("access-control-allow-origin", "")
        self.assertNotEqual(allow_origin, "*")
        self.assertNotIn("evil.example.com", allow_origin)

    def test_no_wildcard_on_simple_requests(self) -> None:
        # /api/live 无运行时依赖，可在未执行 lifespan 的测试客户端中使用
        response = self.client.get(
            "/api/live", headers={"Origin": "https://evil.example.com"}
        )
        self.assertNotEqual(
            response.headers.get("access-control-allow-origin", ""), "*"
        )

    def test_configured_frontend_origin_is_allowed(self) -> None:
        from backend.app.core.config import settings

        configured = [
            origin.strip()
            for origin in settings.cors_allowed_origins.split(",")
            if origin.strip()
        ]
        self.assertTrue(configured, "CORS 白名单不能为空")
        response = self._preflight(configured[0])
        self.assertEqual(
            response.headers.get("access-control-allow-origin"), configured[0]
        )

    def test_production_domains_are_whitelisted_by_default(self) -> None:
        from backend.app.core.config import settings

        self.assertIn("https://aigcnews.cn", settings.cors_allowed_origins)


if __name__ == "__main__":
    unittest.main()
