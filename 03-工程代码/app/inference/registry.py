"""推理后端解析（ARCH-003 §6.1）。

按配置名解析到具体 `TextGenerator` 实例。本批注册：

- `mock` —— 离线联调（无 GPU 亦可跑通全链路）；
- **`vllm` —— `T-004` 已接入**（OpenAI 兼容 HTTP；平台前提与启动参数见
  `04-部署运维/OPS-002`）。

`local` / `remote` 保留注册位并显式抛 `NOT_IMPLEMENTED`——
**宁可显式报「未接入」，也不静默降级**（与工件纪律同源）。
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.errors import AppError, ErrorCode
from app.inference.base import TextGenerator
from app.inference.mock_backend import MockBackend
from app.inference.vllm_backend import build_from_settings

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


def _vllm_factory() -> TextGenerator:
    """运行时读配置装配（**不在导入期读配置**，便于测试覆盖 `Settings`）。"""
    from app.core.config import get_settings

    return build_from_settings(get_settings())


register("mock", MockBackend)
register("vllm", _vllm_factory)
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
