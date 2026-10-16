"""应用入口：装配路由、中间件、异常处理器（ARCH-003 §3.4 `app/main.py`）。

启动顺序（**顺序即契约**）：

1. 读取配置并初始化日志；
2. 加载提示词资产（失败即启动失败，**不静默降级**）；
3. 装配服务层与依赖注入容器（`app.state`）；
4. 装配中间件与全局异常处理器（统一错误信封 SW-I06 在此落地）；
5. 挂载探针与业务路由。

运行：

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.api.v1.endpoints import health
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
)
from app.core.logging import configure_logging, get_logger, get_request_id
from app.core.middleware import RequestContextMiddleware
from app.prompts.loader import PromptRepository
from app.repositories.lexicon import load_lexicon
from app.repositories.session_repo import SessionRepository
from app.services.dialogue_service import DialogueService
from app.services.safety_service import SafetyService

logger = get_logger("main")

_DESCRIPTION = """AI 漫剧剧本与分镜提示词生成系统 · 服务端骨架（D-005 一期）。

接口编号对应《软件级需求文档》（`REQ-005`）§3 接口需求：
`SW-I01` 任务对话（本轮实现）· `SW-I02` 生成任务（本轮实现，mock 后端）·
`SW-I03` 内容安全 · `SW-I04` 产物交付 · `SW-I05` 身份认证 · `SW-I06` 统一错误信封（全接口共用）·
`SW-I08` 内容导出。

⚠️ 未接入的接口**显式返回 501**，不静默放行。
"""


def _json(status_code: int, envelope: ErrorEnvelope | dict) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(envelope))


def register_exception_handlers(app: FastAPI) -> None:
    """把全部异常收敛为**统一错误信封**（SW-I06）。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info(
            "app_error",
            extra={
                "extra_fields": {
                    "code": exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code),
                    "status": exc.status_code,
                    "path": request.url.path,
                }
            },
        )
        return _json(exc.status_code, exc.to_envelope(get_request_id()))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="请求参数校验未通过",
                details={"errors": exc.errors()},
                request_id=get_request_id(),
                retryable=False,
            )
        )
        return _json(400, envelope)

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 只记异常类型，不记堆栈（与 SW-I06「不暴露内部细节」同口径）
        logger.error(
            "unhandled_error",
            extra={"extra_fields": {"exc_type": type(exc).__name__, "path": request.url.path}},
        )
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="服务内部错误",
                request_id=get_request_id(),
                retryable=True,
            )
        )
        return _json(500, envelope)


def create_app(settings: Settings | None = None) -> FastAPI:
    """应用工厂。测试可传入自定义 `Settings` 以隔离环境。"""
    settings = settings or get_settings()
    configure_logging(logging.DEBUG if settings.debug else logging.INFO)

    app = FastAPI(
        title=settings.app_name,
        version=health.VERSION,
        description=_DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # ---- 资产与服务（启动即校验：失败不静默降级）----
    prompts = PromptRepository(settings.prompts_dir).load()
    sessions = SessionRepository()
    app.state.settings = settings
    app.state.prompts = prompts
    app.state.sessions = sessions
    # ⚠️ **双闸必须挂在生成链路上**（`T-005` 的实质，不只是提供 `/safety` 端点）：
    #    `SafetyService` 只判定，**阻断由编排层据 verdict 抛 `GUARD_*`**。
    #    接线用**同一实例**（不另造，避免两套策略）；这里用**延迟解析**是因为
    #    `safety_service` 在本行之后才装配，而解析发生在**请求期**，届时必定就绪。
    app.state.dialogue_service = DialogueService(
        sessions, prompts, safety_resolver=lambda: app.state.safety_service
    )

    # ---- 内容安全双闸（`T-005`）----
    # 词库加载**不抛异常**：缺失/为空一律降级为「检测不可用」，由 SafetyService
    # 按 fail-closed 拒绝放行——**绝不在装配阶段崩掉整个应用**，也不静默放行。
    # 受控词库**不入库**，运行时从受控区目录读取（项目方 2026-10-15 决策）；
    # 其路径**不外泄**，只以 `controlled_loaded` 布尔出现在策略视图与本条日志里。
    lexicon = load_lexicon(settings.lexicon_dir, settings.controlled_lexicon_dir)
    app.state.safety_service = SafetyService(
        lexicon,
        output_action=settings.guard_output_action,
        fail_closed=settings.guard_fail_closed,
        max_hits=settings.guard_max_hits,
        enforce=settings.guard_enforce,
        # `SW-017` 话术注入（方案 B）：留空 ⇒ 服务层回落内置默认，行为不变
        refusal_talk=settings.guard_refusal_talk or None,
        clarify_talk=settings.guard_clarify_talk or None,
    )
    logger.info(
        "app_initialized",
        extra={
            "extra_fields": {
                "templates": len(prompts.list()),
                "inference_backend": settings.inference_backend,
                "prompts_root": str(settings.prompts_dir),
                "lexicon_categories": lexicon.category_count,
                "lexicon_words": lexicon.total_words,
                "lexicon_empty_categories": len(lexicon.empty_categories),
                "lexicon_controlled_loaded": lexicon.controlled_loaded,
                "lexicon_circuit_open": not lexicon.usable,
                "guard_enforce": settings.guard_enforce,
                "guard_fail_closed": settings.guard_fail_closed,
                "guard_output_action": settings.guard_output_action,
            }
        },
    )

    # ---- 中间件与异常处理器 ----
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    # ---- 路由 ----
    app.include_router(health.router)
    app.include_router(v1_router.build_router(), prefix=settings.api_prefix)
    return app


app = create_app()
