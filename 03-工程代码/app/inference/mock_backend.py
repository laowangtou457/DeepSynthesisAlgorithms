"""离线 mock 推理后端。

用途：让**全链路在无 GPU 环境可跑通**（T-003 一期验收与 CI）。

纪律：
- **确定性**——同一 prompt 必得同一输出（以摘要为种子），便于测试断言与复现；
- 不调用任何外部服务、不读任何凭证；
- 返回结构带 `_mock` 标记，使 mock 产物**不可能被误当作真实产物**（备案举证时须排除）。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from app.inference.base import GenParams, GenResult, TextGenerator

#: 从渲染后的 prompt 中粗取「阶段」标记，让 mock 回包可读。
_STAGE_HINT = re.compile(r"\[stage:([a-z_]+)\]")


class MockBackend(TextGenerator):
    """确定性 mock 后端。"""

    name = "mock"
    version = "0.1.0"
    context_window = 32768
    max_output_tokens = 4096

    def __init__(self, *, delay_ms: int = 0) -> None:
        self.delay_ms = delay_ms

    # ---- 内部 ----
    @staticmethod
    def _digest(text: str) -> str:
        from app.core.logging import digest

        return digest(text, 12)

    def _payload(self, prompt: str, json_schema: dict | None) -> dict:
        hint = _STAGE_HINT.search(prompt)
        return {
            "_mock": True,
            "_backend": self.name,
            "_prompt_digest": self._digest(prompt),
            "_stage_hint": hint.group(1) if hint else None,
            "_json_schema_applied": json_schema is not None,
            "_note": "本响应由 mock 后端生成，仅用于联调；不得作为生成能力或内容质量证据。",
        }

    # ---- 契约实现 ----
    async def generate(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> GenResult:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        text = json.dumps(self._payload(prompt, json_schema), ensure_ascii=False)
        # 用量按字符数粗估（mock 口径，不得用于容量测算）
        prompt_tokens = max(1, len(prompt) // 2)
        completion_tokens = max(1, len(text) // 2)
        return GenResult(
            text=text,
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            meta={"backend": self.name, "deterministic": True},
        )

    async def stream(
        self, prompt: str, params: GenParams, json_schema: dict | None = None
    ) -> AsyncIterator[str]:  # type: ignore[override]
        text = json.dumps(self._payload(prompt, json_schema), ensure_ascii=False)
        for i in range(0, len(text), 32):
            yield text[i : i + 32]
