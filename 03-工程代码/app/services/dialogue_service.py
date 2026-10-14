"""任务对话编排服务（SW-001 状态机 · SW-002 对话式修改 · SW-003 确认门控）。

服务层纪律（ARCH-003 §3.1）：**不引用 Request/Response**，可直接单测。
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.inference.base import GenParams
from app.inference.registry import get_backend
from app.prompts.loader import PromptRepository
from app.repositories.session_repo import SessionRecord, SessionRepository
from app.services.pack_meta import build_pack_meta
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


class DialogueService:
    """会话编排服务。"""

    def __init__(
        self,
        repo: SessionRepository,
        prompts: PromptRepository,
        backend_resolver=get_backend,
    ) -> None:
        self.repo = repo
        self.prompts = prompts
        self._resolve_backend = backend_resolver

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
        template = self.prompts.get("modify_v1")
        variables: dict[str, Any] = {
            "target_stage": target_stage.value,
            "current_artifact": rec.artifacts.get(key, {}),
            "modification_request": req.modification_request,
        }
        rendered = self.prompts.render(template, variables)
        backend = self._resolve_backend()
        result = await backend.generate(
            f"[stage:modify]\n{rendered.as_text()}", _params_of(template.sampling)
        )
        rec.artifacts[key] = {
            "template_id": template.id,
            "template_version": template.version,
            "revision_request": req.modification_request,
            "models": [{"name": backend.name, "version": backend.version, "adapter": None}],
            "text": result.text,
        }
        rec.history.append(f"revise({target_stage.value}) → {key}")
        self.repo.save(rec)
        return self._result(rec, "revise", target_stage, target_stage)

    # ------------------------------------------------------------------ 内部
    async def _maybe_generate(
        self, rec: SessionRecord, target: Stage, variables: dict[str, Any]
    ) -> None:
        spec = _GENERATE_ON.get(target)
        if spec is None:  # 终态或无需生成
            return
        key, tpl_stage = spec
        template = self.prompts.by_stage(tpl_stage)
        backend = self._resolve_backend()
        merged = dict(variables)
        for var, upstream_key in _UPSTREAM_VARS.get(tpl_stage, {}).items():
            upstream = rec.artifacts.get(upstream_key)
            if upstream is None:
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"生成「{template.name}」缺少上游产物：{upstream_key}",
                    details={"template_id": template.id, "missing_artifact": upstream_key},
                )
            merged.setdefault(var, _artifact_text(upstream))
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
        rendered = self.prompts.render(template, merged)
        result = await backend.generate(
            f"[stage:{tpl_stage}]\n{rendered.as_text()}", _params_of(template.sampling)
        )
        rec.artifacts[key] = {
            "template_id": template.id,
            "template_version": template.version,
            "backend": backend.name,
            "text": result.text,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.prompt_tokens + result.completion_tokens,
            },
        }

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
