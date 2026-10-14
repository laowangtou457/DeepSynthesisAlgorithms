"""产物交付包接口 —— **SW-I04**（交付四件套，不直连下游平台）。

**当前状态：契约占位，实现未接入**（由任务 **T-006** 落地）。

⚠️ 本接口**不对接任何下游平台 API、不托管下游密钥与成片**（SYS-018）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix="/delivery", tags=["SW-I04 · 产物交付"])

_PENDING = "交付四件套打包尚未接入（任务 T-006）"


@router.post("/pack", summary="生成交付包（未接入）")
def pack() -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING)


@router.get("/manifest/{pack_id}", summary="查询交付包清单（未接入）")
def manifest(pack_id: str) -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING, details={"pack_id": pack_id})
