"""分段调用的集成验证：`segment` 计划**真的**驱动了 N 次后端调用。

这是 `T-004` 的核心验收点。改造前 `dialogue_service` 只单次 `by_stage()` 调用，
`segment` 变量**根本不进 `variables`** —— 14 镜整包会被静默截断。
本文件用「计数后端」把「是否真的分了段」变成可断言的机器事实。
"""

from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings
from app.inference.base import GenResult, TextGenerator
from app.prompts.loader import PromptRepository
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.schemas.dialogue import Stage
from app.services.dialogue_service import DialogueService, _compact_upstream_json


class RecordingBackend(TextGenerator):
    """按**调用次序**返回预置片段，并记录每次调用的入参。"""

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
        for piece in ():  # pragma: no cover - 集成测试不用流式
            yield piece


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


#: 单元段产物：**必须有贡献**（否则触发分段贡献闸，见 `test_artifact_gate.py`）。
_UNIT_U01 = {"units": [{"unit_id": "U01"}],
             "shots": [{"shot_id": "S01-SH004", "scene_no": 1, "shot_no": 4}]}
_UNIT_U02 = {"units": [{"unit_id": "U02"}],
             "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}]}


def _storyboard(shot_count: int, units: list[str]) -> dict:
    """分镜形态的**契约完备**夹具。

    ⚠️ `ISSUE-042` 起，上游产物必须过形态闸才能进入生成——此前这些夹具只给
    `units`/`shots` 两个键（**其余 8 个必需键全缺**），属「恰好绕开契约的夹具」，
    会把「上游其实不合规」这一事实掩盖掉。现按 `artifact_contract` 的
    `REQUIRED_TOP_KEYS["storyboard"]` 补齐。
    """
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


#: 剧本形态的**契约完备**夹具（同上，供 `shot_prompt` 的双上游之一）。
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


def _make(
    backend: RecordingBackend,
    storyboard: dict,
    *,
    defaults: dict | None = None,
) -> tuple[DialogueService, SessionRecord]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    service = DialogueService(repo, prompts, backend_resolver=lambda: backend)
    record = repo.create(
        stage=Stage.DRAFT_SHOT_PROMPT.value,
        source_input="一只流浪猫在雨夜被人救起",
        defaults=defaults or {},
    )
    record.artifacts["storyboard"] = {"text": json.dumps(storyboard, ensure_ascii=False)}
    record.artifacts["script"] = {"text": json.dumps(_SCRIPT, ensure_ascii=False)}
    return service, record


def _run(service: DialogueService, record: SessionRecord) -> dict:
    asyncio.run(
        service._maybe_generate(record, Stage.DRAFT_SHOT_PROMPT, dict(record.defaults))
    )
    return record.artifacts["shot_prompt"]


# ------------------------------------------------------------------ 大包必分段
def test_large_storyboard_triggers_three_way_split() -> None:
    """8 镜 > 阈值 6 → `package_head` ＋ 逐单元，**共 3 次调用**。"""
    backend = RecordingBackend(
        [_HEAD, {"units": [{"unit_id": "U01"}], "shots": [{"shot_id": "S01-SH004", "scene_no": 1, "shot_no": 4}]},
         {"units": [{"unit_id": "U02"}], "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}]}]
    )
    service, record = _make(backend, _storyboard(8, ["U01", "U02"]))
    artifact = _run(service, record)

    assert artifact["segment_plan"] == ["package_head", "unit:U01", "unit:U02"]
    assert len(backend.calls) == 3, "`segment` 计划必须真的驱动 3 次后端调用"


def test_merge_orders_shots_even_when_segments_arrive_out_of_order(monkeypatch) -> None:
    """合并结果按镜序重排（交付规范 §3.7），不依赖分段到达次序。

    ⚠️ 本例断言的是**合并排序**语义：分段只回 2 镜而上游有 8 镜，裁决甲的
    守恒兜底（`_reconcile_pack_conservation`）会再补 6 镜占位 ⇒ 为隔离本例
    断言面，临时关闭 `pack_conservation_fill`（守恒兜底有独立测试覆盖）。
    """
    monkeypatch.setenv("APP_PACK_CONSERVATION_FILL", "false")
    get_settings.cache_clear()
    backend = RecordingBackend(
        [_HEAD, {"units": [{"unit_id": "U01"}], "shots": [{"shot_id": "S01-SH004", "scene_no": 1, "shot_no": 4}]},
         {"units": [{"unit_id": "U02"}], "shots": [{"shot_id": "S01-SH001", "scene_no": 1, "shot_no": 1}]}]
    )
    service, record = _make(backend, _storyboard(8, ["U01", "U02"]))
    artifact = _run(service, record)

    merged = json.loads(artifact["text"])
    assert [s["shot_id"] for s in merged["shots"]] == ["S01-SH001", "S01-SH004"]
    assert [u["unit_id"] for u in merged["units"]] == ["U01", "U02"]
    assert merged["schema_version"] == "2.3.0"


def test_every_segment_call_carries_the_output_contract_schema() -> None:
    """受约束解码：**每一次**分段调用都必须带 schema（不是只有首段）。"""
    backend = RecordingBackend([_HEAD, _UNIT_U01, _UNIT_U02])
    service, record = _make(backend, _storyboard(8, ["U01", "U02"]))
    artifact = _run(service, record)

    assert artifact["constrained_decoding"] is True
    assert all(call["schema"] is not None for call in backend.calls)
    schema = backend.calls[0]["schema"]
    assert schema["properties"]["schema_version"]["const"] == "2.3.0"


def test_segment_trace_records_each_call_for_audit() -> None:
    """分段留痕：每段的段名、字符数、摘要、结束原因都要可回溯。"""
    backend = RecordingBackend([_HEAD, _UNIT_U01, _UNIT_U02])
    service, record = _make(backend, _storyboard(8, ["U01", "U02"]))
    artifact = _run(service, record)

    trace = artifact["segments"]
    assert [t["segment"] for t in trace] == ["package_head", "unit:U01", "unit:U02"]
    assert all(t["chars"] > 0 and len(t["digest"]) == 12 for t in trace)
    assert artifact["usage"]["total_tokens"] == sum(
        t and 15 for t in trace
    )  # 每段 mock 固定 10+5


# ------------------------------------------------------------------ 小包不分段
def test_small_storyboard_stays_single_call(monkeypatch) -> None:
    """≤6 镜走整包：1 次调用，产物直接取用（不合并）。

    ⚠️ 同上：本例断言「整包直取、零合并告警」，而空 `shots` 会触发裁决甲的
    守恒兜底（补 4 镜占位＋留痕告警）⇒ 临时关闭 `pack_conservation_fill` 隔离断言面。
    """
    monkeypatch.setenv("APP_PACK_CONSERVATION_FILL", "false")
    get_settings.cache_clear()
    backend = RecordingBackend([{"schema_version": "2.3.0", "meta": {}, "style_bible": {}, "units": [], "shots": [], "aigc_meta": {}}])
    service, record = _make(backend, _storyboard(4, ["U01"]))
    artifact = _run(service, record)

    assert artifact["segment_plan"] == ["all"]
    assert len(backend.calls) == 1
    assert "merge_warnings" not in artifact


# ------------------------------------------------------------------ 显式覆盖
def test_explicit_all_forces_single_call_on_large_storyboard() -> None:
    """客户显式指定 `segment=all` 时尊重其选择（模板语义：强制整包）。"""
    backend = RecordingBackend([_HEAD])
    service, record = _make(
        backend, _storyboard(14, ["U01", "U02", "U03"]), defaults={"segment": "all"}
    )
    artifact = _run(service, record)

    assert artifact["segment_plan"] == ["all"]
    assert len(backend.calls) == 1


def test_auto_over_threshold_without_units_fails_loudly() -> None:
    """上游缺 `units[]` 且镜数超阈值 → **显式失败**，不静默退回整包。"""
    import pytest

    from app.core.errors import AppError, ErrorCode

    backend = RecordingBackend([_HEAD])
    service, record = _make(backend, _storyboard(14, []))
    with pytest.raises(AppError) as ei:
        _run(service, record)
    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert len(backend.calls) == 0, "计划阶段就应失败，不应发起任何调用"


# ------------------------------- 上游输入体积：紧凑化（`ISSUE-037` 方案 D 的服务层一半）
def test_compact_upstream_json_is_whitespace_only() -> None:
    """紧凑化**只去空白**：解析后与原文**完全相等**（键序、键值、精度一律不变）。"""
    raw = json.dumps(
        {"b": 1, "a": [1, 2, {"c": "中文"}], "d": 1.5, "e": None, "f": True},
        ensure_ascii=False,
        indent=2,
    )
    compacted, info = _compact_upstream_json(raw)

    assert info["changed"] == 1
    assert info["chars_before"] == len(raw)
    assert info["chars_after"] == len(compacted) < len(raw)
    assert json.loads(compacted) == json.loads(raw)
    assert list(json.loads(compacted)) == list(json.loads(raw)), "键序不得改变"
    assert "中文" in compacted, "中文不得被转义（ensure_ascii=False）"


def test_compact_upstream_json_tolerates_fence_and_prose() -> None:
    """围栏与前后缀说明文字按 `parse_json_object` 的**既有口径**容忍（不另立一套）。"""
    raw = '好的，结果如下：\n```json\n{"a":  1,\n "b": [1, 2]}\n```\n'
    compacted, info = _compact_upstream_json(raw)

    assert info["changed"] == 1
    assert json.loads(compacted) == {"a": 1, "b": [1, 2]}


def test_compact_upstream_json_returns_original_when_unparsable() -> None:
    """解析失败**原样返回** —— 体积优化**不得**成为新的失败点。"""
    raw = "这不是 JSON，只是一段说明文字"
    compacted, info = _compact_upstream_json(raw)

    assert compacted == raw
    assert info["changed"] == 0


def test_compact_upstream_json_handles_empty_and_non_string() -> None:
    for raw in ("", "   ", None, 123):  # type: ignore[list-item]
        compacted, info = _compact_upstream_json(raw)  # type: ignore[arg-type]
        assert compacted == raw
        assert info["changed"] == 0


def test_compaction_shrinks_prompt_without_touching_upstream_artifact() -> None:
    """端到端：紧凑化只作用于「交给模型的变量」，**会话内的上游产物一字未改**。"""
    storyboard = _storyboard(2, ["U01"])
    backend = RecordingBackend([_HEAD])
    service, record = _make(backend, storyboard)
    before = record.artifacts["storyboard"]["text"]

    _run(service, record)

    prompt = backend.calls[0]["prompt"]
    assert json.dumps(storyboard, ensure_ascii=False, separators=(",", ":")) in prompt
    assert before not in prompt, "prompt 中不应再出现未压缩的上游原文"
    assert record.artifacts["storyboard"]["text"] == before, "会话内产物不得被改动"


def test_compaction_can_be_disabled_by_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """配置位可关断（用于「原文即所见」的对照量测）——关断时回去的是**原文**。"""
    monkeypatch.setenv("APP_PROMPT_COMPACT_UPSTREAM", "false")
    get_settings.cache_clear()
    try:
        storyboard = _storyboard(2, ["U01"])
        backend = RecordingBackend([_HEAD])
        service, record = _make(backend, storyboard)
        before = record.artifacts["storyboard"]["text"]

        _run(service, record)

        assert before in backend.calls[0]["prompt"]
    finally:
        get_settings.cache_clear()


# ------------------------------------------------- `丙`（2026-11-07 裁决）：合并凑数检出 → 可重试
def test_inject_merge_dup_verdict_marks_not_ok_and_retryable() -> None:
    from app.services.dialogue_service import _inject_merge_dup_verdict
    from app.services.quality_gate import QualityVerdict

    verdict = QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=True,
        engine_checks=10, engine_errors=[], engine_warnings=[],
        pack_blocks=[], pack_warnings=[], retryable=[], non_retryable=[],
        enforced=False,
    )
    out = _inject_merge_dup_verdict(
        verdict, ["merge.shot_dup_in_segment｜分镜「S01-SH002」在第 2 段内重复出现 2 次"]
    )
    assert out.ok is False
    assert len(out.retryable) == 1
    assert "S01-SH002" in out.retryable[0]
    assert "merge.shot_dup_in_segment" in out.retryable[0]


def test_inject_merge_dup_verdict_preserves_existing_retryable() -> None:
    from app.services.dialogue_service import _inject_merge_dup_verdict
    from app.services.quality_gate import QualityVerdict

    verdict = QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=False,
        engine_checks=10, engine_errors=["shot_prompt · R34 …"], engine_warnings=[],
        pack_blocks=[], pack_warnings=[], retryable=["shot_prompt · R34 …"],
        non_retryable=[], enforced=False,
    )
    out = _inject_merge_dup_verdict(verdict, ["merge.shot_dup_in_segment｜…"])
    assert out.retryable[0] == "shot_prompt · R34 …"
    assert out.retryable[1].startswith("merge.shot_dup_in_segment｜")


# ------------------------------------------------- `丙`（2026-11-07 裁决）：合并凑数检出 → 可重试
def test_inject_merge_dup_verdict_marks_not_ok_and_retryable() -> None:
    from app.services.dialogue_service import _inject_merge_dup_verdict
    from app.services.quality_gate import QualityVerdict

    verdict = QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=True,
        engine_checks=10, engine_errors=[], engine_warnings=[],
        pack_blocks=[], pack_warnings=[], retryable=[], non_retryable=[],
        enforced=False,
    )
    out = _inject_merge_dup_verdict(
        verdict, ["merge.shot_dup_in_segment｜分镜「S01-SH002」在第 2 段内重复出现 2 次"]
    )
    assert out.ok is False
    assert len(out.retryable) == 1
    assert "S01-SH002" in out.retryable[0]
    assert "merge.shot_dup_in_segment" in out.retryable[0]


