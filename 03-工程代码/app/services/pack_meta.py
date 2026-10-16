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
PLACEHOLDER_PROVIDER_NAME = "{{PROVIDER_NAME}}"
PLACEHOLDER_STATEMENT_ID = "{{STATEMENT_ID}}"
PLACEHOLDER_TASK_ID = "{{TASK_ID}}"

#: **「检测/校验未跑过」的显式取值**。
#: ⚠️ 刻意用「占位」措辞而非 `"unknown"` —— `CFG-006` 交付 schema 的 `compliance.*`
#: 只允许枚举真值（`passed`/`blocked`/`present`/`missing`/`skipped`），**没有「未知」这一档**
#: ⇒ 写占位必然 `schema.pack` BLOCK。这是**已知的口径冲突**（见 `ISSUE-047`），
#: 在项目方裁决「扩展 schema 枚举 / 拆预演包 schema」之前，此处**按纪律保留占位**：
#: 宁可 BLOCK，不可把「没检测」写成「通过」。
PLACEHOLDER_SAFETY = "占位（内容安全双闸结果未取得）"

#: 服务层域键（`meta` 内这些键**一律以服务层真值覆盖**，模型自述值丢弃）。
#: ⚠️ **不含** `title`／`total_duration_ms`／`notes`／`aspect_ratio_default` ——
#: 前两者是模型创作与自洽性判据的载体（`R14`／`R31` 要靠它判），后两者无合规含义。
#: ⚠️ **也不含 `unsupported_task_types`** —— 它属**对外能力声明**而非合规字段，
#: 服务层未配置时**没有真值**；若放进本表，`build_pack_meta` 的默认空列表会把
#: 模型已声明的内容**降级成 `[]`**（既违反交付 schema 的 `minItems: 1`，
#: 又被 `validate_pack` 判 WARN）。该键由 `apply_service_truth` 的 ②′ **单独**处理。
META_SERVICE_KEYS: tuple[str, ...] = (
    "pack_id",
    "created_at",
    "task_type",
    "generator",
    "generation_trace",
)


