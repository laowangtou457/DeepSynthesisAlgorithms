# -*- coding: utf-8 -*-
"""`T-116` script 段逐场拆段的单元测试（2026-11-24，方案 B：package_head + scene:N）。

⚠️ 覆盖面五组，与施工清单一一对应：
  ① **调用计划**：`plan_script_segments`／`synopsis_scene_nos`（场号缺失/重复/非正整数
     ⇒ 空清单降级，**不抛错**——与剧本侧 `scene_nos_of` 的 fail-fast 刻意不同）；
  ② **段级 schema 收窄**：head 段 required＝head 键集＋acts 骨架；场段 required＝
     场对象键集（**无 `act_no`**）；`all` 原样返回；
  ③ **合并装配**：幕骨架→场装配（`act_no` 由骨架派生、`scene_nos` 删除）／
     `forbidden_items` 机械承继／`total_est_seconds` 机械求和／重号·缺场·无幕认领
     **不静默**（负向样本——判据空跑家族防护：每个告警分支都有真实触发用例）；
  ④ **计划分支**：`_segment_plan` 的 script 分支（开关关 ⇒ `["all"]`；开关开 ⇒ 拆段
     计划；梗概场号异常 ⇒ 降级 `["all"]`）；
  ⑤ **段变量注入**：`_script_seg_vars`（head 锚点承继／head 不可解析降级文案）。

⚠️ 不真调模型（与 `test_scene_orchestration.py` 同构，`__new__` 免依赖构造）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.dialogue_service import DialogueService, _merge_parts
from app.services.segment import (
    SCRIPT_HEAD_TOP_KEYS,
    SCRIPT_SCENE_KEYS,
    cap_script_schema_for_segment,
    merge_script_parts,
    plan_script_segments,
    synopsis_scene_by_no,
    synopsis_scene_nos,
)


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _synopsis(*scene_nos: int, est: int = 12) -> dict:
    """最小梗概：scenes_outline 场号唯一即可驱动计划。"""
    return {
        "title": "测试片",
        "scenes_outline": [
            {"no": n, "location": f"场景{n}", "time_of_day": "夜",
             "present": ["CHR-01"], "beat": f"第{n}场事件",
             "purpose": "建立", "est_seconds": est}
            for n in scene_nos
        ],
        "forbidden_items": ["血腥", "真实人物"],
        "total_est_seconds": est * len(scene_nos),
    }


def _head(*act_plan: tuple[int, list[int]]) -> dict:
    """头部段产物：锚点键＋幕骨架（acts[].scene_nos）。"""
    return {
        "title": "测试片",
        "logline": "一句话",
        "genre": "剧情",
        "style_bible": {"style_id": "STYLE-01", "style_prompt_zh": "写实"},
        "characters": [{"character_id": "CHR-01", "name": "主角"}],
        "props": [],
        "acts": [
            {"act_no": no, "act_name": f"第{no}幕", "act_summary": "走向",
             "scene_nos": list(nos)}
            for no, nos in act_plan
        ],
        "unspecified": [],
    }


def _scene_seg(no: int, est: int = 12) -> dict:
    """单场段产物：裸场对象（无 act_no——由骨架派生）。"""
    return {
        "no": no,
        "slug": f"外景 · 场景{no} · 夜",
        "location": f"场景{no}",
        "time_of_day": "夜",
        "present": ["CHR-01"],
        "props_present": [],
        "action": f"第{no}场动作调度",
        "sfx_hint": ["雨声"],
        "dialogue": [{"speaker_id": "CHR-01", "line": "台词"}],
        "beat": f"第{no}场事件",
        "purpose": "建立",
        "est_seconds": est,
    }


# ---------------------------------------------------------------- ① 调用计划
def test_plan_script_segments_normal():
    plan = plan_script_segments(_synopsis(1, 2, 3))
    assert plan == ["package_head", "scene:1", "scene:2", "scene:3"]


def test_plan_script_segments_degrades_on_duplicate_nos():
    syn = _synopsis(1, 2)
    syn["scenes_outline"].append({"no": 1, "location": "x"})
    assert plan_script_segments(syn) == []  # 重复 ⇒ 降级（不抛错）


def test_plan_script_segments_degrades_on_missing_or_bad_no():
    syn = _synopsis(1, 2)
    syn["scenes_outline"].append({"location": "缺场号"})
    assert plan_script_segments(syn) == []
    syn2 = _synopsis(1)
    syn2["scenes_outline"][0]["no"] = "1"  # 非整数
    assert plan_script_segments(syn2) == []


def test_plan_script_segments_degrades_on_non_dict_or_empty():
    assert plan_script_segments(None) == []
    assert plan_script_segments({}) == []
    syn = _synopsis()
    syn["scenes_outline"] = []
    assert plan_script_segments(syn) == []


def test_synopsis_scene_by_no_returns_original_objects():
    syn = _synopsis(2, 1)
    by_no = synopsis_scene_by_no(syn)
    assert set(by_no) == {1, 2}
    assert by_no[1] is syn["scenes_outline"][1]  # 原样引用，不裁剪不改写
    assert synopsis_scene_nos(syn) == [1, 2]  # 计划按场号升序


# ---------------------------------------------------------------- ② 段级 schema 收窄
def test_cap_head_schema_narrows_to_head_keys_and_skeleton():
    full = {"type": "object", "required": ["title", "acts"], "properties": {}}
    seg = cap_script_schema_for_segment(full, "package_head")
    assert seg is not full
    assert set(seg["required"]) == set(SCRIPT_HEAD_TOP_KEYS)
    act = seg["properties"]["acts"]["items"]
    assert set(act["required"]) == {"act_no", "act_name", "act_summary", "scene_nos"}


def test_cap_scene_schema_has_scene_keys_without_act_no():
    full = {"type": "object", "required": ["acts"], "properties": {}}
    seg = cap_script_schema_for_segment(full, "scene:2")
    assert set(seg["required"]) == set(SCRIPT_SCENE_KEYS)
    assert "act_no" not in seg["required"]  # 幕归属由骨架决定，场段无此键
    assert seg["properties"]["dialogue"]["type"] == "array"  # 数组键钉类型


def test_cap_schema_all_mode_is_identity():
    full = {"type": "object", "required": ["acts"]}
    assert cap_script_schema_for_segment(full, "all") is full
    assert cap_script_schema_for_segment(None, "scene:1") is None


# ---------------------------------------------------------------- ③ 合并装配
def test_merge_assembles_scenes_into_act_skeleton():
    syn = _synopsis(1, 2, 3, est=10)
    parts = [
        _head((1, [1, 2]), (2, [3])),
        _scene_seg(1, est=10),
        _scene_seg(2, est=12),
        _scene_seg(3, est=14),
    ]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert warnings == []
    assert [a["act_no"] for a in merged["acts"]] == [1, 2]
    assert all("scene_nos" not in a for a in merged["acts"])  # 骨架键已删除
    act1_nos = [s["no"] for s in merged["acts"][0]["scenes"]]
    assert act1_nos == [1, 2]
    # act_no 由骨架派生（场段无此键）
    assert all(s["act_no"] == 1 for s in merged["acts"][0]["scenes"])
    assert all(s["act_no"] == 2 for s in merged["acts"][1]["scenes"])
    # 机械承继/派生
    assert merged["forbidden_items"] == syn["forbidden_items"]
    assert merged["total_est_seconds"] == 10 + 12 + 14
    assert merged["style_bible"]["style_id"] == "STYLE-01"  # head 键一次定义


def test_merge_warns_on_duplicate_scene_across_parts():
    syn = _synopsis(1)
    parts = [_head((1, [1])), _scene_seg(1), _scene_seg(1)]
    _, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("场号重复" in w for w in warnings)  # 重号不静默（负向样本）


def test_merge_warns_when_skeleton_declares_scene_without_part():
    syn = _synopsis(1, 2)
    parts = [_head((1, [1, 2])), _scene_seg(1)]  # 场 2 无段
    _, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("无对应场段产物" in w for w in warnings)  # 缺场不静默（负向样本）


def test_merge_warns_on_unclaimed_scene():
    syn = _synopsis(1, 2)
    parts = [_head((1, [1])), _scene_seg(1), _scene_seg(2)]  # 场 2 无幕认领
    _, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("无幕认领" in w for w in warnings)  # 不伪造归属（负向样本）


def test_merge_warns_when_head_missing_skeleton():
    syn = _synopsis(1)
    head = _head((1, [1]))
    del head["acts"]
    parts = [head, _scene_seg(1)]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("缺 acts 骨架" in w for w in warnings)
    assert merged["acts"] == []


def test_merge_warns_on_out_of_scope_head_key():
    syn = _synopsis(1)
    rogue = _scene_seg(1)
    rogue["style_bible"] = {"style_id": "STYLE-99"}  # 场段越界重出锚点
    parts = [_head((1, [1])), rogue]
    _, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("越界重出头部键" in w for w in warnings)  # 负向样本


def test_merge_total_sum_skips_bad_est_with_warning():
    syn = _synopsis(1, 2)
    bad = _scene_seg(2)
    bad["est_seconds"] = "12"  # 非数值
    parts = [_head((1, [1, 2])), _scene_seg(1, est=10), bad]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert merged["total_est_seconds"] == 10
    assert any("est_seconds 缺失或非数值" in w for w in warnings)  # 负向样本


# ---------------------------------------------------------------- ④ 计划分支
def _plan_args(syn: dict, *, orchestration: bool):
    get_settings().script_scene_orchestration = orchestration
    rec = SimpleNamespace(
        session_id="sess_t116", artifacts={"synopsis": {"text": json.dumps(syn)}}
    )
    tpl = SimpleNamespace(variables=[{"name": "segment"}], default_of=lambda n: "all")
    try:
        return _svc()._segment_plan(tpl, "script", rec, {})
    finally:
        get_settings().script_scene_orchestration = False


def test_segment_plan_switch_off_keeps_legacy_all():
    assert _plan_args(_synopsis(1, 2), orchestration=False) == ["all"]


def test_segment_plan_switch_on_returns_script_plan():
    assert _plan_args(_synopsis(1, 2), orchestration=True) == [
        "package_head", "scene:1", "scene:2",
    ]


def test_segment_plan_switch_on_bad_synopsis_degrades_to_all():
    syn = _synopsis(1, 2)
    syn["scenes_outline"].append({"no": 1})  # 重复场号
    assert _plan_args(syn, orchestration=True) == ["all"]


# ---------------------------------------------------------------- ⑤ 段变量注入
def _run_script_seg_vars(seg, produced):
    ctx = {"scenes": synopsis_scene_by_no(_synopsis(1, 2))}
    return _svc()._script_seg_vars(seg, ctx, produced)


def test_script_seg_vars_head_mode_declares_skeleton_scope():
    vars_ = _run_script_seg_vars("package_head", {})
    assert "头部模式" in vars_["scene_scope"]
    assert "不要写任何场的正文" in vars_["scene_scope"]


def test_script_seg_vars_scene_mode_injects_scene_and_head_anchors():
    head_doc = json.dumps(_head((1, [1, 2])), ensure_ascii=False)
    vars_ = _run_script_seg_vars("scene:2", {"package_head": head_doc})
    assert "单场模式" in vars_["scene_scope"]
    assert "不输出 `act_no`" in vars_["scene_scope"]
    scene = json.loads(vars_["scene_json"])
    assert scene["no"] == 2  # 梗概场对象原样注入
    anchors = json.loads(vars_["script_head_json"])
    assert anchors["style_bible"]["style_id"] == "STYLE-01"  # 锚点承继


def test_script_seg_vars_scene_mode_degrades_when_head_unparsable():
    vars_ = _run_script_seg_vars("scene:1", {"package_head": "不是 JSON"})
    assert "头部锚点缺失" in vars_["script_head_json"] or "不可解析" in vars_["script_head_json"]


# ---------------------------------------------------------------- 合并分发（服务层）
def test_merge_parts_dispatches_script_shape():
    texts = [
        json.dumps(_head((1, [1, 2])), ensure_ascii=False),
        json.dumps(_scene_seg(1), ensure_ascii=False),
        json.dumps(_scene_seg(2), ensure_ascii=False),
    ]
    merged_text, warnings = _merge_parts(texts, "script", _synopsis(1, 2))
    assert warnings == []
    doc = json.loads(merged_text)
    assert [s["no"] for s in doc["acts"][0]["scenes"]] == [1, 2]
    assert doc["forbidden_items"] == ["血腥", "真实人物"]


# ---------------------------------------------------------------- QA 证伪修复回归
def test_retry_segments_script_maps_act_index_to_scene_segs():
    """L1/O5：script 判据报错形态 `acts[i].scenes[j]`——经 head 骨架 scene_nos 映射到场段。"""
    plan = ["package_head", "scene:1", "scene:2", "scene:3"]
    texts = {
        "package_head": json.dumps(_head((1, [1, 2]), (2, [3])), ensure_ascii=False),
        "scene:1": json.dumps(_scene_seg(1), ensure_ascii=False),
    }
    verdict = SimpleNamespace(
        retryable=["acts[1].scenes[0].est_seconds 超限"], non_retryable=[]
    )
    picked, note = _svc()._retry_segments(plan, verdict, texts, "script")
    assert "scene:3" in picked
    assert "scene:1" not in picked  # 宁多勿漏但不得误伤无关场
    assert "package_head" in picked  # acts 域词命中共处理
    assert note is None  # 定位成功，不回退全段


def test_retry_segments_script_zero_contribution_uses_script_keys():
    """L1：HEAD_KEYS 是交付包键——旧表会把 script 场段全判零贡献强制重烧。

    verdict 用越界幕索引（acts[1]，骨架只有 1 幕）⇒ 场段既无域词命中也无映射，
    若零贡献误判仍在，两个场段会被强制重烧（picked 含全部段）。
    """
    plan = ["package_head", "scene:1", "scene:2"]
    texts = {
        "package_head": json.dumps(_head((1, [1, 2])), ensure_ascii=False),
        "scene:1": json.dumps(_scene_seg(1), ensure_ascii=False),
        "scene:2": json.dumps(_scene_seg(2), ensure_ascii=False),
    }
    verdict = SimpleNamespace(retryable=["acts[1] 越界缺幕"], non_retryable=[])
    picked, _ = _svc()._retry_segments(plan, verdict, texts, "script")
    assert picked == ["package_head"]  # 只 head；场段不误判零贡献


def test_script_seg_vars_prior_texts_rescues_head_on_retry():
    """B1：段级重采只传坏段 ⇒ produced 无 head——必须回退查 prior_texts 取最新成功锚点。"""
    head_doc = json.dumps(_head((1, [1, 2])), ensure_ascii=False)
    vars_ = _svc()._script_seg_vars(
        "scene:2",
        {"scenes": synopsis_scene_by_no(_synopsis(1, 2))},
        produced={},
        prior_texts={"package_head": head_doc},
    )
    anchors = json.loads(vars_["script_head_json"])
    assert anchors["style_bible"]["style_id"] == "STYLE-01"
    assert "头部锚点缺失" not in vars_["script_head_json"]  # 不再注入与事实相反的假降级


def test_head_cap_keeps_three_act_bounds():
    """L2：R6 三幕约束在 head 段解码期不下沉丢失（全量 schema 的 minItems/maxItems=3）。"""
    seg = cap_script_schema_for_segment({"type": "object"}, "package_head")
    act = seg["properties"]["acts"]["items"]
    assert act["minItems"] == 3 and act["maxItems"] == 3


def test_merge_total_excludes_unclaimed_scenes():
    """L4：无幕认领的场不计入 total（否则 total ≠ Σ(acts 内各场) 自相矛盾产物）。"""
    syn = _synopsis(1, 2)
    parts = [_head((1, [1])), _scene_seg(1, est=10), _scene_seg(2, est=20)]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert merged["total_est_seconds"] == 10
    assert any("无幕认领" in w and "不计入" in w for w in warnings)
