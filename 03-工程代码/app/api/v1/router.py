"""v1 路由汇总（ARCH-003 §3.4 `api/v1/router.py`）。

端点与需求编号的对应关系（**接口契约的目录索引**）：

| 模块 | 需求编号 | 状态 |
| --- | --- | --- |
| `dialogue`  | SW-I01（SW-001~003） | ✅ 本批实现 |
| `tasks`     | SW-I02（SW-004~008） | ✅ 本批实现（mock 后端） |
| `safety`    | SW-I03（SW-009~011、017） | ⏳ 占位（T-005） |
| `delivery`  | SW-I04 | ⏳ 占位（T-006） |
| `auth`      | SW-I05 | ⏳ 占位（二期） |
| `export`    | SW-I08 | ⏳ 占位（二期） |

⚠️ `SW-I06` 统一错误信封是**全接口共用的横切契约**，不在本表（无独立端点）——
其实现见 `app/core/errors.py`，由全局异常处理器统一装配。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import auth, delivery, dialogue, export, safety, tasks


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(dialogue.router)
    router.include_router(tasks.router)
    router.include_router(safety.router)
    router.include_router(delivery.router)
    router.include_router(auth.router)
    router.include_router(export.router)
    return router
