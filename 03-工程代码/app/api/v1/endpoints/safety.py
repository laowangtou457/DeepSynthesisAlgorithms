"""内容安全端点 —— **SW-I03**（承载 `SW-009` / `SW-010` / `SW-011` / `SW-017`）。

**状态：已由任务 `T-005` 从契约占位改为实现**（此前显式 501）。

⚠️ 端点纪律（`SW-104`）：**只做参数校验与结果封装，不含任何判定逻辑**——
判定全部在 `app/services/safety_service.py`。⚠️ 本接口**不阻断**：返回
verdict 由调用方（编排层／客户端）决定处置；「阻断」发生在生成链路上。

⚠️ **「通过」的充分条件**是 `passed=true` **且** `degraded=false`；
`degraded=true` 时结论仅供记录，**不得据以放行**。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_safety_service
from app.core.logging import get_request_id
from app.schemas.common import Envelope
from app.schemas.safety import (
    InjectionRequest,
    InjectionVerdict,
    InspectRequest,
    InspectVerdict,
    PolicyView,
)
from app.services.safety_service import SafetyService

router = APIRouter(prefix="/safety", tags=["SW-I03 · 内容安全"])


@router.post("/inspect", response_model=Envelope[InspectVerdict], summary="输入／输出内容检测")
def inspect(
    body: InspectRequest,
    svc: SafetyService = Depends(get_safety_service),
) -> Envelope[InspectVerdict]:
    """`SW-009`（`channel=input`）／`SW-010`（`channel=output`）。"""
    return Envelope(request_id=get_request_id(), data=svc.inspect(body))


@router.post(
    "/injection",
    response_model=Envelope[InjectionVerdict],
    summary="提示注入检测（SW-011）",
)
def injection(
    body: InjectionRequest,
    svc: SafetyService = Depends(get_safety_service),
) -> Envelope[InjectionVerdict]:
    return Envelope(
        request_id=get_request_id(),
        data=svc.check_injection(body.text, body.context_fields),
    )


@router.get(
    "/policy",
    response_model=Envelope[PolicyView],
    summary="安全策略与检测能力现状",
)
def policy(
    svc: SafetyService = Depends(get_safety_service),
) -> Envelope[PolicyView]:
    """检测能力现状（词库规模、空类别、熔断状态）。

    ⚠️ 本视图**不参与放行决策**，供监督与举证查阅；
    空类别＝**覆盖不完整**，不等于「无风险」。
    """
    return Envelope(request_id=get_request_id(), data=svc.policy())