"""`package_head` 段级采样收紧（`ISSUE-084` 改判后 B3）。

背景（`DEV-20261113-006`）：r6 跑测中 `package_head` 段偶发**真跑满 12288
tokens** 致整轮作废（≈28 分钟/轮），而该段正常产出仅 ≈5,319 tokens
（`artifacts_t086_units_smoke` 段级留痕）⇒ 呈「退化 ramble」倾向。B3 的收口
只在**该段**下调 `temperature` 并以 `max_tokens` 封顶做快速失败，不动分段
编排、不动模板正文、不动判据。

本文件把收紧逻辑当**纯函数**测（`_package_head_sampling`，不必起服务），
再补一条端到端断言：`package_head` 调用带收紧后的参数，`unit:*` 调用
**逐字保持**模板采样（`SW-007` 的 0.7 只约束镜头创意正文，不受 B3 影响）。
"""

from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings
from app.inference.base import GenParams, GenResult, TextGenerator
from app.prompts.loader import PromptRepository
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.schemas.dialogue import Stage
from app.services.dialogue_service import (
    _GENERATE_ON,
    DialogueService,
    _package_head_sampling,
    _params_of,
)

#: 模板现值（`TPL-009_shot_prompt_v1.yaml`）：B3 的前提。
#: 若模板采样调整，本文件的两处期望值须随之更新——否则 B3 的收紧语义失去意义。
_TP_TEMPERATURE = 0.7
_TP_MAX_TOKENS = 12288

#: 该段**正常**产出（`artifacts_t086_units_smoke` 实测 ≈5,319 tokens）。
#: 封顶必须显著高于它，否则会把正常轮次推进「快速失败」制造假截断。
_NORMAL_COMPLETION_TOKENS = 5319


# --------------------------------------------------------------- 纯函数：收紧
def test_package_head_cools_down_and_caps_tokens() -> None:
    """基线场景：0.7 → 0.4、12288 → 8192。"""
    tightened = _package_head_sampling(
        GenParams(temperature=_TP_TEMPERATURE, max_tokens=_TP_MAX_TOKENS)
    )

    assert tightened.temperature == 0.4
    assert tightened.max_tokens == 8192


def test_cap_stays_above_normal_completion() -> None:
    """封顶 8192 **高于**该段正常产出 ≈5.3K——正常轮次不该被 502 截断。"""
    tightened = _package_head_sampling(
        GenParams(temperature=_TP_TEMPERATURE, max_tokens=_TP_MAX_TOKENS)
    )

    assert tightened.max_tokens > _NORMAL_COMPLETION_TOKENS
    # 且确实低于原上限：否则「快速失败」没发生，收口等于没做。
    assert tightened.max_tokens < _TP_MAX_TOKENS


def test_other_sampling_fields_are_untouched() -> None:
    """只动两个字段：`top_p`／`top_k`／`repetition_penalty`／`stop` 原样。"""
    base = GenParams(
        temperature=_TP_TEMPERATURE,
        top_p=0.85,
        top_k=40,
        max_tokens=_TP_MAX_TOKENS,
        repetition_penalty=1.1,
        stop=("</json>",),
    )
    tightened = _package_head_sampling(base)

    assert tightened.top_p == 0.85
    assert tightened.top_k == 40
    assert tightened.repetition_penalty == 1.1
    assert tightened.stop == ("</json>",)


def test_original_params_are_not_mutated() -> None:
    """`GenParams` 是 frozen dataclass：收紧返回**新对象**，入参不得被改写。

    这一点很关键——`unit:*` 段复用的是同一个模板采样解析结果，若就地改写，
    收紧会「泄漏」到镜头正文段（正是 B3 明令不能动的部分）。
    """
    base = GenParams(temperature=_TP_TEMPERATURE, max_tokens=_TP_MAX_TOKENS)
    _ = _package_head_sampling(base)

    assert base.temperature == _TP_TEMPERATURE
    assert base.max_tokens == _TP_MAX_TOKENS


# --------------------------------------------------------------- 纯函数：min 语义
def test_already_cooler_temperature_is_not_raised() -> None:
    """`temperature` 已低于阈值 ⇒ **不放大**（取 min）。"""
    tightened = _package_head_sampling(
        GenParams(temperature=0.3, max_tokens=_TP_MAX_TOKENS)
    )

    assert tightened.temperature == 0.3


def test_already_smaller_token_cap_is_not_raised() -> None:
    """`max_tokens` 已低于阈值 ⇒ **不放大**（取 min）。"""
    tightened = _package_head_sampling(
        GenParams(temperature=_TP_TEMPERATURE, max_tokens=4096)
    )

    assert tightened.max_tokens == 4096


def test_values_exactly_at_threshold_stay_put() -> None:
    """边界：恰好等于阈值时是恒等变换（幂等）。"""
    base = GenParams(temperature=0.4, max_tokens=8192)
    tightened = _package_head_sampling(base)

    assert tightened == base
    assert _package_head_sampling(tightened) == tightened, "收紧必须幂等"


