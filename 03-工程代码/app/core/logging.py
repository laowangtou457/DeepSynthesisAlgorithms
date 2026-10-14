"""结构化日志与请求上下文。

对应 ARCH-003 §6.5「可观测性与审计留痕」：

- 输出 JSON 单行日志，字段含 `request_id`、事件名与结构化键值；
- **严禁记录完整用户文本与密钥**，只记 `input_digest`（哈希前 16 位）；
- 生产可平滑替换为 `structlog`，本模块对外接口保持不变。
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sys
import time
from typing import Any

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def set_request_id(value: str) -> contextvars.Token[str]:
    return _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def digest(text: str, length: int = 16) -> str:
    """输入摘要（不存明文）。审计与缓存键均用本口径。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


class JsonFormatter(logging.Formatter):
    """JSON 行格式。异常只记**类型名**，不记堆栈（与 SW-I06 同口径）。"""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": get_request_id(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """进程级日志初始化（幂等：重复调用只重设级别）。"""
    root = logging.getLogger("app")
    root.setLevel(level)
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.handlers = [handler]
    root.propagate = False


def get_logger(name: str = "app") -> logging.Logger:
    if name == "app" or name.startswith("app."):
        return logging.getLogger(name)
    return logging.getLogger(f"app.{name}")
