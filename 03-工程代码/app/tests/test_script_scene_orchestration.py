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
    SCRIPT_ACTION_MAX_CHARS,
    SCRIPT_DIALOGUE_LINE_MAX_CHARS,
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
    """①：无幕认领且无空幕 ⇒ 如实告警＋不装配、不计入 total（QA E5：两段告警都要有）。"""
    syn = _synopsis(1, 2)
    parts = [_head((1, [1])), _scene_seg(1), _scene_seg(2)]  # 场 2 无幕认领
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("无幕认领" in w for w in warnings)  # 不静默
    assert any("无空幕可回填" in w for w in warnings)  # 结构性失败如实暴露
    assert any("不计入 total_est_seconds" in w for w in warnings)
    assert merged["total_est_seconds"] == 12  # 未装配场不伪造归属、不计入


def test_merge_does_not_resurrect_out_of_scope_scene():
    """① QA A2：梗概外的场（包装形态产物可带出）不得经「回填空幕」复活。"""
    syn = _synopsis(1, 2, est=10)
    parts = [_head((1, [1]), (2, []), (3, [3])), _scene_seg(1, est=10), _scene_seg(9, est=10)]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("梗概外的场号" in w and "9" in w for w in warnings)
    nos = [s["no"] for a in merged["acts"] for s in a["scenes"]]
    assert 9 not in nos  # 不装配
    assert merged["total_est_seconds"] == 10  # 不计入


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


# ================================================================ T-117 硬约束
# ① head/scene max_tokens 收口；② dialogue maxItems 解码期派生；
# ③ script 截断重采预算数字反馈；④ storyboard prev_scene_tail 同款 B1 修复。
from app.inference.base import GenParams  # noqa: E402
from app.services.coverage_reconcile import DIALOGUE_SPEED_MAX  # noqa: E402
from app.services.dialogue_service import (  # noqa: E402
    SCRIPT_DIALOGUE_MAX_ITEMS_CAP,
    SCRIPT_DIALOGUE_MIN_CHARS_PER_LINE,
    SCRIPT_HEAD_MAX_TOKENS,
    SCRIPT_SCENE_MAX_TOKENS,
    SHOT_PROMPT_UNIT_MAX_TOKENS,
    STORYBOARD_SCENE_MAX_TOKENS,
    _script_dialogue_budget_items,
    _script_dialogue_max_items,
    _script_head_sampling,
    _script_truncation_feedback,
)


def test_cap_scene_schema_pins_dialogue_max_items():
    """②：dialogue_max_items 为正整数 ⇒ 段级 schema 给 dialogue 钉 maxItems（解码期硬约束）。"""
    full = {"type": "object"}
    seg = cap_script_schema_for_segment(full, "scene:2", dialogue_max_items=135)
    dlg = seg["properties"]["dialogue"]
    assert dlg["maxItems"] == 135
    # 其余数组键不受影响
    for key in ("present", "props_present", "sfx_hint"):
        assert "maxItems" not in seg["properties"][key]
    # head 段不受该参数影响（无 dialogue 键）
    head_seg = cap_script_schema_for_segment(full, "package_head", dialogue_max_items=135)
    assert "dialogue" not in head_seg["properties"]


def test_cap_scene_schema_dialogue_max_items_absent_when_invalid():
    """②：None／非正数／布尔（bool 是 int 子类）一律不加约束——缺数据不造硬数字。"""
    full = {"type": "object"}
    for bad in (None, 0, -5, True):
        seg = cap_script_schema_for_segment(full, "scene:2", dialogue_max_items=bad)
        assert "maxItems" not in seg["properties"]["dialogue"], bad


