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

#: 链路四段的**形态合规样本**（`ISSUE-042` 起必需）。
#:
#: ⚠️ 为什么 mock 必须产出合规产物：形态闸（`app/services/artifact_contract.py`）
#: 生效后，「产物合不合形态」是**入库的硬前提**——一份不合形态的 mock 回包
#: 会被闸门正当地拦下，使「离链路在无 GPU 环境可跑通」这一 mock 的**存在理由**消失。
#: 即：**mock 的职责从「回一段 JSON」升级为「回一段像该阶段产物的 JSON」**。
#:
#: ⚠️ 本表**刻意不 import 契约模块**（`inference` 层不反向依赖 `services` 层）；
#: 代价是可能「悄悄偏离契约」，故由 `app/tests/test_output_schema.py` 的
#: `test_mock_samples_satisfy_artifact_contract` 做**单向断言**兜住——
#: 契约一改而本表未随改，测试会**当场失败**，不会静默漂移。
#:
#: ⚠️ `_mock` 等标记键**必须保留**：它们是「mock 产物不可能被误当作真实产物」的凭据
#: （备案举证时须排除）。形态闸只要求**必需键齐备**，不禁止额外键，故二者不冲突。
_MOCK_SAMPLES: dict[str, dict] = {
    "synopsis": {
        "title": "【mock】梗概标题",
        "logline": "【mock】一句话故事",
        "protagonist": "【mock】主角",
        "supporting": "【mock】配角",
        "world": "【mock】世界观",
        "conflict": "【mock】核心冲突",
        "scenes_outline": [],
        "ending": "【mock】结局",
        "forbidden_items": [],
        "total_est_seconds": 0,
        "unspecified": [],
    },
    "script": {
        "title": "【mock】剧本标题",
        "logline": "【mock】一句话故事",
        "genre": "【mock】题材",
        "style_bible": {},
        "characters": [],
        "props": [],
        "acts": [],
        "forbidden_items": [],
        "total_est_seconds": 0,
        "unspecified": [],
    },
    "storyboard": {
        "title": "【mock】分镜标题",
        "genre": "【mock】题材",
        "style_ref": "ST-00",
        "aspect_ratio_default": "16:9",
        "total_duration_ms": 0,
        "units": [],
        "shots": [],
        "forbidden_items": [],
        "unspecified": [],
        "quality_gate": {},
    },
    # `shot_prompt` 阶段的产物即**交付包**（形态 `pack`），顶层必需 6 段。
    "shot_prompt": {
        "schema_version": "2.1.0",
        "meta": {},
        "style_bible": {},
        "characters": [],
        "props": [],
        "units": [],
        "shots": [],
        "forbidden_items": [],
        "aigc_meta": {},
    },
}


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
        stage = hint.group(1) if hint else None
        sample = _MOCK_SAMPLES.get(stage or "")
        if sample is not None:
            # 在**形态合规**的样本上叠 mock 标记（见 `_MOCK_SAMPLES` 的两条 ⚠️）。
            return {
                **sample,
                "_mock": True,
                "_backend": self.name,
                "_prompt_digest": self._digest(prompt),
                "_stage_hint": stage,
                "_json_schema_applied": json_schema is not None,
                "_note": "本响应由 mock 后端生成，仅用于联调；不得作为生成能力或内容质量证据。",
            }
        # 链路四段之外（`modify`／`check_consistency`／通用模板等）无形态契约，
        # 保持原「元数据回包」形态。
        return {
            "_mock": True,
            "_backend": self.name,
            "_prompt_digest": self._digest(prompt),
            "_stage_hint": stage,
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