def test_inject_merge_dup_verdict_preserves_existing_retryable() -> None:
    from app.services.dialogue_service import _inject_merge_dup_verdict
    from app.services.quality_gate import QualityVerdict

    verdict = QualityVerdict(
        stage="shot_prompt", shape="pack", checked=True, ok=False,
        engine_checks=10, engine_errors=["shot_prompt · R34 …"], engine_warnings=[],
        pack_blocks=[], pack_warnings=[], retryable=["shot_prompt · R34 …"],
        non_retryable=[], enforced=False,
    )
    out = _inject_merge_dup_verdict(verdict, ["merge.shot_dup_in_segment｜…"])
    assert out.retryable[0] == "shot_prompt · R34 …"
    assert out.retryable[1].startswith("merge.shot_dup_in_segment｜")


# ------------------------------------------- `ISSUE-063`／裁决 6：外观锚逐场分布留痕探测
def _sb_two_scenes() -> str:
    import json as _json

    return _json.dumps(
        {
            "shots": [
                # 场 1：两镜都重述了外观锚（「银色短发」3-gram 命中）
                {"shot_id": "S01-SH001", "scene_no": 1,
                 "action": {"start": "银色短发的少女抬头", "change": "", "end": ""}},
                {"shot_id": "S01-SH002", "scene_no": 1,
                 "action": {"start": "她甩了甩银色短发", "change": "", "end": ""}},
                # 场 2：零重述
                {"shot_id": "S02-SH001", "scene_no": 2,
                 "action": {"start": "她走进教室", "change": "", "end": ""}},
            ]
        },
        ensure_ascii=False,
    )


