# -*- coding: utf-8 -*-
"""`T-100` 逐场编排的单元测试（`PRO-014` §3；2026-11-05 授权代决落地）。

⚠️ 覆盖面四组，与施工清单一一对应：
  ① **调用计划**：`plan_scene_segments`／`scene_nos_of`（场号缺失／非整数／重复 ⇒ 显式报错）；
  ② **storyboard 合并**：头部键换表（不得丢 `title`/`genre`/`style_ref`/`aspect_ratio_default`）／
     `total_duration_ms` 丢弃／追加不排序（保住 `R8` 的「数组序＝镜序」前提）／
     重号**不静默**（场景重复、`shot_id` 重复都只告警、条目全留）；
  ③ **标识归一化**：`shot_id` 按场内数组序重编、`units[].shot_ids` 同步映射、
     `unit_id` 按 `(scene_no, 原 id)` 重编；`R9` 不一致时**不重编**（不洗白）；
  ④ **按场重试定位**：门禁报「场 k」时只重跑该场。

⚠️ 不真调模型（与 `test_derived_shot_no_backfill.py` 同构，`__new__` 免依赖构造）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.dialogue_service import DialogueService, _merge_parts
from app.services.segment import (
    HEAD_KEYS_STORYBOARD,
    merge_storyboard_parts,
    plan_scene_segments,
    scene_by_no,
    scene_nos_of,
)


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _script(*scene_nos: int) -> dict:
    """一个 act 包住全部场（足够验证计划推导；多 act 的排序见专门用例）。"""
    return {"acts": [{"no": 1, "scenes": [{"no": n, "action": f"第{n}场动作"} for n in scene_nos]}]}


def _sb(scene: int, shot_ids: list[str], *, unit_id: str = "U01",
        title: str = "片名", total: int = 0) -> dict:
    """一段（=一场）storyboard 产物。"""
    return {
        "title": title,
        "genre": "剧情",
        "style_ref": "STYLE-01",
        "aspect_ratio_default": "16:9",
        "total_duration_ms": total,
        "units": [{"unit_id": unit_id, "scene_no": scene, "shot_ids": list(shot_ids),
                   "soundscape": "环境", "music": "N/A"}],
        "shots": [{"shot_id": sid, "unit_id": unit_id, "scene_no": scene,
                   "shot_no": i + 1, "duration_ms": 5000}
                  for i, sid in enumerate(shot_ids)],
        "forbidden_items": ["血腥"],
        "unspecified": [],
        "quality_gate": {"self_check": f"第{scene}场自查通过"},
    }


# ------------------------------------------------------------------ ① 调用计划

def test_plan_scene_segments_sorted_across_acts() -> None:
    script = {"acts": [
        {"no": 1, "scenes": [{"no": 1}, {"no": 2}]},
        {"no": 2, "scenes": [{"no": 3}]},
    ]}
    assert plan_scene_segments(script) == ["scene:1", "scene:2", "scene:3"]
    assert scene_nos_of(script) == [1, 2, 3]
    assert scene_by_no(script)[2] == {"no": 2}


def test_plan_scene_segments_rejects_missing_acts() -> None:
    for bad in ({}, {"acts": []}, {"acts": [{}]}, {"acts": [{"scenes": []}]}):
        try:
            plan_scene_segments(bad)
        except AppError as exc:
            assert "无法推导逐场调用计划" in exc.message
        else:  # pragma: no cover
            raise AssertionError(f"应报错但未报：{bad}")


def test_plan_scene_segments_rejects_non_integer_no() -> None:
    try:
        plan_scene_segments({"acts": [{"scenes": [{"no": "一"}]}]})
    except AppError as exc:
        assert "`no` 不是整数" in exc.message
    else:  # pragma: no cover
        raise AssertionError("非整数场号应报错")


def test_plan_scene_segments_rejects_duplicate_no() -> None:
    try:
        plan_scene_segments({"acts": [{"scenes": [{"no": 1}, {"no": 1}]}]})
    except AppError as exc:
        assert "场号重复" in exc.message
    else:  # pragma: no cover
        raise AssertionError("场号重复应报错")


# ------------------------------------------------------------------ ② 合并

def test_merge_keeps_storyboard_head_keys() -> None:
    """⚠️ 关键回归：用包的 `HEAD_KEYS` 合并会丢掉 title/genre/style_ref/aspect_ratio_default。"""
    merged, warnings = merge_storyboard_parts([_sb(1, ["S01-SH001"]), _sb(2, ["S02-SH001"])])
    for key in HEAD_KEYS_STORYBOARD:
        assert key in merged, f"{key} 丢失"
    assert merged["title"] == "片名" and merged["style_ref"] == "STYLE-01"
    assert not [w for w in warnings if "缺顶层必需键" in w]


def test_merge_head_drift_warns_but_keeps_first() -> None:
    merged, warnings = merge_storyboard_parts([
        _sb(1, ["S01-SH001"], title="甲"),
        _sb(2, ["S02-SH001"], title="乙"),
    ])
    assert merged["title"] == "甲"
    assert any("头部字段「title」" in w and "保留先出现者" in w for w in warnings)


def test_merge_drops_total_duration_ms() -> None:
    """各场自带的是「本场之和」⇒ 不参与合并，交由 R14 回填按 Σ 重算。"""
    merged, _ = merge_storyboard_parts([
        _sb(1, ["S01-SH001"], total=5000),
        _sb(2, ["S02-SH001"], total=7000),
    ])
    assert "total_duration_ms" not in merged


def test_merge_preserves_plan_order_and_within_scene_order() -> None:
    """⚠️ 追加**不排序**：按 shot_no 排序会打乱「单元内编号 [1,1,2,2]」的数组序，
    破坏 `R8` 派生回填所依赖的「数组序＝镜序」前提。"""
    a = _sb(1, ["S01-SH002", "S01-SH001"])  # 模型顺序故意逆序
    b = _sb(2, ["S02-SH001"])
    merged, _ = merge_storyboard_parts([a, b])
    assert [s["shot_id"] for s in merged["shots"]] == ["S01-SH002", "S01-SH001", "S02-SH001"]


def test_merge_unspecified_dedup() -> None:
    a = _sb(1, ["S01-SH001"])
    a["unspecified"] = [{"field": "x", "reason": "r"}]
    b = _sb(2, ["S02-SH001"])
    b["unspecified"] = [{"field": "x", "reason": "r"}, {"field": "y", "reason": "r2"}]
    merged, _ = merge_storyboard_parts([a, b])
    assert [u["field"] for u in merged["unspecified"]] == ["x", "y"]


def test_merge_duplicate_shot_id_warns_but_keeps_all() -> None:
    """跨场重号（逐场各从 S01-SH001 起编）⇒ 只告警、**条目全留**，交归一化与 R7。"""
    merged, warnings = merge_storyboard_parts([
        _sb(1, ["S01-SH001"]),
        _sb(2, ["S01-SH001"]),  # 场号 2 却编了 S01 前缀
    ])
    assert len(merged["shots"]) == 2
    assert any("shot_id 重复" in w for w in warnings)
    # 两段的 scene_no 不同（1／2）⇒ 不触发「场号重复」告警；该告警另有用例覆盖


def test_merge_duplicate_unit_id_warns() -> None:
    merged, warnings = merge_storyboard_parts([
        _sb(1, ["S01-SH001"], unit_id="U01"),
        _sb(2, ["S02-SH001"], unit_id="U01"),
    ])
    assert len(merged["units"]) == 2
    assert any("unit_id 重复" in w for w in warnings)


def test_merge_scene_duplicated_warns() -> None:
    """模型越界写了别的场（两段都出第 1 场）⇒ 显式告警、条目全留，交 R41／R42／R10 判。"""
    merged, warnings = merge_storyboard_parts([
        _sb(1, ["S01-SH001"]),
        _sb(1, ["S01-SH002"]),
    ])
    assert len(merged["shots"]) == 2
    assert any("场号重复出现于多段" in w for w in warnings)


def test_merge_parts_dispatch_by_stage() -> None:
    """`_merge_parts` 按形态分派：storyboard 走专属合并，其余仍走包合并。"""
    a, b = _sb(1, ["S01-SH001"]), _sb(2, ["S02-SH001"])
    text, _ = _merge_parts([json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False)],
                           "storyboard")
    assert json.loads(text)["title"] == "片名"
    # 包形态：title 不在 `HEAD_KEYS` 里 ⇒ 不参与合并
    text2, _ = _merge_parts([json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False)],
                            "shot_prompt")
    assert "title" not in json.loads(text2)


# -------------------------- `ISSUE-062` 裁决 5：继承项 `fill_stage` 锁回上游层

def test_merge_relocks_inherited_fill_stage() -> None:
    """继承项（`upstream_field` 非空）被本层改写成 `storyboard` ⇒ 合并侧锁回 `script`。

    `R21` 只报告不修复，而模型在逐场输入里**看不到上游那条的 `fill_stage`**
    ⇒ 这是「模型无从知道」型失败，必须在合并侧机械修正（同 `R14`/`R8`/`R24` 族）。
    """
    upstream = {"unspecified": [{"field": "climax_action", "reason": "客户未给",
                                 "owner": "客户", "fill_stage": "script"}]}
    a = _sb(1, ["S01-SH001"])
    a["unspecified"] = [{"field": "climax_action", "reason": "客户未给", "owner": "客户",
                         "upstream_field": "beats[2].action", "fill_stage": "storyboard"}]
    merged, warnings = merge_storyboard_parts([a], upstream=upstream)
    assert merged["unspecified"][0]["fill_stage"] == "script"
    assert any("锁回上游层" in w for w in warnings)
    # 只动 `fill_stage`：其余字段原样
    assert merged["unspecified"][0]["owner"] == "客户"
    assert merged["unspecified"][0]["upstream_field"] == "beats[2].action"


def test_merge_keeps_native_item_fill_stage() -> None:
    """本层新增项（`upstream_field` 空）⇒ `fill_stage` 归本层，**不得**被改成 script。"""
    upstream = {"unspecified": [{"field": "climax_action", "fill_stage": "script"}]}
    a = _sb(1, ["S01-SH001"])
    a["unspecified"] = [{"field": "climax_action", "reason": "本层定", "owner": "客户",
                         "fill_stage": "storyboard"}]  # 无 upstream_field
    merged, warnings = merge_storyboard_parts([a], upstream=upstream)
    assert merged["unspecified"][0]["fill_stage"] == "storyboard"
    assert not any("锁回上游层" in w for w in warnings)


def test_merge_reports_inherited_item_missing_upstream() -> None:
    """声称继承、上游台账查无此条 ⇒ **不改写**、只留痕（不得用机械改写掩盖上游缺口）。"""
    a = _sb(1, ["S01-SH001"])
    a["unspecified"] = [{"field": "ghost", "reason": "r", "owner": "客户",
                         "upstream_field": "beats[9].action", "fill_stage": "storyboard"}]
    merged, warnings = merge_storyboard_parts([a], upstream={"unspecified": []})
    assert merged["unspecified"][0]["fill_stage"] == "storyboard"
    assert any("查无对应条目" in w for w in warnings)


def test_merge_no_upstream_leaves_fill_stage_untouched() -> None:
    """不传上游（解析失败等）⇒ 一律不改写，交 `R21` 照常判。"""
    a = _sb(1, ["S01-SH001"])
    a["unspecified"] = [{"field": "x", "reason": "r", "owner": "客户",
                         "upstream_field": "b.eats", "fill_stage": "storyboard"}]
    merged, warnings = merge_storyboard_parts([a])
    assert merged["unspecified"][0]["fill_stage"] == "storyboard"
    assert not any("锁回上游层" in w or "查无对应条目" in w for w in warnings)


# ------------------------------------------------------------------ ③ 标识归一化

def _two_scene_doc() -> str:
    """逐场编排的真实形态：两场各自从 `S01-SH001`／`U01` 起编。"""
    a, b = _sb(1, ["S01-SH001", "S01-SH002"]), _sb(2, ["S01-SH001", "S01-SH002"])
    merged, _ = merge_storyboard_parts([a, b])
    return json.dumps(merged, ensure_ascii=False)


def test_normalize_renumbers_shot_id_per_scene() -> None:
    out, rec = _svc()._normalize_storyboard_identity("storyboard", _two_scene_doc())
    doc = json.loads(out)
    assert [s["shot_id"] for s in doc["shots"]] == [
        "S01-SH001", "S01-SH002", "S02-SH001", "S02-SH002",
    ]
    assert rec["shots[].shot_id"]["renumbered"] == 2


def test_normalize_remaps_unit_shot_ids() -> None:
    out, _ = _svc()._normalize_storyboard_identity("storyboard", _two_scene_doc())
    doc = json.loads(out)
    assert doc["units"][1]["shot_ids"] == ["S02-SH001", "S02-SH002"]


def test_normalize_renumbers_unit_id_by_scene() -> None:
    """同名不同场（逐场下必然）⇒ 按 `(scene_no, 原 id)` 重编为 U01/U02，不得混成一个。"""
    out, rec = _svc()._normalize_storyboard_identity("storyboard", _two_scene_doc())
    doc = json.loads(out)
    assert [u["unit_id"] for u in doc["units"]] == ["U01", "U02"]
    assert [s["unit_id"] for s in doc["shots"]] == ["U01", "U01", "U02", "U02"]
    assert rec["units[].unit_id"]["changed"] is True


def test_normalize_skips_unit_when_link_inconsistent() -> None:
    """`R9` 已失败 ⇒ **不重编** `unit_id`（否则会把链接错误洗白成"看起来对了"）。"""
    doc = _sb(1, ["S01-SH001", "S01-SH002"])
    doc["units"][0]["shot_ids"] = ["S01-SH001"]  # 少列一镜 ⇒ 双向不一致
    out, rec = _svc()._normalize_storyboard_identity(
        "storyboard", json.dumps(doc, ensure_ascii=False)
    )
    assert rec["units[].unit_id"]["skipped"].startswith("unit_shot_link_inconsistent")
    assert rec["units[].unit_id"]["changed"] is False
    assert json.loads(out)["units"][0]["unit_id"] == "U01"


def test_normalize_switch_off_leaves_untouched() -> None:
    settings = get_settings()
    raw = _two_scene_doc()
    try:
        settings.storyboard_identity_normalize = False
        out, rec = _svc()._normalize_storyboard_identity("storyboard", raw)
        assert out == raw and rec is None
    finally:
        settings.storyboard_identity_normalize = True


def test_normalize_non_storyboard_stage_unaffected() -> None:
    raw = json.dumps({"shots": [{"shot_id": "X", "scene_no": 1}]}, ensure_ascii=False)
    out, rec = _svc()._normalize_storyboard_identity("script", raw)
    assert out == raw and rec is None


# ------------------------------------------------------------------ ④ 按场重试定位

def test_retry_scope_picks_only_reported_scene() -> None:
    texts = {
        "scene:1": json.dumps(_sb(1, ["S01-SH001"]), ensure_ascii=False),
        "scene:2": json.dumps(_sb(2, ["S02-SH001"]), ensure_ascii=False),
        "scene:3": json.dumps(_sb(3, ["S03-SH001"]), ensure_ascii=False),
    }
    verdict = SimpleNamespace(retryable=["场 3 · R42 SCENE_SHOT_FLOOR：场 3 仅 1 镜（须 ≥ 2）"])
    picked, note = _svc()._retry_segments(["scene:1", "scene:2", "scene:3"], verdict, texts)
    assert picked == ["scene:3"] and note is None


def test_retry_scope_picks_on_shot_id_prefix() -> None:
    texts = {
        "scene:1": json.dumps(_sb(1, ["S01-SH001"]), ensure_ascii=False),
        "scene:2": json.dumps(_sb(2, ["S02-SH001"]), ensure_ascii=False),
    }
    verdict = SimpleNamespace(retryable=["R11 UNIT_MOVE_UNIQUE：S02-SH001 与 S02-SH002 运镜重复"])
    picked, _ = _svc()._retry_segments(["scene:1", "scene:2"], verdict, texts)
    assert picked == ["scene:2"]


def test_retry_scope_falls_back_to_all_when_unlocatable() -> None:
    texts = {
        "scene:1": json.dumps(_sb(1, ["S01-SH001"]), ensure_ascii=False),
        "scene:2": json.dumps(_sb(2, ["S02-SH001"]), ensure_ascii=False),
    }
    verdict = SimpleNamespace(retryable=["某条无法定位的报错"])
    picked, note = _svc()._retry_segments(["scene:1", "scene:2"], verdict, texts)
    assert picked == ["scene:1", "scene:2"] and note == "scope_fallback"
