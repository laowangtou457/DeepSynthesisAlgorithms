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

#: **storyboard 形态**的头部键（`T-100` 逐场编排；与包形态的 `HEAD_KEYS` **不同一套**）。
#:
#: ⚠️ **必须分开的理由**（`PRO-014` §2.3，施工前实测）：storyboard 的顶层是
#: `title`/`genre`/`style_ref`/`aspect_ratio_default`/`total_duration_ms`/`units`/`shots`/
#: `forbidden_items`/`unspecified`/`quality_gate`（`artifact_contract.REQUIRED_TOP_KEYS["storyboard"]`）。
#: 若逐场产物直接走 `merge_segments`（包的 `HEAD_KEYS`）⇒ `title`/`genre`/`style_ref`/
#: `aspect_ratio_default` **会整体丢失**，合并结果随即过不了 `required` 投影。
#:
#: `total_duration_ms` **刻意不在表内**：各场产物自带的是「本场之和」，合并后必须由
#: `R14` 回填按合并产物的 Σ 重算（`dialogue_service._backfill_total_sum`）。
HEAD_KEYS_STORYBOARD: tuple[str, ...] = (
    "title",
    "genre",
    "style_ref",
    "aspect_ratio_default",
    "forbidden_items",
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


# ------------------------------------------------------- 逐场编排（`T-100`／`PRO-014`）
def scene_nos_of(script: dict[str, Any] | None) -> list[int]:
    """上游剧本的**场号清单**（按 `acts[]` 出现顺序、场内按 `no` 升序）。

    ⚠️ 异常一律**显式报错、不猜测**：场号缺失／非整数／重复 ⇒ 逐场编排无从保证
    「每场一次调用」，静默跳过会导致该场**无人负责**（正是 `PRO-014` 要消灭的漏场形态）。
    """
    if not isinstance(script, dict):
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "上游剧本不是对象，无法推导逐场调用计划",
        )
    acts = script.get("acts")
    if not isinstance(acts, list) or not acts:
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "上游剧本缺 `acts[]`（或为空），无法推导逐场调用计划",
            details={"acts_type": type(acts).__name__},
        )
    nos: list[int] = []
    for ai, act in enumerate(acts):
        if not isinstance(act, dict):
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游剧本 acts[{ai}] 不是对象，无法推导逐场调用计划",
                details={"index": ai},
            )
        scenes = act.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise AppError(
                ErrorCode.GENERATION_FAILED,
                f"上游剧本 acts[{ai}] 缺 `scenes[]`（或为空），无法推导逐场调用计划",
                details={"act_index": ai},
            )
        for si, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"上游剧本 acts[{ai}].scenes[{si}] 不是对象，无法推导逐场调用计划",
                    details={"act_index": ai, "scene_index": si},
                )
            no = scene.get("no")
            if not isinstance(no, int) or isinstance(no, bool):
                raise AppError(
                    ErrorCode.GENERATION_FAILED,
                    f"上游剧本 acts[{ai}].scenes[{si}] 的 `no` 不是整数，无法推导逐场调用计划",
                    details={"act_index": ai, "scene_index": si, "no": no},
                )
            nos.append(no)
    dup = sorted({n for n in nos if nos.count(n) > 1})
    if dup:
        raise AppError(
            ErrorCode.GENERATION_FAILED,
            "上游剧本场号重复（" + "、".join(str(n) for n in dup) + "），无法推导逐场调用计划",
            details={"scene_nos": nos, "duplicated": dup},
        )
    return nos


