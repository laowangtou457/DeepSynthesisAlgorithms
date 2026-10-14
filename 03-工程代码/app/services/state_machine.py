"""任务对话状态机（SW-001 七阶段流转 ＋ SW-003 梗概确认门控）。

设计要点
--------
1. **阶段全序**：`ORDER` 是唯一的顺序真值来源。推进只能沿全序前进一步，
   回退只能回到全序中位于当前位置之前的阶段。
2. **转移表带动作类型**：`TRANSITIONS` 把「源 → 目标」映射到一个动作
   （`generate` / `confirm` / `advance`）。这使「未经确认就进入剧本阶段」
   在**结构上不可能**发生——从「梗概修改」出发的唯一合法转移是 `confirm`；
   试图 `advance` 会因目标边不是 `advance` 动作而被拒。
   ⇒ **门控不是散落的 if 判断，而是转移表本身的形态**（判据即数据结构）。
3. **状态机不碰 IO**：本模块是纯函数 + 数据，可脱离 FastAPI 单测。
"""

from __future__ import annotations

from enum import Enum

from app.core.errors import AppError, ErrorCode
from app.schemas.dialogue import Stage


class Action(str, Enum):
    """推进方向上的一步动作类型。"""

    GENERATE = "generate"  # 需要一次生成（如「待梗概」→「梗概修改」）
    CONFIRM = "confirm"    # 需要客户确认（如「梗概修改」→「梗概确认」）
    ADVANCE = "advance"    # 直接推进
    ROLLBACK = "rollback"  # 回退


#: 阶段全序（推进方向）。**顺序的唯一真值来源。**
ORDER: tuple[Stage, ...] = (
    Stage.DRAFT_SYNOPSIS,
    Stage.SYNOPSIS_REVISING,
    Stage.SYNOPSIS_CONFIRMED,
    Stage.DRAFT_SCRIPT,
    Stage.DRAFT_STORYBOARD,
    Stage.DRAFT_SHOT_PROMPT,
    Stage.COMPLETED,
)

_INDEX: dict[Stage, int] = {stage: i for i, stage in enumerate(ORDER)}


#: (源, 目标) → 动作类型。**未登记的相邻转移视为非法**（防御性断言）。
TRANSITIONS: dict[tuple[Stage, Stage], Action] = {
    (Stage.DRAFT_SYNOPSIS, Stage.SYNOPSIS_REVISING): Action.GENERATE,
    (Stage.SYNOPSIS_REVISING, Stage.SYNOPSIS_CONFIRMED): Action.CONFIRM,
    (Stage.SYNOPSIS_CONFIRMED, Stage.DRAFT_SCRIPT): Action.ADVANCE,
    (Stage.DRAFT_SCRIPT, Stage.DRAFT_STORYBOARD): Action.ADVANCE,
    (Stage.DRAFT_STORYBOARD, Stage.DRAFT_SHOT_PROMPT): Action.ADVANCE,
    (Stage.DRAFT_SHOT_PROMPT, Stage.COMPLETED): Action.ADVANCE,
}


def next_stage(current: Stage) -> Stage | None:
    """全序中的下一个阶段；终态返回 `None`。"""
    idx = _INDEX[current]
    return ORDER[idx + 1] if idx + 1 < len(ORDER) else None


def label_of(stage: Stage) -> str:
    return stage.label_zh


def plan_advance(current: Stage) -> tuple[Stage, Action]:
    """解析「推进」的下一步。

    返回 `(目标阶段, 动作类型)`。当下一步需要**客户确认**时，抛
    `CONFIRMATION_REQUIRED`——这正是 SW-003 门控的对外表现形式。
    """
    nxt = next_stage(current)
    if nxt is None:
        raise AppError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"当前阶段「{label_of(current)}」已是终态，无法继续推进",
            details={"stage": current.value},
        )
    action = TRANSITIONS.get((current, nxt))
    if action is None:  # pragma: no cover - 表结构自检，正常不可达
        raise AppError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"状态表缺失转移：{current.value} → {nxt.value}",
        )
    if action is Action.CONFIRM:
        raise AppError(
            ErrorCode.CONFIRMATION_REQUIRED,
            f"须先确认「{label_of(current)}」的产物，方可进入「{label_of(nxt)}」阶段",
            details={"stage": current.value, "required_action": action.value},
        )
    return nxt, action


def plan_confirm(current: Stage) -> Stage:
    """解析「确认」动作的目标阶段；当前阶段不可确认时抛错。"""
    nxt = next_stage(current)
    if nxt is None or TRANSITIONS.get((current, nxt)) is not Action.CONFIRM:
        raise AppError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"当前阶段「{label_of(current)}」无需确认",
            details={"stage": current.value},
        )
    return nxt


def rollback_targets(current: Stage) -> list[Stage]:
    """可回退到的全部前置阶段（按全序升序）。"""
    return list(ORDER[: _INDEX[current]])


def resolve_rollback(current: Stage, target: Stage) -> Stage:
    """校验回退目标必须是**严格前置**阶段；不合法抛 `ROLLBACK_TARGET_INVALID`。"""
    if _INDEX[target] >= _INDEX[current]:
        raise AppError(
            ErrorCode.ROLLBACK_TARGET_INVALID,
            f"回退目标「{label_of(target)}」不是「{label_of(current)}」的前置阶段",
            details={
                "current_stage": current.value,
                "target_stage": target.value,
                "allowed_targets": [s.value for s in rollback_targets(current)],
            },
        )
    return target


def is_terminal(stage: Stage) -> bool:
    return stage is Stage.COMPLETED


def assert_table_consistency() -> None:
    """状态表自检：全序上每一对相邻阶段都必须登记，且不得有非法登记。

    供测试调用——**表结构本身也是被检查对象**。
    """
    for idx in range(len(ORDER) - 1):
        edge = (ORDER[idx], ORDER[idx + 1])
        if edge not in TRANSITIONS:
            raise AssertionError(f"状态表缺失相邻转移：{edge[0].value} → {edge[1].value}")
    for src, dst in TRANSITIONS:
        if _INDEX[dst] != _INDEX[src] + 1:
            raise AssertionError(
                f"状态表含非相邻转移：{src.value} → {dst.value}（跨阶段转移只能走 rollback）"
            )
