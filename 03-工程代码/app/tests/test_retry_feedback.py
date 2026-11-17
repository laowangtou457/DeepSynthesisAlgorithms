# -*- coding: utf-8 -*-
"""**乙**：质量门禁重试的「判据反馈注入」与「承继字段失败跳过」（2026-11-17 裁决）。

⚠️ **负向验证纪律**（同 `test_quality_gate_t086.py`）：每个用例对应一次**实测事实**——
甲试点（`DEV-20261117-001`）盲重试救回 0/4：

| 用例 | 对应的实测事实／缺陷形态 |
| --- | --- |
| 反馈文本构造 | retryable 明细是重采唯一可用的「哪里错了」信息；非 retryable 不得混入 |
| unit→scene 映射 | 甲试点第 1 轮：retryable 明写 `U02` 却只重采 `scene:1`（打偏） |
| 承继字段跳过 | `camera.*` 出生于 `storyboard` 段且 `shot_prompt` 承继守恒 ⇒ 下游重试结构上无效 |
| 反馈随重采注入 | 盲重试（同提示词重掷骰子）打破不了系统性偏置 ⇒ 反馈必须真的到达模型 |
| 映射不到回退全段 | 宁多勿漏纪律保持不变（`scope_fallback`） |

⚠️ 不真调模型（ScriptedBackend 替身，夹具复用 `test_quality_gate_t086`）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.schemas.dialogue import Stage
from app.services import quality_gate
from app.services.dialogue_service import DialogueService

from test_quality_gate_t086 import (  # noqa: F401  （夹具复用，不重复造轮子）
    _BAD_STORYBOARD,
    _GOOD_STORYBOARD,
    _gen,
    _record,
    _svc,
)
from test_artifact_gate import (  # noqa: F401  （全上游夹具：shot_prompt 需 script＋storyboard）
    VALID_PACK,
    _gen as _gen_ag,
    _record as _record_ag,
    _svc as _svc_ag,
)


class _Verdict(SimpleNamespace):
    """最小门禁结论替身（`_retry_segments`／反馈构造只读 `retryable`）。"""


def _svc_light() -> DialogueService:
    """`__new__` 免依赖构造（`_retry_segments`／纯助手不需要仓库与后端）。"""
    return DialogueService.__new__(DialogueService)


# --------------------------------------------------------------- 反馈文本构造

def test_retry_feedback_text_includes_retryable_and_caps() -> None:
    """反馈只含 retryable、按 ≤8 条截断、带次序与兜底句；non_retryable 不得混入。"""
    items = ["失败 %02d：某判据未达标" % i for i in range(10)]
    v = SimpleNamespace(retryable=items, non_retryable=["compliance.marking_pending：占位"])
    text = DialogueService._retry_feedback_text(2, v)
    assert text is not None
    assert "第 2 次尝试" in text
    assert "- 失败 07：某判据未达标" in text          # 前 8 条全带
    assert "失败 08" not in text                      # 第 9 条被截掉
    assert "另有 2 条同类失败未列出" in text
    assert "compliance.marking_pending" not in text   # non_retryable 不进反馈
    assert "合法 JSON" in text


def test_retry_feedback_text_truncates_long_items() -> None:
    """单条 ≤200 字符（反馈是指向灯，不是全文回显——防「抄错值」复发）。"""
    v = SimpleNamespace(retryable=["X" * 500], non_retryable=[])
    text = DialogueService._retry_feedback_text(1, v)
    assert text is not None and len(text) < 400 and "XXXXX" in text


def test_retry_feedback_text_none_when_no_retryable() -> None:
    v = SimpleNamespace(retryable=[], non_retryable=["compliance.x"])
    assert DialogueService._retry_feedback_text(1, v) is None


# ------------------------------------------------------- unit→scene 映射（乙修）

def test_retry_segments_maps_mentioned_unit_to_scene() -> None:
    """storyboard 段：retryable 提 `U02` ⇒ 从上一轮段产物解析出 `U02` 属 `scene:2`。"""
    texts = {
        "scene:1": json.dumps({"units": [{"unit_id": "U01"}],
                               "shots": [{"shot_id": "S01-SH001", "unit_id": "U01"}]}),
        "scene:2": json.dumps({"units": [{"unit_id": "U02"}],
                               "shots": [{"shot_id": "S02-SH001", "unit_id": "U02"}]}),
        "scene:3": json.dumps({"units": [{"unit_id": "U03"}],
                               "shots": [{"shot_id": "S03-SH001", "unit_id": "U03"}]}),
    }
    v = _Verdict(retryable=["storyboard · R11 UNIT_MOVE_UNIQUE：U02 运镜重复 ['static','static']"],
                 non_retryable=[])
    picked, scope = _svc_light()._retry_segments(["scene:1", "scene:2", "scene:3"], v, texts)
    assert picked == ["scene:2"], "必须重采 U02 所属的场，而不是打偏到别的场"
    assert scope is None


def test_retry_segments_unmatched_unit_falls_back_to_all() -> None:
    """点名的单元在上一轮任何段里都找不到 ⇒ 回退全部段（宁多勿漏纪律不变）。"""
    texts = {
        "scene:1": json.dumps({"units": [{"unit_id": "U01"}],
                               "shots": [{"shot_id": "S01-SH001", "unit_id": "U01"}]}),
        "scene:2": json.dumps({"units": [{"unit_id": "U02"}],
                               "shots": [{"shot_id": "S02-SH001", "unit_id": "U02"}]}),
    }
    v = _Verdict(retryable=["R11 UNIT_MOVE_UNIQUE：U09 运镜重复"], non_retryable=[])
    picked, scope = _svc_light()._retry_segments(["scene:1", "scene:2"], v, texts)
    assert picked == ["scene:1", "scene:2"] and scope == "scope_fallback"


def test_retry_segments_unit_stage_direct_match_still_works() -> None:
    """shot_prompt 段（plan=`unit:Uxx`）的既有直接匹配不得被新规则破坏。"""
    texts = {
        "unit:U01": json.dumps({"units": [{"unit_id": "U01"}],
                                "shots": [{"shot_id": "S01-SH001", "unit_id": "U01"}]}),
        "unit:U02": json.dumps({"units": [{"unit_id": "U02"}],
                                "shots": [{"shot_id": "S02-SH001", "unit_id": "U02"}]}),
    }
    v = _Verdict(retryable=["shot_prompt · R11 UNIT_MOVE_UNIQUE：U02 运镜重复"], non_retryable=[])
    picked, scope = _svc_light()._retry_segments(["unit:U01", "unit:U02"], v, texts)
    assert picked == ["unit:U02"] and scope is None


# --------------------------------------------------- 承继字段失败跳过（乙新增）

def test_shot_prompt_inherited_only_failure_skips_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`shot_prompt` 段 retryable 全部为 R11/R19 族 ⇒ **不重采**（结构上救不回），判定如实留痕。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        backend, service, repo, rec = _shot_prompt_harness()
        # ⚠️ 只用 R11（QA 结论 A1：pack 分支不接线 rule_gate，R19 在 shot_prompt 段不可达，
        # 用 R19 串会制造「生产可达」假象——正是 QA 抓出并订正的点）。
        seq = iter([
            _V(False, [
                "shot_prompt · R11 UNIT_MOVE_UNIQUE：U02 运镜重复 ['static','static']",
            ], stage="shot_prompt"),
            _V(False, [
                "shot_prompt · R11 UNIT_MOVE_UNIQUE：U02 运镜重复 ['static','static']",
            ], stage="shot_prompt"),
        ])
        monkeypatch.setattr(quality_gate, "check", _checker(seq))
        _gen_ag(service, rec, Stage.DRAFT_SHOT_PROMPT)

        assert len(backend.calls) == 1, "承继字段失败不得白烧第二次采样（甲试点 +40% 时长的教训）"
        gate = rec.artifacts["shot_prompt"]["quality_gate"]
        assert gate["ok"] is False, "跳过 ≠ 放行：判定必须如实留痕"
        assert gate["retry_scope"] == "retry_skipped_inherited_move"
    finally:
        get_settings.cache_clear()


def test_shot_prompt_mixed_failure_still_retries_with_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """混合失败（R11＋本段可修项）⇒ 照常重试，且第二次请求**必须带反馈文本**。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        backend, service, repo, rec = _shot_prompt_harness()
        seq = iter([
            _V(False, [
                "shot_prompt · R11 UNIT_MOVE_UNIQUE：U02 运镜重复 ['static','static']",
                "shot_prompt · R35 PROP_ANCHOR：S01-SH001 的 prop_refs 未命中道具锚",
            ], stage="shot_prompt"),
            _V(True, [], stage="shot_prompt"),
        ])
        monkeypatch.setattr(quality_gate, "check", _checker(seq))
        _gen_ag(service, rec, Stage.DRAFT_SHOT_PROMPT)

        assert len(backend.calls) == 2
        first_prompt = backend.calls[0]["prompt"]
        retry_prompt = backend.calls[1]["prompt"]
        assert "[整改反馈]" not in first_prompt, "首轮不得带反馈"
        assert "[整改反馈]" in retry_prompt
        assert "第 1 次尝试" in retry_prompt
        assert "R35 PROP_ANCHOR" in retry_prompt, "本段可修项必须出现在反馈里"
        assert "R11 UNIT_MOVE_UNIQUE" in retry_prompt
    finally:
        get_settings.cache_clear()


