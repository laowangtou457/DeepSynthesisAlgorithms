"""pytest 公共配置。

包根是**上一级目录**（`03-工程代码`）——即 `app` 包的父目录；
`pythonpath = [".."]`（见 pyproject.toml）已把该目录加入导入路径，
此处再加一道保险，使测试可脱离 pytest 直接运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]  # 03-工程代码
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    """新建应用实例并返回测试客户端（每个测试独立，避免会话串扰）。"""
    get_settings.cache_clear()
    app = create_app(Settings())
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


# ---- 裁决 4（2026-11-09，`DEV-20261109-002`）后的测试配置隔离 ----
#: 生产默认已把两个生成行为开关翻 `true`。下列三个模块测的是
#: 「API 链路阶段顺序／产物形态闸／门禁重试回路」，其假上游剧本不含 `acts[]`；
#: 逐场编排会在前置显式报错（502）而根本走不到被测断言 ⇒ 用 env 把它们钉回旧形态。
#: 其余模块（尤其 `test_scene_orchestration.py`／`test_shot_prompt_scope.py`）
#: 一律使用生产默认值；新默认本身由 `test_decision4_defaults.py` 单独断言。
#: ⚠️ 这是**测试夹具与生产默认解耦**，不是把断言期望值改松。
_LEGACY_BEHAVIOR_MODULES = frozenset({
    "test_api_smoke",
    "test_artifact_gate",
    "test_quality_gate_t086",
})


@pytest.fixture(autouse=True)
def _pin_legacy_behavior_defaults(request, monkeypatch):
    """仅在上述三模块内把两开关钉为 false（含 `Settings()` 直接构造路径）。"""
    if request.module.__name__.rsplit(".", 1)[-1] not in _LEGACY_BEHAVIOR_MODULES:
        yield
        return
    monkeypatch.setenv("APP_STORYBOARD_SCENE_ORCHESTRATION", "false")
    monkeypatch.setenv("APP_SHOT_PROMPT_SEGMENT_SCOPE", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