def test_script_dialogue_max_items_derives_from_est():
    """②：est × DIALOGUE_SPEED_MAX ÷ 每行最短字数，**与段预算取小**（`T-121` ③）；异常 ⇒ None。"""
    ctx = {"scenes": {3: {"est_seconds": 30}}}
    budget = _script_dialogue_budget_items()
    # (4096 − 2000 − 512) ÷ 40：action 预留从 maxLength 派生（QA B2），schema 允许面不得越过段 max_tokens
    assert budget == 39
    est_derived = 30 * DIALOGUE_SPEED_MAX // SCRIPT_DIALOGUE_MIN_CHARS_PER_LINE
    assert est_derived == 135
    assert _script_dialogue_max_items(ctx, "scene:3") == min(est_derived, budget) == 39
    # est 缺失／非数值／≤0／段名异常 ⇒ None
    assert _script_dialogue_max_items({"scenes": {3: {}}}, "scene:3") is None
    assert _script_dialogue_max_items(
        {"scenes": {3: {"est_seconds": "30"}}}, "scene:3"
    ) is None
    assert _script_dialogue_max_items(
        {"scenes": {3: {"est_seconds": 0}}}, "scene:3"
    ) is None
    assert _script_dialogue_max_items(ctx, "package_head") is None
    assert _script_dialogue_max_items(None, "scene:3") is None
    # est=120：est 派生 540、绝对封顶 160，但**预算派生 39 更紧** ⇒ 39（`T-121` ③）
    assert _script_dialogue_max_items(
        {"scenes": {3: {"est_seconds": 120}}}, "scene:3"
    ) == budget == 39
    # ---- QA E1：est 派生分支必须**活着**（否则「实现退化为 min(160,39)」也全绿）----
    assert _script_dialogue_max_items(
        {"scenes": {3: {"est_seconds": 8}}}, "scene:3"
    ) == 8 * DIALOGUE_SPEED_MAX // SCRIPT_DIALOGUE_MIN_CHARS_PER_LINE == 36
    # ---- QA B2：预算按**实际生效** max_tokens 折算（模板调低 ⇒ 行数同步缩小）----
    assert _script_dialogue_budget_items(2048) < 0  # 预留已超上限
    assert _script_dialogue_max_items(ctx, "scene:3", max_tokens=2048) == 135  # QA B3 降级：退回 est＋封顶
    assert _script_dialogue_max_items(ctx, "scene:3", max_tokens=3000) == 12  # (3000−2000−512)÷40


def test_script_head_sampling_caps_tokens_keeps_temperature():
    """①：head 段 max_tokens 收口 4096（`T-121` ②：2048 尾部偏紧，min 语义不放大），温度不动。"""
    capped = _script_head_sampling(GenParams(temperature=0.8, max_tokens=8192))
    assert capped.max_tokens == SCRIPT_HEAD_MAX_TOKENS == 4096
    assert capped.temperature == 0.8
    # 模板本就保守时不放大
    assert _script_head_sampling(
        GenParams(temperature=0.8, max_tokens=1024)
    ).max_tokens == 1024


# ---- ② 接线测试（假后端）：max_tokens 收口／schema maxItems／trace 观测位 ----
class _RecordingBackend2:
    name = "fake"
    version = "fake-1"

    def __init__(self, results):
        self.calls = []  # (prompt, params, schema)
        self.results = list(results)

    async def generate(self, prompt, params, json_schema):
        self.calls.append((prompt, params, json_schema))
        text, finish = self.results.pop(0) if self.results else ("{}", "stop")
        return SimpleNamespace(
            text=text, prompt_tokens=1, completion_tokens=1, finish_reason=finish
        )


class _CapturePrompts:
    def __init__(self):
        self.seen_vars = []

    def render(self, template, seg_vars):
        self.seen_vars.append(dict(seg_vars))
        return SimpleNamespace(as_text=lambda: "{}")


class _ScriptTemplate:
    name = "tpl"
    id = "TPL-008"
    version = "3"
    variables: list = []
    sampling = {"temperature": 0.8, "max_tokens": 8192}
    required_variables: list[str] = []


_SCRIPT_FULL_SCHEMA = {
    "type": "object",
    "required": ["title", "acts"],
    "properties": {"title": {}, "acts": {"type": "array"}},
}


