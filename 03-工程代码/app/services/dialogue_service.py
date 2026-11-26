"""任务对话编排服务（SW-001 状态机 · SW-002 对话式修改 · SW-003 确认门控）。

服务层纪律（ARCH-003 §3.1）：**不引用 Request/Response**，可直接单测。
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import digest, get_logger
from app.inference.base import GenParams
from app.inference.registry import get_backend
from app.prompts.loader import PromptRepository, Template
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.services.output_schema import (
    cap_pack_array_bounds,
    engine_schema_source,
    load_engine_schema,
    stripped_paths,
)
from app.services.pack_meta import apply_service_truth, build_pack_meta
from app.services import artifact_contract, content_adequacy, quality_gate
from app.services.coverage_reconcile import DIALOGUE_SPEED_MAX, reconcile_coverage_gaps
from app.services.segment import (
    SCRIPT_HEAD_TOP_KEYS,
    SCRIPT_SCENE_KEYS,
    cap_script_schema_for_segment,
    is_multi_part,
    merge_script_parts,
    merge_segments,
    merge_storyboard_parts,
    parse_json_object,
    plan_scene_segments,
    plan_script_segments,
    plan_segments,
    scene_by_no,
    scope_storyboard_for_segment,
    segment_unit_ids,
    shot_count_of,
    synopsis_scene_by_no,
    unit_ids_of,
    unit_shot_counts_of,
)
from app.schemas.dialogue import (
    ConfirmRequest,
    ReviseRequest,
    RollbackRequest,
    SessionCreateRequest,
    SessionView,
    Stage,
    TransitionResult,
)
from app.services import state_machine as sm

logger = get_logger("dialogue")

#: 生成动作发生时，**目标阶段** → 产物键 / 模板阶段。
#: 同一条映射同时服务「写到会话的哪个产物槽」与「用哪条链路模板」。
_GENERATE_ON: dict[Stage, tuple[str, str]] = {
    Stage.SYNOPSIS_REVISING: ("synopsis", "synopsis"),
    Stage.DRAFT_SCRIPT: ("script", "script"),
    Stage.DRAFT_STORYBOARD: ("storyboard", "storyboard"),
    Stage.DRAFT_SHOT_PROMPT: ("shot_prompt", "shot_prompt"),
}

#: 生成某阶段时，需从会话既有产物中取出的上游输入变量。
_UPSTREAM_VARS: dict[str, dict[str, str]] = {
    "script": {"synopsis_json": "synopsis"},
    "storyboard": {"script_json": "script"},
    "shot_prompt": {"storyboard_json": "storyboard", "script_json": "script"},
}

#: 形态闸失败中**可重试**的原因码（`ISSUE-094`）。
#:
#: - `artifact_shape_invalid`：`_guard_artifact_shape` 在 `verdict.reason` 为空时的兜底码；
#: - `script_structure_invalid`：`check_shape` 第四层（元素级结构，仅 `script`）的原因码。
#:
#: ⚠️ **只收这两码**：其余形态闸原因码（`artifact_empty`／`artifact_not_json`／
#: `artifact_shape_mismatch`／`artifact_missing_required_keys`）同样是**单次采样的
#: 随机波动**，但它们此前就**没有**重试额度；本批裁决只要求把「生成失败可自愈」这条
#: 打通到形态闸，故按裁决给定的两码**精确收口**，不擅自扩大（多给额度＝成倍耗时，
#: 属 `T-086` 量测后另议的范围）。
_SHAPE_GATE_RETRY_REASONS: frozenset[str] = frozenset(
    {"artifact_shape_invalid", "script_structure_invalid"}
)

#: **乙（2026-11-17 裁决「先甲后乙」）：承继字段类失败的判据标记**。
#:
#: ⚠️ 甲试点实锤（`DEV-20261117-001`，0/4 救回、+40% 时长）：`camera.move` 出生于
#: `storyboard` 段（`TPL-008` 导演决策层），`shot_prompt` 段（`TPL-009`）对
#: `camera.*` 是「**承继守恒：原样承继，一字不得改**」⇒ 在 `shot_prompt` 段对这类
#: 失败做重采**结构上不可能成功**（只会原样继承上游运镜），且盲重采实测产出过
#: 更差样本（`schema.pack` 缺 `action`／`prompt_en` 空串）。凡 retryable 明细**全部**
#: 命中下列标记 ⇒ 跳过本段重试（`retry_skipped_inherited_move`），判定照旧如实留痕。
#:
#: ⚠️ **只收 `R11`，不收 `R19`**（独立 QA 证伪结论 A1，2026-11-17）：`R19 GATE`
#: 目前**只在 storyboard 形态报出** —— `validate_output.validate_doc` 的 pack 分支
#: 不接线 `rule_gate`（pack 只跑 `R27/R10/R11/R35/R36/R26/R33/R34/外观复述/卫生/
#: R30/R31/R32`），所以 `shot_prompt` 段的 retryable **不可能**含 `R19`；把它放进
#: 标记是一段走不到的死代码，还会在测试里制造「生产可达」假象。
#: ⚠️ **豁免理由（明写，QA 缺口 5）**：`R10`（单元成员数）与 `R31`（镜数低于上游）
#: 同属承继面，但 **B 期 A/B 实测 `R31` 盲重试救回 3/5**（`shots_floor` 注释），
#: `R10` 亦无「重试必败」证据 ⇒ 二者保持可重试，不进本标记。
#: ⚠️ **已知风险（QA 结论 A2，登记）**：若未来把 `R19` 接进 pack 判据，**必须先拆
#: 「覆盖率族」**——构图/轴线/画面结果覆盖读 `shot_language.composition/axis/result`
#: （`CFG-006` required），属**本段可修**；届时直接并标记会错杀可重试项。
_INHERITED_MOVE_MARKERS: tuple[str, ...] = ("R11 UNIT_MOVE_UNIQUE",)

#: **客户侧自由文本字段**——`SW-009`／`SW-011` 输入闸的检测范围（`T-005`）。
#:
#: ⚠️ 刻意**排除**三类字段，理由须可举证：
#: ① 上游产物字段（`*_json` / `current_artifact`）—— 那是**模型产物**，已由 **输出闸**（`SW-010`）复检过，
#:    再按「输入」检一遍既不必要、也把「客户输入」与「模型产出」混为一谈；
#: ② 服务层注入的 `pack_meta` —— 由 `build_pack_meta()` 生成，模型不得编造，同样不是客户输入；
#: ③ 会话内部字段（`session_id` 等）。
#: ⇒ 本表即「**谁的话要过输入闸**」的唯一口径；新增客户侧字段须同时登记于此。
_CLIENT_TEXT_FIELDS: tuple[str, ...] = (
    "source_input",
    "genre",
    "target_duration",
    "audience",
    "must_include",
    "must_avoid",
    "client_visual_input",
    "gap_answers",
    "modification_request",
    "client_confirm",
)


def _no_safety():
    """默认安全服务解析器：未接线时返回 `None`（**不假装通过**，见 `_guard_input`）。"""
    return None


def _client_texts(variables: dict[str, Any]) -> list[tuple[str, str]]:
    """取出待过输入闸的「(字段名, 文本)」清单。"""
    out: list[tuple[str, str]] = []
    for name in _CLIENT_TEXT_FIELDS:
        value = variables.get(name)
        if isinstance(value, str):
            if value.strip():
                out.append((name, value))
        elif isinstance(value, (list, tuple)):
            joined = "；".join(str(v) for v in value if str(v).strip())
            if joined:
                out.append((name, joined))
    return out


@lru_cache(maxsize=1)
def _camera_no_amp_moves() -> frozenset[str]:
    """`CFG-002` 中声明「不得携带幅度/速度」的运镜码集合（`T-103` 机械清洗的**唯一事实源**）。

    ⚠️ 必须从词表现读、**不在本文件硬编码** `{static, pov}`：词表是契约，若未来新增
    `no_amplitude_no_speed: true` 的运镜码，清洗侧与门禁侧要同时生效（否则出现
    「门禁拦、清洗不修」的死循环）。
    """
    module = quality_gate.load_pack_validator()
    if module is None:
        return frozenset()
    try:
        vocab = module.load_yaml(module.CONFIG / "CFG-002_shot_vocab.yaml") or {}
    except Exception:  # 词表不可读 ⇒ 不清洗（宁可不改，也不猜）
        return frozenset()
    return frozenset(
        str(c.get("code"))
        for c in (vocab.get("camera_move") or [])
        if isinstance(c, dict) and c.get("no_amplitude_no_speed") and c.get("code")
    )


@lru_cache(maxsize=1)
def _camera_move_en_sentences() -> dict[str, str]:
    """`CFG-002` 的 `camera_move[].model_map.minimax_h3` —— **投影规则⑤的句式唯一真值源**。

    为什么从这里取而不在代码里写句子
    --------------------------------
    `CFG-002` 第 18 行明写「**规则：新增取值必须在本文件登记，不得在代码或模板中硬编码**」；
    而这 20 句英文恰好是 H3 侧**已核对过的措辞**（规范 §3.7.2 的映射表与之同源）。
    硬编码一份 = 第二份口径，词表升版时两边必然分叉（本工程多次因「两处口径打架」返工）。

    ⚠️ 词表不可读／无 `camera_move` 段 ⇒ 返回空字典，调用方**整体跳过**（fail-open，
       宁可不补也不猜；缺口仍由 `R34` 如实判失败）。

    返回 `{运镜 code: 英文句}`（如 `"static" → "The camera holds a static shot."`）。
    """
    module = quality_gate.load_pack_validator()
    if module is None:
        return {}
    try:
        vocab = module.load_yaml(module.CONFIG / "CFG-002_shot_vocab.yaml") or {}
    except Exception:  # noqa: BLE001 - 词表不可读 ⇒ 不补（不猜）
        return {}
    out: dict[str, str] = {}
    for entry in (vocab.get("camera_move") or []):
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        model_map = entry.get("model_map") or {}
        sentence = model_map.get("minimax_h3") if isinstance(model_map, dict) else None
        if code and isinstance(sentence, str) and sentence.strip():
            out[str(code)] = sentence.strip()
    return out


@lru_cache(maxsize=1)
def _camera_sentence_re() -> Any | None:
    """`R34` 的判定正则（`CAMERA_SENTENCE_RE`）—— **判据唯一真值源直接复用，不抄第二份**。

    ⚠️ 抄一份正则的后果是「服务层补的句子按 A 版口径合规、门禁按 B 版口径判失败」，
       这类分叉在本工程已发生过（`ISSUE-047` 一族）。判据模块不可加载时返回 `None`，
       调用方**整体跳过**（不补，交 `R34` 如实判）。
    """
    module = quality_gate.load_engine_validator()
    if module is None:
        return None
    return getattr(module, "CAMERA_SENTENCE_RE", None)


#: 运镜句里「幅度／速度」短语的**规范形态**（`CFG-002` 的 base 句恒用这两个短语）——
#: 键省略时删短语、键存在且非默认值时替换短语。⚠️ 只匹配 base 句自带的形态，
#: 不试图改写模型已写好的句子（本机制**只追加**，不改原句）。
_AMP_PHRASE_RE = re.compile(r"\s+with (?:small|large) amplitude")
_SPEED_PHRASE_RE = re.compile(r"\s+at (?:slow|fast) speed")


def _render_camera_sentence(base: str, cam: dict[str, Any]) -> str:
    """把 `CFG-002` 的 base 句按本镜 `camera.amplitude`／`camera.speed` 调成实况句。

    `static`／`pov` 的 base 句本就不带幅度速度（`"The camera holds a static shot."`），
    且上游 `_normalize_camera_amp_speed` 已删掉它们的 `amplitude`／`speed`
    ⇒ 两者天然自洽，本函数对它们是恒等变换。

    ⚠️ **只读 `camera`，绝不写回**：`amplitude`／`speed` 的取值面由 `R26`／`R33` 判，
       本函数改字段就会制造那两条判据的失败（§3.7.2 的互斥关系）。
    """
    amp = cam.get("amplitude")
    speed = cam.get("speed")
    out = base
    if isinstance(amp, str) and amp in ("small", "large"):
        if _AMP_PHRASE_RE.search(out):
            out = _AMP_PHRASE_RE.sub(f" with {amp} amplitude", out)
    else:
        # 键省略／非强调值 ⇒ 句子里也不该出现幅度（§3.7.2「仅当需要强调时」）
        out = _AMP_PHRASE_RE.sub("", out)
    if isinstance(speed, str) and speed in ("slow", "fast"):
        if _SPEED_PHRASE_RE.search(out):
            out = _SPEED_PHRASE_RE.sub(f" at {speed} speed", out)
    else:
        out = _SPEED_PHRASE_RE.sub("", out)
    return out.strip()


#: **投影规则⑥**（外观复述机械清洗）的机械常量。
#: ⚠️ 判据侧的**命中口径**（中文 3 字／英文 3 实词、`CJK_RUN_RE`、`ANCHOR_NGRAM`）**不在本文件**：
#:    一律经 `quality_gate.load_engine_validator()` 从 `prompts/validate_output.py` 取，
#:    本文件只持有「删多少算删空」「迭代几轮算不收敛」这两条**服务层策略**参数。
#:
#: - `_APPEARANCE_ECHO_MAX_ROUNDS`：子句删除的**不动点迭代**上限。命中可能**跨子句拼出伪 gram**
#:   （删掉中间一句后，两侧汉字重新连成一段 ⇒ 新的 3 字窗口），故删一轮必须**整段复算**；
#:   5 轮是「一轮至少删一个子句」的宽松上界（真实正文子句数远小于此，实测 1～2 轮收敛）。
#: - `_APPEARANCE_ECHO_MIN_ZH_CHARS`／`_APPEARANCE_ECHO_MIN_EN_WORDS`：**不删空保护**阈值。
#:   规范 §3.7.6 的正文下界（中文 90 字／英文 450 字符）是**创作建议值**且远高于「可读」底线，
#:   直接拿它当回滚线会让绝大多数命中都回滚（等于机制失效）；这里取「**还读得懂**」的硬底：
#:   中文去空白后 ≥10 字、英文 ≥6 实词。删到低于此值 ⇒ **整镜回滚**（不制造新的 `R27` 缺陷）。
#:   ⚠️ **「回滚线 10 字」已于 2026-11-16 由项目方确认**（与 §3.7.6 的 90 字**口径不同、
#:   不冲突**：90 字约束的是**模型创作产出**，10 字约束的是**服务层删减的下限**；
#:   两者一旦混用，投影规则⑥ 在短镜上恒回滚、规则形同未接线）。改动此值须同步
#:   SPEC-008 §3.7.2 投影规则⑥ 边界④ 与本注释——**判据口径与规范条文必须同源**。
_APPEARANCE_ECHO_MAX_ROUNDS = 5
_APPEARANCE_ECHO_MIN_ZH_CHARS = 10
_APPEARANCE_ECHO_MIN_EN_WORDS = 6

#: **占位镜**在 `notes` 上的固定前缀 —— 本文件内的**唯一真值源**。
#: ① `_reconcile_pack_conservation` 补占位镜时用它拼 `notes`；
#: ② 投影规则⑥ 用它判「这一镜是服务层构造的占位镜」并**整镜跳过**（SPEC-008 V2.6 §3.7.2 边界⑤）。
#: ⚠️ 与判据 `R27P PLACEHOLDER`（`prompts/validate_output.py`，`notes` 以「服务层构造占位」开头）
#:    是**同一锚点字符串**——判据侧为内联字面量，本批**不改判据**，故此处以常量表达并在注释里点明同源；
#:    今后若改这串中文，两处必须同批改（否则「服务层认定的占位镜」与「判据认定的占位镜」会分叉）。
_PLACEHOLDER_NOTES_PREFIX = "服务层构造占位"

#: 子句分隔符族（删除粒度＝**完整子句**）：中文按 `。！？；，、`、英文按 `. ! ? ; ,`。
#: ⚠️ 英文的 `.` 会把 `2.5`／`Mr.` 一并切断，但提示词正文里罕见，且判据本身也不区分
#:    「句」与「分句」——宁可粗切（切细了最多多删一个片段，切粗了会整句消失）。
_ZH_CLAUSE_SEPS = "。！？；，、"
_EN_CLAUSE_SEPS = ".!?;,"
#: 同类分隔符连排（删子句后的残留）：折叠为一个，**保留后一个**（见 `_join_clauses`）。
_ZH_SEP_RUN_RE = re.compile(r"[。！？；，、]{2,}")
_EN_SEP_RUN_RE = re.compile(r"[.!?;,]{2,}")
_WS_RE = re.compile(r"\s")


def _split_clauses(text: str, seps: str) -> list[tuple[str, str]]:
    """把正文切成 `[(子句, 尾随分隔符), …]`（**保留分隔符**，删子句时不粘连相邻内容）。

    ⚠️ 为什么按**子句**切而不按词切：投影规则⑥ 的口径是「删冗余」，**不是改写句子**——
       逐词手术会把一句话抠成病句，且等于服务层改写模型语义（越界）。删**完整子句**
       是唯一既能清掉命中锚、又不改变剩余句子语义的粒度（裁决口径，写进 §3.7.2）。
    """
    tokens: list[tuple[str, str]] = []
    buf: list[str] = []
    for ch in text:
        if ch in seps:
            tokens.append(("".join(buf), ch))
            buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append(("".join(buf), ""))
    return tokens


def _join_clauses(
    tokens: list[tuple[str, str]],
    *,
    sep_run_re: Any,
    lead_strip: str,
    tail_strip: str,
    terminators: str,
    default_terminator: str,
) -> str:
    """把 `[(子句, 分隔符), …]` 重新拼回正文（**机械重组**，不改写任何词）。

    三处机械动作（逐条可解释，均不承载创作意图）：
    ① 子句被删后相邻两个分隔符会连排（`…滑落，；她占据…`）⇒ **折叠为一个、保留后一个**
       （后一个正是原句该处的层级标点，折叠后与「直接删掉前半句」读起来一致）；
    ② 首尾残留的分隔符／空白去掉（否则正文会以 `，`／`,` 起止，属脏化）；
    ③ 收尾若已无终止符，补本语言的默认终止符（`。`／`.`）——**只补标点，不补内容**
       （与投影规则⑤ 的 `terminator_added` 同性质）。
    """
    out = "".join(f"{clause}{sep}" for clause, sep in tokens)
    out = sep_run_re.sub(lambda m: m.group(0)[-1], out)
    out = out.strip()
    out = out.lstrip(lead_strip)
    out = out.rstrip(tail_strip)
    out = out.strip()
    if out and out[-1] not in terminators:
        out = out + default_terminator
    return out


def _zh_appearance_hit(
    cjk_run_re: Any, anchor_n: int, text: str, grams: frozenset[str] | set[str]
) -> str | None:
    """中文正文是否复述外观锚（**与 `R28` 第 1815-1818 行完全同一口径**）。

    只在**汉字连续段**内滑 `ANCHOR_NGRAM` 窗口（避免中英混排的跨段伪命中），
    窗口落在 `grams` 里即命中。返回首个命中的 gram（供留痕），无命中返回 `None`。
    """
    if not text:
        return None
    for run in cjk_run_re.findall(text):
        for i in range(len(run) - anchor_n + 1):
            gram = run[i:i + anchor_n]
            if gram in grams:
                return gram
    return None


def _en_appearance_hit(
    en_content_ngrams: Any, text: str, grams: frozenset[str] | set[str]
) -> str | None:
    """英文正文是否复述外观锚（**与 `R28` 第 1828-1831 行完全同一口径**：实词 3-gram 求交）。"""
    if not text:
        return None
    inter = en_content_ngrams(text) & grams
    return sorted(inter)[0] if inter else None


def _scrub_appearance_echo_field(
    raw: str,
    *,
    lang: str,
    hit: Any,
    is_too_short: Any,
) -> tuple[str, str | None, str, int]:
    """对**一个字段**（某镜的 `prompt_zh` 或 `prompt_en`）做子句级清洗，迭代到不动点。

    :param lang: `"zh"`／`"en"`（决定分隔符族与默认终止符）。
    :param hit: `(text) -> 命中的 gram 或 None`，**判据口径由调用方从 engine 取**（不在此重写）。
    :param is_too_short: `(text) -> bool`，**不删空保护**的度量。
    :returns: `(新文本, 首个命中 gram, 状态, 迭代轮次)`；
        状态 ∈ `scrubbed`（已删且复算归零）／`unresolvable`（删不动或 5 轮仍命中）／
        `would_empty`（删到过短 ⇒ 已回滚）／`nothing`（本来就不命中）。

    ⚠️ **不硬凑**：`unresolvable` 一律返回**当前文本**并如实登记，交判据 `R28` 判失败——
       本机制的价值是把「可自动消解的命中」消解掉，不是把 `R28` 洗绿。
    """
    if lang == "zh":
        seps, sep_run_re = _ZH_CLAUSE_SEPS, _ZH_SEP_RUN_RE
        lead_strip, tail_strip = "，、；", "，、；"
        terminators, default_terminator = "。！？", "。"
    else:
        seps, sep_run_re = _EN_CLAUSE_SEPS, _EN_SEP_RUN_RE
        lead_strip, tail_strip = ",;", ",;"
        terminators, default_terminator = ".!?", "."

    first_gram = hit(raw)
    if first_gram is None:
        return raw, None, "nothing", 0

    cur = raw
    rounds = 0
    while rounds < _APPEARANCE_ECHO_MAX_ROUNDS:
        gram_now = hit(cur)
        if gram_now is None:
            break
        rounds += 1
        kept: list[tuple[str, str]] = []
        dropped = False
        for clause, sep in _split_clauses(cur, seps):
            if clause and hit(clause) is not None:
                if lang == "en" and clause.lstrip().startswith("The camera"):
                    # **保护投影规则⑤ 补的句子**（同时也保护模型自己写对的句子）：
                    # 运镜句是本层刚投影进来的合规内容，删它等于亲手打开 `R34` 的洞。
                    kept.append((clause, sep))
                    continue
                kept.append(("", sep))
                dropped = True
            else:
                kept.append((clause, sep))
        if not dropped:
            # 命中只落在受保护子句（`The camera …`）内 ⇒ 无可删子句，**如实登记**
            return cur, gram_now, "unresolvable", rounds
        cur = _join_clauses(
            kept,
            sep_run_re=sep_run_re,
            lead_strip=lead_strip,
            tail_strip=tail_strip,
            terminators=terminators,
            default_terminator=default_terminator,
        )

    leftover = hit(cur)
    if leftover is not None:
        # 5 轮仍命中（跨子句伪 gram 或只剩受保护子句）⇒ 放弃并如实登记
        return cur, leftover, "unresolvable", rounds
    if is_too_short(cur):
        # **不删空保护**：删到过短 ⇒ 整镜回滚（原文一字不动），不制造新的正文缺失缺陷
        return raw, first_gram, "would_empty", rounds
    return cur, first_gram, "scrubbed", rounds


class DialogueService:
    """会话编排服务。"""

    def __init__(
        self,
        repo: SessionRepository,
        prompts: PromptRepository,
        backend_resolver=get_backend,
        safety_resolver=_no_safety,
    ) -> None:
        self.repo = repo
        self.prompts = prompts
        self._resolve_backend = backend_resolver
        self._safety_resolver = safety_resolver

    # ------------------------------------------------------------------ 查询
    def _require(self, session_id: str) -> SessionRecord:
        rec = self.repo.get(session_id)
        if rec is None:
            raise AppError(
                ErrorCode.SESSION_NOT_FOUND,
                f"会话不存在：{session_id}",
                details={"session_id": session_id},
            )
        return rec

    @staticmethod
    def _view(rec: SessionRecord) -> SessionView:
        stage = Stage(rec.stage)
        return SessionView(
            session_id=rec.session_id,
            stage=stage,
            stage_label=sm.label_of(stage),
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            artifacts=rec.artifacts,
            confirmed_snapshot=rec.confirmed_snapshot,
            history=list(rec.history),
        )

    def get(self, session_id: str) -> SessionView:
        return self._view(self._require(session_id))

    # ------------------------------------------------------------------ 创建
    def create_session(self, req: SessionCreateRequest) -> SessionView:
        defaults: dict[str, Any] = {"source_input": req.source_input}
        if req.genre:
            defaults["genre"] = req.genre
        if req.target_duration:
            defaults["target_duration"] = req.target_duration
        if req.audience:
            defaults["audience"] = req.audience
        rec = self.repo.create(
            stage=Stage.DRAFT_SYNOPSIS.value,
            source_input=req.source_input,
            defaults=defaults,
        )
        rec.history.append(f"create → {rec.stage}")
        self.repo.save(rec)
        logger.info(
            "session_created",
            extra={"extra_fields": {"session_id": rec.session_id}},
        )
        return self._view(rec)

    # ------------------------------------------------------------------ 推进
    async def advance(self, session_id: str, variables: dict[str, Any] | None = None) -> TransitionResult:
        """沿全序推进一步。

        ⚠️ 当下一步需要客户确认时，`sm.plan_advance` 会抛 `CONFIRMATION_REQUIRED`
        ——这就是 **SW-003 门控**：未确认梗概时**无法**推进到剧本阶段。
        """
        rec = self._require(session_id)
        current = Stage(rec.stage)
        target, action = sm.plan_advance(current)  # 可能抛 CONFIRMATION_REQUIRED
        merged = dict(rec.defaults)
        merged.update(variables or {})
        await self._maybe_generate(rec, target, merged)
        self._move(rec, current, target, action.value)
        return self._result(rec, action.value, current, target)

    # ------------------------------------------------------------------ 确认
    def confirm(self, session_id: str, req: ConfirmRequest | None = None) -> TransitionResult:
        """确认门控（SW-003）：固化当前产物快照，允许进入下一阶段。"""
        rec = self._require(session_id)
        current = Stage(rec.stage)
        target = sm.plan_confirm(current)  # 不可确认时抛 INVALID_STATE_TRANSITION
        key = _artifact_key_of(current)
        if key and key in rec.artifacts:
            snapshot = {
                "artifact": key,
                "stage": current.value,
                "content": rec.artifacts[key],
                "note": (req.note if req else None),
            }
            rec.confirmed_snapshot = snapshot
            logger.info(
                "snapshot_frozen",
                extra={"extra_fields": {"session_id": rec.session_id, "artifact": key}},
            )
        self._move(rec, current, target, sm.Action.CONFIRM.value)
        return self._result(rec, sm.Action.CONFIRM.value, current, target)

    # ------------------------------------------------------------------ 回退
    def rollback(self, session_id: str, req: RollbackRequest) -> TransitionResult:
        """回退到任意前置阶段（SW-001）。已确认快照保留，供对照。"""
        rec = self._require(session_id)
        current = Stage(rec.stage)
        target = sm.resolve_rollback(current, req.target_stage)
        if req.reason:
            rec.history.append(f"rollback_reason: {req.reason}")
        self._move(rec, current, target, sm.Action.ROLLBACK.value)
        return self._result(rec, sm.Action.ROLLBACK.value, current, target)

    # ------------------------------------------------------------------ 修改
    async def revise(self, session_id: str, req: ReviseRequest) -> TransitionResult:
        """对话式修改（SW-002）。

        本批对接 `modify_v1`（链路支撑模板、刻意不填 stage）：只**替换目标产物槽**，
        **不改变阶段**——修改是阶段内的迭代动作，不是状态迁移。
        """
        rec = self._require(session_id)
        target_stage = req.target_stage or Stage(rec.stage)
        key = _artifact_key_of(target_stage)
        if key is None:
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                f"阶段「{sm.label_of(target_stage)}」暂无可修改的产物",
                details={"stage": target_stage.value},
            )
        # ---- `SW-017` 含糊时澄清（`CFG-008`「意图不唯一时不猜、不择优」）----
        # 口径 A（项目方 2026-10-16 裁决）：**必填项缺失即含糊**，转澄清并**中止本次 revise**。
        # ⚠️ 契约要求「澄清期 `change_log` 必须为空」⇒此处**不改产物、不写 history**，
        #   只把缺失项与澄清话术回给调用方；覆盖率不足时再叠加模型判定（口径 B）。
        safety = self._safety_resolver()
        if safety is not None:
            missing = safety.detect_ambiguity(
                {
                    "target_stage": target_stage.value,
                    "modification_request": req.modification_request,
                }
            )
            if missing:
                rec.history.append(
                    f"revise_clarify({target_stage.value}) 缺项={'/'.join(missing)}"
                )
                self.repo.save(rec)
                raise AppError(
                    ErrorCode.CLARIFICATION_NEEDED,
                    safety.clarify_talk(),
                    details={
                        "missing_items": missing,
                        "judge": "CFG-008「含糊时澄清」：必填项缺失，不猜不择优",
                    },
                )
        template = self.prompts.get("modify_v1")
        variables: dict[str, Any] = {
            "target_stage": target_stage.value,
            "current_artifact": rec.artifacts.get(key, {}),
            "modification_request": req.modification_request,
        }
        # ---- 安全双闸（`T-005`）：修改意见同属**客户输入**；产出同样须复检 ----
        guard_input = self._guard_input(variables)
        rendered = self.prompts.render(template, variables)
        backend = self._resolve_backend()
        result = await backend.generate(
            f"[stage:modify]\n{rendered.as_text()}", _params_of(template.sampling)
        )
        guard_output = self._guard_output(result.text)
        rec.artifacts[key] = {
            "template_id": template.id,
            "template_version": template.version,
            "revision_request": req.modification_request,
            "models": [{"name": backend.name, "version": backend.version, "adapter": None}],
            "text": result.text,
        }
        if guard_input is not None or guard_output is not None:
            rec.artifacts[key]["safety"] = {"input": guard_input, "output": guard_output}
        rec.history.append(f"revise({target_stage.value}) → {key}")
        self.repo.save(rec)
        return self._result(rec, "revise", target_stage, target_stage)

    # ------------------------------------------------------ 安全双闸（`T-005`）
    def _guard_input(self, variables: dict[str, Any]) -> dict[str, Any] | None:
        """`SW-009` 输入前置检测 ＋ `SW-011` 提示注入防护。

        ⚠️ **服务层只判定、编排层才阻断**（`SafetyService` 的分层纪律）——
        本方法据 verdict 决定**是否抛 `GUARD_INPUT_BLOCKED`**。
        `enforce=false`（受控旁路，项目方 2026-10-15 决策）时**照样检测、照样留痕**，仅不抛错。
        未接线（`safety_resolver` 为默认）时返回 `None` —— **不假装通过**（留痕缺失本身即信号）。
        """
        safety = self._safety_resolver()
        if safety is None:
            return None

        entries: list[dict[str, Any]] = []
        for field, text in _client_texts(variables):
            verdict = safety.inspect_input(text)
            injection = safety.check_injection(text)
            entries.append(
                {
                    "field": field,
                    "passed": verdict.passed,
                    "action": verdict.action,
                    # ⚠️ 受控类**只记分类码与计数、绝不落命中词明文**
                    "hit_count": verdict.hit_count,
                    "hit_categories": [h.category_id for h in verdict.hits],
                    "degraded": verdict.degraded,
                    "injection_blocked": injection.blocked,
                    "injection_patterns": list(injection.patterns),
                }
            )
            blocked = injection.blocked or not verdict.passed
            if blocked and safety.enforce:
                raise AppError(
                    ErrorCode.GUARD_INPUT_BLOCKED,
                    injection.message if injection.blocked else verdict.message,
                    details={
                        "field": field,
                        "reason": "prompt_injection" if injection.blocked else verdict.action,
                        "hit_categories": [h.category_id for h in verdict.hits],
                        "degraded_reason": verdict.degraded_reason,
                        "refusal_talk": verdict.refusal_talk or safety.refusal_talk(),
                    },
                )
        return {
            "channel": "input",
            "enforced": safety.enforce,
            "circuit_open": safety.circuit_open,
            "checked_fields": [e["field"] for e in entries],
            "blocked": any(
                (not e["passed"]) or e["injection_blocked"] for e in entries
            ),
            "entries": entries,
        }

    def _guard_output(self, text: str) -> dict[str, Any] | None:
        """`SW-010` 输出复检。命中处置由 `guard_output_action`（block／replace／flag）决定。

        ⚠️ `flag` 的 `passed=True`（**标记待人工复核、不阻断**）是**策略语义**，
        故此处只对 `passed=False` 抛错；`flag` 命中仍会进留痕。
        """
        safety = self._safety_resolver()
        if safety is None:
            return None

        # `ISSUE-070` 生产侧修复：模型侧拒答话术走独立通道，不过输出词闸
        # （拒答话术为说明理由会复述敏感词，被输出闸拦截 ⇒ 用户看到兜底话术而非拒答说明）。
        # 语义闸（若注入）仍对该通道复检，仅 `Unsafe` 才拦——防「伪装拒答」绕过词闸。
        verdict = safety.inspect_output(text, is_refusal=safety.looks_like_refusal(text))
        summary: dict[str, Any] = {
            "channel": "output",
            "passed": verdict.passed,
            "action": verdict.action,
            "hit_count": verdict.hit_count,
            "hit_categories": [h.category_id for h in verdict.hits],
            "degraded": verdict.degraded,
            "degraded_reason": verdict.degraded_reason,
            "enforced": safety.enforce,
        }
        if not verdict.passed and safety.enforce:
            raise AppError(
                ErrorCode.GUARD_OUTPUT_BLOCKED,
                verdict.message,
                details={
                    "action": verdict.action,
                    "hit_categories": summary["hit_categories"],
                    "degraded_reason": verdict.degraded_reason,
                    "refusal_talk": verdict.refusal_talk or safety.refusal_talk(),
                },
            )
        return summary

    # ------------------------------------------- 产物形态闸（`ISSUE-042` 根治）
    def _guard_not_truncated(self, tpl_stage: str, trace: list[dict[str, Any]]) -> list[str]:
        """**截断判定**：任一段 `finish_reason=length` 即「输出被长度上限切断」。

        ⚠️ 为什么单列一闸（实测教训）：`ISSUE-042` 的产物**不是**被长度截断的
        ——`completion_tokens=4,715` 远未触 `max_tokens=8,192`，`finish_reason` 却是 `stop`，
        即**模型自终止在一个不完整的结构上**（`temperature=0.8` ⇒ 随机发生，
        同模板同输入的上一轮产出过合法 JSON）。两者**修法不同**：
        长度截断 → 调 `max_tokens`／改分段粒度；结构自终止 → **约束解码**。
        故本闸只负责如实区分，不把它们混成一句「JSON 解析失败」。

        返回被截断的段名清单（留痕用）；`shape_gate_enforce=true` 时随之抛错。
        """
        truncated = [str(t.get("segment")) for t in trace if t.get("finish_reason") == "length"]
        if not truncated:
            return []
        if get_settings().shape_gate_enforce:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"「{tpl_stage}」段输出被长度上限切断（段：{'、'.join(truncated)}）",
                details={
                    "reason": "segment_truncated",
                    "stage": tpl_stage,
                    "truncated_segments": truncated,
                    "segment_plan": [t.get("segment") for t in trace],
                },
            )
        logger.warning(
            "segment_truncated_bypassed",
            extra={
                "extra_fields": {
                    "stage": tpl_stage,
                    "truncated_segments": truncated,
                    "note": "形态闸处于受控旁路（shape_gate_enforce=false），未阻断",
                }
            },
        )
        return truncated

    def _admit_upstream(self, upstream_key: str, text: str) -> dict[str, Any]:
        """**上游准入闸**：每一份交给模型的上游产物，先过形态闸。

        ⚠️ 设立理由（实测）：第 3 轮真跑中分镜段产出**被截断的 JSON**，
        提示词段仍拿到它继续生成，模型因此**自行编造** `units=7／shots=13`
        ——而这份「上游」根本不可解析，本层第一纪律「**承继守恒**」
        **在源头已不可验证**。「上游可不可用」是**可判的事实**，
        不该由下游「尽力而为」；`_artifact_text()` 只负责取正文，**没有判定能力**。

        ⚠️ 分层纪律（与 `SW-010` 同款）：**服务层只判定、编排层阻断**——
        本方法据 verdict 决定是否抛 `GENERATION_FAILED`。
        """
        shape = artifact_contract.STAGE_TO_SHAPE.get(upstream_key)
        if shape is None:  # pragma: no cover - 现有上游三键均有形态
            return {"upstream": upstream_key, "checked": False}
        verdict = artifact_contract.check_shape(shape, text)
        enforcement = get_settings().shape_gate_enforce
        record: dict[str, Any] = {
            "upstream": upstream_key,
            "shape": shape,
            "checked": True,
            "ok": verdict.ok,
            # ⚠️ 字段名刻意**不叫 `reason`**：闸门的机器可判原因码占用 `details["reason"]`，
            #    若此处同名，摊平 `record` 时会把「闸门原因」覆盖成「形态判定原因」
            #    ——本批实现时已踩（负样本测试当场暴露），故分离为 `shape_reason`。
            "shape_reason": verdict.reason,
            "enforced": enforcement,
        }
        if verdict.ok:
            return record
        if enforcement:
            # ⚠️ `retryable=False`：上游已入库且不变，**重跑本步不会改变它**——
            #    恢复路径是回退到上游阶段重新生成，不是重试本步。
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游产物「{upstream_key}」未通过形态闸，拒绝据此生成：{verdict.error}"
                "（恢复路径：回退到该上游阶段重新生成）",
                # ⚠️ `reason` **放在最后写**：任何摊平进来的子对象都不得覆盖闸门原因码。
                details={
                    **record,
                    **(verdict.error_details or {}),
                    "reason": "upstream_invalid",
                },
                retryable=False,
            )
        logger.warning(
            "upstream_shape_gate_bypassed",
            extra={
                "extra_fields": {
                    **record,
                    "note": "形态闸处于受控旁路（shape_gate_enforce=false），未阻断",
                }
            },
        )
        return record

    def _guard_artifact_shape(self, tpl_stage: str, text: str) -> dict[str, Any] | None:
        """**生成后形态闸**：产物必须过形态契约，否则**不写产物槽、不推进状态机**。

        三条纪律：
        1. **单段与多段收敛到同一条路径** —— 消掉「产物是否被检查**取决于 `segment` 取值**」
           这一偶然性（改造前单段 `final_text = texts[0]` 完全不解析）；
        2. **判定与否可核查** —— 返回值恒非空且带 `checked=true`：
           「判过且通过」与「根本没判」在留痕上**必须可分**
           （`ISSUE-042` 的成因正是二者同形：`merge_warnings: 0` 既可能是
           「合并无告警」、也可能是「压根没合并」）；
        3. **只判形态、不判合规** —— 字段级／取值级判据属交付层（R26~R36），
           服务层不引入工程侧脚本依赖。

        ⚠️ 抛出即「**不写槽、不推进**」：`advance()` 在 `_maybe_generate()` 之后才 `_move()`，
        异常会中断该次推进 ⇒ 会话停在原阶段，**不会出现「非法产物驱动下游」的状态**。
        """
        shape = artifact_contract.STAGE_TO_SHAPE.get(tpl_stage)
        if shape is None:  # pragma: no cover - 现有四阶段均有形态
            return None
        enforcement = get_settings().shape_gate_enforce
        verdict = artifact_contract.check_shape(shape, text)
        record: dict[str, Any] = {
            "stage": tpl_stage,
            "shape": shape,
            "checked": True,
            "ok": verdict.ok,
            # ⚠️ 同 `_admit_upstream`：与闸门原因码 `details["reason"]` **不得同名**。
            "shape_reason": verdict.reason,
            "detected_shape": verdict.detected,
            "missing_keys": list(verdict.missing),
            "enforced": enforcement,
        }
        if verdict.ok:
            return record
        if not enforcement:
            logger.warning(
                "artifact_shape_gate_bypassed",
                extra={
                    "extra_fields": {
                        **record,
                        "note": "形态闸处于受控旁路（shape_gate_enforce=false），未阻断",
                    }
                },
            )
            return record
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            f"「{tpl_stage}」段产物未通过形态闸：{verdict.error}",
            # ⚠️ `reason` **放在最后写**（同上游准入闸的理由）。
            details={
                **record,
                **(verdict.error_details or {}),
                "reason": verdict.reason or "artifact_shape_invalid",
            },
        )

    def _assess_content_adequacy(
        self, tpl_stage: str, text: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """`ISSUE-045` **内容足量性探测**：判、记，**但不阻断**。

        与 `_guard_artifact_shape`（结构层、可阻断）**刻意分成两组留痕字段**，
        不得合并成一个布尔 —— 「结构过了」与「内容够不够」是两件事：
        `ISSUE-042` 修的是前者，`ISSUE-045` 记的是后者，二者的实证是**同一批产物**。

        ⚠️ **本方法永不抛错、永不阻断**（2026-10-16 项目方裁决）：字段级算术自洽与
        覆盖度属**质量**维度，而真实模型产物**普遍**不自洽（四轮真跑中凡产出分镜者
        `Σ镜头时长 ≠ total_duration_ms` **无一轮例外**）⇒ 若设阻断，链路直接不可用。
        判定与执行分离，同 `SafetyService` 的分层纪律。

        上游文本取 `variables` 里**模型实际看到的那一份**（已按 `ISSUE-044` 决定是否紧凑化）
        —— 判据与生成**同源同物**，避免"判的和用的不是一份"。
        """
        upstream: dict[str, str] = {}
        if tpl_stage in content_adequacy.NEEDS_UPSTREAM:
            for var in _UPSTREAM_VARS.get(tpl_stage, {}):
                value = variables.get(var)
                if isinstance(value, str):
                    upstream[var] = value
        try:
            return content_adequacy.assess(tpl_stage, text, upstream)
        except Exception as exc:  # noqa: BLE001 探测模块**不得**成为新的失败点
            logger.warning(
                "content_adequacy_failed",
                extra={"extra_fields": {"stage": tpl_stage, "error": type(exc).__name__}},
            )
            return {"checked": False, "ok": None, "stage": tpl_stage, "findings": [], "metrics": {}}

    def _guard_segment_contributions(
        self, tpl_stage: str, plan: list[str], texts: list[str]
    ) -> list[dict[str, Any]]:
        """**分段贡献闸**：多段计划里，每一段都必须**真的产出东西**。

        ⚠️ 补的是一个**静默洞**（本批自查发现，与 `ISSUE-042` 同族）：
        `merge_segments()` 对「可解析但一个相关键都没有」的段**不会产生任何告警**
        ——它只是「什么都没并进去」。于是若某个 `unit:<id>` 段返回 `{}` 或无关对象，
        该单元的镜会**整段消失**，而合并结果依然「结构完整、`merge_warnings=0`」
        ⇒ 正是本工程最要防的「**看起来完整、实则无据**」。

        判据刻意**极宽松**（只反对「零贡献」，不判贡献得对不对）：
        段产物须至少含一个 `HEAD_KEYS ∪ {units, shots}` 的**非空**键。
        理由：语义级判定（「这个 unit 段有没有把该单元的镜出全」）需要上游基准，
        属**交付层**（`validate_pack.py` 与 `--storyboard` 比对）的事，服务层不自造。
        """
        from app.services.segment import HEAD_KEYS

        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "script":
            # `T-116`：script 拆段产物的键集是 head 键集 ∪ 场对象键集
            # （`HEAD_KEYS` 是交付包键，与 script 形态不同族，不适用）；
            # `scenes` 是合并器容忍的包装形态键（QA 证伪 L5：两处口径取齐）。
            contributable = (
                set(SCRIPT_HEAD_TOP_KEYS) | set(SCRIPT_SCENE_KEYS) | {"scenes"}
            )
        else:
            contributable = set(HEAD_KEYS) | {"units", "shots"}
        records: list[dict[str, Any]] = []
        empty: list[str] = []
        for seg, text in zip(plan, texts):
            try:
                doc = parse_json_object(text)
            except AppError as exc:
                # 解析失败由 `_merge_parts` 统一报错（此处不抢先，避免两处归因打架）
                records.append({"segment": seg, "parsed": False, "note": exc.message[:80]})
                continue
            keys = [k for k in contributable if k in doc and doc[k]]
            records.append({"segment": seg, "parsed": True, "contributing_keys": keys})
            if not keys:
                empty.append(seg)
        if empty and get_settings().shape_gate_enforce:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"「{tpl_stage}」段产物有 {len(empty)} 段零贡献"
                f"（段：{'、'.join(empty)}）——合并后会出现无据缺口，拒绝入库",
                details={
                    "reason": "segment_contributing_nothing",
                    "stage": tpl_stage,
                    "empty_segments": empty,
                    "segment_plan": list(plan),
                },
            )
        return records

    # ------------------------------------------------------------------ 内部
    def _segment_plan(
        self,
        template: Template,
        tpl_stage: str,
        rec: SessionRecord,
        merged: dict[str, Any],
    ) -> list[str]:
        """解析本次生成的**调用计划**（`T-004`）。

        只有声明了 `segment` 变量的模板才分段；其余模板为单次调用。
        `auto` 的拆分依据是**上游镜数与单元数**，故须解析上游产物——
        上游无法解析时降为整包并**留告警**（不静默假装已知镜数）。

        ⚠️ **降级与阻断的分工（`ISSUE-042` 后）**：本方法**只管计划**，
        「上游该不该被放行」是**上游准入闸**（`_admit_upstream`）的判断。
        `shape_gate_enforce=true` 时上游不可解析**在上游循环里就已阻断**，
        故本处 `None` 分支**不可达**；保留它是为了让受控旁路下仍能如实留痕。
        """
        if not any(v["name"] == "segment" for v in template.variables):
            return ["all"]

        # ---- `T-100`／`PRO-014`：分镜段逐场编排（每场一次调用）----
        # ⚠️ 计划来源是**上游剧本的场号清单**（不是分镜产物自己的场分组——后者正是要消灭的
        #    空真来源：产物缺哪场，它自己的场分组就少哪场）。
        # ⚠️ 与 `shot_prompt` 的 `auto` 不同，本分支**没有「镜数阈值」**：逐场的动机是
        #    **场覆盖**而非输出体积，3 场与 30 场同样需要。
        if tpl_stage == "storyboard":
            if not get_settings().storyboard_scene_orchestration:
                return ["all"]
            script = _upstream_json(rec.artifacts.get("script"))
            if script is None:
                logger.warning(
                    "scene_plan_upstream_unparsed",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "note": "上游剧本无法解析为 JSON，逐场编排退为整片一次调用"
                            "（⚠️ 形态闸生效时本分支不可达——上游准入闸已先阻断）",
                        }
                    },
                )
                return ["all"]
            return plan_scene_segments(script)

        # ---- `T-116`：script 段逐场拆段（package_head + scene:N）----
        # ⚠️ 计划来源是**上游梗概的场号清单**（`scenes_outline`）——场号沿用梗概是
        #    本层硬性约束（不得重编、不得增删），场号真值在梗概侧。
        # ⚠️ 开关关 ⇒ 整段模式（旧行为零改动）；梗概场号异常 ⇒ 降级整段＋留痕
        #    （形态闸生效时本分支不可达——上游准入闸已先阻断）。
        if tpl_stage == "script":
            if not get_settings().script_scene_orchestration:
                return ["all"]
            plan_script = plan_script_segments(_upstream_json(rec.artifacts.get("synopsis")))
            if not plan_script:
                logger.warning(
                    "script_plan_upstream_unparsed",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "note": "梗概 scenes_outline 场号异常，逐场拆段退为整片一次调用"
                            "（⚠️ 形态闸生效时本分支不可达——上游准入闸已先阻断）",
                        }
                    },
                )
                return ["all"]
            return plan_script

        value = merged.get("segment") or template.default_of("segment") or "auto"
        shot_count, unit_ids = 0, []
        unit_counts: list[int] = []
        if tpl_stage == "shot_prompt":
            storyboard = _upstream_json(rec.artifacts.get("storyboard"))
            if storyboard is None:
                logger.warning(
                    "segment_plan_upstream_unparsed",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "note": "上游分镜产物无法解析为 JSON，`auto` 退为整包"
                            "（⚠️ 形态闸生效时本分支不可达——上游准入闸已先阻断）",
                        }
                    },
                )
            else:
                shot_count = shot_count_of(storyboard)
                unit_ids = unit_ids_of(storyboard)
                unit_counts = unit_shot_counts_of(storyboard)
        # `丙`：分段最小镜数（`0`/`1`＝关，旧行为不变）。段粒度由「每单元一段」变为
        # 「相邻单元攒到 ≥ N 镜一组」——`DEV-20261117-003`／`-004` 实证：2 镜单元单独
        # 成段时该单元 need=2 且只有 2 镜 ⇒ 强制全异，是最难达标的形态。
        # ⚠️ 独立 QA 复验条件②：组段依赖 `_run_segments` 的按段 schema 封顶
        # （`units_cap`/`units_floor`/`shots_floor`），而封顶只在 `shot_prompt_segment_scope=true`
        # 且拿到裁剪副本时生效 ⇒ 裁剪关闭时必须**禁用组段**，否则「组段标签存在但
        # units_floor 不存在」会静默绕过「单元一个不能少」的保护。
        # ⚠️ 条件④：取值只接受 0/1/2/3（`2×min_shots ≤ AUTO_SHOT_THRESHOLD=6`）；
        # 越界如实告警并回退 0（不静默按大值组出超体积段）。
        min_shots = get_settings().segment_plan_min_shots
        if min_shots not in (0, 1, 2, 3):
            logger.warning(
                "segment_plan_min_shots_invalid",
                extra={
                    "extra_fields": {
                        "session_id": rec.session_id,
                        "value": min_shots,
                        "note": "取值仅支持 0/1/2/3（2×min ≤ 整包阈值 6）；已按 0（关）处理",
                    }
                },
            )
            min_shots = 0
        if min_shots >= 2 and not get_settings().shot_prompt_segment_scope:
            logger.warning(
                "segment_plan_min_shots_ignored",
                extra={
                    "extra_fields": {
                        "session_id": rec.session_id,
                        "note": "`shot_prompt_segment_scope=false` ⇒ 无按段 schema 封顶，"
                        "组段会失去 units_floor 保护，已按 0（关）处理",
                    }
                },
            )
            min_shots = 0
        plan = plan_segments(
            value,
            shot_count=shot_count,
            unit_ids=unit_ids,
            min_shots=min_shots,
            unit_shot_counts=unit_counts,
        )
        if min_shots >= 2 and value == "auto" and any("+" in s for s in plan):
            logger.info(
                "segment_plan_grouped",
                extra={
                    "extra_fields": {
                        "session_id": rec.session_id,
                        "min_shots": min_shots,
                        "groups": [s for s in plan if s.startswith("unit:")],
                        "unit_counts": unit_counts,
                    }
                },
            )
        return plan

    async def _run_segments(
        self,
        template: Template,
        tpl_stage: str,
        merged: dict[str, Any],
        segs: list[str],
        supports_segment: bool,
        json_schema: dict[str, Any] | None,
        backend: Any,
        scene_ctx: dict[int, dict[str, Any]] | None = None,
        scope_ctx: dict[str, Any] | None = None,
        script_ctx: dict[str, Any] | None = None,
        prior_texts: dict[str, str] | None = None,
        retry_feedback: str | None = None,
        retry_feedback_unlocated: bool = False,
    ) -> tuple[dict[str, str], list[dict[str, Any]], int, int, list[str]]:
        """按 `segs` 逐段调用引擎，返回 `(段→文本, 本批留痕, prompt_tokens, completion_tokens, 截断段)`。

        ⚠️ 抽出来是为 `T-086` 的**按段重试**服务：重试时只传「失败的段」，
        未失败的段**沿用上一轮的采样结果**（各自独立，互不牵连）。
        ⚠️ **本方法只做调用与留痕，不改写、不润色模型输出。**
        ⚠️ `scene_ctx`（`T-100` 逐场编排）：场号 → 该场对象；非空且段名为 `scene:<no>` 时，
        按段注入 `scene_scope`／`scene_json`／`prev_scene_tail`／`scene_budget`
        ——**段间存在前向依赖**（上一场末镜喂下一场的衔接参照），故逐场必须**串行**。
        ⚠️ `scope_ctx`（`T-101`／`PRO-015` 段级输入裁剪）：`{"storyboard": <已解析的上游>}`；
        非空且段名为 `package_head`／`unit:<id>` 时，把 `storyboard_json` 换成**按段裁剪副本**。
        裁剪失败 ⇒ 原样整份（`scope_storyboard_for_segment` 返回 `None` 时），留痕在 trace。
        ⚠️ `retry_feedback`（**乙**，2026-11-17 裁决）：重采请求附带的**判据反馈**文本
        （由 `_retry_feedback_text` 构造，只含 retryable 明细）。甲试点（`DEV-20261117-001`）
        实证盲重采救回 0/4——模型不知道「为什么重采」，系统性偏置原样复现。注入位置在
        **请求侧**（提示词尾追加），不改写产物、不改模板正文；trace 记 `retry_feedback` 布尔。
        ⚠️ `retry_feedback_unlocated`（QA 结论 b 的缓解）：反馈随**全段**注入（定位回退）
        时，每段前置「只纠正与本段相关者」免责句——防未失败段被反馈诱发改写
        （甲试点第 2 轮「重采产出更差样本」的同族风险）。
        ⚠️ `prior_texts`（`T-116` QA 证伪 B1 修复）：**此前各 attempt 已成功的段文本**
        （调用方的 `texts_by_seg`，在本方法返回前不含本批产出）。段级重采只传坏段，
        本批 `produced` 缺 head ⇒ script 场段的锚点承继须回退查 `prior_texts`——
        否则重采场段会拿到「头部不可解析」的**假降级文案**（与事实相反的指令）
        并在 unspecified 里登记假台账条目。
        """
        produced: dict[str, str] = {}
        trace: list[dict[str, Any]] = []
        prompt_tokens = completion_tokens = 0
        for seg in segs:
            seg_vars = dict(merged)
            if supports_segment:
                seg_vars["segment"] = seg
            if scene_ctx is not None and seg.startswith("scene:"):
                # ---- `T-117` ④（storyboard 同款 B1 修复）：段级重采只传坏段 ⇒
                #      重采场段的 `prev_scene_tail` 拿不到上一场产物，会拿到
                #      「本场为第一场，或上一场尚未产出」的**假降级文案**——
                #      与事实相反（上一场早已成功）。回退查 `prior_texts`
                #      （此前 attempt 已成功的段文本），与 script 侧 B1 修复同构。
                seg_vars.update(
                    self._scene_seg_vars(seg, scene_ctx, produced, prior_texts)
                )
            # ---- `T-116` script 逐场拆段：段级变量（范围声明／梗概场对象／head 锚点承继）----
            if script_ctx is not None and (
                seg == "package_head" or seg.startswith("scene:")
            ):
                seg_vars.update(
                    self._script_seg_vars(seg, script_ctx, produced, prior_texts)
                )
            storyboard_scope = "full"
            scoped_doc: dict[str, Any] | None = None
            if scope_ctx is not None and (
                seg == "package_head" or seg.startswith("unit:")
            ):
                scoped_doc, scope_warnings = scope_storyboard_for_segment(
                    seg, scope_ctx.get("storyboard") or {}
                )
                if scoped_doc is not None:
                    # 紧凑序列化（与 `_compact_upstream_json` 的「去空白」动机一致：
                    # 交给模型的是变量值，不是留档原文）
                    seg_vars["storyboard_json"] = json.dumps(
                        scoped_doc, ensure_ascii=False, separators=(",", ":")
                    )
                    storyboard_scope = "scoped"
                for note in scope_warnings:
                    logger.warning(
                        "segment_scope_fallback",
                        extra={
                            "extra_fields": {"segment": seg, "note": note}
                        },
                    )
            # ---- 引擎 schema 按段收窄（`T-101`／`PRO-015` §7：产出侧的结构闸）----
            # ⚠️ A 期实测证伪了「输入回声」主因：输入裁剪后 `package_head` 仍产出
            # 8,433 tokens（合并后头部仅 ≈1.2K）——产出体积由引擎 schema 的允许面决定。
            # 头部段 `units`/`shots` 上限 0；单元段 `units` 上限 1、`shots` 上限＝
            # 该单元在上游的镜数（`scoped_doc` 已算好）。超出上游的镜本来就该被判据拦
            # （`R31`/`R7`），这里只是把「事后判」升级为「事中不生成」。
            seg_schema = json_schema
            schema_capped = False
            # ---- `T-116` script 段级 schema 收窄：head 段＝head 键集＋幕骨架形态；
            #      场段＝场对象键集（无 `act_no`）。全量 script schema 会强制场段
            #      重出全部顶层键（含 style_bible 大对象），拆段动机被 schema 抵消。
            if script_ctx is not None and (
                seg == "package_head" or seg.startswith("scene:")
            ):
                # ---- `T-117` ②：dialogue 行数解码上限按 est 同源派生（est 异常 ⇒ None）----
                seg_schema = cap_script_schema_for_segment(
                    json_schema,
                    seg,
                    dialogue_max_items=_script_dialogue_max_items(script_ctx, seg),
                )
                schema_capped = seg_schema is not json_schema
            if scope_ctx is not None and scoped_doc is not None and isinstance(json_schema, dict):
                if seg == "package_head":
                    seg_schema = cap_pack_array_bounds(
                        json_schema, units_cap=0, shots_cap=0)
                    schema_capped = True
                elif seg.startswith("unit:"):
                    seg_shots = len(scoped_doc.get("shots") or [])
                    # `丙`：单元段可含**多单元组**（`unit:U01+U02`）⇒ 单元数上限按组宽，
                    # 不再硬编码 1（否则组段产物第 2 个单元会被 schema 截掉）。
                    seg_units = max(1, len(scoped_doc.get("units") or []))
                    seg_schema = cap_pack_array_bounds(
                        json_schema,
                        units_cap=seg_units,
                        # `丙` QA 证伪项（2026-11-17）：组段必须把单元数**下限**也钉到
                        # 组宽——否则模型少产一个单元、把其镜并入同场其它单元即可通过
                        # `R9`/`R10`/`R31`（实测全绿）。单单元段传 1 与旧行为等价。
                        units_floor=seg_units,
                        shots_cap=seg_shots,
                        # `R31`（镜数低于上游）裁决 2 修法 A：把镜数下限抬到上游镜数——
                        # 事后判 → 事中不可少写。B 期实测 on 臂 `pack_shots_lt_upstream`
                        # 2/11、`R31` 5/11（重试救回 3、失守 2）。
                        shots_floor=seg_shots,
                    )
                    schema_capped = True
            rendered = self.prompts.render(template, seg_vars)
            # ---- 乙：重采请求侧注入判据反馈（不改模板、不改产物；见 `_retry_feedback_text`）----
            # QA 结论 b（2026-11-17）：定位回退（`scope_fallback`）时反馈随**全段**注入，
            # 未失败段也会读到与本段无关的条目 ⇒ 前置「只纠正与本段相关者」免责句，防未
            # 失败段被反馈诱发改写（甲试点第 2 轮「重采产出更差样本」的同族风险）。
            prompt_text = f"[stage:{tpl_stage}]\n{rendered.as_text()}"
            if retry_feedback:
                note = (
                    "（失败未能定位到具体段：以下为本轮全段需注意的判据失败；"
                    "请只纠正与本段相关者，其余内容保持不变）\n" if retry_feedback_unlocated else ""
                )
                prompt_text = prompt_text + "\n\n" + note + retry_feedback
            # ---- 段级采样收紧（`ISSUE-084` 改判后 B3，DEV-20261113-006 续）----
            # ⚠️ 只动 `package_head` 段：该段是 `meta`／`style_bible`／`characters`
            # 等**元数据**，不是镜头创意正文，`SW-007` 的 0.7 只约束镜头正文。
            # ⚠️ QA 证伪 L3 修复：限定 `shot_prompt` 阶段——script 的 head 段承担
            #    **设计类创作**（`TPL-008` 硬性约束 5：外观／风格锚首定义），降温到
            #    0.4 是未声明的行为变化，不在本批授权面内（script head 维持模板
            #    采样 0.8；storyboard 本就无 `package_head` 段，行为不变）。
            seg_params = _params_of(template.sampling)
            if tpl_stage == "shot_prompt" and seg == "package_head":
                seg_params = _package_head_sampling(seg_params)
            # ---- `T-117` ①：script 段 `max_tokens` 按段收口（跑飞快速失败）----
            # ⚠️ 只动 `max_tokens` 不动温度：script head 是设计类创作（QA 证伪 L3
            #    裁决维持模板 0.8），scene 是正文创作；收口值给足正常产出余量
            #    （head 实测 822~1435 tok ⇒ 2048 ≈ 1.4×；scene 实测 235~389 tok
            #    ⇒ 4096 ≈ 10×），跑飞轮在此快速失败进按段重采，不再烧满 8192。
            elif tpl_stage == "script" and seg == "package_head":
                seg_params = _script_head_sampling(seg_params)
            elif tpl_stage == "script" and seg.startswith("scene:"):
                seg_params = replace(
                    seg_params,
                    max_tokens=min(seg_params.max_tokens, SCRIPT_SCENE_MAX_TOKENS),
                )
            # ---- `T-118` ②：下游段 `max_tokens` 按段收口（跑飞快速失败）----
            # 证据锚与授权面同 `T-117` ①（见常量区注释）：上限高于全部历史正常
            # stop 产出 ⇒ 正常轮零影响；跑飞轮不再烧满 12288/8192。
            elif tpl_stage == "storyboard" and seg.startswith("scene:"):
                seg_params = replace(
                    seg_params,
                    max_tokens=min(seg_params.max_tokens, STORYBOARD_SCENE_MAX_TOKENS),
                )
            elif tpl_stage == "shot_prompt" and seg.startswith("unit:"):
                seg_params = replace(
                    seg_params,
                    max_tokens=min(seg_params.max_tokens, SHOT_PROMPT_UNIT_MAX_TOKENS),
                )
            result = await backend.generate(
                prompt_text,
                seg_params,
                seg_schema,
            )
            produced[seg] = result.text
            prompt_tokens += result.prompt_tokens
            completion_tokens += result.completion_tokens
            trace.append(
                {
                    "segment": seg,
                    "chars": len(result.text),
                    "digest": digest(result.text, 12),
                    "finish_reason": result.finish_reason,
                    # ---- 段级输入裁剪留痕（`T-101`／`PRO-015`）----
                    # `scoped`＝本段注入的是裁剪副本；`full`＝整份（开关关／段名不匹配／裁剪回退）。
                    "storyboard_scope": storyboard_scope,
                    # 引擎 schema 是否按段收窄（`cap_pack_array_bounds`）——与输入裁剪同一开关族。
                    "schema_capped": schema_capped,
                    # ---- 段级 token 留痕（`ISSUE-058` 发生率统计的观测补强）----
                    # ⚠️ 此前 trace 只有 chars／finish_reason：502 截断轮**无产物落盘**，
                    #    「真 8192 跑满」与「其他原因」只能靠延迟推断（186s≈全量生成
                    #    时间）。补段级 token 后，截断归因可直接对账 usage。
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    # ---- 乙：本段采样是否带判据反馈（「注入了没有」必须可核查）----
                    "retry_feedback": bool(retry_feedback),
                    # ---- `T-117` ② 观测位：本段 dialogue 行数解码上限（非 script
                    #      场段为 None；截断轮可对账「预算数字是否合理」）----
                    "dialogue_max_items": (
                        _script_dialogue_max_items(script_ctx, seg)
                        if script_ctx is not None and seg.startswith("scene:")
                        else None
                    ),
                }
            )
        truncated = [t["segment"] for t in trace if t.get("finish_reason") == "length"]
        return produced, trace, prompt_tokens, completion_tokens, truncated

    def _scene_seg_vars(
        self,
        seg: str,
        scene_ctx: dict[int, dict[str, Any]],
        produced: dict[str, str],
        prior_texts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """`scene:<no>` 段的**逐场变量**（`T-100`／`PRO-014` §3.3）。

        ⚠️ 逐场变量**只补充"本段干什么"**，不裁剪全局上下文——`script_json` 仍整份注入
        （`character_refs`／`prop_refs`／风格一致性都依赖它）。裁了会出现「角色引用瞎编」的新失败类。
        """
        try:
            no = int(seg.split(":", 1)[1])
        except (IndexError, ValueError):
            return {}
        scene = scene_ctx.get(no) or {}
        total = len(scene_ctx)
        est = scene.get("est_seconds")
        floor = 2  # `R42` 每场下限（与 `R22`「场 ≥ 8s ＝ 4s × 2 镜」同源推导）
        if isinstance(est, (int, float)) and not isinstance(est, bool) and est > 0:
            ceiling = max(floor, int(est) // 4)  # 单镜下限 4s ⇒ 场秒数 ÷ 4
            budget = (
                f"本场 est_seconds = {int(est)} 秒 ⇒ 镜头数须在 **{floor} ~ {ceiling}** 之间"
                f"（下限＝最小合规单元 2 镜；上限＝⌊场秒数 ÷ 单镜下限 4s⌋）；"
                f"本场各镜 duration_ms 之和须 ≈ {int(est) * 1000} ms（允许 ±10%，超出须在 unspecified 说明）。"
            )
        else:
            budget = (
                f"本场 est_seconds 缺失 ⇒ 镜头数须 ≥ {floor} 镜，且各镜时长之和不得明显超出剧本该场预算。"
            )
        scope = (
            f"**单场模式**——本次调用**只**输出剧本第 {no} 场（共 {total} 场）的镜头。"
            f"其他场由别的调用负责：**不要写别的场、不要留占位、不要替别的场补内容**。"
            f"`shots[]` 与 `units[]` 只含本场；所有 `shots[].scene_no` 与 `units[].scene_no` "
            f"一律填 **{no}**；`shot_id` 形如 `S{no:02d}-SH<镜号三位>`（场号两位固定为 {no:02d}）。"
        )
        return {
            "scene_scope": scope,
            "scene_json": json.dumps(scene, ensure_ascii=False, indent=2),
            "prev_scene_tail": self._prev_scene_tail(no, produced, prior_texts),
            "scene_budget": budget,
        }

    @staticmethod
    def _prev_scene_tail(
        no: int,
        produced: dict[str, str],
        prior_texts: dict[str, str] | None = None,
    ) -> str:
        """上一场末镜摘要（跨场衔接的唯一信息来源；拿不到就如实说、并给保守口径）。

        ⚠️ `T-117` ④（storyboard 同款 B1 修复）：段级重采只传坏段 ⇒ 本批
        `produced` 不含上一场（早已成功）的产物，旧实现会注入「本场为第一场，
        或上一场尚未产出」的**假降级文案**——衔接参照凭空丢失，首镜 `transition_in`
        被误导为保守 `cut`。回退查 `prior_texts`（此前 attempt 的成功采样），
        最新成功值优先（`produced` 先查，与 script 侧 head 承继同构）。
        """
        raw = produced.get(f"scene:{no - 1}") or (prior_texts or {}).get(
            f"scene:{no - 1}"
        )
        if not raw:
            return "无（本场为第一场，或上一场尚未产出）——本场首镜 `transition_in` 填 `cut`。"
        try:
            doc = parse_json_object(raw)
        except AppError:
            return "（上一场产物不可解析）——本场首镜 `transition_in` 一律填 `cut`。"
        shots = doc.get("shots")
        if not isinstance(shots, list) or not shots:
            return "（上一场无镜头产出）——本场首镜 `transition_in` 一律填 `cut`。"
        last = shots[-1] if isinstance(shots[-1], dict) else {}
        action = last.get("action") if isinstance(last.get("action"), dict) else {}
        tail = (
            f"上一场（第 {no - 1} 场）末镜：`shot_id`={last.get('shot_id')}"
            f"；`action.end`={action.get('end')}"
            f"；`transition_out`={last.get('transition_out', '（省略）')}。"
            f"本场首镜的 `transition_in` 须与之衔接；无把握时填 `cut`。"
        )
        return tail

    def _script_seg_vars(
        self,
        seg: str,
        script_ctx: dict[str, Any],
        produced: dict[str, str],
        prior_texts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """`T-116` script 段**逐场拆段**的段级变量。

        ⚠️ 与 `_scene_seg_vars`（storyboard）**同构但不共用**：script 的 head 键含
        `style_bible`/`characters`/`props` 大对象 ⇒ 场段**不重出 head**，而是把
        head 段产物（锚点）解析后作为 `script_head_json` 注入给每个场段承继——
        重出既浪费又引入段间漂移。head 不可解析 ⇒ 降级文案＋场段按梗概自行定义
        （不静默假装锚点在），锚点一致性交判据判。

        ⚠️ 段间存在**前向依赖**（场段要承继 head 锚点）⇒ 逐场必须**串行**（与
        storyboard 的 `prev_scene_tail` 前向依赖同款，调用序已保证）。
        """
        scenes: dict[int, dict[str, Any]] = script_ctx.get("scenes") or {}
        if seg == "package_head":
            scope = (
                "**头部模式**——本次调用只输出全片锚点与幕骨架：`title`/`logline`/`genre`/"
                "`style_bible`/`characters`/`props` 与 `acts[]` 骨架（每幕含 `act_no`/`act_name`/"
                "`act_summary`/`scene_nos` 场号归属清单，**不含任何场内容**）与 `unspecified`。"
                "各场正文由别的调用负责：**不要写任何场的正文（action/dialogue 等）——"
                "output 节的 scenes[] 场对象示例是给整片/单场模式看的，本段不得照抄**。"
                "`acts[].scene_nos` **每幕至少 1 场**（不得空幕），并集必须恰好覆盖梗概 "
                "scenes_outline 的全部场号（不重不漏）。正确产物 ≈ 800~1500 tokens，写完即停。"
            )
            return {
                "scene_scope": scope,
                "scene_json": "",
                "script_head_json": "无（本段即头部段）",
            }
        try:
            no = int(seg.split(":", 1)[1])
        except (IndexError, ValueError):
            return {}
        scene = scenes.get(no) or {}
        total = len(scenes)
        est = scene.get("est_seconds")
        budget = (
            f"本场台词**总字数（含旁白/画外音）不得超过 {int(est) * DIALOGUE_SPEED_MAX} 字**"
            f"（est_seconds={int(est)} × 门禁上限 {DIALOGUE_SPEED_MAX} 字/秒，复测 r5 scene:3 "
            "两连截断实锤的收敛约束）；台词写完须自校验字数，超出就删冗余、合并短句。"
            if isinstance(est, (int, float)) and not isinstance(est, bool) and est > 0
            else "本场梗概 est_seconds 缺失——台词总量保守控制（总字数 ≤ 200 字）。"
        )
        scope = (
            f"**单场模式**——本次调用只输出剧本第 {no} 场（共 {total} 场）的**场对象**"
            f"（no/slug/location/time_of_day/present/props_present/action/sfx_hint/"
            f"dialogue/beat/purpose/est_seconds）。"
            f"其他场由别的调用负责：**不要写别的场、不要留占位、不要替别的场补内容**。"
            f"场号 `no` 恒为 **{no}**；**不输出 `act_no`**——幕归属由头部段的幕骨架决定，"
            f"本段无权判断。{budget}"
        )
        # ---- QA 证伪 B1 修复：本批 `produced` 缺 head（段级重采只传坏段）时回退查
        #      `prior_texts`（此前 attempt 已成功的采样）——最新成功值优先。
        head_raw = produced.get("package_head") or (prior_texts or {}).get(
            "package_head"
        )
        head_json = (
            "无（头部段尚未产出或不可解析）——外观与风格锚点由本段按梗概自行定义，"
            "并在 unspecified 中登记「头部锚点缺失」。"
        )
        if head_raw:
            try:
                doc = parse_json_object(head_raw)
            except AppError:
                doc = None
            if isinstance(doc, dict):
                anchors = {
                    k: doc[k]
                    for k in ("title", "logline", "genre", "style_bible", "characters", "props")
                    if k in doc
                }
                head_json = json.dumps(anchors, ensure_ascii=False, indent=2)
        return {
            "scene_scope": scope,
            "scene_json": json.dumps(scene, ensure_ascii=False, indent=2),
            "script_head_json": head_json,
        }

    def _retry_segments(
        self,
        plan: list[str],
        verdict: Any,
        texts: dict[str, str],
        tpl_stage: str = "",
    ) -> tuple[list[str], str | None]:
        """从门禁结论**定位要重跑的段**；定位不到就**回退为全部段**。

        `T-086` 采用的粒度是「按段」（项目方 2026-10-16 裁决）：分镜段约 130 s、
        提示词段约 304 s ⇒ 整阶段重跑的重试代价过高，而门禁报错里**通常带有定位信息**。

        定位规则（**宁多勿漏**）：
        1. 报错文本里出现的 `U<数字>` ⇒ 对应 `unit:Uxx` 段；
        2. 报错涉及包级/元数据（`meta.`／`total_duration_ms`／`package`）⇒ 加 `package_head` 段；
        3. 上一轮**解析失败或零贡献**的段 ⇒ 一律重跑（`_guard_segment_contributions` 的结论）；
        4. 一条都定位不到 ⇒ **回退为全部段**，并在留痕里标 `scope_fallback`
           （⚠️ 宁可多跑，不得漏跑 —— 漏跑＝那一段的缺陷被永久留下）。
        """
        from app.services.segment import HEAD_KEYS  # noqa: F401  （语义留痕用）

        if get_settings().quality_gate_retry_scope == "stage" or not is_multi_part(plan):
            # 单段计划（`plan == ["all"]`）时「按段」与「整阶段」等价，不必另行标注
            return list(plan), (None if len(plan) == 1 else "scope_stage")

        messages = list(verdict.retryable) if verdict is not None else []
        joined = " ".join(messages)
        # 单元 id 一律用词边界匹配：旧实现 `uid in joined` 会把 `U01` 命中到 `U010`
        # （独立 QA 2026-11-17 低优先级项；组段后误命中会放大成整组重采）。
        mentioned = set(re.findall(r"\bU\d{2,}\b", joined))
        picked: list[str] = []
        for seg in plan:
            if seg.startswith("unit:"):
                # `丙`：单元段可能是多单元组（`unit:U01+U02`）⇒ 段名整体（含 `+`）
                # 不可能出现在判据消息里，须逐 id 匹配（命中任一即重采该组）。
                uids = segment_unit_ids(seg)
                if not uids:
                    uid = seg.split(":", 1)[1]
                    if uid and uid in mentioned:
                        picked.append(seg)
                elif any(u in mentioned for u in uids):
                    picked.append(seg)
            # ---- `T-100` 逐场编排：按场定位（判据报错里的「场 k」与 shot_id 前缀两种形态）----
            # 真机形态：`R41`／`R42` 报「场 4 ...」；`R10`／`R11`／`R19` 报单元号或 `shot_id`。
            if seg.startswith("scene:"):
                no = seg.split(":", 1)[1]
                try:
                    prefix = f"S{int(no):02d}-"
                except ValueError:
                    prefix = ""
                if f"场 {no}" in joined or (prefix and prefix in joined):
                    picked.append(seg)
        # ---- `T-101`／`PRO-015`：shot_id 定位（`R34` 等判据**只列 shot_id**，无 `U` 字面）----
        # 885s 轮实锤：`R34` 报「S02-SH002；S03-SH002；…」⇒ 规则 1 的 `U` 字面定位不到
        # ⇒ `scope_fallback` **全部 6 段重跑**（第 2 次 17.2K completion 基本白烧）。
        # 定位①（包含关系）：shot 的属主段必含其 id——报错 shot_id 出现在某段产物文本
        #   ⇒ 该段重跑（无需全局映射表）；
        # 定位②（场前缀兜底，**宁多勿漏**）：`S<场>-` 前缀 → 场号 → 段产物 `units[].scene_no`
        #   命中即重跑——覆盖「镜整段没生成出来、任何段文本里都找不到」的形态。
        #   解析失败的段交给下方「解析失败 ⇒ 必须重跑」规则统一兜（不在②里抢跑）。
        err_shot_ids = sorted(set(re.findall(r"S\d{2}-SH\d{3}", joined)))
        if err_shot_ids:
            for seg in plan:
                if seg.startswith("unit:") and any(
                    sid in texts.get(seg, "") for sid in err_shot_ids
                ):
                    picked.append(seg)
            scene_hits = {int(m) for m in re.findall(r"S(\d{2})-SH", joined)}
            if scene_hits:
                for seg in plan:
                    if seg in picked or not seg.startswith("unit:"):
                        continue
                    try:
                        doc = parse_json_object(texts.get(seg, ""))
                    except AppError:
                        continue
                    for u in doc.get("units") or []:
                        if isinstance(u, dict) and u.get("scene_no") in scene_hits:
                            picked.append(seg)
                            break
        # ---- 乙：unit→scene 映射（`storyboard` 段 plan=`scene:N`，报错只提 `U<id>`）----
        # ⚠️ 甲试点实锤（`DEV-20261117-001`）：retryable 明写 `U02`，旧规则只能靠
        # 「场 N」／`S<场>-SH` 字面命中 ⇒ 打偏到 `scene:1`。这里从上一轮**各段产物文本**
        # 解析 `units[].unit_id`／`shots[].unit_id`，把被点名的单元映射回所属场。
        # 宁多勿漏：同一 id 出现在多个场（不应发生，发生了就多场都重采）。
        mentioned_units = set(re.findall(r"\bU\d{2,}\b", joined))
        if mentioned_units:
            for seg in plan:
                if seg in picked or not seg.startswith("scene:"):
                    continue
                try:
                    seg_doc = parse_json_object(texts.get(seg, ""))
                except AppError:
                    continue
                if not isinstance(seg_doc, dict):
                    continue
                unit_ids: set[str] = set()
                for u in seg_doc.get("units") or []:
                    if isinstance(u, dict) and u.get("unit_id"):
                        unit_ids.add(str(u["unit_id"]))
                for s in seg_doc.get("shots") or []:
                    if isinstance(s, dict) and s.get("unit_id"):
                        unit_ids.add(str(s["unit_id"]))
                if unit_ids & mentioned_units:
                    picked.append(seg)
        # ---- `T-116` script 拆段定位（QA 证伪 L1/O5 修复；`quality_gate_stages`
        #      默认含 `script` ⇒ 本分支可达，不是防御性代码）：
        # ① script 域词 ⇒ head 段（head 承担锚点与幕骨架）；
        # ② `acts[i]` 索引 → 上一轮 head 产物的骨架 `scene_nos` → 对应场段
        #    （script 判据报错形态是 `acts[i].scenes[j].…`，无场号字面）。
        # 宁多勿漏口径不变：定位不到 ⇒ 回退全部段（scope_fallback）。
        if tpl_stage == "script":
            if any(
                k in joined
                for k in (
                    "style_bible", "logline", "genre", "characters", "props",
                    "total_est_seconds", "forbidden_items", "unspecified", "acts",
                )
            ):
                if "package_head" in plan:
                    picked.append("package_head")
            act_idx = {int(m) for m in re.findall(r"acts\[(\d+)\]", joined)}
            if act_idx and "package_head" in texts:
                try:
                    head_doc = parse_json_object(texts["package_head"])
                except AppError:
                    head_doc = None
                acts_list = head_doc.get("acts") if isinstance(head_doc, dict) else None
                if isinstance(acts_list, list):
                    for i in act_idx:
                        if not 0 <= i < len(acts_list) or not isinstance(acts_list[i], dict):
                            continue
                        for no in acts_list[i].get("scene_nos") or []:
                            seg = f"scene:{no}"
                            if seg in plan and seg not in picked:
                                picked.append(seg)
            if "scene:" in joined or re.search(r"场\s*\d+", joined):
                for seg in plan:
                    no = seg.split(":", 1)[1] if seg.startswith("scene:") else ""
                    if no and (f"scene:{no}" in joined or f"场 {no}" in joined):
                        picked.append(seg)
        if any(k in joined for k in ("meta.", "total_duration_ms", "package_head", "package")):
            if "package_head" in plan:
                picked.append("package_head")
        # ---- QA 证伪 L1 修复：零贡献键集按阶段取表（与 `_guard_segment_contributions`
        #      同源同族——`HEAD_KEYS` 是交付包键，script 场段一个都没有 ⇒ 旧表会把
        #      script 全部场段误判零贡献强制重烧）。
        if tpl_stage == "script":
            contributable = set(SCRIPT_HEAD_TOP_KEYS) | set(SCRIPT_SCENE_KEYS) | {"scenes"}
        else:
            contributable = set(HEAD_KEYS) | {"units", "shots"}
        for seg in plan:
            text = texts.get(seg, "")
            try:
                doc = parse_json_object(text)
            except AppError:
                picked.append(seg)  # 解析失败 ⇒ 必须重跑
                continue
            if isinstance(doc, dict) and not any(doc.get(k) for k in contributable):
                picked.append(seg)  # 零贡献 ⇒ 必须重跑
        uniq = [s for s in plan if s in set(picked)]
        if not uniq:
            return list(plan), "scope_fallback"
        return uniq, None

    @staticmethod
    def _retry_feedback_text(attempt: int, verdict: Any, limit: int = 8) -> str | None:
        """**乙**（2026-11-17 裁决「先甲后乙」）：构造重采请求的**判据反馈**文本。

        ⚠️ 只带 **retryable** 明细（non_retryable 是「重试改了也白改」项，放进反馈会
        诱导模型去撞死路）；每条截断 ≤200 字符、最多 `limit` 条——反馈是**指向灯**，
        不是全文回显（甲试点之前的「全文重注」曾被 v2.2.1 事故证伪：模型会抄错值）。
        ⚠️ 措辞（QA 结论 d 附带发现）：注入对象是**下一次**请求 ⇒ 写「上一轮（第 N 次
        尝试）产物」，不得写「这是第 N 次尝试」（会让第 2 次采样读到「这是第 1 次」）。
        ⚠️ 返回 `None`＝无可反馈内容（retryable 空），调用方不得注入空块。
        """
        items = [str(x) for x in (getattr(verdict, "retryable", None) or []) if str(x).strip()]
        if not items:
            return None
        lines = [
            "[整改反馈] 上一轮（第 %d 次尝试）产物以下交付判据未通过，本轮必须逐条纠正：" % attempt,
        ]
        lines += ["- %s" % s[:200] for s in items[:limit]]
        if len(items) > limit:
            lines.append("- （另有 %d 条同类失败未列出，本轮须同样避免）" % (len(items) - limit))
        lines.append("未列出的内容保持不变；输出仍必须是符合引擎 schema 的合法 JSON。")
        return "\n".join(lines)

    @staticmethod
    def _retry_targets_inherited_moves(tpl_stage: str, verdict: Any) -> bool:
        """**乙**：本段（`shot_prompt` 形态 `pack`）的 retryable 是否**全部**为承继字段失败。

        ⚠️ 全部命中 `_INHERITED_MOVE_MARKERS` 才跳过：混合形态（如 `R11` 运镜＋`R35`
        道具锚）里后者本段可修 ⇒ 照常重试（反馈文本里本段可修项照带）。
        ⚠️ 跳过 ≠ 放行：判定照旧走 `gate_failed` 分支如实留痕／如实拒绝，
        改变的只是「要不要在本段白烧一次重采」。
        ⚠️ 标记清单为什么只有 `R11`：见模块常量 `_INHERITED_MOVE_MARKERS` 的注释
        （QA 结论 A1／缺口 5／A2，2026-11-17）。
        """
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) != "pack":
            return False
        items = [str(x) for x in (getattr(verdict, "retryable", None) or [])]
        if not items:
            return False
        return all(any(m in x for m in _INHERITED_MOVE_MARKERS) for x in items)

    def _apply_service_truth(
        self, tpl_stage: str, text: str, rec: SessionRecord, backend: Any,
        guard_input: dict[str, Any] | None,
        guard_output: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any] | None]:
        """交付包产物的**服务层真值覆盖**（`T-086` 配套；项目方 2026-10-16 裁决）。

        背景（实测发现，**合规级**）：模型会把服务层刻意留的占位**补成看起来已通过的假值**
        （`safety_check:"passed"`／`marking_check.explicit:"present"`／`statement_id:"ST-001"`）
        ⇒ 产物**看起来已过内容安全与标识校验，而平台根本没做**。详情见
        `app/services/pack_meta.py::apply_service_truth`。

        ⚠️ 覆盖**只针对服务层域字段**；模型可影响字段一字不改（本层第一纪律）。
        ⚠️ `aigc_meta.AIGC.ProduceID` **必须与覆盖后的 `meta.pack_id` 同源** ——
           否则会把「模型自拟但恰好一致」换成「覆盖后不一致」，**制造新的 BLOCK**。
        """
        shape = artifact_contract.STAGE_TO_SHAPE.get(tpl_stage)
        if shape != "pack" or not get_settings().service_truth_override:
            return text, None
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None  # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        truth = build_pack_meta(
            session_id=rec.session_id,
            stage=tpl_stage,
            templates=[{"id": self.prompts.by_stage(tpl_stage).id,
                        "version": self.prompts.by_stage(tpl_stage).version}],
            # ⚠️ **语义修正**（2026-11-03 真机实测）：schema 真相源（官方样例
            #    `CFG-004_demo_pack.json`）是 `name`＝**模型名**／`backend`＝**后端枚举**
            #    ／`revision`＝模型 revision。⚠️ 而 `backend.name` 是**后端标识**
            #    （`vllm`）、`backend.version` 是**模型名**（`inference/base.py`）
            #    ⇒ 原写法 `{"name": backend.name, ...}` 把后端名填进了 `name`，
            #    与 schema 语义**正好相反** ⇒ 真机产物过门禁报 BLOCK。
            model={
                "name": backend.version or "unknown",
                "backend": backend.name if backend.name in
                           ("vllm", "transformers", "llama_cpp", "remote_api") else "other",
                "revision": backend.version or "unknown",
            },
            settings=get_settings(),
            artifacts=rec.artifacts,
            title=rec.source_input[:30],
            safety={"input": guard_input, "output": guard_output},
        )
        overrides = apply_service_truth(
            doc, truth,
            provider_name=get_settings().provider_name,
            provider_code=get_settings().provider_code,
        )
        if not overrides:
            return text, None
        return json.dumps(doc, ensure_ascii=False), overrides

    def _apply_derived_backfill(
        self, tpl_stage: str, text: str, gate_upstream: dict[str, str] | None = None
    ) -> tuple[str, dict[str, Any] | None]:
        """**派生量**的确定性回填（`R14`／`R4`／`R31` 总量守恒 ＋ `R8` 场内镜号序列 ＋ `R24` 道具覆盖；2026-11-04 授权落地，`R8`/`R24` 于 2026-11-05 同构扩展）。

        背景（实测，`ISSUE-038` ＋ `PRO-011` 真基线）：`total_duration_ms`／
        `total_est_seconds` 是**跨字段算术**——「等于子项之和」。这类约束
        **受约束解码表达不了**（schema 只能约束单字段取值，无法表达字段间求和），
        提示词路线已**四版四错**（v2.2.0 散文条款／v2.2.1 给自洽字面值 `18200`／
        v2.2.2 归零 ＋ 算式紧邻示例），真机三种样本 **3/3** 产物 `total_duration_ms`
        **恒为 `0`**（照抄骨架）；`script` 的 `total_est_seconds` 真基线 **3/3 轮**
        与 Σ 各场不等；交付包 `meta.total_duration_ms` 真基线 **2/2 轮**失守。

        ⚠️ **不改判据**：`R14`／`R4`／`R31` 一字未动；回填后它们判的是
        「回填结果是否守恒」。
        ⚠️ **不改创作**：只改**由子项唯一决定**的量，镜数／时长／运镜／场内容均不动。
        ⚠️ **必须留痕**：模型原值一并记入 `derived_backfill`——否则等于**悄悄改产物**，
           而「产物被动过却查不出来」比「字段填错」更危险（本层第一纪律）。
        ⚠️ 生效时产物会**重新序列化**（`json.dumps(ensure_ascii=False)`，与交付包 `pack`
           的真值覆盖同口径）：只影响空白与缩进，不改语义、不改键序。
        ⚠️ 分段开关（`PRO-011` 附 4 真值归属方案 A）：`storyboard_derived_backfill`（`R14`，
           2026-11-04 项目方裁决）· `script_derived_backfill`（`R4`，含 `synopsis` 形态）·
           `pack_derived_backfill`（`R31` 算术侧）· `storyboard_shot_no_backfill`（`R8`，
           2026-11-05 同构扩展）· `storyboard_prop_coverage_backfill`（`R24`，2026-11-05
           同构扩展、需 `gate_upstream` 的剧本原文）各自独立、默认 `true`。
        """
        settings = get_settings()
        if tpl_stage == "storyboard":
            # 三项派生量各自独立回填（R14 总量守恒 ＋ R8 场内镜号序列 ＋ R24 道具覆盖），
            # 留痕合并进同一个 `derived_backfill` 字典（键不冲突：
            # `total_duration_ms` vs `shots[].shot_no` vs `shots[].prop_refs`）。
            backfills: dict[str, Any] = {}
            if settings.storyboard_derived_backfill:
                text, rec = self._backfill_total_sum(
                    text, rule="R14", field="total_duration_ms",
                    item_field="duration_ms", item_label="shot_count",
                )
                if rec:
                    backfills.update(rec)
            if settings.storyboard_shot_no_backfill:
                text, rec = self._backfill_shot_no_seq(text)
                if rec:
                    backfills.update(rec)
            if settings.storyboard_prop_coverage_backfill:
                script_text = (gate_upstream or {}).get("script")
                if script_text:
                    text, rec = self._backfill_prop_coverage(text, script_text)
                    if rec:
                        backfills.update(rec)
            return text, (backfills or None)
        if tpl_stage in ("script", "synopsis"):
            if not settings.script_derived_backfill:
                return text, None
            return self._backfill_total_sum(
                text, rule="R4", field="total_est_seconds",
                item_field="est_seconds", item_label="scene_count",
            )
        if tpl_stage == "shot_prompt":
            if not settings.pack_derived_backfill:
                return text, None
            return self._backfill_total_sum(
                text, rule="R31", field="meta.total_duration_ms",
                item_field="duration_ms", item_label="shot_count",
            )
        return text, None

    def _backfill_total_sum(
        self,
        text: str,
        *,
        rule: str,
        field: str,
        item_field: str,
        item_label: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """按「`field` ＝ Σ 子项 `item_field`」复算覆写（三段共用，逐段开关在调用方）。

        子项定位与判据同源：`storyboard`／`pack` 取 `shots[]`；`script` 取
        `acts[].scenes[]`；`synopsis` 取 `scenes_outline[]`（与 `validate_output.py`
        的 `iter_scenes` 同口径）。子项值**非整数**时**不兜底**（交 `R12`／`R13`
        等对应判据判），只如实留痕 `skipped`。
        """
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None          # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        # ---- 取子项值 ----
        vals: list[int] = []
        if field.startswith("meta."):
            shots = doc.get("shots")
            container = doc.get("meta") if isinstance(doc.get("meta"), dict) else None
            if not isinstance(shots, list) or not shots or container is None:
                return text, None
        elif field == "total_est_seconds":
            # `script`（acts[].scenes[]）与 `synopsis`（scenes_outline[]）同游标（R4 口径）
            scenes: list[Any] = []
            if "acts" in doc:
                for act in doc.get("acts") or []:
                    if isinstance(act, dict):
                        scenes.extend(act.get("scenes") or [])
            else:
                scenes = list(doc.get("scenes_outline") or [])
            if not scenes:
                return text, None
            shots = scenes
            container = doc
        else:
            shots = doc.get("shots")
            container = doc
            if not isinstance(shots, list) or not shots:
                return text, None
        for it in shots:
            v = it.get(item_field) if isinstance(it, dict) else None
            if isinstance(v, bool) or not isinstance(v, int):
                # 非整数时长／秒数属对应判据（`R12`／`R13` 等）的判定对象，**不在此处兜底**
                return text, {field: {
                    "field": field, "rule": rule, "changed": False,
                    "action": "skipped_non_integer_item",
                    "note": f"存在非整数 {item_field} ⇒ 交对应判据判，本层不回填",
                }}
            vals.append(v)
        computed = sum(vals)
        # ---- 取原值（支持 `meta.` 前缀的嵌套目标）----
        if field.startswith("meta."):
            sub = field.split(".", 1)[1]
            original = container.get(sub)
        else:
            original = container.get(field)
        record: dict[str, Any] = {
            "field": field, "rule": rule,
            "original": original, "computed": computed,
            "changed": original != computed,
            item_label: len(vals),
            "action": "recomputed" if original != computed else "noop",
        }
        if original == computed:
            return text, {field: record}
        if field.startswith("meta."):
            container[field.split(".", 1)[1]] = computed
        else:
            doc[field] = computed
        return json.dumps(doc, ensure_ascii=False), {field: record}

    def _backfill_shot_no_seq(self, text: str) -> tuple[str, dict[str, Any] | None]:
        """`R8`（`shots[].shot_no` 场内从 1 连续）的确定性回填（2026-11-05 落地，`T-087` 余项）。

        ⚠️ **为什么是派生量**：`shot_no` 是**位置投影**——`TPL-010` 数量要求 1 明写
           「`shots` 的顺序即全片镜序」，故场内第 k 个镜头的 `shot_no` 恒等于 k，
           由数组结构**唯一决定**（与 `R14`「总量＝Σ 子项」同类的字段间/字段-结构
           算术，受约束解码表达不了）。真基线反证：2026-11-04 冒烟（`sess_2738d84570fe`
           storyboard 第 2 轮）实测模型按**单元内**编号产出 `[1,1,2,2]`——
           提示词「场内连续编号」条款（v2.2.0 起一直在）拦不住 7B 对编号的自配解读。
        ⚠️ **比 `R14` 多一层承重性**：`shot_no` 是**排序键**——`segment.py` 镜序
           （`scene_no → shot_no` 升序）、`export_models.py`／`E4` 导出序都吃它；
           单元内编号会让场景级排序出现平键、按 `shot_id` 兜底成**错序**。回填把
           排序键修回与镜序（数组序）一致。
        ⚠️ **不改创作**：只重编编号，不动 `shots` 的顺序／内容／单元归属；
           数组序本身是模型的创作声明，回填只是把它投影成判据要的连续整数。
        ⚠️ **必须留痕**：模型原值（按 `shot_id` 键控、只记被改动的镜头）记入
           `derived_backfill["shots[].shot_no"]`——否则等于悄悄改产物（第一纪律）。
        ⚠️ **非整数场景号不兜底**：任一头 `scene_no` 不是整数（分组语义已破坏）
           ⇒ 如实留痕 `skipped_non_integer_scene_no`、交由 `R8`/`R9` 判。
        """
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None          # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        shots = doc.get("shots")
        if not isinstance(shots, list) or not shots:
            return text, None
        for r in shots:
            if not isinstance(r, dict) or isinstance(r.get("scene_no"), bool) \
                    or not isinstance(r.get("scene_no"), int):
                return text, {"shots[].shot_no": {
                    "field": "shots[].shot_no", "rule": "R8", "changed": False,
                    "action": "skipped_non_integer_scene_no",
                    "note": "存在非整数 scene_no ⇒ 场内分组语义已破坏，交 R8/R9 判，本层不回填",
                }}
        counters: dict[int, int] = {}
        changed: dict[str, Any] = {}
        for idx, r in enumerate(shots):
            sc = r["scene_no"]
            counters[sc] = counters.get(sc, 0) + 1
            want = counters[sc]
            old = r.get("shot_no")
            if old != want:
                key = r.get("shot_id") if isinstance(r.get("shot_id"), str) else f"shots[{idx}]"
                changed[key] = old
                r["shot_no"] = want
        record: dict[str, Any] = {
            "field": "shots[].shot_no", "rule": "R8",
            "changed": bool(changed),
            "action": "renumbered" if changed else "noop",
            "scene_count": len(counters),
            "shot_count": len(shots),
        }
        if changed:
            record["original"] = changed
        if not changed:
            return text, {"shots[].shot_no": record}
        return json.dumps(doc, ensure_ascii=False), {"shots[].shot_no": record}

    def _backfill_prop_coverage(
        self, text: str, script_text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """`R24`（道具覆盖：某场 `props_present` 非空 ⇒ 该场至少一镜标进 `prop_refs`）的
        确定性回填（2026-11-05 落地，`T-087` 余项后续）。

        ⚠️ **为什么是派生量**：道具「在场」由**上游剧本声明**（`scenes[].props_present`），
           分镜层的义务（`BR-03`「有道具入画必标」）只是把它落到镜——「该场至少一镜」
           是上游数据的**逻辑后承**（与 `R8` 位置投影同类：结构＋上游唯一决定）。
           「补进哪一镜」是创作决策，本回填用**约定**承担：该场**首镜**（数组序第一个，
           建立镜惯例——该场出场面的第一镜最可能拍到在场景物）。
           真基线反证：2026-11-05 冒烟（`sess_dac62518e40c` storyboard 第 2 轮）实测
           场 4 `props_present=['PRP-01']` 而该场无一镜标出——`TPL-010` 数量要求 14
           「有道具入画必标」条款（v2.1.0 起一直在）拦不住 7B 的漏标。
        ⚠️ **与纯算术回填的差异（如实标注）**：`R14` 纯算术、`R8` 纯位置投影；
           本项是「上游声明 × 场首镜约定」的**语义层投影**——承载镜选择是约定而非
           唯一真值，故留痕必须完整（模型原 `prop_refs` 按 `shot_id` 键控全记）。
        ⚠️ **不改创作**：只补**缺失的** `prop_id`（已标的绝不动、不重排、不去重改写）；
           `prop_refs` 只引用剧本已定义的 `prop_id`，不新增道具。
        ⚠️ **必须留痕**：`derived_backfill["shots[].prop_refs"]`——否则等于悄悄改产物
           （第一纪律）。
        ⚠️ **场无镜头不兜底**：该场在 `shots` 中无任一镜（3 镜吸引子等场覆盖缺失形态）
           ⇒ 留痕 `skipped_scene_without_shots`、交 `R24`/场覆盖判据如实判——本回填
           不制造「道具已覆盖」的假象。
        ⚠️ 语义镜像 `validate_output.py` 的 `_upstream_props_by_scene`（剧本场键＝
           `acts[].scenes[].no`／`scenes_outline[].no`；分镜镜键＝`scene_no`）。
        """
        try:
            doc = parse_json_object(text)
            script = parse_json_object(script_text)
        except AppError:
            return text, None          # 解析不了由形态闸/上游准入闸报出（不抢先归因）
        if not isinstance(doc, dict) or not isinstance(script, dict):
            return text, None
        shots = doc.get("shots")
        if not isinstance(shots, list) or not shots:
            return text, None
        # ---- 上游场→props（与判据 `_upstream_props_by_scene` 逐字同口径）----
        pres: dict[Any, list] = {}
        for act in (script.get("acts") or []):
            if not isinstance(act, dict):
                continue
            for sc in (act.get("scenes") or []):
                if isinstance(sc, dict):
                    pres[sc.get("no")] = sc.get("props_present") or []
        for sc in (script.get("scenes_outline") or []):
            if isinstance(sc, dict):
                pres.setdefault(sc.get("no"), sc.get("props_present") or [])
        pres = {k: v for k, v in pres.items() if v}
        if not pres:
            return text, None
        # ---- 本层场→已标道具并集（只认 list[str] 的 prop_refs）----
        def _refs(r: dict) -> set:
            v = r.get("prop_refs")
            if isinstance(v, list):
                return {x for x in v if isinstance(x, str)}
            return set()

        by_scene: dict[Any, list[dict]] = {}
        for r in shots:
            if isinstance(r, dict):
                by_scene.setdefault(r.get("scene_no"), []).append(r)
        changed: dict[str, Any] = {}
        skipped_scenes: list[Any] = []
        covered_scenes = 0
        for s, need in pres.items():
            need_set = {p for p in need if isinstance(p, str)}
            scene_shots = by_scene.get(s)
            if not scene_shots:
                skipped_scenes.append(s)      # 场覆盖缺失（吸引子形态）⇒ 不造假，交判据
                continue
            got: set = set()
            for r in scene_shots:
                got |= _refs(r)
            miss = sorted(need_set - got)
            if not miss:
                covered_scenes += 1
                continue
            first = scene_shots[0]            # 场首镜（数组序第一个）承载约定
            key = first.get("shot_id") if isinstance(first.get("shot_id"), str) \
                else f"shots[{shots.index(first)}]"
            changed[key] = list(first.get("prop_refs") or []) \
                if isinstance(first.get("prop_refs"), list) else None
            first["prop_refs"] = sorted(set(_refs(first)) | set(miss))
            covered_scenes += 1
        record: dict[str, Any] = {
            "field": "shots[].prop_refs", "rule": "R24",
            "changed": bool(changed),
            "action": "covered_first_shot" if changed else "noop",
            "scene_with_props": len(pres),
            "scene_covered": covered_scenes,
        }
        if changed:
            record["original"] = changed
        if skipped_scenes:
            record["skipped_scene_without_shots"] = skipped_scenes
        if not changed:
            return text, {"shots[].prop_refs": record}
        return json.dumps(doc, ensure_ascii=False), {"shots[].prop_refs": record}

    def _normalize_storyboard_identity(
        self, tpl_stage: str, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """**分镜标识归一化**（`R7`／`R9` 的派生量；`T-100` 配套，2026-11-05 授权代决）。

        为什么是派生量
        --------------
        `shot_id` 的格式 `S<场号两位>-SH<镜号三位>`（`R7`）是 `scene_no` 与**数组序位**的
        **纯函数**——与 `R8` 的 `shot_no`（场内位置投影）同族。逐场编排下每次调用各自从
        `S01-SH001` 起编，跨场必然重号；而 `merge_segments` 的 `setdefault` 语义会把重号
        静默丢成一份（丢哪一场取决于遍历顺序）。

        两条纪律
        --------
        - **不猜**：`scene_no` 非整数的镜头**不重编**（分组语义已破坏），如实留痕；
        - **不洗白**：`units[].shot_ids` 与 `shots[].unit_id` 不是双向一致时（`R9` 已失败），
          `unit_id` **不重编**——否则会把链接错误改成"看起来对了"，掩掉真实缺陷。

        ⚠️ 本方法**不改任何创作字段**（`action`／`camera`／`duration_ms` 等一字不动），
        只写标识；且位置在**合并后、门禁前**（门禁要判最终入库的那一份）。
        """
        if not get_settings().storyboard_identity_normalize:
            return text, None
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) != "storyboard":
            return text, None
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None  # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        shots = doc.get("shots")
        units = doc.get("units")
        if not isinstance(shots, list) or not isinstance(units, list):
            return text, None

        # ---- ① `shot_id`：按场内数组序重编（`R7`）----
        # ⚠️ 映射键**必须带场号**：逐场编排下各场都从 `S01-SH001` 起编，只按旧串映射会串场
        #    （实测：把第 1 场单元的 `shot_ids` 改成了第 2 场的编号）。
        old_to_new: dict[tuple[Any, str], str] = {}
        counter: dict[int, int] = {}
        renamed_shots = 0
        skipped_non_int = 0
        samples: dict[str, str] = {}
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            scene_no = shot.get("scene_no")
            if not isinstance(scene_no, int) or isinstance(scene_no, bool):
                skipped_non_int += 1
                continue
            counter[scene_no] = counter.get(scene_no, 0) + 1
            new_id = f"S{scene_no:02d}-SH{counter[scene_no]:03d}"
            old_id = shot.get("shot_id")
            if old_id != new_id:
                if isinstance(old_id, str) and old_id:
                    old_to_new[(scene_no, old_id)] = new_id
                shot["shot_id"] = new_id
                renamed_shots += 1
                if len(samples) < 5:
                    samples[f"{scene_no}:{old_id}"] = new_id

        # ---- ② `units[].shot_ids` 随 `shot_id` 同步映射（否则 `R9` 的链接会断）----
        renamed_units_refs = 0
        for unit in units:
            if not isinstance(unit, dict):
                continue
            ids = unit.get("shot_ids")
            if not isinstance(ids, list):
                continue
            scene_no = unit.get("scene_no")
            mapped = [
                old_to_new.get((scene_no, x), x) if isinstance(x, str) else x for x in ids
            ]
            if mapped != ids:
                unit["shot_ids"] = mapped
                renamed_units_refs += 1

        # ---- ③ `unit_id`：按 `(scene_no, 原 unit_id)` 定位后重编（`R9`）----
        # ⚠️ 为什么带 `scene_no`：逐场编排下**各场独立从 U01 起编**是必然形态，
        #    合并后同名不同场。只按名字重编会把两个场的单元混成一个（正是要消灭的错）。
        unit_keys: list[tuple[Any, str]] = []
        declared: dict[tuple[Any, str], list[str]] = {}
        for unit in units:
            if not isinstance(unit, dict):
                continue
            uid = unit.get("unit_id")
            if uid in (None, ""):
                continue
            key = (unit.get("scene_no"), str(uid))
            if key in declared:
                continue  # 同场同名单元：无法区分，交 R9 判
            unit_keys.append(key)
            declared[key] = [x for x in (unit.get("shot_ids") or []) if isinstance(x, str)]
        claims: dict[tuple[Any, str], list[str]] = {}
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            uid, sid = shot.get("unit_id"), shot.get("shot_id")
            if isinstance(uid, str) and isinstance(sid, str):
                claims.setdefault((shot.get("scene_no"), uid), []).append(sid)
        consistent = set(claims).issubset(set(declared)) and all(
            set(claims.get(key, [])) == set(ids) for key, ids in declared.items()
        )
        unit_map: dict[tuple[Any, str], str] = {}
        renamed_units = 0
        unit_record: dict[str, Any] = {"rule": "R9", "changed": False}
        if not unit_keys:
            unit_record["skipped"] = "units_empty"
        elif not consistent:
            unit_record["skipped"] = "unit_shot_link_inconsistent（交 R9 判，不重编）"
        else:
            for i, key in enumerate(unit_keys, start=1):
                if key[1] != f"U{i:02d}":
                    unit_map[key] = f"U{i:02d}"
                    renamed_units += 1
            if unit_map:
                for unit in units:
                    if isinstance(unit, dict):
                        key = (unit.get("scene_no"), str(unit.get("unit_id")))
                        if key in unit_map:
                            unit["unit_id"] = unit_map[key]
                for shot in shots:
                    if isinstance(shot, dict):
                        key = (shot.get("scene_no"), str(shot.get("unit_id")))
                        if key in unit_map:
                            shot["unit_id"] = unit_map[key]
            unit_record["changed"] = bool(unit_map)
            unit_record["renumbered"] = renamed_units

        shot_record: dict[str, Any] = {
            "rule": "R7",
            "field": "shots[].shot_id",
            "changed": bool(renamed_shots or renamed_units_refs),
            "renumbered": renamed_shots,
            "unit_shot_ids_remapped": renamed_units_refs,
        }
        if samples:
            shot_record["original_sample"] = samples
        if skipped_non_int:
            shot_record["skipped_non_integer_scene"] = skipped_non_int

        if not (shot_record["changed"] or unit_record["changed"] or unit_record.get("skipped")):
            return text, {
                "shots[].shot_id": {**shot_record, "action": "noop"},
                "units[].unit_id": {**unit_record, "action": "noop"},
            }
        return json.dumps(doc, ensure_ascii=False), {
            "shots[].shot_id": shot_record,
            "units[].unit_id": unit_record,
        }


    def _normalize_camera_amp_speed(
        self, tpl_stage: str, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """**`camera.amp_speed` 机械清洗**（`T-103` 结构性档；2026-11-12 项目方裁决允许）。

        为什么改模型产物
        ----------------
        `delivery/validate_pack.py` ⑯：`camera.move ∈ {static, pov}` 时不得携带
        `amplitude`／`speed`（静态机位无运镜幅度/速度，语义互斥）。实测 14/14 镜
        模型**习惯性全填**档位、`xgrammar` 不支持 if-then 条件约束 ⇒ 生成期拦不住；
        两次 attempt 均报、重试不可自愈（`DEV-20261109-005` §3）。

        允许边界（裁决口径三件）
        ----------------------
        - **只删机械字段**：`amplitude`／`speed` 是枚举档位，不承载创作意图；`camera.move`／
          `from`／`to`／`action.*` 一字不动，删后镜头语义不变；
        - **不静默**：逐镜留痕（镜号／删的键／删前值）＋ 删前删后正文摘要，
          并追加一条 `merge_warnings`，门禁报告可查「N 镜经机械清洗后通过」；
        - **位置在引擎响应归一化层**（合并后、门禁前），与 `T-100` 标识归一化同层。
        """
        if not get_settings().camera_amp_speed_normalize:
            return text, None
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) not in ("storyboard", "pack"):
            return text, None
        no_amp = _camera_no_amp_moves()
        if not no_amp:
            return text, None
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None  # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        shots = doc.get("shots")
        if not isinstance(shots, list):
            return text, None

        before_digest = digest(text)
        items: list[dict[str, Any]] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            cam = shot.get("camera")
            if not isinstance(cam, dict):
                continue
            move = cam.get("move")
            if move not in no_amp:
                continue
            removed = {k: cam[k] for k in ("amplitude", "speed") if k in cam}
            if not removed:
                continue
            for k in removed:
                del cam[k]
            items.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "move": move,
                    "removed_keys": sorted(removed),
                    "original": removed,
                }
            )
        if not items:
            return text, {
                "cleaned": 0,
                "action": "noop",
                "source": "CFG-002.camera_move.no_amplitude_no_speed",
            }
        out = json.dumps(doc, ensure_ascii=False)
        return out, {
            "cleaned": len(items),
            "items": items[:50],
            "items_truncated": max(0, len(items) - 50),
            "source": "CFG-002.camera_move.no_amplitude_no_speed",
            "text_digest_before": before_digest,
            "text_digest_after": digest(out),
            "note": "机械字段清洗（非创作内容）；依据 T-103 裁决（2026-11-12）",
        }

    def _ensure_en_camera_sentence(
        self, tpl_stage: str, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """**投影规则⑤：英文运镜句机械补全**（项目方 2026-11-16 裁决批准）。

        为什么改模型产物
        ----------------
        `R34 EN_CAMERA_SENTENCE`（`prompts/validate_output.py`）要求每镜 `prompt_en` 含
        **以 `The camera` 起句的独立句**。`r6` 复验批 **12/12 挂 R34、重试自愈 0/12**，
        `ab_t101_r6/on/run1` 更实证「越试越差」（attempt1 缺 1 镜 → attempt2 缺 4 镜）。
        模板侧已把该要求写进 `guards`（「运镜句完整性」）并在 examples 给正例，
        仍然漏 ⇒ **模板措辞路线已到顶**，只能机制化处置。

        允许边界（裁决口径四件）
        ----------------------
        - **性质是投影，不是创作**：`camera.*` 是上游已定的导演决策（承继层「一字不得改」），
          本方法只把该决策**投影为英文句子**（与投影规则① lighting 拆分同族）；
        - **只追加、不改原句**：原文字一字不动，仅在句尾加一句；唯一的正文改动是
          **句末终止符的 ASCII 归一**（`。！？` → `.`/`!`/`?`）——不归一就拼不出独立句，
          该动作逐镜记 `punct_normalized`／`punct_action`，**不静默**；
        - **占位镜一律跳过**：`prompt_en` 为空／缺失的镜不补（`_reconcile_pack_conservation`
          明令占位镜留空「不伪造创作内容」；替它补句会把 `R27P` 的洞洗白）；
        - **不静默**：逐镜留痕（镜号／运镜／补的句子）＋ `merge_warnings` 汇总一条。

        幂等性
        ------
        补过的镜第二次进来必然命中 `CAMERA_SENTENCE_RE` ⇒ noop；`added==0` 时**返回原 text
        不重序列化**（字节级不变）。

        :returns: `(新文本, 留痕 dict 或 None)`；不适用／不可解析／词表或判据不可得 ⇒ `(text, None)`。
        """
        if not get_settings().pack_en_camera_sentence_fill:
            return text, None
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) != "pack":
            return text, None
        sentences = _camera_move_en_sentences()
        camera_re = _camera_sentence_re()
        if not sentences or camera_re is None:
            # 词表／判据其一不可得 ⇒ **整体跳过**（宁可不补，也不猜一份口径出来）
            return text, None
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None  # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        shots = doc.get("shots")
        if not isinstance(shots, list):
            return text, None

        before_digest = digest(text)
        items: list[dict[str, Any]] = []
        skipped_empty = 0
        skipped_no_vocab = 0
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            raw = shot.get("prompt_en")
            if not isinstance(raw, str) or not raw.strip():
                # 占位镜（或模型漏写）——**不补**，交 R27／R27P 如实判
                skipped_empty += 1
                continue
            if camera_re.search(raw):
                continue  # 已有独立运镜句 ⇒ noop
            stripped = raw.strip()
            if stripped.startswith("The camera"):
                # 唯一「看着合规却被判失败」的形态：句首有前导空白 ⇒ `^` 失配。
                # 此时**去掉前导空白**即可（绝不追加第二句运镜句——那会让同一镜出现两次运镜）。
                shot["prompt_en"] = stripped
                items.append(
                    {
                        "shot_id": shot.get("shot_id"),
                        "move": None,
                        "sentence": None,
                        "action": "leading_trimmed",
                        "punct_normalized": False,
                    }
                )
                continue
            cam = shot.get("camera")
            cam = cam if isinstance(cam, dict) else {}
            move = cam.get("move")
            base = sentences.get(str(move)) if move else None
            if not base:
                skipped_no_vocab += 1
                continue
            sentence = _render_camera_sentence(base, cam)
            if not camera_re.search(sentence):
                # 自检：词表句自身若不成「The camera 起句独立句」⇒ 不补（词表升版兜底）
                skipped_no_vocab += 1
                continue
            body = stripped
            punct_action = ""
            if body[-1] in "。！？":
                body = body[:-1] + {"。": ".", "！": "!", "？": "?"}[body[-1]]
                punct_action = "cjk_to_ascii"
            elif body[-1] not in ".!?":
                # 末尾无终止符 ⇒ 先补句号，否则追加的句子无法成为「独立句」
                body = body + "."
                punct_action = "terminator_added"
            new_text = f"{body} {sentence}"
            if not camera_re.search(new_text):  # 双保险：拼完必须真的过判据
                skipped_no_vocab += 1
                continue
            shot["prompt_en"] = new_text
            items.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "move": move,
                    "sentence": sentence,
                    "action": "appended",
                    "punct_normalized": bool(punct_action),
                    "punct_action": punct_action,
                }
            )
        if not items:
            return text, {
                "added": 0,
                "skipped_empty": skipped_empty,
                "skipped_no_vocab": skipped_no_vocab,
                "items": [],
                "items_truncated": False,
                "action": "noop",
                "source": "CFG-002.camera_move.model_map.minimax_h3",
            }
        out = json.dumps(doc, ensure_ascii=False, indent=2)
        return out, {
            "added": len(items),
            "skipped_empty": skipped_empty,
            "skipped_no_vocab": skipped_no_vocab,
            "items": items[:50],
            "items_truncated": max(0, len(items) - 50),
            "source": "CFG-002.camera_move.model_map.minimax_h3",
            "text_digest_before": before_digest,
            "text_digest_after": digest(out),
            "note": "投影规则⑤：按 camera.* 追加英文运镜句（只追加、不改原句）；"
            "占位镜跳过；依据项目方 2026-11-16 裁决",
        }


    def _clean_pack_appearance_echo(
        self, tpl_stage: str, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """**投影规则⑥：正文外观复述的机械清洗**（项目方 2026-11-16 裁决批准）。

        为什么改模型产物
        ----------------
        `R28 PACK_APPEARANCE_ECHO`（`prompts/validate_output.py` 的
        `rule_pack_appearance_echo`）要求交付包 `shots[].prompt_zh`／`prompt_en` 的**正文
        不得复述** `characters[].appearance_lock_zh|_en`。真机 **6 轮跑测 6/6 挂 `R28`**，
        命中片段集中在 `潜水服`×25／`orange rescue suit`×7／`深蓝色`×3——**全是 3 字／3 实词
        的最小窗口**，靠模型改措辞无法稳定规避：模板 `TPL-009:641-643` 已明令「外观命中即删」，
        同模板又要求「正文密度下界」（八维双落地）⇒ 模型唯一逃逸口就是服装/体型词。
        **措辞路线已到顶**（与投影规则⑤ 同性质的结论），只能服务层机制化。

        允许边界（裁决口径五件）
        ----------------------
        - **性质是投影规则⑥，不是「改创作」**：与 ⑤ 同族、方向相反——⑤ 是「补格式」、
          ⑥ 是「删冗余」。删掉的**不是**创作内容，而是「规范已明令不得进正文的冗余复述」
          （§3.4「外观只在此处定义一次」）；
        - **删除粒度＝完整子句**：不做逐词手术、不改写句子——逐词抠会把句子抠成病句，
          而服务层改写语义即越界；
        - **删后必须复算**：一律用**判据自身**的 `_anchor_ngrams`／`_en_content_ngrams`／
          `CJK_RUN_RE`／`ANCHOR_NGRAM`（经 `quality_gate.load_engine_validator()` 取，
          **本文件不重写 3 字／3 实词规则**）判定归零；仍命中则**放弃并如实登记**
          `skipped_unresolvable`（不许硬凑、不许掩盖，交 `R28` 判失败）；
        - **不删空保护**：删到「中文去空白后 <10 字／英文 <6 实词」⇒ **整镜回滚**
          （`skipped_would_empty`，原文不动）——否则会把 `R27`（正文非空/可读）的洞
          洗成新缺陷；
        - **只改** `prompt_zh`／`prompt_en`：`camera`／`duration_ms`／`shot_id` 等字段一字不动。

        跳过与保护
        ----------
        - **占位镜整镜跳过**（`skipped_placeholder`）：识别锚是 `notes` 以
          `_PLACEHOLDER_NOTES_PREFIX`（「服务层构造占位」）开头——那正是
          `_reconcile_pack_conservation` 自己写进去的一句，也是判据 `R27P PLACEHOLDER` 的同一锚。
          ⚠️ **不得用「`prompt_en` 为空」当占位镜判据**：`prompt_en` 空也可能是**模型漏写**
          的真实镜，其 `prompt_zh` 是**模型创作内容**，该被清洗；而占位镜的 `prompt_zh`
          是服务层由 `action` 机械派生的，替它清洗等于服务层改写自己刚生成的东西
          （既不增信息，又抹掉追溯线索）；
        - **英文 `The camera` 起句的子句一律不删**：那是投影规则⑤ 刚投影进来的合规内容
          （删它等于打开 `R34` 的洞），同时也保护模型自己写对的那句；若命中只落在该句内
          ⇒ 该镜英文侧记 `skipped_unresolvable`。

        幂等性
        ------
        清洗过的正文再进来必然 `R28` 已归零 ⇒ noop；noop 时**返回原 text 不重序列化**
        （字节级不变，与 `_ensure_en_camera_sentence` 同纪律）。

        :returns: `(新文本, 留痕 dict 或 None)`；开关关闭／非 `pack` 形态／判据不可得／
            不可解析／无外观锚 ⇒ `(text, None)`。
        """
        if not get_settings().pack_appearance_echo_clean:
            return text, None
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) != "pack":
            return text, None
        # ---- 判据口径**单点**：一律从引擎判据模块取，本文件不持有 3 字／3 实词规则 ----
        engine = quality_gate.load_engine_validator()
        if engine is None:
            return text, None  # 判据不可得 ⇒ 不猜口径，整体跳过（fail-open）
        anchor_ngrams = getattr(engine, "_anchor_ngrams", None)
        en_content_ngrams = getattr(engine, "_en_content_ngrams", None)
        cjk_run_re = getattr(engine, "CJK_RUN_RE", None)
        anchor_n = getattr(engine, "ANCHOR_NGRAM", None)
        if (
            not callable(anchor_ngrams)
            or not callable(en_content_ngrams)
            or cjk_run_re is None
            or not isinstance(anchor_n, int)
        ):
            return text, None
        try:
            doc = parse_json_object(text)
        except AppError:
            return text, None  # 解析不了由形态闸报出（不在此处抢先归因）
        if not isinstance(doc, dict):
            return text, None
        shots = doc.get("shots")
        if not isinstance(shots, list):
            return text, None

        # ---- 锚：只取 `characters[]`，与 `R28` 同源（`props[]` 不在 R28 的比对面内）----
        zh_grams: set[str] = set()
        en_grams: set[str] = set()
        for character in (doc.get("characters") or []):
            if not isinstance(character, dict):
                continue
            lock_zh = character.get("appearance_lock_zh")
            if isinstance(lock_zh, str) and lock_zh.strip():
                zh_grams |= anchor_ngrams(lock_zh)
            lock_en = character.get("appearance_lock_en")
            if isinstance(lock_en, str) and lock_en.strip():
                en_grams |= en_content_ngrams(lock_en)
        if not (zh_grams or en_grams):
            return text, None

        before_digest = digest(text)
        items: list[dict[str, Any]] = []
        scrubbed = 0
        skipped_unresolvable = 0
        skipped_would_empty = 0
        skipped_placeholder = 0
        unchanged = 0
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            # ---- **占位镜整镜跳过**（SPEC-008 V2.6 §3.7.2 边界⑤ 的实现对齐）----
            # ⚠️ 识别锚**只认 `notes` 前缀**（＝守恒兜底 `_reconcile_pack_conservation` 自己写的
            #    那句「服务层构造占位…」，也是判据 `R27P PLACEHOLDER` 的同一锚）——
            #    **不得**用「`prompt_en` 为空」当占位镜判据：`prompt_en` 空也可能是
            #    **模型漏写**的真实镜，其 `prompt_zh` 是模型创作内容、**该被清洗**；
            #    而占位镜的 `prompt_zh` 是由 `action` 机械派生的服务层产物，
            #    替它清洗等于让服务层改写自己刚生成的东西（既不增信息，又抹掉可追溯线索）。
            notes = shot.get("notes")
            if isinstance(notes, str) and notes.startswith(_PLACEHOLDER_NOTES_PREFIX):
                skipped_placeholder += 1
                continue
            shot_id = shot.get("shot_id")
            for lang, key, grams in (
                ("zh", "prompt_zh", zh_grams),
                ("en", "prompt_en", en_grams),
            ):
                if not grams:
                    continue
                raw = shot.get(key)
                if not isinstance(raw, str) or not raw.strip():
                    # 空字段（模型漏写本语言正文）：**无可清洗内容**，不计入 `unchanged`
                    continue
                if lang == "zh":
                    def _hit_zh(candidate: str, _grams=grams) -> str | None:
                        return _zh_appearance_hit(cjk_run_re, anchor_n, candidate, _grams)

                    def _too_short_zh(candidate: str) -> bool:
                        return len(_WS_RE.sub("", candidate)) < _APPEARANCE_ECHO_MIN_ZH_CHARS

                    new_value, gram, status, rounds = _scrub_appearance_echo_field(
                        raw, lang=lang, hit=_hit_zh, is_too_short=_too_short_zh
                    )
                else:
                    def _hit_en(candidate: str, _grams=grams) -> str | None:
                        return _en_appearance_hit(en_content_ngrams, candidate, _grams)

                    def _too_short_en(candidate: str) -> bool:
                        # 实词数用**判据自己的**切词与停用词口径（n=1 ⇒ 实词集合）
                        return (
                            len(en_content_ngrams(candidate, 1)) < _APPEARANCE_ECHO_MIN_EN_WORDS
                        )

                    new_value, gram, status, rounds = _scrub_appearance_echo_field(
                        raw, lang=lang, hit=_hit_en, is_too_short=_too_short_en
                    )
                if status == "scrubbed":
                    shot[key] = new_value
                    scrubbed += 1
                    items.append(
                        {
                            "shot_id": shot_id,
                            "lang": lang,
                            "hit_gram": gram,
                            "removed_chars": len(raw) - len(new_value),
                            # 轮次：多数命中 1 轮即归零；>1 说明存在跨子句伪 gram
                            "rounds": rounds,
                        }
                    )
                elif status == "unresolvable":
                    skipped_unresolvable += 1
                elif status == "would_empty":
                    skipped_would_empty += 1
                else:
                    unchanged += 1
        if not items:
            # **字节级 noop**：不重序列化（`json.dumps` 会改缩进／转义，等于白改一遍产物）
            return text, {
                "field": "shots[].prompt_zh|prompt_en",
                "rule": "R28",
                "changed": False,
                "action": "noop",
                "scrubbed": 0,
                "skipped_unresolvable": skipped_unresolvable,
                "skipped_would_empty": skipped_would_empty,
                "skipped_placeholder": skipped_placeholder,
                "unchanged": unchanged,
                "items": [],
                "items_truncated": False,
                "source": "R28.anchor_ngram.cjk3/en3content",
            }
        out = json.dumps(doc, ensure_ascii=False)
        return out, {
            "field": "shots[].prompt_zh|prompt_en",
            "rule": "R28",
            "changed": True,
            "action": "scrubbed",
            "scrubbed": scrubbed,
            "skipped_unresolvable": skipped_unresolvable,
            "skipped_would_empty": skipped_would_empty,
            "skipped_placeholder": skipped_placeholder,
            "unchanged": unchanged,
            "items": items[:50],
            "items_truncated": len(items) > 50,
            "digest_before": before_digest,
            "digest_after": digest(out),
            "source": "R28.anchor_ngram.cjk3/en3content",
            "note": "投影规则⑥：只删命中外观锚的完整子句，删后按判据复算归零才提交；"
            "删到过短则整镜回滚；`The camera` 句与占位镜跳过；依据项目方 2026-11-16 裁决",
        }

    async def _maybe_generate(
        self, rec: SessionRecord, target: Stage, variables: dict[str, Any]
    ) -> None:
        """生成目标阶段产物。

        `T-004` 起改为**分段调用**：单次巨调用（14 镜整包 ≈1.2 万字符）必被截断，
        故按 `segment` 计划逐段生成、再结构合并（见 `app/services/segment.py`），
        并把**输出契约 schema** 交给后端做受约束解码。
        **本方法只做编排与留痕，不改写、不润色模型输出。**
        """
        spec = _GENERATE_ON.get(target)
        if spec is None:  # 终态或无需生成
            return
        key, tpl_stage = spec
        template = self.prompts.by_stage(tpl_stage)
        backend = self._resolve_backend()
        merged = dict(variables)
        compact_trace: dict[str, dict[str, int]] = {}
        upstream_admission: dict[str, dict[str, Any]] = {}
        # `T-086`：门禁的**跨层规则**要的是上游产物**原文**（不是紧凑化后的变量值）——
        # `R23`/`R24`/`R31` 判的是「本层有没有忠实承继上游」，喂紧凑化副本会把
        # 「只去空白」的等价物当成两份不同的东西。故此处按**形态名**另存一份原文。
        gate_upstream: dict[str, str] = {}
        for var, upstream_key in _UPSTREAM_VARS.get(tpl_stage, {}).items():
            upstream = rec.artifacts.get(upstream_key)
            if upstream is None:
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"生成「{template.name}」缺少上游产物：{upstream_key}",
                    details={"template_id": template.id, "missing_artifact": upstream_key},
                )
            upstream_text = _artifact_text(upstream)
            up_shape = artifact_contract.STAGE_TO_SHAPE.get(upstream_key)
            if up_shape:
                gate_upstream[up_shape] = upstream_text
            # ---- `ISSUE-042` 上游准入闸：**先判后采**，不得拿不可解析的上游去生成 ----
            upstream_admission[var] = self._admit_upstream(upstream_key, upstream_text)
            # `ISSUE-037` 方案 D 的服务层一半（`ISSUE-044` 起改为**按段适用**）：
            # 只去空白、**解析失败原样返回**；只作用于「交给模型的变量」，
            # 会话里的 `artifact["text"]` 仍是模型原文。
            # ⚠️ **为什么要按段收窄**（实测）：该项的**唯一动机**是「渲染输入超窗」，
            # 而只有 `shot_prompt` 段会超（未紧凑 58,550 > 32,768）；`storyboard` 段
            # 输入仅 12,214 tokens、**不需要**它，且对照实测该变换在该段**疑似**劣化
            # 产出量（越阈值 4/6 → 1/6，⚠️ p≈0.24 不显著，故只作「谁需要谁才用」）。
            settings = get_settings()
            if settings.prompt_compact_upstream and tpl_stage in settings.compact_stages:
                upstream_text, info = _compact_upstream_json(upstream_text)
                if info["changed"]:
                    compact_trace[var] = info
            merged.setdefault(var, upstream_text)
        # 服务层注入元数据（模板硬性约束：模型不得编造 pack_meta）
        if "pack_meta" in template.required_variables:
            merged["pack_meta"] = json.dumps(
                build_pack_meta(
                    session_id=rec.session_id,
                    stage=tpl_stage,
                    templates=[{"id": template.id, "version": template.version}],
                    model={
                        "name": backend.name,
                        "backend": backend.name,
                        "revision": backend.version,
                    },
                    settings=get_settings(),
                    artifacts=rec.artifacts,
                    title=rec.source_input[:30],
                ),
                ensure_ascii=False,
            )

        # ---- 安全双闸 · 输入侧（`T-005`：`SW-009` 前置检测 ＋ `SW-011` 注入防护）----
        # 闸门在**调用推理后端之前**：命中即不消耗算力（`SW-009`「输入前置检测」）。
        guard_input = self._guard_input(merged)

        # ---- 分段调用（`T-004`）＋ 生成后门禁与重试回路（`T-086`）----
        plan = self._segment_plan(template, tpl_stage, rec, merged)
        # ---- `T-100` 逐场编排：场号 → 该场对象（供 `scene:<no>` 段动态注入变量）----
        # ⚠️ 只在计划确有 `scene:` 段时解析：整片模式（开关关）不必多解析一次剧本。
        # ---- `T-116` script 逐场拆段：梗概场对象（`scene:<no>` 段注入）——来源是
        #      **梗概** `scenes_outline`（场号真值在上游梗概侧），与 storyboard 的
        #      剧本侧 `scene_ctx` 是两条独立通道，互不复用。
        scene_ctx: dict[int, dict[str, Any]] | None = None
        script_ctx: dict[str, Any] | None = None
        if tpl_stage == "script" and any(
            s == "package_head" or str(s).startswith("scene:") for s in plan
        ):
            script_ctx = {"scenes": synopsis_scene_by_no(_upstream_json(rec.artifacts.get("synopsis")))}
        elif any(str(s).startswith("scene:") for s in plan):
            scene_ctx = scene_by_no(_upstream_json(rec.artifacts.get("script")))
        # ---- `T-101`／`PRO-015`：`shot_prompt` 段级输入裁剪的上下文 ----
        # ⚠️ 解析对象是 `merged["storyboard_json"]`（**已紧凑化**的变量值）——
        #    裁剪副本切的是「模型本来要看见的那份」，与门禁的 `gate_upstream`（原文）
        #    是两条独立通道，互不影响（`R23`/`R24`/`R31` 判的是原文）。
        # ⚠️ 解析失败 ⇒ `scope_ctx` 置 `None`（各段整份注入）＋留痕——不猜测。
        scope_ctx: dict[str, Any] | None = None
        if (
            get_settings().shot_prompt_segment_scope
            and tpl_stage == "shot_prompt"
            and any(s == "package_head" or str(s).startswith("unit:") for s in plan)
        ):
            try:
                storyboard_doc = parse_json_object(merged.get("storyboard_json") or "")
            except AppError:
                storyboard_doc = None
            if isinstance(storyboard_doc, dict):
                scope_ctx = {"storyboard": storyboard_doc}
            else:
                logger.warning(
                    "segment_scope_ctx_unparsed",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "note": "storyboard_json 无法解析，段级裁剪不生效（各段整份注入）",
                        }
                    },
                )
        # ⚠️ 交给引擎的必须是**引擎可编译形态**（剥离 `ENGINE_UNSUPPORTED_KEYS`）——
        #    契约真值形态含 `uniqueItems`，xgrammar 编译期即 400 拒收（`OPS-002` §4.3.1）。
        json_schema = load_engine_schema(tpl_stage)
        stripped = stripped_paths(tpl_stage)
        schema_source = engine_schema_source(tpl_stage)
        supports_segment = any(v["name"] == "segment" for v in template.variables)

        # 门禁与重试开关（`T-086`）：判据来源＝`prompts/validate_output.py` ＋
        # `delivery/validate_pack.py`，服务层**不抄第二份**（见 `quality_gate` 模块 docstring）。
        gate_applies = quality_gate.applies_to(tpl_stage)
        retry_enabled = gate_applies and bool(get_settings().quality_gate_retry_enabled)
        max_attempts = (
            max(1, int(get_settings().quality_gate_max_attempts)) if retry_enabled else 1
        )
        # ---- `ISSUE-094`：形态闸是**第二路额度驱动者** ----
        # ⚠️ 为什么必须单独给额度：`script` 段通常不适用质量门禁（`gate_applies=False`）
        #    ⇒ 上式给出 `max_attempts=1` ⇒ **形态闸判失败即抛、零重试**。而形态缺陷
        #    （`acts[2]` 非对象这类元素级结构）是**单次采样的随机波动**，重采一次多半自愈。
        # ⚠️ 取 `max` 而不是相加：两路额度服务的是**同一件资源**（本阶段的采样次数），
        #    相加会让「质量门禁 2 次 ＋ 形态闸 2 次」变成 4 次调用，成倍拉长墙钟时间。
        # ⚠️ **两份额度各自独立判停**（`ISSUE-094` 施工时实测出的必要约束）：
        #    循环上限取两路最大值，但**质量门禁的判停仍只用 `quality_max_attempts`**
        #    ——否则「给形态闸 2 次额度」会顺带把 `quality_gate_retry_enabled=false`
        #    （重试默认关，开关是**成倍耗时**的取舍）悄悄打开：实测该串扰会让
        #    `script` 段在质量门禁不过时多跑一次采样（真跑日志 `quality_gate_retry`
        #    在 `retry_enabled=false` 下出现），属**裁决之外的副作用**，故在此隔离。
        # ⚠️ 受 `shape_gate_enforce` 约束：受控旁路下形态闸不阻断，也就无需重试额度。
        # ⚠️ 读法（独立 QA 指出注释一处易误读，故作措辞收紧）：这里**只有判定阈值是两路各自的**，
        #    而**循环上限是共享的一个数** ⇒ 抬高 `shape_gate_max_attempts` 会在质量门禁重试
        #    已开启时一并抬高其尝试上限（反之亦然）；`quality_gate_retry_enabled=false` 时
        #    质量门禁仍按 `quality_max_attempts=1` 判停（下方隔离），故不受影响。
        quality_max_attempts = max_attempts
        if get_settings().shape_gate_enforce and get_settings().shape_gate_retry_enabled:
            max_attempts = max(max_attempts, max(1, int(get_settings().shape_gate_max_attempts)))
        retry_segs: list[str] = list(plan)
        retry_scope_note: str | None = None
        #: **乙**：下一轮重采要带的判据反馈（由质量门禁重试决策时构造；每轮**消费即清**）。
        retry_feedback_pending: str | None = None
        #: **乙**：反馈是否「未定位」（`scope_fallback` 全段重采）⇒ 注入免责句（见 `_run_segments`）。
        retry_feedback_unlocated_pending: bool = False
        gate_verdicts: list[dict[str, Any]] = []
        quality_verdict: Any = None
        #: 形态闸逐次尝试留痕（`ISSUE-094`）：**只记失败**那次，成功不记。
        #: 有内容 ⇒ `artifact["artifact_shape_retry"]` 落盘（无重试＝不写，同 `amp_norm` 纪律）。
        shape_attempts: list[dict[str, Any]] = []

        texts_by_seg: dict[str, str] = {}
        trace: list[dict[str, Any]] = []
        prompt_tokens = completion_tokens = 0
        final_text = ""
        warnings: list[str] = []
        guard_output: dict[str, Any] | None = None
        artifact_verdict: dict[str, Any] | None = None
        text_penultimate = ""
        truncated_segments: list[str] = []
        segment_contributions: list[dict[str, Any]] = []
        meta_overrides: dict[str, Any] | None = None
        derived_backfill: dict[str, Any] | None = None
        identity_norm: dict[str, Any] | None = None
        amp_norm: dict[str, Any] | None = None
        en_camera_fill: dict[str, Any] | None = None
        appearance_echo_clean: dict[str, Any] | None = None
        acts_repair: dict[str, Any] | None = None
        coverage_reconcile: dict[str, Any] | None = None

        #: 上一轮「结构合法」的状态快照 —— 供「**重试把产物弄坏**」时回退（改造不得变差）。
        last_ok_state: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            segs = list(plan) if attempt == 1 else list(retry_segs)
            # ---- 乙：本轮重采若带判据反馈，**消费即清**（每轮反馈只对应一次决策）----
            feedback = retry_feedback_pending
            feedback_unlocated = retry_feedback_unlocated_pending
            retry_feedback_pending = None
            retry_feedback_unlocated_pending = False
            trace_len_before = len(trace)
            try:
                produced, seg_trace, pt, ct, _truncated_now = await self._run_segments(
                    template, tpl_stage, merged, segs, supports_segment, json_schema,
                    backend, scene_ctx, scope_ctx, script_ctx,
                    prior_texts=dict(texts_by_seg), retry_feedback=feedback,
                    retry_feedback_unlocated=feedback_unlocated,
                )
                for record in seg_trace:
                    record["attempt"] = attempt  # 留痕：这一条是第几次尝试采到的
                texts_by_seg.update(produced)
                trace.extend(seg_trace)
                prompt_tokens += pt
                completion_tokens += ct

                # ---- `ISSUE-042` 截断判定：**只看本次尝试**----
                # ⚠️ 必须传本批 `seg_trace` 而不是累加的 `trace`：重试成功时若还拿上一轮的
                #    `finish_reason=length` 去判，会把**已修好的历史失败**当成当前失败
                #    （＝把历史当现状）—— 这正是 `_guard_not_truncated` 要防的方向性错误。
                # ⚠️ 实测：第 3 轮真跑分镜段 `finish_reason=stop` 却**远未触 `max_tokens`**，
                #    产物在结构中间被截断 ⇒「撞长度上限」与「模型自终止在不完整结构上」
                #    是**两种**失败，分开归因才能指对方向。
                #
                # ---- `ISSUE-090`：截断 ⇒ **只重采样被截断的段**（`ISSUE-094` 同批机制）----
                # ⚠️ 为什么归到这一路：截断是**单次采样撞上 `max_tokens`** 的随机后果
                #    （同一模板同一输入可产出合法产物），属形态闸家族；而「判出即抛」
                #    会把一次可自愈的采样波动升级成整链 502（实测 10 轮连跑 4 轮里 3 轮死于此）。
                # ⚠️ 只重跑**坏段**：`truncated_segments` 精确到 `scene:3`／`unit:U04`；
                #    整份计划重跑在长产物上要再花 15~20 分钟，而坏段通常只占 1/4~1/3。
                # ⚠️ 额度与形态闸共用（`max_attempts`），判停仍在下面按需 `continue`／`raise`。
                try:
                    truncated_segments = self._guard_not_truncated(tpl_stage, seg_trace)
                except AppError as exc:
                    bad_segs = [str(s) for s in ((exc.details or {}).get("truncated_segments") or [])]
                    trunc_reason = str((exc.details or {}).get("reason") or "")
                    shape_attempts.append(
                        {
                            "attempt": attempt,
                            "reason": trunc_reason,
                            "stage": tpl_stage,
                            "shape": artifact_contract.STAGE_TO_SHAPE.get(tpl_stage),
                            "path": None,
                            "segments": bad_segs,
                            "error": str(exc.message or "")[:200],
                        }
                    )
                    if trunc_reason == "segment_truncated" and attempt < max_attempts and bad_segs:
                        retry_segs = [s for s in plan if s in bad_segs] or list(plan)
                        # ---- 批次 1b（`ISSUE-090` ①）：截断重采**带收敛反馈** ----
                        # ⚠️ 盲重采在退化轮上有**再犯率**（同温度同输入，模型可能再次
                        #    跑飞写散文）——探针实测正常产出 1889~7329 tok、8192 上限
                        #    最小余量仅 863 tok（`.wb-e2e/_probe_script_tokens_report.json`），
                        #    截断是长尾但余量并不宽裕。此处把乙臂已验证的「判据反馈
                        #    重采」机制复用到截断族：反馈明写「上次被截断 ⇒ 收敛输出」，
                        #    注入被截断段的重采提示词（trace 的 `retry_feedback` 可核查）。
                        # ⚠️ 消费即清语义与质量门禁反馈一致（循环顶消费后置 `None`）。
                        retry_feedback_pending = (
                            "上一次采样在 " + "、".join(bad_segs) + " 段被 max_tokens "
                            "长度上限截断（finish_reason=length），产物 JSON 不完整。"
                            "本次必须收敛输出：压缩铺陈与重复描写、缩短超长字段值，"
                            "确保 JSON 结构完整闭合且远小于长度上限。"
                        )
                        # ---- `T-117` ③：script 段追加**预算数字**反馈 ----
                        # 复测 r2/r4 实锤 script 段重采兜底 0/3：泛化「收敛输出」
                        # 对跑飞无约束力。按段给出同源硬数字（head 骨架规模／
                        # scene 台词字数与行数预算），让模型知道「收到多少算停」。
                        if tpl_stage == "script":
                            retry_feedback_pending += _script_truncation_feedback(
                                bad_segs, script_ctx
                            )
                        retry_feedback_unlocated_pending = False
                        logger.info(
                            "segment_truncated_retry",
                            extra={
                                "extra_fields": {
                                    "session_id": rec.session_id,
                                    "stage": tpl_stage,
                                    "attempt": attempt,
                                    "next_attempt": attempt + 1,
                                    "truncated_segments": bad_segs,
                                    "retry_segments": retry_segs,
                                    # 批次 1c 收口补观测（批次 1b 收口后的真机缺口）：
                                    # 截断反馈只落在 trace（失败轮不落盘不可回溯）⇒
                                    # 注入与否必须在**日志事件**上可核查（同乙臂
                                    # `feedback_chars` 纪律）。0＝未注入（异常信号）。
                                    "feedback_chars": len(retry_feedback_pending or ""),
                                }
                            },
                        )
                        continue
                    exc.details["shape_attempts"] = list(shape_attempts)
                    raise

                ordered = [texts_by_seg[s] for s in plan if s in texts_by_seg]
                if is_multi_part(plan):
                    segment_contributions = self._guard_segment_contributions(
                        tpl_stage, plan, ordered
                    )
                    # `ISSUE-062`（裁决 5）：storyboard 合并需要**上游剧本产物**来识别
                    # 「继承项」——`fill_stage` 锁回 `script` 的前提是知道上游那条的定责阶段。
                    # ⚠️ 解析失败 ⇒ 传 `None`（合并侧不改写、只留「查无对应条目」痕迹）。
                    merge_upstream: dict[str, Any] | None = None
                    if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "storyboard":
                        try:
                            _up = parse_json_object(merged.get("script_json") or "")
                        except AppError:
                            _up = None
                        merge_upstream = _up if isinstance(_up, dict) else None
                    elif artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "script":
                        # `T-116`：script 合并需要**上游梗概**做机械承继
                        # （forbidden_items 原样承接）与场号基准。
                        try:
                            _up = parse_json_object(merged.get("synopsis_json") or "")
                        except AppError:
                            _up = None
                        merge_upstream = _up if isinstance(_up, dict) else None
                    merge_segs = [s for s in plan if s in texts_by_seg]
                    final_text, warnings = _merge_parts(
                        ordered, tpl_stage, merge_upstream, merge_segs
                    )
                else:
                    final_text, warnings = ordered[0], []

                # ---- 批次1a（`ISSUE-095`/`096`）：acts 元素级预修复（双重序列化归一化）----
                # ⚠️ **位置在归一化链最前**：标识归一化／机械清洗／守恒兜底都要先解析
                #    JSON，结构先合法它们才判得到真形态；修复失败（纯文本等不可解析形态）
                #    **原样留给形态闸拒**——本层只修「确定可修」的，不洗白任何真缺陷。
                # ⚠️ **无条件重赋值**（同 `identity_norm` 写法）：修复只对本次采样的
                #    文本有效，重采后必须清掉上一轮的记录，不得跨尝试残留。
                final_text, acts_repair = _repair_acts_strings(final_text)
                if acts_repair:
                    warnings.append(
                        "acts_repair: "
                        f"{len(acts_repair['acts_unwrapped']) + sum(len(v) for v in acts_repair['scenes_unwrapped'].values())}"
                        " 处双重序列化的 acts/scenes 元素已解析回对象（明细见 artifact）"
                    )

                # ---- `T-100` 标识归一化（`R7`／`R9` 派生量；合并后、门禁前）----
                # ⚠️ 顺序纪律与真值覆盖/派生回填一致：门禁要判**最终入库的那一份**。
                # ⚠️ 必须在 `R8` 回填**之前**：两者都按「场内数组序」定位，先定 `shot_id`
                #    再定 `shot_no`，同一个序位口径，不会互相打架。
                final_text, identity_norm = self._normalize_storyboard_identity(
                    tpl_stage, final_text
                )

                # ---- `T-103` `camera.amp_speed` 机械清洗（引擎响应归一化层，门禁前）----
                # ⚠️ 2026-11-12 项目方裁决：允许清洗、落本层。只删 `static`/`pov` 的
                #    `amplitude`/`speed`（机械档位，非创作内容），逐镜留痕＋告警进
                #    `merge_warnings`（不静默）。
                final_text, amp_norm = self._normalize_camera_amp_speed(
                    tpl_stage, final_text
                )
                if amp_norm and amp_norm.get("cleaned"):
                    warnings.append(
                        f"camera_amp_speed_normalize: {amp_norm['cleaned']} 镜经机械清洗后通过"
                        "（static/pov 的 amplitude/speed 已删，明细见 artifact）"
                    )

                # ---- **投影规则⑥**：R28 正文外观复述机械清洗（项目方 2026-11-16 裁决）----
                # ⚠️ **位置四条硬约束**（改动前请逐条核对）：
                #    ① 在 `_normalize_camera_amp_speed` **之后**——与既有投影链同层，
                #       保持「字段归一 → 正文清理 → 正文补全」的次序；
                #    ② 在 `_ensure_en_camera_sentence` **之前**——**先清洗、后合成**。
                #       否则 ⑤ 补出的 `The camera` 句进入正文后再清洗，会多一次
                #       「这句要不要删」的判断面（极易把刚补的合规句误伤）；
                #    ③ 在 `text_penultimate = final_text`（下方真值覆盖前）与 `_guard_output`
                #       **之前**——否则本步的正文改动会被 `artifact["service_truth_text_changed"]`
                #       误记成「服务层真值覆盖改了正文」（⑤ 已踩过这个归因坑）；
                #    ④ 在 `_reconcile_pack_conservation`（守恒兜底）**之前**——占位镜是
                #       服务层构造、无外观锚，放前面天然免疫（且不替占位镜改正文）。
                final_text, appearance_echo_clean = self._clean_pack_appearance_echo(
                    tpl_stage, final_text
                )
                if appearance_echo_clean and appearance_echo_clean.get("scrubbed"):
                    warnings.append(
                        f"appearance_echo_clean: {appearance_echo_clean['scrubbed']} 处正文外观复述"
                        "已按子句删除（投影规则⑥，明细见 artifact）"
                    )

                # ---- **投影规则⑤**：R34 英文运镜句机械补全（项目方 2026-11-16 裁决）----
                # ⚠️ **位置三条硬约束**（改动前请逐条核对）：
                #    ① 必须在 `_normalize_camera_amp_speed` **之后**——static/pov 的幅速已被删，
                #       补出的句子才是「不带幅度速度」的自洽形态（§3.7.2）；
                #    ② 必须在 `text_penultimate = final_text`（下方真值覆盖前）**之前**——
                #       否则本步的正文改动会被 `artifact["service_truth_text_changed"]`
                #       误记成「服务层真值覆盖改了正文」（留痕错因，极难查）；
                #    ③ 必须在 `_reconcile_pack_conservation`（守恒兜底）**之前**——
                #       兜底补的占位镜 `prompt_en` 留空（不伪造创作内容），本步**跳过空镜**
                #       ⇒ 放在兜底之前，占位镜尚不存在，天然不会替它补句（不洗白 R27P）。
                # ⚠️ 也顺带在 `_guard_output` **之前**：让输出安全闸复检到最终正文。
                final_text, en_camera_fill_now = self._ensure_en_camera_sentence(
                    tpl_stage, final_text
                )
                if en_camera_fill_now and en_camera_fill_now.get("added"):
                    en_camera_fill = en_camera_fill_now
                    warnings.append(
                        f"en_camera_sentence_fill: {en_camera_fill_now['added']} 镜 prompt_en "
                        "机械补英文运镜句（投影规则⑤，CFG-002 词表；只追加、不改原句，明细见 artifact）"
                    )

                # ---- 安全双闸 · 输出侧（`T-005`：`SW-010` 输出复检）----
                # ⚠️ 复检对象是**模型产出的那一份正文**（合并后的最终产物），
                #    不是逐段文本——`SW-010` 判的是「交给客户的东西」。
                # ⚠️ 位置在真值覆盖**之前**：覆盖只改服务层域标识（企业码／编号／合规块），
                #    那些值来自配置而非模型，不属内容安全判据的对象。
                guard_output = self._guard_output(final_text)

                # ---- 服务层真值覆盖（`T-086` 配套）：**必须在门禁之前** ----
                # ⚠️ 顺序不可换：门禁要判的是「最终入库、最终交付的那一份」。
                #    若先判后覆盖，判的是模型自拟元数据（含**假合规值** `safety:"passed"`），
                #    结论本身无意义 —— 而假值恰好会**通过**门禁，比缺失更危险。
                text_penultimate = final_text
                final_text, meta_overrides = self._apply_service_truth(
                    tpl_stage, final_text, rec, backend, guard_input, guard_output
                )

                # ---- 镜集合守恒兜底（`T-101` r3 呈报·裁决甲，2026-11-07）**必须在派生回填之前** ----
                # ⚠️ 顺序硬约束：补进来的占位镜也带 `duration_ms`，必须参与 `Σ`
                #    （`pack_derived_backfill` 的 `meta.total_duration_ms`）——
                #    先回填再补镜会让补入镜的时长漏出总量。
                # ⚠️ 只补「上游有、本层缺」的镜；占位条目 `notes` 明写服务层构造，
                #    告警进 `merge_warnings`（兜底不洗白，模型漏镜率可离线统计）。
                final_text, conservation_fills = _reconcile_pack_conservation(
                    tpl_stage, final_text, gate_upstream
                )
                if conservation_fills:
                    warnings.extend(conservation_fills)

                # ---- 批次 2 一期（覆盖分配器）：门禁同源阈值的确定性兜底改写 ----
                # ⚠️ **必须在派生回填之前**：延展 `duration_ms` 后 `Σ total_duration_ms`
                #    才能被派生回填重算（先回填再延展会让补出的时长漏出总量）。
                # ⚠️ **改写不裁决**：阈值全部同源 import 门禁判据（不抄第二份），
                #    改写后由既有门禁复算——不达标照旧走重采/如实拒绝，本层不洗白。
                # ⚠️ **无条件重赋值**（同 `acts_repair`）：重采后清掉上一轮记录。
                if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) in ("storyboard", "pack"):
                    final_text, coverage_reconcile = _run_coverage_reconcile(final_text)
                    if coverage_reconcile:
                        _n = len(coverage_reconcile["dialogue_stretched"]) + len(
                            coverage_reconcile["lighting_backfilled"]
                        )
                        warnings.append(
                            f"coverage_reconcile: {_n} 处门禁判据族缺陷经确定性兜底改写"
                            "（台词延时长/光线同单元回填，明细见 artifact）"
                        )

                # ---- 派生量回填（`R14`；2026-11-04 项目方裁决）**必须在门禁之前** ----
                # ⚠️ 与 `_apply_service_truth` 同一顺序纪律：门禁要判「最终入库的那一份」。
                # ⚠️ 只补「由模型自己的数据唯一决定」的量（`Σ duration_ms`），不动创作字段。
                final_text, derived_backfill = self._apply_derived_backfill(
                    tpl_stage, final_text, gate_upstream
                )

                # ---- `ISSUE-042` 生成后形态闸（**单段与多段收敛到同一条路径**）----
                # 改造前：多段会经 `_merge_parts` → `parse_json_object`（但那是「合并的必要步骤」），
                # 单段则 `final_text = texts[0]` **完全不解析** ⇒ 产物是否被检查**取决于 `segment` 取值**。
                # 现统一收口：无论单段多段，最终产物都必须过形态闸。
                #
                # ---- `ISSUE-094`：形态闸失败 ⇒ **段内重试**（不再「判出即抛」）----
                # ⚠️ 捕获必须**就地**（在本 try 内）：外层 `except AppError` 走的是
                #    「重试把产物弄坏 ⇒ 回退上一轮合法快照」这条**不同**的语义；
                #    形态闸失败的正确响应是**重采一次样**，不是回退（首轮无快照可退）。
                try:
                    artifact_verdict = self._guard_artifact_shape(tpl_stage, final_text)
                except AppError as exc:
                    shape_reason = str((exc.details or {}).get("reason") or "")
                    shape_path = (exc.details or {}).get("structure_path")
                    # 留痕只记**失败那次**（成功不记）：无重试 ⇒ 该列表为空 ⇒ 不落盘。
                    shape_attempts.append(
                        {
                            "attempt": attempt,
                            "reason": shape_reason,
                            "stage": tpl_stage,
                            "shape": artifact_contract.STAGE_TO_SHAPE.get(tpl_stage),
                            # 元素级缺陷的定位串（`acts[2]` 等）；非元素级失败为 `None`。
                            "path": shape_path,
                            # 摘要而非全文：留痕不落产物原文（同 `amp_norm` 纪律）。
                            "error": str(exc.message or "")[:200],
                        }
                    )
                    if shape_reason in _SHAPE_GATE_RETRY_REASONS and attempt < max_attempts:
                        # 重跑**全部段**：形态缺陷通常来自单段采样，而 `_retry_segments`
                        # 的精确到段依赖「门禁报错文本 → 段」的映射，形态闸没有那个粒度
                        # ⇒ 宁可多跑（不得漏跑），代价由 `shape_gate_max_attempts` 封顶。
                        retry_segs = list(plan)
                        logger.info(
                            "artifact_shape_retry",
                            extra={
                                "extra_fields": {
                                    "session_id": rec.session_id,
                                    "stage": tpl_stage,
                                    "attempt": attempt,
                                    "next_attempt": attempt + 1,
                                    "reason": shape_reason,
                                    "path": shape_path,
                                    "retry_segments": retry_segs,
                                }
                            },
                        )
                        continue
                    # 额度用尽／原因码不可重试：**原样抛出**（不改错误码、不改文案）；
                    # 只把「形态闸尝试过几次」挂进 details，供调用方与离线审计举证。
                    # ⚠️ 追加键不碰 `reason`（闸门原因码），故既有断言面零改动。
                    exc.details["shape_attempts"] = list(shape_attempts)
                    raise
            except AppError:
                # ⚠️ **重试的语义是「改善」，不是「换成另一版」**（本批实测踩到的坑）：
                #    脚本化后端只预置了一轮响应时，第 2 次调用返回 `{}` ⇒ 形态闸判「无法识别」。
                #    若直接抛出，就等于**用一个结构非法的产物替换掉一个结构合法的产物** ——
                #    净效果是变差，且把「质量未过关」这一真问题掩盖成「产物不可解析」。
                #    ⇒ 有上一轮合法快照时**回退**并如实登记；**首轮**不合法则照旧抛出
                #    （与改造前行为一致：不写槽、不推进状态机）。
                if last_ok_state is None:
                    raise
                texts_by_seg = last_ok_state["texts_by_seg"]
                del trace[trace_len_before:]
                final_text = last_ok_state["final_text"]
                warnings = last_ok_state["warnings"]
                guard_output = last_ok_state["guard_output"]
                artifact_verdict = last_ok_state["artifact_verdict"]
                text_penultimate = last_ok_state["text_penultimate"]
                meta_overrides = last_ok_state["meta_overrides"]
                truncated_segments = last_ok_state["truncated_segments"]
                # ⚠️ 回退重放的各归一化对快照文本都是幂等 noop，**唯独本项例外**：
                #    快照文本已修复 ⇒ 重放必然返回 `None`，直接沿用会把它**误抹掉**
                #    ⇒ 必须从快照显式还原（否则「入库产物修过没有」在留痕上失真）。
                acts_repair = last_ok_state["acts_repair"]
                # 批次 2：同 `acts_repair`——快照文本已改写 ⇒ 重放必为 noop，
                # 直接沿用重放会把已改写记录误抹掉 ⇒ 从快照显式还原。
                coverage_reconcile = last_ok_state["coverage_reconcile"]
                final_text, meta_overrides = self._apply_service_truth(
                    tpl_stage, text_penultimate, rec, backend, guard_input, guard_output
                )
                final_text, identity_norm = self._normalize_storyboard_identity(
                    tpl_stage, final_text
                )
                # 回退路径同样须先清洗 amp_speed 再守恒兜底（幂等：已清洗过则为 noop）
                final_text, amp_norm = self._normalize_camera_amp_speed(
                    tpl_stage, final_text
                )
                # 回退路径同样须**先清外观复述、再补运镜句**（同主路径 ② 的理由；
                # 幂等：`text_penultimate` 已清过 ⇒ 此处必为 noop，仍是同一口径的兜底）。
                final_text, appearance_echo_now = self._clean_pack_appearance_echo(
                    tpl_stage, final_text
                )
                if appearance_echo_now and appearance_echo_now.get("scrubbed"):
                    appearance_echo_clean = appearance_echo_now
                    _c = (
                        f"appearance_echo_clean: {appearance_echo_now['scrubbed']} 处正文外观复述"
                        "已按子句删除（投影规则⑥，明细见 artifact）"
                    )
                    if _c not in warnings:
                        warnings.append(_c)
                # 回退路径同样须补运镜句（同上：`text_penultimate` 已含补句 ⇒ 此处必为 noop；
                # 若首轮补句发生在快照之后（不该发生），这里仍是同一口径的兜底）。
                final_text, en_camera_fill_now = self._ensure_en_camera_sentence(
                    tpl_stage, final_text
                )
                if en_camera_fill_now and en_camera_fill_now.get("added"):
                    en_camera_fill = en_camera_fill_now
                    _c = (
                        f"en_camera_sentence_fill: {en_camera_fill_now['added']} 镜 prompt_en "
                        "机械补英文运镜句（投影规则⑤，CFG-002 词表；只追加、不改原句，明细见 artifact）"
                    )
                    if _c not in warnings:
                        warnings.append(_c)
                # 回退路径同样须先守恒兜底再派生回填（占位镜参与 `Σ`）；
                # 快照 `warnings` 已含同码 ⇒ 去重追加（同一 `text_penultimate` 重放）。
                final_text, conservation_fills = _reconcile_pack_conservation(
                    tpl_stage, final_text, gate_upstream
                )
                for _c in conservation_fills:
                    if _c not in warnings:
                        warnings.append(_c)
                final_text, derived_backfill = self._apply_derived_backfill(
                    tpl_stage, final_text, gate_upstream
                )
                retry_scope_note = "retry_degraded_fallback"
                if shape_attempts:
                    # `ISSUE-094` 留痕校正：这一条失败属于**被回退掉的那次采样**
                    # （最终入库的仍是上一轮合法产物）。必须标注，否则审计会把
                    # 「试过但被丢弃」读成「入库的产物没过闸」。
                    shape_attempts[-1]["fallback"] = retry_scope_note
                logger.warning(
                    "quality_gate_retry_degraded",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "stage": tpl_stage,
                            "attempt": attempt,
                            "note": "重试尝试的产物未过结构闸，已回退到上一轮合法产物（重试不得使结果变差）",
                        }
                    },
                )
                break
            last_ok_state = {
                "texts_by_seg": dict(texts_by_seg),
                "final_text": final_text,
                "warnings": list(warnings),
                "guard_output": guard_output,
                "artifact_verdict": artifact_verdict,
                "text_penultimate": text_penultimate,
                "meta_overrides": meta_overrides,
                "derived_backfill": derived_backfill,
                "truncated_segments": list(truncated_segments),
                "acts_repair": acts_repair,
                "coverage_reconcile": coverage_reconcile,
            }

            # ---- 门禁判定（`T-086`）----
            if not gate_applies:
                break
            quality_verdict = await quality_gate.check(
                tpl_stage, text=final_text, upstream=gate_upstream
            )
            # ---- `丙`（2026-11-07 裁决）：合并侧「段内重复凑数」→ 可重试失败 ----
            # `uniqueItems` 不在引擎允许面 ⇒ `shots_floor`（`minItems`）只能管个数、
            # 管不住互异；模型重复同一条目凑数时，合并去重会把凑数转化为终态镜数失守
            # （`ab_t101_r2` run6/run10 实证）。`merge_segments` 已把该形态检出为
            # `merge.shot_dup_in_segment｜…` 告警；这里把它**升级为可重试失败**——
            # 报错文本含 `shot_id`，`_retry_segments` 的包含定位可精确命中属主段，
            # 且重试反馈明写「不得重复条目凑数」，打破确定性退化解。
            dup_codes = [w for w in warnings if w.startswith("merge.shot_dup_in_segment｜")]
            if dup_codes:
                quality_verdict = _inject_merge_dup_verdict(quality_verdict, dup_codes)
            gate_verdicts.append({"attempt": attempt, **quality_verdict.as_record()})
            if quality_verdict.ok is True:
                break
            # ⚠️ 「不值得重试」与「没有额度了」是**两种**停止理由，须分别留痕：
            #    前者＝本次失败里没有模型可影响的项（如合规资产未接入），
            #    重试改了也白改 —— 若混成一句「重试用尽」，会误导成「模型不行」。
            if not quality_gate.should_retry(quality_verdict):
                retry_scope_note = "no_retryable_failure"
                break
            # ---- 乙（2026-11-17 裁决「先甲后乙」）：承继字段失败**跳过本段重试** ----
            # 甲试点实锤（`DEV-20261117-001`，0/4 救回）：`camera.*` 出生于 `storyboard`
            # 段，`shot_prompt` 段承继守恒 ⇒ 本段重采结构上无效且有过退化先例。跳过≠放行：
            # 判定照旧走下方 `gate_failed` 分支如实留痕／如实拒绝。
            if (get_settings().quality_gate_retry_feedback
                    and self._retry_targets_inherited_moves(tpl_stage, quality_verdict)):
                retry_scope_note = "retry_skipped_inherited_move"
                logger.info(
                    "quality_gate_retry_skipped",
                    extra={
                        "extra_fields": {
                            "session_id": rec.session_id,
                            "stage": tpl_stage,
                            "attempt": attempt,
                            "reason": "inherited_move_failure",
                            "retryable": quality_verdict.retryable[:8],
                        }
                    },
                )
                break
            # ⚠️ `ISSUE-094`：质量门禁的判停只看**自己**的额度（`quality_max_attempts`）——
            #    循环上限还含形态闸额度，若此处用 `max_attempts`，等于「给形态闸额度」
            #    顺带把 `quality_gate_retry_enabled=false` 打开（裁决之外的副作用）。
            if attempt >= quality_max_attempts:
                break
            # ---- 乙：重采请求**带判据反馈**（盲重试救回 0/4 的直接对策）----
            retry_feedback_pending = (
                self._retry_feedback_text(attempt, quality_verdict)
                if get_settings().quality_gate_retry_feedback else None
            )
            retry_segs, retry_scope_note = self._retry_segments(
                plan, quality_verdict, texts_by_seg, tpl_stage
            )
            # 定位回退 ⇒ 反馈随全段注入 ⇒ 下轮每段带免责句（QA 结论 b 的缓解）。
            retry_feedback_unlocated_pending = retry_scope_note == "scope_fallback"
            logger.info(
                "quality_gate_retry",
                extra={
                    "extra_fields": {
                        "session_id": rec.session_id,
                        "stage": tpl_stage,
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "retry_segments": retry_segs,
                        "retry_scope": retry_scope_note,
                        "retryable": quality_verdict.retryable[:8],
                        "non_retryable": quality_verdict.non_retryable[:8],
                        "feedback_chars": len(retry_feedback_pending or ""),
                    }
                },
            )

        # ---- 用尽重试仍不过：**如实拒绝／如实登记**（`T-086` 硬约束）----
        # 硬约束原文（`PM-001` `T-086`）：用尽重试仍不过则**必须如实拒绝／如实登记，
        # 不得以放行或「后处理修补」兜底**。置入 `meta.notes` 之类「修补」是被禁止的：
        # 那会把「未通过门禁」这件事从产物里抹掉，而备案举证要的正是「产物可追溯到判定」。
        gate_failed = gate_applies and quality_verdict is not None and quality_verdict.ok is not True
        if gate_failed:
            record = gate_verdicts[-1] if gate_verdicts else {}
            if get_settings().quality_gate_enforce:
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"「{tpl_stage}」段产物用尽 {quality_max_attempts} 次尝试仍未通过质量门禁"
                    f"（形态：{quality_verdict.shape}；可重试失败 {len(quality_verdict.retryable)} 项、"
                    f"重试无用 {len(quality_verdict.non_retryable)} 项）",
                    details={
                        "reason": "quality_gate_not_passed",
                        "stage": tpl_stage,
                        "attempts": quality_max_attempts,
                        "gate": record,
                        "retryable": quality_verdict.retryable[:12],
                        "non_retryable": quality_verdict.non_retryable[:12],
                        "retry_scope": retry_scope_note,
                    },
                )
            logger.warning(
                "quality_gate_bypassed",
                extra={
                    "extra_fields": {
                        "session_id": rec.session_id,
                        "stage": tpl_stage,
                        "attempts": len(gate_verdicts),
                        "gate": record,
                        "retry_scope": retry_scope_note,
                        "note": "质量门禁处于受控旁路（quality_gate_enforce=false），未阻断",
                    }
                },
            )

        # ---- `ISSUE-045` 内容足量性探测（**只判、只留痕、不阻断**）----
        # ⚠️ 与形态闸**分成两组字段**：结构过了 ≠ 内容够了。真实模型产物**普遍**在
        #    「Σ镜头时长 ≠ total_duration_ms」「只覆盖第 1 场」上不自洽，若设阻断则
        #    链路直接不可用 ⇒ 质量维度只留痕，供离线门禁与人工抽检消费（项目方 2026-10-16 裁决）。
        adequacy = self._assess_content_adequacy(tpl_stage, final_text, merged)

        logger.info(
            "generation_completed",
            extra={
                "extra_fields": {
                    "session_id": rec.session_id,
                    "stage": tpl_stage,
                    "backend": backend.name,
                    "segment_plan": plan,
                    # ---- 段级 token 与 finish_reason 留痕（`ISSUE-058` 观测补强）----
                    # ⚠️ 截断轮 502 无产物落盘，服务日志是唯一留痕点；
                    #    「segment＋finish_reason＋completion_tokens」三元组足够
                    #    归因「真跑满上限」vs「其他」，避免下一轮再靠延迟反推。
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "segment_trace": _project_segment_trace(trace),
                    "constrained_decoding": json_schema is not None,
                    # `ISSUE-042`：只留一个布尔看不出「约束从哪来」——
                    # 三段此前恒为 false（无落点），现为 derived，须可核查。
                    "engine_schema_source": schema_source,
                    "schema_stripped_keys": list(stripped),
                    "merge_warnings": len(warnings),
                    # `ISSUE-042` 形态闸留痕：`checked` 与 `ok` **分开记**——
                    # 「判过且通过」与「根本没判」在单一布尔上长得一样（本缺陷的教训）。
                    "artifact_shape": (artifact_verdict or {}).get("shape"),
                    "artifact_shape_checked": artifact_verdict is not None,
                    "artifact_shape_ok": (artifact_verdict or {}).get("ok"),
                    "artifact_shape_reason": (artifact_verdict or {}).get("shape_reason"),
                    "artifact_shape_enforced": (artifact_verdict or {}).get("enforced"),
                    # `ISSUE-094`：形态闸重试了几次（`0` ＝ 一次过，无需重采）。
                    # ⚠️ 与 `artifact_shape_checked` 同一纪律：`attempts` 与 `ok` 分开记，
                    #    「判过且一次过」与「判过且重采过」在单一布尔上长得一样。
                    "artifact_shape_retry_attempts": len(shape_attempts),
                    "upstream_admission": upstream_admission or None,
                    # ---- 上游输入体积留痕（`ISSUE-037` 方案 D 的服务层一半；
                    #      `ISSUE-044` 起**按段适用**，仅在真的压小时出现）----
                    # `None` 表示「本段不适用」或「无可压」（均非异常）。
                    "upstream_compaction": compact_trace or None,
                    # ---- `ISSUE-045` 内容足量性留痕（**只判不拦**）----
                    # `checked` 与 `ok` 分开记，同形态闸的理由：单布尔分不出「没判」与「判过」。
                    "content_adequacy_checked": adequacy.get("checked"),
                    "content_adequacy_ok": adequacy.get("ok"),
                    "content_adequacy_findings": [
                        f.get("code") for f in (adequacy.get("findings") or [])
                    ],
                    # ---- 安全双闸留痕（`T-005`）----
                    "safety_enforced": (guard_input or {}).get("enforced"),
                    "safety_input_blocked": (guard_input or {}).get("blocked"),
                    "safety_input_checked_fields": (guard_input or {}).get("checked_fields"),
                    "safety_output_action": (guard_output or {}).get("action"),
                    "safety_output_hit_count": (guard_output or {}).get("hit_count"),
                    # ---- `T-086` 质量门禁与重试回路留痕 ----
                    # ⚠️ 与形态闸同一纪律：`checked`／`ok` **分开记**，且 `ok` 是三态
                    #    （`True`／`False`／`None`＝无法判定）。「没判」不得长得像「判过」。
                    "quality_gate_applies": gate_applies,
                    "quality_gate_attempts": len(gate_verdicts),
                    "quality_gate_max_attempts": quality_max_attempts,
                    "quality_gate_ok": (quality_verdict.ok if quality_verdict else None),
                    "quality_gate_shape": (quality_verdict.shape if quality_verdict else None),
                    "quality_gate_retryable": (
                        len(quality_verdict.retryable) if quality_verdict else None
                    ),
                    "quality_gate_non_retryable": (
                        len(quality_verdict.non_retryable) if quality_verdict else None
                    ),
                    "quality_gate_retry_scope": retry_scope_note,
                    "quality_gate_enforced": (
                        quality_verdict.enforced if quality_verdict else None
                    ),
                    # ---- 服务层真值覆盖留痕（`T-086` 配套）----
                    "service_truth_overridden": bool(
                        meta_overrides and any(v.get("changed") for v in meta_overrides.values())
                    ),
                    "service_truth_fields": (
                        sorted(k for k, v in (meta_overrides or {}).items() if v.get("changed"))
                    ),
                }
            },
        )

        artifact: dict[str, Any] = {
            "template_id": template.id,
            "template_version": template.version,
            "backend": backend.name,
            "text": final_text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            # ---- `T-004` 新增留痕：生成过程的可复现凭据 ----
            "model": {"name": backend.name, "version": backend.version},
            "segment_plan": plan,
            "segments": trace,
            "constrained_decoding": json_schema is not None,
            # ---- `ISSUE-042` 新增留痕：形态闸的判定结果（**可核查「判过没有」**）----
            "artifact_shape": (artifact_verdict or {}).get("shape"),
            "artifact_shape_checked": artifact_verdict is not None,
            "artifact_shape_ok": (artifact_verdict or {}).get("ok"),
            "artifact_shape_enforced": (artifact_verdict or {}).get("enforced"),
            # ---- `ISSUE-045` 新增留痕：内容足量性（**只判不拦**，与形态闸**分组**留痕）----
            "content_adequacy": adequacy,
            # ---- `T-086` 新增留痕：门禁与重试（**逐次尝试**，可核查「重试了没有」「改了什么」）----
            "quality_gate": {
                "applies": gate_applies,
                "max_attempts": quality_max_attempts,
                "attempts": len(gate_verdicts),
                "ok": (quality_verdict.ok if quality_verdict else None),
                "enforced": (quality_verdict.enforced if quality_verdict else None),
                "retry_scope": retry_scope_note,
                "history": gate_verdicts,
                # ⚠️ 未通过时的明细**必须留下**：它是 `T-087`（资产侧提质）的唯一依据，
                #    也是「如实拒绝」时可向项目方举证的内容。
                "last_retryable": (quality_verdict.retryable if quality_verdict else []),
                "last_non_retryable": (quality_verdict.non_retryable if quality_verdict else []),
            },
        }
        if segment_contributions:
            artifact["segment_contributions"] = segment_contributions
        if shape_attempts:
            # `ISSUE-094` 留痕：形态闸**重采过**的逐次失败明细（第几次／原因码／阶段／
            # 元素级定位串／报错摘要）。⚠️ 同 `amp_norm`／`appearance_echo_clean` 纪律——
            # **无重试（空列表）不写**，不污染每一次生成；一旦重采过就必须留：
            # 否则「产物是第一次采的还是第二次采的」在留痕上无从区分，
            # 而形态闸恰恰改的就是「采几次」这件事。
            # ⚠️ 落点说明：`artifact["artifact_shape"]` 是**形态名字符串**（多份既有测试
            #   断言其等于 `"pack"`／`"storyboard"` 等），不能改成对象把明细塞进去；
            #    故明细落在这组 `artifact_shape_*` 同族字段的**兄弟键**上，键名自带语义。
            artifact["artifact_shape_retry"] = {
                "attempts": len(shape_attempts),
                "attempts_history": shape_attempts,
            }
        if meta_overrides:
            # 覆盖清单（含未变更项）一并留痕：可核查「覆盖**看过**哪些字段」，
            # 与「覆盖**改过**哪些字段」是两件事（同 `checked`/`ok` 分列的纪律）。
            artifact["service_truth"] = meta_overrides
            artifact["service_truth_text_changed"] = final_text != text_penultimate
        if derived_backfill:
            # 派生量回填留痕（`R14`）：`original` 是**模型自拟值**，`computed` 是服务层重算值。
            # ⚠️ 必须留 `original`——只留 `computed` 就等于「产物被动过但查不出来」。
            artifact["derived_backfill"] = derived_backfill
            artifact["derived_backfill_text_changed"] = any(
                v.get("changed") for v in derived_backfill.values()
            )
        if identity_norm:
            # 标识归一化留痕（`R7`/`R9`；`T-100` 逐场编排配套）：`original_sample` 是
            # **模型原值样例**——逐场各从 `S01-SH001`／`U01` 起编是必然形态，必须能查出
            # 「产物里的编号是模型写的还是服务层改的」。
            artifact["identity_normalize"] = identity_norm
            artifact["identity_normalize_changed"] = any(
                bool(v.get("changed")) for v in identity_norm.values() if isinstance(v, dict)
            )
        if amp_norm and amp_norm.get("cleaned"):
            # `T-103` 机械清洗留痕：逐镜明细＋删前/删后正文摘要（不落原文）。
            # ⚠️ 只在**确有清洗**时记：`cleaned=0` 的 noop 不写，避免污染每次生成。
            artifact["camera_amp_speed_normalize"] = amp_norm
        if en_camera_fill and en_camera_fill.get("added"):
            # 投影规则⑤留痕（项目方 2026-11-16 裁决）：逐镜「镜号／运镜／补的句子」＋摘要。
            # ⚠️ 同 `amp_norm` 纪律——`added=0` 的 noop 不写（不污染每次生成）；
            #    但**一旦补过就必须留**：否则「产物里的运镜句是模型写的还是服务层补的」
            #    无从区分，那是本工程明令禁止的「静默修补」。
            artifact["en_camera_sentence"] = en_camera_fill
        if appearance_echo_clean and appearance_echo_clean.get("scrubbed"):
            # 投影规则⑥留痕（项目方 2026-11-16 裁决）：逐镜「镜号／语言／命中 gram／删除长度」
            # ＋删前/删后正文摘要。⚠️ **不落原文**（与 `camera_amp_speed_normalize` 同纪律）：
            # 只留 gram 与长度，正文本身在产物里；留痕再抄一份等于把外观描写**二次散布**。
            # ⚠️ 同 `amp_norm` 纪律——`scrubbed=0` 的 noop 不写（不污染每次生成）；
            #    一旦删过就必须留：否则「正文少了那句是模型没写还是服务层删的」无从区分。
            artifact["appearance_echo_clean"] = appearance_echo_clean
        if acts_repair:
            # 批次1a（`ISSUE-095`/`096`）留痕：双重序列化 acts/scenes 元素的逐处解包
            # 明细（索引＋归属）。⚠️ 同 `amp_norm` 纪律——noop 不写（不污染每次生成）；
            # 一旦修过就必须留：否则「acts[i] 是对象是模型写对的还是服务层解包的」
            # 无从区分，那是本工程明令禁止的「静默修补」。
            artifact["acts_repair"] = acts_repair
        if coverage_reconcile:
            # 批次 2 一期（覆盖分配器）留痕：台词延时长/光线回填的逐镜 before/after。
            # ⚠️ 同 `amp_norm`/`acts_repair` 纪律——noop 不写键；改过必留：
            # 「产物里的时长/光线是模型写的还是服务层兜底的」必须可核查。
            artifact["coverage_reconcile"] = coverage_reconcile
        if upstream_admission:
            artifact["upstream_admission"] = upstream_admission
        if compact_trace:
            # `ISSUE-044` 起**只在适用阶段**出现（默认仅 `shot_prompt`）；
            # 与日志同源的留痕，供离线审计核查「这一段到底紧凑了没有」。
            artifact["upstream_compaction"] = compact_trace
        if warnings:
            artifact["merge_warnings"] = warnings
        # `ISSUE-063`／裁决 6：storyboard 合并后的外观锚逐场重述分布**留痕**（只观测不裁决）
        if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "storyboard":
            anchor_probe = _probe_storyboard_anchor_echo(
                final_text, (merged or {}).get("script_json")
            )
            if anchor_probe is not None:
                artifact["appearance_anchor_echo_probe"] = anchor_probe
        if guard_input is not None or guard_output is not None:
            # 留痕（`T-005`）：可核查的是**分类码与计数**，命中词明文**不入库**
            artifact["safety"] = {"input": guard_input, "output": guard_output}
        rec.artifacts[key] = artifact

    def _move(self, rec: SessionRecord, src: Stage, dst: Stage, action: str) -> None:
        rec.stage = dst.value
        rec.history.append(f"{src.value} --{action}--> {dst.value}")
        self.repo.save(rec)

    @staticmethod
    def _result(
        rec: SessionRecord, action: str, src: Stage, dst: Stage
    ) -> TransitionResult:
        return TransitionResult(
            session_id=rec.session_id,
            action=action,
            from_stage=src,
            to_stage=dst,
            stage_label=sm.label_of(dst),
            view=DialogueService._view(rec),
        )


def _artifact_key_of(stage: Stage) -> str | None:
    """阶段 → 该阶段持有的产物键。"""
    if stage in (Stage.SYNOPSIS_REVISING, Stage.SYNOPSIS_CONFIRMED):
        return "synopsis"
    return _GENERATE_ON.get(stage, (None, None))[0]


def _params_of(sampling: dict[str, Any]) -> GenParams:
    allowed = {"temperature", "top_p", "top_k", "max_tokens", "repetition_penalty"}
    kwargs = {k: sampling[k] for k in allowed if k in sampling}
    if "stop" in sampling and isinstance(sampling["stop"], (list, tuple)):
        kwargs["stop"] = tuple(sampling["stop"])
    return GenParams(**kwargs)


# ---- `T-117` ①：script 段 `max_tokens` 收口值（跑飞快速失败的成本护栏）----
# 实测依据（b23 复测 `DEV-20261124-007`）：head 正常产出 822~1435 tok ⇒ 2048 ≈ 1.4×
# 正常上限；scene 正常产出 235~389 tok ⇒ 4096 ≈ 10×（est 大的场留足余量）。
# ⚠️ 收口不解决跑飞本身（那是 ② dialogue maxItems 的职责），只把「跑飞烧满
# 8192 再失败」压成「快速失败进按段重采」——r2 head 两连撞 8192 的代价实证。
SCRIPT_HEAD_MAX_TOKENS = 2048
SCRIPT_SCENE_MAX_TOKENS = 4096


def _script_head_sampling(seg_params: GenParams) -> GenParams:
    """script `package_head` 段的 `max_tokens` 收口（`T-117` ①）。

    ⚠️ 只动 `max_tokens`，**不动温度**——`_package_head_sampling` 的降温 0.4 是
    shot_prompt head（元数据复述）的行为；script head 是设计类创作（QA 证伪 L3
    裁决维持模板 0.8），不得连带（同批同函数族的两处语义须各守各的授权面）。
    """
    return replace(
        seg_params, max_tokens=min(seg_params.max_tokens, SCRIPT_HEAD_MAX_TOKENS)
    )


# ---- `T-117` ②：dialogue 行数上限的派生参数 ----
# 同源推导：预算字数（est × DIALOGUE_SPEED_MAX）÷ 每行**最短**字数 ⇒ 行数上限。
# QA 证伪 ①（2026-11-25）：分母取 4 会压制短行——est=10s 时上限仅 22 行，
# 而中文有效台词行可短至 2 字（「走。」「好。」），被 xgrammar **静默闭数组**
# 无任何信号 ⇒ 取 **2**（真实下限，est=10s ⇒ 45 行，距正常产出 5~15 行仍有余量）。
SCRIPT_DIALOGUE_MIN_CHARS_PER_LINE = 2
# QA 证伪 ④（适用域上端）：est≈120s 时派生 540 行失去约束意义 ⇒ **绝对封顶**
# 160 行（est≈71s 触顶；仍远高于正常产出 5~15 行，拦得住数百行的跑飞形态）。
SCRIPT_DIALOGUE_MAX_ITEMS_CAP = 160


# ---- `T-118` ②：下游段 `max_tokens` 收口值（跑飞快速失败的成本护栏）----
# 实测依据（`.wb-e2e/_all_tokmax.py` 对全部历史 app 日志的逐段 stop 终态采集，
# 合计 ~345 个 stop）：storyboard 场段 stop 极值 **3303** tok（n=41）⇒ 4096 ≈ 1.24×；
# shot_prompt 单元段 stop 极值 **6672** tok（n=216）⇒ 8192 ≈ 1.23×。两处上限均高于
# **全部**历史正常 stop 产出 ⇒ 正常轮零影响；跑飞轮（b24 r1 shot_prompt unit:U01、
# r7 storyboard scene:1/scene:3，历史 length 事件各烧满 12288/8192）在此快速失败
# 进按段重采，单次跑飞成本 12288→8192／8192→4096。
# ⚠️ 授权面与 `T-117` ① 同款：只动 `max_tokens` 不动温度。
# ⚠️ shot_prompt `package_head` **不动**（维持 B3 的 8192）：现行证据（b24 十轮
#    45 次 stop 极值 1323）与 B3 立项口径（正常 ≈5319 tok，`artifacts_t086`）冲突，
#    且 b24 十轮 head 零跑飞 ⇒ 证据冲突时不改口径（登记于复测判读）。
STORYBOARD_SCENE_MAX_TOKENS = 4096
SHOT_PROMPT_UNIT_MAX_TOKENS = 8192


def _script_dialogue_max_items(
    script_ctx: dict[str, Any] | None, seg: str
) -> int | None:
    """`scene:<no>` 段的 `dialogue` 行数解码上限（`T-117` ②）。

    est 异常（缺失/非数值/≤0）或段名非场段 ⇒ `None`＝不加约束——缺数据就不造
    硬数字，硬数字造错比没有更危险（与 scope 的「缺失 ⇒ 保守提示」口径一致）。
    """
    if not script_ctx:
        return None
    try:
        no = int(seg.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    scene = (script_ctx.get("scenes") or {}).get(no) or {}
    est = scene.get("est_seconds")
    if isinstance(est, bool) or not isinstance(est, (int, float)) or est <= 0:
        return None
    return min(
        max(
            1,
            int(est) * DIALOGUE_SPEED_MAX // SCRIPT_DIALOGUE_MIN_CHARS_PER_LINE,
        ),
        SCRIPT_DIALOGUE_MAX_ITEMS_CAP,
    )


def _script_truncation_feedback(
    bad_segs: list[str], script_ctx: dict[str, Any] | None
) -> str:
    """script 段截断重采的**预算数字反馈**（`T-117` ③）。

    复测 r2/r4 实锤：script 段重采兜底 0/3——泛化反馈（「收敛输出」）对跑飞
    无约束力，模型不知道「收到多少才算停」。按段给出硬数字（同源值，非新造）：
    head 段给骨架规模；场段给台词字数/行数预算。
    """
    parts: list[str] = []
    for seg in bad_segs:
        if seg == "package_head":
            parts.append(
                f"{seg}：正确骨架 ≈800~1500 tokens——只出锚点键与 acts[].scene_nos，"
                "不写任何场正文（action/dialogue），写完即停。"
            )
            continue
        if not seg.startswith("scene:"):
            continue
        try:
            no = int(seg.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        scene = ((script_ctx or {}).get("scenes") or {}).get(no) or {}
        est = scene.get("est_seconds")
        if isinstance(est, bool) or not isinstance(est, (int, float)) or est <= 0:
            parts.append(f"{seg}：台词总量保守控制（总字数 ≤ 200 字），写完即停。")
            continue
        budget_chars = int(est) * DIALOGUE_SPEED_MAX
        max_items = _script_dialogue_max_items({"scenes": {no: scene}}, seg)
        parts.append(
            f"{seg}：台词总字数 ≤ {budget_chars} 字（est_seconds={int(est)} × "
            f"{DIALOGUE_SPEED_MAX} 字/秒上限；dialogue 行数 ≤ {max_items} 行），"
            "action 收敛不铺陈，写完即停。"
        )
    return "".join(parts)


def _package_head_sampling(seg_params: GenParams) -> GenParams:
    """`package_head` 段的采样参数收紧（`ISSUE-084` B3）。

    只对**头部元数据段**生效，不影响 `unit:<id>`／`scene:<no>` 的镜头创意正文
    （`SW-007` 给 `TPL-009` 定的 `temperature=0.7` 因而保持原样）。

    ① 降温 0.7→0.4：`package_head` 产出的是 `meta`／`style_bible`／`characters`
       等**元数据**而非镜头创意正文，需要的是稳定复述而非发散；降温抑制
       自由文本 ramble。r6 run8 实测该段**真跑满 12288 tokens** 致整轮作废
       （约 28 分钟/轮），而该段正常产出仅 ≈5.3K tokens——高温度下的
       自由发挥是退化的可疑来源。
    ② `max_tokens` 封顶 8192（快速失败）：正常产出 ≈5.3K 不受影响；真退化的
       轮次从「12288 tokens／≈28 分钟」降到 8192 级，`T-086` 的按段重试代价
       同步下降——把「整轮作废」压成「单段重试」。

    两者均取 `min` 语义：模板本就比阈值更保守时（例如日后调低到
    `temperature=0.3`）**不放大**，只收紧。

    Args:
        seg_params: 模板采样解析出的原始参数（`_params_of(template.sampling)`）。

    Returns:
        收紧后的**新** `GenParams`（`GenParams` 为 frozen dataclass，不改入参）。
    """
    # ⚠️ 常量内联而非新建设置项：这是一次针对观察轮的定向收口，
    # 可调性由「删掉这几行」提供，不需要额外的配置面。
    return replace(
        seg_params,
        temperature=min(seg_params.temperature, 0.4),
        max_tokens=min(seg_params.max_tokens, 8192),
    )


def _as_text(artifact: Any) -> str:
    if isinstance(artifact, str):
        return artifact
    return json.dumps(artifact, ensure_ascii=False)


def _artifact_text(artifact: Any) -> str:
    """取产物的**模型输出正文**（上游模板要的是它的输出原文，不是包装信封）。"""
    if isinstance(artifact, dict) and "text" in artifact:
        return str(artifact["text"])
    return _as_text(artifact)


def _compact_upstream_json(raw: str) -> tuple[str, dict[str, int]]:
    """把上游产物 JSON 文本压成**紧凑形态**（`ISSUE-037` 方案 D 的服务层一半）。

    模板侧（`TPL-009` v2.1.1）已把上游从「注入 5 次」改为「每变量各只注入一次」；
    本函数再削掉 JSON 里的缩进与换行（`separators=(",", ":")`）。

    三条纪律（本函数**不得**成为新的失败点、也不得改变语义）：
    - **只去空白**：键序、键值、数值精度、Unicode 转义一律不变（`ensure_ascii=False`
      保持中文可读）；解析走 `parse_json_object`，与本工程既有的围栏/前后缀容忍**同一口径**；
    - **解析失败一律原样返回**：这是**体积优化**，不是校验环节——上游解析不了时
      `_segment_plan` 已有独立的告警通道，此处**不得**抢先报错；
    - **不改产物**：只作用于「交给模型的变量」，会话里存的 `artifact["text"]` 仍是模型原文。

    返回 `(文本, 元信息)`；元信息含 `changed`（0/1）与前后字符数，供日志留痕与审计。
    """
    info = {"changed": 0, "chars_before": len(raw) if isinstance(raw, str) else 0}
    if not isinstance(raw, str) or not raw.strip():
        info["chars_after"] = info["chars_before"]
        return raw, info
    try:
        parsed = parse_json_object(raw)
    except AppError:
        info["chars_after"] = len(raw)
        return raw, info
    compacted = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    info["chars_after"] = len(compacted)
    if len(compacted) >= len(raw):  # 没变小就保持「原文即所见」，不做无谓改动
        info["chars_after"] = len(raw)
        return raw, info
    info["changed"] = 1
    return compacted, info


def _loads_json_value(s: str) -> Any:
    """字符串 → JSON 值；解析失败返回 `None`（调用方以 `isinstance(..., dict)` 判定）。

    ⚠️ 必须同捕 `RecursionError`（独立 QA 证伪 D1）：深嵌套 JSON 字符串
    `json.loads` 抛的是 `RecursionError`（非 `ValueError` 子类）——只捕 ValueError
    会把它逃逸成整轮硬崩，把修复前的「可重试失败」（形态闸拒字符串 ⇒ 重采）
    变成「不可重试崩溃」，失败模式反而变差。语义＝解析不了就不碰，留给形态闸拒。
    """
    try:
        return json.loads(s)
    except (ValueError, RecursionError):
        return None


def _repair_acts_strings(raw: str) -> tuple[str, dict[str, Any] | None]:
    """**acts 元素级预修复**（批次1a，`ISSUE-095`/`096`）：把**双重序列化**的
    `acts[i]`／`acts[i].scenes[j]` 元素从 JSON 字符串解析回对象。

    缺陷现场（分层对照两臂 30 轮实测）：模型偶发把剧本的某一幕（场）**再序列化一层**
    ——`acts[i]` 的值是一个 JSON 字符串，其内容本是合法对象。形态闸第四层当场拒绝
    （`script_structure_invalid` ⇒ 重采），重采再犯 ⇒ 整轮失败，是达标率天花板的
    主失败族之一。该形态是**确定可修**的：内容本身合法，只是多包了一层引号。

    三条纪律（与 `_compact_upstream_json` 同族）：
    - **只修确定可修的**：仅当元素是字符串、且 `json.loads` 的结果是**对象（dict）**
      才解包；纯文本（真机现场 `acts[2]＝"第三幕：直接写成了字符串"`）、解析出
      非对象（数组／标量）、二次序列化（字符串里还是字符串）**一律不碰**，
      原样留给形态闸裁决——本层只修「确定可修」的，不洗白任何真缺陷；
    - **解析失败原样返回**：本函数不是校验环节，上游/产物解析不了时不得抢先报错；
    - **修过必留痕**：返回值带逐处定位（索引/形态），调用方写进 `artifact["acts_repair"]`；
      noop 返回 `(原文, None)`（同 `amp_norm` 纪律：不污染每次生成）。

    返回 `(修复后文本, 修复明细 | None)`；文本变更时以 `ensure_ascii=False`
    重序列化（中文可读性守恒）。
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw, None
    try:
        doc = parse_json_object(raw)
    except AppError:
        return raw, None
    if not isinstance(doc, dict):
        return raw, None
    acts = doc.get("acts")
    if not isinstance(acts, list):
        return raw, None

    unwrapped_acts: list[int] = []
    unwrapped_scenes: dict[str, list[int]] = {}
    for ai, act in enumerate(acts):
        if isinstance(act, str):
            parsed_act = _loads_json_value(act)
            if isinstance(parsed_act, dict):
                acts[ai] = parsed_act
                unwrapped_acts.append(ai)
        act = acts[ai]
        if not isinstance(act, dict):
            continue
        scenes = act.get("scenes")
        if not isinstance(scenes, list):
            continue
        for si, scene in enumerate(scenes):
            if isinstance(scene, str):
                parsed_scene = _loads_json_value(scene)
                if isinstance(parsed_scene, dict):
                    scenes[si] = parsed_scene
                    unwrapped_scenes.setdefault(f"acts[{ai}]", []).append(si)
    if not unwrapped_acts and not unwrapped_scenes:
        return raw, None
    info: dict[str, Any] = {
        "changed": True,
        "acts_unwrapped": unwrapped_acts,
        "scenes_unwrapped": unwrapped_scenes,
    }
    return json.dumps(doc, ensure_ascii=False), info


