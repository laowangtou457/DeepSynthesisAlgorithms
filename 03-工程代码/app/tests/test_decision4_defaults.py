# -*- coding: utf-8 -*-
"""裁决 4（2026-11-09，`DEV-20261109-002`）两生成行为开关翻默认的防回退断言。

⚠️ 覆盖面边界：本文件**只**断言「默认值」与「两套开关解耦」，不重复
   `test_scene_orchestration.py`／`test_shot_prompt_scope.py` 已覆盖的接线行为。

背景：两个开关自 2026-11-05 落地起长期默认 `false`（生成行为改变类，须 A/B 验收
后才翻）。回炉后 r4 复验批按 `PRO-015` §3.2 约定线通过，项目方 2026-11-09
「确认翻开关」⇒ 同批翻 `true`。保留可机读断言，防止后续批次无意回退默认值，
也防止把「翻行为开关」误当成「翻 `quality_gate_enforce` 阻断开关」。
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings

#: 会影响本文件断言的三个环境变量（含两套开关解耦的对照项）。
_ENVS = (
    "APP_STORYBOARD_SCENE_ORCHESTRATION",
    "APP_SHOT_PROMPT_SEGMENT_SCOPE",
    "APP_QUALITY_GATE_ENFORCE",
    "APP_PACK_CONSERVATION_FILL",
)


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    """清掉外部 env 覆盖，前后各 `cache_clear()` 一次（`get_settings` 是 lru_cache 单例）。"""
    for key in _ENVS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_decision4_two_behavior_switches_default_on() -> None:
    """裁决 4：两个生成行为开关的默认值为 true。"""
    s = get_settings()
    assert s.storyboard_scene_orchestration is True
    assert s.shot_prompt_segment_scope is True


def test_decision4_does_not_flip_enforce_or_conservation() -> None:
    """两套开关解耦：翻行为开关不触发 ENFORCE，构造兜底也保持开（`PRO-016` V1.7 订正口径）。"""
    s = get_settings()
    assert s.quality_gate_enforce is False
    assert s.pack_conservation_fill is True


def test_decision4_env_override_still_rolls_back(monkeypatch) -> None:
    """回退通道可用 ⇒ A/B 器具 off 臂显式设 false 后，可复现性不受翻默认影响。"""
    monkeypatch.setenv("APP_STORYBOARD_SCENE_ORCHESTRATION", "false")
    monkeypatch.setenv("APP_SHOT_PROMPT_SEGMENT_SCOPE", "false")
    get_settings.cache_clear()
    s = get_settings()
    assert s.storyboard_scene_orchestration is False
    assert s.shot_prompt_segment_scope is False
