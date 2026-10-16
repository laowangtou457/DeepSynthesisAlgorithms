"""内容足量性探测的单测（`ISSUE-045`）。

用例的每一个数值都取自**真跑产物**，不是构造出来的数字：

| 用例 | 对应的实测事实 |
| --- | --- |
| 剧本层 Σ场秒 ≠ 声明总时长 | r5 剧本：`acts` 仅 1 幕 1 场 15 秒，`total_est_seconds` 自报 **108**（差 7.2 倍） |
| 分镜层 Σ镜毫秒 ≠ 声明总时长 | r4 分镜：Σ15,000 ms，`total_duration_ms` 自报 **45,000** |
| 分镜层场覆盖不全 | r4 分镜：**3 镜只覆盖第 1 场**，第 2~5 场全部漏拍且 `unspecified` 无记 |
| 单元规模越界 | 真跑分镜多次出现 1 镜单元（离线 `R10` 同口径） |
| 单场时长低于下限 | 离线 `R22` 口径：≥8 秒（4s × 最少 2 镜） |
| 不可解析／未登记阶段 | **不假装通过**：一律 `checked=false` |
"""

from __future__ import annotations

import json

import pytest

from app.services import content_adequacy


def _script(acts, total):
    return json.dumps(
        {
            "title": "雨夜",
            "logline": "一句话",
            "genre": "科幻惊悚",
            "style_bible": {"style_id": "ST-01"},
            "characters": [],
            "props": [],
            "acts": acts,
            "forbidden_items": [],
            "total_est_seconds": total,
            "unspecified": [],
        },
        ensure_ascii=False,
    )


def _storyboard(shots, total, units):
    return json.dumps(
        {
            "title": "雨夜",
            "genre": "科幻惊悚",
            "style_ref": "ST-01",
            "aspect_ratio_default": "16:9",
            "total_duration_ms": total,
            "units": units,
            "shots": shots,
            "forbidden_items": [],
            "unspecified": [],
            "quality_gate": {},
        },
        ensure_ascii=False,
    )


# ------------------------------------------------------------------ 剧本层
def test_script_total_mismatch_is_flagged() -> None:
    """r5 实测：声明 108 秒、实际只切出 1 场 15 秒。"""
    acts = [{"act_no": 1, "scenes": [{"no": 1, "est_seconds": 15}]}]
    res = content_adequacy.assess("script", _script(acts, 108))
    assert res["checked"] is True and res["ok"] is False
    codes = [f["code"] for f in res["findings"]]
    assert "script_total_mismatch" in codes
    detail = next(f for f in res["findings"] if f["code"] == "script_total_mismatch")
    assert detail["sum_scene_seconds"] == 15 and detail["total_est_seconds"] == 108


def test_script_within_tolerance_is_ok() -> None:
    """r2 实测：Σ108 vs 声明 120 —— 偏差恰 10%，**在容差内**，不得判死。"""
    acts = [
        {"act_no": i, "scenes": [{"no": 2 * i - 1, "est_seconds": 18}, {"no": 2 * i, "est_seconds": 18}]}
        for i in (1, 2, 3)
    ]
    res = content_adequacy.assess("script", _script(acts, 120))
    assert res["ok"] is True, res["findings"]


def test_script_scene_below_duration_floor_is_flagged() -> None:
    """单场 6 秒 < 8 秒下限（`R22`）—— 切不出任何合规单元。"""
    acts = [{"act_no": 1, "scenes": [{"no": 1, "est_seconds": 6}]}]
    res = content_adequacy.assess("script", _script(acts, 6))
    assert "scene_below_duration_floor" in [f["code"] for f in res["findings"]]


def test_script_without_scenes_is_flagged() -> None:
    res = content_adequacy.assess("script", _script([], 0))
    codes = [f["code"] for f in res["findings"]]
    assert "script_no_scenes" in codes
    assert "script_total_missing_or_nonpositive" in codes


