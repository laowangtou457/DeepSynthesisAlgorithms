"""文本合成后端统一契约（ARCH-003 §6.1「可替换是架构底线」）。

控制器与服务层**只依赖本接口**；具体引擎（vLLM / transformers / 远端 API / mock）
通过 `app.inference.registry` 解析，切换只改配置 `APP_INFERENCE_BACKEND`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenParams:
    """采样参数（对应 ARCH-003 §6.1 `GenParams`）。"""

    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    max_tokens: int = 1024
    repetition_penalty: float = 1.05
    stop: tuple[str, ...] = ()


@dataclass
class GenResult:
    """一次生成的结果与用量。"""

    text: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    meta: dict = field(default_factory=dict)


class TextGenerator(ABC):
    """文本合成后端统一契约。"""

    name: str = "base"
    version: str = ""
    context_window: int = 32768
    max_output_tokens: int = 4096

    @abstractmethod
    async def generate(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> GenResult:
        """单次生成（同步语义，内部可为异步 IO）。"""

    @abstractmethod
    def stream(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> AsyncIterator[str]:
        """流式生成（SSE 用，ARCH-003 §5.4）。

        注意：抽象方法体内不得出现 `yield`（那会使它变成异步生成器而无法被覆写），
        故本方法在子类中以异步生成器实现。
        """
        raise NotImplementedError