_SCRIPT_WITH_ANCHOR = '{"characters": [{"appearance_lock_zh": "银色短发、蓝色眼睛"}]}'


def test_anchor_echo_probe_reports_per_scene_distribution() -> None:
    from app.services.dialogue_service import _probe_storyboard_anchor_echo

    out = _probe_storyboard_anchor_echo(_sb_two_scenes(), _SCRIPT_WITH_ANCHOR)
    assert out is not None and out["anchors"] == 1
    rows = {r["scene_no"]: r for r in out["scenes"]}
    assert rows["1"]["echo_shots"] == 2 and rows["1"]["echo_rate"] == 1.0
    assert rows["2"]["echo_shots"] == 0 and rows["2"]["echo_rate"] == 0.0
    assert rows["1"]["anchors_touched"] == ["characters[0].appearance_lock_zh"]
    assert out["spread"]["echo_rate_min"] == 0.0
    assert out["spread"]["echo_rate_max"] == 1.0


def test_anchor_echo_probe_not_applicable_without_script() -> None:
    from app.services.dialogue_service import _probe_storyboard_anchor_echo

    assert _probe_storyboard_anchor_echo(_sb_two_scenes(), None) is None
    assert _probe_storyboard_anchor_echo(_sb_two_scenes(), "不是 json") is None


