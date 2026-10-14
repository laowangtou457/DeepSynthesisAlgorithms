"""请求上下文中间件：请求 ID 贯穿 + 访问日志（ARCH-003 §3.4）。

分层纪律：本层**不含业务逻辑**，只做 HTTP 语义转换。
未捕获异常的兜底转换在 `app.main` 中以全局异常处理器注册（统一错误信封）。
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, reset_request_id, set_request_id

#: 请求 ID 头。客户端可自带以串联链路；缺失则服务端生成。
REQUEST_ID_HEADER = "X-Request-ID"


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求建立 request_id 上下文，并在响应回写头与记录访问日志。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or _new_request_id()
        token = set_request_id(rid)
        request.state.request_id = rid
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            logger = get_logger("http")
            logger.info(
                "http_request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                },
            )
            reset_request_id(token)