def test_run_segments_script_wiring_caps_and_schema() -> None:
    """②：_run_segments 真接线——head/scene 段 max_tokens 收口、dialogue maxItems 注入、trace 观测位。"""
    import asyncio

    svc = _svc()
    svc.prompts = _CapturePrompts()  # type: ignore[assignment]
    backend = _RecordingBackend2([("{}", "stop")] * 3)
    script_ctx = {"scenes": synopsis_scene_by_no(_synopsis(1, 2, est=30))}
    segs = ["package_head", "scene:1", "scene:2"]
    produced, seg_trace, pt, ct, trunc = asyncio.run(
        svc._run_segments(
            _ScriptTemplate(), "script",
            {"segment": "auto", "synopsis_json": json.dumps(_synopsis(1, 2), ensure_ascii=False)},
            segs, True, _SCRIPT_FULL_SCHEMA, backend, None, None, script_ctx,
        )
    )
    assert trunc == []
    # `T-121` ②：head 4096 / scene 4096（head 收口依据＝b25 r8 截断 2048、成功 head stop ≤1406）
    assert backend.calls[0][1].max_tokens == SCRIPT_HEAD_MAX_TOKENS == 4096
    assert backend.calls[1][1].max_tokens == SCRIPT_SCENE_MAX_TOKENS == 4096
    assert backend.calls[2][1].max_tokens == 4096
    # ①：温度不动（L3 授权面）
    assert all(c[1].temperature == 0.8 for c in backend.calls)
    # ②：scene 段 schema 钉 dialogue maxItems＝min(est 派生 135, 封顶 160, 预算派生 39)
    #     （`T-121` ③：schema 允许面不得越过段 max_tokens；预算按 effective 4096 折算）
    d1 = backend.calls[1][2]["properties"]["dialogue"]
    assert d1["maxItems"] == 39
    # `T-121` ③ 补（QA B1）：单行台词长度护栏在同一 items 上（只限行数不限行长仍可撞预算）
    assert d1["items"]["properties"]["line"]["maxLength"] == SCRIPT_DIALOGUE_LINE_MAX_CHARS
    assert "dialogue" not in backend.calls[0][2]["properties"]
    # 观测位：trace 记录派生值
    assert seg_trace[0]["dialogue_max_items"] is None
    assert seg_trace[1]["dialogue_max_items"] == 39
    assert seg_trace[2]["dialogue_max_items"] == 39


def test_scene_seg_vars_receives_prior_texts_in_wiring() -> None:
    """④：storyboard 段接线——_scene_seg_vars 拿到 prior_texts（B1 修复在链路上生效）。"""
    import asyncio

    scene1 = {"shots": [{"shot_id": "S01-SH002", "action": {"end": "收枪"},
                         "transition_out": "cut"}]}
    svc = _svc()
    prompts = _CapturePrompts()
    svc.prompts = prompts  # type: ignore[assignment]
    backend = _RecordingBackend2(
        [(json.dumps(scene1, ensure_ascii=False), "stop"), ("{}", "stop")]
    )
    scene_ctx = {1: {"no": 1}, 2: {"no": 2}}
    prior = {"scene:1": "不是 JSON"}  # prior 留坏值：produced（最新成功值）优先于 prior
    asyncio.run(
        svc._run_segments(
            _ScriptTemplate(), "storyboard",
            {"segment": "auto", "script_json": "{}"},
            ["scene:1", "scene:2"], True, None, backend,
            scene_ctx, None, None, prior_texts=prior,
        )
    )
    v2 = prompts.seen_vars[1]
    assert "S01-SH002" in v2["prev_scene_tail"]  # 重采场段也能拿到上一场锚点


def test_script_truncation_feedback_scene_has_budget_numbers():
    """③：场段截断反馈带同源硬数字（台词字数预算＋行数上限），可核查可执行。"""
    fb = _script_truncation_feedback(
        ["scene:3"], {"scenes": {3: {"est_seconds": 30}}}
    )
    assert "scene:3" in fb
    assert "台词总字数 ≤ 270 字" in fb  # 30 × 9
    # `T-121` ③：行数与 schema 注入同源（min(est 派生 135, 封顶 160, 预算派生 39) ⇒ 39）
    assert "dialogue 行数 ≤ 39 行" in fb
    # QA N2：必须要求「先闭合 JSON 再停」——`stop` 在 JSON 中间不进按段重采
    assert "先闭合 JSON 再停" in fb
    # QA N4：max_tokens 与 schema 同源（模板调低时反馈数字同步）
    fb3000 = _script_truncation_feedback(
        ["scene:3"], {"scenes": {3: {"est_seconds": 30}}}, max_tokens=3000
    )
    assert "dialogue 行数 ≤ 12 行" in fb3000  # (3000−2000−512)÷40


def test_script_truncation_feedback_head_has_skeleton_scale():
    """③：head 段截断反馈给骨架规模（≈800~1500 tok），不含场正文。"""
    fb = _script_truncation_feedback(
        ["package_head"], {"scenes": {3: {"est_seconds": 30}}}
    )
    assert "package_head" in fb
    assert "800~1500" in fb
    assert "不写任何场正文" in fb


def test_script_truncation_feedback_est_missing_conservative():
    """③：est 缺失的场段走保守口径（≤200 字），不造硬数字。"""
    fb = _script_truncation_feedback(["scene:3"], {"scenes": {3: {}}})
    assert "总字数 ≤ 200 字" in fb


