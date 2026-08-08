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


class ApiDocsExposureContracts(unittest.TestCase):
    """交互式 API 文档/OpenAPI schema 暴露面：仅开发环境开放。"""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_docs_gate_matches_env_predicate(self) -> None:
        from backend.app.core.config import settings

        docs_expected = settings.env.lower() in ("development", "dev")
        self.assertEqual(app.docs_url is not None, docs_expected)
        self.assertEqual(app.redoc_url is not None, docs_expected)
        self.assertEqual(app.openapi_url is not None, docs_expected)

    def test_production_never_serves_docs_or_openapi(self) -> None:
        from backend.app.core.config import settings

        if settings.env.lower() in ("development", "dev"):
            self.skipTest("开发环境文档开放，暴露面用例不适用")
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
