"""产物形态闸的负向验证（`ISSUE-042` 根治）。

⚠️ **负向验证纪律**（`CFG-007_SCHEMA.md` 文末既有条款）：只跑通过样本**证明不了**闸门有效
——必须构造越界样本验证**能触发**。本文件的每一个用例都对应一次真跑暴露的失败形态：

| 用例 | 对应的实测事实 |
| --- | --- |
| 截断产物被拒 | 第 3 轮真跑分镜段：13,252 字符、`finish_reason=stop`、`JSONDecodeError(pos=EOF)` |
| 非法上游阻断 | 提示词段拿到该截断上游仍生成，模型自报 `units=7／shots=13`（承继守恒不可验证） |
| 状态机不推进 | 非法产物被当「已完成」入库、`advance` 照常 `_move` |
| 单段也要判 | 改造前 `final_text = texts[0]` **完全不解析**（是否被检查取决于 `segment` 取值） |
| 长度截断单独归因 | 「撞上限」与「结构中间自终止」是两种失败，修法不同 |
| 零贡献段被拒 | `merge_segments` 对「可解析但无贡献」的段**不产生告警** ⇒ 静默缺口 |
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.inference.base import GenParams, GenResult, TextGenerator
from app.prompts.loader import PromptRepository
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.schemas.dialogue import SessionCreateRequest, Stage
from app.services import artifact_contract
from app.services.dialogue_service import DialogueService


class ScriptedBackend(TextGenerator):
    """按调用次序返回预置文本（**不做任何合规加工**——闸门要看的正是原始回包）。"""

    name = "scripted"
    version = "0.1.0"

    def __init__(self, texts: list[str], finish_reasons: list[str] | None = None) -> None:
        self.texts = texts
        self.finish_reasons = finish_reasons or ["stop"] * len(texts)
        self.calls: list[dict] = []

    async def generate(  # type: ignore[no-untyped-def]
        self, prompt, params: GenParams, json_schema=None
    ) -> GenResult:
        index = len(self.calls)
        self.calls.append({"prompt": prompt, "schema": json_schema, "params": params})
        text = self.texts[index] if index < len(self.texts) else "{}"
        reason = self.finish_reasons[index] if index < len(self.finish_reasons) else "stop"
        return GenResult(
            text=text, finish_reason=reason, prompt_tokens=10, completion_tokens=5
        )

    async def stream(self, prompt, params, json_schema=None):  # type: ignore[no-untyped-def]
        for piece in ():  # pragma: no cover - 集成测试不用流式
            yield piece


# --------------------------------------------------------------------- 夹具
VALID_SYNOPSIS = {
    "title": "雨夜",
    "logline": "一句话",
    "protagonist": "小满",
    "supporting": "队长",
    "world": "废弃采矿站",
    "conflict": "采集还是离开",
    "scenes_outline": [],
    "ending": "带着影像撤离",
    "forbidden_items": [],
    "total_est_seconds": 0,
    "unspecified": [],
}
VALID_STORYBOARD = {
    "title": "雨夜",
    "genre": "剧情",
    "style_ref": "ST-01",
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 0,
    "units": [{"unit_id": "U01"}],
    "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}],
    "forbidden_items": [],
    "unspecified": [],
    "quality_gate": {},
}
VALID_SCRIPT = {
    "title": "雨夜",
    "logline": "一句话",
    "genre": "剧情",
    "style_bible": {"style_id": "ST-01"},
    "characters": [],
    "props": [],
    "acts": [],
    "forbidden_items": [],
    "total_est_seconds": 0,
    "unspecified": [],
}
VALID_PACK = {
    "schema_version": "2.1.0",
    "meta": {"pack_id": "AC-PK-1"},
    "style_bible": {"style_id": "ST-01"},
    "characters": [],
    "props": [],
    "units": [{"unit_id": "U01"}],
    "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}],
    "forbidden_items": [],
    "aigc_meta": {"ProduceID": "AC-PK-1"},
}


def _svc(backend: ScriptedBackend) -> tuple[DialogueService, SessionRepository]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    return DialogueService(repo, prompts, backend_resolver=lambda: backend), repo


def _record(repo: SessionRepository, stage: Stage = Stage.DRAFT_SYNOPSIS) -> SessionRecord:
    source = "一只流浪猫在雨夜被人救起"
    rec = repo.create(
        stage=stage.value, source_input=source, defaults={"source_input": source}
    )
    rec.artifacts["synopsis"] = {"text": json.dumps(VALID_SYNOPSIS, ensure_ascii=False)}
    rec.artifacts["storyboard"] = {"text": json.dumps(VALID_STORYBOARD, ensure_ascii=False)}
    rec.artifacts["script"] = {"text": json.dumps(VALID_SCRIPT, ensure_ascii=False)}
    return rec


def _gen(service: DialogueService, rec: SessionRecord, target: Stage) -> None:
    asyncio.run(service._maybe_generate(rec, target, dict(rec.defaults)))


# ------------------------------------------------------------------ 形态契约自身
@pytest.mark.parametrize(
    "text,reason",
    [
        ("", "artifact_empty"),
        ("   ", "artifact_empty"),
        ("这不是 JSON，只是一段说明文字", "artifact_not_json"),
        ('{"title": "被截断的产物", "units": [', "artifact_not_json"),
    ],
)
def test_check_shape_rejects_unparsable(text: str, reason: str) -> None:
    verdict = artifact_contract.check_shape("storyboard", text)
    assert not verdict.ok and verdict.reason == reason


def test_check_shape_detects_shape_mismatch() -> None:
    """声明是交付包、实际产出分镜脚本 ⇒ 张冠李戴必须被识破。"""
    verdict = artifact_contract.check_shape(
        "pack", json.dumps(VALID_STORYBOARD, ensure_ascii=False)
    )
    assert not verdict.ok
    assert verdict.reason == "artifact_shape_mismatch"
    assert verdict.detected == "storyboard"


def test_check_shape_reports_missing_keys_in_truth_order() -> None:
    doc = {k: v for k, v in VALID_STORYBOARD.items() if k not in ("genre", "quality_gate")}
    verdict = artifact_contract.check_shape("storyboard", json.dumps(doc, ensure_ascii=False))
    assert not verdict.ok
    assert verdict.reason == "artifact_missing_required_keys"
    assert verdict.missing == ("genre", "quality_gate"), "缺键须按真值表次序报出"


def test_check_shape_allows_extra_keys_beyond_contract() -> None:
    """⚠️ 真实 `synopsis` 产物顶层比 R5 **多 3 键** —— 额外键不得导致判死。"""
    doc = {"title": "t", "logline": "l", "protagonist": "p", "supporting": "s",
           "world": "w", "conflict": "c", "scenes_outline": [], "ending": "e",
           "forbidden_items": [], "total_est_seconds": 0, "unspecified": [],
           "covered_points": [], "genre": "科幻", "logline_parts": []}
    assert artifact_contract.check_shape("synopsis", json.dumps(doc, ensure_ascii=False)).ok


# ---------------------------------------------------------------- 生成后形态闸
@pytest.mark.parametrize(
    "stage,key",
    [
        (Stage.SYNOPSIS_REVISING, "synopsis"),
        (Stage.DRAFT_SCRIPT, "script"),
        (Stage.DRAFT_STORYBOARD, "storyboard"),
        (Stage.DRAFT_SHOT_PROMPT, "shot_prompt"),
    ],
)
def test_truncated_artifact_is_rejected_and_never_stored(
    stage: Stage, key: str
) -> None:
    """**核心用例**：截断产物必须被拒，且**产物槽一字未动**（不得入库、不得覆盖）。"""
    truncated = '{"title": "气闸门", "units": [{"unit_id": "U01"}'
    backend = ScriptedBackend([truncated])
    service, repo = _svc(backend)
    rec = _record(repo)
    before = rec.artifacts.get(key)

    with pytest.raises(AppError) as ei:
        _gen(service, rec, stage)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert ei.value.details["reason"] == "artifact_not_json", (
        "闸门原因码不得被 `parse_json_object` 的解析器报错覆盖"
    )
    assert rec.artifacts.get(key) == before, (
        f"非法产物**不得**入库/覆盖 `{key}`（这正是 ISSUE-042 的缺陷点）"
    )


def test_shape_gate_stops_state_machine_from_advancing() -> None:
    """`advance()` 层面：形态闸抛出后，状态机**停在原阶段**（不会「照常推进」）。"""
    backend = ScriptedBackend(['{"title": "缺了其余 10 个必需键"}'])
    service, repo = _svc(backend)
    created = service.create_session(SessionCreateRequest(source_input="一只流浪猫"))
    sid = created.session_id

    with pytest.raises(AppError):
        asyncio.run(service.advance(sid))

    assert service.get(sid).stage is Stage.DRAFT_SYNOPSIS
    assert "synopsis" not in service.get(sid).artifacts


def test_length_finish_reason_is_attributed_as_truncation() -> None:
    """「撞长度上限」与「结构中间自终止」**分开归因**——两者修法不同。"""
    backend = ScriptedBackend(['{"title": "被切断"'], finish_reasons=["length"])
    service, repo = _svc(backend)
    rec = _record(repo)

    with pytest.raises(AppError) as ei:
        _gen(service, rec, Stage.SYNOPSIS_REVISING)

    assert ei.value.details["reason"] == "segment_truncated"
    assert ei.value.details["truncated_segments"] == ["all"]


def test_valid_artifact_is_stored_and_records_checked_true() -> None:
    """正向对照：合法产物照常入库，且留痕里 `checked=true`。

    ⚠️ 「判过且通过」与「根本没判」**必须可分**——`ISSUE-042` 的成因正是二者同形
    （`merge_warnings: 0` 既可能是「合并无告警」，也可能是「压根没合并」）。
    """
    backend = ScriptedBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)

    artifact = rec.artifacts["shot_prompt"]
    assert artifact["artifact_shape"] == "pack"
    assert artifact["artifact_shape_checked"] is True
    assert artifact["artifact_shape_ok"] is True


# ------------------------------------------------------------------ 上游准入闸
def test_invalid_upstream_blocks_generation_without_any_call() -> None:
    """**核心用例**：上游是截断 JSON ⇒ 拒绝生成，且**一次后端调用都不发起**。"""
    backend = ScriptedBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)
    rec.artifacts["storyboard"]["text"] = '{"title": "截断的分镜", "units": ['

    with pytest.raises(AppError) as ei:
        _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)

    assert ei.value.details["reason"] == "upstream_invalid"
    assert ei.value.details["upstream"] == "storyboard"
    assert backend.calls == [], "上游不可用时应**先阻断**，不得消耗算力"
    assert "shot_prompt" not in rec.artifacts


def test_upstream_missing_contract_keys_blocks_generation() -> None:
    """上游「可解析但不成形」同样阻断——否则下游会拿一份残缺基准继续编造。"""
    backend = ScriptedBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)
    rec.artifacts["storyboard"]["text"] = json.dumps(
        {"units": [{"unit_id": "U01"}], "shots": []}, ensure_ascii=False
    )

    with pytest.raises(AppError) as ei:
        _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)

    assert ei.value.details["reason"] == "upstream_invalid"
    assert backend.calls == []


# ------------------------------------------------------------------ 分段贡献闸
def test_multi_part_segment_with_no_contribution_is_rejected() -> None:
    """多段计划里「可解析但零贡献」的段必须被拒——
    `merge_segments` 对该形态**不产生任何告警**，是静默缺口。"""
    plan_head = json.dumps(VALID_PACK, ensure_ascii=False)
    backend = ScriptedBackend([plan_head, "{}", plan_head])
    service, repo = _svc(backend)
    rec = _record(repo)
    rec.artifacts["storyboard"]["text"] = json.dumps(
        {
            **VALID_STORYBOARD,
            "shots": [{"shot_id": f"S01-SH{i:03d}", "scene_no": 1, "shot_no": i}
                      for i in range(1, 9)],
            "units": [{"unit_id": "U01"}, {"unit_id": "U02"}],
        },
        ensure_ascii=False,
    )

    with pytest.raises(AppError) as ei:
        _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)

    assert ei.value.details["reason"] == "segment_contributing_nothing"
    assert ei.value.details["empty_segments"] == ["unit:U01"]
    assert "shot_prompt" not in rec.artifacts


# ------------------------------------------------------------------ 受控旁路
def test_bypass_mode_judges_and_traces_but_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`shape_gate_enforce=false`：**照样判定、照样留痕，仅不阻断**（与安全双闸同纪律）。"""
    monkeypatch.setenv("APP_SHAPE_GATE_ENFORCE", "false")
    get_settings.cache_clear()
    try:
        backend = ScriptedBackend(['{"title": "缺键的梗概"}'])
        service, repo = _svc(backend)
        rec = _record(repo)

        _gen(service, rec, Stage.SYNOPSIS_REVISING)

        artifact = rec.artifacts["synopsis"]
        assert artifact["artifact_shape_checked"] is True
        assert artifact["artifact_shape_ok"] is False
        assert artifact["artifact_shape_enforced"] is False
    finally:
        get_settings.cache_clear()