def _run_coverage_reconcile(text: str) -> tuple[str, dict[str, Any] | None]:
    """覆盖分配器的**调用包装**：仅对 `storyboard`/`pack` 形态生效。

    解析失败原样返回（本层不是校验环节，同 `_compact_upstream_json` 口径）；
    有改动时以 `ensure_ascii=False` 重序列化（中文可读性守恒）。
    """
    try:
        doc = parse_json_object(text)
    except AppError:
        return text, None
    if not isinstance(doc, dict):
        return text, None
    changed, trace = reconcile_coverage_gaps(doc)
    if not changed:
        return text, None
    return json.dumps(doc, ensure_ascii=False), trace


def _upstream_json(artifact: Any) -> dict[str, Any] | None:
    """从上游产物取 JSON 对象（产物正文即模型输出的 JSON 串）。

    ⚠️ 解析走 `parse_json_object` —— 与**上游准入闸**（`ISSUE-042`）**同一套口径**
    （围栏／前后缀容忍一致）。此前此处用裸 `json.loads`，会出现
    「闸门判可解析、分段计划却判不可解析」的**分裂口径**：同一份上游两种结论。

    解析失败返回 `None`，由调用方**显式留告警**——不假装已知上游结构。
    ⚠️ 注意：`shape_gate_enforce=true` 时本分支**不可达**（准入闸已先阻断）；
    此处保留 `None` 路径是为了让受控旁路下仍能如实留痕，而不是为了「继续跑」。
    """
    if not isinstance(artifact, dict):
        return None
    text = artifact.get("text")
    if isinstance(text, str):
        try:
            return parse_json_object(text)
        except AppError:
            return None
    return artifact


