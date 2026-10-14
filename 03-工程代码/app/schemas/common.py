"""跨接口共用的契约：成功信封、健康检查。

`ErrorEnvelope` 见 `app.core.errors`（统一错误信封 SW-I06，全接口共用）。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """成功响应信封。成功响应一律携带 `request_id`，便于全链路追踪。"""

    request_id: str = Field(default="", description="请求追踪 ID（与响应头 X-Request-ID 一致）")
    data: T


class HealthStatus(BaseModel):
    """存活／就绪探针载荷。"""

    status: str = Field(description="ok / degraded")
    app_name: str
    version: str
    inference_backend: str
    checks: dict[str, str] = Field(default_factory=dict)
