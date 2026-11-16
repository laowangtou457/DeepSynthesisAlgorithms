# -*- coding: utf-8 -*-
"""**剧本元素级结构闸**（`ISSUE-094`）：形态闸前移 ＋ fail-fast ＋ 段内重试。

缺陷现场（真机第 3 轮，已核实）
------------------------------
上游剧本 `acts[2]` 是**字符串**时，运行期的两道形态闸**都拦不住**——
它们只判**顶层**形态（可解析 → 形态相符 → 顶层必需键齐备，见
`artifact_contract.check_shape` 的前三层），**不判 `acts[]`／`scenes[]` 的元素类型**。
于是这份非法剧本照常入库，直到下游 `dialogue_service._plan_for_stage()` 调
`segment.plan_scene_segments()` 才炸：`502 上游剧本 acts[2] 不是对象，无法推导逐场调用计划`。
而 `script` 段通常不适用质量门禁（`gate_applies=False` ⇒ `max_attempts=1`）
⇒ 形态闸一旦判失败**一律直接抛、零重试**。

本批落地三件事（项目方裁决，逐条对应用例组）
--------------------------------------------
1. **单点判定**：`segment.script_structure_problems()` 是「剧本结构缺陷」的**唯一**实现
   （`scene_nos_of()` 与 `check_shape()` 都从它取），故 `check_shape` 里**没有第二份口径**
   ⇒ 用例组 ⑤ 用「同源锁」把这层关系钉死（文案与 details 逐字相等）；
2. **前移 ＋ fail-fast**：`check_shape("script", …)` 的第四层元素级结构
   ⇒ 用例组 ①（负向：`acts[2]` 非对象被拒）、②（反向锁：合法剧本不许判坏）、
   ③（回归锁：其它形态零影响）；
3. **段内重试**：`_maybe_generate()` 里形态闸失败改为**可重试**（额度来自
   `shape_gate_max_attempts`，默认 2）⇒ 用例组 ⑥（第一次坏、第二次好 ⇒ 自愈且留痕）
   与 ⑦（两次都坏 ⇒ 如实抛出、尝试次数 2）。

⚠️ **负向验证纪律**（`CFG-007_SCHEMA.md` 文末既有条款）：只跑通过样本**证明不了**闸门有效
——本文件的主用例全部是**坏输入必须被拦住**，且断言的是**原因码与文案**，不是「抛了错就行」。

⚠️ 判据零改动：`prompts/validate_output.py`／交付层判据**一字未动**；本批只把
「元素级结构」这把**下游本来就在用的尺子**搬到上游来用。
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
from app.services import artifact_contract
from app.services.dialogue_service import DialogueService
from app.services.segment import scene_nos_of, script_structure_problems


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


def _script(acts: object) -> dict:
    """契约完备的剧本骨架（`acts` 由用例注入，便于构造各种坏形态）。"""
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


VALID_SCRIPT = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]},
        {"act_no": 3, "scenes": [{"no": 3, "est_seconds": 10}]},
    ]
)

#: 真机第 3 轮的那份坏剧本：`acts[2]` 是**字符串**（不是对象）。
BAD_SCRIPT_ACTS_2_STRING = _script(
    [
        {"act_no": 1, "scenes": [{"no": 1, "est_seconds": 10}]},
        {"act_no": 2, "scenes": [{"no": 2, "est_seconds": 10}]},
        "第三幕：直接写成了字符串",
    ]
)

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


class ScriptedBackend(TextGenerator):
    """按调用次序返回预置文本（**不做任何加工**——闸门要看的正是原始回包）。"""

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
        for piece in ():  # pragma: no cover - 本文件不用流式
            yield piece


def _svc(backend: ScriptedBackend) -> tuple[DialogueService, SessionRepository]:
    prompts = PromptRepository(get_settings().prompts_dir).load()
    repo = SessionRepository()
    return DialogueService(repo, prompts, backend_resolver=lambda: backend), repo


def _record(repo: SessionRepository) -> SessionRecord:
    """待生成剧本的会话：只预置**上游梗概**（其余不塞，避免夹具先占位导致断言失真）。"""
    source = "一只流浪猫在雨夜被人救起"
    rec = repo.create(
        stage=Stage.DRAFT_SCRIPT.value, source_input=source, defaults={"source_input": source}
    )
    rec.artifacts["synopsis"] = {"text": json.dumps(VALID_SYNOPSIS, ensure_ascii=False)}
    return rec


def _gen(service: DialogueService, rec: SessionRecord) -> None:
    asyncio.run(service._maybe_generate(rec, Stage.DRAFT_SCRIPT, dict(rec.defaults)))


# ------------------------------------------------- ① 前移：元素级结构必须被拦住
def test_acts_element_that_is_not_object_is_rejected_with_path() -> None:
    """**核心用例**（`ISSUE-094` 的原始现场）：`acts[2]` 是字符串 ⇒ 形态闸当场拒绝。

    ⚠️ 改造前该产物**完整通过**形态闸（前三层只判顶层形态），直到下游
    `plan_scene_segments()` 才炸——本用例断言的正是「**前移到产出一刻**」。
    """
    verdict = artifact_contract.check_shape(
        "script", json.dumps(BAD_SCRIPT_ACTS_2_STRING, ensure_ascii=False)
    )

    assert verdict.ok is False
    assert verdict.reason == "script_structure_invalid"
    assert verdict.error is not None and "acts[2]" in verdict.error
    # 定位串必须是**元素级**的（不是「产物不合法」这种不可行动的报错）
    assert verdict.error_details["structure_path"] == "acts[2]"
    assert verdict.error_details["structure_problem_count"] >= 1
    # ⚠️ 硬纪律：`error_details` 里**不得**出现 `reason` 键（会覆盖闸门原因码）
    assert "reason" not in verdict.error_details


# ------------------------------------------------------- ② 反向锁：合法剧本不许判坏
def test_valid_script_still_passes_the_fourth_layer() -> None:
    """反向锁：**合法剧本必须照常通过**——闸门只反对结构缺陷，不反对创作内容。

    ⚠️ 这条锁防的是「把闸门写得太严」：一旦合法产物被判坏，链路直接不可用，
    而那种缺陷在只有负向样本的测试里**看不出来**。
    """
    verdict = artifact_contract.check_shape(
        "script", json.dumps(VALID_SCRIPT, ensure_ascii=False)
    )
    assert verdict.ok is True, f"合法剧本被误杀：{verdict.reason}／{verdict.error}"
    assert verdict.reason is None


# --------------------------------------------------- ③ 回归锁：其它形态零影响
def test_other_shapes_are_unaffected_by_the_fourth_layer() -> None:
    """`storyboard`（以及 `synopsis`／`pack`）**不做**元素级判定 ⇒ 行为零改动。"""
    storyboard = artifact_contract.check_shape(
        "storyboard", json.dumps(VALID_STORYBOARD, ensure_ascii=False)
    )
    assert storyboard.ok is True and storyboard.reason is None

    # 元素级判定**只对 script 生效**：同一份「坏 acts」套进别的形态不会被本层判死
    # （它会被「形态不符」等既有层判，属既有行为，不在本批改动面内）。
    assert artifact_contract.element_structure_problems(
        "storyboard", BAD_SCRIPT_ACTS_2_STRING
    ) == []


# ------------------------------- ④ 文案守恒锁：下游报错的一字一句都不得变
def test_scene_nos_of_keeps_the_exact_original_message() -> None:
    """**文案守恒锁**：改造把判定搬了家，但外部可见的报错**必须逐字不变**。

    依据：该文案是 `ISSUE-094` 真机 502 的原文，也是既有排查手册／工单的锚点；
    改造只是「更早报同一句话」，不是「换一句话」。
    """
    with pytest.raises(AppError) as ei:
        scene_nos_of(BAD_SCRIPT_ACTS_2_STRING)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert "上游剧本 acts[2] 不是对象，无法推导逐场调用计划" in ei.value.message
    assert ei.value.details == {"index": 2}


# --------------------------------------------- ⑤ 同源锁：一份口径，两处取用
BAD_SCRIPTS = [
    # 缺 acts[]
    {},
    # acts 为空
    {"acts": []},
    # acts[0] 非对象（原始现场的同族形态）
    {"acts": ["第一幕写成了字符串"]},
    # acts[0] 缺 scenes[]
    {"acts": [{"act_no": 1}]},
    # acts[0].scenes[0] 非对象
    {"acts": [{"scenes": ["第一场写成了字符串"]}]},
    # scenes[0].no 非整数
    {"acts": [{"scenes": [{"no": "一"}]}]},
    # 场号重复
    {"acts": [{"scenes": [{"no": 1}, {"no": 1}]}]},
]


@pytest.mark.parametrize("bad", BAD_SCRIPTS)
def test_structure_problems_and_scene_nos_are_the_same_ruler(bad: dict) -> None:
    """**同源锁**：`script_structure_problems()` 报缺陷 ⟺ `scene_nos_of()` 抛错，
    且**文案与 details 逐字相等**（证明两处取的是同一份判定，不是两份口径）。

    ⚠️ 这条锁是 `ISSUE-094` 的防复发机制：本缺陷的成因正是「上游闸只判顶层、
    下游编排判元素级」——**两把尺子**。只要有人日后在任一侧另写一份，
    这个参数化用例就会红。
    """
    problems = script_structure_problems(bad)
    assert problems, f"该坏输入必须被报出：{bad}"

    raised = False
    try:
        scene_nos_of(bad)  # type: ignore[arg-type]
    except AppError as exc:
        raised = True
        assert exc.code is ErrorCode.GENERATION_FAILED
        # 逐字同源：第一条问题的文案与 details 就是抛错用的那一份
        assert exc.message == problems[0][0]
        assert exc.details == problems[0][1]
    assert raised, f"该坏输入必须让 scene_nos_of 抛错：{bad}"


def test_valid_script_yields_no_problems_and_full_scene_nos() -> None:
    """正向对照：合法剧本 ⇒ 零缺陷 ＋ 场号清单原样返回（含顺序）。"""
    assert script_structure_problems(VALID_SCRIPT) == []
    assert scene_nos_of(VALID_SCRIPT) == [1, 2, 3]


def test_empty_acts_is_a_top_level_issue_not_element_level() -> None:
    """**边界锁**（刻意如此，不是遗漏）：空 `acts[]` 不在形态闸第四层判定。

    理由两层：
    1. 它是**顶层取值**问题（`R6` 要求恰 3 幕，属交付层判据），而 `acts` **键缺失**
       已被第三层 `required` 拦住；元素级判定管的是「元素是不是对象、`.no` 是不是整数」；
    2. 空 `acts[]` 的**下游报错本来就是显式的**（`scene_nos_of` 当场抛
       `缺 acts[]（或为空）`），不存在 `ISSUE-094` 那种「闸门放行、很久之后才炸」的静默洞；
       且既有 20+ 用例以 `acts: []` 手工构造上游夹具，并入本层会越权扩大改动面。
    """
    empty_acts = _script([])
    # 单点判定**照常报出**（它是剧本结构缺陷）
    assert script_structure_problems(empty_acts)
    # 但形态闸第四层**不收**这一条（不是元素级定位键）
    assert artifact_contract.element_structure_problems("script", empty_acts) == []
    assert artifact_contract.check_shape(
        "script", json.dumps(empty_acts, ensure_ascii=False)
    ).ok is True


# ------------------------------------- ⑥ 重试链路：第一次坏、第二次好 ⇒ 自愈
def test_shape_gate_failure_is_retried_and_self_heals() -> None:
    """**核心用例**：`script` 段首次产出 `acts[2]` 非对象 ⇒ 自动重采样，
    第二次合法 ⇒ 正常入库，且**重采留痕**可核查（第几次／原因码／定位串）。

    ⚠️ 改造前该场景的结局是：`max_attempts=1`（`script` 段不适用质量门禁）
    ⇒ 形态闸判出即抛 ⇒ 整链 `502`。本用例断言的正是「这条自愈通路」。
    """
    backend = ScriptedBackend(
        [
            json.dumps(BAD_SCRIPT_ACTS_2_STRING, ensure_ascii=False),
            json.dumps(VALID_SCRIPT, ensure_ascii=False),
        ]
    )
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)  # ⚠️ 不抛错 ＝ 重采后自愈

    artifact = rec.artifacts["script"]
    # 最终入库的是**第二次**那一版（合法剧本）
    assert json.loads(artifact["text"])["acts"] == VALID_SCRIPT["acts"]
    assert artifact["artifact_shape_ok"] is True
    # 重采留痕：1 条，且写明第 1 次尝试因元素级结构失败、坏在 acts[2]
    retry = artifact["artifact_shape_retry"]
    assert retry["attempts"] == 1
    history = retry["attempts_history"]
    assert len(history) == 1
    assert history[0]["attempt"] == 1
    assert history[0]["reason"] == "script_structure_invalid"
    assert history[0]["stage"] == "script"
    assert history[0]["path"] == "acts[2]"
    # 段留痕里必须有 `attempt == 2` 的那一批（可核查「真的重采了」）
    assert any(t.get("attempt") == 2 for t in artifact["segments"]), (
        "段留痕缺少第 2 次尝试——无法举证「重试真的发生了」"
    )
    assert len(backend.calls) == 2


# ------------------------------------- ⑦ 重试用尽：两次都坏 ⇒ 如实抛出
def test_shape_gate_exhausts_retries_then_raises_verbatim() -> None:
    """重试用尽 ⇒ **原样**抛 `GENERATION_FAILED`（原因码不变），并带「试过几次」。

    ⚠️ 不写槽、不推进状态机：非法剧本**不得**作为上游传下去（`ISSUE-094` 的第一纪律）。
    """
    bad = json.dumps(BAD_SCRIPT_ACTS_2_STRING, ensure_ascii=False)
    backend = ScriptedBackend([bad, bad])
    service, repo = _svc(backend)
    rec = _record(repo)

    with pytest.raises(AppError) as ei:
        _gen(service, rec)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    # 闸门原因码不得被覆盖（`script_structure_invalid` 由 `verdict.reason` 带出）
    assert ei.value.details["reason"] == "script_structure_invalid"
    assert ei.value.details["structure_path"] == "acts[2]"
    # 「形态闸尝试过几次」必须能看出来（裁决要求：不得只留一句「失败了」）
    attempts = ei.value.details["shape_attempts"]
    assert len(attempts) == 2, f"应记录 2 次形态闸失败，实际 {len(attempts)}"
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert all(a["reason"] == "script_structure_invalid" for a in attempts)
    # 文案仍是那句原文（改造不改文案）
    assert "上游剧本 acts[2] 不是对象" in ei.value.message
    # 非法产物**没入库**
    assert "script" not in rec.artifacts
    assert len(backend.calls) == 2, "额度用尽即停，不得无限重采"


# ------------------------------------- 附：一次过时不落盘（不污染每次生成）
def test_no_retry_attempt_leaves_no_trace_key() -> None:
    """首轮即合法 ⇒ **不写** `artifact_shape_retry`（同 `amp_norm`／
    `appearance_echo_clean` 的 noop 纪律：不污染每一次生成）。"""
    backend = ScriptedBackend([json.dumps(VALID_SCRIPT, ensure_ascii=False)])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)

    artifact = rec.artifacts["script"]
    assert "artifact_shape_retry" not in artifact
    assert artifact["artifact_shape_ok"] is True
    assert len(backend.calls) == 1


# ------------------- ④′ `acts` 容器类型错（独立 QA 证伪发现，本轮补洞口）
@pytest.mark.parametrize(
    "acts_value",
    ["not-a-list", {"no": 1}, None, 42],
    ids=["str", "dict", "null", "int"],
)
def test_non_list_acts_is_caught_by_the_fourth_layer(acts_value: object) -> None:
    """**洞口回归**：`acts` 键存在但**不是 list** ⇒ 必须被形态闸第四层拦下。

    ⚠️ 这条用例的来历：独立 QA 证伪时发现 `acts: "..."`／`{}`／`null`／`42` 能**穿过**
    第四层（旧实现的过滤只看 details 里的定位键 `index`／`act_index`／`scene_nos`，
    而「类型错」只有 `acts_type`）——即闸门依旧放行、下游 `plan_scene_segments()`
    才炸，正是 `ISSUE-094` 要消灭的形态。修法是把「`acts_type` 存在且 ≠ `list`」
    并入元素级判定（不是新写判据：`acts_type` 本来就由 `script_structure_problems` 产出）。

    断言三条：原因码、定位串（`acts`，不假装知道第几幕）、以及「不许判成通过」。
    """
    doc = _script(acts_value)
    verdict = artifact_contract.check_shape("script", json.dumps(doc, ensure_ascii=False))
    assert verdict.ok is False, f"acts={acts_value!r} 竟通过形态闸（ISSUE-094 复发）"
    assert verdict.reason == "script_structure_invalid", verdict.reason
    assert verdict.error_details.get("structure_path") == "acts", verdict.error_details
    # 单点判定同样报出（同源，不是闸门自己另判一份）
    problems = script_structure_problems(doc)
    assert problems and "acts[]" in problems[0][0]


def test_acts_missing_key_is_still_caught_before_the_fourth_layer() -> None:
    """`acts` **键缺失** ⇒ 在前两层就被拦（不被第四层顺手接走）。

    ⚠️ 实测归属：`acts` 是 `script` 形态的**签名键**（`detect_shape` 见 `acts` 才认作剧本）
    ⇒ 缺键时**第二层「形态相符」**先判 `artifact_shape_mismatch`。实测该骨架去掉 `acts`
    后只剩 `unspecified: []`，按签名表落进 `ledger`（签名键巧合，不是本案关注点）——
    故此处只锁「识别结果不是 `script`」，不把 `ledger` 这个偶然值写死成契约。
    分层归属要可核查：缺签名键＝形态判不出（第二层），类型错＝元素级（第四层）。
    混在一起也能拦住，但「哪一层拦的」就查不出来了。
    """
    doc = _script([])
    doc.pop("acts")
    verdict = artifact_contract.check_shape("script", json.dumps(doc, ensure_ascii=False))
    assert verdict.ok is False
    assert verdict.reason == "artifact_shape_mismatch", verdict.reason
    assert verdict.detected != "script", verdict.detected


# ============ ⑧ 长度截断也走同一条重试路（`ISSUE-090`；只重采坏段）
def test_truncated_segment_is_retried_and_self_heals() -> None:
    """`finish_reason=length` ⇒ **只重采被截断的段**，第二次正常 ⇒ 入库。

    ⚠️ 为什么这条与 `ISSUE-094` 同批：实测 10 轮连跑里 **4 轮有 3 轮**死在截断
    （`script` 整包／`storyboard` 的 `scene:3`／`shot_prompt` 的 `unit:U04`）——
    「判出即抛」把一次可自愈的采样波动升级成整链 502，与 `acts[2]` 是同一类问题。
    ⚠️ 只重跑坏段（`truncated_segments` 精确到段名）而不是整份计划：长产物整份重跑
    要再花 15~20 分钟，坏段通常只占 1/4~1/3。
    """
    good = json.dumps(VALID_SCRIPT, ensure_ascii=False)
    backend = ScriptedBackend([good, good], finish_reasons=["length", "stop"])
    service, repo = _svc(backend)
    rec = _record(repo)

    _gen(service, rec)

    assert len(backend.calls) == 2, "截断后必须重采一次（额度 2）"
    art = rec.artifacts["script"]
    hist = art["artifact_shape_retry"]["attempts_history"]
    assert len(hist) == 1, hist
    assert hist[0]["reason"] == "segment_truncated"
    assert hist[0]["segments"] == ["all"], "重采范围必须精确到坏段"
    # 产物仍是合法剧本（重采成功后照常入库）
    assert art["artifact_shape"] == "script"


def test_truncated_segment_exhausts_quota_then_raises() -> None:
    """两次都截断 ⇒ **原样抛出**（原因码保留、尝试次数可查、非法产物不入库）。"""
    good = json.dumps(VALID_SCRIPT, ensure_ascii=False)
    backend = ScriptedBackend([good, good], finish_reasons=["length", "length"])
    service, repo = _svc(backend)
    rec = _record(repo)

    with pytest.raises(AppError) as ei:
        _gen(service, rec)

    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert ei.value.details["reason"] == "segment_truncated"
    assert len(ei.value.details["shape_attempts"]) == 2
    assert all(a["reason"] == "segment_truncated" for a in ei.value.details["shape_attempts"])
    assert len(backend.calls) == 2, "额度用尽即停，不得无限重采"
    assert "script" not in rec.artifacts, "被截断的产物不得入库"
