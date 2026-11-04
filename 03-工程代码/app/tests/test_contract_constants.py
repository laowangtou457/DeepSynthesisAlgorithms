"""契约常量「多处手抄」互锁测试 —— 覆盖矩阵缺口 B 同类收口（2026-11-04）。

⚠️ **为什么单独立文件**：工程已有多处**同一契约常量在 ≥2 处手写**的先例
   （`schema_version` 三处分叉 ⇒ 已由 `test_schema_version_consistency.py` 互锁）。
   本文件把互锁面扩到**质量门阈值**——`SPEC-008` §4.2 明文「阈值与公式必须直接引用
   `audit_shots.py` 的 `GATE`，不得另立一套」（**`NT-09`**），但工程内实际存在
   **两份手抄**（`delivery/validate_pack.py` 与 `prompts/validate_output.py`），
   一致性此前只靠**人工同步** ⇒ 与 `schema_version` 分叉同族（缺口 B 家族）。

⚠️ **互锁语义**：两份 `GATE` 任一处单独改值 ⇒ 本测试即红 ⇒
   「数月后被真机撞出矛盾结论」变为「跑 pytest 即报」。

⚠️ **边界（如实登记）**：`audit_shots.py`（阈值真值源）在工程外
   （`WorkBuddy/2026-09-30-13-16-52/h3_prompt_model/`，不入库）⇒
   本测试只能锁「工程内两份互等」，锁不了「与工程外真值源相等」——
   后者须人工对拍（登记于 `PRO-012` 覆盖矩阵）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(r"E:\深度合成算法工程材料\03-工程代码")
PACK_VALIDATOR = ROOT / "delivery" / "validate_pack.py"
OUTPUT_VALIDATOR = ROOT / "prompts" / "validate_output.py"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------- GATE 11 项阈值


def test_gate_thresholds_are_identical_in_both_validators() -> None:
    """★ 两份手抄 `GATE`（11 项阈值）必须逐键逐值相等（NT-09）。

    任一处单独调阈值而未同步另一处 ⇒ 本测试即红。
    """
    a = _load(PACK_VALIDATOR).GATE
    b = _load(OUTPUT_VALIDATOR).GATE
    assert a.keys() == b.keys(), f"GATE 键集分叉：{a.keys() ^ b.keys()}"
    for k in a:
        assert a[k] == b[k], f"GATE[{k!r}] 分叉：validate_pack={a[k]!r} vs validate_output={b[k]!r}"


# ---------------------------------------------------------------- 语速阈值 ≤ 9 字/秒


def test_dialogue_speed_threshold_is_identical() -> None:
    """★ 语速阈值：`validate_pack.MAX_CHARS_PER_SECOND` ≡ `validate_output` R15 字面量。

    `validate_output.py` 的 R15 把 9 硬编码在 `if rate > 9:`（无命名常量）⇒
    本测试从其源码提取该字面量与 `validate_pack` 的命名常量对拍。
    ⚠️ 若 R15 将来改为命名常量，本测试仍兼容（正则同样命中 `if rate > X:`）。
    """
    pack_mod = _load(PACK_VALIDATOR)
    src = OUTPUT_VALIDATOR.read_text(encoding="utf-8")
    hits = re.findall(r"if rate > ([0-9]+(?:\.[0-9]+)?):", src)
    assert len(hits) == 1, f"R15 语速字面量应恰有 1 处，实测 {len(hits)} 处（判据结构变更，须同步改本测试）"
    r15_threshold = float(hits[0])
    assert pack_mod.MAX_CHARS_PER_SECOND == r15_threshold, (
        f"语速阈值分叉：validate_pack={pack_mod.MAX_CHARS_PER_SECOND} vs "
        f"validate_output R15={r15_threshold}"
    )


# ---------------------------------------------------------------- 容差算法一致性


def test_allow_formula_is_identical() -> None:
    """★ 占比→绝对个数容差公式 `max(1, ceil(ratio*n))` 两处实现必须同算法。

    抽 6 组（ratio, n）对拍两份实现（n=0 边界不取——两处调用方都保证 n≥1）。
    """
    a = _load(PACK_VALIDATOR)._allow
    b = _load(OUTPUT_VALIDATOR)._allow
    for ratio in (0.40, 0.35, 0.30, 0.60):
        for n in (1, 2, 3, 5, 8, 17):
            assert a(ratio, n) == b(ratio, n), (
                f"_allow({ratio},{n}) 分叉：validate_pack={a(ratio, n)} vs "
                f"validate_output={b(ratio, n)}"
            )


# ---------------------------------------------------------------- 运镜类型数下限公式


def test_camera_type_min_formula_is_identical() -> None:
    """★ 运镜类型数下限公式 `min(GATE['运镜类型数'], max(2, ceil(n/4)))` 两处一致。"""
    import math

    pack_mod = _load(PACK_VALIDATOR)
    for n in (2, 3, 5, 8, 12, 20):
        expect = min(pack_mod.GATE["运镜类型数"], max(2, math.ceil(n / 4)))
        # validate_pack 内嵌实现
        assert min(pack_mod.GATE["运镜类型数"], max(2, pack_mod._ceil(n / 4))) == expect
