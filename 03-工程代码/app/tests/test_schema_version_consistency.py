"""`schema_version` 契约常量的**一致性断言** —— 防「多处手抄」分叉。

⚠️ **背景（2026-11-03 实测发现）**：`CFG-006` 的 `schema_version` 在**三处**被手抄：

| # | 位置 | 角色 |
| --- | --- | --- |
| 1 | `delivery/schemas/CFG-006_shot_prompt_pack.v1.schema.json` 的 `const` | **契约真值源** |
| 2 | `prompts/templates/TPL-009_shot_prompt_v1.yaml` 正文的 `"schema_version"` | **模型实际写进产物的值** |
| 3 | `app/inference/mock_backend.py` | mock 产物（形态闸会校验） |

⚠️ **实测已发生过一次分叉**：v2.1.0 那次修订**只改了版本说明、漏改正文**
⇒ 模板正文是 `2.0.0`、契约 `const` 是 `2.1.0`
⇒ 模型照模板写出的值与契约不符 ⇒ **形态闸／交付门禁报错 ⇒ 产物白跑**。

⇒ 本文件把三者**互锁**：任一处改动而另两处未改 ⇒ **测试立刻失败**。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(r"E:\深度合成算法工程材料\03-工程代码")


def _schema_const() -> str:
    schema = json.loads(
        (ROOT / "delivery" / "schemas" / "CFG-006_shot_prompt_pack.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    return schema["properties"]["schema_version"]["const"]


def _template_const() -> str:
    text = (ROOT / "prompts" / "templates" / "TPL-009_shot_prompt_v1.yaml") \
        .read_text(encoding="utf-8")
    m = re.search(r'"schema_version":\s*"([0-9.]+)"', text)
    assert m, "TPL-009 正文里找不到 schema_version 常量"
    return m.group(1)


def _mock_const() -> str:
    text = (ROOT / "app" / "inference" / "mock_backend.py").read_text(encoding="utf-8")
    m = re.search(r'"schema_version":\s*"([0-9.]+)"', text)
    assert m, "mock_backend.py 里找不到 schema_version 常量"
    return m.group(1)


def test_schema_version_constants_are_consistent() -> None:
    """⚠️ **三处必须相等**（契约真值源／模板正文／mock 后端）。"""
    const = _schema_const()
    assert _template_const() == const, (
        f"★ TPL-009 正文与 schema const 不一致："
        f"模板 {_template_const()} ≠ 契约 {const}"
    )
    assert _mock_const() == const, (
        f"★ mock_backend 与 schema const 不一致："
        f"mock {_mock_const()} ≠ 契约 {const}"
    )


def test_schema_version_is_not_stale() -> None:
    """⚠️ 契约常量须为**现行版**（不是历史值）。"""
    const = _schema_const()
    assert const == "2.3.0", f"契约常量应为 2.3.0（`T-098` vocabRef 枚举化，取值域收紧升次版本；`PRO-011` 线 3），实得 {const}"
