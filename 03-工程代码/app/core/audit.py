"""溯源审计留痕 —— `SW-016` 五要素，官方第 9 项「生成内容溯源留存 ≥6 个月」（`T-090`）。

## 为什么单独一个模块

- **语义**（五要素怎么取、哪些字段不许落明文）属本模块；
- **通道**（写到哪、怎么轮转、留存几天）属 `core/logging.py`。
  两者分开，改留存策略不动审计语义，反之亦然。

## 五要素（`SW-016`）与取数来源

| 要素 | 字段 | 来源 |
| --- | --- | --- |
| 会话 | `session_id` | 状态迁移结果 |
| 阶段 | `stage` | `to_stage`（真正产出内容的阶段） |
| 模型 | `model.name`／`backend`／`revision` | 产物 `model.version`（模型名）、`backend`（后端标识）；`revision` 取不到时为 `null` |
| 模板 | `templates[].id/version` | 产物 `template_id`／`template_version` |
| 时间 | `ts` | 记录时点（ISO 8601，含时区偏移） |
| 结果 | `result.status`／`chars`／`digest` | `ok` ＋ 正文**摘要**（**绝不落明文**，同 `core/logging.py` 纪律） |

⚠️ **不复述产物正文**：审计件用于「这份内容什么时候、由哪个模型、按哪版模板产出」的溯源，
**不是**内容归档——正文在交付包里。审计件落明文会把留存成本与 PII 面一并放大。

⚠️ `model` 的两个字段**在本工程里语义相反**（`inference/base.py`：`name`＝后端标识、
`version`＝模型名；schema／样例口径相反）——本模块**显式对调**并在此注明，
避免下一个读者再踩一次（`delivery_service._model_trace` 的同款教训）。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.logging import digest, get_audit_logger, get_request_id

#: 产生一次「内容产出」的动作（`advance` 的 `generate` 与 `revise`）
TRACE_ACTIONS = ("generate", "revise")

#: 本机时区（审计件给人看：备案截图、人工调取）
_CST = timezone(timedelta(hours=8))

#: 阶段值的前后缀（`draft_script` → `script`；`synopsis_revising` → `synopsis`）
_DRAFT_PREFIX = "draft_"
_STAGE_SUFFIXES = ("_revising", "_confirmed")


def artifact_key_for(stage: str) -> str:
    """**阶段值 → 产物键**（如 `draft_script` → `script`、`synopsis_revising` → `synopsis`）。

    ⚠️ **这是一份与 `dialogue_service._artifact_key_of` 并行的规则**（后者用显式映射表，
    本处用可推导的前后缀规则）。两个来源必须始终相等——由
    `tests/test_log_retention.py::test_artifact_key_rule_matches_service_map` 互锁对拍；
    分叉即报警（本工程反复踩过「同一口径两处手写」的坑，故此处**不留裸副本**）。
    """
    s = str(stage or "")
    if s.startswith(_DRAFT_PREFIX):
        s = s[len(_DRAFT_PREFIX):]
    for suf in _STAGE_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def build_trace(
    *,
    session_id: str,
    stage: str,
    artifact: dict[str, Any] | None,
    action: str,
    request_id: str = "",
) -> dict[str, Any]:
    """组装一条五要素溯源记录（**纯函数**，便于测试与复用）。"""
    art = artifact or {}
    model = art.get("model") or {}
    text = str(art.get("text") or "")
    gate = art.get("quality_gate") or {}
    return {
        "kind": "trace_generation",
        "ts": datetime.now(_CST).isoformat(timespec="seconds"),
        # ① 会话
        "session_id": session_id,
        # ② 阶段
        "stage": stage,
        # ③ 模型（⚠️ 语义对调：`model.version` 才是模型名，见模块头注）
        "model": {
            "name": str(model.get("version") or model.get("name") or ""),
            "backend": str(art.get("backend") or model.get("name") or ""),
            "revision": art.get("model_revision"),
        },
        # ④ 模板
        "templates": [
            {
                "id": str(art.get("template_id") or ""),
                "version": str(art.get("template_version") or ""),
            }
        ],
        # ⑤ 结果（正文只留摘要与长度，不落明文）
        "result": {
            "action": action,
            "status": "ok",
            "chars": len(text),
            "digest": digest(text),
            "quality_gate_ok": gate.get("ok"),
            "quality_gate_attempts": gate.get("attempts"),
        },
        "request_id": request_id or get_request_id(),
    }


def emit_trace(record: dict[str, Any]) -> None:
    """写入审计通道（`<log_dir>/audit.log`，按日轮转，留存 `log_retention_days`）。"""
    get_audit_logger().info("trace_generation", extra={"extra_fields": record})


def trace_transition(result: Any) -> dict[str, Any] | None:
    """从一次状态迁移结果中提取五要素并落审计；**不产出内容的动作不记**。

    返回值：写入的记录（便于调用方/测试断言）；不适用时返回 `None`。
    """
    action = str(getattr(result, "action", "") or "")
    if action not in TRACE_ACTIONS:
        return None
    stage = str(getattr(getattr(result, "to_stage", ""), "value", "") or getattr(result, "to_stage", ""))
    view = getattr(result, "view", None)
    artifacts = getattr(view, "artifacts", None) or {}
    # ⚠️ 产物键 ≠ 阶段值（`synopsis_revising` 的产物存在 `synopsis` 下，实测踩到）
    key = artifact_key_for(stage)
    artifact = artifacts.get(key) if isinstance(artifacts, dict) else None
    if not isinstance(artifact, dict) or not artifact.get("text"):
        return None
    record = build_trace(
        session_id=str(getattr(result, "session_id", "") or ""),
        stage=stage,
        artifact=artifact,
        action=action,
        request_id=get_request_id(),
    )
    emit_trace(record)
    return record