def apply_service_truth(
    doc: Any,
    truth: dict[str, Any],
    *,
    provider_name: str = "",
    provider_code: str = "",
) -> dict[str, Any] | None:
    """把**服务层真值**覆盖进交付包产物（`T-086` 配套；项目方 2026-10-16 裁决）。

    背景（实测发现，**合规级**）：本模块刻意把备案关联字段写成占位符
    （`safety_check:"占位（…）"`／`marking_check:"占位"`／`statement_id:"{{STATEMENT_ID}}"`），
    但真实产物里这些值**被模型替换成了「看起来已通过」的假值**：

    | 字段 | 服务层注入 | 实测产物（模型自拟） |
    | --- | --- | --- |
    | `compliance.safety_check.input` | `占位（内容安全双闸未接入）` | `passed`（带时间戳） |
    | `compliance.copyright_check.status` | `占位（版权校验未接入）` | `passed` |
    | `compliance.marking_check.explicit` | `占位` | `present` |
    | `compliance.statement_id` | `{{STATEMENT_ID}}` | `ST-001` |
    | `generator.provider_code` | `{{PROVIDER_CODE}}` | `{}`（← 渲染期被抹空，见 `loader` 注记） |
    | `aigc_meta.AIGC.ContentProducer` | 模板给的是占位 | `SW-005` |

    ⚠️ **为什么「假值」比「缺失」危险**：缺失会被门禁拦下；假值会**通过**门禁，
    于是「平台做过内容安全与标识校验」这件事**在产物里成立了、在事实里不成立**。
    ⇒ 合规字段的**写入权必须归服务层**（本工程的占位符纪律要的正是「显式中断反查链」）。

    覆盖范围＝**服务层域**（`_META_SERVICE_KEYS` ＋ `compliance` ＋ `aigc_meta.AIGC`）；
    ⚠️ **模型可影响字段一字不改**（`title`／`total_duration_ms`／`notes`／`shots`／`units`／
    `characters`／`props`／`style_bible`／`forbidden_items`…）—— 本工程第一纪律：**不改写模型输出**。
    本函数**只覆盖、不新增**：模型没输出的服务层域键**不补**（缺键是 `R27`／`R30` 的判据，
    补上等于替模型把洞填了）。

    返回**覆盖清单**（`{字段路径: {"from": 原值, "to": 新值, "changed": bool}}`）；
    `doc` 不是字典（解析失败）时返回 `None`，**不抛错**——形态闸与本函数各有归因通道。
    """
    if not isinstance(doc, dict):
        return None
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        return None

    overrides: dict[str, dict[str, Any]] = {}

    def _set(container: dict[str, Any], key: str, value: Any, path: str) -> None:
        had = key in container
        old = container.get(key)
        if had and old == value:
            overrides[path] = {"from": old, "to": value, "changed": False}
            return
        container[key] = value
        overrides[path] = {"from": old if had else None, "to": value, "changed": True,
                           "was_absent": not had}

    # ① `meta` 的服务层域键（**只覆盖已有的**，不替模型补缺）
    for key in META_SERVICE_KEYS:
        if key in truth and key in meta:
            _set(meta, key, truth[key], f"meta.{key}")

    # ② `meta.compliance`：**整块覆盖**（它是纯合规块，无模型创作成分）
    comp = truth.get("compliance")
    if isinstance(comp, dict) and "compliance" in meta:
        _set(meta, "compliance", comp, "meta.compliance")

    # ②′ `unsupported_task_types` 是**对外能力声明**、**不是合规字段** ⇒ 与 ① 分列：
    #    服务层**有配置**才覆盖；未配置则**保留模型值**。
    #    ⚠️ 反面教训（本批探针实测）：`build_pack_meta` 原先硬编码 `[]`，若一并覆盖会把
    #    模型已声明的 `["keyframe_completion"]` **降级成空列表** —— 既违反交付 schema 的
    #    `minItems: 1`，又被 `validate_pack` 判 WARN（「留空会让客户以为支持」）。
    #    即「**用一个服务层没有真值的字段去覆盖一个有内容的字段**」＝ 以纪律之名降质。
    utt = truth.get("unsupported_task_types")
    if isinstance(utt, list) and utt and "unsupported_task_types" in meta:
        _set(meta, "unsupported_task_types", utt, "meta.unsupported_task_types")

    # ③ `aigc_meta.AIGC` 标识块：`R30` 要求 `Label="1"`、`ProduceID == meta.pack_id`、
    #    `PropagateID == ProduceID`、`ContentPropagator == ContentProducer`。
    #    ⚠️ `ProduceID` **必须与覆盖后的 `meta.pack_id` 同源**，否则会把
    #    「模型自拟但恰好一致」换成「服务层覆盖后不一致」⇒ **制造新的 BLOCK**。
    am = doc.get("aigc_meta")
    aigc = am.get("AIGC") if isinstance(am, dict) else None
    if isinstance(aigc, dict):
        pack_id = meta.get("pack_id", "")
        producer = f"{provider_name or PLACEHOLDER_PROVIDER_NAME}/{provider_code or PLACEHOLDER_PROVIDER_CODE}"
        for key, value in (
            ("Label", "1"),
            ("ContentProducer", producer),
            ("ProduceID", pack_id),
            ("ContentPropagator", producer),
            ("PropagateID", pack_id),
        ):
            if key in aigc:
                _set(aigc, key, value, f"aigc_meta.AIGC.{key}")
        # `ReservedCode1/2` 属预留位，服务层无真值 ⇒ **不动**（保留模型值/空串）
    return overrides


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _split_csv(raw: str) -> list[str]:
    """逗号分隔 → 去空项列表（配置位统一用裸字符串，理由见 `app/core/config.py`）。"""
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def _safety_verdict(safety: dict[str, Any] | None) -> dict[str, Any]:
    """把双闸（`SW-009`／`SW-010`）留痕折算为交付 schema 的 `safety_check` 取值。

    ⚠️ 折算刻意**偏严**：只要检测到命中，一律记 `blocked` —— 即便双闸处于
    「只判不拦」（`guard_enforce=false`）而实际放行了。理由：`compliance.*` 是
    **合规声明**，声明的是「检测结论」而不是「本次是否放行」；
    `flag`（放行并打标）在 `CFG-006` 里**没有对应取值**，按最严记 `blocked`。
    """
    if not isinstance(safety, dict):
        return {"input": PLACEHOLDER_SAFETY, "output": PLACEHOLDER_SAFETY, "checked_at": ""}
    inp = safety.get("input") if isinstance(safety.get("input"), dict) else None
    out = safety.get("output") if isinstance(safety.get("output"), dict) else None
    if inp is None and out is None:
        return {"input": PLACEHOLDER_SAFETY, "output": PLACEHOLDER_SAFETY, "checked_at": ""}
    return {"input": _safety_side(inp), "output": _safety_side(out), "checked_at": _now_iso()}


