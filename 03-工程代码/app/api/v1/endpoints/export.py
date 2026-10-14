"""内容导出接口 —— **SW-I08**（承载 SW-022，导出到本地）。

**当前状态：契约占位，实现未接入**（D-005 二期）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix="/export", tags=["SW-I08 · 内容导出"])

_PENDING = "内容导出尚未接入（D-005 二期）"


@router.post("/{session_id}", summary="导出会话产物（未接入）")
def export(session_id: str) -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING, details={"session_id": session_id})
