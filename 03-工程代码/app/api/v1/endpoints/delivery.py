"""产物交付包接口 —— **SW-I04**（交付四件套，不直连下游平台）。

**当前状态：已实现**（任务 **T-006**，2026-11-03）。

⚠️ 本接口**不对接任何下游平台 API、不托管下游密钥与成片**（`SYS-018`）——
只把**交付包文件**落到本地目录，由人工／外部流程取走。

⚠️ **交付包在正式交付意义上是「预演包」**：`compliance.*`／`pack_id`／`statement_id`
的占位**如实保留**（`PRO-007` 根因 A／B 待项目方裁决）⇒ 响应里的
`is_preview=true` 与 `unfilled` 列表**必须**被调用方读走，不得省略。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_dialogue_service
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_request_id
from app.schemas.common import Envelope
from app.services.delivery_service import PREVIEW_NOTE, DeliveryResult, pack_delivery

router = APIRouter(prefix="/delivery", tags=["SW-I04 · 产物交付"])


class PackRequest(BaseModel):
    """打包请求。

    ⚠️ **不接收任何下游平台地址与密钥**（`SYS-018`）——
    交付包只落本地文件，由外部流程取走。
    """

    out_dir: str = Field(
        default="",
        description=(
            "交付目录（留空则用配置 `delivery_out_dir`，"
            "默认 `<工程>/.wb-e2e/delivery`）。"
        ),
    )


class PackView(BaseModel):
    """打包结果视图。"""

    pack_id: str
    pack_dir: str
    files: list[str] = Field(default_factory=list)
    #: ⚠️ **未回填的占位字段**（如 `generator.provider_code`／`compliance.statement_id`）
    unfilled: list[str] = Field(default_factory=list)
    #: ⚠️ **是否预演包**（true ⇒ **不得用于正式交付**，须回填后复检）
    is_preview: bool = True
    pack_bytes: int = 0
    preview_note: str = Field(default="", description="预演包留痕说明（须随包保留）")


@router.post(
    "/pack",
    response_model=Envelope[PackView],
    summary="生成交付包（四件套）",
)
def pack(
    session_id: str,
    body: PackRequest | None = None,
    request: Request = None,  # type: ignore[assignment]
    svc: Any = Depends(get_dialogue_service),
) -> Envelope[PackView]:
    """把会话的 `shot_prompt` 产物打包成交付四件套。

    ⚠️ **前置**：会话须已产出 `shot_prompt`（形态 `pack`）——
    服务层真值（`compliance.*`／`aigc_meta`）在编排层生成时已注入，本接口**不二次生成**。
    """
    settings = request.app.state.settings if request is not None else None
    out_dir = (body.out_dir if body else "") or ""
    if not out_dir:
        out_dir = getattr(settings, "delivery_out_dir", "") or ""
    if not out_dir:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "未指定交付目录：请在请求体给 `out_dir`，或配置 `delivery_out_dir`",
            details={"session_id": session_id},
        )
    result: DeliveryResult = pack_delivery(
        svc=svc, session_id=session_id, out_dir=out_dir, settings=settings
    )
    return Envelope(
        request_id=get_request_id(),
        data=PackView(
            pack_id=result.pack_id,
            pack_dir=result.pack_dir,
            files=result.files,
            unfilled=result.unfilled,
            is_preview=result.is_preview,
            pack_bytes=result.pack_bytes,
            preview_note=PREVIEW_NOTE if result.is_preview else "",
        ),
    )


@router.get(
    "/manifest/{pack_id}",
    response_model=Envelope[dict],
    summary="查询交付包清单",
)
def manifest(
    pack_id: str,
    out_dir: str = "",
    request: Request = None,  # type: ignore[assignment]
) -> Envelope[dict]:
    """读回已打包交付包的清单（`manifest.json`）。

    ⚠️ **只读本地文件**——不反查会话、不重新生成。
    ⚠️ `out_dir` 留空时用配置 `delivery_out_dir`。
    """
    settings = request.app.state.settings if request is not None else None
    base = out_dir or getattr(settings, "delivery_out_dir", "") or ""
    if not base:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "未指定交付目录：请给查询参数 `out_dir`，或配置 `delivery_out_dir`",
            details={"pack_id": pack_id},
        )
    safe = "".join(ch for ch in pack_id if ch.isalnum() or ch in "-_")[:64]
    path = Path(base).resolve() / safe / "manifest.json"
    if not path.is_file():
        raise AppError(
            ErrorCode.NOT_FOUND,
            f"交付包 {pack_id} 的清单不存在",
            details={"pack_id": pack_id, "path": str(path)},
        )
    return Envelope(request_id=get_request_id(), data=json.loads(path.read_text(encoding="utf-8")))