def test_prev_scene_tail_prior_texts_fallback_storyboard_b1():
    """④（storyboard 同款 B1）：重采场段 produced 无上一场 ⇒ 回退 prior_texts，
    不再注入「本场为第一场，或上一场尚未产出」的假降级文案。"""
    scene1 = {
        "shots": [
            {
                "shot_id": "S01-SH002",
                "action": {"end": "主角收枪离场"},
                "transition_out": "cut",
            }
        ]
    }
    ctx = {1: {"no": 1}, 2: {"no": 2}}
    vars_ = _svc()._scene_seg_vars(
        "scene:2", ctx, produced={}, prior_texts={"scene:1": json.dumps(scene1, ensure_ascii=False)}
    )
    tail = vars_["prev_scene_tail"]
    assert "上一场（第 1 场）末镜" in tail
    assert "S01-SH002" in tail
    assert "本场为第一场，或上一场尚未产出" not in tail
    # produced 优先（最新成功值）：两处都有时用 produced
    vars_prod = _svc()._scene_seg_vars(
        "scene:2", ctx,
        produced={"scene:1": json.dumps(scene1, ensure_ascii=False)},
        prior_texts={"scene:1": "不是 JSON"},
    )
    assert "S01-SH002" in vars_prod["prev_scene_tail"]
    # 两处都没有 ⇒ 真降级（如实说）
    vars_none = _svc()._scene_seg_vars("scene:2", ctx, produced={}, prior_texts={})
    assert "本场为第一场，或上一场尚未产出" in vars_none["prev_scene_tail"]


# ================================================== `T-118`（批次 5：action 护栏＋下游按段预算＋场号机械回填）

def test_cap_scene_schema_pins_action_max_length():
    """①：scene 段 schema 给 action 钉 maxLength（解码期长度护栏）；其余标量键原样。"""
    full = {"type": "object"}
    seg = cap_script_schema_for_segment(full, "scene:1")
    assert seg["properties"]["action"] == {
        "type": "string",
        "maxLength": SCRIPT_ACTION_MAX_CHARS,
    }
    assert SCRIPT_ACTION_MAX_CHARS == 2000  # 证据锚口径（见常量注释：非 est 派生）
    # 其余标量键仍是无约束投影（不借机扩权）
    assert seg["properties"]["slug"] == {}
    assert seg["properties"]["no"] == {}
    # head 段是骨架形态，无 action 键
    head_seg = cap_script_schema_for_segment(full, "package_head")
    assert "action" not in head_seg["properties"]
    # all 模式原样返回（收窄不越界）
    assert cap_script_schema_for_segment(full, "all") is full


def test_run_segments_storyboard_shot_prompt_wiring_caps() -> None:
    """②：下游段接线——storyboard 场段 4096／shot_prompt 单元段 8192；温度逐字不动。"""
    import asyncio

    svc = _svc()
    svc.prompts = _CapturePrompts()  # type: ignore[assignment]
    # storyboard：场段收口 4096（模板 8192 被 min 收口）；温度不动
    backend_sb = _RecordingBackend2([("{}", "stop")] * 2)
    asyncio.run(
        svc._run_segments(
            _ScriptTemplate(), "storyboard",
            {"segment": "auto", "script_json": "{}"},
            ["scene:1", "scene:2"], True, None, backend_sb,
            {1: {"no": 1}, 2: {"no": 2}}, None, None,
        )
    )
    assert all(
        c[1].max_tokens == STORYBOARD_SCENE_MAX_TOKENS == 4096
        for c in backend_sb.calls
    )
    assert all(c[1].temperature == 0.8 for c in backend_sb.calls)
    # shot_prompt：模板 12288 ⇒ head 走 B3（8192）＋unit 收口 8192；unit 温度逐字不动
    backend_sp = _RecordingBackend2([("{}", "stop")] * 2)
    asyncio.run(
        svc._run_segments(
            _ScriptTemplate(), "shot_prompt",
            {"segment": "auto", "script_json": "{}"},
            ["package_head", "unit:U01"], True, None, backend_sp,
            None, None, None,
        )
    )
    assert backend_sp.calls[0][1].max_tokens == 8192  # B3 head 上限（本批不动）
    assert backend_sp.calls[0][1].temperature == 0.4  # B3 降温仍生效
    assert backend_sp.calls[1][1].max_tokens == SHOT_PROMPT_UNIT_MAX_TOKENS == 8192
    assert backend_sp.calls[1][1].temperature == 0.8  # L3 授权面：unit 温度不动


