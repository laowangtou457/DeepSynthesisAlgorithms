# -*- coding: utf-8 -*-
"""`丙`（分段最小镜数）单元测试：组段计划、多单元裁剪、重试定位、口径守恒。

背景（`DEV-20261117-003`／`-004`）：2 镜单元单独成段时，单元级运镜多样性门槛
（`need=2`）要求两镜全异，而该段只有 2 镜可分配 ⇒ 实测最易失守。`丙` 把相邻单元
攒成 ≥N 镜的组（`unit:U01+U02`），**只改调用粒度，不改任何判据**。
"""
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.services.dialogue_service import DialogueService
from app.services.segment import (
    group_units_by_min_shots,
    plan_segments,
    scope_storyboard_for_segment,
    segment_unit_ids,
    unit_shot_counts_of,
)


def _storyboard() -> dict:
    return {
        "units": [
            {"unit_id": "U01", "scene_no": 1, "shot_ids": ["S01-SH001", "S01-SH002"]},
            {"unit_id": "U02", "scene_no": 1, "shot_ids": ["S01-SH003", "S01-SH004"]},
        ],
        "shots": [
            {"shot_id": "S01-SH001", "unit_id": "U01"},
            {"shot_id": "S01-SH002", "unit_id": "U01"},
            {"shot_id": "S01-SH003", "unit_id": "U02"},
            {"shot_id": "S01-SH004", "unit_id": "U02"},
        ],
    }


# ------------------------------------------------------------------ 组段

def test_group_basic_two_shot_units_pair_up() -> None:
    """[2,2] + min=3 ⇒ 一组 4 镜（消灭 2 镜小段）。"""
    assert group_units_by_min_shots(["U01", "U02"], [2, 2], 3) == [["U01", "U02"]]


def test_group_keeps_big_unit_alone_and_merges_tail() -> None:
    """[2,2,3,2]：U03 自成一档；片尾 2 镜余组并入上一组（不在片尾留小段）。"""
    assert group_units_by_min_shots(
        ["U01", "U02", "U03", "U04"], [2, 2, 3, 2], 3
    ) == [["U01", "U02"], ["U03", "U04"]]


def test_group_tail_merge_when_smaller_than_min() -> None:
    """[2,2,2] ⇒ [U01+U02] ＋ 末组 [U03] 仅 2 镜 < 3 ⇒ 并入前组（6 镜 ≤ 2×min）。"""
    assert group_units_by_min_shots(["U01", "U02", "U03"], [2, 2, 2], 3) == [
        ["U01", "U02", "U03"]
    ]


def test_group_tail_merge_capped_at_twice_min() -> None:
    """[2,3,2]：末组并入会到 7 镜 > 2×min=6 ⇒ **不并**，如实留一个小段（QA 中优先级项）。"""
    assert group_units_by_min_shots(["U01", "U02", "U03"], [2, 3, 2], 3) == [
        ["U01", "U02"],
        ["U03"],
    ]


def test_group_off_or_misaligned_falls_back_to_per_unit() -> None:
    """`min_shots<2`、镜数不对齐、含非正数 ⇒ 一律逐单元（不猜、不凑组）。"""
    assert group_units_by_min_shots(["U01", "U02"], [2, 2], 0) == [["U01"], ["U02"]]
    assert group_units_by_min_shots(["U01", "U02"], [2], 3) == [["U01"], ["U02"]]
    assert group_units_by_min_shots(["U01", "U02"], [2, 0], 3) == [["U01"], ["U02"]]


def test_plan_auto_grouped_vs_off() -> None:
    """`auto`：关＝逐单元；开＝组段标签 `unit:U01+U02`；≤6 镜仍整包（阈值不受影响）。"""
    uids = ["U01", "U02", "U03"]
    counts = [2, 2, 2]
    off = plan_segments("auto", shot_count=9, unit_ids=uids, min_shots=0,
                        unit_shot_counts=counts)
    on = plan_segments("auto", shot_count=9, unit_ids=uids, min_shots=3,
                       unit_shot_counts=counts)
    assert off == ["package_head", "unit:U01", "unit:U02", "unit:U03"]
    assert on == ["package_head", "unit:U01+U02+U03"]
    assert plan_segments("auto", shot_count=6, unit_ids=uids, min_shots=3,
                         unit_shot_counts=counts) == ["all"]


def test_plan_unit_group_label_validated_against_upstream() -> None:
    """显式 `unit:U01+U02` 合法；含上游没有的单元 ⇒ 报错（不静默丢弃）。"""
    assert plan_segments("unit:U01+U02", shot_count=4, unit_ids=["U01", "U02"]) == [
        "unit:U01+U02"
    ]
    with pytest.raises(AppError) as ei:
        plan_segments("unit:U01+U09", shot_count=4, unit_ids=["U01", "U02"])
    assert "U09" in str(ei.value)


# ------------------------------------------------------------------ 裁剪

