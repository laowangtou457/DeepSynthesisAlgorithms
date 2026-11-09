# -*- coding: utf-8 -*-
"""`R8` 场内镜号序列回填的单元测试（`T-087` 余项；2026-11-05）。

⚠️ 覆盖面：「单元内编号→场内重编」「已合规→noop」「缺键→补齐」「非整数 scene_no
→skipped」「开关关→不动」五态；**不**真调模型（与 `test_derived_total_backfill.py`
同构，纯函数式变换、`__new__` 免依赖构造）。
⚠️ 真值基线（2026-11-04 冒烟 `sess_2738d84570fe` storyboard 第 2 轮）：模型按
**单元内**编号产出每一场 `[1,1,2,2]` ⇒ `R8` 报「应为 1..4，实际 [1,1,2,2]」；
回填后须场内 `1..n` 连续、数组序（创作声明）一字不动、模型原值按 `shot_id`
键控留痕。
"""

from __future__ import annotations

import json

from app.core.config import get_settings
from app.services.dialogue_service import DialogueService


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _storyboard(shots: list[dict]) -> str:
    """最小 storyboard 形态（R14 那半要求 duration_ms 为整数，避免串到它的 skipped 路径）。"""
    return json.dumps({
        "shots": shots,
        "total_duration_ms": sum(s["duration_ms"] for s in shots),
    }, ensure_ascii=False)


def _shot(sid: str, scene: int, no: object, ms: int = 5000) -> dict:
    return {"shot_id": sid, "unit_id": f"U{scene:02d}", "scene_no": scene,
            "shot_no": no, "duration_ms": ms}


# ---------------------------------------------------------------- 主形态：单元内编号 → 场内重编

def test_per_unit_numbering_renumbered_to_scene_seq() -> None:
    """真基线形态复现：每一场 `[1,1,2,2]`（模型按单元内编号）⇒ 回填为 `1,2,3,4`。"""
    shots = [
        _shot("S01-SH001", 1, 1), _shot("S01-SH002", 1, 1),
        _shot("S01-SH003", 1, 2), _shot("S01-SH004", 1, 2),
        _shot("S02-SH001", 2, 1), _shot("S02-SH002", 2, 2),
    ]
    raw = _storyboard(shots)
    out, rec = _svc()._apply_derived_backfill("storyboard", raw)
    assert out is not None and rec is not None
    r = rec["shots[].shot_no"]
    assert r["rule"] == "R8" and r["changed"] is True and r["action"] == "renumbered"
    assert r["scene_count"] == 2 and r["shot_count"] == 6
    # 模型原值按 shot_id 键控留痕（只记被改动的镜头：S01-SH001 与场景 2 两镜原值即对、不记）
    assert r["original"] == {"S01-SH002": 1, "S01-SH003": 2, "S01-SH004": 2}
    doc = json.loads(out)
    assert [s["shot_no"] for s in doc["shots"]] == [1, 2, 3, 4, 1, 2]
    # 创作声明一字不动：shot_id／scene_no／unit_id／时长与数组序
    assert [(s["shot_id"], s["scene_no"], s["unit_id"], s["duration_ms"])
            for s in doc["shots"]] == [
        ("S01-SH001", 1, "U01", 5000), ("S01-SH002", 1, "U01", 5000),
        ("S01-SH003", 1, "U01", 5000), ("S01-SH004", 1, "U01", 5000),
        ("S02-SH001", 2, "U02", 5000), ("S02-SH002", 2, "U02", 5000),
    ]
    # R14 那半同时跑过（守恒 ⇒ noop）
    assert rec["total_duration_ms"]["action"] == "noop"


def test_already_correct_is_noop() -> None:
    shots = [_shot(f"S01-SH00{i}", 1, i) for i in (1, 2, 3)]
    raw = _storyboard(shots)
    out, rec = _svc()._apply_derived_backfill("storyboard", raw)
    assert out == raw  # 合规 → 原文返回（不重新序列化）
    r = rec["shots[].shot_no"]
    assert r["action"] == "noop" and r["changed"] is False
    assert "original" not in r  # 无改动不记原值


def test_missing_shot_no_filled() -> None:
    shots = [_shot("S01-SH001", 1, None), _shot("S01-SH002", 1, 1)]
    out, rec = _svc()._apply_derived_backfill("storyboard", _storyboard(shots))
    r = rec["shots[].shot_no"]
    assert r["changed"] is True and r["original"] == {"S01-SH001": None, "S01-SH002": 1}
    assert [s["shot_no"] for s in json.loads(out)["shots"]] == [1, 2]


# ---------------------------------------------------------------- 防御路径

def test_non_integer_scene_no_skipped() -> None:
    """场号非整数 ⇒ 场内分组语义已破坏，不兜底、原文不动、如实留痕。"""
    shots = [_shot("S01-SH001", 1, 1), {"shot_id": "X", "scene_no": "一", "shot_no": 2,
                                       "unit_id": "U01", "duration_ms": 5000}]
    raw = _storyboard(shots)
    out, rec = _svc()._apply_derived_backfill("storyboard", raw)
    r = rec["shots[].shot_no"]
    assert r["action"] == "skipped_non_integer_scene_no" and r["changed"] is False
    # 原文 JSON 体不动（R14 守恒 ⇒ 同样 noop，不回写）
    assert json.loads(out)["shots"] == json.loads(raw)["shots"]


def test_switch_off_leaves_artifact_untouched() -> None:
    s = get_settings()
    shots = [_shot("S01-SH001", 1, 1), _shot("S01-SH002", 1, 1)]
    raw = _storyboard(shots)
    try:
        s.storyboard_shot_no_backfill = False
        out, rec = _svc()._apply_derived_backfill("storyboard", raw)
        assert out == raw
        assert rec is not None and "shots[].shot_no" not in rec  # R14 那半仍在跑
        assert rec["total_duration_ms"]["action"] == "noop"
    finally:
        s.storyboard_shot_no_backfill = True


def test_non_storyboard_stage_unaffected() -> None:
    out, rec = _svc()._apply_derived_backfill("synopsis",
        json.dumps({"scenes_outline": [{"est_seconds": 10}], "total_est_seconds": 10}))
    assert rec is not None and "shots[].shot_no" not in rec