def test_merge_parts_stamps_scene_no_from_segment_name():
    """③：场段产物 no 与段号不一致 ⇒ 机械回填＋告警；骨架声明的场全部装配进幕。

    b24 r8/r9 实锤形态：模型在段内把 no 写成别的场号 ⇒ 合并按产物 no 装配 ⇒
    acts[2].scenes=[] ⇒ 形态闸拒（90s 级整轮失败）。段名是场号唯一真值。
    """
    head = {
        "title": "t", "style_bible": {"a": 1}, "characters": [], "props": [],
        "acts": [
            {"act_no": 1, "act_name": "一", "act_summary": "s", "scene_nos": [1]},
            {"act_no": 2, "act_name": "二", "act_summary": "s", "scene_nos": [2]},
            {"act_no": 3, "act_name": "三", "act_summary": "s", "scene_nos": [3]},
        ],
    }
    s1 = {"no": 1, "slug": "一", "est_seconds": 10}
    s2 = {"no": 2, "slug": "二", "est_seconds": 10}
    s3_bad = {"no": 1, "slug": "三", "est_seconds": 10}  # 段 scene:3 被错标 no=1
    texts = [json.dumps(x, ensure_ascii=False) for x in (head, s1, s2, s3_bad)]
    merged_text, warnings = _merge_parts(
        texts, "script", None,
        ["package_head", "scene:1", "scene:2", "scene:3"],
    )
    merged = json.loads(merged_text)
    acts = merged["acts"]
    # 回填前：场 3 找不到产物 ⇒ acts[2].scenes=[] ⇒ 形态闸拒（缺陷本体）
    assert [len(a["scenes"]) for a in acts] == [1, 1, 1]
    assert acts[2]["scenes"][0]["no"] == 3
    assert acts[2]["scenes"][0]["slug"] == "三"
    assert any("机械回填" in w and "scene:3" in w for w in warnings)
    # 机械派生不受错标影响（三场各 10s）
    assert merged["total_est_seconds"] == 30


def test_merge_parts_stamp_covers_missing_no_and_skips_wrapper():
    """③ 边界：缺 no ⇒ 补段号；scenes[] 包装形态不裁断（原样交合并器）。"""
    bare = {"slug": "x", "est_seconds": 5}  # 缺 no
    merged_text, warnings = _merge_parts(
        [json.dumps(bare, ensure_ascii=False)], "script", None, ["scene:1"]
    )
    assert any("机械回填为 1" in w for w in warnings)
    # 无 head 骨架 ⇒ 场无幕认领（合并侧如实告警路径），本例只验证回填已发生
    merged_doc = json.loads(merged_text)
    assert merged_doc["acts"] == []
    wrapper = {"scenes": [{"no": 9, "slug": "w", "est_seconds": 5}]}
    _, warnings2 = _merge_parts(
        [json.dumps(wrapper, ensure_ascii=False)], "script", None, ["scene:1"]
    )
    assert not any("机械回填" in w for w in warnings2)


def test_merge_parts_without_segs_keeps_legacy_behavior():
    """③：segs 缺省（旧调用方/旧测试）⇒ 不回填，行为逐字不变。"""
    head = {
        "title": "t", "style_bible": {}, "characters": [], "props": [],
        "acts": [
            {"act_no": 1, "act_name": "一", "act_summary": "s", "scene_nos": [1]},
            {"act_no": 2, "act_name": "二", "act_summary": "s", "scene_nos": [2]},
            {"act_no": 3, "act_name": "三", "act_summary": "s", "scene_nos": [3]},
        ],
    }
    s1 = {"no": 1, "slug": "一", "est_seconds": 5}
    s2 = {"no": 2, "slug": "二", "est_seconds": 5}
    s3_bad = {"no": 1, "slug": "三", "est_seconds": 5}
    texts = [json.dumps(x, ensure_ascii=False) for x in (head, s1, s2, s3_bad)]
    merged_text, warnings = _merge_parts(texts, "script", None)
    merged = json.loads(merged_text)
    assert merged["acts"][2]["scenes"] == []  # 旧行为：错标场装配不进幕（形态闸拒）
    assert not any("机械回填" in w for w in warnings)


