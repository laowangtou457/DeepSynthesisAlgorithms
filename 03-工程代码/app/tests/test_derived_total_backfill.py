# -*- coding: utf-8 -*-
"""派生总量回填的单元测试（`T-096` 线 3；`R14`／`R4`／`R31` 三段共用实现）。

⚠️ 覆盖面：三段各自的「失守→复算」「守恒→noop」「子项非整数→skipped」
「开关关→不动」四态；**不**真调模型（本方法是纯函数式变换，`self` 仅用于
分发 `_backfill_total_sum`，故用 `__new__` 免依赖构造）。
⚠️ 判据侧由 `prompts/validate_output.py` 在门禁期独立判定「回填后守恒」，
本测试只锁服务层行为（含留痕字段完整）。
"""

from __future__ import annotations

import json

from app.core.config import get_settings
from app.services.dialogue_service import DialogueService


def _svc() -> DialogueService:
    """免依赖构造：`_apply_derived_backfill` 只用 `get_settings()` 与自身分发。"""
    return DialogueService.__new__(DialogueService)


# ---------------------------------------------------------------- script（R4）

def test_script_total_recomputed_from_scene_sum() -> None:
    doc = {
        "title": "t", "acts": [
            {"scenes": [{"est_seconds": 30}, {"est_seconds": 45}]},
            {"scenes": [{"est_seconds": 63}]},
        ],
        "total_est_seconds": 120,  # 模型手填错（真基线 R4 形态）
    }
    out, rec = _svc()._apply_derived_backfill("script", json.dumps(doc, ensure_ascii=False))
    assert out is not None and rec is not None
    r = rec["total_est_seconds"]
    assert r["rule"] == "R4" and r["changed"] is True and r["action"] == "recomputed"
    assert r["original"] == 120 and r["computed"] == 138 and r["scene_count"] == 3
    assert json.loads(out)["total_est_seconds"] == 138
    # 场内容一字不动
    assert json.loads(out)["acts"] == doc["acts"]


def test_script_noop_when_consistent() -> None:
    doc = {"acts": [{"scenes": [{"est_seconds": 10}, {"est_seconds": 20}]}],
           "total_est_seconds": 30}
    out, rec = _svc()._apply_derived_backfill("script", json.dumps(doc))
    assert out == json.dumps(doc)  # 守恒 → 原文返回（不重新序列化）
    assert rec["total_est_seconds"]["action"] == "noop"


def test_synopsis_total_recomputed_from_outline() -> None:
    doc = {"scenes_outline": [{"est_seconds": 25}, {"est_seconds": 55}],
           "total_est_seconds": 0}
    out, rec = _svc()._apply_derived_backfill("synopsis", json.dumps(doc))
    assert rec["total_est_seconds"]["computed"] == 80
    assert json.loads(out)["total_est_seconds"] == 80


def test_script_skipped_on_non_integer_item() -> None:
    doc = {"acts": [{"scenes": [{"est_seconds": 30}, {"est_seconds": "lots"}]}],
           "total_est_seconds": 1}
    out, rec = _svc()._apply_derived_backfill("script", json.dumps(doc, ensure_ascii=False))
    assert out == json.dumps(doc, ensure_ascii=False)  # 不动产物
    assert rec["total_est_seconds"]["action"] == "skipped_non_integer_item"


def test_script_switch_off_is_noop() -> None:
    s = get_settings()
    doc = {"acts": [{"scenes": [{"est_seconds": 1}]}], "total_est_seconds": 999}
    raw = json.dumps(doc)
    try:
        s.script_derived_backfill = False
        out, rec = _svc()._apply_derived_backfill("script", raw)
        assert out == raw and rec is None
    finally:
        s.script_derived_backfill = True


# ---------------------------------------------------------------- pack（R31 算术侧）

def test_pack_meta_total_recomputed() -> None:
    doc = {"meta": {"total_duration_ms": 60000},
           "shots": [{"duration_ms": 5000}] * 10}  # Σ=50000（真基线缺陷 B 形态）
    out, rec = _svc()._apply_derived_backfill("shot_prompt", json.dumps(doc))
    r = rec["meta.total_duration_ms"]
    assert r["rule"] == "R31" and r["changed"] is True and r["computed"] == 50000
    assert json.loads(out)["meta"]["total_duration_ms"] == 50000
    assert json.loads(out)["shots"] == doc["shots"]  # 镜数据一字不动


# ---------------------------------------------------------------- storyboard（R14 回归）

def test_storyboard_semantics_unchanged() -> None:
    """`R14` 既有语义回归：Σ→覆写；非整数→skipped；守恒→noop。"""
    doc = {"shots": [{"duration_ms": 5000}] * 6, "total_duration_ms": 0}
    out, rec = _svc()._apply_derived_backfill("storyboard", json.dumps(doc))
    assert rec["total_duration_ms"]["rule"] == "R14"
    assert json.loads(out)["total_duration_ms"] == 30000
    doc2 = {"shots": [{"duration_ms": 1}, {"duration_ms": "x"}], "total_duration_ms": 2}
    out2, rec2 = _svc()._apply_derived_backfill("storyboard", json.dumps(doc2))
    assert rec2["total_duration_ms"]["action"] == "skipped_non_integer_item"
    doc3 = {"shots": [{"duration_ms": 100}], "total_duration_ms": 100}
    out3, rec3 = _svc()._apply_derived_backfill("storyboard", json.dumps(doc3))
    assert out3 == json.dumps(doc3) and rec3["total_duration_ms"]["action"] == "noop"


def test_unknown_stage_is_noop() -> None:
    out, rec = _svc()._apply_derived_backfill("revise", '{"a":1}')
    assert out == '{"a":1}' and rec is None
