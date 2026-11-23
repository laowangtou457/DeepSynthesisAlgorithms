# -*- coding: utf-8 -*-
"""**acts 元素级预修复器**（批次1a，`ISSUE-095`/`096`）的穷举用例。

缺陷现场（分层对照两臂 30 轮实测的主失败族）
--------------------------------------------
模型偶发把剧本的某一幕（场）**再序列化一层**——`acts[i]` 的值是一个 JSON 字符串，
其内容本是合法对象。形态闸第四层当场拒绝（`script_structure_invalid` ⇒ 重采），
重采再犯 ⇒ 整轮失败。本批在归一化链最前加**确定性预修复**：只把「内容合法、
多包一层引号」的元素解析回对象；不可解析形态（纯文本等）**原样留给形态闸拒**。

用例组（正负各半，负向样本纪律见 `CFG-007_SCHEMA.md` 文末条款）：
- ① 可修形态逐种解包（acts 元素／scenes 元素／多处并发）＋中文不转义；
- ② 不可修形态逐种**不碰**（纯文本／数组／标量／二次序列化）；
- ③ noop 不写键（不污染每次生成，同 `amp_norm` 纪律）；
- ④ 端到端：可修 ⇒ 首采即过、留痕可核查、下游场号可推导；
- ⑤ 端到端负向：纯文本 `acts[2]` **照旧被拒**（修复不洗白真缺陷），
  且**部分修复不掩盖**其余缺陷（混合形态仍按 `acts[2]` 拒）。
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
from app.schemas.dialogue import Stage
from app.services.dialogue_service import DialogueService, _repair_acts_strings
from app.services.segment import scene_nos_of


# --------------------------------------------------------------------- 夹具
def _script(acts: object) -> dict:
    """契约完备的剧本骨架（与 `test_script_structure_gate` 同款）。"""
    return {
        "title": "雨夜",
        "logline": "一句话",
        "genre": "剧情",
        "style_bible": {"style_id": "ST-01"},
        "characters": [],
        "props": [],
        "acts": acts,
        "forbidden_items": [],
        "total_est_seconds": 30,
        "unspecified": [],
    }


ACT3 = {"act_no": 3, "scenes": [{"no": 3, "est_seconds": 10, "location": "雨夜矿区"}]}

#: **可修复形态**：`acts[2]` 是 JSON 字符串，内容本是合法对象（双重序列化）。
REPAIRABLE_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]},
        json.dumps(ACT3, ensure_ascii=False),
    ]
)

#: **可修复形态（场级）**：`acts[1].scenes[0]` 是 JSON 字符串。
REPAIRABLE_SCENES_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {
            "act_no": 2,
            "scenes": [json.dumps({"no": 2, "est_seconds": 10}, ensure_ascii=False)],
        },
        {"act_no": 3, "scenes": [{"no": 3, "est_seconds": 10}]},
    ]
)

#: **不可修复形态（负向对照）**：`acts[2]` 是纯文本——内容本身就不是对象，
#: 修复器不得碰它，形态闸照旧拒绝（真机第 3 轮现场的同款形态）。
PLAIN_TEXT_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]},
        "第三幕：直接写成了字符串",
    ]
)

#: **混合形态**：acts[1] 可修、acts[2] 纯文本 ⇒ 只修 acts[1]，
#: 修复**不得掩盖** acts[2] 的真缺陷（仍按 acts[2] 拒）。
MIXED_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        json.dumps(
            {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]}, ensure_ascii=False
        ),
        "第三幕：直接写成了字符串",
    ]
)

VALID_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]},
        {"act_no": 3, "scenes": [{"no": 3, "est_seconds": 10}]},
    ]
)


class ScriptedBackend(TextGenerator):
    """按调用次序返回预置文本（与 `test_script_structure_gate` 同款）。"""

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
        for piece in ():  # pragma: no cover - 本文件不用流式
            yield piece


def _svc(backend: ScriptedBackend) -> tuple[DialogueService, SessionRepository]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    return DialogueService(repo, prompts, backend_resolver=lambda: backend), repo


def _record(repo: SessionRepository) -> SessionRecord:
    source = "一只流浪猫在雨夜被人救起"
    rec = repo.create(
        stage=Stage.DRAFT_SCRIPT.value, source_input=source, defaults={"source_input": source}
    )
    rec.artifacts["synopsis"] = {"text": json.dumps(
        {
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
        },
        ensure_ascii=False,
    )}
    return rec


def _gen(service: DialogueService, rec: SessionRecord) -> None:
    asyncio.run(service._maybe_generate(rec, Stage.DRAFT_SCRIPT, dict(rec.defaults)))


# ------------------------------------- ① 可修形态：逐种解包 ＋ 明细可核查
def test_double_serialized_act_element_is_unwrapped() -> None:
    """核心正向：`acts[2]` 是合法对象的 JSON 字符串 ⇒ 解包回对象，明细逐处定位。"""
    raw = json.dumps(REPAIRABLE_SCRIPT, ensure_ascii=False)
    repaired, info = _repair_acts_strings(raw)

    assert repaired is not raw, "有修复 ⇒ 必须返回新文本"
    assert info == {"changed": True, "acts_unwrapped": [2], "scenes_unwrapped": {}}
    doc = json.loads(repaired)
    assert doc["acts"][2] == ACT3
    assert isinstance(doc["acts"][2], dict)
    # 中文可读性守恒：重序列化不转义（ensure_ascii=False）
    assert "雨夜矿区" in repaired


def test_double_serialized_scene_element_is_unwrapped() -> None:
    """场级同族：`acts[1].scenes[0]` 是 JSON 字符串 ⇒ 解包，归属记到 `acts[1]`。"""
    repaired, info = _repair_acts_strings(
        json.dumps(REPAIRABLE_SCENES_SCRIPT, ensure_ascii=False)
    )

    assert info == {"changed": True, "acts_unwrapped": [], "scenes_unwrapped": {"acts[1]": [0]}}
    doc = json.loads(repaired)
    assert doc["acts"][1]["scenes"][0] == {"no": 2, "est_seconds": 10}


def test_multiple_repairs_in_one_pass() -> None:
    """多处并发：acts 与 scenes 各一处 ⇒ 一次全修，明细同时记录。"""
    doc = {
        "acts": [
            {"act_no": 1, "scenes": [json.dumps({"no": 1}, ensure_ascii=False)]},
            json.dumps(
                {"act_no": 2, "scenes": [{"no": 2}]}, ensure_ascii=False
            ),
        ]
    }
    repaired, info = _repair_acts_strings(json.dumps(doc, ensure_ascii=False))

    assert info["acts_unwrapped"] == [1]
    assert info["scenes_unwrapped"] == {"acts[0]": [0]}
    assert json.loads(repaired)["acts"][1]["scenes"][0] == {"no": 2}


# ------------------------------------- ② 不可修形态：一律不碰（负向）
@pytest.mark.parametrize(
    "raw",
    [
        # 纯文本（真机第 3 轮现场）
        json.dumps(PLAIN_TEXT_SCRIPT, ensure_ascii=False),
        # 整体不可解析
        "这不是 JSON",
        # 空串
        "",
        # 空白
        "   ",
        # 顶层是数组
        json.dumps([{"acts": []}], ensure_ascii=False),
        # 没有 acts 键
        json.dumps({"title": "雨夜"}, ensure_ascii=False),
        # acts 不是数组
        json.dumps({"acts": "第一幕"}, ensure_ascii=False),
    ],
)
def test_unrepairable_inputs_are_untouched(raw: str) -> None:
    """**负向锁**：解析不了／没有 acts／acts 非数组 ⇒ 原样返回、零修复。"""
    repaired, info = _repair_acts_strings(raw)
    assert repaired == raw, "不可修形态必须原样返回（留给形态闸裁决）"
    assert info is None


@pytest.mark.parametrize(
    "element",
    [
        # JSON 字符串但内容是数组
        json.dumps([1, 2], ensure_ascii=False),
        # JSON 字符串但内容是标量
        "42",
        "null",
        # 二次序列化（字符串里还是字符串）
        json.dumps(json.dumps({"act_no": 3}, ensure_ascii=False), ensure_ascii=False),
        # 不是合法 JSON
        "第三幕：直接写成了字符串",
    ],
)
def test_non_object_string_elements_are_not_unwrapped(element: str) -> None:
    """**负向锁**：元素是字符串、但 `json.loads` 结果不是**对象** ⇒ 不解包。"""
    raw = json.dumps(_script([element]), ensure_ascii=False)
    repaired, info = _repair_acts_strings(raw)
    assert repaired == raw
    assert info is None
    assert json.loads(repaired)["acts"][0] == element, "原元素一字不动"


def test_noop_on_valid_script_returns_identical_text() -> None:
    """合法剧本 ⇒ 原样返回（且是**同一字符串**，不做无谓重序列化）。"""
    raw = json.dumps(VALID_SCRIPT, ensure_ascii=False)
    repaired, info = _repair_acts_strings(raw)
    assert repaired is raw
    assert info is None


def test_deeply_nested_json_string_does_not_escape_recursion_error() -> None:
    """**负向锁（独立 QA 证伪 D1）**：深嵌套 JSON 字符串元素 `json.loads` 抛的是
    `RecursionError`（非 `ValueError` 子类）——不捕会把「修复前可重试的采样失败」
    （形态闸拒字符串 ⇒ 重采）逃逸成整轮硬崩，失败模式反而变差。
    语义＝解析不了就不碰，原样留给形态闸拒。"""
    deep = '{"a":' * 3000 + "1" + "}" * 3000
    raw = json.dumps(_script([deep]), ensure_ascii=False)
    repaired, info = _repair_acts_strings(raw)
    assert repaired == raw
    assert info is None


# ------------------------------------- ③ 端到端：可修 ⇒ 首采即过 ＋ 留痕
def test_repairable_script_passes_on_first_attempt_with_trace() -> None:
    """核心端到端：`acts[2]` 双重序列化 ⇒ 解包后**首采即过形态闸**（零重采），
    留痕可核查「解包发生在哪一处」，下游场号推导正常。"""
    backend = ScriptedBackend([json.dumps(REPAIRABLE_SCRIPT, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)  # ⚠️ 不抛错 ＝ 修复生效

    artifact = rec.artifacts["script"]
    # 文本里的 acts[2] 已是对象形态
    doc = json.loads(artifact["text"])
    assert doc["acts"][2] == ACT3
    assert artifact["artifact_shape_ok"] is True
    # 首采即过：零形态重采
    assert "artifact_shape_retry" not in artifact
    assert len(backend.calls) == 1
    # 修复留痕：逐处定位（noop 不写键、修过必留——本例属「修过必留」）
    assert artifact["acts_repair"] == {
        "changed": True,
        "acts_unwrapped": [2],
        "scenes_unwrapped": {},
    }
    # 告警不静默
    assert any(w.startswith("acts_repair:") for w in artifact.get("merge_warnings", []))
    # 下游可用性：场号推导正常（修复后的文本经得起同一把尺子）
    assert scene_nos_of(doc) == [1, 2, 3]


def test_scene_level_repair_is_recorded_with_owner() -> None:
    """场级修复端到端：明细归属记到 `acts[1]`，首采即过。"""
    backend = ScriptedBackend([json.dumps(REPAIRABLE_SCENES_SCRIPT, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)

    artifact = rec.artifacts["script"]
    assert artifact["acts_repair"] == {
        "changed": True,
        "acts_unwrapped": [],
        "scenes_unwrapped": {"acts[1]": [0]},
    }
    assert artifact["artifact_shape_ok"] is True
    assert scene_nos_of(json.loads(artifact["text"])) == [1, 2, 3]


def test_valid_script_leaves_no_repair_trace_key() -> None:
    """noop 不写键（不污染每次生成）：合法剧本 ⇒ artifact **无** `acts_repair` 键。"""
    backend = ScriptedBackend([json.dumps(VALID_SCRIPT, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)

    assert "acts_repair" not in rec.artifacts["script"]
    assert "acts_repair:" not in "｜".join(
        rec.artifacts["script"].get("merge_warnings", [])
    )


# ------------------------------- ④ 端到端负向：修复不洗白真缺陷
def test_plain_text_act_is_still_rejected() -> None:
    """**负向样本**：`acts[2]` 是纯文本（真机现场）⇒ 照旧被形态闸拒绝，
    原因码／定位串不变——预修复**只修确定可修的**，不扩大放行面。"""
    bad = json.dumps(PLAIN_TEXT_SCRIPT, ensure_ascii=False)
    backend = ScriptedBackend([bad, bad])
    service, repo = _svc(backend)
    rec = _record(repo)

    with pytest.raises(AppError) as ei:
        _gen(service, rec)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert ei.value.details["reason"] == "script_structure_invalid"
    assert ei.value.details["structure_path"] == "acts[2]"
    # 非法产物没入库
    assert "script" not in rec.artifacts


def test_partial_repair_does_not_mask_remaining_defect() -> None:
    """**负向样本（混合）**：acts[1] 可修、acts[2] 纯文本 ⇒ acts[1] 修了，
    但整份产物**仍按 acts[2] 拒**——部分修复不得掩盖其余缺陷。"""
    bad = json.dumps(MIXED_SCRIPT, ensure_ascii=False)
    backend = ScriptedBackend([bad, bad])
    service, repo = _svc(backend)
    rec = _record(repo)

    with pytest.raises(AppError) as ei:
        _gen(service, rec)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert ei.value.details["reason"] == "script_structure_invalid"
    assert ei.value.details["structure_path"] == "acts[2]"
    assert "script" not in rec.artifacts