def test_scope_multi_unit_keeps_all_group_shots() -> None:
    """组段裁剪保留组内两单元及其全部镜；单单元段行为不变。"""
    scoped, warnings = scope_storyboard_for_segment("unit:U01+U02", _storyboard())
    assert scoped is not None and warnings == []
    assert [u["unit_id"] for u in scoped["units"]] == ["U01", "U02"]
    assert [s["shot_id"] for s in scoped["shots"]] == [
        "S01-SH001", "S01-SH002", "S01-SH003", "S01-SH004"
    ]
    single, _ = scope_storyboard_for_segment("unit:U02", _storyboard())
    assert [s["shot_id"] for s in single["shots"]] == ["S01-SH003", "S01-SH004"]


def test_scope_unknown_unit_returns_none_with_warning() -> None:
    """组内任一单元不在上游 ⇒ 回退整份注入（宁喂全量，不喂抽掉证据的输入）。"""
    scoped, warnings = scope_storyboard_for_segment("unit:U01+U09", _storyboard())
    assert scoped is None and warnings and "U09" in warnings[0]


def test_unit_shot_counts_requires_declared_equal_actual() -> None:
    """逐单元镜数必须**声明==实测**；整体只靠 `shots[].unit_id` 时按实测；不一致 ⇒ 空。"""
    assert unit_shot_counts_of(_storyboard()) == [2, 2]
    doc = _storyboard()
    doc["shots"] = doc["shots"][:3]  # U02 少产 1 镜（声明 2 ≠ 实测 1）
    assert unit_shot_counts_of(doc) == []
    # 上游整体不填 shot_ids、只靠 shots[].unit_id ⇒ 按实测计
    doc2 = _storyboard()
    for u in doc2["units"]:
        u["shot_ids"] = []
    assert unit_shot_counts_of(doc2) == [2, 2]
    assert unit_shot_counts_of({}) == []
    assert unit_shot_counts_of({"units": [{"shot_ids": []}], "shots": []}) == []


def test_scope_dedupes_duplicate_unit_id() -> None:
    """上游同 id 重复出现 ⇒ 只取首条（否则单单元段 units_cap 会被算成 2）。"""
    doc = _storyboard()
    doc["units"].append(dict(doc["units"][0]))
    scoped, _ = scope_storyboard_for_segment("unit:U01", doc)
    assert [u["unit_id"] for u in scoped["units"]] == ["U01"]


def test_cap_schema_pins_units_floor_for_group() -> None:
    """组段必须把 `units` 的 minItems 也钉到组宽（QA 高风险项：单元可静默消失）。"""
    from app.services.output_schema import cap_pack_array_bounds

    schema = {
        "properties": {
            "units": {"type": "array", "minItems": 1},
            "shots": {"type": "array", "minItems": 2},
        }
    }
    capped = cap_pack_array_bounds(
        schema, units_cap=2, shots_cap=4, shots_floor=4, units_floor=2
    )
    assert capped["properties"]["units"]["maxItems"] == 2
    assert capped["properties"]["units"]["minItems"] == 2  # 一个单元都不能少
    assert capped["properties"]["shots"]["minItems"] == 4
    # 单单元段：与旧行为一致（1..1）
    capped1 = cap_pack_array_bounds(
        schema, units_cap=1, shots_cap=2, shots_floor=2, units_floor=1
    )
    assert capped1["properties"]["units"]["minItems"] == 1


def test_retry_unit_match_uses_word_boundary() -> None:
    """`U01` 不得命中 `U010`（旧实现子串误命中，组段后会放大为整组重采）。"""
    svc = DialogueService.__new__(DialogueService)
    plan = ["package_head", "unit:U01+U02", "unit:U010"]
    texts = {
        "package_head": '{"meta": {"pack_id": "p1"}}',
        "unit:U01+U02": '{"units": [{"unit_id": "U01"}], "shots": [{"shot_id": "S01-SH001"}]}',
        "unit:U010": '{"units": [{"unit_id": "U010"}], "shots": [{"shot_id": "S02-SH001"}]}',
    }
    verdict = SimpleNamespace(retryable=["R11 UNIT_MOVE_UNIQUE：单元 U010 运镜重复"])
    picked, _ = svc._retry_segments(plan, verdict, texts)
    assert picked == ["unit:U010"]


# ------------------------------------------------------ 生产接线（QA 缺口）

def _plan_storyboard() -> dict:
    """7 镜 3 单元（2/2/3）——超过 `AUTO_SHOT_THRESHOLD=6`，走 `package_head`＋逐单元。"""
    units, shots = [], []
    for idx, (uid, n) in enumerate((("U01", 2), ("U02", 2), ("U03", 3)), start=1):
        ids = [f"S01-SH{idx:02d}{k:01d}" for k in range(n)]
        units.append({"unit_id": uid, "scene_no": 1, "shot_ids": ids})
        shots += [{"shot_id": sid, "unit_id": uid} for sid in ids]
    return {"units": units, "shots": shots}


def _plan_rec() -> SimpleNamespace:
    import json

    return SimpleNamespace(
        session_id="sess_plan",
        artifacts={"storyboard": {"text": json.dumps(_plan_storyboard(), ensure_ascii=False)}},
    )


