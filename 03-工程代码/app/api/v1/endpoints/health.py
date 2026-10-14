"""健康与就绪探针（ARCH-003 §5.1）。

- `/health` 存活探针：进程在即 ok；
- `/ready`  就绪探针：检查提示词资产是否加载成功（本批无 DB / Redis）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.schemas.common import HealthStatus

router = APIRouter(tags=["运维"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthStatus, summary="存活探针")
def health() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(
        status="ok",
        app_name=settings.app_name,
        version=VERSION,
        inference_backend=settings.inference_backend,
    )


@router.get("/ready", response_model=HealthStatus, summary="就绪探针")
def ready(request: Request) -> JSONResponse:
    settings = get_settings()
    checks: dict[str, str] = {}
    ok = True
    prompts = getattr(request.app.state, "prompts", None)
    if prompts is None:
        checks["prompts"] = "missing"
        ok = False
    else:
        try:
            checks["prompts"] = f"ok ({len(prompts.list())} templates)"
        except Exception as exc:  # pragma: no cover - 资产损坏才会走到
            checks["prompts"] = f"error: {type(exc).__name__}"
            ok = False
    body = HealthStatus(
        status="ok" if ok else "degraded",
        app_name=settings.app_name,
        version=VERSION,
        inference_backend=settings.inference_backend,
        checks=checks,
    )
    code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=body.model_dump())
