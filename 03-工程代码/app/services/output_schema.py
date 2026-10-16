"""输出契约 schema 的加载（**受约束解码**的 schema 来源）。

`TPL-009_shot_prompt_v1.yaml` 的 `sampling` 注释明写：

    本层输出为**受约束解码**的 JSON（服务层以 jsonschema 为 FSM 约束采样，
    `CFG-006_shot_prompt_pack.v1.schema.json`）。

故服务层**必须**把该 schema 交给推理后端——这是**契约要求**，不是额外耦合；
`T-003` 已在 `TextGenerator.generate(..., json_schema)` 预留参数位，
本模块补的是「schema 从哪来」，`dialogue_service` 补的是「把它传下去」。

⚠️ 与「离线交付门禁」的**边界**：本模块只**读取 schema 用于采样约束**；
   对产物跑 `validate_pack.py` 做判定属交付层（`SW-I04`，当前返回 `501`），
   **不**在服务层引入工程侧脚本依赖。

⚠️ 加载失败（文件缺失／不可解析）时**抛错，而非静默放弃约束**——
   静默放弃会让产物从「受约束解码」悄悄退化为「自由生成」，
   这正是本工程最忌讳的「静默降级」。

⚠️ **两个函数，两种形态，不得混用**：
   - `load_output_schema()` = **契约真值**（完整，用于应用层校验与留档）；
   - `load_engine_schema()` = **引擎可编译形态**（剥离 `ENGINE_UNSUPPORTED_KEYS`，
     供受约束解码）。剥离只**换执行位置**，约束不丢失——见 `ENGINE_UNSUPPORTED_KEYS`。

⚠️ **两类来源，同一入口（`ISSUE-042` 起）**：
   本工程只有 `shot_prompt` 层有**契约文件**（`CFG-006`）。中间三层
   （`synopsis`／`script`／`storyboard`）的形态真值原先只存在于人读文档
   （`CFG-007_SCHEMA.md`）与**离线**门禁脚本（`validate_output.py`）里，
   ⇒ 运行期**拿不到**，三段的 `constrained_decoding` 恒为 `false`（实测），
   模型因而可以自由产出**截断的 JSON**（即 `ISSUE-042`）。
   现由 `app/services/artifact_contract.py` 把 R5 真值搬进运行期，
   `load_engine_schema()` 对这三段返回**派生形态 schema**（`required` 投影）。
   ⚠️ 派生 schema 是**真值的投影、不是第二份真值**——「约束这些键必须在」只约束**形态**，
   不约束字段类型与多余键（那两件事分别属契约文件与交付层 R36）。
   ⚠️ 两个来源**必须走同一入口**：调用方一律用 `load_engine_schema()`，
   不得自行判断「这段有没有 schema」——那正是本缺陷的成因形态。
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services import artifact_contract

_log = get_logger(__name__)

#: 引擎侧（xgrammar）**不支持**的 JSON Schema 关键字 —— 发给引擎前必须剥离。
#:
#: 实测依据（`OPS-002` §4.3.1 ①，2026-10-15 端到端校验）：真实 `CFG-006` 原样传入
#: 即被**编译期**拒收 —— `{"error":{"message":"Grammar error: Unimplemented keys:
#: [\"uniqueItems\"]","code":400}}`（≈0.01 s，**响亮失败而非静默退化**）；
#: 逐轮剥离实测**只需剥这一处**（`pattern`×16／`enum`×19／`minItems`×7／`maxItems`／
#: `minLength`／`minimum`／`multipleOf`／`const`／`oneOf`／`$ref`×9／`format` **全部可通过**）。
#:
#: ⚠️ 剥离的后果与**补回方式**：`uniqueItems` 表达的「数组元素不重复」在**解码期失效**，
#: 但约束**不丢失** —— 应用层仍用**完整** schema 走 `jsonschema` 校验（`validate_pack.py`
#: 支持该键）⇒ 约束**换执行位置**，不是被删除。
#: 故本表**只**列确有实测证据的键，其余键**逐字保留**；新增条目须附实测出处。
ENGINE_UNSUPPORTED_KEYS: frozenset[str] = frozenset({"uniqueItems"})

#: 阶段 → 输出契约 schema 的工程内相对路径（**契约文件型**来源）。
#:
#: 只有 `shot_prompt` 层的产物（＝交付包）有契约文件：规范对**交付包**建立了
#: JSON Schema（`CFG-006_shot_prompt_pack.v1.schema.json`）。
#: 其余三段（`synopsis`/`script`/`storyboard`）的产物是**中间 JSON**，
#: 契约以「顶层必需键」形式存在于 `validate_output.py` 的 R5 —— 该真值现由
#: `artifact_contract.REQUIRED_TOP_KEYS` 承载，走**派生型**来源（见 `load_engine_schema`）。
#: `revise` 层不在本表内（其产物为交付包或独立台账，由 `SW-008` 自身判据承担）。
STAGE_SCHEMA: dict[str, str] = {
    "shot_prompt": "delivery/schemas/CFG-006_shot_prompt_pack.v1.schema.json",
}


def _schemas_dir() -> Path:
    """schema 根目录：显式配置优先，否则按工程布局定位。"""
    settings = get_settings()
    configured = (settings.delivery_schemas_dir or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # prompts_dir 指向 `<工程代码>/prompts`，其父目录即 `<工程代码>`
    return settings.prompts_dir.parent / "delivery" / "schemas"


def schema_path_for(stage: str) -> Path | None:
    rel = STAGE_SCHEMA.get(stage)
    if rel is None:
        return None
    return _schemas_dir() / Path(rel).name


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> dict:
    path = Path(path_str)
    if not path.is_file():
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "输出契约 schema 不存在——受约束解码无法建立",
            details={"expected": str(path)},
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "输出契约 schema 不是合法 JSON",
            details={"path": str(path), "reason": exc.msg},
        ) from exc
    if not isinstance(loaded, dict):
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "输出契约 schema 顶层应为对象",
            details={"path": str(path)},
        )
    return loaded


def load_output_schema(stage: str) -> dict | None:
    """取该阶段的**契约真值** schema（完整，含全部关键字）。

    该阶段无交付契约时返回 `None`（非错误）。⚠️ **发给引擎请用
    `load_engine_schema()`** —— 本函数返回的形态含 `uniqueItems`，引擎编译期即报错。
    """
    path = schema_path_for(stage)
    if path is None:
        return None
    return _load_cached(str(path))


def _strip_unsupported(node: Any, removed: list[str], path: str = "$") -> Any:
    """返回剥离了引擎不支持关键字的**深拷贝**；`removed` 记录被剥键的路径。

    ⚠️ 必须**深拷贝**：`_load_cached` 的返回对象被 `lru_cache` 复用，
       原地 `del` 会污染「完整契约 schema」这一真值 —— 后续任何 `load_output_schema()`
       都会拿到已被改坏的形态，属**静默降级**（本工程最忌讳的失败形态）。
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ENGINE_UNSUPPORTED_KEYS:
                removed.append(f"{path}.{key}")
                continue
            out[key] = _strip_unsupported(value, removed, f"{path}.{key}")
        return out
    if isinstance(node, list):
        return [
            _strip_unsupported(item, removed, f"{path}[{idx}]")
            for idx, item in enumerate(node)
        ]
    return copy.deepcopy(node)


