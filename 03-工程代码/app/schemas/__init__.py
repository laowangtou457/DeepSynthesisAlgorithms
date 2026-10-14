"""对外契约层（请求／响应／错误）。

- `common.py` —— 成功信封、健康检查
- `dialogue.py` —— 任务对话与状态机（SW-I01 / SW-001~003）
- `task.py` —— 生成任务（SW-I02 / SW-004~008）

契约纪律：**接口传值用稳定 `value`，界面展示才用中文标签**；
取值一经发布不得改名（改名即破坏既有会话与既有产物的可解析性）。
"""

from app.schemas.common import Envelope, HealthStatus
from app.schemas.dialogue import (
    AdvanceRequest,
    ConfirmRequest,
    ReviseRequest,
    RollbackRequest,
    SessionCreateRequest,
    SessionView,
    Stage,
    TransitionResult,
)
from app.schemas.task import (
    GenerationOutput,
    GenerationRequest,
    GenerationResponse,
    LatencyBreakdown,
    ModelInfo,
    Provenance,
    SamplingParams,
    SafetyDecision,
    TemplateInfo,
    Usage,
)

__all__ = [
    "Envelope",
    "HealthStatus",
    "Stage",
    "SessionCreateRequest",
    "SessionView",
    "AdvanceRequest",
    "ReviseRequest",
    "ConfirmRequest",
    "RollbackRequest",
    "TransitionResult",
    "SamplingParams",
    "GenerationRequest",
    "GenerationOutput",
    "Usage",
    "ModelInfo",
    "SafetyDecision",
    "Provenance",
    "LatencyBreakdown",
    "GenerationResponse",
    "TemplateInfo",
]
