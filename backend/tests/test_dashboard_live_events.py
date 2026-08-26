from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_dashboard


class _FakeBroadcaster:
    """可控的 broadcaster 替身：按脚本 yield 帧后正常结束生成器。

    TestClient 对「永不结束的流」取消语义不可靠（close 不保证即时 cancel
    挂起的 await），断连清理已由 broadcaster.subscribe 单测覆盖；这里钉住
    wire format 与响应头契约即可。
    """

    def __init__(self, frames: list[dict[str, Any] | None]) -> None:
        self.frames = frames
        self.cleaned_up = False

    async def subscribe(self) -> AsyncIterator[dict[str, Any] | None]:
        try:
            for frame in self.frames:
                yield frame
        finally:
            self.cleaned_up = True


def _make_app(broadcaster: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.state.live_stats_broadcaster = broadcaster
    return app


class DashboardLiveEventsContractTests(unittest.TestCase):
    def test_returns_503_when_broadcaster_unavailable(self) -> None:
        app = _make_app(None)
        response = TestClient(app).get("/api/dashboard/live-events")
        self.assertEqual(response.status_code, 503)

    def test_stream_headers_and_frame_wire_format(self) -> None:
        payload_first = {"total_documents": 7, "mcp_total_calls": 3}
        payload_second = {"total_documents": 8, "mcp_total_calls": 3}
        broadcaster = _FakeBroadcaster([payload_first, None, payload_second])
        app = _make_app(broadcaster)

        with TestClient(app).stream("GET", "/api/dashboard/live-events") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers["content-type"], "text/event-stream; charset=utf-8"
            )
            # 本机 nginx 回源链必须关闭代理缓冲，否则流被截断
            self.assertEqual(response.headers["x-accel-buffering"], "no")
            self.assertEqual(response.headers["cache-control"], "no-cache")

            # SSE 帧以空行分隔，与传输分块无关（TestClient 会合并小 chunk）
            body = "".join(response.iter_text())

        frames = [frame for frame in body.split("\n\n") if frame]
        self.assertEqual(frames[0], "retry: 3000")
        self.assertEqual(
            frames[1], f"data: {json.dumps(payload_first, ensure_ascii=False)}"
        )
        self.assertEqual(frames[2], ": hb")
        self.assertEqual(
            frames[3], f"data: {json.dumps(payload_second, ensure_ascii=False)}"
        )
        self.assertEqual(len(frames), 4)

        # 订阅生成器结束后必须完成清理（finally 注销订阅者）
        self.assertTrue(broadcaster.cleaned_up)


if __name__ == "__main__":
    unittest.main()
