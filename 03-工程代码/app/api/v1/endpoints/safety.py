"""内容安全接口 —— **SW-I03**（承载 SW-009 / SW-010 / SW-011 / SW-017）。

**当前状态：契约占位，实现未接入**（由任务 **T-005** 落地）。

纪律：本接口**显式返回 501**，不做静默放行——「宁可显式报『未接入』，
也不输出一个看起来通过、实则未经检测的安全结论」。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix="/safety", tags=["SW-I03 · 内容安全"])

_PENDING = "内容安全双闸尚未接入（任务 T-005）；本接口不提供任何安全判定结论"


@router.post("/inspect", summary="输入／输出内容检测（未接入）")
def inspect() -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING)


@router.get("/policy", summary="安全策略查询（未接入）")
def policy() -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING)
