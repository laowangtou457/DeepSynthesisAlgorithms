"""生成任务端点 —— **SW-I02**（承载 SW-004~SW-008）。

本批（T-003 一期）由 **mock 后端**执行生成：响应结构与真实后端**完全一致**，
故 T-004 接入 vLLM 时，本文件的契约与代码均无需改动。
响应体中的 `provenance` 即**隐式生成标识**载体（SW-012），不可省略。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.deps import get_prompts
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


@router.post(
    "/generations",
    response_model=GenerationResponse,
    summary="执行一次生成（按模板或按链路阶段）",
)
async def create_generation(
    body: GenerationRequest,
    prompts: PromptRepository = Depends(get_prompts),
) -> GenerationResponse:
    tpl = _resolve_template(prompts, body)
    rendered = prompts.render(tpl, body.variables)
    backend = get_backend(body.model)
    params = _params(body, tpl)

    started = time.perf_counter()
    result = await backend.generate(rendered.as_text(), params)
    elapsed = int((time.perf_counter() - started) * 1000)

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
        safety=SafetyDecision(),
        provenance=Provenance(ai_generated=True, provider_code="", content_id=""),
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
