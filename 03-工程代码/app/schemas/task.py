"""生成任务契约（SW-I02 承载 SW-004~SW-008）。

响应体结构对齐《模型框架设计说明书》ARCH-003 §5.2「统一信封」——
`provenance` 是**隐式生成标识**载体，**不可省略**（SW-012）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SamplingParams(BaseModel):
    """采样参数。区间约束在契约层声明（不在业务代码里手工 if）。"""

    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    top_k: int = Field(default=50, ge=0)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    repetition_penalty: float = Field(default=1.05, gt=0)
    stop: list[str] = Field(default_factory=list)


class GenerationRequest(BaseModel):
    """生成请求：按模板或按链路阶段二选一。

    `stage` 取 **链路阶段名**（`synopsis` / `script` / `storyboard` / `shot_prompt` / `revise`），
    与 `prompts/CFG-008_manifest.yaml` 的 `stage` 字段一一对应——
    ⚠️ 不要与会话阶段（`draft_script` 等，见 `schemas.dialogue.Stage`）混淆。
    """

    template_id: str | None = Field(default=None, description="提示词模板 id（如 script_v1）")
    stage: str | None = Field(default=None, description="链路阶段名，用于自动解析模板")
    variables: dict[str, Any] = Field(default_factory=dict, description="模板变量取值")
    model: str | None = Field(default=None, description="推理后端名，缺省用配置默认")
    params: SamplingParams | None = Field(default=None, description="采样参数，缺省取模板默认")


class GenerationOutput(BaseModel):
    text: str
    format: str = "text"
    finish_reason: str = "stop"
    citations: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelInfo(BaseModel):
    name: str
    version: str = ""
    adapter: str | None = None


class SafetyDecision(BaseModel):
    """内容安全判定结果（SW-009/010 双闸；本批为桩，恒 pass）。"""

    input_decision: str = "pass"
    output_decision: str = "pass"
    labels: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """隐式生成标识载体（SW-012）。取值一律由服务层注入，不得在生成层自拟。"""

    ai_generated: bool = True
    provider_code: str = ""
    content_id: str = ""


class LatencyBreakdown(BaseModel):
    queue: int = 0
    prefill: int = 0
    decode: int = 0
    total: int = 0


class GenerationResponse(BaseModel):
    request_id: str
    task_id: str | None = None
    status: str = "succeeded"
    output: GenerationOutput
    usage: Usage = Field(default_factory=Usage)
    model: ModelInfo
    safety: SafetyDecision = Field(default_factory=SafetyDecision)
    provenance: Provenance = Field(default_factory=Provenance)
    cache_hit: bool = False
    latency_ms: LatencyBreakdown = Field(default_factory=LatencyBreakdown)


class TemplateInfo(BaseModel):
    """模板清单条目（供 `/templates` 查询）。"""

    id: str
    name: str
    version: str
    task_type: str
    stage: str | None = None
    file: str
    status: str = "active"
