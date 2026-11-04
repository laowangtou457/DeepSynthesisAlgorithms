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
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Any

#: 工程根（`03-工程代码`）：`app/core/logging.py` → parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

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


def configure_logging(level: int = logging.INFO, *, settings: Any = None) -> None:
    """进程级日志初始化（幂等：重复调用只重设级别／重建文件通道）。

    **两个通道**（`T-090`，官方第 9 项「溯源日志留存 ≥6 个月」）：

    | 通道 | 载体 | 内容 |
    | --- | --- | --- |
    | 应用日志 | `stdout` ＋ `<log_dir>/app.log`（按日轮转） | 全部结构化事件（JSON 单行） |
    | **溯源审计** | `<log_dir>/audit.log`（按日轮转） | `SW-016` 五要素：会话／阶段／模型／模板／时间／结果 |

    ⚠️ 留存：`backupCount = log_retention_days`（默认 **180**）——`TimedRotatingFileHandler`
    在每次轮转时删除超过该天数的旧件 ⇒ 「6 个月」由**机制保证**，不靠人工清理。
    ⚠️ 幂等：按处理器上的 `_wb_kind` 标记去重；重复调用不会叠加重复行（uvicorn `--reload`
    与测试反复 `create_app` 都会走到这里）。
    """
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    root = logging.getLogger("app")
    root.setLevel(level)
    root.propagate = False

    # ① stdout（始终保留：容器/前台运维的可读出口）
    if not any(getattr(h, "_wb_kind", "") == "stdout" for h in root.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._wb_kind = "stdout"  # type: ignore[attr-defined]
        root.handlers = [h for h in root.handlers if h.formatter is None] + [handler]
    for h in root.handlers:
        if getattr(h, "_wb_kind", "") == "stdout":
            h.setLevel(level)

    if not bool(getattr(settings, "log_to_file", True)):
        # 关闭落盘时**移除**既有的文件通道（避免测试互相污染）
        root.handlers = [h for h in root.handlers if getattr(h, "_wb_kind", "") != "app_file"]
        audit = logging.getLogger("app.audit")
        audit.handlers = []
        return

    log_dir = _resolve_log_dir(str(getattr(settings, "log_dir", "") or ""))
    retention = int(getattr(settings, "log_retention_days", 180) or 180)

    # ② 应用日志落盘（按日轮转，留存 = retention_days）
    # ⚠️ 幂等判断**不能只看「有没有」**：`app.main` 在导入期就会用**默认配置**建一次通道，
    #    之后 `create_app(自定义 Settings())`（测试／部署切目录）必须**改指向**，
    #    否则日志会静默写去旧目录（本批实测踩到：`tmp_path` 里空无一物）。
    app_path = log_dir / "app.log"
    _ensure_file_handler(root, "app_file", app_path, retention)

    # ③ 溯源审计通道（**独立 logger + 独立文件**：审计件的留存与可调取不依赖应用日志）
    audit = logging.getLogger("app.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False
    _ensure_file_handler(audit, "audit_file", log_dir / "audit.log", retention)


def _ensure_file_handler(
    logger: logging.Logger, kind: str, path: Path, retention_days: int
) -> None:
    """确保 `logger` 上恰有一个指向 `path`、留存为 `retention_days` 的文件通道。"""
    for h in list(logger.handlers):
        if getattr(h, "_wb_kind", "") != kind:
            continue
        target = Path(getattr(h, "baseFilename", "") or "")
        if target.resolve() == path.resolve() and getattr(h, "backupCount", -1) == retention_days:
            return  # 已在位且口径一致
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:  # noqa: BLE001 - 关闭旧通道失败不应影响启动
            pass
    fh = _daily_handler(path, retention_days)
    fh._wb_kind = kind  # type: ignore[attr-defined]
    logger.addHandler(fh)


def _resolve_log_dir(raw: str) -> Path:
    """日志目录：显式配置优先，否则 `<工程根>/.wb-e2e/logs`（gitignore 内）。"""
    d = Path(raw) if raw else _PROJECT_ROOT / ".wb-e2e" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _daily_handler(path: Path, retention_days: int) -> logging.Handler:
    """按日轮转的文件通道；`backupCount` 即留存天数（超期由 logging 自动删除）。"""
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",
        interval=1,
        backupCount=max(int(retention_days), 1),
        encoding="utf-8",
        delay=True,
        utc=False,
    )
    # 轮转后文件名形如 `app.log.2026-11-04`（日期可读，便于人工调取与截图举证）
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(JsonFormatter())
    return handler


def get_audit_logger() -> logging.Logger:
    """溯源审计 logger（`SW-016` 五要素由 `core/audit.py` 组装后写入本通道）。"""
    return logging.getLogger("app.audit")


def get_logger(name: str = "app") -> logging.Logger:
    if name == "app" or name.startswith("app."):
        return logging.getLogger(name)
    return logging.getLogger(f"app.{name}")
