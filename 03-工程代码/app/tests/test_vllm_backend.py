"""vLLM 后端适配器测试（消息形态、受约束解码、错误映射、SSE）。

全程使用 `httpx.MockTransport` **免网测试**——不起真实服务也能验证
「发出去的请求长什么样」与「收回来的东西怎么归一化」。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import AppError, ErrorCode
from app.inference.base import GenParams
from app.inference.vllm_backend import (
    VllmBackend,
    build_from_settings,
    split_sections,
    to_messages,
)

PROMPT = "[stage:shot_prompt]\n<system>\nSYS\n\n<task>\nTASK\n\n<output>\nOUT"


def _ok_body(text: str = "{}", model: str = "Qwen2.5-7B-Instruct") -> dict:
    return {
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def _backend(handler, **kwargs) -> VllmBackend:
    return VllmBackend(
        base_url="http://vllm.test/v1",
        model="Qwen2.5-7B-Instruct",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _capture(seen: dict, body: dict | None = None, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(status, json=body or _ok_body())

    return handler


# --------------------------------------------------------------- 消息形态
def test_split_sections_restores_five_sections() -> None:
    text = "<system>\nA\n\n<task>\nB\n\n<context>\nC\n\n<output>\nD\n\n<examples>\nE"
    assert split_sections(text) == {
        "system": "A",
        "task": "B",
        "context": "C",
        "output": "D",
        "examples": "E",
    }


def test_to_messages_lifts_system_and_keeps_stage_line() -> None:
    messages = to_messages(PROMPT)
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[1]["role"] == "user"
    # 阶段标记是留痕，不丢弃
    assert "[stage:shot_prompt]" in messages[1]["content"]
    assert "<task>\nTASK" in messages[1]["content"]
    assert "SYS" not in messages[1]["content"]  # system 不重复进 user


def test_to_messages_without_sections_falls_back_to_single_user() -> None:
    assert to_messages("裸文本，无节结构") == [
        {"role": "user", "content": "裸文本，无节结构"}
    ]


# --------------------------------------------------------------- 请求装配
def test_generate_request_shape_and_constrained_decoding() -> None:
    seen: dict = {}
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    backend = _backend(_capture(seen, _ok_body('{"ok": true}')))

    result = asyncio.run(
        backend.generate(
            PROMPT, GenParams(temperature=0.5, max_tokens=2048, top_k=40), schema
        )
    )

    assert seen["url"].endswith("/chat/completions")
    body = seen["body"]
    assert body["model"] == "Qwen2.5-7B-Instruct"
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 2048
    assert body["top_k"] == 40
    assert body["repetition_penalty"] == pytest.approx(1.05)
    # 默认形态 = structured_outputs（vLLM >= 0.12.0）
    assert body["structured_outputs"] == {"json": schema}  # 受约束解码已下发
    assert "guided_json" not in body  # 旧字段不得混发（新版会被静默忽略）
    assert body["messages"][0]["role"] == "system"
    assert "stream" not in body

    assert result.text == '{"ok": true}'
    assert result.finish_reason == "stop"
    assert (result.prompt_tokens, result.completion_tokens) == (11, 7)
    assert result.meta["json_schema_applied"] is True


def test_no_schema_means_no_constrained_params() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen))
    asyncio.run(backend.generate(PROMPT, GenParams()))
    assert "structured_outputs" not in seen["body"]
    assert "guided_json" not in seen["body"]
    assert "response_format" not in seen["body"]


def test_guided_decoding_mode_legacy_guided_json_is_opt_in_only() -> None:
    """旧引擎（< 0.12.0）仍可用 `guided_json`，但**必须显式声明**，不作默认。

    回归意义：若有人把默认改回 `guided_json`，本用例仍过——故另由
    `test_default_mode_is_structured_outputs` 锁住默认值。
    """
    seen: dict = {}
    backend = _backend(_capture(seen), guided_decoding_mode="guided_json")
    asyncio.run(backend.generate(PROMPT, GenParams(), {"type": "object"}))
    assert seen["body"]["guided_json"] == {"type": "object"}
    assert "structured_outputs" not in seen["body"]


def test_default_mode_is_structured_outputs() -> None:
    """锁住默认形态：v0.12.0 已移除 `guided_json`，默认值不得回退。"""
    assert _backend(_capture({})).guided_decoding_mode == "structured_outputs"


def test_guided_decoding_mode_response_format() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen), guided_decoding_mode="response_format")
    asyncio.run(backend.generate(PROMPT, GenParams(), {"type": "object"}))
    assert "guided_json" not in seen["body"]
    assert "structured_outputs" not in seen["body"]
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_guided_decoding_mode_off_sends_neither() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen), guided_decoding_mode="off")
    asyncio.run(backend.generate(PROMPT, GenParams(), {"type": "object"}))
    assert "guided_json" not in seen["body"]
    assert "structured_outputs" not in seen["body"]
    assert "response_format" not in seen["body"]


def test_unknown_guided_decoding_mode_fails_loudly() -> None:
    """未知形态必须**显式报错**，绝不「当作没约束」静默继续（纪律：宁可报错不降级）。"""
    backend = _backend(_capture({}), guided_decoding_mode="typo_mode")
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams(), {"type": "object"}))
    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert "typo_mode" in str(ei.value)


def test_stop_sequences_are_forwarded_as_list() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen))
    asyncio.run(backend.generate(PROMPT, GenParams(stop=("\n\n", "</s>"))))
    assert seen["body"]["stop"] == ["\n\n", "</s>"]


# --------------------------------------------------------------- 错误映射
def test_http_4xx_is_mapped_and_not_retryable() -> None:
    backend = _backend(lambda r: httpx.Response(400, text="bad request"))
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams()))
    assert ei.value.code is ErrorCode.GENERATION_FAILED
    assert ei.value.retryable is False
    assert ei.value.details["status"] == 400


def test_http_5xx_is_retryable() -> None:
    backend = _backend(lambda r: httpx.Response(503, text="unavailable"))
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams()))
    assert ei.value.retryable is True
    assert ei.value.details["status"] == 503


def test_timeout_is_mapped_with_timeout_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    backend = _backend(handler, timeout=7.0)
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams()))
    assert ei.value.retryable is True
    assert "超时" in ei.value.message
    assert ei.value.details["timeout_seconds"] == 7.0


def test_connection_error_never_leaks_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    backend = _backend(handler, api_key="super-secret-key")
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams()))
    assert ei.value.retryable is True
    dumped = json.dumps(ei.value.details, ensure_ascii=False)
    assert "super-secret-key" not in dumped
    assert "Authorization" not in dumped


def test_empty_choices_is_explicit_error() -> None:
    backend = _backend(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(AppError) as ei:
        asyncio.run(backend.generate(PROMPT, GenParams()))
    assert "choices" in ei.value.message


def test_api_key_is_sent_as_bearer_when_configured() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen), api_key="k-123")
    asyncio.run(backend.generate(PROMPT, GenParams()))
    assert seen["headers"]["authorization"] == "Bearer k-123"


def test_no_authorization_header_when_key_absent() -> None:
    seen: dict = {}
    backend = _backend(_capture(seen))
    asyncio.run(backend.generate(PROMPT, GenParams()))
    assert "authorization" not in seen["headers"]


# --------------------------------------------------------------- 流式
def test_stream_parses_sse_deltas_and_stops_at_done() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        payload = "\n\n".join(
            [
                'data: {"model": "m", "choices": [{"delta": {"content": "你"}}]}',
                'data: {"choices": [{"delta": {"content": "好"}}]}',
                'data: {"choices": [{"delta": {}}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, text=payload + "\n\n")

    async def collect() -> list[str]:
        backend = _backend(handler)
        try:
            return [piece async for piece in backend.stream(PROMPT, GenParams())]
        finally:
            await backend.aclose()

    assert asyncio.run(collect()) == ["你", "好"]


# --------------------------------------------------------------- 版本口径
def test_version_falls_back_to_configured_then_served() -> None:
    backend = _backend(lambda r: httpx.Response(200, json=_ok_body(model="qwen-served")))
    assert backend.version == "Qwen2.5-7B-Instruct"  # 尚未探测
    asyncio.run(backend.generate(PROMPT, GenParams()))
    assert backend.version == "qwen-served"  # 服务端回包后回填


def test_build_from_settings_reads_config_once() -> None:
    settings = SimpleNamespace(
        vllm_base_url="http://127.0.0.1:8001/v1/",
        vllm_model="Qwen2.5-7B-Instruct",
        vllm_api_key="",
        vllm_timeout_seconds=9.0,
        vllm_guided_decoding_mode="off",
    )
    backend = build_from_settings(settings)
    assert backend.base_url == "http://127.0.0.1:8001/v1"  # 尾斜杠规整
    assert backend.model == "Qwen2.5-7B-Instruct"
    assert backend.timeout == 9.0
    assert backend.guided_decoding_mode == "off"


# --------------------------------------------------------------- 注册表
def test_registry_returns_vllm_backend_not_unavailable() -> None:
    """`vllm` 必须已由「未接入」变为真实工厂（`T-004` 的验收点之一）。"""
    from app.core.config import get_settings
    from app.inference.registry import get_backend

    get_settings.cache_clear()
    backend = get_backend("vllm")
    assert isinstance(backend, VllmBackend)
    assert backend.base_url == get_settings().vllm_base_url
    get_settings.cache_clear()
