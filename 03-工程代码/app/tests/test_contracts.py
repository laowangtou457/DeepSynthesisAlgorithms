"""契约层与统一错误信封（SW-I06）测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.errors import _DEFAULT_STATUS, AppError, ErrorCode
from app.schemas.task import GenerationRequest, SamplingParams


def test_every_error_code_has_http_status() -> None:
    """每个错误码都必须登记默认 HTTP 状态（防止端点各自裁决）。"""
    for code in ErrorCode:
        assert code in _DEFAULT_STATUS, f"{code} 缺默认状态码"


def test_error_envelope_shape_is_stable() -> None:
    """统一错误信封的字段集固定（SW-I06 契约）。"""
    env = AppError(ErrorCode.SESSION_NOT_FOUND, "会话不存在").to_envelope("req_x")
    body = env.model_dump()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "request_id", "retryable"}
    assert body["error"]["request_id"] == "req_x"


def test_envelope_never_carries_stacktrace() -> None:
    """信封结构里**不存在**承载堆栈的字段（结构性保证，不靠自觉）。"""
    env = AppError(ErrorCode.INTERNAL_ERROR, "服务内部错误").to_envelope()
    assert "traceback" not in env.model_dump_json()
    assert "stack" not in env.model_dump_json().lower()


def test_retryable_defaults() -> None:
    assert AppError(ErrorCode.INTERNAL_ERROR, "x").retryable is True
    assert AppError(ErrorCode.GENERATION_FAILED, "x").retryable is True
    assert AppError(ErrorCode.SESSION_NOT_FOUND, "x").retryable is False


def test_conflicts_use_409() -> None:
    """状态机类冲突一律 409（并发语义），而不是 400。"""
    for code in (
        ErrorCode.INVALID_STATE_TRANSITION,
        ErrorCode.CONFIRMATION_REQUIRED,
        ErrorCode.ROLLBACK_TARGET_INVALID,
    ):
        assert _DEFAULT_STATUS[code] == 409


def test_sampling_bounds_enforced_by_contract() -> None:
    """区间约束在契约层声明，越界即 ValidationError。"""
    SamplingParams(temperature=0, top_p=1, max_tokens=1)  # 边界合法
    for bad in (
        {"temperature": 2.5},
        {"temperature": -0.1},
        {"top_p": 0},
        {"top_p": 1.5},
        {"max_tokens": 0},
        {"max_tokens": 99999},
        {"repetition_penalty": 0},
    ):
        with pytest.raises(ValidationError):
            SamplingParams(**bad)


def test_generation_request_requires_template_or_stage() -> None:
    """`template_id` 与 `stage` 均为可选**在契约层**——二者必居其一是服务层判据，
    此处只固化「都不给时仍能构造对象」这一事实（判据由端点测试覆盖）。"""
    req = GenerationRequest()
    assert req.template_id is None and req.stage is None
