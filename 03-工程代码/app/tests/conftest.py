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
