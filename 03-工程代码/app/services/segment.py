"""分段生成：调用计划、分段产物解析与结构合并。

依据
----
`TPL-009_shot_prompt_v1.yaml` 的 `segment` 变量声明 ＋ `CFG-008_manifest.yaml`
（`shot_prompt_v1` 条目「分段策略」）：

| 取值 | 语义 |
| --- | --- |
| `auto`（**默认**） | 按上游镜数自动决定：**≤6 镜取 `all`**；**>6 镜取 `package_head` ＋ 逐单元** |
| `all` | 强制整包（一次调用产出完整包） |
| `package_head` | 只出头部（`meta` / `style_bible` / `characters` / `props` / `forbidden_items` / `aigc_meta`） |
| `unit:<unit_id>` | 只出该单元与其成员镜 |
| `gap_ledger` | **仅 `revise_v1` 独有**：产出独立缺口台账（**不进交付包**） |

为什么默认不是 `all`
--------------------
14 镜整包约 1.2 万字符，**远超单次生成窗口**，直出必然截断或后半段漂移
（外部评审 `PR-08` 已实测）。故模板把默认值由 `all` 改为 `auto`，
由调用方按 `package_head → unit:U01 → unit:U02 …` 顺序循环。

合并纪律
--------
分段产物**本身不可能单独过交付包 schema**（`required` 六项不齐，见 `CFG-008` 原话），
故本模块只做**结构合并**并**如实登记告警**，**不谎称已过门禁**；
「拼装后能否过 `validate_pack.py`」是交付层的判据，不在本模块职责内。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from app.core.errors import AppError, ErrorCode

#: `auto` 的镜数阈值：不超过此值走整包，超过则分段（依模板声明）。
AUTO_SHOT_THRESHOLD = 6

#: 已知的固定粒度取值。
_FIXED_SEGMENTS = frozenset({"all", "package_head", "gap_ledger"})

#: 交付包顶层必需键（`CFG-006_shot_prompt_pack.v1.schema.json` 的 `required`）。
REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "schema_version",
    "meta",
    "style_bible",
    "units",
    "shots",
    "aigc_meta",
)

#: 只在头部段产出的顶层键（合并时取「首个出现者」）。
HEAD_KEYS: tuple[str, ...] = (
    "schema_version",
    "meta",
    "style_bible",
    "characters",
    "props",
    "forbidden_items",
    "aigc_meta",
)


# --------------------------------------------------------------------- 上游取数
def shot_count_of(storyboard: dict[str, Any] | None) -> int:
    """上游分镜产物的镜数。"""
    if not isinstance(storyboard, dict):
        return 0
    shots = storyboard.get("shots")
    return len(shots) if isinstance(shots, list) else 0


def unit_ids_of(storyboard: dict[str, Any] | None) -> list[str]:
    """上游分镜产物的单元 id 列表（按出现顺序，保持上游次序）。

    缺失 `unit_id` 的单元**不静默跳过**——跳过会导致该单元的分镜无处安放。
    """
    if not isinstance(storyboard, dict):
        return []
    units = storyboard.get("units")
    if not isinstance(units, list):
        return []
    out: list[str] = []
    for idx, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游 units[{idx}] 不是对象，无法解析分段计划",
                details={"index": idx},
            )
        uid = unit.get("unit_id")
        if uid in (None, ""):
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游 units[{idx}] 缺 `unit_id`，无法生成 `unit:<id>` 分段计划",
                details={"index": idx},
            )
        out.append(str(uid))
    return out


# --------------------------------------------------------------------- 计划
def plan_segments(
    segment: str | None,
    *,
    shot_count: int,
    unit_ids: Sequence[str] = (),
) -> list[str]:
    """解析 `segment` 取值 → **调用计划**（每项对应一次生成调用）。

    未知取值或无法执行的组合**一律显式报错**，不猜测、不静默退化。
    """
    value = (segment or "auto").strip() or "auto"

    if value in _FIXED_SEGMENTS:
        # `gap_ledger` 是 `revise_v1` 独有粒度；此处不校验模板归属——
        # 归属校验由模板变量声明承担，避免本模块硬编码模板知识。
        return [value]

    if value.startswith("unit:"):
        uid = value[len("unit:") :].strip()
        if not uid:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "`segment` 取值 `unit:` 后缺单元 id",
                details={"segment": value},
            )
        if unit_ids and uid not in unit_ids:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"`segment` 指定的单元「{uid}」不在上游 units[] 中",
                details={"segment": value, "available_units": list(unit_ids)},
            )
        return [value]

    if value == "auto":
        if shot_count <= AUTO_SHOT_THRESHOLD:
            return ["all"]
        if not unit_ids:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游 {shot_count} 镜超过整包阈值 {AUTO_SHOT_THRESHOLD}，但 units[] 为空——"
                "无法按 `auto` 拆分为 `package_head` ＋ 逐单元",
                details={"shot_count": shot_count, "threshold": AUTO_SHOT_THRESHOLD},
            )
        return ["package_head", *(f"unit:{uid}" for uid in unit_ids)]

    raise AppError(
        ErrorCode.VALIDATION_ERROR,
        f"未知的 `segment` 取值「{value}」",
        details={
            "segment": value,
            "known": sorted(_FIXED_SEGMENTS) + ["auto", "unit:<unit_id>"],
        },
    )


def is_multi_part(plan: Sequence[str]) -> bool:
    """是否属于「需要合并」的多段计划（单段计划直接取用，不必合并）。"""
    return len(plan) > 1


# --------------------------------------------------------------------- 解析
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def parse_json_object(text: str) -> dict[str, Any]:
    """把模型输出解析为 JSON 对象。

    受约束解码（`guided_json` / `response_format`）下应为**裸 JSON**；
    但 `off` 模式或模型偶发围栏时须容忍 ``` 围栏与前后缀说明文字。

    仍无法解析时抛 `GENERATION_FAILED`——**宁可报错，也不静默产出空对象**。
    """
    if not isinstance(text, str) or not text.strip():
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "分段产物为空，无法解析为 JSON 对象",
        )
    candidate = _FENCE.sub("", text.strip()).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # 兜底：截取首个 `{` 到末个 `}`（容忍模型在 JSON 前后加说明文字）
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    "分段产物不是合法 JSON，无法解析",
                    details={"reason": exc.msg, "position": exc.pos, "prefix": candidate[:120]},
                ) from exc
        else:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                "分段产物中找不到 JSON 对象",
                details={"prefix": candidate[:120]},
            ) from None
    if not isinstance(parsed, dict):
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            f"分段产物 JSON 顶层不是对象（实际为 {type(parsed).__name__}）",
        )
    return parsed


# --------------------------------------------------------------------- 合并
def _natkey(text: Any) -> list[tuple[int, Any]]:
    """自然序键（`U02` 排在 `U10` 之前）。元素统一为定长元组，可安全比较。"""
    return [
        (0, int(token)) if token.isdigit() else (1, token)
        for token in re.split(r"(\d+)", str(text))
    ]


def _int_or(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unit_sort_key(unit: dict[str, Any]) -> list[tuple[int, Any]]:
    return _natkey(unit.get("unit_id", ""))


def _shot_sort_key(shot: dict[str, Any]) -> tuple[int, int, list[tuple[int, Any]]]:
    """交付规范 §3.7 镜序：`scene_no` → `shot_no` 升序，再以 `shot_id` 稳定。"""
    return (
        _int_or(shot.get("scene_no")),
        _int_or(shot.get("shot_no")),
        _natkey(shot.get("shot_id", "")),
    )


def merge_segments(parts: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """把分段产物按结构合并为一个交付包。

    规则
    ----
    - 顶层**头部键**取**首个出现者**（同键不同值时保留先出现者并告警）；
    - `units[]` / `shots[]` 按 `unit_id` / `shot_id` **拼接去重**，
      并按上游次序（单元）与镜序（分镜）**重排**；
    - **不补齐、不编造**任何字段——缺失的必需键只记告警，
      由交付层的 `validate_pack.py` 裁决。

    返回 `(合并结果, 告警列表)`。**告警是留痕，不是静默容忍**。
    """
    warnings: list[str] = []
    merged: dict[str, Any] = {}
    unit_map: dict[str, dict[str, Any]] = {}
    shot_map: dict[str, dict[str, Any]] = {}

    for idx, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            warnings.append(f"第 {idx} 段不是 JSON 对象，已跳过（实际 {type(part).__name__}）")
            continue

        for key in HEAD_KEYS:
            if key not in part:
                continue
            if key not in merged:
                merged[key] = part[key]
            elif merged[key] != part[key]:
                warnings.append(
                    f"头部字段「{key}」在第 {idx} 段取值与先前不同——保留先出现者（先到先得）"
                )

        for unit in part.get("units") or []:
            if not isinstance(unit, dict) or unit.get("unit_id") in (None, ""):
                warnings.append(f"第 {idx} 段含缺 `unit_id` 的单元项，已跳过")
                continue
            uid = str(unit["unit_id"])
            if uid in unit_map and unit_map[uid] != unit:
                warnings.append(f"单元「{uid}」在第 {idx} 段重复且内容不同——保留先出现者")
                continue
            unit_map.setdefault(uid, unit)

        for shot in part.get("shots") or []:
            if not isinstance(shot, dict) or shot.get("shot_id") in (None, ""):
                warnings.append(f"第 {idx} 段含缺 `shot_id` 的分镜项，已跳过")
                continue
            sid = str(shot["shot_id"])
            if sid in shot_map and shot_map[sid] != shot:
                warnings.append(f"分镜「{sid}」在第 {idx} 段重复且内容不同——保留先出现者")
                continue
            shot_map.setdefault(sid, shot)

    merged["units"] = sorted(unit_map.values(), key=_unit_sort_key)
    merged["shots"] = sorted(shot_map.values(), key=_shot_sort_key)

    missing = [k for k in REQUIRED_TOP_KEYS if k not in merged]
    if missing:
        warnings.append(
            "合并后缺顶层必需键：" + "、".join(missing) + "——须由完整包补齐，本节不作裁决"
        )
    return merged, warnings