def test_project_segment_trace_keys_are_contract():
    """④：投影键集断言（抽函数防「观测位失效」回归——b24 十轮 dialogue_max_items 零命中教训）。"""
    from app.services.dialogue_service import _project_segment_trace

    trace = [
        {"segment": "scene:1", "finish_reason": "stop", "completion_tokens": 223,
         "storyboard_scope": "full", "schema_capped": True, "dialogue_max_items": 135,
         "internal_only": "不该外泄的内部键"},
    ]
    out = _project_segment_trace(trace)
    assert set(out[0].keys()) == {
        "segment", "finish_reason", "completion_tokens",
        "storyboard_scope", "schema_capped", "dialogue_max_items",
    }
    assert out[0]["dialogue_max_items"] == 135
    assert "internal_only" not in out[0]
    # 缺键容忍（生成端旧键缺失时投影给默认值，不抛）
    out2 = _project_segment_trace([{"segment": "all"}])
    assert out2[0]["storyboard_scope"] == "full"
    assert out2[0]["schema_capped"] is False
    assert out2[0]["dialogue_max_items"] is None


def test_merge_parts_stamp_covers_bool_no_escape():
    """③ QA C-1：bool 错标（no=true 恰逢 scene:1，`True == 1` 值相等逃逸形态）必须回填。"""
    bare = {"no": True, "slug": "x", "est_seconds": 5}
    merged_text, warnings = _merge_parts(
        [json.dumps(bare, ensure_ascii=False)], "script", None, ["scene:1"]
    )
    assert any("机械回填为 1" in w for w in warnings)
    float_case = {"no": 1.0, "slug": "x", "est_seconds": 5}
    _, warnings2 = _merge_parts(
        [json.dumps(float_case, ensure_ascii=False)], "script", None, ["scene:1"]
    )
    assert any("机械回填为 1" in w for w in warnings2)


# ================================================== `T-121`（批次 6：骨架分区机械对齐＋head 4096＋dialogue 预算同源＋storyboard 反馈）

def test_merge_prunes_out_of_scope_skeleton_declarations_and_splits():
    """①：骨架越界声明剔除＋剔除致空幕 ⇒ 从场数最多的幕分流末场（保 R6）。

    b25 r1 `acts[2]` 缺 `scenes[]` 实锤形态：骨架自由书写场号（9/4 梗概没有）
    ⇒ 装配不出内容 ⇒ 空幕 ⇒ 形态闸拒。场号唯一合法面是梗概。
    """
    syn = _synopsis(1, 2, 3, est=10)
    parts = [
        _head((1, [1, 2, 9]), (2, [3]), (3, [4])),  # 9、4 越界
        _scene_seg(1, est=10),
        _scene_seg(2, est=10),
        _scene_seg(3, est=10),
    ]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    assert any("越界声明" in w and "9" in w for w in warnings)
    assert any("越界声明" in w and "4" in w for w in warnings)
    acts = merged["acts"]
    assert [a["act_no"] for a in acts] == [1, 2, 3]  # R6 三幕不变量
    assert all(a["scenes"] for a in acts)  # 无空幕（分流后）
    assert [s["no"] for s in acts[0]["scenes"]] == [1]  # 场 2 被分流走
    assert [s["no"] for s in acts[1]["scenes"]] == [3]
    assert [s["no"] for s in acts[2]["scenes"]] == [2]  # 分流末场落空幕
    assert any("机械分流场 2" in w for w in warnings)
    assert acts[2]["scenes"][0]["act_no"] == 3  # 归属随新幕机械改写
    assert merged["total_est_seconds"] == 30  # 不丢场


def test_merge_backfills_unclaimed_scene_into_empty_act():
    """①：骨架漏声明（场未认领）⇒ 机械回填进空幕，不丢场、不伪造归属。"""
    syn = _synopsis(1, 2, 3, est=10)
    parts = [
        _head((1, [1]), (2, []), (3, [3])),  # 幕 2 漏声明场 2
        _scene_seg(1, est=10),
        _scene_seg(2, est=10),
        _scene_seg(3, est=10),
    ]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    acts = merged["acts"]
    assert [s["no"] for s in acts[1]["scenes"]] == [2]  # 回填进空幕
    assert acts[1]["scenes"][0]["act_no"] == 2
    assert merged["total_est_seconds"] == 30
    assert any("未被任何幕声明" in w and "act_no=2" in w for w in warnings)


