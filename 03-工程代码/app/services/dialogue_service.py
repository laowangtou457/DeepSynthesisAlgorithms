"""任务对话编排服务（SW-001 状态机 · SW-002 对话式修改 · SW-003 确认门控）。

服务层纪律（ARCH-003 §3.1）：**不引用 Request/Response**，可直接单测。
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import digest, get_logger
from app.inference.base import GenParams
from app.inference.registry import get_backend
from app.prompts.loader import PromptRepository, Template
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.services.output_schema import (
    engine_schema_source,
    load_engine_schema,
    stripped_paths,
)
from app.services.pack_meta import apply_service_truth, build_pack_meta
from app.services import artifact_contract, content_adequacy, quality_gate
from app.services.segment import (
    is_multi_part,
    merge_segments,
    parse_json_object,
    plan_segments,
    shot_count_of,
    unit_ids_of,
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

        verdict = safety.inspect_output(text)
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

        value = merged.get("segment") or template.default_of("segment") or "auto"
        shot_count, unit_ids = 0, []
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
        return plan_segments(value, shot_count=shot_count, unit_ids=unit_ids)

    async def _run_segments(
        self,
        template: Template,
        tpl_stage: str,
        merged: dict[str, Any],
        segs: list[str],
        supports_segment: bool,
        json_schema: dict[str, Any] | None,
        backend: Any,
    ) -> tuple[dict[str, str], list[dict[str, Any]], int, int, list[str]]:
        """按 `segs` 逐段调用引擎，返回 `(段→文本, 本批留痕, prompt_tokens, completion_tokens, 截断段)`。

        ⚠️ 抽出来是为 `T-086` 的**按段重试**服务：重试时只传「失败的段」，
        未失败的段**沿用上一轮的采样结果**（各自独立，互不牵连）。
        ⚠️ **本方法只做调用与留痕，不改写、不润色模型输出。**
        """
        produced: dict[str, str] = {}
        trace: list[dict[str, Any]] = []
        prompt_tokens = completion_tokens = 0
        for seg in segs:
            seg_vars = dict(merged)
            if supports_segment:
                seg_vars["segment"] = seg
            rendered = self.prompts.render(template, seg_vars)
            result = await backend.generate(
                f"[stage:{tpl_stage}]\n{rendered.as_text()}",
                _params_of(template.sampling),
                json_schema,
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
                }
            )
        truncated = [t["segment"] for t in trace if t.get("finish_reason") == "length"]
        return produced, trace, prompt_tokens, completion_tokens, truncated

    def _retry_segments(
        self, plan: list[str], verdict: Any, texts: dict[str, str]
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
        picked: list[str] = []
        for seg in plan:
            if seg.startswith("unit:"):
                uid = seg.split(":", 1)[1]
                if uid and uid in joined:
                    picked.append(seg)
        if any(k in joined for k in ("meta.", "total_duration_ms", "package_head", "package")):
            if "package_head" in plan:
                picked.append("package_head")
        for seg in plan:
            text = texts.get(seg, "")
            try:
                doc = parse_json_object(text)
            except AppError:
                picked.append(seg)  # 解析失败 ⇒ 必须重跑
                continue
            if isinstance(doc, dict) and not any(doc.get(k) for k in (set(HEAD_KEYS) | {"units", "shots"})):
                picked.append(seg)  # 零贡献 ⇒ 必须重跑
        uniq = [s for s in plan if s in set(picked)]
        if not uniq:
            return list(plan), "scope_fallback"
        return uniq, None

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
            model={"name": backend.name, "backend": backend.name, "revision": backend.version},
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
        retry_segs: list[str] = list(plan)
        retry_scope_note: str | None = None
        gate_verdicts: list[dict[str, Any]] = []
        quality_verdict: Any = None

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

        #: 上一轮「结构合法」的状态快照 —— 供「**重试把产物弄坏**」时回退（改造不得变差）。
        last_ok_state: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            segs = list(plan) if attempt == 1 else list(retry_segs)
            trace_len_before = len(trace)
            try:
                produced, seg_trace, pt, ct, _truncated_now = await self._run_segments(
                    template, tpl_stage, merged, segs, supports_segment, json_schema, backend
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
                truncated_segments = self._guard_not_truncated(tpl_stage, seg_trace)

                ordered = [texts_by_seg[s] for s in plan if s in texts_by_seg]
                if is_multi_part(plan):
                    segment_contributions = self._guard_segment_contributions(
                        tpl_stage, plan, ordered
                    )
                    final_text, warnings = _merge_parts(ordered)
                else:
                    final_text, warnings = ordered[0], []

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

                # ---- `ISSUE-042` 生成后形态闸（**单段与多段收敛到同一条路径**）----
                # 改造前：多段会经 `_merge_parts` → `parse_json_object`（但那是「合并的必要步骤」），
                # 单段则 `final_text = texts[0]` **完全不解析** ⇒ 产物是否被检查**取决于 `segment` 取值**。
                # 现统一收口：无论单段多段，最终产物都必须过形态闸。
                artifact_verdict = self._guard_artifact_shape(tpl_stage, final_text)
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
                final_text, meta_overrides = self._apply_service_truth(
                    tpl_stage, text_penultimate, rec, backend, guard_input, guard_output
                )
                retry_scope_note = "retry_degraded_fallback"
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
                "truncated_segments": list(truncated_segments),
            }

            # ---- 门禁判定（`T-086`）----
            if not gate_applies:
                break
            quality_verdict = await quality_gate.check(
                tpl_stage, text=final_text, upstream=gate_upstream
            )
            gate_verdicts.append({"attempt": attempt, **quality_verdict.as_record()})
            if quality_verdict.ok is True:
                break
            # ⚠️ 「不值得重试」与「没有额度了」是**两种**停止理由，须分别留痕：
            #    前者＝本次失败里没有模型可影响的项（如合规资产未接入），
            #    重试改了也白改 —— 若混成一句「重试用尽」，会误导成「模型不行」。
            if not quality_gate.should_retry(quality_verdict):
                retry_scope_note = "no_retryable_failure"
                break
            if attempt >= max_attempts:
                break
            retry_segs, retry_scope_note = self._retry_segments(plan, quality_verdict, texts_by_seg)
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
                    f"「{tpl_stage}」段产物用尽 {max_attempts} 次尝试仍未通过质量门禁"
                    f"（形态：{quality_verdict.shape}；可重试失败 {len(quality_verdict.retryable)} 项、"
                    f"重试无用 {len(quality_verdict.non_retryable)} 项）",
                    details={
                        "reason": "quality_gate_not_passed",
                        "stage": tpl_stage,
                        "attempts": max_attempts,
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
                    "quality_gate_max_attempts": max_attempts,
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
                "max_attempts": max_attempts,
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
        if meta_overrides:
            # 覆盖清单（含未变更项）一并留痕：可核查「覆盖**看过**哪些字段」，
            # 与「覆盖**改过**哪些字段」是两件事（同 `checked`/`ok` 分列的纪律）。
            artifact["service_truth"] = meta_overrides
            artifact["service_truth_text_changed"] = final_text != text_penultimate
        if upstream_admission:
            artifact["upstream_admission"] = upstream_admission
        if compact_trace:
            # `ISSUE-044` 起**只在适用阶段**出现（默认仅 `shot_prompt`）；
            # 与日志同源的留痕，供离线审计核查「这一段到底紧凑了没有」。
            artifact["upstream_compaction"] = compact_trace
        if warnings:
            artifact["merge_warnings"] = warnings
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


def _merge_parts(texts: list[str]) -> tuple[str, list[str]]:
    """多段产物 → 合并后的完整包文本（＋合并告警）。

    ⚠️ **合并 ≠ 通过门禁**：`CFG-008` 明写「分段产物本身不可能单独过交付包 schema」
    （`required` 六项不齐）。合并结果的合规判定属**交付层**（`validate_pack.py`），
    此处只做**结构合并与留痕**，不越界裁决。
    """
    parsed = [parse_json_object(text) for text in texts]
    merged, warnings = merge_segments(parsed)
    return json.dumps(merged, ensure_ascii=False, indent=2), warnings
