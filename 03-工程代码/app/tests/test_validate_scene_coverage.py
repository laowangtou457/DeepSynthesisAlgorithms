# -*- coding: utf-8 -*-
"""`PRO-013` 裁决落地批的判据测试（`R41`/`R42`/三态化；2026-11-05）。

⚠️ 覆盖面：
1. `R41` 场次覆盖：缺场报错（含 scenes_missing）／无上游 not_tested／全覆盖通过；
2. `R42` 每场镜数下限：单镜场报错／全片下限（⌈Σest÷15s⌉）／无上游时只判每场；
3. 三态化（§4.1）：镜数 < `N_MIN_DENOMINATOR` ⇒ `R10`/`R11`/`R19` 未测不判通过；
4. 互锁：`quality_gate._engine_errors` 重置的 `RESULT` 含 `not_tested` 键（三态化
   与门禁的两侧同步锚——否则 `not_tested()` 会 KeyError 或静默丢）。
"""

from __future__ import annotations

import asyncio
import json

from app.services import quality_gate


def _module():
    m = quality_gate._engine_validator()
    assert m is not None, "判据模块加载失败"
    return m


def _reset(m) -> None:
    m.QUIET = True
    m.RESULT = {"checks": 0, "errors": [], "warnings": [], "not_tested": []}
    m.UPSTREAM = {"doc": None, "src": None, "sb_doc": None, "sb_src": None}


def _script_doc(total: int, scenes: list[int]) -> dict:
    return {
        "acts": [{"act_no": 1, "scenes": [
            {"no": no, "est_seconds": 10, "purpose": "交代", "dialogue": []}
            for no in scenes
        ]}],
        "total_est_seconds": total,
    }


def _sb_doc(shot_ms: list[int], scene_nos: list[int], total_ms: int | None = None) -> dict:
    return {
        "units": [{"unit_id": "U01", "shot_ids": [f"S{i+1:02d}" for i in range(len(shot_ms))]}],
        "shots": [
            {
                "shot_id": f"S{i+1:02d}", "shot_no": i + 1, "unit_id": "U01",
                "scene_no": scene_nos[i], "duration_ms": shot_ms[i],
                "camera": {"move": "pan_right"}, "dialogue": [],
            }
            for i in range(len(shot_ms))
        ],
        "total_duration_ms": total_ms if total_ms is not None else sum(shot_ms),
    }


def _run(m, doc: dict, script: dict | None = None) -> dict:
    _reset(m)
    if script is not None:
        m.UPSTREAM["doc"] = script
    m.validate_doc(doc, "storyboard", fname="t.json")
    return m.RESULT


# ---------------------------------------------------------------- R41 场次覆盖

def test_r41_missing_scenes_reported() -> None:
    """3 场剧本只拍场 1 ⇒ R41 报 scenes_missing=[2,3]（PRO-013 89% 真形态）。"""
    m = _module()
    r = _run(m, _sb_doc([5000, 5000, 5000], [1, 1, 1]), _script_doc(30, [1, 2, 3]))
    hits = [e for e in r["errors"] if "R41 SCENE_COVERAGE" in e]
    assert len(hits) == 1 and "scenes_missing=[2, 3]" in hits[0]


def test_r41_full_coverage_passes() -> None:
    m = _module()
    r = _run(m, _sb_doc([5000, 5000, 5000, 5000, 5000, 5000], [1, 1, 2, 2, 3, 3]),
             _script_doc(30, [1, 2, 3]))
    assert not any("R41" in e for e in r["errors"])      # 全覆盖 ⇒ R41 不报失败
    assert not any("R41" in x for x in r["not_tested"])  # 有上游 ⇒ 也不落未测


def test_r41_no_upstream_is_not_tested() -> None:
    """无上游 ⇒ not_tested（三态化：缺上游不得判通过）。"""
    m = _module()
    r = _run(m, _sb_doc([5000, 5000, 5000], [1, 1, 1]))
    assert any("R41 SCENE_COVERAGE" in x and "未测" in x for x in r["not_tested"])
    assert not any("R41" in e for e in r["errors"])


# ---------------------------------------------------------------- R42 每场镜数下限

def test_r42_single_shot_scene_reported() -> None:
    """场 2 只有 1 镜 ⇒ R42 报「须 ≥ 2」（＝最小合规单元，与 R22 同源）。"""
    m = _module()
    r = _run(m, _sb_doc([5000] * 6, [1, 1, 1, 1, 1, 2]), _script_doc(30, [1, 2, 3]))
    hits = [e for e in r["errors"] if "R42 SCENE_SHOT_FLOOR" in e]
    assert len(hits) == 1 and "场 2 仅 1 镜" in hits[0]


def test_r42_whole_film_floor_from_upstream() -> None:
    """上游 total=90s ⇒ 全片下限 ⌈90÷15⌉=6；4 镜 ⇒ 报下限不足。"""
    m = _module()
    r = _run(m, _sb_doc([5000] * 4, [1, 1, 2, 2]), _script_doc(90, [1, 2]))
    hits = [e for e in r["errors"] if "R42" in e]
    assert any("全片 4 镜 < ⌈Σ90s ÷ 15s⌉=6" in e for e in hits)


