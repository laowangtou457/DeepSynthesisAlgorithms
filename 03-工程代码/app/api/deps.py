"""依赖注入：从 `app.state` 取出服务层实例。

使端点只依赖抽象、不自行构造资源（便于测试替换仓储与推理后端）。
"""

from __future__ import annotations

from fastapi import Request

from app.prompts.loader import PromptRepository
from app.services.dialogue_service import DialogueService


def get_dialogue_service(request: Request) -> DialogueService:
    return request.app.state.dialogue_service


def get_prompts(request: Request) -> PromptRepository:
    return request.app.state.prompts
