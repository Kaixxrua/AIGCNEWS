from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api.exception_handlers import register_exception_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @app.get("/client-error")
    async def client_error() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    return app


class UnhandledExceptionHandlerTests(unittest.TestCase):
    def test_unhandled_exception_matches_starlette_default_500_wire_format(self) -> None:
        # raise_server_exceptions=False：ServerErrorMiddleware 响应后仍会上抛
        # 让 uvicorn 记日志，测试客户端这里只需观察 wire 格式。
        response = TestClient(_make_app(), raise_server_exceptions=False).get("/boom")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.text, "Internal Server Error")
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertNotIn("kaboom", response.text)

    def test_unhandled_exception_is_logged_for_error_event_capture(self) -> None:
        with patch("backend.app.api.exception_handlers.logger") as logger_mock:
            TestClient(_make_app(), raise_server_exceptions=False).get("/boom")

        # logger.exception → root ERROR Handler → error_events 表
        logger_mock.exception.assert_called_once()
        args = logger_mock.exception.call_args.args
        self.assertEqual(args[1:], ("GET", "/boom"))

    def test_http_exception_still_uses_fastapi_default_handler(self) -> None:
        response = TestClient(_make_app(), raise_server_exceptions=False).get(
            "/client-error"
        )

        self.assertEqual(response.status_code, 418)
        self.assertEqual(response.json(), {"detail": "teapot"})


if __name__ == "__main__":
    unittest.main()
