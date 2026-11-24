# -*- coding: utf-8 -*-
"""**覆盖分配器**（批次 2 一期）：门禁判据族的**确定性兜底改写**（单点实现）。

靶面（2026-11-23 真机 5 轮实证锁定的剩余失败族，`DEV-20261123-004`）：
- **光线覆盖 0%**（gate.lighting 族，`ISSUE-089` 末段同族）：单元内空 `lighting` 镜
  用**同单元首个非空值**回填（同一场景光线连续，属确定性映射而非创作）；
- **台词语速超限**（`R15 DIALOGUE_SPEED`）：只延 `duration_ms`——判据报错文本明文
  修法「只延时不改画面（§4.5）」，纯算术、零创作干预。

三条纪律：
1. **阈值同源**：一切阈值/上限 `import` 自 `prompts.validate_output`（`GATE`／
   `DIALOGUE_SPEED_MAX`／`DURATION_MAX_MS`），**不抄第二份**——判据改阈值，
   本层行为随之变（同源锁测试钉住引用关系）；
2. **最小干预**：光线只补「达标所需最少镜数」（`ceil(limit×n)−已有命中`），
   不多补一台；全单元皆空 ⇒ **不伪造**，原样留给门禁拒；语速延展到
   `DURATION_MAX_MS` 仍不够 ⇒ 不动（无从机械修复，如实交给门禁/重采）；
3. **改写不裁决**：本层**不判达标**——改写后由既有门禁复算说了算；
   修过必留痕（逐镜 before/after），noop 返回 `None`（同 `amp_norm` 纪律：
   不污染每次生成，不静默修补）。

分期说明：运镜多样性轮换（单一运镜占比超限的改写）涉创作面更大干预，
**留批次 2 二期**，一期不动。
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any

# ⚠️ 同源引用（纪律 1）：不得在本模块复制阈值字面量。
# `prompts/` 不是可 import 包（既有口径），按 `quality_gate` 同款机制以**文件路径**
# 加载判据模块 ⇒ 同一份文件、同源取值（判据改阈值，本层行为随之变）。
_CODE_DIR = Path(__file__).resolve().parents[2]  # app/services/ → app/ → 03-工程代码


def _load_validator() -> Any:
    path = _CODE_DIR / "prompts" / "validate_output.py"
    spec = importlib.util.spec_from_file_location(
        "_coverage_reconcile_validate_output", path
    )
    assert spec is not None and spec.loader is not None, f"判据模块缺失：{path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_VO = _load_validator()
DIALOGUE_SPEED_MAX = _VO.DIALOGUE_SPEED_MAX
DURATION_MAX_MS = _VO.DURATION_MAX_MS
GATE = _VO.GATE


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def reconcile_coverage_gaps(doc: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    """对解析后的分镜/交付包形态跑两族确定性兜底改写。

    返回 `(是否改动, 明细 | None)`；**原地修改** `doc["shots"]` 内的镜条目，
    由调用方重序列化（与既有归一化族同口径）。noop ⇒ `(False, None)`。
    """
    shots = doc.get("shots")
    if not isinstance(shots, list) or not shots:
        return False, None

    stretched: list[dict[str, Any]] = []
    backfilled: list[dict[str, Any]] = []

    # ---- ① R15 台词语速兜底：只延 `duration_ms`，不改画面/台词 ----
    for r in shots:
        if not isinstance(r, dict):
            continue
        d = r.get("dialogue")
        d = d.strip() if isinstance(d, str) else ""
        ms = r.get("duration_ms")
        # 与 R15 同一输入域：非字符串台词按「无台词」跳过（类型防御同 `ISSUE-049` 口径）
        if not d or not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms <= 0:
            continue
        if len(d) / (ms / 1000.0) <= DIALOGUE_SPEED_MAX:
            continue
        # 达标所需最小时长：ms ≥ 字数×1000/语速上限；且 **R12 整秒约束**（`duration_ms`
        # 必须 1000 整数倍）⇒ 再向上取整到整秒（ceil(a/b·c) 恒等式：ceil(len/上限)×1000）。
        # 105 字：ceil(105/9)=12 ⇒ 12000ms（语速 8.75 ≤ 9 且为整秒，两判据同时成立）。
        need = math.ceil(len(d) / DIALOGUE_SPEED_MAX) * 1000
        if need > DURATION_MAX_MS:
            continue  # 时长区间装不下 ⇒ 无从机械修复，如实留给门禁
        if need > ms:
            r["duration_ms"] = need
            stretched.append(
                {"shot_id": r.get("shot_id"), "chars": len(d),
                 "ms_before": ms, "ms_after": need}
            )

    # ---- ② 光线覆盖兜底：同单元首个非空 `lighting` 回填（补最少镜数） ----
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in shots:
        if isinstance(r, dict):
            groups.setdefault(str(r.get("unit_id") or ""), []).append(r)
    limit = GATE["光线覆盖"]
    for uid, rows in groups.items():
        n = len(rows)
        if not n:
            continue
        empty_rows = [r for r in rows if not _nonempty(r.get("lighting"))]
        if not empty_rows:
            continue
        shortfall = math.ceil(limit * n) - (n - len(empty_rows))
        if shortfall <= 0:
            continue  # 该单元已达标 ⇒ 最小干预，一台不补
        fill = next(
            (x["lighting"].strip() for x in rows if _nonempty(x.get("lighting"))),
            None,
        )
        if not fill:
            continue  # 全单元皆空 ⇒ 不伪造创作内容，如实留给门禁
        for r in empty_rows[:shortfall]:
            r["lighting"] = fill
            backfilled.append(
                {"shot_id": r.get("shot_id"), "unit_id": uid, "value": fill}
            )

    if not stretched and not backfilled:
        return False, None
    return True, {
        "changed": True,
        "dialogue_stretched": stretched,
        "lighting_backfilled": backfilled,
    }