@lru_cache(maxsize=8)
def _engine_cached(path_str: str) -> tuple[dict, tuple[str, ...]]:
    """引擎形态（剥后 schema ＋ 被剥路径）。缓存键＝文件路径，与契约真值共用同一源。"""
    full = _load_cached(path_str)
    removed: list[str] = []
    stripped = _strip_unsupported(full, removed)
    if not isinstance(stripped, dict):  # pragma: no cover - `_load_cached` 已保证顶层为对象
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "输出契约 schema 顶层应为对象",
            details={"path": path_str},
        )
    if removed:
        # 如实留痕：剥离是可核查的事实，不是静默容忍
        _log.warning(
            "受约束解码 schema 已剥离引擎不支持的关键字（约束改由应用层校验补回）",
            extra={"extra_fields": {"schema_path": path_str, "removed": list(removed)}},
        )
    return stripped, tuple(removed)


def load_engine_schema(stage: str) -> dict | None:
    """取该阶段**发给引擎**的 schema（已剥离 `ENGINE_UNSUPPORTED_KEYS`）。

    返回**副本**：调用方（后端序列化层）原地改动不会污染缓存。

    两类来源（`ISSUE-042` 起，**同一入口**）：
    - **契约文件型**：`shot_prompt` → `CFG-006`（已剥 `uniqueItems`）；
    - **派生型**：`synopsis`／`script`／`storyboard` → `artifact_contract` 按 R5 真值
      现算的 `required` 投影（见该模块 docstring 的设计取舍）。

    ⚠️ 该阶段确无任何形态契约时返回 `None`（＝该层产物不设受约束解码）。
    ⚠️ **不得由调用方自行推断「有没有 schema」** —— 那正是 `ISSUE-042` 的成因形态；
       一律走本函数，并可用 `engine_schema_source()` 取来源用于留痕。
    """
    path = schema_path_for(stage)
    if path is not None:
        schema, _ = _engine_cached(str(path))
        return copy.deepcopy(schema)
    shape = artifact_contract.STAGE_TO_SHAPE.get(stage)
    if shape is None:
        return None
    return artifact_contract.derived_engine_schema(shape)


def engine_schema_source(stage: str) -> str:
    """该阶段引擎 schema 的**来源**（留痕／举证用）：`asset` ／ `derived` ／ `none`。

    存在的理由：`ISSUE-042` 的教训是「**『已约束』与『没约束』在留痕上长得一样**」——
    日志里只有一个布尔 `constrained_decoding`，看不出约束是从哪来的、是否只是巧合。
    把来源显式写进留痕，使「三段何时开始受约束」成为可核查的事实。
    """
    if schema_path_for(stage) is not None:
        return "asset"
    if stage in artifact_contract.STAGE_TO_SHAPE:
        return "derived"
    return "none"


def stripped_paths(stage: str) -> tuple[str, ...]:
    """该阶段 schema 中被剥离的键路径（留痕／举证用；无剥离时为空元组）。"""
    path = schema_path_for(stage)
    if path is None:
        return ()
    _, removed = _engine_cached(str(path))
    return removed
