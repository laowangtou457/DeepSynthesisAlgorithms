"""交付包元数据（`pack_meta`）装配。

⚠️ 纪律来源：`TPL-009_shot_prompt_v1.yaml` 硬性约束 12 ——
「元数据不得编造：pack_id／created_at／session_id／task_id／statement_id／provider_code／
compliance.* 一律取自**服务层注入**的 pack_meta；缺失时写占位符并登记，不得自拟」。

本模块就是那句「服务层注入」的实现点，取值策略分两档：

| 档 | 取值 | 处理 |
| --- | --- | --- |
| 服务层**确知** | session_id / created_at / 模板链 / 模型名与版本 | 如实注入 |
| 服务层**不知** | 企业码 / 声明编号等备案关联字段 | **写占位符**（`{{...}}`）并计入 `_unfilled` 列表，**绝不编造** |

⚠️ 占位符与「编号 → 生成记录反查链」的关系：占位符使链条**显式中断**，
便于备案举证时一眼看出哪些字段尚未由配置补齐；若填看似合理的假值，
反查会在不知情的情况下断链（比留空危险得多）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

#: 链路阶段顺序（用于推导 `stage_chain`）。
CHAIN_ORDER: tuple[str, ...] = ("synopsis", "script", "storyboard", "shot_prompt", "revise")

#: 企业码占位符（脱敏版不得写真实企业标识）。
PLACEHOLDER_PROVIDER_CODE = "{{PROVIDER_CODE}}"
PLACEHOLDER_STATEMENT_ID = "{{STATEMENT_ID}}"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stage_chain_of(artifacts: dict[str, Any], *, including: str | None = None) -> list[str]:
    """按链路顺序推导已完成的阶段链；`including` 用于把「即将写入」的阶段计入。"""
    present = set(artifacts)
    if including:
        present.add(including)
    return [s for s in CHAIN_ORDER if s in present]


def build_pack_meta(
    *,
    session_id: str,
    stage: str,
    templates: list[dict[str, str]],
    model: dict[str, Any],
    settings: Any,
    artifacts: dict[str, Any] | None = None,
    task_id: str | None = None,
    title: str | None = None,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """装配 `pack_meta`。返回的结构与 `TPL-009` 描述逐字对齐。"""
    artifacts = artifacts or {}
    provider_code = (getattr(settings, "provider_code", "") or "").strip()
    unfilled: list[str] = []

    if not provider_code:
        provider_code = PLACEHOLDER_PROVIDER_CODE
        unfilled.append("generator.provider_code")

    if not pack_id:
        # §5.2 编码：<企业码>-PK-<YYYYMMDD>-<8 位短码>
        day = datetime.now().strftime("%Y%m%d")
        pack_id = f"{provider_code}-PK-{day}-{uuid.uuid4().hex[:8].upper()}"

    statement_id = PLACEHOLDER_STATEMENT_ID
    unfilled.append("compliance.statement_id")

    return {
        "pack_id": pack_id,
        "title": title or "",
        "created_at": _now_iso(),
        "task_type": "text_to_video",
        "unsupported_task_types": [],
        "generator": {
            "system": getattr(settings, "app_name", ""),
            "version": getattr(settings, "app_version", "0.1.0"),
            "provider": getattr(settings, "provider_name", ""),
            "provider_code": provider_code,
        },
        "generation_trace": {
            "session_id": session_id,
            "task_id": task_id or "",
            "stage_chain": stage_chain_of(artifacts, including=stage),
            "templates": templates,
            "model": model,
        },
        "compliance": {
            "safety_check": {
                "input": "占位（内容安全双闸未接入，见任务 T-005）",
                "output": "占位（内容安全双闸未接入，见任务 T-005）",
                "checked_at": "",
            },
            "copyright_check": {"status": "占位（版权校验未接入，见任务 T-008）", "note": ""},
            "marking_check": {"explicit": "占位", "implicit": "占位"},
            "statement_id": statement_id,
        },
        "aspect_ratio_default": None,
        # ⚠️ 非契约字段：仅服务层留痕用，投放前由服务层剥离（不进交付包）
        "_unfilled": unfilled,
    }