def test_storyboard_retry_prompt_carries_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    """storyboard 段（运镜出生地）：重采请求带 retryable 明细；次轮过 ⇒ 停在 2 次调用。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    try:
        seq = iter([
            _V(False, ["storyboard · R11 UNIT_MOVE_UNIQUE：U02 运镜重复 ['static','static']"]),
            _V(True, []),
        ])
        from test_quality_gate_t086 import ScriptedBackend  # noqa: PLC0415  （就近导入夹具）
        monkeypatch.setattr(quality_gate, "check", _checker(seq))
        backend = ScriptedBackend([
            json.dumps(_BAD_STORYBOARD, ensure_ascii=False),
            json.dumps(_GOOD_STORYBOARD, ensure_ascii=False),
        ])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        assert len(backend.calls) == 2
        assert "[整改反馈]" in backend.calls[1]["prompt"]
        assert "U02 运镜重复" in backend.calls[1]["prompt"], "被点名的单元必须出现在反馈里"
        gate = rec.artifacts["storyboard"]["quality_gate"]
        assert gate["attempts"] == 2 and gate["ok"] is True
    finally:
        get_settings.cache_clear()


def test_feedback_disabled_keeps_legacy_blind_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关（回滚位）⇒ 重试照常发生但**不带反馈**（旧行为可一键恢复）。"""
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_ENABLED", "true")
    monkeypatch.setenv("APP_QUALITY_GATE_RETRY_FEEDBACK", "false")
    get_settings.cache_clear()
    try:
        seq = iter([
            _V(False, ["R10 UNIT_SIZE：U01 成员数 1"]),
            _V(True, []),
        ])
        from test_quality_gate_t086 import ScriptedBackend  # noqa: PLC0415
        monkeypatch.setattr(quality_gate, "check", _checker(seq))
        backend = ScriptedBackend([
            json.dumps(_BAD_STORYBOARD, ensure_ascii=False),
            json.dumps(_GOOD_STORYBOARD, ensure_ascii=False),
        ])
        service, repo = _svc(backend)
        rec = _record(repo, Stage.DRAFT_STORYBOARD)

        _gen(service, rec, Stage.DRAFT_STORYBOARD)

        assert len(backend.calls) == 2
        assert "[整改反馈]" not in backend.calls[1]["prompt"]
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------------ 夹具与替身

