"""状态机单元测试（SW-001 七阶段流转 · SW-003 确认门控）。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.schemas.dialogue import Stage
from app.services import state_machine as sm


def test_table_consistency() -> None:
    """转移表自检：全序相邻必登记、且不得有跨阶段登记。"""
    sm.assert_table_consistency()


def test_order_matches_requirement() -> None:
    """七阶段顺序与 SW-001 原文逐项一致（防止顺序被误改）。"""
    assert [s.label_zh for s in sm.ORDER] == [
        "待梗概",
        "梗概修改",
        "梗概确认",
        "待剧本",
        "待分镜",
        "待提示词",
        "已完成",
    ]


def test_advance_walks_the_whole_chain() -> None:
    """从「待梗概」可沿全序走完全链路（跳过需确认的一段）。"""
    seq: list[Stage] = []
    stage = Stage.DRAFT_SYNOPSIS
    while True:
        try:
            nxt, _action = sm.plan_advance(stage)
        except AppError as exc:
            assert exc.code is ErrorCode.CONFIRMATION_REQUIRED, exc
            stage = sm.plan_confirm(stage)
            seq.append(stage)
            continue
        stage = nxt
        seq.append(stage)
        if sm.is_terminal(stage):
            break
    assert seq == list(sm.ORDER[1:])


def test_gate_blocks_unconfirmed_advance() -> None:
    """SW-003 门控：未确认梗概时，「推进」被拒（而不是悄悄跳过）。"""
    with pytest.raises(AppError) as ei:
        sm.plan_advance(Stage.SYNOPSIS_REVISING)
    assert ei.value.code is ErrorCode.CONFIRMATION_REQUIRED
    assert ei.value.status_code == 409


def test_confirm_only_valid_where_required() -> None:
    """「确认」只在需要确认的阶段成立；其它阶段调用即报错。"""
    assert sm.plan_confirm(Stage.SYNOPSIS_REVISING) is Stage.SYNOPSIS_CONFIRMED
    for stage in (Stage.DRAFT_SYNOPSIS, Stage.SYNOPSIS_CONFIRMED, Stage.DRAFT_SCRIPT):
        with pytest.raises(AppError) as ei:
            sm.plan_confirm(stage)
        assert ei.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_terminal_stage_cannot_advance() -> None:
    with pytest.raises(AppError) as ei:
        sm.plan_advance(Stage.COMPLETED)
    assert ei.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_rollback_targets_are_strictly_prior() -> None:
    assert sm.rollback_targets(Stage.DRAFT_STORYBOARD) == [
        Stage.DRAFT_SYNOPSIS,
        Stage.SYNOPSIS_REVISING,
        Stage.SYNOPSIS_CONFIRMED,
        Stage.DRAFT_SCRIPT,
    ]


def test_rollback_rejects_non_prior_target() -> None:
    for target in (Stage.DRAFT_STORYBOARD, Stage.DRAFT_SHOT_PROMPT, Stage.COMPLETED):
        with pytest.raises(AppError) as ei:
            sm.resolve_rollback(Stage.DRAFT_SCRIPT, target)
        assert ei.value.code is ErrorCode.ROLLBACK_TARGET_INVALID