def test_anchor_echo_probe_notes_when_upstream_has_no_anchors() -> None:
    from app.services.dialogue_service import _probe_storyboard_anchor_echo

    out = _probe_storyboard_anchor_echo(_sb_two_scenes(), '{"characters": []}')
    assert out is not None and out["anchors"] == 0 and "note" in out


# ---------------------------------------------------------------------------
# `T-101` 裁决甲（2026-11-07）：`_reconcile_pack_conservation` 镜集合守恒兜底
# ---------------------------------------------------------------------------

_UPSTREAM_SB = json.dumps(
    {
        "style_ref": "cell_shading",
        "shots": [
            {
                "shot_id": "S01-SH001", "unit_id": "U01", "scene_no": 1, "shot_no": 1,
                "shot_size": "wide", "camera": {"move": "push_in"}, "duration_ms": 5000,
                "action": {"start": "a", "change": "b", "end": "c"},
                "shot_language": {"composition": "x"}, "character_refs": ["c1"], "prop_refs": [],
            },
            {
                "shot_id": "S01-SH002", "unit_id": "U01", "scene_no": 1, "shot_no": 2,
                "shot_size": "full", "camera": {"move": "push_in"}, "duration_ms": 5000,
                "action": {"start": "d", "change": "", "end": "f"},
                "shot_language": {"composition": "y"}, "character_refs": [], "prop_refs": [],
            },
        ],
    },
    ensure_ascii=False,
)