def _V(ok, retryable, non_retryable=(), stage="storyboard"):
    """门禁结论替身：带 `as_record`（`gate_verdicts` 会调它留痕，t086 `_StubVerdict` 同款）。"""
    shape = "pack" if stage == "shot_prompt" else "storyboard"
    return SimpleNamespace(
        ok=ok, retryable=list(retryable), non_retryable=list(non_retryable),
        shape=shape, checked=True, enforced=False, reason=None, stage=stage,
        as_record=lambda: {"stage": stage, "shape": shape, "checked": True, "ok": ok,
                           "retryable": len(retryable), "non_retryable": len(non_retryable)},
    )


def _checker(seq):  # type: ignore[no-untyped-def]
    ''' 是 async ⇒ 替身也必须是 async（t086 同款手法）。'''
    async def _check(*a, **k):  # type: ignore[no-untyped-def]
        return next(seq)
    return _check


def _shot_prompt_harness():  # type: ignore[no-untyped-def]
    """`shot_prompt` 段的最小夹具：`shot_prompt` 需要 **script＋storyboard 双上游**
    （缺 script 会在 2306 行被上游准入挡下）⇒ 复用 `test_artifact_gate` 的全上游夹具，
    产物文本用其 `VALID_PACK`（该夹具下形态闸必过，门禁结论由替身控制）。"""
    from test_artifact_gate import ScriptedBackend as AGBackend  # noqa: PLC0415
    backend = AGBackend([json.dumps(VALID_PACK, ensure_ascii=False)])
    service, repo = _svc_ag(backend)
    rec = _record_ag(repo)
    return backend, service, repo, rec