def _probe_storyboard_anchor_echo(final_text: str, script_json: str | None) -> dict[str, Any] | None:
    """`ISSUE-063`／裁决 6（2026-11-05 按 B）：合并后外观锚「逐场重述分布」**留痕级探测**。

    背景：逐场编排（`T-100`）下每场只看到全局 `style_bible` ＋ `prev_scene_tail`，
    看不到其他场已落地的具体外观写法 ⇒ 实测 `R23` off 2/12 → on 4/12。
    本探测把「每场各有多少镜重述了外观锚、重述了哪些锚」量化留痕，供
    「是否扩 `prev_scene_tail`（修法候选①）」的裁决取证。

    ⚠️ 纪律：**只观测、不裁决**——不进 `retryable`／不改 `ok`／不动 `R23` 语义
    （裁决 6 明写不新造 `R` 判据）。n-gram 口径直接复用门禁已加载的
    `validate_output` 模块（`_anchors`／`_anchor_ngrams`／`_semantic_text`），
    不抄第二份（与「判据唯一」同族纪律：两套口径漂移即失真）。
    返回 `None` 表示不适用（非 storyboard／无上游剧本／判据模块缺失）。
    """
    engine = quality_gate._engine_validator()  # noqa: SLF001 - 复用判据模块的官方加载口
    if engine is None:
        return None
    try:
        sb = json.loads(final_text)
    except Exception:  # noqa: BLE001 - 探测对象非法 ⇒ 探测不适用（生成侧另有报错链）
        return None
    script: Any = None
    if script_json:
        try:
            script = json.loads(script_json)
        except Exception:  # noqa: BLE001
            script = None
    if not isinstance(sb, dict) or not isinstance(script, dict):
        return None
    anchors = engine._anchors(script)  # noqa: SLF001
    if not anchors:
        return {"probe": "ISSUE-063", "anchors": 0, "note": "上游无 appearance_lock_zh，无可比对象"}
    gram_src = [(label, engine._anchor_ngrams(a)) for label, a in anchors]  # noqa: SLF001
    scenes: dict[str, dict[str, Any]] = {}
    for shot in sb.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        sc = str(shot.get("scene_no"))
        st = scenes.setdefault(
            sc, {"shots": 0, "echo_shots": 0, "echo_grams": 0, "anchors_touched": set()}
        )
        st["shots"] += 1
        text = engine._semantic_text(shot)  # noqa: SLF001
        if not text:
            continue
        hit_grams = 0
        hit_labels: set[str] = set()
        for label, grams in gram_src:
            got = {g for g in grams if g in text}
            if got:
                hit_grams += len(got)
                hit_labels.add(label)
        if hit_grams:
            st["echo_shots"] += 1
            st["echo_grams"] += hit_grams
            st["anchors_touched"] |= hit_labels
    rows = []
    rates = []
    for sc in sorted(scenes, key=lambda x: (len(x), x)):
        st = scenes[sc]
        rate = (st["echo_shots"] / st["shots"]) if st["shots"] else 0.0
        rates.append(rate)
        rows.append({
            "scene_no": sc,
            "shots": st["shots"],
            "echo_shots": st["echo_shots"],
            "echo_rate": round(rate, 4),
            "echo_grams": st["echo_grams"],
            "anchors_touched": sorted(st["anchors_touched"]),
        })
    return {
        "probe": "ISSUE-063",
        "note": "留痕级探测（裁决 6）：只观测不裁决、不改 R23；n-gram 口径复用 validate_output",
        "anchors": len(anchors),
        "scenes": rows,
        "spread": {
            "echo_rate_min": round(min(rates), 4) if rates else None,
            "echo_rate_max": round(max(rates), 4) if rates else None,
        },
    }