def _safety_side(side: dict[str, Any] | None) -> str:
    """单侧（输入／输出）折算。取不到该侧留痕时返回占位，**不猜**。"""
    if not isinstance(side, dict):
        return PLACEHOLDER_SAFETY
    if side.get("hit_count"):
        return "blocked"
    if side.get("blocked") or str(side.get("action") or "") in {"block", "replace"}:
        return "blocked"
    return "passed"


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
    safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """装配 `pack_meta`。返回的结构与 `TPL-009` 描述逐字对齐。

    `safety` 为**双闸（`SW-009`／`SW-010`）的实际判定留痕**（调用方传入生成侧的
    `artifact["safety"]`）。⚠️ 不传时 `compliance.safety_check` 写占位 —— 但**能传就必须传**：
    「内容安全检测过没过」是服务层**确知**的事实，写占位等于把已知事实丢弃，
    而交付门禁的判据是 `input/output != "passed" → BLOCK` ⇒ 占位会**恒 BLOCK**。
    """
    artifacts = artifacts or {}
    provider_code = (getattr(settings, "provider_code", "") or "").strip()
    provider_name = (getattr(settings, "provider_name", "") or "").strip()
    unfilled: list[str] = []

    if not provider_code:
        provider_code = PLACEHOLDER_PROVIDER_CODE
        unfilled.append("generator.provider_code")
    if not provider_name:
        provider_name = PLACEHOLDER_PROVIDER_NAME
        unfilled.append("generator.provider")

    if not pack_id:
        # §5.2 编码：<企业码>-PK-<YYYYMMDD>-<8 位短码>
        day = datetime.now().strftime("%Y%m%d")
        pack_id = f"{provider_code}-PK-{day}-{uuid.uuid4().hex[:8].upper()}"

    statement_id = PLACEHOLDER_STATEMENT_ID
    unfilled.append("compliance.statement_id")

    # 未声明任务号时**写占位、不写空串**：`CFG-006` 要求 `task_id` 非空，
    # 空串会被 schema 判 BLOCK，而「无任务号」这一事实**本身**应可识别（同占位符纪律）。
    task_id_value = (task_id or "").strip() or PLACEHOLDER_TASK_ID
    if task_id_value == PLACEHOLDER_TASK_ID:
        unfilled.append("generation_trace.task_id")

    # 对外能力声明：**有配置才写**（不替项目方做产品声明），无配置时留空给调用方决定
    utt = _split_csv(getattr(settings, "unsupported_task_types", "") or "")

    return {
        "pack_id": pack_id,
        "title": title or "",
        "created_at": _now_iso(),
        "task_type": "text_to_video",
        "unsupported_task_types": [],
        "generator": {
            "system": getattr(settings, "app_name", ""),
            "version": getattr(settings, "app_version", "0.1.0"),
            "provider": provider_name,
            "provider_code": provider_code,
        },
        "generation_trace": {
            "session_id": session_id,
            "task_id": task_id_value,
            "stage_chain": stage_chain_of(artifacts, including=stage),
            "templates": templates,
            "model": model,
        },
        "compliance": {
            # ⚠️ `safety_check` 取**双闸实测结果**（能取到就必须取，见函数 docstring）；
            #    取不到才退回占位 —— 而占位在交付 schema 里**没有合法取值**（enum 仅
            #    `passed`/`blocked`）⇒ 会是 `schema.pack` BLOCK。这是**如实**的：
            #    「检测没跑过」本就不该被当成「检测通过」。
            "safety_check": _safety_verdict(safety),
            # ⚠️ `copyright_check`（`T-008`）与 `marking_check`（标识服务）**尚未接入**，
            #    服务层**确实没有真值** ⇒ 只能写占位。占了位就会 BLOCK —— 正确，见上。
            "copyright_check": {"status": "占位（版权校验未接入，见任务 T-008）", "note": ""},
            "marking_check": {"explicit": "占位", "implicit": "占位"},
            "statement_id": statement_id,
        },
        # 对外能力声明（未配置则为空列表；覆盖与否见 `apply_service_truth` ②′）
        "unsupported_task_types": utt,
        "aspect_ratio_default": None,
        # ⚠️ 非契约字段：仅服务层留痕用，投放前由服务层剥离（不进交付包）
        "_unfilled": unfilled,
    }