def test_merge_overlapping_declaration_keeps_first_and_rebalances():
    """①：重叠声明装配进先声明的幕；后幕空 ⇒ 分流末场补位（三幕各≥1，R6 保住）。"""
    syn = _synopsis(1, 2, 3, est=10)
    parts = [
        _head((1, [1, 2]), (2, [2]), (3, [3])),  # 场 2 被两幕声明
        _scene_seg(1, est=10),
        _scene_seg(2, est=10),
        _scene_seg(3, est=10),
    ]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    acts = merged["acts"]
    assert any("被多个幕声明" in w for w in warnings)
    assert [s["no"] for s in acts[0]["scenes"]] == [1]
    assert [s["no"] for s in acts[1]["scenes"]] == [2]  # 分流补位后非空
    assert [s["no"] for s in acts[2]["scenes"]] == [3]
    assert merged["total_est_seconds"] == 30


def test_merge_donor_is_act_with_most_scenes_not_last_index():
    """① QA A1：空幕补位取**场数最多**的幕，不是索引最大的候选幕。

    原写法 `max(索引)` ⇒ 两候选时会选靠后的幕（本例 act2 只有 2 场，act1 有 4 场）。
    """
    syn = _synopsis(1, 2, 3, 4, 5, 6, est=10)
    parts = [
        _head((1, [1, 2, 3, 4]), (2, [5, 6]), (3, [99])),  # act3 声明越界场 ⇒ 空
        *[_scene_seg(n, est=10) for n in (1, 2, 3, 4, 5, 6)],
    ]
    merged, warnings = merge_script_parts(parts, synopsis=syn)
    acts = merged["acts"]
    assert [s["no"] for s in acts[0]["scenes"]] == [1, 2, 3]  # act1 让出末场 4
    assert [s["no"] for s in acts[1]["scenes"]] == [5, 6]  # 2 场的幕不动
    assert [s["no"] for s in acts[2]["scenes"]] == [4]  # 空幕由场数最多的幕补位
    assert any("机械分流场 4" in w for w in warnings)


def test_storyboard_truncation_feedback_scene_has_budget_numbers():
    """④：storyboard 场段截断反馈带 est_seconds 与规模锚（同源硬数字可核查）。

    QA C1/C3/C4 订正：锚随 est 外推（常态 1800／封顶 3300）、镜数按 est÷4（不再
    声称「镜数随上游」）、并要求「先闭合 JSON 再停」。
    """
    from app.services.dialogue_service import _storyboard_truncation_feedback

    fb = _storyboard_truncation_feedback(
        ["scene:4"], {4: {"est_seconds": 30, "no": 4}}
    )
    assert "scene:4" in fb
    assert "est_seconds=30" in fb
    assert "1800" in fb  # 常态场锚（est=30 恰为 p90）
    assert "镜数按 est÷4" in fb  # C3：不得写「镜数以上游为准」
    assert "上游为准" not in fb
    assert "先闭合 JSON 再停" in fb  # C4：防把 length 截断转成未闭合 stop
    # C1：大场按 60 tok/秒外推、封顶历史极值 3300
    fb_big = _storyboard_truncation_feedback(["scene:4"], {4: {"est_seconds": 60}})
    assert "3300" in fb_big
    assert "15 镜以内" in fb_big
    # est 缺失 ⇒ 无 est 数字（锚退回 p90，不造 est）
    fb2 = _storyboard_truncation_feedback(["scene:4"], {4: {}})
    assert "est_seconds=" not in fb2
    assert "1800" in fb2


def test_truncation_budget_feedback_selects_stage_context():
    """`T-121` ④ wiring 单点：阶段 → 上下文配对（QA C2/E3：调用点分支不得无覆盖）。

    script 用**梗概**场上下文、storyboard 用**剧本**场上下文——两条独立通道，
    错了会拿到不存在的 est（← b25 逐段 trace 对账时最容易错的一处）。
    """
    from app.services.dialogue_service import _truncation_budget_feedback

    fb_script = _truncation_budget_feedback(
        "script", ["scene:3"], {"scenes": {3: {"est_seconds": 30}}}, {3: {"est_seconds": 99}}
    )
    assert "台词总字数 ≤ 270 字" in fb_script  # 用了梗概的 est=30
    fb_sb = _truncation_budget_feedback(
        "storyboard", ["scene:3"], {"scenes": {3: {"est_seconds": 99}}}, {3: {"est_seconds": 30}}
    )
    assert "est_seconds=30" in fb_sb  # 用了剧本的 est=30
    assert "台词总字数" not in fb_sb
    # 其他阶段：不加数字（也绝不借用别阶段上下文造数字）
    assert _truncation_budget_feedback("shot_prompt", ["unit:U01"], None, {1: {}}) == ""
    # QA N4：sampling 传入 ⇒ script 行数按实际生效 max_tokens 折算
    fb_low = _truncation_budget_feedback(
        "script", ["scene:3"], {"scenes": {3: {"est_seconds": 30}}}, None,
        {"temperature": 0.8, "max_tokens": 3000},
    )
    assert "dialogue 行数 ≤ 12 行" in fb_low