def _reconcile_pack_conservation(
    tpl_stage: str, text: str, gate_upstream: dict[str, str] | None
) -> tuple[str, list[str]]:
    """`甲`（2026-11-07 项目方裁决，`DEV-20261107-004` §五）：`shot_prompt` 包镜集合守恒的构造保证。

    **背景**（r2／r3 两批实证）：`uniqueItems` 不在引擎允许面 ⇒ `shots_floor`
    （`minItems`）管得住个数、管不住互异；事后闸（裁决丙的 dup 检出）只能拦
    「已生成的退化解」，拦不住「首轮无凑数、次轮才掉镜」（`ab_t101_r3` on#01／
    on#08，缺的恒为上游 `S01-SH003`）⇒ **集合守恒类硬约束只能由构造保证**
    （与 `T-100` 场覆盖的构造保证同源）。

    **做法**：门禁判定前，校验「`shots[]` ⊇ 上游分镜镜集合」；上游有而本层缺的镜，
    按上游镜定义**补占位条目**——`camera`／`duration_ms`／`action`／`shot_language`
    等**两层同形态**的机械承继字段照抄上游（与承继层「一字不得改」同口径），
    `prompt_zh` 由 `action` 三段派生，**`prompt_en` 留空**（不伪造创作内容，交
    `R27` 等判据如实判）；`notes` 明写「服务层构造占位」。
    补镜后 `shots[]` **按上游镜序重排**（v1.1 修正，`DEV-20261107-006`）——
    `R31 PACK_DURATION_LOCK` 是**位置 zip 比对**（`zip(up_ids, now_ids)`），
    追加在尾部会使缺位之后所有镜位置错位、整串误报「时长被改动」。

    ⚠️ **只补「上游有、本层缺」**；本层凭空多出的镜（幻觉镜号）**不删**——另一类错误，
       交 `R31` 逐镜比对如实判。
    ⚠️ **不洗白**：每次补镜产生 `merge.shot_conservation_fill｜…` 告警（进
       `merge_warnings`／run 记录），模型真实漏镜率可离线统计。
    ⚠️ 产物不可解析／无上游／非 `shot_prompt` 段 ⇒ **原样返回**（不猜测、不静默）。
    """
    if tpl_stage != "shot_prompt":
        return text, []
    settings = get_settings()
    if not settings.pack_conservation_fill:
        return text, []
    upstream_text = (gate_upstream or {}).get("storyboard")
    if not upstream_text:
        return text, []
    try:
        upstream_doc = json.loads(upstream_text)
    except Exception:
        return text, []
    upstream_shots = upstream_doc.get("shots")
    if not isinstance(upstream_shots, list) or not upstream_shots:
        return text, []
    try:
        doc = parse_json_object(text)
    except Exception:
        return text, []
    shots = doc.get("shots")
    if not isinstance(shots, list):
        return text, []
    have = {
        s.get("shot_id") for s in shots if isinstance(s, dict) and s.get("shot_id")
    }
    style_ref_default = upstream_doc.get("style_ref")
    fills: list[str] = []
    for up in upstream_shots:
        if not isinstance(up, dict):
            continue
        sid = up.get("shot_id")
        if not sid or sid in have:
            continue
        action = up.get("action") if isinstance(up.get("action"), dict) else {}
        prompt_zh = "；".join(
            str(action.get(k, "")).strip()
            for k in ("start", "change", "end")
            if str(action.get(k, "")).strip()
        )
        placeholder = {
            "shot_id": sid,
            "unit_id": up.get("unit_id"),
            "scene_no": up.get("scene_no"),
            "shot_no": up.get("shot_no"),
            "shot_size": up.get("shot_size"),
            "camera": up.get("camera"),
            "duration_ms": up.get("duration_ms"),
            "prompt_zh": prompt_zh,
            "prompt_en": "",
            "action": up.get("action"),
            "shot_language": up.get("shot_language"),
            "style_ref": style_ref_default,
            "character_refs": up.get("character_refs") or [],
            "prop_refs": up.get("prop_refs") or [],
            # ⚠️ v1.1（DEV-20261107-006）：`lighting`／`dialogue`／`sfx`／`transition_*`
            #    **不照抄**——它们是层间形态不同的表达层字段（上游分镜层 `lighting`
            #    是「词表值——说明」散文形态，shot_prompt 层 R32 要纯词表 code；
            #    R33 的规则即「留空须省略键」）。占位镜没有真实表达内容，省略这些键
            #    交判据如实判／后续补写。
            "notes": _PLACEHOLDER_NOTES_PREFIX + "（2026-11-07 裁决甲）：模型漏生成本镜；"
            "机械承继字段引用上游分镜镜定义，prompt_zh 由 action 派生，"
            "prompt_en 留空待补——占位本身不构成创作合格，交判据如实判。",
        }
        shots.append({k: v for k, v in placeholder.items() if v is not None})
        fills.append(
            f"merge.shot_conservation_fill｜服务层按裁决甲补占位镜「{sid}」"
            f"（单元 {up.get('unit_id')}；上游有而本层缺——机械字段引上游，"
            "prompt_en 留空如实待判；兜底不洗白，本告警计入模型漏镜率）"
        )
    if not fills:
        return text, []
    # ⚠️ v1.1：按上游镜序重排（R31 位置 zip 比对要求位置同序）；本层多出的
    #    幻觉镜号不进上游序，保持原相对顺序置于末尾，交 R31 如实判。
    up_order = {
        up.get("shot_id"): i for i, up in enumerate(upstream_shots)
        if isinstance(up, dict) and up.get("shot_id")
    }
    known = [s for s in shots if isinstance(s, dict) and s.get("shot_id") in up_order]
    unknown = [s for s in shots if not (isinstance(s, dict) and s.get("shot_id") in up_order)]
    known.sort(key=lambda s: up_order[s["shot_id"]])
    doc["shots"] = known + unknown
    return json.dumps(doc, ensure_ascii=False, indent=2), fills


