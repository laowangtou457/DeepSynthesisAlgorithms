# -*- coding: utf-8 -*-
"""**覆盖分配器**（批次 2 一期）的穷举用例。

靶面（2026-11-23 真机 5 轮实证锁定）：光线覆盖 0%（同单元回填）＋台词语速超限
（只延时长）。三条纪律的验证面：
- **阈值同源锁**：改写器的阈值/上限是 `prompts.validate_output` 的**同一对象**
  （判据改阈值 ⇒ 改写器行为随之变，不存在第二份口径）；
- **最小干预**：光线只补「达标所需最少镜数」；全单元皆空不伪造；
  语速延展装不下时长区间就不动——不可修形态**原样留给门禁拒**（负向样本）；
- **改写不裁决**：本层不判达标；noop 不写键（不污染每次生成）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import get_settings
from app.inference.base import GenParams, GenResult, TextGenerator
from app.prompts.loader import PromptRepository
from app.repositories.session_repo import SessionRepository
from app.schemas.dialogue import Stage
from app.services import coverage_reconcile
from app.services.coverage_reconcile import (
    DIALOGUE_SPEED_MAX,
    DURATION_MAX_MS,
    reconcile_coverage_gaps,
)


# ---------------------------------------------------------------- 同源锁
def test_thresholds_are_same_source_references() -> None:
    """**同源锁**：改写器的常量来自**同一份判据文件**（路径身份判定）。

    这条锁防的是「有人日后在改写器里复制一份阈值字面量」——一旦复制，
    判据改阈值而改写器不跟，改写与判定就会打架（`ISSUE-094` 两把尺子的同族事故）。
    `prompts/` 非 import 包 ⇒ 以 `quality_gate` 同款文件路径加载机制取同源值。
    """
    from pathlib import Path

    assert Path(coverage_reconcile._VO.__file__).resolve() == (
        Path(__file__).resolve().parents[2] / "prompts" / "validate_output.py"
    )


# ---------------------------------------------------------------- ① 台词延时长
def test_dialogue_speed_violation_is_stretched_to_exact_minimum() -> None:
    """核心正向：105 字 / 5000ms（21 字/秒）⇒ 延到 `ceil(105/9)×1000 = 12000ms`。
    ⚠️ 取整到**整秒**（12000 而非数学最小 11667）是 **R12 硬约束**：
    `duration_ms` 必须 1000 整数倍——延到 11667 修好了 R15 却撞 R12。
    改后语速 105/12 = 8.75 ≤ 9 且 12000 % 1000 == 0，两判据同时成立。"""
    doc = {"shots": [{"shot_id": "S01-SH001", "dialogue": "字" * 105, "duration_ms": 5000}]}
    changed, trace = reconcile_coverage_gaps(doc)

    assert changed is True
    assert doc["shots"][0]["duration_ms"] == 12000
    assert trace["dialogue_stretched"] == [
        {"shot_id": "S01-SH001", "chars": 105, "ms_before": 5000, "ms_after": 12000}
    ]
    assert trace["lighting_backfilled"] == []
    # 改写后语速达标（改写不裁决，但算术上必须真的可过）＋ 不引入 R12 违例
    assert len("字" * 105) / (12000 / 1000.0) <= DIALOGUE_SPEED_MAX
    assert 12000 % 1000 == 0


def test_dialogue_at_boundary_is_untouched() -> None:
    """边界锁：语速**恰好等于**上限（判据是 `rate > 9` 严格大于）⇒ 不动。"""
    # 90 字 / 10000ms = 9.0 字/秒：不超限
    doc = {"shots": [{"shot_id": "S01-SH001", "dialogue": "字" * 90, "duration_ms": 10000}]}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None
    assert doc["shots"][0]["duration_ms"] == 10000


@pytest.mark.parametrize(
    "shot",
    [
        # 非字符串台词（数组形态，`ISSUE-049` 同款）⇒ 按「无台词」跳过
        {"shot_id": "S01-SH001", "dialogue": [{"type": "旁白", "text": "字" * 105}],
         "duration_ms": 5000},
        # 无 duration_ms
        {"shot_id": "S01-SH001", "dialogue": "字" * 105},
        # duration_ms 非法
        {"shot_id": "S01-SH001", "dialogue": "字" * 105, "duration_ms": 0},
        {"shot_id": "S01-SH001", "dialogue": "字" * 105, "duration_ms": True},
    ],
)
def test_dialogue_unusable_inputs_are_untouched(shot: dict) -> None:
    """负向锁：与 R15 同一输入域，域外一律不碰。"""
    doc = {"shots": [shot]}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None


def test_dialogue_beyond_duration_cap_is_untouched() -> None:
    """**负向样本**：达标所需时长超出 `DURATION_MAX_MS` ⇒ 无从机械修复，不硬改。"""
    chars = DIALOGUE_SPEED_MAX * (DURATION_MAX_MS // 1000) + 100  # 装不下
    doc = {"shots": [{"shot_id": "S01-SH001", "dialogue": "字" * chars, "duration_ms": 5000}]}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None
    assert doc["shots"][0]["duration_ms"] == 5000


# ---------------------------------------------------------------- ② 光线回填
def _unit(unit_id: str, lightings: list) -> list[dict]:
    """按光线列表构造一个单元的镜（`duration_ms` 合法整秒，与本两族无关）。"""
    return [
        {"shot_id": f"S01-SH{str(i + 1).zfill(3)}", "unit_id": unit_id,
         "lighting": lv, "duration_ms": 4000}
        for i, lv in enumerate(lightings)
    ]


def test_lighting_gap_backfilled_from_same_unit() -> None:
    """核心正向（真机 r2/r5 现场形态）：单元 3 镜仅 1 镜命中（33% < 40%）
    ⇒ 缺口 `ceil(0.4×3)−1 = 1` ⇒ 回填**最少 1 台**，取同单元首个非空值；
    改后覆盖 2/3 ≥ 40%。⚠️ 回填后余下空镜**不动**（最小干预：只补 shortfall 台）。"""
    doc = {"shots": _unit("U04", [None, None, "practical_light"])}
    changed, trace = reconcile_coverage_gaps(doc)

    assert changed is True
    assert doc["shots"][0]["lighting"] == "practical_light"  # 空镜被回填
    assert doc["shots"][1]["lighting"] is None               # 只补缺口数，不多补
    assert doc["shots"][2]["lighting"] == "practical_light"  # 原值不动
    assert trace["lighting_backfilled"] == [
        {"shot_id": "S01-SH001", "unit_id": "U04", "value": "practical_light"}
    ]


def test_lighting_already_meeting_threshold_is_untouched() -> None:
    """最小干预锁：单元 3 镜已 2 台命中（67% ≥ 40% 达标）⇒ 一台都不补。"""
    doc = {"shots": [
        {"shot_id": "S01-SH001", "unit_id": "U01", "lighting": "daylight", "duration_ms": 4000},
        {"shot_id": "S01-SH002", "unit_id": "U01", "lighting": "daylight", "duration_ms": 4000},
        {"shot_id": "S01-SH003", "unit_id": "U01", "lighting": None, "duration_ms": 4000},
    ]}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None
    assert doc["shots"][2]["lighting"] is None


def test_lighting_unit_all_empty_is_not_fabricated() -> None:
    """**负向样本（不伪造纪律）**：全单元皆空 ⇒ 无同源值可取，不捏造创作内容。"""
    doc = {"shots": _unit("U04", [None, None, None])}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None
    assert doc["shots"][0]["lighting"] is None


def test_lighting_whitespace_only_counts_as_empty() -> None:
    """与判据同一判定：空白字符串不算命中（`str.strip()` 口径）⇒ 可被回填。"""
    doc = {"shots": _unit("U04", ["   ", None, "practical_light"])}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    assert doc["shots"][0]["lighting"] == "practical_light"
    assert doc["shots"][1]["lighting"] is None  # 只补 shortfall=1 台


def test_units_are_processed_independently() -> None:
    """分组锁：按 `unit_id` 独立分组（与 gate 的单元级报错同域）——
    A 单元达标不豁免 B 单元的缺口。"""
    doc = {"shots": [
        {"shot_id": "S01-SH001", "unit_id": "U01", "lighting": "daylight", "duration_ms": 4000},
        {"shot_id": "S01-SH002", "unit_id": "U01", "lighting": "daylight", "duration_ms": 4000},
        {"shot_id": "S02-SH001", "unit_id": "U04", "lighting": None, "duration_ms": 4000},
        {"shot_id": "S02-SH002", "unit_id": "U04", "lighting": None, "duration_ms": 4000},
        {"shot_id": "S02-SH003", "unit_id": "U04", "lighting": "practical_light", "duration_ms": 4000},
    ]}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    assert doc["shots"][2]["lighting"] == "practical_light"
    assert doc["shots"][3]["lighting"] is None
    assert [b["shot_id"] for b in trace["lighting_backfilled"]] == ["S02-SH001"]

# ---------------------------------------------------------------- ④ 运镜轮换（批次 2 二期）
def _gate_check_camera(rows: list[dict]) -> list[str]:
    """同源复算自证：调判据文件同款 `_gate_check`，只取运镜相关未达标项。"""
    bad = coverage_reconcile._VO._gate_check(rows)
    return [b for b in bad if any(k in b for k in ("运镜", "静止镜", "单一运镜", "类型数"))]


def _shots_moves(spec: list[tuple[str, str, str | None]]) -> list[dict]:
    """(shot_id, unit_id, move) → shots；move 传 None 表示缺 camera.move（整镜缺失）。"""
    out = []
    for sid, uid, mv in spec:
        shot = {"shot_id": sid, "unit_id": uid, "duration_ms": 4000,
                "lighting": "daylight"}
        if mv is not None:
            shot["camera"] = {"move": mv}
        out.append(shot)
    return out


def test_camera_rotation_below_denominator_is_untouched() -> None:
    """**三态化同源口径**：R19/R11 在镜数 < `N_MIN_DENOMINATOR` 时门禁 not_tested
    ⇒ 改写器同口径不动（1~5 镜短片上「类型数 ≥ 2」甚至不可满足，动了也白动）。"""
    n_min = coverage_reconcile._VO.N_MIN_DENOMINATOR
    assert n_min == 6
    spec = [("S01-SH001", "U01", "static"), ("S01-SH002", "U01", "static")]
    doc = {"shots": _shots_moves(spec)}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None


def test_camera_rotation_r3_scene_changes_exactly_one() -> None:
    """核心正向（真机 r3 现场，`DEV-20261124-003`）：8 镜整片含一个 2 镜全 static
    单元 ⇒ R11 重复＋该单元类型结构问题由**恰 1 镜**改写修复（最小干预——首版
    无条件把 2 镜都拖入曾被快测抓出）；改后同源 `_gate_check` 复算零运镜未达标。"""
    doc = {"shots": _shots_moves([
        ("S01-SH001", "U01", "static"), ("S01-SH002", "U01", "static"),
        ("S02-SH001", "U02", "push_in"), ("S02-SH002", "U02", "pull_out"),
        ("S03-SH001", "U03", "zoom_in"), ("S03-SH002", "U03", "truck_left"),
        ("S04-SH001", "U04", "arc"), ("S04-SH002", "U04", "tracking"),
    ])}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    rot = trace["camera_rotated"]
    assert [r["shot_id"] for r in rot] == ["S01-SH002"]
    assert rot[0]["before"] == "static" and rot[0]["after"] == "push_in"
    u01 = [s["camera"]["move"] for s in doc["shots"] if s["unit_id"] == "U01"]
    assert len(set(u01)) == 2  # R11 修复
    assert _gate_check_camera(doc["shots"]) == []


def test_camera_rotation_static_over_rotates_tail_only() -> None:
    """静止镜超限（尾部）：12 镜 static×6（各一单元、无 R11 冲突）＋6 异值 ⇒
    超出 `_allow(0.4,12)=5` 恰 **1 台**（尾部 SH06）；改后 `_gate_check` 零运镜未达标。"""
    spec = ([("S-SH%02d" % i, "U%02d" % i, "static") for i in range(1, 7)]
            + [("S-SH%02d" % i, "U%02d" % i, mv) for i, mv in zip(
                range(7, 13), ["pan_left", "pan_right", "tilt_up", "tilt_down", "arc", "tracking"])])
    doc = {"shots": _shots_moves(spec)}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    rot = trace["camera_rotated"]
    assert [r["shot_id"] for r in rot] == ["S-SH06"]
    after = doc["shots"][5]["camera"]["move"]
    assert after not in ("static", "pov")  # 不引入 NO_PARAM 值（R17 参数面）
    assert _gate_check_camera(doc["shots"]) == []


def test_camera_rotation_single_move_over_via_simulation() -> None:
    """单一运镜超限走**模拟改后**路径：static 与 push_in 两类各 6/12 双超限
    （每单元 [push_in, static] 交替、无 R11 冲突）⇒ 恰补 2 台；改后 `_gate_check`
    零运镜未达标。"""
    spec = [("S-SH%02d" % i, "U%02d" % i, "push_in" if i % 2 else "static")
            for i in range(1, 13)]
    doc = {"shots": _shots_moves(spec)}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    rot = trace["camera_rotated"]
    assert [r["shot_id"] for r in rot] == ["S-SH11", "S-SH12"], [
        (r["shot_id"], r["before"], r["after"]) for r in rot]
    assert _gate_check_camera(doc["shots"]) == []


def test_camera_rotation_missing_move_is_filled() -> None:
    """move 缺失（运镜覆盖门槛 1.00）⇒ 补值；camera 对象缺失时就地创建；
    同单元已用 push_in ⇒ 跳到下一候选 pull_out（R11）。"""
    doc = {"shots": _shots_moves([
        ("S01-SH001", "U01", "push_in"), ("S01-SH002", "U01", None),
        ("S02-SH001", "U02", "pull_out"), ("S02-SH002", "U02", "zoom_in"),
        ("S03-SH001", "U03", "truck_left"), ("S03-SH002", "U03", "arc"),
    ])}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    rot = trace["camera_rotated"]
    assert [r["shot_id"] for r in rot] == ["S01-SH002"]
    assert rot[0]["before"] is None
    assert doc["shots"][1]["camera"]["move"] == "pull_out"
    assert _gate_check_camera(doc["shots"]) == []


def test_camera_rotation_compliant_is_noop() -> None:
    """已合规 ⇒ noop（不污染每次生成）。"""
    doc = {"shots": _shots_moves([
        ("S01-SH001", "U01", "push_in"), ("S01-SH002", "U01", "pull_out"),
        ("S02-SH001", "U02", "zoom_in"), ("S02-SH002", "U02", "truck_left"),
        ("S03-SH001", "U03", "arc"), ("S03-SH002", "U03", "tracking"),
    ])}
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is False and trace is None


def test_camera_rotation_is_idempotent() -> None:
    """幂等锁：轮换后再跑 ⇒ noop（改写器输出自身达标）。"""
    doc = {"shots": _shots_moves([
        ("S01-SH001", "U01", "static"), ("S01-SH002", "U01", "static"),
        ("S02-SH001", "U02", "push_in"), ("S02-SH002", "U02", "pull_out"),
        ("S03-SH001", "U03", "zoom_in"), ("S03-SH002", "U03", "truck_left"),
        ("S04-SH001", "U04", "arc"), ("S04-SH002", "U04", "tracking"),
    ])}
    changed, _ = reconcile_coverage_gaps(doc)
    assert changed is True
    changed2, trace2 = reconcile_coverage_gaps(doc)
    assert changed2 is False and trace2 is None

# ---------------------------------------------------------------- ⑤ 结构与幂等
def test_no_shots_or_unexpected_doc_is_noop() -> None:
    for doc in [{}, {"shots": []}, {"shots": ["不是字典"]}, {"shots": None}]:
        changed, trace = reconcile_coverage_gaps(doc)  # type: ignore[arg-type]
        assert changed is False and trace is None


def test_reconcile_is_idempotent() -> None:
    """幂等锁：改写后的文档再跑一遍 ⇒ noop（不二次改写、不重复留痕）。"""
    doc = {"shots": _unit("U04", [None, None, "practical_light"])}
    doc["shots"][0]["dialogue"] = "字" * 105
    doc["shots"][0]["duration_ms"] = 5000
    changed, trace = reconcile_coverage_gaps(doc)
    assert changed is True
    assert trace["dialogue_stretched"] and trace["lighting_backfilled"]
    changed2, trace2 = reconcile_coverage_gaps(doc)
    assert changed2 is False and trace2 is None


# ------------------------------------- ④ 端到端接线：改写落在生成链上且留痕
class _StubVerdict:
    """门禁结论替身（控制流断言用，同 `test_quality_gate_t086` 口径）。"""

    def __init__(self) -> None:
        self.ok = True
        self.retryable: list[str] = []
        self.non_retryable: list[str] = []
        self.shape = "storyboard"
        self.checked = True
        self.enforced = False
        self.reason = None
        self.stage = "storyboard"

    def as_record(self) -> dict:
        # 同 `test_quality_gate_t086` 的替身口径（dialogue_service 落 verdict 留痕时调用）。
        return {"stage": self.stage, "shape": self.shape, "checked": True, "ok": self.ok,
                "retryable": len(self.retryable), "non_retryable": len(self.non_retryable)}


class ScriptedBackend(TextGenerator):
    name = "scripted"
    version = "0.1.0"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls: list[dict] = []

    async def generate(  # type: ignore[no-untyped-def]
        self, prompt, params: GenParams, json_schema=None
    ) -> GenResult:
        index = len(self.calls)
        self.calls.append({"prompt": prompt, "schema": json_schema, "params": params})
        text = self.texts[index] if index < len(self.texts) else "{}"
        return GenResult(
            text=text, finish_reason="stop", prompt_tokens=10, completion_tokens=5
        )

    async def stream(self, prompt, params, json_schema=None):  # type: ignore[no-untyped-def]
        for piece in ():  # pragma: no cover
            yield piece


def test_wiring_reconcile_runs_in_generation_chain(monkeypatch) -> None:
    """端到端：分镜段产出带「语速超限＋光线缺口」的产物 ⇒ 改写在归一化链上
    真实发生（门禁前），留痕落 `artifact["coverage_reconcile"]`＋告警不静默。"""
    from app.services import dialogue_service as ds

    async def _stub_check(stage, text=None, upstream=None):  # type: ignore[no-untyped-def]
        return _StubVerdict()

    monkeypatch.setattr(ds.quality_gate, "check", _stub_check)
    monkeypatch.setattr(get_settings(), "storyboard_scene_orchestration", False)

    # 合格分镜底板（同 T-086 `_GOOD_STORYBOARD` 骨架）＋两类靶面缺陷：
    # SH001 台词 105 字/5000ms（超速）＋ U01 三镜仅一镜有光线（33% < 40%，缺口 1 台）
    doc = {
        "title": "雨夜", "genre": "剧情", "style_ref": "ST-01",
        "aspect_ratio_default": "16:9", "total_duration_ms": 12000,
        "units": [{"unit_id": "U01", "scene_no": 1,
                   "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"]}],
        "shots": [
            {"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1, "unit_id": "U01",
             "duration_ms": 5000, "dialogue": "字" * 105, "lighting": None},
            {"shot_id": "S01-SH002", "scene_no": 1, "shot_no": 2, "unit_id": "U01",
             "duration_ms": 4000, "lighting": None},
            {"shot_id": "S01-SH003", "scene_no": 1, "shot_no": 3, "unit_id": "U01",
             "duration_ms": 4000, "lighting": "practical_light"},
        ],
        "forbidden_items": [], "unspecified": [], "quality_gate": {},
    }
    backend = ScriptedBackend([json.dumps(doc, ensure_ascii=False)])
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    service = ds.DialogueService(repo, prompts, backend_resolver=lambda: backend)
    source = "一只流浪猫在雨夜被人救起"
    rec = repo.create(stage=Stage.DRAFT_STORYBOARD.value, source_input=source,
                      defaults={"source_input": source})
    rec.artifacts["script"] = {"text": json.dumps({
        "title": "雨夜", "logline": "一句话", "genre": "剧情",
        "style_bible": {"style_id": "ST-01"}, "characters": [], "props": [],
        "acts": [], "forbidden_items": [], "total_est_seconds": 0, "unspecified": [],
    }, ensure_ascii=False)}

    asyncio.run(service._maybe_generate(rec, Stage.DRAFT_STORYBOARD, dict(rec.defaults)))

    artifact = rec.artifacts["storyboard"]
    assert "coverage_reconcile" in artifact, "改写发生在链上 ⇒ 留痕必须落 artifact"
    cr = artifact["coverage_reconcile"]
    assert len(cr["dialogue_stretched"]) == 1 and len(cr["lighting_backfilled"]) == 1
    # 产物文本里时长已是延展值（R12 整秒口径 12000）、光线已回填
    out = json.loads(artifact["text"])
    assert out["shots"][0]["duration_ms"] == 12000
    assert out["shots"][0]["lighting"] == "practical_light"
    assert any(w.startswith("coverage_reconcile:") for w in artifact.get("merge_warnings", []))
    assert len(backend.calls) == 1, "一次采样即入库（改写不消耗重采额度）"