def test_cap_scene_schema_dialogue_items_cover_truth_fields():
    """`T-121` ③ 补（QA B1 第 2 轮）：`dialogue.items` 必须**列全真值字段集**。

    ISSUE-059 实测纪律（`artifact_contract.py`＋`test_contract_engine_constraints.py` 回归锁）：
    `items.properties` 少列字段且无 `required` ⇒ xgrammar 把未列字段**一律禁止**
    （4/4 轮塌缩）。若只列 `line`，产物将失去 `speaker_id`/`type`/`emotion`
    ⇒ `R20` 每行报错（retryable ⇒ 每轮多烧一次采样且不自愈）、`speaker_id` 静默丢失。
    """
    full = {"type": "object"}
    seg = cap_script_schema_for_segment(full, "scene:1", dialogue_max_items=39)
    items = seg["properties"]["dialogue"]["items"]
    props = set(items["properties"])
    # 真值五字段（模板 TPL-008 与真产物 31/31 行）：不等即红（多列/少列都算改口径）
    assert props == {"speaker_id", "speaker_name", "type", "line", "emotion"}
    # 判据真正消费的三个必须强制（R20 读 type、R15 读 line、下游读 speaker_id）
    assert set(items["required"]) >= {"speaker_id", "type", "line"}
    assert items["properties"]["line"]["maxLength"] == SCRIPT_DIALOGUE_LINE_MAX_CHARS
    # 不加 enum（本工程既定裁决：vLLM 会静默忽略该形态，约束等于没写还多一层假象）
    assert "enum" not in items["properties"]["type"]


def test_est_guards_reject_nan_and_inf():
    """QA N3：`json.loads` 接受 NaN/Infinity 字面量 ⇒ 数值守卫必须挡在 `int()` 之前。"""
    from app.services.dialogue_service import (
        _script_dialogue_max_items,
        _storyboard_scene_tok_anchor,
    )

    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _script_dialogue_max_items(
            {"scenes": {3: {"est_seconds": bad}}}, "scene:3"
        ) is None
        assert _storyboard_scene_tok_anchor(bad) == 1800  # 退回 p90 锚，不抛
    fb = _script_truncation_feedback(
        ["scene:3"], {"scenes": {3: {"est_seconds": float("nan")}}}
    )
    assert "总字数 ≤ 200 字" in fb  # 走「est 缺失」保守口径
    # storyboard 侧同款守卫（QA 第 3 轮：该分支此前无覆盖）
    from app.services.dialogue_service import _storyboard_truncation_feedback

    fb_sb = _storyboard_truncation_feedback(["scene:3"], {3: {"est_seconds": float("nan")}})
    assert "est_seconds=" not in fb_sb
    assert "1800" in fb_sb


def test_run_segments_script_budget_tracks_effective_max_tokens():
    """QA 第 2 轮补：三处（采样／schema／trace）都按 effective max_tokens 折算。

    模板 max_tokens=3000（< 4096）⇒ 采样 3000、maxItems＝12、trace＝12——
    若任一处回退成常量 4096 口径，本用例即红（此前三处全为 39 时无法区分）。
    """
    import asyncio

    class _LowCapTemplate(_ScriptTemplate):
        sampling = {"temperature": 0.8, "max_tokens": 3000}

    svc = _svc()
    svc.prompts = _CapturePrompts()  # type: ignore[assignment]
    backend = _RecordingBackend2([("{}", "stop")])
    script_ctx = {"scenes": synopsis_scene_by_no(_synopsis(1, est=30))}
    _, seg_trace, _, _, _ = asyncio.run(
        svc._run_segments(
            _LowCapTemplate(), "script",
            {"segment": "auto", "synopsis_json": json.dumps(_synopsis(1))},
            ["scene:1"], True, _SCRIPT_FULL_SCHEMA, backend, None, None, script_ctx,
        )
    )
    assert backend.calls[0][1].max_tokens == 3000
    assert backend.calls[0][2]["properties"]["dialogue"]["maxItems"] == 12
    assert seg_trace[0]["dialogue_max_items"] == 12
