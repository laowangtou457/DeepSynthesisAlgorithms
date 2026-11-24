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

分期说明：**运镜轮换已于批次 2 二期实装**（③，2026-11-24，真机 r3 现场 2 镜单元全 static
实证靶面）——同样走「确定性最小改写」：只改超出允许数的镜、替换值按 `MOVE_ENUM` 枚举
顺序确定性选取；创作面边界（替换值不读画面语义）在函数 docstring 如实登记。
"""
from __future__ import annotations

import importlib.util
import math
from collections import Counter
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

    # ---- ③ 运镜轮换（批次 2 二期）：R11 单元重复 / R19 静止镜·单一运镜·类型数 / 运镜覆盖 ----
    rotated: list[dict[str, Any]] = []
    _rotate_camera_moves(shots, rotated)

    if not stretched and not backfilled and not rotated:
        return False, None
    return True, {
        "changed": True,
        "dialogue_stretched": stretched,
        "lighting_backfilled": backfilled,
        "camera_rotated": rotated,
    }


def _cam_move(r: dict[str, Any]) -> Any:
    cam = r.get("camera")
    return cam.get("move") if isinstance(cam, dict) else None


def _set_cam_move(r: dict[str, Any], value: str) -> None:
    cam = r.get("camera")
    if not isinstance(cam, dict):
        cam = {}
        r["camera"] = cam
    cam["move"] = value


def _rotate_camera_moves(shots: list[Any], rotated: list[dict[str, Any]]) -> None:
    """运镜族确定性兜底改写（批次 2 二期）。

    靶面＝真机 r3 现场形态（2026-11-24，`DEV-20261124-003`）：2 镜单元全 static，
    同时踩 R11（单元内重复）＋R19 静止镜超限＋R19 运镜类型数不足——一个改写动作
    可同时缓解多项。

    **待改集合**（最小干预，分两步收敛）：
    第一步无条件纳入——
    ① 单元内 `camera.move` 重复的后续镜（R11，每单元保留首个）；
    ② 整片 `static` 超出 `_allow(静止镜占比, n)` 的尾部镜（R19）；
    ③ `move` 缺失镜（R19 运镜覆盖门槛 1.00＝每镜都要有）；
    第二步**模拟改后**仍超限才补入——④ 单一运镜：按「待改镜不计原值」模拟改后计数，
    某类型仍超 `_allow(单一运镜占比, n)` ⇒ 从该类型非待改镜尾部补入差额
    （避免把「② 改 static 已顺带解决单一超限」的镜重复拖入；首版无条件纳入曾被
    快测抓出违反最小干预：r3 场景 1 镜可过却被改 2 镜）。
    类型数缺口（R19 下限 `min(运镜类型数, max(2, ⌈n/4⌉))`）在**分配完成后复算**，
    仍不足 ⇒ 从计数最多类型的非待改镜尾部补差额再增量分配。

    **替换值分配**（确定性）：按 `MOVE_ENUM` 枚举顺序取第一个满足——
    非 `NO_PARAM_MOVES`（不引入 static/pov，规避 R17 参数面）∧ 不与本单元已用/已分配
    值重复（R11）∧ 改后该类型计数不超 `_allow(单一运镜占比, n)`（不制造新超限）。
    未出现过的类型天然排在前面被优先选中 ⇒ 顺带填补类型缺口。

    ⚠️ **如实登记的边界**：替换值是纯结构修复（不读画面语义上下文）——与一期光线
    回填「同单元值不读语义」同水平；语义适当性由门禁复算与人工抽检兜底。
    改写不裁决：改后由既有门禁复算说了算（用例以同文件 `_gate_check` 复算自证）。
    """
    rows = [r for r in shots if isinstance(r, dict)]
    n = len(rows)
    if not n:
        return
    # ⚠️ 三态化同源口径：R19/R11 在镜数低于分母基线时门禁 **not_tested** ⇒ 本层同口径
    # 不动（改写不裁决的门禁不测形态；1~5 镜短片上「类型数 ≥ 2」甚至不可满足）。
    if n < _VO.N_MIN_DENOMINATOR:
        return
    allow = _VO._allow  # 同源引用：容差算法与判据同一实现，不抄第二份

    def cur(i: int) -> Any:
        return _cam_move(rows[i])

    # ---- 第一步：无条件待改集合 ----
    must: set[int] = set()
    by_unit: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_unit.setdefault(str(r.get("unit_id") or ""), []).append(i)
    # ① R11 单元内重复：保留每单元首个
    for idxs in by_unit.values():
        seen: set[str] = set()
        for i in idxs:
            m = cur(i)
            if m and m in seen:
                must.add(i)
            elif m:
                seen.add(m)
    # ② 静止镜超限（尾部）
    statics = [i for i in range(n) if cur(i) == "static"]
    st_over = len(statics) - allow(GATE["静止镜占比"], n)
    if st_over > 0:
        must.update(statics[-st_over:])
    # ③ move 缺失（运镜覆盖门槛 1.00）
    must.update(i for i in range(n) if not cur(i))

    # ---- 第二步：模拟改后（待改镜不计原值）单一运镜仍超限 ⇒ 尾部补入差额 ----
    sim = Counter(m for i in range(n) if i not in must and (m := cur(i)))
    for t, c in list(sim.items()):
        over = c - allow(GATE["单一运镜占比"], n)
        if over > 0:
            pool = [i for i in range(n) if cur(i) == t and i not in must]
            must.update(pool[-over:])
    if not must:
        return

    # ---- 替换值分配（确定性：MOVE_ENUM 枚举顺序；支持增量调用） ----
    assigned: set[int] = set()

    def assign(new_idxs: set[int]) -> None:
        unit_used: dict[str, set[str]] = {}
        for uid, idxs in by_unit.items():
            used = set()
            for i in idxs:
                m = cur(i)
                if m and i not in new_idxs and i not in assigned:
                    used.add(m)
            unit_used[uid] = used
        for i in assigned:  # 已分配镜的新值计入「单元已用」与计数
            m = cur(i)
            if m:
                unit_used[str(rows[i].get("unit_id") or "")].add(m)
        # ⚠️ 计数**全量初始化**（含待改镜原值），分配时对该镜「原值退出＋新值进入」
        # 增量增减——首版把待改镜原值排除在初始化外、又对它减 1 ⇒ 双重扣除，
        # 单一运镜上限检查失效（快测抓出：SH12 被错配成 push_in 仍 6/12 超限）。
        counts: Counter[str] = Counter(m for m in (cur(i) for i in range(n)) if m)
        for i in sorted(new_idxs):
            r = rows[i]
            uid = str(r.get("unit_id") or "")
            before = cur(i)
            chosen = None
            for cand in _VO.MOVE_ENUM:
                if cand in _VO.NO_PARAM_MOVES:
                    continue
                if cand in unit_used[uid]:
                    continue  # R11：单元内不重复
                if counts.get(cand, 0) + 1 > allow(GATE["单一运镜占比"], n):
                    continue  # 不制造新的单一运镜超限
                chosen = cand
                break
            if not chosen:
                continue  # 无合法候选（理论不可达：18 类候选 × allow ≥ 1）⇒ 原样留给门禁
            _set_cam_move(r, chosen)
            assigned.add(i)
            if before:
                counts[before] -= 1  # 该镜原值退出计数（缺失镜原值不计）
            counts[chosen] = counts.get(chosen, 0) + 1
            unit_used[uid].add(chosen)
            rotated.append(
                {"shot_id": r.get("shot_id"), "unit_id": uid,
                 "before": before, "after": chosen}
            )

    assign(must)

    # ---- 类型数缺口：分配后复算，仍不足 ⇒ 从计数最多类型的非待改镜尾部补差额 ----
    need = min(GATE["运镜类型数"], max(2, -(-n // 4)))
    types_now = len({m for m in (cur(i) for i in range(n)) if m})
    gap = need - types_now
    if gap > 0:
        cnt = Counter(m for m in (cur(i) for i in range(n)) if m)
        top = cnt.most_common(1)[0][0]
        pool = [i for i in range(n) if cur(i) == top and i not in must]
        extra = set(pool[-gap:])
        must |= extra
        assign(extra)
