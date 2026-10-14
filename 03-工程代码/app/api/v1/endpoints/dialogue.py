"""任务对话端点 —— **SW-I01**（承载 SW-001 / SW-002 / SW-003）。

HTTP 语义与状态机动作的对应关系（**这是本接口的契约核心**）：

| 端点 | 状态机语义 | 越界时的表现 |
| --- | --- | --- |
| `POST /sessions` | 建会话，落「待梗概」 | — |
| `POST /sessions/{id}/advance` | 沿全序推进一步（可能触发一次生成） | 下一步需确认时 → `409 CONFIRMATION_REQUIRED`（**SW-003 门控**） |
| `POST /sessions/{id}/confirm` | 执行确认动作并固化快照 | 当前阶段无需确认 → `409 INVALID_STATE_TRANSITION` |
| `POST /sessions/{id}/rollback` | 回退到**前置**阶段 | 目标非前置 → `409 ROLLBACK_TARGET_INVALID` |
| `POST /sessions/{id}/revise` | SW-002 对话式修改（**不改阶段**） | 当前阶段无可改产物 → `409` |
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import get_dialogue_service
from app.core.logging import get_request_id
from app.schemas.common import Envelope
from app.schemas.dialogue import (
    AdvanceRequest,
    ConfirmRequest,
    ReviseRequest,
    RollbackRequest,
    SessionCreateRequest,
    SessionView,
    TransitionResult,
)
from app.services.dialogue_service import DialogueService

router = APIRouter(prefix="/sessions", tags=["SW-I01 · 任务对话"])


@router.post(
    "",
    response_model=Envelope[SessionView],
    status_code=status.HTTP_201_CREATED,
    summary="创建任务会话",
)
def create_session(
    body: SessionCreateRequest,
    svc: DialogueService = Depends(get_dialogue_service),
) -> Envelope[SessionView]:
    return Envelope(request_id=get_request_id(), data=svc.create_session(body))


@router.get(
    "/{session_id}",
    response_model=Envelope[SessionView],
    summary="查询会话状态",
)
def get_session(
    session_id: str, svc: DialogueService = Depends(get_dialogue_service)
) -> Envelope[SessionView]:
    return Envelope(request_id=get_request_id(), data=svc.get(session_id))


@router.post(
    "/{session_id}/advance",
    response_model=Envelope[TransitionResult],
    summary="推进到下一阶段",
)
async def advance(
    session_id: str,
    body: AdvanceRequest | None = None,
    svc: DialogueService = Depends(get_dialogue_service),
) -> Envelope[TransitionResult]:
    variables = body.variables if body else {}
    result = await svc.advance(session_id, variables)
    return Envelope(request_id=get_request_id(), data=result)


@router.post(
    "/{session_id}/confirm",
    response_model=Envelope[TransitionResult],
    summary="确认门控（SW-003）",
)
def confirm(
    session_id: str,
    body: ConfirmRequest | None = None,
    svc: DialogueService = Depends(get_dialogue_service),
) -> Envelope[TransitionResult]:
    result = svc.confirm(session_id, body)
    return Envelope(request_id=get_request_id(), data=result)


@router.post(
    "/{session_id}/rollback",
    response_model=Envelope[TransitionResult],
    summary="回退到前置阶段",
)
def rollback(
    session_id: str,
    body: RollbackRequest,
    svc: DialogueService = Depends(get_dialogue_service),
) -> Envelope[TransitionResult]:
    result = svc.rollback(session_id, body)
    return Envelope(request_id=get_request_id(), data=result)


@router.post(
    "/{session_id}/revise",
    response_model=Envelope[TransitionResult],
    summary="对话式修改（SW-002）",
)
async def revise(
    session_id: str,
    body: ReviseRequest,
    svc: DialogueService = Depends(get_dialogue_service),
) -> Envelope[TransitionResult]:
    result = await svc.revise(session_id, body)
    return Envelope(request_id=get_request_id(), data=result)