# ------------------------------------------------ 端到端：只有头部段被收紧
class _RecordingBackend(TextGenerator):
    """按调用次序返回预置片段，并记录每次调用的入参。"""

    name = "recording"
    version = "0.1.0"

    def __init__(self, parts: list[dict] | None = None) -> None:
        self.parts = parts or []
        self.calls: list[dict] = []

    async def generate(self, prompt, params, json_schema=None) -> GenResult:  # type: ignore[no-untyped-def]
        index = len(self.calls)
        self.calls.append({"prompt": prompt, "schema": json_schema, "params": params})
        payload = self.parts[index] if index < len(self.parts) else {}
        return GenResult(
            text=json.dumps(payload, ensure_ascii=False),
            prompt_tokens=10,
            completion_tokens=5,
        )

    async def stream(self, prompt, params, json_schema=None):  # type: ignore[no-untyped-def]
        for piece in ():  # pragma: no cover - 本文件不测流式
            yield piece


#: 头部段产物（`units`／`shots` 由段级 schema 上限为 0 强制为空）。
_HEAD = {
    "schema_version": "2.3.0",
    "meta": {"pack_id": "AC-PK-20261015-ABCD1234"},
    "style_bible": {"style_id": "ST-01"},
    "characters": [{"character_id": "CHR-01"}],
    "props": [],
    "forbidden_items": [],
    "aigc_meta": {"ProduceID": "AC-PK-20261015-ABCD1234"},
    "units": [],
    "shots": [],
}

#: 单元段产物：**必须有贡献**（否则触发分段贡献闸）。
_UNIT_U01 = {
    "units": [{"unit_id": "U01"}],
    "shots": [{"shot_id": "S01-SH004", "scene_no": 1, "shot_no": 4}],
}
_UNIT_U02 = {
    "units": [{"unit_id": "U02"}],
    "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}],
}


def _storyboard(shot_count: int, units: list[str]) -> dict:
    """分镜形态的**契约完备**夹具（10 个必需键齐备）。"""
    return {
        "title": "雨夜",
        "genre": "剧情",
        "style_ref": "ST-01",
        "aspect_ratio_default": "16:9",
        "total_duration_ms": 0,
        "units": [{"unit_id": u} for u in units],
        "shots": [
            {"shot_id": f"S01-SH{i:03d}", "scene_no": 1, "shot_no": i}
            for i in range(1, shot_count + 1)
        ],
        "forbidden_items": [],
        "unspecified": [],
        "quality_gate": {},
    }


#: 剧本形态的契约完备夹具（`shot_prompt` 的双上游之一）。
_SCRIPT: dict = {
    "title": "雨夜",
    "logline": "一只流浪猫在雨夜被人救起",
    "genre": "剧情",
    "style_bible": {"style_id": "ST-01"},
    "characters": [],
    "props": [],
    "acts": [],
    "forbidden_items": [],
    "total_est_seconds": 0,
    "unspecified": [],
}


def _make(backend: _RecordingBackend, storyboard: dict) -> tuple[DialogueService, SessionRecord]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    service = DialogueService(repo, prompts, backend_resolver=lambda: backend)
    record = repo.create(
        stage=Stage.DRAFT_SHOT_PROMPT.value,
        source_input="一只流浪猫在雨夜被人救起",
        defaults={},
    )
    record.artifacts["storyboard"] = {"text": json.dumps(storyboard, ensure_ascii=False)}
    record.artifacts["script"] = {"text": json.dumps(_SCRIPT, ensure_ascii=False)}
    return service, record


def test_only_package_head_call_is_tightened_end_to_end() -> None:
    """3 次调用中：`package_head` 用收紧参数，`unit:*` **逐字**用模板采样。"""
    backend = _RecordingBackend([_HEAD, _UNIT_U01, _UNIT_U02])
    service, record = _make(backend, _storyboard(8, ["U01", "U02"]))

    asyncio.run(
        service._maybe_generate(record, Stage.DRAFT_SHOT_PROMPT, dict(record.defaults))
    )

    artifact = record.artifacts["shot_prompt"]
    assert artifact["segment_plan"] == ["package_head", "unit:U01", "unit:U02"]
    assert len(backend.calls) == 3

    # 服务层用**模板阶段名**（`_GENERATE_ON` 的第二元）取模板，与产物键不同名。
    tpl_stage = _GENERATE_ON[Stage.DRAFT_SHOT_PROMPT][1]
    template = service.prompts.by_stage(tpl_stage)
    base = _params_of(template.sampling)
    assert base.temperature == _TP_TEMPERATURE, "模板采样漂移 ⇒ 本文件的 B3 前提需重估"
    assert base.max_tokens == _TP_MAX_TOKENS

    head_params = backend.calls[0]["params"]
    assert head_params.temperature == 0.4
    assert head_params.max_tokens == 8192

    for index, segment in ((1, "unit:U01"), (2, "unit:U02")):
        unit_params = backend.calls[index]["params"]
        assert unit_params == base, f"{segment} 必须原样使用模板采样（`SW-007` 的 0.7）"
        assert unit_params.temperature == _TP_TEMPERATURE
