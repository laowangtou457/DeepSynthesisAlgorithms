"""类型化错误体系与统一错误信封。

对应需求 **SW-I06「统一错误信封」**：所有接口共用同一结构，
**绝不向客户端暴露堆栈或内部细节**（ARCH-003 §5.3）。

结构：

    {"error": {"code", "message", "details", "request_id", "retryable"}}

错误码在此集中登记（唯一真值来源）；散落在端点内的字面量错误码属缺陷。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """错误码登记表。新增错误码须同时在此与 `_DEFAULT_STATUS` 登记。"""

    # ---- 通用 ----
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"

    # ---- 会话与状态机（SW-001 / SW-003）----
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    ROLLBACK_TARGET_INVALID = "ROLLBACK_TARGET_INVALID"

    # ---- 生成与模板（SW-I02）----
    TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
    TEMPLATE_VARIABLE_MISSING = "TEMPLATE_VARIABLE_MISSING"
    GENERATION_FAILED = "GENERATION_FAILED"

    # ---- 内容安全（SW-I03）----
    GUARD_INPUT_BLOCKED = "GUARD_INPUT_BLOCKED"
    GUARD_OUTPUT_BLOCKED = "GUARD_OUTPUT_BLOCKED"
    #: `SW-017` 含糊时澄清（`CFG-008`「意图不唯一时不猜、不择优，转 `guard_clarify_v1` 追问」）。
    #: 2026-10-16 项目方裁决 `ISSUE-035` ③ 取**口径 A**（必填项缺失即含糊）时落地。
    #: ⚠️ **不是拦截**（内容本身可能安全，只是指令不完整）⇒ 状态码取 **409 Conflict**
    #:   而非 4xx 语义错误；`details.missing_items` 给出缺失项供前端渲染追问。
    #: ⚠️ 契约要求「澄清期 `change_log` 必须为空」⇒ 编排层抛本码时**不写产物、不写 history**。
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"

    # ---- 交付与导出（SW-I04 / SW-I08）----
    DELIVERY_PACK_INVALID = "DELIVERY_PACK_INVALID"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


#: 错误码 → 默认 HTTP 状态码。**唯一定义处**，端点内不得另行裁决。
_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.SESSION_EXPIRED: 410,
    ErrorCode.INVALID_STATE_TRANSITION: 409,
    ErrorCode.CONFIRMATION_REQUIRED: 409,
    ErrorCode.ROLLBACK_TARGET_INVALID: 409,
    ErrorCode.TEMPLATE_NOT_FOUND: 404,
    ErrorCode.TEMPLATE_VARIABLE_MISSING: 422,
    ErrorCode.GENERATION_FAILED: 502,
    ErrorCode.GUARD_INPUT_BLOCKED: 422,
    ErrorCode.GUARD_OUTPUT_BLOCKED: 451,
    ErrorCode.CLARIFICATION_NEEDED: 409,
    ErrorCode.DELIVERY_PACK_INVALID: 422,
    ErrorCode.NOT_IMPLEMENTED: 501,
}

#: 前端约定（ARCH-003 §5.3）：4xx 不重试（429 按 Retry-After 除外）；
#: 5xx 与网络失败最多重试 3 次、指数退避；仅 `retryable=true` 允许自动重试。
_RETRYABLE: frozenset[ErrorCode] = frozenset(
    {ErrorCode.INTERNAL_ERROR, ErrorCode.GENERATION_FAILED}
)


class ErrorDetail(BaseModel):
    """错误信封内层。`details` 只放可公开的结构化信息（如限额与实测值）。"""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    retryable: bool = False


class ErrorEnvelope(BaseModel):
    """统一错误信封（SW-I06）。所有 4xx / 5xx 响应体均为此结构。"""

    error: ErrorDetail


class AppError(Exception):
    """业务异常基类。抛出即由全局异常处理器转换为统一错误信封。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = (
            status_code if status_code is not None else _DEFAULT_STATUS.get(code, 500)
        )
        self.details = details or {}
        self.retryable = _RETRYABLE.__contains__(code) if retryable is None else retryable

    def to_envelope(self, request_id: str = "") -> ErrorEnvelope:
        return ErrorEnvelope(
            error=ErrorDetail(
                code=self.code.value if isinstance(self.code, ErrorCode) else str(self.code),
                message=self.message,
                details=self.details,
                request_id=request_id,
                retryable=self.retryable,
            )
        )


def error_status(code: ErrorCode) -> int:
    """供异常处理器查询错误码对应的 HTTP 状态。"""
    return _DEFAULT_STATUS.get(code, 500)