# ------------------------------------------------------------------ 分镜层
UPSTREAM_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 18}, {"no": 2, "est_seconds": 18}]},
        {"act_no": 2, "scenes": [{"no": 3, "est_seconds": 18}]},
    ],
    54,
)


def test_storyboard_duration_sum_mismatch_is_flagged() -> None:
    """r4 实测：Σ15,000 ≠ 声明 45,000。"""
    text = _storyboard(
        [{"shot_id": "S01-SH001", "scene_no": 1, "duration_ms": 5000},
         {"shot_id": "S01-SH002", "scene_no": 1, "duration_ms": 5000},
         {"shot_id": "S01-SH003", "scene_no": 1, "duration_ms": 5000}],
        45000,
        [{"unit_id": "U01", "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"]}],
    )
    res = content_adequacy.assess("storyboard", text, {"script_json": UPSTREAM_SCRIPT})
    codes = [f["code"] for f in res["findings"]]
    assert "storyboard_duration_sum_mismatch" in codes
    assert "scene_coverage_incomplete" in codes
    cov = next(f for f in res["findings"] if f["code"] == "scene_coverage_incomplete")
    assert cov["scenes_covered"] == [1] and cov["scenes_missing"] == [2, 3]


def test_storyboard_full_coverage_and_arithmetic_is_ok() -> None:
    text = _storyboard(
        [{"shot_id": f"S{i:02d}-SH001", "scene_no": i, "duration_ms": 9000} for i in (1, 2, 3)],
        27000,
        [{"unit_id": "U01", "shot_ids": ["S01-SH001", "S02-SH001"]},
         {"unit_id": "U02", "shot_ids": ["S03-SH001"]}],  # 1 镜单元 → 越界
    )
    res = content_adequacy.assess("storyboard", text, {"script_json": UPSTREAM_SCRIPT})
    codes = [f["code"] for f in res["findings"]]
    assert "scene_coverage_incomplete" not in codes
    assert "storyboard_duration_sum_mismatch" not in codes
    assert "unit_size_out_of_range" in codes


def test_storyboard_coverage_is_not_judged_without_usable_upstream() -> None:
    """⚠️ 上游不可用时**不出结论**（不假装「覆盖齐全」）——`checked` 仍为真但无覆盖判据。"""
    text = _storyboard(
        [{"shot_id": "S01-SH001", "scene_no": 1, "duration_ms": 9000}],
        9000,
        [{"unit_id": "U01", "shot_ids": ["S01-SH001", "S01-SH001"]}],
    )
    res = content_adequacy.assess("storyboard", text, {"script_json": '{"title": 截断'})
    assert res["checked"] is True
    assert "scenes_expected" not in res["metrics"]
    assert "scene_coverage_incomplete" not in [f["code"] for f in res["findings"]]


# ------------------------------------------------------------------ 边界
def test_unparsable_text_is_not_treated_as_passed() -> None:
    """解析不归本模块管，但**绝不**把「拿不到数」记成「合格」。"""
    res = content_adequacy.assess("script", '{"title": "被截断", "acts": [')
    assert res["checked"] is False and res["ok"] is None
    assert res["findings"][0]["code"] == "unparsable_for_adequacy"


def test_unregistered_stage_is_not_treated_as_passed() -> None:
    """`shot_prompt`（交付包）本批未登记内容判据 ⇒ `checked=false`。"""
    res = content_adequacy.assess("shot_prompt", '{"meta": {}}')
    assert res["checked"] is False and res["ok"] is None


@pytest.mark.parametrize("stage", ["script", "storyboard", "synopsis"])
@pytest.mark.parametrize("text", ["", "null", "[]", '"字符串"', "123", '{"acts": "不是数组"}'])
def test_probe_never_raises_on_hostile_input(stage: str, text: str) -> None:
    """探测模块**不得成为新的失败点**：任何畸形输入都只能返回结论，不得抛错。"""
    res = content_adequacy.assess(stage, text)
    assert set(res) >= {"checked", "ok", "stage", "findings", "metrics"}
    assert res["stage"] == stage
