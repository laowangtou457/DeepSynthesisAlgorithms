# -*- coding: utf-8 -*-
"""`R24` 道具覆盖回填的单元测试（`T-087` 余项后续；2026-11-05）。

⚠️ 覆盖面：「整场漏标→场首镜补标」「已有部分标→只补缺」「场无镜头→skipped 不造假」
「无上游剧本→不动」「开关关→不动」五态；**不**真调模型（与
`test_derived_shot_no_backfill.py` 同构，纯函数式变换、`__new__` 免依赖构造）。
⚠️ 真值基线（2026-11-05 冒烟 `sess_dac62518e40c` storyboard 第 2 轮）：场 4
`props_present=['PRP-01']` 而该场无一镜标出 ⇒ `R24` 报「1 处漏拍」；回填后
场首镜 `prop_refs` 补上缺失 `prop_id`、模型原值按 `shot_id` 键控留痕。
"""

from __future__ import annotations

import json

from app.core.config import get_settings
from app.services.dialogue_service import DialogueService


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _shot(sid: str, scene: int, refs: list | None) -> dict:
    shot = {"shot_id": sid, "unit_id": f"U{scene:02d}", "scene_no": scene,
            "shot_no": 1, "duration_ms": 5000}
    if refs is not None:
        shot["prop_refs"] = refs
    return shot


def _storyboard(shots: list[dict]) -> str:
    return json.dumps({
        "shots": shots,
        "total_duration_ms": sum(s["duration_ms"] for s in shots),
    }, ensure_ascii=False)


def _script(props_by_scene: dict[int, list]) -> str:
    return json.dumps({
        "acts": [{"scenes": [
            {"no": no, "props_present": refs} for no, refs in props_by_scene.items()
        ]}],
    }, ensure_ascii=False)


# ---------------------------------------------------------------- 主形态：整场漏标 → 场首镜补标

def test_whole_scene_missed_backfilled_to_first_shot() -> None:
    """真基线形态复现：场 2 有 props_present=['PRP-01','PRP-02'] 而无一镜标出
    ⇒ 场 2 首镜（数组序第一个）prop_refs 补上两个编号、原值（缺键⇒None）留痕。"""
    shots = [
        _shot("S01-SH001", 1, ["PRP-09"]),       # 场 1 剧本无道具 → 不动
        _shot("S02-SH001", 2, None),              # 场 2 首镜：漏标（缺键）
        _shot("S02-SH002", 2, None),
    ]
    raw = _storyboard(shots)
    script = _script({1: [], 2: ["PRP-01", "PRP-02"]})
    out, rec = _svc()._apply_derived_backfill("storyboard", raw, {"script": script})
    assert out is not None and rec is not None
    r = rec["shots[].prop_refs"]
    assert r["rule"] == "R24" and r["changed"] is True
    assert r["action"] == "covered_first_shot"
    assert r["scene_with_props"] == 1 and r["scene_covered"] == 1
    assert r["original"] == {"S02-SH001": None}
    doc = json.loads(out)
    assert doc["shots"][0]["prop_refs"] == ["PRP-09"]     # 场 1 一字不动
    assert doc["shots"][1]["prop_refs"] == ["PRP-01", "PRP-02"]
    assert "prop_refs" not in doc["shots"][2]              # 只补首镜、其余不动


def test_partial_coverage_only_missing_added() -> None:
    """场内已标一部分（次镜标了 PRP-01）⇒ 只把缺的 PRP-02 补进场首镜、已标的不动。"""
    shots = [
        _shot("S01-SH001", 1, ["PRP-03"]),        # 首镜已标但不含缺失项
        _shot("S01-SH002", 1, ["PRP-01"]),        # 次镜已标
    ]
    script = _script({1: ["PRP-01", "PRP-02"]})
    out, rec = _svc()._apply_derived_backfill(
        "storyboard", _storyboard(shots), {"script": script})
    r = rec["shots[].prop_refs"]
    assert r["changed"] is True and r["original"] == {"S01-SH001": ["PRP-03"]}
    doc = json.loads(out)
    assert doc["shots"][0]["prop_refs"] == ["PRP-02", "PRP-03"]  # 缺项并入首镜、已有项保留
    assert doc["shots"][1]["prop_refs"] == ["PRP-01"]             # 次镜一字不动


def test_fully_covered_is_noop() -> None:
    shots = [_shot("S01-SH001", 1, ["PRP-01", "PRP-02"])]
    script = _script({1: ["PRP-01", "PRP-02"]})
    raw = _storyboard(shots)
    out, rec = _svc()._apply_derived_backfill("storyboard", raw, {"script": script})
    assert out == raw  # 合规 → 原文返回
    r = rec["shots[].prop_refs"]
    assert r["action"] == "noop" and r["changed"] is False
    assert "original" not in r


# ---------------------------------------------------------------- 防御路径

def test_scene_without_shots_skipped_not_faked() -> None:
    """3 镜吸引子形态：剧本场 5 有道具但分镜无该场任一镜 ⇒ 留痕 skip、不制造
    「道具已覆盖」假象（交 R24/场覆盖判据如实判）。"""
    shots = [_shot("S01-SH001", 1, ["PRP-01"])]
    script = _script({1: ["PRP-01"], 5: ["PRP-07"]})
    out, rec = _svc()._apply_derived_backfill(
        "storyboard", _storyboard(shots), {"script": script})
    r = rec["shots[].prop_refs"]
    assert r["changed"] is False
    assert r["skipped_scene_without_shots"] == [5]
    assert "original" not in r


def test_no_upstream_script_untouched() -> None:
    shots = [_shot("S01-SH001", 1, None)]
    raw = _storyboard(shots)
    out, rec = _svc()._apply_derived_backfill("storyboard", raw)  # 不传 gate_upstream
    assert rec is not None and "shots[].prop_refs" not in rec
    assert "shots[].prop_refs" not in json.loads(out)["shots"][0]


def test_switch_off_leaves_artifact_untouched() -> None:
    s = get_settings()
    shots = [_shot("S01-SH001", 1, None)]
    script = _script({1: ["PRP-01"]})
    raw = _storyboard(shots)
    try:
        s.storyboard_prop_coverage_backfill = False
        out, rec = _svc()._apply_derived_backfill("storyboard", raw, {"script": script})
        assert rec is not None and "shots[].prop_refs" not in rec  # 其余回填仍在跑
        assert "shots[].prop_refs" not in rec
    finally:
        s.storyboard_prop_coverage_backfill = True


def test_scenes_outline_form_supported() -> None:
    """synopsis 形态剧本（scenes_outline）与 acts 形态同口径（镜像判据侧兼容）。"""
    shots = [_shot("S01-SH001", 1, None)]
    script = json.dumps({"scenes_outline": [{"no": 1, "props_present": ["PRP-01"]}]})
    out, rec = _svc()._apply_derived_backfill(
        "storyboard", _storyboard(shots), {"script": script})
    r = rec["shots[].prop_refs"]
    assert r["changed"] is True
    assert json.loads(out)["shots"][0]["prop_refs"] == ["PRP-01"]
