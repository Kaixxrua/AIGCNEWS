"""全局未捕获异常处理器：让请求路径 500 落入错误事件采集。

wire 格式与 Starlette ServerErrorMiddleware 默认响应逐字节一致
（纯文本 "Internal Server Error"），属行为兼容变更：
- HTTPException 仍走 FastAPI 内置处理器，完全不受影响；
- 副作用仅测试语义：TestClient(raise_server_exceptions=True) 不再上抛
  已覆盖异常、debug=True 不再返回 traceback 页面。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> PlainTextResponse:
    # logger.exception → root ERROR Handler → error_events 表
    logger.exception(
        "[HTTP] Unhandled exception on %s %s", request.method, request.url.path
    )
    return PlainTextResponse("Internal Server Error", status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unhandled_exception_handler)