def scene_by_no(script: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """场号 → 该场对象（**保持原样，不裁剪、不改写**；变量注入时整份交给模型）。"""
    if not isinstance(script, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for act in script.get("acts") or []:
        if not isinstance(act, dict):
            continue
        for scene in act.get("scenes") or []:
            if isinstance(scene, dict) and isinstance(scene.get("no"), int):
                out[int(scene["no"])] = scene
    return out


def plan_scene_segments(script: dict[str, Any] | None) -> list[str]:
    """逐场编排的**调用计划**：`["scene:1", "scene:2", …]`（场号升序）。"""
    return [f"scene:{n}" for n in sorted(scene_nos_of(script))]


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

        # ---- `丙`（2026-11-07 裁决）：段内 shot_id 重复＝「凑数形态」检出 ----
        # `uniqueItems` 不在引擎允许面 ⇒ 模型可用「重复同一条目」凑 `minItems` 下限
        # （复验批 `ab_t101_r2` run6/run10 实证：U01 段重复 `S01-SH002` 凑满 3，
        # 合并去重后终态 2 镜失守）。段内重复**从来不是合法产物**（交付规范 shot_id
        # 全包唯一）⇒ 显式检出、留机器可读码，由服务层转成可重试失败（见
        # `dialogue_service` 门禁判定后的注入），替代「静默 setdefault 丢镜」。
        part_shot_ids: list[str] = []
        for shot in part.get("shots") or []:
            if not isinstance(shot, dict) or shot.get("shot_id") in (None, ""):
                warnings.append(f"第 {idx} 段含缺 `shot_id` 的分镜项，已跳过")
                continue
            sid = str(shot["shot_id"])
            part_shot_ids.append(sid)
            if sid in shot_map and shot_map[sid] != shot:
                warnings.append(f"分镜「{sid}」在第 {idx} 段重复且内容不同——保留先出现者")
                continue
            shot_map.setdefault(sid, shot)
        for sid in sorted({s for s in part_shot_ids if part_shot_ids.count(s) > 1}):
            warnings.append(
                f"merge.shot_dup_in_segment｜分镜「{sid}」在第 {idx} 段内重复出现 "
                f"{part_shot_ids.count(sid)} 次（同一 shot_id 单段内重复＝凑数形态）"
                "——已保留先到者，重试时必须为每个 shot_id 写不同镜头"
            )

    merged["units"] = sorted(unit_map.values(), key=_unit_sort_key)
    merged["shots"] = sorted(shot_map.values(), key=_shot_sort_key)

    missing = [k for k in REQUIRED_TOP_KEYS if k not in merged]
    if missing:
        warnings.append(
            "合并后缺顶层必需键：" + "、".join(missing) + "——须由完整包补齐，本节不作裁决"
        )
    return merged, warnings


def merge_storyboard_parts(
    parts: Sequence[dict[str, Any]],
    *,
    upstream: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """逐场产物（storyboard 形态）→ 合并后的分镜脚本（`T-100`／`PRO-014` §3.4）。

    与 `merge_segments` 的**四处刻意不同**（每一处都对应一种真失败形态）：

    1. **头部键换表**（`HEAD_KEYS_STORYBOARD`）——包的 `HEAD_KEYS` 不含
       `title`/`genre`/`style_ref`/`aspect_ratio_default`，直接复用会整体丢键；
    2. `total_duration_ms` **不合并**（丢弃）——各场自带的是「本场之和」，合并后由
       `R14` 回填按 `Σ duration_ms` 重算；
    3. `units[]`/`shots[]` **追加、不排序、不去重**——顺序由**调用计划**保证
       （`plan_scene_segments` 按场号升序，各场内保持模型数组序）。⚠️ 若在此按
       `shot_no` 排序，会把「单元内编号 `[1,1,2,2]`」的数组序打乱，进而破坏
       `R8` 派生回填所依赖的「数组序＝镜序」前提；
    4. **重号不静默**——同一 `scene_no` 出现在两段以上、或 `shot_id`/`unit_id` 重复，
       一律**显式告警**并**保留全部条目**（交 `R41`/`R42`/`R7`/`R9` 判）。
       `merge_segments` 的 `setdefault` 语义会静默丢弃后到者，而「哪些被丢」取决于
       遍历顺序——正是本工程最要防的「看起来完整、实则无据」。

    ⚠️ 本函数**不判合规**：合并结果能否过 `required` 投影／形态闸，是
    `dialogue_service._guard_artifact_shape` 与交付层的职责，此处只做结构合并与留痕。

    参数 `upstream`（2026-11-05 新增，`ISSUE-062` 裁决 5）
    ----------------------------------------------------
    传入**上游剧本层产物**时，对 `unspecified` 中「继承项」（`upstream_field` 非空）做
    **`fill_stage` 锁回上游层**：上游确为 `script` 的，把本层改写的值改回 `script`
    并留痕「改过／未改」。

    为什么必须在合并侧做（而不是靠判据）：`R21` 只**报告**违规，模型看不到上游那条
    条目的 `fill_stage`（逐场输入的 `unspecified` 是本场要输出的候选、不是上游台账）
    ⇒ 「模型不知道该值是继承来的」⇒ 判据写多少遍都改不动。实测 `T-100` `b` 期
    `R21` **1/12→5/12**。这与 `R14`/`R8`/`R24` 同族：**把约束从模型移到程序**。
    ⚠️ 只在**上游真值确为 `script`** 时改写（不覆盖上游自身的可疑值），
    且**不改** `owner`/`field`/`reason`/`blocking`——只动 `fill_stage` 一个键。
    """
    warnings: list[str] = []
    merged: dict[str, Any] = {}
    units_out: list[dict[str, Any]] = []
    shots_out: list[dict[str, Any]] = []
    unspecified_out: list[dict[str, Any]] = []
    seen_unspec: set[tuple[str, str]] = set()
    self_checks: list[str] = []
    scene_owner: dict[Any, int] = {}
    dupe_scene: set[Any] = set()

    for idx, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            warnings.append(f"第 {idx} 段不是 JSON 对象，已跳过（实际 {type(part).__name__}）")
            continue

        for key in HEAD_KEYS_STORYBOARD:
            if key not in part:
                continue
            if key not in merged:
                merged[key] = part[key]
            elif merged[key] != part[key]:
                warnings.append(
                    f"头部字段「{key}」在第 {idx} 段取值与先前不同——保留先出现者（先到先得）"
                )

        gate = part.get("quality_gate")
        if isinstance(gate, dict):
            check = gate.get("self_check")
            if isinstance(check, str) and check.strip():
                self_checks.append(check.strip())

        for item in part.get("unspecified") or []:
            if not isinstance(item, dict):
                warnings.append(f"第 {idx} 段的 unspecified 含非对象项，已跳过")
                continue
            key = (str(item.get("field")), str(item.get("reason")))
            if key in seen_unspec:
                continue
            seen_unspec.add(key)
            unspecified_out.append(item)

        for unit in part.get("units") or []:
            if not isinstance(unit, dict) or unit.get("unit_id") in (None, ""):
                warnings.append(f"第 {idx} 段含缺 `unit_id` 的单元项，已保留但不可链接")
                if isinstance(unit, dict):
                    units_out.append(unit)
                continue
            units_out.append(unit)
            nos = [unit.get("scene_no")] if unit.get("scene_no") is not None else []
            for no in nos:
                if no in scene_owner and scene_owner[no] != idx:
                    dupe_scene.add(no)
                scene_owner.setdefault(no, idx)

        for shot in part.get("shots") or []:
            if not isinstance(shot, dict):
                warnings.append(f"第 {idx} 段含非对象分镜项，已跳过")
                continue
            shots_out.append(shot)
            no = shot.get("scene_no")
            if no is not None:
                if no in scene_owner and scene_owner[no] != idx:
                    dupe_scene.add(no)
                scene_owner.setdefault(no, idx)

    if dupe_scene:
        warnings.append(
            "场号重复出现于多段（"
            + "、".join(str(n) for n in sorted(dupe_scene, key=str))
            + "）——模型越界写了别的场；条目全部保留，交 R41／R42／R10 判"
        )
    shot_ids = [str(s.get("shot_id")) for s in shots_out if s.get("shot_id") not in (None, "")]
    dup_shots = sorted({x for x in shot_ids if shot_ids.count(x) > 1})
    if dup_shots:
        warnings.append(
            "shot_id 重复（" + "、".join(dup_shots[:5]) + "）——未做去重，交 R7 判"
        )
    unit_ids = [str(u.get("unit_id")) for u in units_out if u.get("unit_id") not in (None, "")]
    dup_units = sorted({x for x in unit_ids if unit_ids.count(x) > 1})
    if dup_units:
        warnings.append(
            "unit_id 重复（" + "、".join(dup_units[:5]) + "）——未做去重，交 R9 判"
        )

    merged["units"] = units_out
    merged["shots"] = shots_out
    merged["unspecified"] = unspecified_out
    merged["quality_gate"] = (
        {"self_check": "；".join(dict.fromkeys(self_checks))} if self_checks else {}
    )
    if len(set(self_checks)) > 1:
        warnings.append("多段 self_check 不一致——已按段序拼接，仅留痕不裁决")

    # ---- `ISSUE-062`：继承项 `fill_stage` 锁回上游层（裁决 5）----
    locked, untracked = lock_inherited_fill_stage(unspecified_out, upstream)
    if locked:
        warnings.append(
            "unspecified 继承项 fill_stage 锁回上游层："
            + "；".join(f"{f}（『{old}』→『script』）" for f, old in locked)
            + "——继承项的追问阶段由剧本层定，本层不得改写（R21 语义）"
        )
    if untracked:
        warnings.append(
            "unspecified 继承项在上游台账中查无对应条目（未改写，留痕）："
            + "、".join(untracked[:5])
        )
    return merged, warnings


def lock_inherited_fill_stage(
    items: list[dict[str, Any]],
    upstream: dict[str, Any] | None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """把 `unspecified` 中**继承项**的 `fill_stage` 锁回上游层（`ISSUE-062` 裁决 5）。

    判定口径（与 `validate_output.rule_unspecified_owner` 的 storyboard 分支逐条对齐）：

    - 只看 `upstream_field` 非空者（＝继承项；空者属本层新增，`fill_stage` 由本层定）；
    - 上游确实存在同 `field` 且 `fill_stage == "script"` 的条目 ⇒ 本层值不为 `script`
      时改回 `script`，并在返回值里留「改过」痕迹；
    - 上游查无对应条目 ⇒ **不改写**，只登记 `untracked`（「看起来继承、实则无据」，
      交由 `R21` 照常判 —— 不得用机械改写掩盖上游缺口）；
    - 上游该条 `fill_stage` 本身不是 `script` ⇒ 不改写（不覆盖上游可疑值）。

    返回 `(改过的 [(field, 原值)...], 查无对应的 [field...])`；两表都为空＝无需留痕。
    """
    changed: list[tuple[str, str]] = []
    untracked: list[str] = []
    if not isinstance(upstream, dict):
        return changed, untracked
    upstream_stage: dict[str, Any] = {}
    for it in upstream.get("unspecified") or []:
        if isinstance(it, dict):
            f = str(it.get("field") or "").strip()
            if f and f not in upstream_stage:
                upstream_stage[f] = it.get("fill_stage")
    for it in items:
        if not isinstance(it, dict):
            continue
        field = str(it.get("field") or "").strip()
        inherited = str(it.get("upstream_field") or "").strip()
        if not inherited:
            continue
        if field not in upstream_stage:
            untracked.append(field or inherited)
            continue
        if upstream_stage[field] != "script":
            continue
        if it.get("fill_stage") != "script":
            changed.append((field or inherited, str(it.get("fill_stage"))))
            it["fill_stage"] = "script"
    return changed, untracked


# ------------------------------------------------- 段级输入裁剪（`T-101`／`PRO-015`）
def scope_storyboard_for_segment(
    seg: str,
    storyboard: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """按段构造 `storyboard_json` 的**裁剪副本**（`T-101`／`PRO-015` §3.1①）。

    规则
    ----
    - `package_head`：头部键全保留＋`units[]` 全量＋`unspecified` 全量，
      **`shots[]` 置空**（头部段不产镜；镜明细是上游里最大的体积块）；
    - `unit:<id>`：头部键全保留＋**只该单元**＋**只该单元的镜**
      （按 `shots[].unit_id == uid` 与 `units[].shot_ids` 的**并集**过滤；
      `unspecified` 全量保留）；
    - 其余段名（`all` 等）⇒ **返回 `None`（不裁剪）**；
    - `unit:<id>` 在 `units[]` 中找不到 ⇒ **返回 `None` 并告警**——
      宁可用整份让模型照单全收，也不喂一份「抽掉证据的输入」
      （与 `scene:` 段解析失败回退整片的纪律同源：不猜测、不静默）。

    ⚠️ 本函数**只切片、不改写**任何字段值（与「服务层不改写模型真值域」同一纪律；
    这里是把上游读给模型的**范围**收窄，内容逐字不变）。
    返回 `(scoped | None, warnings)`：`None` 表示调用方应注入整份原文。
    """
    warnings: list[str] = []
    if seg not in ("package_head",) and not seg.startswith("unit:"):
        return None, warnings
    if not isinstance(storyboard, dict):
        return None, ["上游分镜不是对象，无法按段裁剪——回退整份注入"]

    scoped: dict[str, Any] = {}
    for key in HEAD_KEYS_STORYBOARD:
        if key in storyboard:
            scoped[key] = storyboard[key]
    if isinstance(storyboard.get("total_duration_ms"), (int, float)):
        scoped["total_duration_ms"] = storyboard["total_duration_ms"]
    if isinstance(storyboard.get("unspecified"), list):
        scoped["unspecified"] = storyboard["unspecified"]
    if isinstance(storyboard.get("quality_gate"), dict):
        scoped["quality_gate"] = storyboard["quality_gate"]

    units = storyboard.get("units")
    units = units if isinstance(units, list) else []
    shots = storyboard.get("shots")
    shots = shots if isinstance(shots, list) else []

    if seg == "package_head":
        scoped["units"] = units
        scoped["shots"] = []
        return scoped, warnings

    uid = seg.split(":", 1)[1].strip()
    mine = [u for u in units if isinstance(u, dict) and str(u.get("unit_id")) == uid]
    if not mine:
        return None, [f"裁剪目标单元「{uid}」不在上游 units[] 中——回退整份注入（不猜测）"]
    wanted_ids = {
        str(sid)
        for u in mine
        for sid in (u.get("shot_ids") or [])
        if sid not in (None, "")
    }
    mine_shots = [
        s
        for s in shots
        if isinstance(s, dict)
        and (str(s.get("unit_id")) == uid or str(s.get("shot_id")) in wanted_ids)
    ]
    if wanted_ids and len(mine_shots) < len(wanted_ids):
        got = {str(s.get("shot_id")) for s in mine_shots}
        missing = sorted(wanted_ids - got)
        warnings.append(
            "单元「" + uid + "」声明的镜在上游 shots[] 中缺 " + str(len(missing)) + " 条（"
            + "、".join(missing[:5]) + "）——按并集如实收窄，缺项交 R9／R41 判"
        )
    scoped["units"] = mine
    scoped["shots"] = mine_shots
    return scoped, warnings