# --------------------------------------------------- 内容足量性（`ISSUE-045`）
def test_content_adequacy_is_traced_but_never_blocks() -> None:
    """**合法形态 ＋ 严重欠生成**必须**照常入库**，只在留痕里报出来。

    形态取自 `r4` 真跑：3 镜**只覆盖第 1 场**（上游有 3 场）、`Σ 15,000 ms ≠ 声明 45,000 ms`。
    ⚠️ 2026-10-16 项目方裁决：内容足量属**质量**维度、**不设阻断**
    —— 真实模型产物普遍不自洽（四轮真跑中凡产出分镜者时长**无一轮守恒**），
    设阻断会让整条链路不可用。故本用例断言的是「**入库了 ＋ 报出来了**」。
    """
    weak = {
        **VALID_STORYBOARD,
        "total_duration_ms": 45000,
        "shots": [
            {"shot_id": f"S01-SH{i:03d}", "scene_no": 1, "shot_no": i, "duration_ms": 5000}
            for i in (1, 2, 3)
        ],
        "units": [{"unit_id": "U01", "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"]}],
    }
    backend = ScriptedBackend([json.dumps(weak, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)
    rec.artifacts["script"]["text"] = json.dumps(
        {
            **VALID_SCRIPT,
            "acts": [
                {"act_no": a, "scenes": [{"no": n, "est_seconds": 18}]}
                for a, n in ((1, 1), (2, 2), (3, 3))
            ],
            "total_est_seconds": 54,
        },
        ensure_ascii=False,
    )

    _gen(service, rec, Stage.DRAFT_STORYBOARD)  # ⚠️ 不抛错 ＝ 不阻断

    artifact = rec.artifacts["storyboard"]
    assert artifact["artifact_shape_ok"] is True, "形态（结构）确实合规——拦不住它正是本缺陷"
    adequacy = artifact["content_adequacy"]
    assert adequacy["checked"] is True and adequacy["ok"] is False
    codes = {f["code"] for f in adequacy["findings"]}
    assert {"storyboard_duration_sum_mismatch", "scene_coverage_incomplete"} <= codes
    coverage = next(f for f in adequacy["findings"] if f["code"] == "scene_coverage_incomplete")
    assert coverage["scenes_covered"] == [1] and coverage["scenes_missing"] == [2, 3]


def test_content_adequacy_is_separate_from_shape_gate() -> None:
    """两组判据**分字段留痕**：「结构过了」与「内容够了」不得挤进同一个布尔。"""
    backend = ScriptedBackend([json.dumps(VALID_STORYBOARD, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec, Stage.DRAFT_STORYBOARD)

    artifact = rec.artifacts["storyboard"]
    assert artifact["artifact_shape_checked"] is True
    assert "content_adequacy" in artifact and artifact["content_adequacy"]["stage"] == "storyboard"


# --------------------------------------------------- 紧凑化按段适用（`ISSUE-044`）
def test_compaction_applies_only_to_configured_stages() -> None:
    """默认配置下**只对 `shot_prompt` 段**紧凑化，`storyboard` 段原样注入。

    依据（实测）：紧凑化的**唯一动机**是「渲染输入超窗」，而只有 `shot_prompt` 段会超
    （未紧凑 58,550 > 32,768）；`storyboard` 段输入仅 12,214 tokens、**不需要**它。
    """
    # ---- `shot_prompt`：仍紧凑化（方案 D 的目的不受影响）----
    backend = ScriptedBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)
    _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)
    assert set(rec.artifacts["shot_prompt"].get("upstream_compaction") or {}) == {
        "storyboard_json",
        "script_json",
    }

    # ---- `storyboard`：默认不紧凑化 ⇒ 留痕中不出现该项 ----
    backend2 = ScriptedBackend([json.dumps(VALID_STORYBOARD, ensure_ascii=False)])
    service2, repo2 = _svc(backend2)
    rec2 = _record(repo2)
    _gen(service2, rec2, Stage.DRAFT_STORYBOARD)
    assert "upstream_compaction" not in rec2.artifacts["storyboard"]


def test_compaction_stages_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """该范围**由配置决定**（不得硬编码）：改配置即改行为。"""
    monkeypatch.setenv("APP_PROMPT_COMPACT_STAGES", "storyboard")
    get_settings.cache_clear()
    try:
        backend = ScriptedBackend([json.dumps(VALID_STORYBOARD, ensure_ascii=False)])
        service, repo = _svc(backend)
        rec = _record(repo)
        _gen(service, rec, Stage.DRAFT_STORYBOARD)
        assert set(rec.artifacts["storyboard"].get("upstream_compaction") or {}) == {"script_json"}
    finally:
        get_settings.cache_clear()


def test_empty_compaction_stages_disables_it_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空串 ＝ **不适用任何阶段**（不得因为空串而回退成「全都适用」）。"""
    monkeypatch.setenv("APP_PROMPT_COMPACT_STAGES", "")
    get_settings.cache_clear()
    try:
        backend = ScriptedBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
        service, repo = _svc(backend)
        rec = _record(repo)
        _gen(service, rec, Stage.DRAFT_SHOT_PROMPT)
        assert "upstream_compaction" not in rec.artifacts["shot_prompt"]
    finally:
        get_settings.cache_clear()
