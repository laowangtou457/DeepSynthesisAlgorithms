"""内容导出接口 —— **SW-I08**（承载 SW-022，导出到本地，含导出文件显式标识）。

**当前状态：已实现（2026-11-10，任务 `T-006`）**。此前为契约占位（D-005 二期）。

⚠️ 本接口的**唯一职责**是把**已落盘的交付包**（`POST /delivery/pack` 的产物）
按格式重出到 `exports/` 并刷新 `manifest.json` 的 `exports[]`。
它**不重新生成内容、不调用模型、不对接任何下游平台**（`SYS-018`）。

⚠️ **标识不可缺**：每份导出物都必须带显式标识（`SPEC-008 §9.2` 差异化注入位）。
判定**不采信写入假设**，一律回读落盘文件取证（`export_service._evidence`）；
缺标识的记录会以 `explicit_mark=false` 出现在响应与清单里，
由清单判据 `export.mark` 阻断整包导出。
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
from app.services.export_service import (
    SUPPORTED_FORMATS,
    build_exports,
    update_manifest_file,
)

router = APIRouter(prefix="/export", tags=["SW-I08 · 内容导出"])


class ExportRequest(BaseModel):
    """导出请求。

    ⚠️ **不接收下游平台地址与密钥**（`SYS-018`）——只落本地文件。
    """

    pack_dir: str = Field(
        default="",
        description="交付包目录（留空则按配置 `delivery_out_dir` ＋ 会话 id 反查 pack.json）",
    )
    formats: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_FORMATS),
        description="导出格式（json/md/csv/xlsx/txt；pdf 未实现）",
    )
    refresh_manifest: bool = Field(
        default=True,
        description="是否刷新同目录 `manifest.json` 的 `exports[]`（须文件已存在）",
    )


class ExportView(BaseModel):
    """导出结果视图。"""

    pack_id: str
    export_dir: str
    #: 逐文件记录（`explicit_mark=false` ⇒ 该文件**不得**用于对外交付）
    records: list[dict] = Field(default_factory=list)
    #: 未产出／降级说明（如 pdf 未实现、适配参数待核对）
    failed: list[str] = Field(default_factory=list)
    manifest_updated: bool = False


def _find_pack_by_session(base: str, session_id: str) -> Path | None:
    """在交付根目录里按 `meta.generation_trace.session_id` 反查**最新的** `pack.json`。

    ⚠️ **不猜编号**：只认 `pack.json` 里服务层写入的真值（`R30` 同源纪律）。
    """
    for cand in sorted(
        (p for p in Path(base).resolve().glob("*/pack.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            meta = (json.loads(cand.read_text(encoding="utf-8")).get("meta") or {})
        except (OSError, ValueError):
            continue
        trace = meta.get("generation_trace") or {}
        if trace.get("session_id") == session_id:
            return cand
    return None


@router.post("/{session_id}", response_model=Envelope[ExportView], summary="导出会话交付包产物")
def export(
    session_id: str,
    body: ExportRequest | None = None,
    request: Request = None,  # type: ignore[assignment]
    svc: Any = Depends(get_dialogue_service),
) -> Envelope[ExportView]:
    """按格式导出并注入显式标识（`SW-022`）。

    ⚠️ **前置**：须先调用 `POST /delivery/pack` 生成交付包 —— 本接口只认
    **已落盘的 `pack.json`**（导出物是包的派生视图，不是包的替代品）。
    """
    body = body or ExportRequest()
    pack_dir = body.pack_dir or ""

    if not pack_dir:
        settings = request.app.state.settings if request is not None else None
        base = getattr(settings, "delivery_out_dir", "") or ""
        if not base:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "未指定交付目录：请在请求体给 `pack_dir`，或配置 `delivery_out_dir`",
                details={"session_id": session_id},
            )
        hit = _find_pack_by_session(base, session_id)
        if hit is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                f"会话 {session_id} 尚无交付包，请先调用 /delivery/pack",
                details={"session_id": session_id, "searched": base},
            )
        pack_dir = str(hit.parent)

    root = Path(pack_dir).resolve()
    pack_path = root / "pack.json"
    if not pack_path.is_file():
        raise AppError(
            ErrorCode.NOT_FOUND,
            "交付包缺 `pack.json`，无法导出",
            details={"pack_dir": str(root), "session_id": session_id},
        )

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    formats = tuple(f for f in (body.formats or []) if f)
    res = build_exports(pack, pack_path, formats=formats)

    updated = False
    mf = root / "manifest.json"
    if body.refresh_manifest and mf.is_file():
        update_manifest_file(mf, res.records)
        updated = True

    return Envelope(
        request_id=get_request_id(),
        data=ExportView(
            pack_id=str((pack.get("meta") or {}).get("pack_id") or ""),
            export_dir=str(root / "exports"),
            records=res.records,
            failed=res.failed,
            manifest_updated=updated,
        ),
    )


@router.get("/formats", response_model=Envelope[dict], summary="查询支持的导出格式")
def formats() -> Envelope[dict]:
    """支持的格式与**各自标识注入位**（供前端呈现「照做即合规」说明）。"""
    return Envelope(
        request_id=get_request_id(),
        data={
            "formats": list(SUPPORTED_FORMATS),
            "not_implemented": {"pdf": "SPEC-008 §12 T-06 待决，P2 后置"},
            "injection": {
                "json": "顶层 explicit_mark ＋ AIGC 键",
                "md": "文首引用块 ＋ 文末标注；文末「## 元数据」小节",
                "csv": "首行注释行 ＋ 末行重复；末行 #AIGC: JSON",
                "xlsx": "首行合并单元格标识行；工作簿文档属性 keywords（见 ISSUE-073）",
                "txt": "标识区 ＋ 固定分隔行 ＋ 提示词区（两段式）；标识区内 ProduceID 行",
            },
        },
    )
