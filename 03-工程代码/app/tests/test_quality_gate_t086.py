"""生成后门禁与重试回路的验证（`T-086`；`ISSUE-038` 链路侧一半）。

⚠️ **负向验证纪律**（同 `test_artifact_gate.py`）：本文件的每个用例都对应一次**实测事实**
或一条**已发生过的缺陷形态**，不是「跑通即算过」：

| 用例 | 对应的实测事实／缺陷形态 |
| --- | --- |
| 门禁留痕三态 | `ok=True, checks=0` ＝ **判据空转**却被当通过（本批探针实测踩到） |
| 重试无用项不重试 | `compliance.marking` 由**合规资产**决定，重试改了也白改（白烧 300 s） |
| 用尽重试后如实拒绝 | `T-086` 硬约束：**不得以放行或后处理修补兜底** |
| 重试不得使结果变差 | 本轮**真实踩到**：脚本化后端第 2 轮返回 `{}` ⇒ 形态闸判「无法识别」 |
| 真值覆盖 | 实测产物把服务层占位补成 `safety:"passed"`／`statement_id:"ST-001"`（**假合规**） |
| 覆盖不碰模型字段 | 本层第一纪律：**不改写模型输出**（`total_duration_ms` 等一字不动） |
| 占位符原样保留 | `{{PROVIDER_CODE}}` 曾被渲染成 `{}` ⇒ 交付门禁的 `"{{" in` 判据永不触发 |
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.inference.base import GenParams, GenResult, TextGenerator
from app.prompts.loader import PromptRepository, _interpolate
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.schemas.dialogue import Stage
from app.services import quality_gate
from app.services.dialogue_service import DialogueService
from app.services.pack_meta import apply_service_truth, build_pack_meta


class ScriptedBackend(TextGenerator):
    """按调用次序返回预置文本（**不做任何合规加工**）。

    ⚠️ `name` 取 `vllm`（而不是 `scripted`）是有意的：交付 schema 的
    `generation_trace.model.backend` 是**封闭枚举**（`vllm`／`transformers`／
    `llama_cpp`／`remote_api`／`other`），而服务层真值会把该字段写进产物 ——
    用一个枚举外的名字会让**夹具自己**制造 `schema.pack` BLOCK，掩盖真正要测的东西。
    """

    name = "vllm"
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
        return GenResult(text=text, prompt_tokens=10, completion_tokens=5)

    async def stream(self, prompt, params, json_schema=None):  # type: ignore[no-untyped-def]
        for piece in ():  # pragma: no cover - 集成测试不用流式
            yield piece


# --------------------------------------------------------------------- 夹具
#: 分镜段一门未过（`R10` 单元成员数 1 ⇒ 结构性不合格）——**模型可影响**，属可重试。
_BAD_STORYBOARD = {
    "title": "雨夜",
    "genre": "剧情",
    "style_ref": "ST-01",
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 4000,
    "units": [{"unit_id": "U01", "scene_no": 1, "shot_ids": ["S01-SH001"]}],
    "shots": [
        {
            "shot_id": "S01-SH001",
            "scene_no": 1,
            "shot_no": 1,
            "unit_id": "U01",
            "duration_ms": 4000,
        }
    ],
    "forbidden_items": [],
    "unspecified": [],
    "quality_gate": {},
}

#: 分镜段**质量全过**的对照夹具（成员数 2、镜序连续、时长守恒）。
_GOOD_STORYBOARD = {
    **_BAD_STORYBOARD,
    "units": [{"unit_id": "U01", "scene_no": 1, "shot_ids": ["S01-SH001", "S01-SH002"]}],
    "shots": [
        {"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1, "unit_id": "U01",
         "duration_ms": 4000},
        {"shot_id": "S01-SH002", "scene_no": 1, "shot_no": 2, "unit_id": "U01",
         "duration_ms": 4000},
    ],
    "total_duration_ms": 8000,
}

#: **模型自拟的模型侧元数据**（含实测到的「假合规」值）。
_MODEL_PACK = {
    "schema_version": "2.1.0",
    "meta": {
        "pack_id": "FR-PK-20261016-DEADBEEF",
        "created_at": "2026-10-16T09:47:15+08:00",
        "task_type": "text_to_video",
        "unsupported_task_types": ["keyframe_completion"],
        "generator": {"system": "x", "version": "0.1.0", "provider": "SW-005",
                      "provider_code": "{}"},
        "generation_trace": {"session_id": "sess_forged", "task_id": "T-001"},
        "total_duration_ms": 8000,
        "compliance": {
            "safety_check": {"input": "passed", "output": "passed",
                             "checked_at": "2026-10-16T09:47:15+08:00"},
            "copyright_check": {"status": "passed", "note": ""},
            "marking_check": {"explicit": "present", "implicit": "missing"},
            "statement_id": "ST-001",
        },
    },
    "style_bible": {"style_id": "ST-01"},
    "characters": [],
    "props": [],
    "units": [{"unit_id": "U01"}],
    "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}],
    "forbidden_items": [],
    "aigc_meta": {"AIGC": {"Label": "1", "ContentProducer": "SW-005",
                           "ProduceID": "FR-PK-20261016-DEADBEEF",
                           "ReservedCode1": "", "ContentPropagator": "SW-005",
                           "PropagateID": "FR-PK-20261016-DEADBEEF", "ReservedCode2": ""}},
}


def _svc(backend: ScriptedBackend) -> tuple[DialogueService, SessionRepository]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    return DialogueService(repo, prompts, backend_resolver=lambda: backend), repo


def _record(
    repo: SessionRepository, stage: Stage, *, upstream: tuple[str, ...] = ("script",)
) -> SessionRecord:
    """建会话并**只**预置所需上游。

    ⚠️ 必须按需预置：若给分镜段用例也塞一份 `storyboard`，那么「产物未通过门禁所以
    **不得入库**」这类断言会因为**夹具先占位**而假通过 —— 断言失去了意义。
    """
    source = "一只流浪猫在雨夜被人救起"
    rec = repo.create(stage=stage.value, source_input=source,
                      defaults={"source_input": source})
    if "script" in upstream:
        rec.artifacts["script"] = {"text": json.dumps({
            "title": "雨夜", "logline": "一句话", "genre": "剧情",
            "style_bible": {"style_id": "ST-01"}, "characters": [], "props": [],
            "acts": [], "forbidden_items": [], "total_est_seconds": 0, "unspecified": [],
        }, ensure_ascii=False)}
    if "storyboard" in upstream:
        rec.artifacts["storyboard"] = {
            "text": json.dumps(_GOOD_STORYBOARD, ensure_ascii=False)
        }
    return rec


def _gen(service: DialogueService, rec: SessionRecord, target: Stage) -> None:
    asyncio.run(service._maybe_generate(rec, target, dict(rec.defaults)))


class _StubVerdict:
    """可控的门禁结论替身（用于**控制流**断言：重试几次、什么时候停）。

    ⚠️ 为什么用替身而不是「造一份真能过门禁的产物」：`R19`／`R23`／`R24` 等质量门
    要求「轴线覆盖 ≥30%」这类**统计性**条件，构造一个全过的夹具本身就是一个
    大工程，且会随判据演进失效 —— 那种测试断言的是**夹具**，不是**回路**。
    真判据的正确性由 `probe_t086_gate.py`（对着真实产物）与
    `test_compliance_failures_are_classified_as_non_retryable` 负责。
    """

    def __init__(self, ok: bool, retryable: list[str], non_retryable: list[str] | None = None):
        self.ok = ok
        self.retryable = retryable
        self.non_retryable = non_retryable or []
        self.shape = "storyboard"
        self.checked = True
        self.enforced = False
        self.reason = None
        self.stage = "storyboard"

    def as_record(self) -> dict:
        return {"stage": self.stage, "shape": self.shape, "checked": True, "ok": self.ok,
                "retryable": len(self.retryable), "non_retryable": len(self.non_retryable)}


async def _next_verdict(seq):  # type: ignore[no-untyped-def]
    """按序列返回替身结论（`quality_gate.check` 的 async 签名替身）。"""
    return next(seq)


# ------------------------------------------------------------------ 占位符纪律
def test_double_brace_placeholder_survives_rendering() -> None:
    """`{{PROVIDER_CODE}}` 必须**原样保留**——它曾被渲染成 `{}`，使反查链静默断掉。

    ⚠️ 交付门禁 `validate_pack.py` 的判据是 `"{{" in provider_code`；
    若渲染成 `{PROVIDER_CODE}`（单花括号）或 `{}`，该 WARN **永不触发** ⇒ 占位项静默通过。
    """
    class _Tpl:
        @staticmethod
        def default_of(name: str) -> None:
            return None

    out = _interpolate('"provider_code": "{{PROVIDER_CODE}}"', {}, _Tpl())
    assert out == '"provider_code": "{{PROVIDER_CODE}}"'
    assert "{{" in out, "判据依赖 `{{`，渲染后必须仍能检出"

    # 相邻 `}}` 是 JSON 示例的合法收尾，**不得**被误当占位符处理
    nested = '{"a": {"b": 1}}'
    assert _interpolate(nested, {}, _Tpl()) == nested

    # 既有变量插值行为不变
    assert _interpolate("v={foo}", {"foo": "OK"}, _Tpl()) == "v=OK"


# ------------------------------------------------------------------ 门禁三态
def test_gate_ok_is_tristate_and_never_reports_false_pass() -> None:
    """`ok` 必须是三态：**「没判」不得长得像「判过且通过」**。

    ⚠️ 实测踩到（本批探针）：产物是 **API 信封**（`{"request_id":…,"data":…}`）时，
    `detect_shape` 返回 `None` ⇒ 判据脚本「无法识别形态 → 告警并跳过」⇒
    `checks=0, errors=0` ⇒ 按「无失败即通过」折算会得到 **`ok=True`** —— 一个
    「什么都没判」的产物被报成「通过」（`ISSUE-042` 的同形缺陷）。
    """
    envelope = json.dumps({"request_id": "req_x", "data": {"view": {}}})
    verdict = asyncio.run(quality_gate.check("storyboard", text=envelope))
    assert verdict.checked is True
    assert verdict.ok is None and verdict.reason == "shape_undetected", (
        f"判据空转必须报 None，不得报 True（实测得到 ok={verdict.ok!r}, reason={verdict.reason!r}）"
    )

    # 负向对照：结构合法但质量未过 ⇒ 必须是**确定的 False**，不是 None
    bad = asyncio.run(quality_gate.check(
        "storyboard", text=json.dumps(_BAD_STORYBOARD, ensure_ascii=False)
    ))
    assert bad.ok is False and bad.engine_checks > 0
    assert bad.retryable, "分镜段的成员数不合格属**模型可影响**，应判为可重试"


def test_compliance_failures_are_classified_as_non_retryable() -> None:
    """合规资产缺口**不得**被拿去重试（否则白烧数百秒、还误导归因方向）。

    `compliance.marking` 由标识服务（`SW-014`）决定，模型与重试都改不了它。
    """
    verdict = asyncio.run(quality_gate.check(
        "shot_prompt", text=json.dumps(_MODEL_PACK, ensure_ascii=False)
    ))
    assert verdict.ok is False
    assert any("compliance" in c for c in verdict.non_retryable), (
        f"合规类失败应进 non_retryable，实得 {verdict.non_retryable}"
    )
    assert not any("compliance" in c for c in verdict.retryable)


# ------------------------------------------------------------------ 真值覆盖
def test_service_truth_overrides_forged_compliance_values() -> None:
    """模型自拟的「假合规」必须被服务层真值覆盖（**合规级**缺陷）。

    实测产物里 `safety_check:"passed"`（还带时间戳）、`marking_check.explicit:"present"`、
    `statement_id:"ST-001"` 全是模型编的 —— 产物看起来已过内容安全与标识校验，
    而平台根本没做。这比「缺失」危险：缺失会被门禁拦下，**假值会通过门禁**。
    """
    settings = get_settings()
    doc = json.loads(json.dumps(_MODEL_PACK, ensure_ascii=False))
    before = dict(doc["meta"]["compliance"])

    truth = build_pack_meta(
        session_id="sess_real", stage="shot_prompt", templates=[], model={},
        settings=settings, artifacts={}, title="t",
    )
    overrides = apply_service_truth(
        doc, truth, provider_name=settings.provider_name,
        provider_code=settings.provider_code,
    )
    assert overrides is not None

    comp = doc["meta"]["compliance"]
    assert comp != before, "模型自拟的合规块**必须**被覆盖"
    assert comp["statement_id"] == truth["compliance"]["statement_id"]
    assert comp["marking_check"] == truth["compliance"]["marking_check"]
    assert "passed" not in json.dumps(comp["copyright_check"], ensure_ascii=False)

    # 标识块必须与覆盖后的 `meta.pack_id` **同源**，否则会制造新的 `meta.produce_id` BLOCK
    aigc = doc["aigc_meta"]["AIGC"]
    assert aigc["ProduceID"] == doc["meta"]["pack_id"]
    assert aigc["PropagateID"] == aigc["ProduceID"]
    assert aigc["ContentPropagator"] == aigc["ContentProducer"]
    assert aigc["Label"] == "1"

    # `generation_trace.session_id` 属服务层域（反查链）⇒ 必须换成真值
    assert doc["meta"]["generation_trace"]["session_id"] == "sess_real"

    # ⚠️ **模型可影响字段一字不改**（本层第一纪律）
    assert doc["meta"]["total_duration_ms"] == 8000
    assert doc["shots"] == _MODEL_PACK["shots"]
    # ⚠️ 能力声明属**对外口径**、服务层无真值 ⇒ 未配置时**保留模型值**（不得降级成空列表）
    assert doc["meta"]["unsupported_task_types"] == ["keyframe_completion"]


def test_service_truth_never_invents_missing_keys() -> None:
    """覆盖**只覆盖已有键、不替模型补缺**：缺键是 `R27`／`R30` 的判据，补上等于替模型填洞。"""
    settings = get_settings()
    doc = {"schema_version": "2.1.0", "meta": {"pack_id": "AC-PK-1"}, "aigc_meta": {}}
    truth = build_pack_meta(session_id="s", stage="shot_prompt", templates=[], model={},
                            settings=settings, artifacts={}, title="t")
    apply_service_truth(doc, truth, provider_name="", provider_code="")
    assert "created_at" not in doc["meta"], "模型没输出的服务层域键不得被补上"
    assert "compliance" not in doc["meta"]
    assert "AIGC" not in doc["aigc_meta"]


# ------------------------------------------------------------------ 回路行为
def test_gate_runs_once_and_is_traced_when_retry_disabled() -> None:
    """重试关（默认）时：判定与留痕照常，**但只调用一次后端**（不得偷偷重试）。"""
    backend = ScriptedBackend([json.dumps(_BAD_STORYBOARD, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo, Stage.DRAFT_STORYBOARD)

    _gen(service, rec, Stage.DRAFT_STORYBOARD)

    assert len(backend.calls) == 1
    gate = rec.artifacts["storyboard"]["quality_gate"]
    assert gate["applies"] is True
    assert gate["attempts"] == 1
    assert gate["ok"] is False, "质量未过必须如实记为 False"
    assert gate["history"][0]["checked"] is True
    assert gate["last_retryable"], "失败明细必须留下 —— 它是 T-087 的唯一依据"


def test_retry_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """**默认不重试**（成倍耗时）：`quality_gate_retry_enabled` 缺省为 `False`。"""
    get_settings.cache_clear()
    try:
        assert get_settings().quality_gate_retry_enabled is False
        assert get_settings().quality_gate_enforce is False
        assert get_settings().quality_gate_enabled is True
    finally:
        get_settings.cache_clear()


def test_retry_then_pass_stops_early(monkeypatch: pytest.MonkeyPatch) -> None:
    """首轮未过、次轮过 ⇒ 停在 **2 次调用**，且末次判定为 `ok=True`。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        seq = iter([
            _StubVerdict(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
            _StubVerdict(True, []),
        ])
        monkeypatch.setattr(quality_gate, "check",
                            lambda *a, **k: _next_verdict(seq))
        backend = ScriptedBackend([
            json.dumps(_BAD_STORYBOARD, ensure_ascii=False),
            json.dumps(_GOOD_STORYBOARD, ensure_ascii=False),
        ])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        assert len(backend.calls) == 2, "上限 2 且次轮已过 ⇒ 不得再多跑"
        gate = rec.artifacts["storyboard"]["quality_gate"]
        assert gate["attempts"] == 2
        assert gate["ok"] is True
        # 两次尝试都必须留痕（「重试了没有」必须可核查，
        # 且「直出率」要与「重试后通过率」**可分** —— 二者混成一个数就失去了诊断力）
        assert [h["attempt"] for h in gate["history"]] == [1, 2]
        assert gate["history"][0]["ok"] is False and gate["history"][1]["ok"] is True
    finally:
        get_settings.cache_clear()


def test_retry_never_degrades_a_valid_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """**重试不得使结果变差**：次轮产出非法时回退到首轮，并如实标注。

    ⚠️ 本批**真实踩到**：脚本化后端只预置一轮响应时，第 2 次调用返回 `{}` ⇒
    形态闸判「无法识别」。若直接抛出，等于用**结构非法**的产物替换掉**结构合法**的产物 ——
    净效果是变差，且把「质量未过关」掩盖成「产物不可解析」。
    """
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        backend = ScriptedBackend([
            json.dumps(_BAD_STORYBOARD, ensure_ascii=False),
            "{}",  # 次轮：不可解析（形态闸会判「无法识别」）
        ])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        artifact = rec.artifacts["storyboard"]
        assert artifact["artifact_shape_ok"] is True, "产物必须是首轮那一版（结构合法）"
        assert json.loads(artifact["text"])["units"][0]["unit_id"] == "U01"
        assert artifact["quality_gate"]["retry_scope"] == "retry_degraded_fallback"
    finally:
        get_settings.cache_clear()


def test_exhausted_retry_rejects_honestly_when_enforcing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`T-086` 硬约束：用尽重试仍不过 ⇒ **如实拒绝**，且产物**不得入库**。

    ⚠️ 不得以「放行」或「后处理修补」（如改写 `meta.notes` 说本包已通过）兜底 ——
    那会把「未通过门禁」这件事从产物里抹掉，而备案举证要的正是「产物可追溯到判定」。
    """
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    monkeypatch.setenv("APP_QUALITY_GATE_ENFORCE", "true")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            quality_gate, "check",
            lambda *a, **k: _next_verdict(iter([
                _StubVerdict(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
                _StubVerdict(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
            ])),
        )
        bad = json.dumps(_BAD_STORYBOARD, ensure_ascii=False)
        backend = ScriptedBackend([bad, bad])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        with pytest.raises(AppError) as ei:
            _gen(service, rec, Stage.DRAFT_STORYBOARD)

        assert ei.value.code is ErrorCode.GENERATION_FAILED
        assert ei.value.details["reason"] == "quality_gate_not_passed"
        assert ei.value.details["attempts"] == 2
        assert len(backend.calls) == 2, "上限已用尽，不得再多跑"
        assert "storyboard" not in rec.artifacts, "未过门禁的产物**不得入库**"
    finally:
        get_settings.cache_clear()


def test_exhausted_retry_passes_through_and_traces_when_not_enforcing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分阶段上线期间（`enforce=false`）：**放行但如实登记**，且留痕里 `enforced=false`。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            quality_gate, "check",
            lambda *a, **k: _next_verdict(iter([
                _StubVerdict(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
                _StubVerdict(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
            ])),
        )
        bad = json.dumps(_BAD_STORYBOARD, ensure_ascii=False)
        backend = ScriptedBackend([bad, bad])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        gate = rec.artifacts["storyboard"]["quality_gate"]
        assert gate["attempts"] == 2 and gate["ok"] is False
        assert gate["enforced"] is False, "旁路状态必须在留痕里体现，**不得静默**"
    finally:
        get_settings.cache_clear()


def test_no_retryable_failure_stops_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败里若**没有模型可影响的项**，立刻停 —— 不把额度烧在改不动的事情上。

    ⚠️ 这条规则的值在于**省时间与归因**：`compliance.*` 类失败由合规资产决定，
    重试两次照样失败，但日志会看起来像「模型不行」（实测 `shot_prompt` 段单次约 304 s，
    白烧两次即 10 分钟）。判据本身由 `should_retry` 承担、分类正确性另有用例覆盖；
    此处只验**控制流**确实据它停下。
    """
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            quality_gate, "check",
            lambda *a, **k: _next_verdict(iter([
                _StubVerdict(False, [], ["compliance.marking｜标识完整性校验未通过"]),
            ])),
        )
        bad = json.dumps(_BAD_STORYBOARD, ensure_ascii=False)
        backend = ScriptedBackend([bad, bad])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        gate = rec.artifacts["storyboard"]["quality_gate"]
        assert gate["retry_scope"] == "no_retryable_failure"
        assert len(backend.calls) == 1, "无可重试项时不得再调用后端"
        assert gate["last_non_retryable"], "重试无用的明细必须留下（举证与归因都要它）"
    finally:
        get_settings.cache_clear()


