# -*- coding: utf-8 -*-
"""`T-101`／`PRO-015` `shot_prompt` 段级体积承接的单元测试（A 期，2026-11-05）。

⚠️ 覆盖面三组，与 `PRO-015` §3.1 施工清单一一对应：
  ① **段级输入裁剪**：`scope_storyboard_for_segment` 的切片纪律
     （`package_head` 去 `shots[]`；`unit:` 只留本单元与本单元镜；
     uid 不中／上游非对象 ⇒ `None`＋告警，**不猜测**）；
  ② **裁剪注入接线**：开关开 ⇒ 段变量被换成紧凑序列化的裁剪副本；
     开关关／非 shot_prompt 段名 ⇒ `full`；裁剪回退 ⇒ `full`＋留痕；
  ③ **重试 shot_id 定位**：`R34` 只列 shot_id 的报错 ⇒ 属主段被挑中；
     场前缀兜底（镜没生成出来的形态）；仍定位不到 ⇒ `scope_fallback` 保底。

⚠️ 不真调模型（与 `test_scene_orchestration.py` 同构，`__new__` 免依赖构造＋假后端）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.dialogue_service import DialogueService
from app.services.output_schema import cap_pack_array_bounds
from app.services.segment import scope_storyboard_for_segment


def _svc() -> DialogueService:
    return DialogueService.__new__(DialogueService)


def _pack_storyboard() -> dict:
    """两个单元／4 镜的上游分镜（含头部键与 unspecified，形态对齐 `HEAD_KEYS_STORYBOARD`）。"""
    return {
        "title": "片名", "genre": "剧情", "style_ref": "STYLE-01",
        "aspect_ratio_default": "16:9", "total_duration_ms": 20000,
        "units": [
            {"unit_id": "U01", "scene_no": 1, "shot_ids": ["S01-SH001", "S01-SH002"],
             "soundscape": "环境"},
            {"unit_id": "U02", "scene_no": 2, "shot_ids": ["S02-SH001", "S02-SH002"],
             "soundscape": "安静"},
        ],
        "shots": [
            {"shot_id": "S01-SH001", "unit_id": "U01", "scene_no": 1, "shot_no": 1},
            {"shot_id": "S01-SH002", "unit_id": "U01", "scene_no": 1, "shot_no": 2},
            {"shot_id": "S02-SH001", "unit_id": "U02", "scene_no": 2, "shot_no": 1},
            {"shot_id": "S02-SH002", "unit_id": "U02", "scene_no": 2, "shot_no": 2},
        ],
        "forbidden_items": ["血腥"],
        "unspecified": [{"field": "dialogue", "reason": "客户未定"}],
        "quality_gate": {"self_check": "自查通过"},
    }


# ------------------------------------------------------------- ① 裁剪纯函数

def test_scope_package_head_keeps_units_drops_shots() -> None:
    scoped, warns = scope_storyboard_for_segment("package_head", _pack_storyboard())
    assert scoped is not None and warns == []
    assert scoped["shots"] == []                      # 头部段不产镜：镜明细（最大体积块）不注入
    assert [u["unit_id"] for u in scoped["units"]] == ["U01", "U02"]  # units 全量保留（供枚举）
    for k in ("title", "genre", "style_ref", "aspect_ratio_default", "forbidden_items",
              "total_duration_ms", "unspecified", "quality_gate"):
        assert k in scoped                             # 头部键与小键全保留
    assert scoped["unspecified"] == [{"field": "dialogue", "reason": "客户未定"}]


def test_scope_unit_filters_to_own_unit_and_shots() -> None:
    scoped, warns = scope_storyboard_for_segment("unit:U02", _pack_storyboard())
    assert scoped is not None and warns == []
    assert [u["unit_id"] for u in scoped["units"]] == ["U02"]
    assert [s["shot_id"] for s in scoped["shots"]] == ["S02-SH001", "S02-SH002"]
    assert scoped["title"] == "片名"                   # 头部键仍在（跨段一致性素材）


def test_scope_unit_picks_shots_by_union_when_unit_id_missing_on_shots() -> None:
    """`shots[].unit_id` 缺失时按 `units[].shot_ids` 并集收窄（两条判据是并集）。"""
    sb = _pack_storyboard()
    for s in sb["shots"]:
        s.pop("unit_id")
    scoped, _ = scope_storyboard_for_segment("unit:U01", sb)
    assert [s["shot_id"] for s in scoped["shots"]] == ["S01-SH001", "S01-SH002"]


def test_scope_unit_reports_missing_shots_without_fabricating() -> None:
    """单元声明的镜在上游 shots[] 缺 ⇒ 只留痕，不编造。"""
    sb = _pack_storyboard()
    sb["shots"] = [s for s in sb["shots"] if s["shot_id"] != "S02-SH002"]
    scoped, warns = scope_storyboard_for_segment("unit:U02", sb)
    assert scoped is not None
    assert [s["shot_id"] for s in scoped["shots"]] == ["S02-SH001"]
    assert len(warns) == 1 and "S02-SH002" in warns[0]


def test_scope_unit_not_found_returns_none_with_warning() -> None:
    scoped, warns = scope_storyboard_for_segment("unit:U09", _pack_storyboard())
    assert scoped is None                             # 回退整份注入（不猜测）
    assert len(warns) == 1 and "U09" in warns[0]


def test_scope_ignores_other_segment_names_and_bad_input() -> None:
    assert scope_storyboard_for_segment("all", _pack_storyboard())[0] is None
    scoped, warns = scope_storyboard_for_segment("unit:U01", "not-a-dict")  # type: ignore[arg-type]
    assert scoped is None and warns


# ------------------------------------------------------- ② 裁剪注入接线（假后端）

class _RecordingBackend:
    name = "fake"
    version = "fake-1"

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.schemas: list[dict | None] = []

    async def generate(self, prompt: str, params, json_schema):
        self.seen.append(prompt)
        self.schemas.append(json_schema)
        text = json.dumps({"units": [], "shots": []}, ensure_ascii=False)
        return SimpleNamespace(
            text=text, prompt_tokens=1, completion_tokens=1, finish_reason="stop"
        )


class _Prompts:
    def render(self, template, seg_vars):
        return SimpleNamespace(as_text=lambda: json.dumps(
            {"storyboard_json": seg_vars.get("storyboard_json", ""),
             "segment": seg_vars.get("segment", "")}, ensure_ascii=False))


class _Template:
    name = "tpl"
    id = "TPL-009"
    version = "1"
    variables: list = []
    sampling: dict = {}
    required_variables: list[str] = []


#: 整包引擎 schema 的最小形态（对齐 `CFG-006` 的关键边界：units minItems=1、shots minItems=2、无 maxItems）。
_PACK_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "meta", "style_bible", "units", "shots", "aigc_meta"],
    "properties": {
        "schema_version": {"type": "string"},
        "units": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "shots": {"type": "array", "minItems": 2, "items": {"type": "object"}},
    },
}


async def _run(segs, scope_on) -> tuple[list, _RecordingBackend]:
    import asyncio

    svc = _svc()
    svc.prompts = _Prompts()  # type: ignore[assignment]
    backend = _RecordingBackend()
    merged = {"storyboard_json": json.dumps(_pack_storyboard(), ensure_ascii=False),
              "segment": "auto"}
    produced, seg_trace, pt, ct, trunc = await svc._run_segments(
        _Template(), "shot_prompt", merged, segs, True, _PACK_SCHEMA, backend, None,
        {"storyboard": _pack_storyboard()} if scope_on else None,
    )
    return seg_trace, backend


def test_run_segments_scopes_storyboard_per_segment() -> None:
    import asyncio

    trace, backend = asyncio.run(_run(["package_head", "unit:U01"], scope_on=True))
    assert [t["storyboard_scope"] for t in trace] == ["scoped", "scoped"]
    assert [t["schema_capped"] for t in trace] == [True, True]
    # 第 1 次调用的输入里：shots 为空（头部段裁剪）
    first = json.loads(backend.seen[0].split("\n", 1)[1])
    assert json.loads(first["storyboard_json"])["shots"] == []
    # 第 2 次（unit:U01）：只有 U01 的两镜
    second = json.loads(backend.seen[1].split("\n", 1)[1])
    sb = json.loads(second["storyboard_json"])
    assert [u["unit_id"] for u in sb["units"]] == ["U01"]
    assert [s["shot_id"] for s in sb["shots"]] == ["S01-SH001", "S01-SH002"]


def test_run_segments_caps_engine_schema_per_segment() -> None:
    import asyncio

    trace, backend = asyncio.run(_run(["package_head", "unit:U01"], scope_on=True))
    head_schema, unit_schema = backend.schemas[0], backend.schemas[1]
    # 头部段：units/shots 上限 0（且 minItems 被压到 0 —— 否则 schema 不可满足）
    assert head_schema["properties"]["units"]["maxItems"] == 0
    assert head_schema["properties"]["units"]["minItems"] == 0
    assert head_schema["properties"]["shots"]["maxItems"] == 0
    assert head_schema["properties"]["shots"]["minItems"] == 0
    # 单元段：units 上限 1；shots 上限＝该单元上游镜数（2）
    assert unit_schema["properties"]["units"]["maxItems"] == 1
    assert unit_schema["properties"]["shots"]["maxItems"] == 2
    # required 不动（空数组仍满足必需键，合并端幂等）
    assert "units" in head_schema.get("required", [])
    assert "shots" in head_schema.get("required", [])


def test_run_segments_schema_uncapped_when_scope_off() -> None:
    import asyncio

    trace, backend = asyncio.run(_run(["unit:U01"], scope_on=False))
    assert trace[0]["schema_capped"] is False
    assert "maxItems" not in (backend.schemas[0] or {}).get("properties", {}).get("units", {})


def test_run_segments_full_when_scope_ctx_absent() -> None:
    import asyncio

    trace, backend = asyncio.run(_run(["unit:U01"], scope_on=False))
    assert trace[0]["storyboard_scope"] == "full"
    first = json.loads(backend.seen[0].split("\n", 1)[1])
    assert len(json.loads(first["storyboard_json"])["shots"]) == 4   # 整份


def test_run_segments_falls_back_to_full_on_scope_miss() -> None:
    import asyncio

    trace, backend = asyncio.run(_run(["unit:U09"], scope_on=True))
    assert trace[0]["storyboard_scope"] == "full"                    # uid 不中 ⇒ 整份＋留痕
    assert len(json.loads(backend.seen[0].split("\n", 1)[1])["storyboard_json"]) > 0


# ------------------------------------------------------------ ③ 重试 shot_id 定位

def _texts_with_units() -> dict:
    """两段的产物文本：`unit:U01` 含 S01 两镜、`unit:U02` 含 S02 两镜。"""
    return {
        "package_head": json.dumps({"schema_version": "2.1.0", "meta": {}}, ensure_ascii=False),
        "unit:U01": json.dumps({"units": [{"unit_id": "U01", "scene_no": 1, "shot_ids": ["S01-SH001", "S01-SH002"]}],
                                "shots": [{"shot_id": "S01-SH001"}, {"shot_id": "S01-SH002"}]}, ensure_ascii=False),
        "unit:U02": json.dumps({"units": [{"unit_id": "U02", "scene_no": 2, "shot_ids": ["S02-SH001", "S02-SH002"]}],
                                "shots": [{"shot_id": "S02-SH001"}, {"shot_id": "S02-SH002"}]}, ensure_ascii=False),
    }


def test_retry_locates_unit_by_shot_id_containment() -> None:
    """`R34` 真机形态：报错只列 shot_id（无 `U` 字面）⇒ 属主段被挑中。"""
    verdict = SimpleNamespace(retryable=[
        "shot_prompt · R34 EN_CAMERA_SENTENCE：2 镜的 prompt_en 缺以 `The camera` 起句的独立句"
        " → S02-SH002；S03-SH001"
    ])
    picked, note = _svc()._retry_segments(
        ["package_head", "unit:U01", "unit:U02"], verdict, _texts_with_units())
    assert picked == ["unit:U02"] and note is None


def test_retry_scene_prefix_fallback_picks_owner_unit() -> None:
    """镜整段没生成出来（任何段文本都找不到该 shot_id）⇒ 场前缀兜底命中属主单元。"""
    verdict = SimpleNamespace(retryable=["R41：S01-SH009 不存在于产物"])
    picked, note = _svc()._retry_segments(
        ["package_head", "unit:U01", "unit:U02"], verdict, _texts_with_units())
    assert picked == ["unit:U01"] and note is None


def test_retry_still_falls_back_when_nothing_locatable() -> None:
    verdict = SimpleNamespace(retryable=["某条无定位信息的报错"])
    picked, note = _svc()._retry_segments(
        ["package_head", "unit:U01", "unit:U02"], verdict, _texts_with_units())
    assert picked == ["package_head", "unit:U01", "unit:U02"] and note == "scope_fallback"


def test_retry_old_u_literal_rule_still_works() -> None:
    """规则 1（`U` 字面）不被新规则破坏。"""
    verdict = SimpleNamespace(retryable=["R11 UNIT_MOVE_UNIQUE：U01 运镜重复"])
    picked, _ = _svc()._retry_segments(
        ["package_head", "unit:U01", "unit:U02"], verdict, _texts_with_units())
    assert picked == ["unit:U01"]
# --------------------------------------------- ④ 引擎 schema 按段收窄（纯函数）

def test_cap_pack_array_bounds_sets_max_and_floors_min() -> None:
    src = {
        "type": "object",
        "required": ["units", "shots"],
        "properties": {
            "units": {"type": "array", "minItems": 1},
            "shots": {"type": "array", "minItems": 2},
        },
    }
    out = cap_pack_array_bounds(src, units_cap=0, shots_cap=0)
    # cap < minItems ⇒ minItems 压到 0（否则 schema 不可满足，引擎编译期即拒收）
    assert out["properties"]["units"] == {"type": "array", "minItems": 0, "maxItems": 0}
    assert out["properties"]["shots"] == {"type": "array", "minItems": 0, "maxItems": 0}
    # 原 schema 不被原地改动（深拷贝）
    assert src["properties"]["units"] == {"type": "array", "minItems": 1}
    assert "maxItems" not in src["properties"]["units"]


def test_cap_pack_array_bounds_keeps_min_when_cap_above_it() -> None:
    src = {"properties": {"shots": {"type": "array", "minItems": 2}}}
    out = cap_pack_array_bounds(src, units_cap=1, shots_cap=3)
    assert out["properties"]["shots"]["minItems"] == 2     # cap 3 ≥ minItems 2 ⇒ 不动
    assert out["properties"]["shots"]["maxItems"] == 3


def test_cap_pack_array_bounds_passthrough_none_and_non_array() -> None:
    assert cap_pack_array_bounds(None, units_cap=0, shots_cap=0) is None
    src = {"properties": {"units": {"type": "object"}}}    # 非 array ⇒ 不动
    out = cap_pack_array_bounds(src, units_cap=0, shots_cap=0)
    assert out["properties"]["units"] == {"type": "object"}


# --------------------- ⑤ `R31` 镜数下限（裁决 2 修法 A：minItems == maxItems == 上游镜数）

def test_cap_pack_array_bounds_shots_floor_lifts_min_to_upstream() -> None:
    """单元段：`minItems` 抬到上游镜数 ⇒ 「少写镜」从**事后判 `R31`** 变成**事中不可生成**。

    实测依据（2026-11-05 探测器三件）：
    - `_probe_engine_bound_witness.py` 独立取证「数组边界确实进 grammar」
      （`maxItems=1` 精确 1 镜；`minItems=20` 被逼跑满 `max_tokens`）；
    - `_probe_r31_shots_min_n12.py`：`minItems=maxItems=3` **12/12 零失败、
      镜数恒 3、无 `finish_reason=length`**、`completion_tokens` 恒 1948。
    """
    src = {"properties": {"units": {"type": "array", "minItems": 1},
                          "shots": {"type": "array", "minItems": 2}}}
    out = cap_pack_array_bounds(src, units_cap=1, shots_cap=4, shots_floor=4)
    assert out["properties"]["shots"] == {
        "type": "array", "minItems": 4, "maxItems": 4}
    # `units` 不设下限（只约束镜数），仍按 cap 处理
    assert out["properties"]["units"] == {
        "type": "array", "minItems": 1, "maxItems": 1}


def test_cap_pack_array_bounds_shots_floor_never_exceeds_cap() -> None:
    """`floor > cap` 时必须收敛到 `cap`——`minItems > maxItems` 是不可满足的 schema。"""
    src = {"properties": {"shots": {"type": "array", "minItems": 2}}}
    out = cap_pack_array_bounds(src, units_cap=1, shots_cap=2, shots_floor=5)
    assert out["properties"]["shots"]["minItems"] == 2
    assert out["properties"]["shots"]["maxItems"] == 2


def test_cap_pack_array_bounds_head_segment_keeps_no_floor() -> None:
    """头部段（`shots_cap=0`）不传 `shots_floor` ⇒ 仍走「cap < minItems ⇒ 压 0」老路。"""
    src = {"properties": {"shots": {"type": "array", "minItems": 2}}}
    out = cap_pack_array_bounds(src, units_cap=0, shots_cap=0)
    assert out["properties"]["shots"] == {
        "type": "array", "minItems": 0, "maxItems": 0}
