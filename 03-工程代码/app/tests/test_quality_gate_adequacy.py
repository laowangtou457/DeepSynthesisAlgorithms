"""`PRO-010` 批次 1（`content_adequacy` 接入门禁判定）测试。

覆盖三条核心行为：
1. **留痕独立成组**（批次 1-C）：adequacy 结论**不合并**进 `engine_errors`，两组字段并存。
2. **去重规则**（批次 1-B）：同一失败若等效 `R` 判据已报出 ⇒ adequacy finding 只作佐证，
   **不进 `retryable`**；无等效判据的（`scene_coverage_incomplete`）**必须进**。
3. **不改变 `ok`**：adequacy 失败**不产生阻断**（`ok` 仍只由判据族失败决定）。

⚠️ 本文件的构造产物**刻意精简**（只保留被测判据关心的键），
目的是**隔离被测行为**——若补全全部必备字段，`R5` 等噪声判据会掩盖目标信号。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services import quality_gate


# ------------------------------------------------------------------ 工具
def _script(total: int, scene_seconds: int, acts: int = 1, scenes: int = 1) -> dict:
    """构造 `script_v1` 产物。`acts`／`scenes` 用于触发 `R6`（幕数）。"""
    return {
        "acts": [
            {
                "act_no": a + 1,
                "scenes": [
                    {"no": s + 1, "est_seconds": scene_seconds, "purpose": "交代", "dialogue": []}
                    for s in range(scenes)
                ],
            }
            for a in range(acts)
        ],
        "total_est_seconds": total,
    }


def _storyboard(shot_ms: list[int], total_ms: int, scene_nos: list[int] | None = None) -> dict:
    """构造 `storyboard_v1` 产物。"""
    nos = scene_nos if scene_nos is not None else [1] * len(shot_ms)
    return {
        "units": [{"unit_id": "U01", "shot_ids": [f"S{i+1:02d}" for i in range(len(shot_ms))]}],
        "shots": [
            {
                "shot_id": f"S{i+1:02d}",
                "shot_no": i + 1,
                "unit_id": "U01",
                "scene_no": nos[i],
                "duration_ms": shot_ms[i],
                "camera": {"move": "推", "shot_size": "中景"},
                "dialogue": [],
            }
            for i in range(len(shot_ms))
        ],
        "total_duration_ms": total_ms,
    }


async def _run(stage: str, text: str, upstream: dict[str, str] | None = None):
    return await quality_gate.check(stage, text=text, upstream=upstream)


# ------------------------------------------------------------------ 1-C 留痕独立成组
def test_adequacy_findings_are_kept_separate_from_engine_errors() -> None:
    """adequacy 结论**不合并**进 `engine_errors`（结构 vs 内容两组字段并存）。"""
    doc = _script(total=125, scene_seconds=15)
    v = asyncio.run(_run("script", json.dumps(doc, ensure_ascii=False)))

    # adequacy 侧：探测到了「Σ场秒 ≠ 声明总时长」
    assert v.adequacy_checked is True
    assert v.adequacy_ok is False
    codes = [f.get("code") for f in v.adequacy_findings]
    assert "script_total_mismatch" in codes

    # ⚠️ 两组字段**分开**：`engine_errors` 里不应出现 adequacy 的 code
    assert not any("script_total_mismatch" in e for e in v.engine_errors)
    # 留痕记录里也**分组**呈现
    rec = v.as_record()
    assert "adequacy_findings" in rec and "adequacy_finding_codes" in rec
    assert rec["adequacy_finding_codes"] != rec["engine_error_codes"]


def test_adequacy_checked_false_for_unregistered_stage() -> None:
    """未登记内容判据的阶段 ⇒ `adequacy_checked=False`（**不假装通过**）。"""
    doc = {"meta": {}, "shots": []}
    v = asyncio.run(_run("pack", json.dumps(doc, ensure_ascii=False)))
    # `pack` 不在 `_ASSESSORS` ⇒ 该段未登记内容判据
    assert v.adequacy_checked is False
    assert v.adequacy_ok is None


# ------------------------------------------------------------------ 1-B 去重规则
def test_duplicate_finding_does_not_enter_retryable() -> None:
    """⭐ **去重规则**：等效 `R` 判据（`R4`）已报出 ⇒ adequacy finding **不进 `retryable`**。

    场景：剧本层 `total_est_seconds` 与 Σ场秒不符。
    - `R4 EST_SECONDS_SUM`（判据族）会报出；
    - `script_total_mismatch`（adequacy）会报出**同一件事**。
    ⇒ 二者**只能计一次**，否则重试成本翻倍。
    """
    doc = _script(total=125, scene_seconds=15)
    v = asyncio.run(_run("script", json.dumps(doc, ensure_ascii=False)))

    # 判据族确实报了 R4
    assert any("R4" in e for e in v.engine_errors), "前提失效：R4 未报出"

    # adequacy 侧也探测到了
    f = next(f for f in v.adequacy_findings if f.get("code") == "script_total_mismatch")
    # ⚠️ 标记为「等效判据已报出」
    assert f.get("source") == "engine_dup"
    assert f.get("equiv_rule") == "R4"

    # ⭐ **不进** `retryable`（否则同一失败计两次）
    assert not any("script_total_mismatch" in r for r in v.retryable)
    # 且 `retryable` 里那条 `R4` 仍在（判据族那条没被吞掉）
    assert any("R4" in r for r in v.retryable)


def test_scene_coverage_incomplete_enters_retryable() -> None:
    """⭐ `scene_coverage_incomplete` 的重试触发能力（`PRO-013` 后由 `R41` 承接）。

    `PRO-013`（2026-11-05）落地 `R41`（场次覆盖）前，`content_adequacy` 的场覆盖度是
    相对判据族的**唯一净增能力**（`R10`／`R14`／`R19` 全只审段内）⇒ 必须亲自进
    `retryable`。`R41` 落地后等效判据出现 ⇒ 走 `engine_dup` 去重（同一失败只计一次），
    **重试触发不丢**——由 `R41` 的引擎失败驱动（`R41` 非 `_NON_RETRYABLE_*` 标记，
    自身 retryable）。
    """
    script = _script(total=30, scene_seconds=30, acts=3, scenes=3)
    # 分镜只覆盖第 1 场（3 镜都在场 1）⇒ 场覆盖度不完整
    sb = _storyboard(shot_ms=[10000, 10000, 10000], total_ms=30000, scene_nos=[1, 1, 1])
    v = asyncio.run(_run(
        "storyboard",
        json.dumps(sb, ensure_ascii=False),
        upstream={"script": json.dumps(script, ensure_ascii=False)},
    ))

    codes = [f.get("code") for f in v.adequacy_findings]
    assert "scene_coverage_incomplete" in codes, f"未探测到场覆盖度不足：{codes}"

    f = next(f for f in v.adequacy_findings if f.get("code") == "scene_coverage_incomplete")
    # ⭐ `R41` 已落地 ⇒ 等效判据在（engine 侧报出 R41）⇒ 去重只作佐证
    assert f.get("source") == "engine_dup"
    assert f.get("equiv_rule") == "R41"
    assert not any("scene_coverage_incomplete" in r for r in v.retryable)
    # ⭐ 重试触发**不丢**：由 `R41` 的引擎失败驱动（retryable、非 non_retryable 标记族）
    assert any("R41" in r for r in v.retryable), f"R41 未驱动重试：{v.retryable}"


def test_storyboard_duration_mismatch_is_deduped_against_r14() -> None:
    """分镜层 `Σ镜时长 ≠ total` ⇒ `R14` 与 adequacy 报**同一件事** ⇒ 只计一次。"""
    sb = _storyboard(shot_ms=[15000, 15000, 15000], total_ms=30000)
    v = asyncio.run(_run("storyboard", json.dumps(sb, ensure_ascii=False)))

    assert any("R14" in e for e in v.engine_errors), "前提失效：R14 未报出"
    f = next(
        (f for f in v.adequacy_findings if f.get("code") == "storyboard_duration_sum_mismatch"),
        None,
    )
    assert f is not None, "前提失效：adequacy 未探测到时长不符"
    assert f.get("source") == "engine_dup"
    assert f.get("equiv_rule") == "R14"
    assert not any("storyboard_duration_sum_mismatch" in r for r in v.retryable)


# ------------------------------------------------------------------ 口径边界：不改变 ok
def test_adequacy_failure_alone_does_not_change_ok() -> None:
    """⚠️ **本批次不产生阻断**：adequacy 失败**不改变 `ok`**。

    项目方裁决「先跑只判不拦观测」⇒ adequacy 的失败只进 `retryable`（触发重试），
    **不**把 `ok` 翻成 `False` ⇒ `enforce=true` 时也不会因此拦下产物。
    """
    # 构造一个「判据族全过、但 adequacy 有发现」的产物：场覆盖度不足
    script = _script(total=30, scene_seconds=30, acts=3, scenes=3)
    sb = _storyboard(shot_ms=[10000, 10000, 10000], total_ms=30000, scene_nos=[1, 1, 1])
    v = asyncio.run(_run(
        "storyboard",
        json.dumps(sb, ensure_ascii=False),
        upstream={"script": json.dumps(script, ensure_ascii=False)},
    ))
    # adequacy 确实有发现
    assert v.adequacy_findings
    # ⭐ 但 `ok` **不因 adequacy 而变 False**（判据族失败才有）
    if not v.engine_errors and not v.pack_blocks:
        assert v.ok is not False


def test_upstream_alias_mapping() -> None:
    """门禁的**形态名** upstream（`script`）⇒ adequacy 的**变量名**（`script_json`）。

    ⚠️ 若映射错了，场覆盖度判据会因取不到上游而**静默不出结论**
    （`content_adequacy._expected_scenes` 取不到就返回 `None`）
    ⇒ 那样就复现了「探测不到 ⇒ 缺陷漏过」的原始形态。
    """
    script = _script(total=30, scene_seconds=30, acts=3, scenes=3)
    sb = _storyboard(shot_ms=[10000, 10000, 10000], total_ms=30000, scene_nos=[1, 1, 1])
    v = asyncio.run(_run(
        "storyboard",
        json.dumps(sb, ensure_ascii=False),
        upstream={"script": json.dumps(script, ensure_ascii=False)},
    ))
    codes = [f.get("code") for f in v.adequacy_findings]
    assert "scene_coverage_incomplete" in codes, f"上游映射失效，未探测到场覆盖度：{codes}"


# ------------------------------------------------------------------ 只调不抄
def test_module_does_not_duplicate_adequacy_rules() -> None:
    """⚠️ **不抄第二份口径**：`quality_gate` 内**不得**出现 adequacy 的判据常量副本。

    抄一份＝两处口径，本工程已多次因「两处口径打架」返工（最近一例见 `ISSUE-047`）。
    """
    src = (Path(__file__).resolve().parents[1] / "services" / "quality_gate.py").read_text(
        encoding="utf-8"
    )
    # 只允许在**映射表**里出现 finding code（那是去重用的映射，不是判据副本）
    assert "SCENE_DURATION_FLOOR_SECONDS" not in src, "抄了 `content_adequacy` 的判据常量"
    assert "UNIT_SIZE_ALLOWED" not in src, "抄了 `content_adequacy` 的判据常量"
    assert "SCRIPT_TOTAL_TOLERANCE" not in src, "抄了 `content_adequacy` 的判据常量"


def test_total_zero_is_deduped_against_r14() -> None:
    """⭐ **真实链路观测补入的边界**（2026-11-03 批次 1 真跑）。

    `total_duration_ms=0` 这个形态下，`R14`（判据族）与
    `storyboard_total_missing_or_nonpositive`（adequacy）**报的是同一件事**：
    - `R14`：`total is None` → 「缺 total_duration_ms」；`total != s` → 「Σ≠total」
      ⇒ `total=0` 走后者分支，**已被覆盖**；
    - adequacy：`total` 非正 → `storyboard_total_missing_or_nonpositive`。

    ⚠️ **离线读判据源码时看不出来**（像是「缺失」与「不等」两件事），
    是**真跑**才暴露的 ⇒ 若不补进去重表，同一失败会被**计两次**
    （`R14` 一次 ＋ adequacy 一次）⇒ 重试成本翻倍。
    """
    sb = _storyboard(shot_ms=[15000, 15000, 15000], total_ms=0)
    v = asyncio.run(_run("storyboard", json.dumps(sb, ensure_ascii=False)))

    # 判据族确实报了 R14
    assert any("R14" in e for e in v.engine_errors), "前提失效：R14 未报出"

    f = next(
        (f for f in v.adequacy_findings if f.get("code") == "storyboard_total_missing_or_nonpositive"),
        None,
    )
    assert f is not None, "前提失效：adequacy 未探测到 total 非正"
    # ⚠️ 须被去重（等效判据 R14 已报出）
    assert f.get("source") == "engine_dup"
    assert f.get("equiv_rule") == "R14"
    assert not any("storyboard_total_missing_or_nonpositive" in r for r in v.retryable)
