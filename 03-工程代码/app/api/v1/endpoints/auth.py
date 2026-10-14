"""身份认证接口 —— **SW-I05**（承载 SW-020）。

**当前状态：契约占位，实现未接入**（D-005 二期）。

⚠️ 契约层**分列两类、不得混用**（SW-I05 原文，`RQ5-06`）：
① 账号体系（微信小程序登录 / 手机号登录）；② 真实身份认证（`SYS-003` 规定方式）。
**微信登录不得充抵实名。**
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode

router = APIRouter(prefix="/auth", tags=["SW-I05 · 身份认证"])

_PENDING = "身份认证尚未接入（D-005 二期）"


@router.post("/login", summary="账号登录（未接入）")
def login() -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING)


@router.post("/verify-identity", summary="真实身份认证（未接入；不得以登录替代）")
def verify_identity() -> None:
    raise AppError(ErrorCode.NOT_IMPLEMENTED, _PENDING)
