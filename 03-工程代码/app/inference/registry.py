"""推理后端解析（ARCH-003 §6.1）。

按配置名解析到具体 `TextGenerator` 实例。本批只注册 `mock`；
`vllm` / `local` / `remote` 保留注册位并显式抛 `NOT_IMPLEMENTED`——
**宁可显式报「未接入」，也不静默降级**（与工件纪律同源）。
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.errors import AppError, ErrorCode
from app.inference.base import TextGenerator
from app.inference.mock_backend import MockBackend

_FACTORIES: dict[str, Callable[[], TextGenerator]] = {}


def register(name: str, factory: Callable[[], TextGenerator]) -> None:
    _FACTORIES[name] = factory


def _unavailable(name: str) -> Callable[[], TextGenerator]:
    def factory() -> TextGenerator:  # pragma: no cover - 仅在误配时触发
        raise AppError(
            ErrorCode.NOT_IMPLEMENTED,
            f"推理后端「{name}」尚未接入（接入见任务清单 T-012 / T-004）",
            details={"available": available()},
        )

    return factory


register("mock", MockBackend)
register("vllm", _unavailable("vllm"))
register("local", _unavailable("local"))
register("remote", _unavailable("remote"))


def available() -> list[str]:
    return sorted(_FACTORIES)


def get_backend(name: str | None = None) -> TextGenerator:
    """按名取后端实例；缺省读配置 `APP_INFERENCE_BACKEND`。"""
    if name is None:
        from app.core.config import get_settings

        name = get_settings().inference_backend
    factory = _FACTORIES.get(name)
    if factory is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"未知的推理后端「{name}」",
            details={"available": available()},
        )
    return factory()