def test_r42_per_scene_floor_without_upstream() -> None:
    """无上游 ⇒ 只判每场 ≥2（自足），不判 not_tested。"""
    m = _module()
    r = _run(m, _sb_doc([5000, 5000, 5000, 5000], [1, 1, 2, 2]))
    assert not any("R42" in e for e in r["errors"])
    assert not any("R42" in x for x in r["not_tested"])


# ---------------------------------------------------------------- R43 单场镜数上限

def _script_doc_secs(scene_secs: dict[int, int], total: int) -> dict:
    """按场给**不同** `est_seconds` 的剧本（`R43` 要逐场算上限）。"""
    return {
        "acts": [{"act_no": 1, "scenes": [
            {"no": no, "est_seconds": secs, "purpose": "交代", "dialogue": []}
            for no, secs in scene_secs.items()
        ]}],
        "total_est_seconds": total,
    }


def test_r43_scene_over_cap_reported() -> None:
    """场 1 只有 16s（上限 4 镜）却分了 9 镜 ⇒ R43 报 2.25 倍（T-100 b 期实测形态）。"""
    m = _module()
    r = _run(m, _sb_doc([2000] * 9, [1] * 9), _script_doc_secs({1: 16}, 16))
    hits = [e for e in r["errors"] if "R43 SCENE_SHOT_CAP" in e]
    assert len(hits) == 1
    assert "场 1 分到 9 镜 > ⌊16s ÷ 4s⌋=4" in hits[0]


def test_r43_scene_at_cap_passes() -> None:
    m = _module()
    r = _run(m, _sb_doc([4000] * 4, [1] * 4), _script_doc_secs({1: 16}, 16))
    assert not any("R43" in e for e in r["errors"])
    assert not any("R43" in x for x in r["not_tested"])


def test_r43_without_upstream_is_not_tested() -> None:
    """无上游 ⇒ not_tested（**不拿产物自己的 duration_ms 反推**——那等于让产物自证）。"""
    m = _module()
    r = _run(m, _sb_doc([2000] * 9, [1] * 9))
    assert any("R43 SCENE_SHOT_CAP" in x and "未测" in x for x in r["not_tested"])
    assert not any("R43" in e for e in r["errors"])


def test_r43_unknown_scene_not_judged() -> None:
    """场号在上游查无此场 ⇒ 本条不越界（交 `R41`/`R10`），不误报。"""
    m = _module()
    r = _run(m, _sb_doc([2000] * 9, [9] * 9), _script_doc_secs({1: 16}, 16))
    assert not any("R43" in e and "场 9" in e for e in r["errors"])


# ---------------------------------------------------------------- 三态化（§4.1）

def test_tri_state_small_sample_not_tested() -> None:
    """3 镜产物 ⇒ R10/R11/R19 未测（68% 退化形态此前三项全绿——空真堵口）。"""
    m = _module()
    r = _run(m, _sb_doc([5000, 5000, 5000], [1, 1, 1]), _script_doc(30, [1, 2, 3]))
    nt = " ".join(r["not_tested"])
    for rule in ("R10 UNIT_SIZE", "R11 UNIT_MOVE_UNIQUE", "R19 GATE"):
        assert rule in nt, f"{rule} 未落 not_tested：{r['not_tested']}"
    # 未测 ≠ 失败：这三项不得再进 errors（空真「全绿」被取消）
    for rule in ("R10 UNIT_SIZE", "R11 UNIT_MOVE_UNIQUE", "R19 GATE"):
        assert not any(rule in e and "未测" not in e for e in r["errors"])


def test_tri_state_above_threshold_still_judged() -> None:
    """8 镜（≥ N_MIN=6）⇒ R10/R11/R19 照常判定（不误伤正常规模）。"""
    m = _module()
    r = _run(m, _sb_doc([5000] * 8, [1, 1, 2, 2, 3, 3, 4, 4]), _script_doc(40, [1, 2, 3, 4]))
    nt = " ".join(r["not_tested"])
    assert "R10 UNIT_SIZE" not in nt and "R11 UNIT_MOVE_UNIQUE" not in nt and "R19 GATE" not in nt


# ---------------------------------------------------------------- 门禁互锁

def test_gate_engine_result_reset_includes_not_tested() -> None:
    """互锁：`_engine_errors` 重置的 RESULT 带 `not_tested` 键并随返回值带出。"""
    m = _module()
    doc = _sb_doc([5000, 5000, 5000], [1, 1, 1])
    script_text = json.dumps(_script_doc(30, [1, 2, 3]), ensure_ascii=False)
    out = quality_gate._engine_errors(m, doc, "storyboard", {"script": script_text})
    assert "not_tested" in out and isinstance(out["not_tested"], list)
    assert any("R10" in x for x in out["not_tested"])
    # R41 失败仍进 errors（重试驱动不丢）
    assert any("R41 SCENE_COVERAGE" in e for e in out["errors"])


def test_gate_verdict_r41_drives_retry() -> None:
    """端到端：场覆盖缺失 ⇒ R41 进 retryable（`PRO-013` 后重试触发由 R41 承接）。"""
    script = json.dumps(_script_doc(30, [1, 2, 3]), ensure_ascii=False)
    sb = json.dumps(_sb_doc([10000, 10000, 10000], [1, 1, 1], total_ms=30000), ensure_ascii=False)
    v = asyncio.run(quality_gate.check("storyboard", text=sb, upstream={"script": script}))
    assert any("R41" in r for r in v.retryable), f"R41 未驱动重试：{v.retryable}"
