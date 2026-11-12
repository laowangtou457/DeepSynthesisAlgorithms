# -*- coding: utf-8 -*-
"""`T-103` `camera.amp_speed` 机械清洗（引擎响应归一化层）单元测试。

2026-11-12 项目方裁决：**允许清洗、落 engine 响应归一化层**，并要求「逐镜留痕＋
门禁报告标注 N 镜经机械清洗后通过」。

覆盖五组：
  ① `static`/`pov` 带幅度/速度 ⇒ 删键，`camera` 其余键与 `action.*` 一字不动；
  ② 非 `no_amp` 运镜（`push_in`）带幅度 ⇒ 不动（不是无差别删字段）；
  ③ 非 storyboard/shot_prompt 阶段 ⇒ 不介入（`script` 等无 `shots` 语义）；
  ④ 开关关闭 ⇒ 原样返回（回退路径）；
  ⑤ **与门禁联动**：demo pack 注入 `static`＋幅速 ⇒ `validate_pack` 报
     `camera.amp_speed` BLOCK；清洗后同码消失（证明清洗真能解除该 BLOCK）。

⚠️ 不真调模型（`__new__` 免依赖构造，与 `test_scene_orchestration.py` 同构）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.services.dialogue_service import DialogueService, _camera_no_amp_moves

_DEMO_PACK = Path(__file__).resolve().parents[2] / "delivery" / "examples" / "CFG-004_demo_pack.json"


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _doc(shots: list[dict]) -> dict:
    return {
        "title": "测试片",
        "shots": shots,
        "units": [{"unit_id": "U01", "shot_ids": [s["shot_id"] for s in shots]}],
    }


def _shot(sid: str, move: str, **cam_extra) -> dict:
    return {
        "shot_id": sid,
        "shot_size": "中景",
        "scene_no": 1,
        "camera": {"move": move, **cam_extra},
        "action": {"start": "人物站立", "change": "转头"},
        "duration_ms": 3000,
    }


def test_static_and_pov_cleaned_with_per_shot_trace() -> None:
    doc = _doc(
        [
            _shot("S01-SH001", "push_in", amplitude="small", speed="slow"),
            _shot("S01-SH002", "static", amplitude="small", speed="slow"),
            _shot("S01-SH003", "pov", amplitude="large"),
        ]
    )
    out, rec = _svc()._normalize_camera_amp_speed("shot_prompt", json.dumps(doc, ensure_ascii=False))

    parsed = json.loads(out)
    by_id = {s["shot_id"]: s for s in parsed["shots"]}
    # ① 非 no_amp 运镜不受影响（push_in 合法携带幅度/速度）
    assert by_id["S01-SH001"]["camera"] == {"move": "push_in", "amplitude": "small", "speed": "slow"}
    # ② static / pov 的幅速被删，move 与其它创作字段一字不动
    assert by_id["S01-SH002"]["camera"] == {"move": "static"}
    assert by_id["S01-SH003"]["camera"] == {"move": "pov"}
    assert by_id["S01-SH002"]["action"] == {"start": "人物站立", "change": "转头"}
    assert by_id["S01-SH002"]["shot_size"] == "中景"
    assert by_id["S01-SH002"]["duration_ms"] == 3000

    # ③ 逐镜留痕：镜号／删的键／删前值／前后摘要，且不回写原文
    assert rec is not None and rec["cleaned"] == 2
    assert [i["shot_id"] for i in rec["items"]] == ["S01-SH002", "S01-SH003"]
    assert rec["items"][0]["removed_keys"] == ["amplitude", "speed"]
    assert rec["items"][0]["original"] == {"amplitude": "small", "speed": "slow"}
    assert rec["items"][1]["removed_keys"] == ["amplitude"]
    assert rec["text_digest_before"] != rec["text_digest_after"]
    assert len(rec["text_digest_before"]) == 16 and len(rec["text_digest_after"]) == 16
    assert "action" not in json.dumps(rec, ensure_ascii=False)  # 只留痕，不复制创作正文


def test_noop_when_no_amp_move_absent() -> None:
    text = json.dumps(_doc([_shot("S01-SH001", "push_in", amplitude="small")]), ensure_ascii=False)
    out, rec = _svc()._normalize_camera_amp_speed("shot_prompt", text)
    assert out == text  # 一个字节都不改
    assert rec is not None and rec["cleaned"] == 0 and rec["action"] == "noop"


def test_skip_for_non_shot_stage() -> None:
    text = json.dumps(_doc([_shot("S01-SH001", "static", amplitude="small")]), ensure_ascii=False)
    out, rec = _svc()._normalize_camera_amp_speed("script", text)
    assert out == text and rec is None


def test_switch_off_returns_text_unchanged() -> None:
    settings = get_settings()
    original = settings.camera_amp_speed_normalize
    settings.camera_amp_speed_normalize = False
    try:
        text = json.dumps(_doc([_shot("S01-SH001", "static", amplitude="small")]), ensure_ascii=False)
        out, rec = _svc()._normalize_camera_amp_speed("shot_prompt", text)
        assert out == text and rec is None
    finally:
        settings.camera_amp_speed_normalize = original


def test_no_amp_moves_come_from_vocab() -> None:
    """清洗集合必须与 `CFG-002` 同源（词表新增 no_amp 码时门禁与清洗同时生效）。"""
    assert {"static", "pov"} <= set(_camera_no_amp_moves())


def test_gate_linkage_cleaning_removes_amp_speed_block(tmp_path) -> None:
    """⑤ 门禁联动：注入 static＋幅速 ⇒ BLOCK；清洗后同码消失（真集成，非模拟）。"""
    from delivery.validate_pack import validate_pack

    data = json.loads(_DEMO_PACK.read_text(encoding="utf-8"))
    shots = data["shots"]
    target = shots[0]
    target["camera"] = {"move": "static", "amplitude": "small", "speed": "slow"}
    dirty = tmp_path / "pack_dirty.json"
    dirty.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    rep_dirty = validate_pack(dirty)
    codes_dirty = [c for lvl, c, _ in rep_dirty.items if lvl == "BLOCK"]
    assert "camera.amp_speed" in codes_dirty, codes_dirty
    assert rep_dirty.blocked is True

    # 走生产同一方法清洗（而不是手写删键）
    cleaned_text, rec = _svc()._normalize_camera_amp_speed("shot_prompt", dirty.read_text(encoding="utf-8"))
    assert rec is not None and rec["cleaned"] == 1
    clean = tmp_path / "pack_clean.json"
    clean.write_text(cleaned_text, encoding="utf-8")

    rep_clean = validate_pack(clean)
    codes_clean = [c for lvl, c, _ in rep_clean.items if lvl == "BLOCK"]
    assert "camera.amp_speed" not in codes_clean, codes_clean
