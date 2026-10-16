"""分段生成模块测试（调用计划、产物解析、结构合并）。

背景（`T-004` 的实质工作）：`segment=auto` 的调用循环此前**零实现**——
服务层只单次 `by_stage()` 调用，`segment` 甚至不进 `variables`；
而 14 镜整包 ≈1.2 万字符**必被截断**（模板自述，评审 `PR-08` 实测）。
"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.segment import (
    AUTO_SHOT_THRESHOLD,
    merge_segments,
    parse_json_object,
    plan_segments,
    shot_count_of,
    unit_ids_of,
)


def _storyboard(shot_count: int, units: list[str] | None = None) -> dict:
    return {
        "units": [{"unit_id": u} for u in (units or [])],
        "shots": [
            {"shot_id": f"S01-SH{i:03d}", "scene_no": 1, "shot_no": i}
            for i in range(1, shot_count + 1)
        ],
    }


# --------------------------------------------------------------- 上游取数
def test_shot_count_and_unit_ids_from_storyboard() -> None:
    sb = _storyboard(4, ["U01", "U02"])
    assert shot_count_of(sb) == 4
    assert unit_ids_of(sb) == ["U01", "U02"]


def test_unparseable_upstream_yields_zero_not_exception() -> None:
    assert shot_count_of(None) == 0
    assert unit_ids_of({"shots": "不是列表"}) == []


def test_unit_without_unit_id_is_explicit_error() -> None:
    """缺 `unit_id` 不静默跳过——跳过会让该单元的分镜无处安放。"""
    with pytest.raises(AppError) as ei:
        unit_ids_of({"units": [{"scene_no": 1}]})
    assert ei.value.code is ErrorCode.GENERATION_FAILED


# --------------------------------------------------------------- 调用计划
@pytest.mark.parametrize("value", ["all", "package_head", "gap_ledger"])
def test_fixed_segments_pass_through(value: str) -> None:
    assert plan_segments(value, shot_count=99, unit_ids=["U01"]) == [value]


def test_default_is_auto_and_small_board_stays_whole() -> None:
    assert plan_segments(None, shot_count=0) == ["all"]
    assert plan_segments("", shot_count=AUTO_SHOT_THRESHOLD) == ["all"]


def test_threshold_boundary_is_inclusive() -> None:
    """`≤6 镜用 all` 是**闭区间**——第 7 镜才拆。"""
    assert plan_segments("auto", shot_count=AUTO_SHOT_THRESHOLD) == ["all"]
    plan = plan_segments(
        "auto", shot_count=AUTO_SHOT_THRESHOLD + 1, unit_ids=["U01", "U02"]
    )
    assert plan == ["package_head", "unit:U01", "unit:U02"]


def test_auto_over_threshold_without_units_is_explicit_error() -> None:
    with pytest.raises(AppError) as ei:
        plan_segments("auto", shot_count=14, unit_ids=[])
    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert "package_head" in ei.value.message


def test_explicit_unit_segment_validated_against_upstream() -> None:
    assert plan_segments("unit:U02", shot_count=8, unit_ids=["U01", "U02"]) == ["unit:U02"]
    with pytest.raises(AppError):
        plan_segments("unit:U09", shot_count=8, unit_ids=["U01"])


def test_unit_segment_requires_identifier() -> None:
    with pytest.raises(AppError) as ei:
        plan_segments("unit:", shot_count=1)
    assert ei.value.code is ErrorCode.VALIDATION_ERROR


def test_unknown_segment_is_rejected_not_guessed() -> None:
    with pytest.raises(AppError) as ei:
        plan_segments("half", shot_count=1)
    assert ei.value.code is ErrorCode.VALIDATION_ERROR
    assert "known" in ei.value.details


# --------------------------------------------------------------- 产物解析
def test_parse_accepts_bare_json_and_fenced_json() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_tolerates_surrounding_prose() -> None:
    assert parse_json_object('这是结果：{"a": 1} 完毕') == {"a": 1}


def test_parse_rejects_empty_and_non_object() -> None:
    for bad in ("", "   ", "[1, 2]", "no json here"):
        with pytest.raises(AppError) as ei:
            parse_json_object(bad)
        assert ei.value.code is ErrorCode.GENERATION_FAILED


# --------------------------------------------------------------- 结构合并
def _head() -> dict:
    return {
        "schema_version": "2.1.0",
        "meta": {"pack_id": "AC-PK-20261015-ABCD1234"},
        "style_bible": {"style_id": "ST-01"},
        "characters": [{"character_id": "CHR-01"}],
        "aigc_meta": {"ProduceID": "AC-PK-20261015-ABCD1234"},
        "units": [],
        "shots": [],
    }


def test_merge_takes_head_from_first_part_and_concatenates_body() -> None:
    u1 = {"units": [{"unit_id": "U01"}], "shots": [{"shot_id": "S01-SH002", "scene_no": 1, "shot_no": 2}]}
    u2 = {"units": [{"unit_id": "U02"}], "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}]}
    merged, warnings = merge_segments([_head(), u1, u2])

    assert merged["schema_version"] == "2.1.0"
    assert merged["meta"] == {"pack_id": "AC-PK-20261015-ABCD1234"}
    assert [u["unit_id"] for u in merged["units"]] == ["U01", "U02"]
    # 镜序按 scene_no → shot_no 重排（交付规范 §3.7），不依赖分段到达次序
    assert [s["shot_id"] for s in merged["shots"]] == ["S01-SH001", "S01-SH002"]
    assert warnings == []


def test_merge_orders_units_naturally_not_lexically() -> None:
    """`U02` 必须排在 `U10` 之前（字典序会排反）。"""
    parts = [
        {"units": [{"unit_id": uid}], "shots": []} for uid in ("U10", "U02", "U01")
    ]
    merged, _ = merge_segments(parts)
    assert [u["unit_id"] for u in merged["units"]] == ["U01", "U02", "U10"]


def test_merge_keeps_first_on_conflicting_duplicate_and_warns() -> None:
    a = {"units": [], "shots": [{"shot_id": "S01-SH001", "shot_no": 1, "prompt_zh": "先到"}]}
    b = {"units": [], "shots": [{"shot_id": "S01-SH001", "shot_no": 1, "prompt_zh": "后到"}]}
    merged, warnings = merge_segments([_head(), a, b])
    assert merged["shots"][0]["prompt_zh"] == "先到"
    assert any("S01-SH001" in w for w in warnings)


def test_merge_warns_when_head_field_conflicts() -> None:
    second = {"schema_version": "9.9.9"}
    merged, warnings = merge_segments([_head(), second])
    assert merged["schema_version"] == "2.1.0"  # 先到先得
    assert any("schema_version" in w for w in warnings)


def test_merge_reports_missing_required_top_keys_without_fabricating() -> None:
    """缺必需键**只告警、不补齐**——补齐就是编造。"""
    merged, warnings = merge_segments([{"units": [], "shots": []}])
    assert any("必需键" in w for w in warnings)
    assert "meta" not in merged
    assert "schema_version" not in merged


def test_merge_skips_non_object_part_and_records_warning() -> None:
    merged, warnings = merge_segments([_head(), "不是对象"])  # type: ignore[list-item]
    assert merged["schema_version"] == "2.1.0"
    assert any("不是 JSON 对象" in w for w in warnings)


def test_merge_skips_body_items_missing_identifier() -> None:
    part = {"units": [{"scene_no": 1}], "shots": [{"shot_no": 1}]}
    merged, warnings = merge_segments([part])
    assert merged["units"] == [] and merged["shots"] == []
    assert len([w for w in warnings if "已跳过" in w]) == 2
