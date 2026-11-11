"""生成任务端点 —— **SW-I02**（承载 SW-004~SW-008）。

本批（T-003 一期）由 **mock 后端**执行生成：响应结构与真实后端**完全一致**，
故 T-004 接入 vLLM 时，本文件的契约与代码均无需改动。
响应体中的 `provenance` 即**隐式生成标识**载体（SW-012），不可省略。

⚠️ **ISSUE-078 收口（2026-11-11，方案 A＋B3）**：本端点曾把调用方 `variables`
直接渲染进推理后端、**任何安全闸都不经过**——与对话链路形成防护落差
（`revise_v1` 的客户素材原文 `source_material` 仅经此端点可达，等于给注入开直通车）。
现补齐**端点级双闸**：输入侧对全部字符串实值跑 `SW-009` 词闸＋`SW-011` 注入检测，
输出侧对生成文本跑 `SW-010` 复检；`SafetyDecision()` 空桩改为真实判定；
`provenance.content_id` 由服务层编号注入（不再恒空）。
方案 B3 定位注记：本端点为**直连生成面**（响应头 `X-Debug-Surface: true`），
其产物**不得进入交付链路**（交付只接受对话链路产物），定位已登记 `PM-001`。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_prompts, get_safety_service
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_request_id
from app.inference.base import GenParams
from app.inference.registry import available, get_backend
from app.prompts.loader import STAGE_TEMPLATE, PromptRepository, Template
from app.schemas.common import Envelope
from app.schemas.task import (
    GenerationOutput,
    GenerationRequest,
    GenerationResponse,
    LatencyBreakdown,
    ModelInfo,
    Provenance,
    SafetyDecision,
    TemplateInfo,
    Usage,
)
from app.services.safety_service import SafetyService

router = APIRouter(tags=["SW-I02 · 生成任务"])


def _resolve_template(prompts: PromptRepository, body: GenerationRequest) -> Template:
    if body.template_id:
        return prompts.get(body.template_id)
    if body.stage:
        return prompts.by_stage(body.stage)
    raise AppError(
        ErrorCode.VALIDATION_ERROR,
        "须提供 template_id 或 stage 之一",
        details={"stages": sorted(STAGE_TEMPLATE)},
    )


def _params(body: GenerationRequest, tpl: Template) -> GenParams:
    if body.params is not None:
        data = body.params.model_dump()
        return GenParams(
            temperature=data["temperature"],
            top_p=data["top_p"],
            top_k=data["top_k"],
            max_tokens=data["max_tokens"],
            repetition_penalty=data["repetition_penalty"],
            stop=tuple(data.get("stop") or ()),
        )
    allowed = {"temperature", "top_p", "top_k", "max_tokens", "repetition_penalty"}
    kwargs = {k: tpl.sampling[k] for k in allowed if k in tpl.sampling}
    return GenParams(**kwargs)


def _iter_client_strings(variables: dict[str, Any]) -> list[tuple[str, str]]:
    """取调用方 `variables` 中全部字符串实值（含列表拼接），作为待检文本。

    ⚠️ 与对话链路 `_client_texts` 的**白名单字段**口径不同：本端点变量键由
    模板任意定义，故按**全键扫描**——漏扫一个键就等于给注入留一个旁路。
    """
    out: list[tuple[str, str]] = []
    for name, value in variables.items():
        if isinstance(value, str):
            if value.strip():
                out.append((name, value))
        elif isinstance(value, (list, tuple)):
            joined = "；".join(str(v) for v in value if str(v).strip())
            if joined:
                out.append((name, joined))
    return out


def _guard_inputs(
    safety: SafetyService, variables: dict[str, Any]
) -> tuple[str, list[str]]:
    """输入侧双检测（`SW-009` 词闸 ＋ `SW-011` 注入）。

    ⚠️ 分层纪律与对话链路一致：**服务层只判定、端点才阻断**。
    `enforce=false`（受控旁路）时**照样检测、照样进 labels**，仅不抛错。
    返回 `(input_decision, labels)`；labels 只含分类码/模式名，**不落命中词明文**。
    """
    decision = "pass"
    labels: list[str] = []
    for field, text in _iter_client_strings(variables):
        verdict = safety.inspect_input(text)
        injection = safety.check_injection(text)
        labels.extend(h.category_id for h in verdict.hits)
        if injection.blocked:
            labels.extend(injection.patterns)
        blocked = injection.blocked or not verdict.passed
        if blocked:
            decision = "block"
            if safety.enforce:
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
    return decision, labels


def _guard_output_text(
    safety: SafetyService, text: str
) -> tuple[str, list[str]]:
    """输出侧复检（`SW-010`）。返回 `(output_decision, labels)`。

    模型侧拒答话术走独立通道（`ISSUE-070` 同款口径）：先判 `looks_like_refusal`
    再复检，防「说明理由会复述敏感词」被输出词闸误拦。
    """
    verdict = safety.inspect_output(text, is_refusal=safety.looks_like_refusal(text))
    labels = [h.category_id for h in verdict.hits]
    if not verdict.passed and safety.enforce:
        raise AppError(
            ErrorCode.GUARD_OUTPUT_BLOCKED,
            verdict.message,
            details={
                "action": verdict.action,
                "hit_categories": labels,
                "degraded_reason": verdict.degraded_reason,
                "refusal_talk": verdict.refusal_talk or safety.refusal_talk(),
            },
        )
    return verdict.action, labels


@router.post(
    "/generations",
    response_model=GenerationResponse,
    summary="执行一次生成（按模板或按链路阶段）",
)
async def create_generation(
    body: GenerationRequest,
    response: Response,
    prompts: PromptRepository = Depends(get_prompts),
    safety: SafetyService = Depends(get_safety_service),
) -> GenerationResponse:
    # ⚠️ B3 定位注记（ISSUE-078）：直连生成面审计标记——本端点产物**不得进入
    #    交付链路**（交付只接受对话链路产物），网关与审计凭此头区分。
    response.headers["X-Debug-Surface"] = "true"

    tpl = _resolve_template(prompts, body)
    input_decision, input_labels = _guard_inputs(safety, body.variables)
    rendered = prompts.render(tpl, body.variables)
    backend = get_backend(body.model)
    params = _params(body, tpl)

    started = time.perf_counter()
    result = await backend.generate(rendered.as_text(), params)
    elapsed = int((time.perf_counter() - started) * 1000)

    output_decision, output_labels = _guard_output_text(safety, result.text)

    return GenerationResponse(
        request_id=get_request_id(),
        task_id=None,
        status="succeeded",
        output=GenerationOutput(text=result.text, finish_reason=result.finish_reason),
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        model=ModelInfo(name=backend.name, version=backend.version, adapter=None),
        safety=SafetyDecision(
            input_decision=input_decision,
            output_decision=output_decision,
            labels=sorted(set(input_labels) | set(output_labels)),
        ),
        # ⚠️ `content_id` 由服务层编号注入（R30 同源纪律：编号不可由模型/调用方自拟）；
        #    本端点无交付包，取请求级服务层编号。
        provenance=Provenance(
            ai_generated=True, provider_code="", content_id=get_request_id()
        ),
        cache_hit=False,
        latency_ms=LatencyBreakdown(total=elapsed),
    )


@router.get(
    "/templates",
    response_model=Envelope[list[TemplateInfo]],
    summary="可用提示词模板清单",
)
def list_templates(
    status: str | None = None,
    task_type: str | None = None,
    prompts: PromptRepository = Depends(get_prompts),
) -> Envelope[list[TemplateInfo]]:
    items = [
        TemplateInfo(
            id=t.id,
            name=t.name,
            version=t.version,
            task_type=t.task_type,
            stage=t.stage,
            file=t.file,
            status=t.status,
        )
        for t in prompts.list(status=status, task_type=task_type)
    ]
    return Envelope(request_id=get_request_id(), data=items)


@router.get(
    "/backends",
    response_model=Envelope[list[str]],
    summary="已注册的推理后端",
)
def list_backends() -> Envelope[list[str]]:
    return Envelope(request_id=get_request_id(), data=available())
