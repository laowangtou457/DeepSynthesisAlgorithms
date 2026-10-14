"""任务对话契约（SW-I01 承载 SW-001 / SW-002 / SW-003）。

状态取值为 **SW-001** 原文的七阶段：

    待梗概 → 梗概修改 → 梗概确认 → 待剧本 → 待分镜 → 待提示词 → 已完成

⚠️ 阶段取值是**契约**：一经发布不得随意改名（改名即破坏既有会话的可恢复性）。
中文标签由 `Stage.label_zh` 给出，界面展示用标签、接口传值用 `value`。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Stage(str, Enum):
    """任务对话七阶段（SW-001）。"""

    DRAFT_SYNOPSIS = "draft_synopsis"          # 待梗概
    SYNOPSIS_REVISING = "synopsis_revising"    # 梗概修改
    SYNOPSIS_CONFIRMED = "synopsis_confirmed"  # 梗概确认
    DRAFT_SCRIPT = "draft_script"              # 待剧本
    DRAFT_STORYBOARD = "draft_storyboard"      # 待分镜
    DRAFT_SHOT_PROMPT = "draft_shot_prompt"    # 待提示词
    COMPLETED = "completed"                    # 已完成

    @property
    def label_zh(self) -> str:
        return _STAGE_LABELS[self]


_STAGE_LABELS: dict[Stage, str] = {
    Stage.DRAFT_SYNOPSIS: "待梗概",
    Stage.SYNOPSIS_REVISING: "梗概修改",
    Stage.SYNOPSIS_CONFIRMED: "梗概确认",
    Stage.DRAFT_SCRIPT: "待剧本",
    Stage.DRAFT_STORYBOARD: "待分镜",
    Stage.DRAFT_SHOT_PROMPT: "待提示词",
    Stage.COMPLETED: "已完成",
}


class SessionCreateRequest(BaseModel):
    """创建任务会话（客户一句话／素材）。"""

    source_input: str = Field(
        min_length=1, max_length=2000, description="一句话创意或要点清单"
    )
    genre: str | None = Field(default=None, description="题材倾向")
    target_duration: str | None = Field(default=None, description="成片目标时长")
    audience: str | None = Field(default=None, description="目标受众")


class SessionView(BaseModel):
    """会话视图（对外可见的会话状态）。"""

    session_id: str
    stage: Stage
    stage_label: str
    created_at: str
    updated_at: str
    artifacts: dict[str, Any] = Field(
        default_factory=dict, description="各阶段产物快照（key = 阶段名）"
    )
    confirmed_snapshot: dict[str, Any] | None = Field(
        default=None, description="梗概确认时固化的快照（SW-003）"
    )
    history: list[str] = Field(default_factory=list, description="状态迁移轨迹")


class AdvanceRequest(BaseModel):
    """推进到下一阶段（可能触发一次生成）。"""

    variables: dict[str, Any] = Field(
        default_factory=dict, description="本次生成所需变量（覆盖会话默认值）"
    )
    force: bool = Field(
        default=False,
        description="保留位：仅供内部联调；**不改变门控语义**，未确认梗概时仍拒绝",
    )


class ReviseRequest(BaseModel):
    """对话式修改（SW-002）：以自然语言意见对当前阶段产物做定向修改。"""

    modification_request: str = Field(min_length=1, description="客户的自然语言修改意见")
    target_stage: Stage | None = Field(default=None, description="修改对象阶段，缺省为当前阶段")


class ConfirmRequest(BaseModel):
    """确认门控（SW-003）：确认当前产物完整，允许进入下一阶段。"""

    note: str | None = Field(default=None, description="确认备注")


class RollbackRequest(BaseModel):
    """回退到任意**前置**阶段（SW-001）。"""

    target_stage: Stage = Field(description="目标阶段，必须是当前阶段之前的状态")
    reason: str | None = Field(default=None, description="回退原因（留痕用）")


class TransitionResult(BaseModel):
    """一次状态迁移的结果。"""

    session_id: str
    action: str = Field(description="本次动作：generate / confirm / advance / rollback / revise")
    from_stage: Stage
    to_stage: Stage
    stage_label: str
    view: SessionView