def test_should_retry_ignores_non_retryable_only_failures() -> None:
    """`should_retry` 的判据＝「是否存在模型可影响的失败」，仅此一条。"""
    only_asset = quality_gate.QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=False, engine_checks=5,
        engine_errors=[], engine_warnings=[],
        pack_blocks=["compliance.marking｜标识完整性校验未通过"],
        pack_warnings=[], retryable=[], non_retryable=["compliance.marking｜…"],
        enforced=False,
    )
    assert quality_gate.should_retry(only_asset) is False

    has_model_side = quality_gate.QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=False, engine_checks=5,
        engine_errors=["unit.camera_dup"], engine_warnings=[],
        pack_blocks=["compliance.marking｜标识完整性校验未通过"],
        pack_warnings=[], retryable=["unit.camera_dup｜单元 U01 内运镜类型重复"],
        non_retryable=["compliance.marking｜…"], enforced=False,
    )
    assert quality_gate.should_retry(has_model_side) is True


# ------------------------------------------------------------------ 按段重试定位
def test_retry_segments_locates_units_and_falls_back_to_all() -> None:
    """按段定位：报错里带 `U01` ⇒ 只重跑 `unit:U01`；定位不到 ⇒ **回退全部段**。"""
    plan = ["package_head", "unit:U01", "unit:U02"]
    # 各段都**有贡献**（否则会触发「零贡献段必重跑」这条独立规则，干扰本用例的判据）
    texts = {
        "package_head": json.dumps({"schema_version": "2.1.0"}, ensure_ascii=False),
        "unit:U01": json.dumps({"units": [{"unit_id": "U01"}],
                                "shots": [{"shot_id": "S01-SH001"}]}, ensure_ascii=False),
        "unit:U02": json.dumps({"units": [{"unit_id": "U02"}],
                                "shots": [{"shot_id": "S01-SH002"}]}, ensure_ascii=False),
    }

    class _V:
        retryable = ["单元 U01 内运镜类型重复"]

    service, _repo = _svc(ScriptedBackend([]))
    picked, _note = service._retry_segments(plan, _V(), texts)
    assert "unit:U01" in picked and "unit:U02" not in picked, (
        f"应只重跑被点名的单元段，实得 {picked}"
    )

    class _Vague:
        retryable = ["产物某处不对（无定位信息）"]

    picked2, note2 = service._retry_segments(plan, _Vague(), texts)
    assert picked2 == plan, "定位不到时必须回退为**全部段**（宁可多跑，不得漏跑）"
    assert note2 == "scope_fallback"

    # 单段计划（`all`）时「按段」与「整阶段」等价，不需要标注 fallback
    picked3, note3 = service._retry_segments(["all"], _Vague(), {"all": "{}"})
    assert picked3 == ["all"] and note3 is None


def test_retry_segments_always_reruns_zero_contribution_and_unparsable() -> None:
    """**零贡献／不可解析**的段一律重跑 —— 它们正是「看起来完整、实则无据」的来源。"""
    plan = ["package_head", "unit:U01", "unit:U02"]
    texts = {
        "package_head": json.dumps({"schema_version": "2.1.0"}, ensure_ascii=False),
        "unit:U01": "{}",                # 可解析但**零贡献**
        "unit:U02": "这不是 JSON",        # 解析失败
    }

    class _NoLocator:
        retryable = ["与具体段无关的报错"]

    service, _repo = _svc(ScriptedBackend([]))
    picked, _note = service._retry_segments(plan, _NoLocator(), texts)
    assert "unit:U01" in picked and "unit:U02" in picked
    assert "package_head" not in picked, "有贡献的段不该被连坐重跑"