def _plan_tpl() -> SimpleNamespace:
    return SimpleNamespace(
        variables=[{"name": "segment"}],
        default_of=lambda name: "auto",
    )


def test_segment_plan_wires_min_shots_from_settings(monkeypatch) -> None:
    """接线：`_segment_plan` 必须真的把 `segment_plan_min_shots` 传下去并组段。"""
    from app.core.config import get_settings

    svc = DialogueService.__new__(DialogueService)
    monkeypatch.setenv("APP_SEGMENT_PLAN_MIN_SHOTS", "3")
    get_settings.cache_clear()
    try:
        plan = svc._segment_plan(_plan_tpl(), "shot_prompt", _plan_rec(), {})
    finally:
        get_settings.cache_clear()
    assert plan == ["package_head", "unit:U01+U02", "unit:U03"]
    # 2+2=4 ≥3 成组；U03 自身 3 镜自成一档 ⇒ 两段（无余组可并）


def test_segment_plan_default_off_keeps_per_unit(monkeypatch) -> None:
    """默认 `0` ⇒ 逐单元（生产行为零变化）。"""
    from app.core.config import get_settings

    svc = DialogueService.__new__(DialogueService)
    monkeypatch.delenv("APP_SEGMENT_PLAN_MIN_SHOTS", raising=False)
    get_settings.cache_clear()
    try:
        plan = svc._segment_plan(_plan_tpl(), "shot_prompt", _plan_rec(), {})
    finally:
        get_settings.cache_clear()
    assert plan == ["package_head", "unit:U01", "unit:U02", "unit:U03"]


def test_shot_counts_rejects_out_of_range_units() -> None:
    """QA 复验条件①：出现 1 镜／≥4 镜单元 ⇒ 不组段（否则语义无解）。"""
    doc = _storyboard()
    doc["units"][0]["shot_ids"] = ["S01-SH001"]  # U01 只有 1 镜（声明==实测）
    doc["shots"] = [s for s in doc["shots"] if s["shot_id"] != "S01-SH002"]
    assert unit_shot_counts_of(doc) == []


def test_segment_plan_disabled_when_scope_off(monkeypatch) -> None:
    """QA 复验条件②：裁剪关闭 ⇒ 组段禁用（否则会绕过 units_floor 保护）。"""
    from app.core.config import get_settings

    svc = DialogueService.__new__(DialogueService)
    monkeypatch.setenv("APP_SEGMENT_PLAN_MIN_SHOTS", "3")
    monkeypatch.setenv("APP_SHOT_PROMPT_SEGMENT_SCOPE", "false")
    get_settings.cache_clear()
    try:
        plan = svc._segment_plan(_plan_tpl(), "shot_prompt", _plan_rec(), {})
    finally:
        get_settings.cache_clear()
    assert plan == ["package_head", "unit:U01", "unit:U02", "unit:U03"]


def test_segment_plan_rejects_out_of_range_min_shots(monkeypatch) -> None:
    """QA 复验条件④：`min_shots` 越界（如 5）⇒ 告警并回退 0，不组出超体积段。"""
    from app.core.config import get_settings

    svc = DialogueService.__new__(DialogueService)
    monkeypatch.setenv("APP_SEGMENT_PLAN_MIN_SHOTS", "5")
    get_settings.cache_clear()
    try:
        plan = svc._segment_plan(_plan_tpl(), "shot_prompt", _plan_rec(), {})
    finally:
        get_settings.cache_clear()
    assert plan == ["package_head", "unit:U01", "unit:U02", "unit:U03"]


def test_segment_unit_ids_parsing() -> None:
    """段名解析：多单元、空 id、非单元段。"""
    assert segment_unit_ids("unit:U01+U02") == ["U01", "U02"]
    assert segment_unit_ids("unit:U01") == ["U01"]
    assert segment_unit_ids("unit:") == []
    assert segment_unit_ids("all") == []


# ------------------------------------------------------------------ 重试定位

def test_retry_picks_multi_unit_group_by_any_member() -> None:
    """判据消息只提 `U02` ⇒ 含 U02 的组段必须被选中（不再依赖段名字面匹配）。"""
    svc = DialogueService.__new__(DialogueService)
    plan = ["package_head", "unit:U01+U02", "unit:U03"]
    texts = {
        "package_head": '{"meta": {"pack_id": "p1"}}',
        "unit:U01+U02": '{"units": [{"unit_id": "U01"}, {"unit_id": "U02"}], "shots": [{"shot_id": "S01-SH003"}]}',
        "unit:U03": '{"units": [{"unit_id": "U03"}], "shots": [{"shot_id": "S02-SH001"}]}',
    }
    verdict = SimpleNamespace(retryable=["R11 UNIT_MOVE_UNIQUE：单元 U02 运镜重复"])
    picked, scope = svc._retry_segments(plan, verdict, texts)
    assert picked == ["unit:U01+U02"]
    assert scope is None