_PACK_MISSING_ONE = json.dumps(
    {
        "units": [{"unit_id": "U01", "shot_ids": ["S01-SH001", "S01-SH002"]}],
        "shots": [
            {
                "shot_id": "S01-SH001", "unit_id": "U01", "scene_no": 1, "shot_no": 1,
                "shot_size": "wide", "camera": {"move": "push_in"}, "duration_ms": 5000,
                "prompt_zh": "已有", "prompt_en": "The camera pushes in.",
                "action": {"start": "a", "change": "b", "end": "c"},
                "shot_language": {"composition": "x"}, "style_ref": "cell_shading",
                "character_refs": ["c1"], "prop_refs": [],
            }
        ],
    },
    ensure_ascii=False,
)


def test_conservation_fill_repairs_missing_upstream_shot() -> None:
    from app.services.dialogue_service import _reconcile_pack_conservation

    new_text, fills = _reconcile_pack_conservation(
        "shot_prompt", _PACK_MISSING_ONE, {"storyboard": _UPSTREAM_SB}
    )
    assert len(fills) == 1 and "S01-SH002" in fills[0]
    assert fills[0].startswith("merge.shot_conservation_fill｜")
    doc = json.loads(new_text)
    ids = [s["shot_id"] for s in doc["shots"]]
    assert ids == ["S01-SH001", "S01-SH002"]  # 上游镜序追加
    fill = doc["shots"][1]
    # 机械承继字段照抄上游（与承继层「一字不得改」同口径）
    assert fill["camera"] == {"move": "push_in"} and fill["duration_ms"] == 5000
    assert fill["shot_size"] == "full" and fill["shot_language"] == {"composition": "y"}
    assert fill["style_ref"] == "cell_shading"  # 取上游 storyboard 顶层
    # prompt_zh 由 action 派生（空段被跳过）；prompt_en 留空如实待判；notes 明写占位
    assert fill["prompt_zh"] == "d；f"
    assert fill["prompt_en"] == ""
    assert "服务层构造占位" in fill["notes"] and "裁决甲" in fill["notes"]
    # 已有镜一字不动
    assert doc["shots"][0]["prompt_zh"] == "已有"
    # 单元悬空引用随补镜解除
    assert all(r in set(ids) for r in doc["units"][0]["shot_ids"])