def _inject_merge_dup_verdict(verdict: Any, dup_codes: list[str]) -> Any:
    """`丙`（2026-11-07 裁决）：把合并侧检出的「段内重复凑数」注入门禁结论。

    `uniqueItems` 不在引擎允许面 ⇒ `shots_floor`（`minItems`）只管个数、管不住互异；
    模型重复同一条目凑数时，合并去重会把凑数转化为终态镜数失守（`ab_t101_r2`
    run6/run10 实证）。`merge_segments` 检出为 `merge.shot_dup_in_segment｜…` 告警；
    本函数把它**升级为可重试失败**（`ok=False` ＋ `retryable` 追加）——报错文本含
    `shot_id`，`_retry_segments` 的包含定位可精确命中属主段，且重试反馈明写
    「不得重复条目凑数」，打破确定性退化解。
    """
    return verdict._replace(
        ok=False,
        retryable=verdict.retryable
        + [f"{w}（裁决丙：重试纪律——不得用重复条目凑 minItems 下限）" for w in dup_codes],
    )


def _project_segment_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``generation_completed`` 日志的段级 trace **投影**（留痕契约）。

    键集即「日志可复核面」：``segment``／``finish_reason``／``completion_tokens``
    （`ISSUE-058` 观测补强三元组）＋ ``storyboard_scope``／``schema_capped``
    （`T-101`／`PRO-015`：裁剪与收窄是否生效——否则「以为开了、实际没开」在
    留痕上无法区分，`ISSUE-042` 同源教训：缺布尔就无法举证）＋
    ``dialogue_max_items``（`T-118` ④：`T-117` ② 观测位补投影——trace 生成端
    早已带键、投影一直缺 ⇒ 「上限实际取值」全日志零命中，b24 十轮实测）。

    ⚠️ 抽成函数是为**键集可断言**：内联推导式无测试抓手，投影缺字段这种
    「观测位失效」（SW-011 同族）只能等事故后从日志反推。
    """
    return [
        {
            "segment": t.get("segment"),
            "finish_reason": t.get("finish_reason"),
            "completion_tokens": t.get("completion_tokens"),
            "storyboard_scope": t.get("storyboard_scope", "full"),
            "schema_capped": bool(t.get("schema_capped", False)),
            "dialogue_max_items": t.get("dialogue_max_items"),
        }
        for t in trace
    ]


def _merge_parts(
    texts: list[str],
    tpl_stage: str = "",
    upstream: dict[str, Any] | None = None,
    segs: list[str] | None = None,
) -> tuple[str, list[str]]:
    """多段产物 → 合并后的完整包文本（＋合并告警）。

    ⚠️ **合并 ≠ 通过门禁**：`CFG-008` 明写「分段产物本身不可能单独过交付包 schema」
    （`required` 六项不齐）。合并结果的合规判定属**交付层**（`validate_pack.py`），
    此处只做**结构合并与留痕**，不越界裁决。

    ⚠️ **按形态分派（`T-100`）**：`storyboard` 的头部键与交付包**不是同一套**
    （`title`/`genre`/`style_ref`/`aspect_ratio_default` vs `meta`/`style_bible`/…），
    用 `merge_segments` 会把前者整体丢掉 ⇒ 必须走 `merge_storyboard_parts`。

    `upstream`（`ISSUE-062` 裁决 5）：storyboard 形态下传上游剧本产物，供合并侧把
    `unspecified` **继承项**的 `fill_stage` 锁回 `script`；其余形态不使用。

    `segs`（`T-118` ③）：与 `` texts `` 等长的段名清单（plan 顺序）。script 形态下
    场段产物的 `` no `` **机械回填为段号**——场号唯一真值是段名（plan 由骨架
    `` scene_nos `` 派生 ⇒ 段名即骨架声明的场）；模型在段内自由书写的 `` no ``
    与段号不一致时（段级 schema 该键无约束），合并按产物 `` no `` 装配 ⇒ 该场
    装配不进任何幕 ⇒ `` acts[ai].scenes=[] `` ⇒ 形态闸拒（b24 r8/r9 实锤
    「acts[2] 缺 scenes[]」90 s 级整轮失败）。⚠️ 不走 schema enum 钉值：vLLM
    0.10.x 对不支持的 JSON Schema 形态**静默忽略**（`ISSUE-086` 同族教训），
    机械回填是行为可验证的确定性修复。`` segs `` 缺省（None）或长度不符时
    不回填（旧行为零变化）。
    """
    parsed = [parse_json_object(text) for text in texts]
    stamp_warnings: list[str] = []
    if (
        segs is not None
        and artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "script"
        and len(segs) == len(parsed)
    ):
        for _i, (_seg, _part) in enumerate(zip(segs, parsed)):
            if not _seg.startswith("scene:") or not isinstance(_part, dict):
                continue
            if "scenes" in _part:  # 包装形态（整段多场）：不在本层裁断，原样交合并器
                continue
            _m = re.fullmatch(r"scene:(\d+)", _seg)
            if not _m:
                continue
            _no = int(_m.group(1))
            # ⚠️ 类型敏感（QA C-1，2026-11-26）：`True == 1`、`1.0 == 1` 在值相等
            # 语义下会漏掉 bool/float 错标——scene:1 专属逃逸形态（其余场号
            # `True != N` 本就会回填）。与 merge 侧 bool 排除口径对齐。
            _old = _part.get("no")
            if (
                not isinstance(_old, int)
                or isinstance(_old, bool)
                or _old != _no
            ):
                parsed[_i] = {**_part, "no": _no}
                stamp_warnings.append(
                    f"场段 {_seg} 产物 no={_part.get('no')!r} ≠ 段号——机械回填为 {_no}"
                    "（场号唯一真值是段名，`T-118` ③）"
                )
    if artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "storyboard":
        merged, warnings = merge_storyboard_parts(parsed, upstream=upstream)
    elif artifact_contract.STAGE_TO_SHAPE.get(tpl_stage) == "script":
        # `T-116`：script 逐场拆段产物 → 幕骨架装配（锚点只定义一次＋机械承继）。
        merged, warnings = merge_script_parts(parsed, synopsis=upstream)
    else:
        merged, warnings = merge_segments(parsed)
    return json.dumps(merged, ensure_ascii=False, indent=2), stamp_warnings + warnings
