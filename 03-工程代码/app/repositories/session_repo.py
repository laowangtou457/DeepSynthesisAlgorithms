"""会话存储。

本批（T-003 一期）为**进程内存实现**，仅用于打通链路与自动化测试。

替换路径（T-004 及二期）：PostgreSQL `sessions` 表 + Redis 热缓存，
见 ARCH-003 §7.2；**本层接口保持不变**，替换实现不影响服务层。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    """本机时区的 ISO 时间串（秒精度）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class SessionRecord:
    """会话记录（持久化实体）。"""

    session_id: str
    stage: str
    source_input: str
    created_at: str
    updated_at: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    confirmed_snapshot: dict[str, Any] | None = None
    history: list[str] = field(default_factory=list)
    #: 会话级默认变量（创建时由 source_input 等派生，供各阶段生成兜底）
    defaults: dict[str, Any] = field(default_factory=dict)


class SessionRepository:
    """线程安全的内存会话仓库。"""

    def __init__(self) -> None:
        self._data: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    def create(self, *, stage: str, source_input: str, defaults: dict[str, Any]) -> SessionRecord:
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        ts = now_iso()
        rec = SessionRecord(
            session_id=sid,
            stage=stage,
            source_input=source_input,
            created_at=ts,
            updated_at=ts,
            defaults=defaults,
        )
        with self._lock:
            self._data[sid] = rec
        return rec

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._data.get(session_id)

    def save(self, rec: SessionRecord) -> None:
        rec.updated_at = now_iso()
        with self._lock:
            self._data[rec.session_id] = rec

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._data.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        """仅供测试使用。"""
        with self._lock:
            self._data.clear()