def test_conservation_fill_noop_when_complete() -> None:
    from app.services.dialogue_service import _reconcile_pack_conservation

    complete = json.dumps(
        json.loads(_PACK_MISSING_ONE) | {"shots": json.loads(_PACK_MISSING_ONE)["shots"] + [
            {
                "shot_id": "S01-SH002", "unit_id": "U01", "scene_no": 1, "shot_no": 2,
                "shot_size": "full", "camera": {"move": "push_in"}, "duration_ms": 5000,
                "prompt_zh": "x", "prompt_en": "y", "action": {}, "shot_language": {},
                "style_ref": "cell_shading", "character_refs": [], "prop_refs": [],
            }
        ]},
        ensure_ascii=False,
    )
    new_text, fills = _reconcile_pack_conservation(
        "shot_prompt", complete, {"storyboard": _UPSTREAM_SB}
    )
    assert fills == [] and new_text == complete  # 原样返回（不重新序列化）


def test_conservation_fill_noop_for_other_stage_and_missing_upstream() -> None:
    from app.services.dialogue_service import _reconcile_pack_conservation

    text, fills = _reconcile_pack_conservation(
        "storyboard", _PACK_MISSING_ONE, {"storyboard": _UPSTREAM_SB}
    )
    assert fills == [] and text == _PACK_MISSING_ONE
    text, fills = _reconcile_pack_conservation("shot_prompt", _PACK_MISSING_ONE, None)
    assert fills == [] and text == _PACK_MISSING_ONE
    text, fills = _reconcile_pack_conservation(
        "shot_prompt", _PACK_MISSING_ONE, {"storyboard": "不是 json"}
    )
    assert fills == [] and text == _PACK_MISSING_ONE


def test_conservation_fill_respects_switch(monkeypatch) -> None:
    from app.services.dialogue_service import _reconcile_pack_conservation

    monkeypatch.setenv("APP_PACK_CONSERVATION_FILL", "false")
    get_settings.cache_clear()
    try:
        text, fills = _reconcile_pack_conservation(
            "shot_prompt", _PACK_MISSING_ONE, {"storyboard": _UPSTREAM_SB}
        )
        assert fills == [] and text == _PACK_MISSING_ONE
    finally:
        monkeypatch.delenv("APP_PACK_CONSERVATION_FILL")
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# `甲` v1.1（2026-11-07 `DEV-20261107-006`，r4 收口实证驱动）：
# 镜序重排（R31 位置比对）＋ 层间形态字段不照抄（R32/R33）
# ---------------------------------------------------------------------------

_UPSTREAM_SB_V2 = json.dumps(
    {
        "style_ref": "cell_shading",
        "shots": [
            {
                "shot_id": "S01-SH001", "unit_id": "U01", "scene_no": 1, "shot_no": 1,
                "shot_size": "wide", "camera": {"move": "push_in"}, "duration_ms": 5000,
                "action": {"start": "a", "change": "b", "end": "c"},
                "shot_language": {"composition": "x"}, "character_refs": [], "prop_refs": [],
                "lighting": "低饱和光+昏暗灯光",  # 上游分镜层＝散文形态（R32 在 shot_prompt 层要 code）
                "dialogue": "上游层的台词散文", "sfx": "上游音效说明",
                "transition_in": "上游转场说明",
            },
            {
                "shot_id": "S01-SH002", "unit_id": "U01", "scene_no": 1, "shot_no": 2,
                "shot_size": "full", "camera": {"move": "pull_out"}, "duration_ms": 4000,
                "action": {"start": "d", "change": "", "end": "f"},
                "shot_language": {"composition": "y"}, "character_refs": [], "prop_refs": [],
                "lighting": "顶光",
            },
            {
                "shot_id": "S01-SH003", "unit_id": "U01", "scene_no": 1, "shot_no": 3,
                "shot_size": "close", "camera": {"move": "static"}, "duration_ms": 3000,
                "action": {"start": "g", "change": "h", "end": "i"},
                "shot_language": {"composition": "z"}, "character_refs": [], "prop_refs": [],
                "lighting": "侧光",
            },
        ],
    },
    ensure_ascii=False,
)


def _pack_with(shots: list[dict]) -> str:
    return json.dumps({"units": [], "shots": shots}, ensure_ascii=False)


def test_conservation_fill_reorders_to_upstream_sequence() -> None:
    """v1.1：占位镜按**上游位置**插入（非尾部追加）——R31 是位置 zip 比对。"""
    from app.services.dialogue_service import _reconcile_pack_conservation

    # 本层缺中间镜 S01-SH002（r4 on#1 实战形态：恒缺 U01 第三镜的同类）
    pack = _pack_with([
        {
            "shot_id": "S01-SH001", "unit_id": "U01", "scene_no": 1, "shot_no": 1,
            "shot_size": "wide", "camera": {"move": "push_in"}, "duration_ms": 5000,
            "prompt_zh": "已有1", "prompt_en": "e1", "action": {},
            "shot_language": {}, "style_ref": "cell_shading",
            "character_refs": [], "prop_refs": [],
        },
        {
            "shot_id": "S01-SH003", "unit_id": "U01", "scene_no": 1, "shot_no": 3,
            "shot_size": "close", "camera": {"move": "static"}, "duration_ms": 3000,
            "prompt_zh": "已有3", "prompt_en": "e3", "action": {},
            "shot_language": {}, "style_ref": "cell_shading",
            "character_refs": [], "prop_refs": [],
        },
    ])
    new_text, fills = _reconcile_pack_conservation(
        "shot_prompt", pack, {"storyboard": _UPSTREAM_SB_V2}
    )
    assert len(fills) == 1
    ids = [s["shot_id"] for s in json.loads(new_text)["shots"]]
    assert ids == ["S01-SH001", "S01-SH002", "S01-SH003"]  # 上游序，非 [1,3,2]


def test_conservation_fill_omits_cross_layer_expression_fields() -> None:
    """v1.1：层间形态不同的表达层字段（lighting/dialogue/sfx/transition_*）不照抄。

    r4 on#1 实证：照抄上游散文 lighting 触发 R32 LIGHTING_VOCAB＋R33
    PACK_NO_EMPTY_STRING（R33 自己的规则＝「留空须省略键」）。
    """
    from app.services.dialogue_service import _reconcile_pack_conservation

    pack = _pack_with([
        {
            "shot_id": "S01-SH002", "unit_id": "U01", "scene_no": 1, "shot_no": 2,
            "shot_size": "full", "camera": {"move": "pull_out"}, "duration_ms": 4000,
            "prompt_zh": "已有", "prompt_en": "e", "action": {},
            "shot_language": {}, "style_ref": "cell_shading",
            "character_refs": [], "prop_refs": [],
        },
    ])
    new_text, fills = _reconcile_pack_conservation(
        "shot_prompt", pack, {"storyboard": _UPSTREAM_SB_V2}
    )
    assert len(fills) == 2  # 缺 SH001 与 SH003
    shots = {s["shot_id"]: s for s in json.loads(new_text)["shots"]}
    for sid in ("S01-SH001", "S01-SH003"):
        for banned in ("lighting", "dialogue", "sfx", "transition_in", "transition_out"):
            assert banned not in shots[sid], f"{sid} 不应含 {banned}"
    # 两层同形态的机械字段仍照抄
    assert shots["S01-SH001"]["camera"] == {"move": "push_in"}
    assert shots["S01-SH001"]["duration_ms"] == 5000
