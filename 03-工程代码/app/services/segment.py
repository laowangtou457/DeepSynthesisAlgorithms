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
def unit_shot_counts_of(storyboard: dict[str, Any] | None) -> list[int]:
    """上游分镜产物**逐单元镜数**（与 `unit_ids_of()` 同序对齐）。

    `丙`（2026-11-17，分段最小镜数）：组段需要「每单元几镜」才能把相邻单元攒到
    ≥ N 镜。取数口径＝**声明与实测必须逐单元相等**；任一单元 `shot_ids` 声明长度与
    `shots[]` 实测归属不一致 ⇒ 返回 `[]`（调用方退回逐单元）。
    ⚠️ 早期版本取两者**较大者**，被独立 QA 证伪：声明大于实测时组段按「声明」判定
    ≥N，而 schema 的 `shots_floor` 只能按「实测」设 ⇒ 2 镜小段原地复活（`[2,2]` 声明、
    `[1,1]` 实测时组段只有 2 镜可分配）。**一处组段、一处压 floor，两头必须同源**。
    ⚠️ 无法判定时返回 `[]`（与 `unit_ids` 不对齐）⇒ 放弃组段，不猜测。
    """
    if not isinstance(storyboard, dict):
        return []
    units = storyboard.get("units")
    shots = storyboard.get("shots")
    if not isinstance(units, list) or not isinstance(shots, list):
        return []
    by_unit: dict[str, int] = {}
    for s in shots:
        if isinstance(s, dict) and s.get("unit_id") not in (None, ""):
            uid = str(s["unit_id"])
            by_unit[uid] = by_unit.get(uid, 0) + 1
    pairs: list[tuple[int, int]] = []
    for unit in units:
        if not isinstance(unit, dict):
            return []
        uid = unit.get("unit_id")
        if uid in (None, ""):
            return []
        declared = unit.get("shot_ids")
        declared_n = len(declared) if isinstance(declared, list) else 0
        pairs.append((declared_n, by_unit.get(str(uid), 0)))
    if pairs and all(d == 0 for d, _ in pairs) and all(a > 0 for _, a in pairs):
        # 上游整体只靠 `shots[].unit_id` 归属（`units[].shot_ids` 未填）⇒ 按实测计，
        # 不与 `shots_floor`（也按实测）冲突。
        counts = [a for _, a in pairs]
    elif any(d != a for d, a in pairs):
        # 逐单元声明≠实测 ⇒ 放弃组段（口径必须与 schema `shots_floor` 同源）
        return []
    else:
        counts = [d for d, _ in pairs]
    if any(n < 2 or n > 3 for n in counts):
        # `TPL-008` BR-11：单元镜数 ∈[2,3]。出现 1 镜／≥4 镜单元（脏上游或上游 `R10`
        # 失守）时**不组段**——组段要求「这几个单元都被写全」，而 1 镜单元本身不满足
        # `unit.shot_ids` 的 2–3 下限 ⇒ 语义无解（独立 QA 复验条件①）。
        return []
    return counts


def segment_unit_ids(seg: str) -> list[str]:
    """`unit:U01` / `unit:U01+U02` → `["U01", "U02"]`；非 `unit:` 段返回 `[]`。

    `丙` 起段名可为**多单元组**（`+` 连接，顺序即上游单元序）。解析失败（空 id）时
    返回 `[]`——调用方按「非单元段」处理，不得静默当成单单元。
    """
    if not isinstance(seg, str) or not seg.startswith("unit:"):
        return []
    body = seg.split(":", 1)[1]
    uids = [p.strip() for p in body.split("+")]
    if not uids or any(not u for u in uids):
        return []
    return uids


def group_units_by_min_shots(
    unit_ids: Sequence[str],
    unit_shot_counts: Sequence[int],
    min_shots: int,
) -> list[list[str]]:
    """`丙`：把相邻单元攒成**每段 ≥ `min_shots` 镜**的组（单元不拆、不跨单元重排）。

    - `min_shots < 2` ⇒ 逐单元分组（与旧行为等价，调用方也可直接不用本函数）；
    - 数与 `unit_ids` 不对齐 / 含非正数 ⇒ 逐单元分组（**不猜**，宁可不组）；
    - **末组余数并入上一组**：余数组 `< min_shots` 时并进前一组（否则「2 镜小段」这一
      最严形态会在片尾复现，正好是本法要消灭的对象）；只有一组时如实保留原样；
    - **并入上限**（2026-11-18 项目方裁决⑤「倾向放宽、先实测 7 镜组」）：上限从固定
      `2×min_shots` 放宽为 **`2×min_shots − 2 + max(unit_shot_counts)`** —— 这是
      「贪心攒组＋末组并入」的**可达理论上界**（min=3、单元 ∈[2,3] 时＝7：前组最大
      `min−1+max_unit=5`，末组最大 `min−1=2`）。固定 `2×min=6` 会把 `[2,3,2]` 这类
      输入卡成 7>6 而留下 2 镜小段；放宽后 **7 镜组是封闭上界、不会无限增长**（`min`
      已被 `_segment_plan` 收窄到 0~3）。9 镜组（QA 首轮的 `[3,3,3] min=4` 例）在
      `min ≤ 3` 下不可达。
    """
    if min_shots < 2 or len(unit_ids) != len(unit_shot_counts):
        return [[uid] for uid in unit_ids]
    if any(not isinstance(n, int) or n <= 0 for n in unit_shot_counts):
        return [[uid] for uid in unit_ids]
    groups: list[list[str]] = []
    sums: list[int] = []
    cur: list[str] = []
    acc = 0
    for uid, n in zip(unit_ids, unit_shot_counts):
        cur.append(uid)
        acc += n
        if acc >= min_shots:
            groups.append(cur)
            sums.append(acc)
            cur, acc = [], 0
    if cur:
        groups.append(cur)
        sums.append(acc)
    # 末组余数并入上一组（避免片尾复现「< min_shots 的小段」；只有一组则保留原样）
    # ⚠️ 体积上限（2026-11-18 裁决⑤放宽）：并入后不得超过 `2×min − 2 + max_unit`
    # ——贪心攒组＋末组并入的可达理论上界（min=3、单元 ∈[2,3] 时＝7）。超过则
    # **保留原样**（宁可留一个诚实的小段，也不把单次调用推到无界）。
    if len(groups) >= 2 and sums[-1] < min_shots:
        cap = 2 * min_shots - 2 + max(unit_shot_counts)
        if sums[-2] + sums[-1] <= cap:
            groups[-2].extend(groups.pop())
    return groups


def plan_segments(
    segment: str | None,
    *,
    shot_count: int,
    unit_ids: Sequence[str] = (),
    min_shots: int = 0,
    unit_shot_counts: Sequence[int] = (),
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
        uids = segment_unit_ids(value)
        if not uids:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "`segment` 取值 `unit:` 后缺单元 id",
                details={"segment": value},
            )
        if unit_ids:
            unknown = [u for u in uids if u not in unit_ids]
            if unknown:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"`segment` 指定的单元「{'、'.join(unknown)}」不在上游 units[] 中",
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
        # `丙`（2026-11-17）：分段最小镜数。`min_shots>=2` 时把相邻单元攒成
        # ≥ min_shots 镜的组（段名 `unit:U01+U02`），消灭「2 镜单元单独成段」这一最严
        # 形态（单元 need=2 且只有 2 镜 ⇒ 强制全异；见 `DEV-20261117-003`／`-004`）。
        groups = group_units_by_min_shots(unit_ids, unit_shot_counts, min_shots)
        return [
            "package_head",
            *(f"unit:{'+'.join(g)}" for g in groups),
        ]

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
def _scan_script_structure(script: Any) -> tuple[list[tuple[str, dict[str, Any]]], list[int]]:
    """剧本 `acts[]`／`scenes[]` 的**元素级结构扫描**（`ISSUE-094` 的单点实现）。

    ⚠️ **唯一口径**（本工程明令禁止第二份）：本函数是「剧本结构缺陷」的**唯一**判定处，
    两个调用方各自取用自己需要的那一半：

    | 调用方 | 取用 | 性质 |
    | --- | --- | --- |
    | `` scene_nos_of() `` | 抛错（取**第一条**问题） | 下游使用前 fail-fast（`GENERATION_FAILED`） |
    | `` artifact_contract.check_shape() `` | 返回 verdict（取**第一条**问题＋条数） | 生成后形态闸（`script_structure_invalid`） |

    为什么必须是同一个函数：缺陷（`ISSUE-094`）的现场正是「**两处判定口径打架**」——
    形态闸只判顶层形态（可解析／形态相符／必需键齐备），逐场编排却在**元素级**上判定
    ⇒ `acts[2]` 是字符串时，闸门放行、下游 `plan_scene_segments` 才炸（`502`）。
    前移的唯一安全做法是**把下游那把尺子原样搬到上游**，而不是在上游另写一把。

    返回 ``(问题清单, 已是合法场号的清单)``：

    - 问题清单**不抛错**（判定与裁决分离，同 `artifact_contract` 的分层纪律）；
      每条为 ``(人类可读文案, details)``，**文案与 details 与改造前的逐条 `AppError` 完全一致**
      （文案守恒：外部可见的报错文本一字未变）；
    - 场号清单只在**无问题**时有意义（有问题时是「扫到一半」的残值，调用方不得使用）。

    ⚠️ 场号重复只在**其余全合法**时才统计（与改造前语义一致：先逐元素判定、后查重）。
    """
    if not isinstance(script, dict):
        return [("上游剧本不是对象，无法推导逐场调用计划", {})], []
    acts = script.get("acts")
    if not isinstance(acts, list) or not acts:
        return [
            (
                "上游剧本缺 `acts[]`（或为空），无法推导逐场调用计划",
                {"acts_type": type(acts).__name__},
            )
        ], []

    problems: list[tuple[str, dict[str, Any]]] = []
    nos: list[int] = []
    for ai, act in enumerate(acts):
        if not isinstance(act, dict):
            problems.append(
                (f"上游剧本 acts[{ai}] 不是对象，无法推导逐场调用计划", {"index": ai})
            )
            continue
        scenes = act.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            problems.append(
                (
                    f"上游剧本 acts[{ai}] 缺 `scenes[]`（或为空），无法推导逐场调用计划",
                    {"act_index": ai},
                )
            )
            continue
        for si, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                problems.append(
                    (
                        f"上游剧本 acts[{ai}].scenes[{si}] 不是对象，无法推导逐场调用计划",
                        {"act_index": ai, "scene_index": si},
                    )
                )
                continue
            no = scene.get("no")
            if not isinstance(no, int) or isinstance(no, bool):
                problems.append(
                    (
                        f"上游剧本 acts[{ai}].scenes[{si}] 的 `no` 不是整数，"
                        "无法推导逐场调用计划",
                        {"act_index": ai, "scene_index": si, "no": no},
                    )
                )
                continue
            nos.append(no)

    if problems:
        return problems, nos
    dup = sorted({n for n in nos if nos.count(n) > 1})
    if dup:
        problems.append(
            (
                "上游剧本场号重复（" + "、".join(str(n) for n in dup) + "），"
                "无法推导逐场调用计划",
                {"scene_nos": nos, "duplicated": dup},
            )
        )
    return problems, nos


def script_structure_problems(script: Any) -> list[tuple[str, dict[str, Any]]]:
    """剧本 `acts[]`／`scenes[]` 的**结构缺陷清单**（不抛错；`ISSUE-094` 的单点判定）。

    覆盖的缺陷面（逐条与 `` scene_nos_of() `` 改造前抛出的错误**文案／details 逐字一致**）：

    | # | 缺陷 | details |
    | --- | --- | --- |
    | 1 | 剧本不是对象 | `{}` |
    | 2 | 缺 `acts[]`（或为空） | `acts_type` |
    | 3 | `acts[ai]` 不是对象 | `index` |
    | 4 | `acts[ai]` 缺 `scenes[]`（或为空） | `act_index` |
    | 5 | `acts[ai].scenes[si]` 不是对象 | `act_index`、`scene_index` |
    | 6 | `scenes[si].no` 不是整数 | `act_index`、`scene_index`、`no` |
    | 7 | 场号重复 | `scene_nos`、`duplicated` |

    ⚠️ **不抛错、不改写**：本函数只描述事实（同 `SafetyService`「服务层只判定、
    编排层阻断」的分层纪律）；是否阻断、以什么错误码阻断由调用方裁决。
    """
    return _scan_script_structure(script)[0]


def scene_nos_of(script: dict[str, Any] | None) -> list[int]:
    """上游剧本的**场号清单**（按 `acts[]` 出现顺序、场内按 `no` 升序）。

    ⚠️ 异常一律**显式报错、不猜测**：场号缺失／非整数／重复 ⇒ 逐场编排无从保证
    「每场一次调用」，静默跳过会导致该场**无人负责**（正是 `PRO-014` 要消灭的漏场形态）。

    ⚠️ **判定不在此处实现**（`ISSUE-094`）：结构缺陷的唯一口径是
    `` script_structure_problems() ``；本函数只负责「有问题 ⇒ 用**第一条**问题抛错」，
    即改造前的行为与文案一字不变（现有测试 `app/tests/test_segment.py`／
    `test_scene_orchestration.py` 未改动）。
    """
    problems, nos = _scan_script_structure(script)
    if problems:
        message, details = problems[0]
        raise AppError(ErrorCode.GENERATION_FAILED, message, details=details)
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


# ------------------------------------------------- script 逐场拆段（`T-116`）
#: `script` 段 `package_head`（头部）段的**顶层键集**。
#: ⚠️ 这**不是契约真值**——契约真值仍是 `` REQUIRED_TOP_KEYS["script"] ``（唯一口径）；
#:    段级键集只约束「这一段调用要出什么」，合并后的完整产物仍按全量契约判定
#:    （与 `cap_pack_array_bounds`「解码约束不是判据第二份」同性质）。
SCRIPT_HEAD_TOP_KEYS: tuple[str, ...] = (
    "title",
    "logline",
    "genre",
    "style_bible",
    "characters",
    "props",
    "acts",
    "unspecified",
)

#: 单场段（`scene:<no>`）的**场对象键集**。`act_no` 刻意不在内：
#: 幕归属由 head 段的 acts 骨架**一次定义**（场段无此键 ⇒ 跨段归属不一致在
#: 结构上不可能发生——「把约束从模型移到程序」同族纪律）。
SCRIPT_SCENE_KEYS: tuple[str, ...] = (
    "no",
    "slug",
    "location",
    "time_of_day",
    "present",
    "props_present",
    "action",
    "sfx_hint",
    "dialogue",
    "beat",
    "purpose",
    "est_seconds",
)

#: 场对象中**必须是数组**的键（段级 schema 钉类型，防模型把数组写成标量）。
_SCRIPT_SCENE_ARRAY_KEYS = ("present", "props_present", "sfx_hint", "dialogue")


def synopsis_scene_nos(synopsis: dict[str, Any] | None) -> list[int]:
    """梗概 `` scenes_outline `` 的**场号清单**（升序）。

    与 `` scene_nos_of() ``（剧本侧，fail-fast 抛错）**刻意不同**：梗概侧不抛错——
    场号异常（缺失／重复／非正整数）时逐场拆段无从保证「每场一次调用」，
    返回空清单由调用方**降级整段＋留痕**（同 storyboard 的上游不可解析口径；
    形态闸生效时该分支不可达——上游准入闸已先阻断）。
    """
    if not isinstance(synopsis, dict):
        return []
    outline = synopsis.get("scenes_outline")
    if not isinstance(outline, list) or not outline:
        return []
    nos: list[int] = []
    for item in outline:
        no = item.get("no") if isinstance(item, dict) else None
        if isinstance(no, bool) or not isinstance(no, int) or no <= 0:
            return []
        nos.append(no)
    if len(set(nos)) != len(nos):
        return []
    return sorted(nos)


def synopsis_scene_by_no(synopsis: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """场号 → 梗概场对象（`` scenes_outline `` 元素**原样**，不裁剪、不改写）。"""
    out: dict[int, dict[str, Any]] = {}
    if not isinstance(synopsis, dict):
        return out
    for item in synopsis.get("scenes_outline") or []:
        if isinstance(item, dict) and isinstance(item.get("no"), int):
            out[int(item["no"])] = item
    return out


def plan_script_segments(synopsis: dict[str, Any] | None) -> list[str]:
    """script 段**逐场拆段**的调用计划：`` ["package_head", "scene:1", …] ``（场号升序）。

    梗概场号异常 ⇒ 返回 `[]`（调用方降级整段＋留痕）。
    """
    nos = synopsis_scene_nos(synopsis)
    if not nos:
        return []
    return ["package_head"] + [f"scene:{n}" for n in nos]


def cap_script_schema_for_segment(
    schema: dict[str, Any] | None,
    seg: str,
    *,
    dialogue_max_items: int | None = None,
) -> dict[str, Any] | None:
    """script 段级 schema 收窄（`T-116`；受约束解码的**段投影**）。

    为什么必须收窄：script 的派生引擎 schema 按 `` REQUIRED_TOP_KEYS["script"] ``
    投影（`acts` 等全量键全为 required）——逐场段若仍拿全量 schema 做受约束解码，
    xgrammar 会**强制**模型在每个场段里重出全部顶层键（含 `style_bible` 大对象），
    「单场小输出」的拆段动机即被 schema 自身抵消。

    - `package_head` 段：required＝head 键集；`acts` 收窄为**骨架形态**
      （`act_no`/`act_name`/`act_summary`/`scene_nos[]` 整数数组）；
    - `scene:<no>` 段：required＝场对象键集（无 `act_no`），数组键钉 `array` 类型；
      `dialogue_max_items` 为正整数时给 `dialogue` 数组钉 `maxItems`（`T-117` ②：
      把台词预算从 scope **提示**升级为**解码期硬约束**——复测 r4 scene:2 两连
      截断实锤 scope 提示拦不住跑飞；上限由调用方按 `est × DIALOGUE_SPEED_MAX ÷
      每行最短字数` 同源派生，本函数不做推导、只落地数值）；
    - 其他取值（含 `all`）原样返回（不收窄）。
    """
    if not isinstance(schema, dict) or seg == "all":
        return schema
    if seg == "package_head":
        act_skeleton = {
            "type": "object",
            "properties": {
                "act_no": {},
                "act_name": {},
                "act_summary": {},
                "scene_nos": {
                    "type": "array",
                    "items": {"type": "integer"},
                    # 复测 r1/r4 实锤：空幕（scene_nos=[]）⇒ 合并产物 acts[].scenes=[]
                    # 被形态闸「缺 scenes[]（或为空）」拒——解码期直接禁空幕。
                    "minItems": 1,
                },
            },
            "required": ["act_no", "act_name", "act_summary", "scene_nos"],
            # QA 证伪 L2 修复：三幕约束（R6）在 head 段解码期下沉——全量 schema 的
            # `FIELD_CONSTRAINTS["script"]["acts"]` 带 minItems/maxItems=3（T-096 线 3
            # 真机实证），段级收窄不得把它丢掉（否则只能靠合并后 R6 事后拦）。
            "minItems": 3,
            "maxItems": 3,
        }
        return {
            "type": "object",
            "properties": {
                **{k: {} for k in SCRIPT_HEAD_TOP_KEYS if k != "acts"},
                "acts": {"type": "array", "items": act_skeleton},
            },
            "required": list(SCRIPT_HEAD_TOP_KEYS),
        }
    if seg.startswith("scene:"):
        props: dict[str, Any] = {}
        for key in SCRIPT_SCENE_KEYS:
            props[key] = (
                {"type": "array", "items": {}}
                if key in _SCRIPT_SCENE_ARRAY_KEYS
                else {}
            )
        # ---- `T-117` ②：dialogue 行数**解码期**硬上限 ----
        # 调用方按 est × DIALOGUE_SPEED_MAX ÷ 每行最短字数 同源派生；est 异常时
        # 传 None ⇒ 不加约束（与 scope 的「缺失 ⇒ 保守提示」口径一致：缺数据
        # 就不造硬数字，硬数字造错比没有更危险）。
        if (
            isinstance(dialogue_max_items, int)
            and not isinstance(dialogue_max_items, bool)
            and dialogue_max_items > 0
        ):
            props["dialogue"] = {
                "type": "array",
                "items": {},
                "maxItems": dialogue_max_items,
            }
        return {
            "type": "object",
            "properties": props,
            "required": list(SCRIPT_SCENE_KEYS),
        }
    return schema


def merge_script_parts(
    parts: Sequence[dict[str, Any]],
    *,
    synopsis: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """script 逐场拆段产物 → 合并后的完整剧本（`T-116`）。

    与 `` merge_storyboard_parts() `` 同族纪律（每处刻意不同都对应一种真失败形态）：

    1. **头部键只在 head 段定义一次**：`` style_bible ``／`` characters ``／`` props ``
       是锚点类大对象，场段不重出（重出既浪费又引入段间漂移）——合并器从 head 段
       取 `` SCRIPT_HEAD_TOP_KEYS ``；后续段越界重出且取值不同 ⇒ 显式告警（先到先得）。
    2. **幕骨架 → 场装配**：head 段 `` acts[] `` 是**骨架形态**（含 `` scene_nos[] ``），
       合并侧按 `` scene_nos `` 把场段对象装配进各幕 `` scenes[] ``；骨架键
       `` scene_nos `` **删除**（最终契约不含）；场段越界输出的 `` act_no `` **丢弃**
       ——幕归属唯一真值是骨架，装配出的 `` act_no `` 由骨架派生（机械一致）。
    3. **机械承继/派生**：`` forbidden_items ``（原样承继梗概）与
       `` total_est_seconds ``（各场之和）由合并侧**机械计算**——「把约束从模型
       移到程序」同族纪律（这两个字段连截断风险都消失）。
    4. **重号/缺场不静默**：同一场号出现于两段以上、骨架 `` scene_nos `` 有场无段、
       场段对象无幕认领——一律**显式告警**（条目按语义保留或如实缺失，
       交形态闸/判据判，不洗白、不伪造归属）。

    ⚠️ 本函数**不判合规**：合并结果能否过形态闸与判据，是既有闸门职责。
    """
    warnings: list[str] = []
    merged: dict[str, Any] = {}
    head: dict[str, Any] | None = None
    scenes_by_no: dict[int, dict[str, Any]] = {}
    scene_owner: dict[int, int] = {}
    dupe_scene: set[int] = set()
    unspecified_out: list[dict[str, Any]] = []
    seen_unspec: set[tuple[str, str]] = set()

    for idx, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            warnings.append(f"第 {idx} 段不是 JSON 对象，已跳过（实际 {type(part).__name__}）")
            continue
        # ---- 头部段识别：含锚点类键且无场对象键（`no`）----
        if head is None and "no" not in part and (
            "style_bible" in part or "acts" in part
        ):
            head = part
            for item in part.get("unspecified") or []:
                if not isinstance(item, dict):
                    warnings.append(f"第 {idx} 段的 unspecified 含非对象项，已跳过")
                    continue
                key = (str(item.get("field")), str(item.get("reason")))
                if key in seen_unspec:
                    continue
                seen_unspec.add(key)
                unspecified_out.append(item)
            continue
        # ---- 场段：裸场对象或 `scenes[]` 包装（容忍两种形态）----
        if isinstance(part.get("scenes"), list):
            scene_iter = part.get("scenes")
        elif isinstance(part.get("no"), int) and not isinstance(part.get("no"), bool):
            scene_iter = [part]
        else:
            warnings.append(
                f"第 {idx} 段既非头部段也无场对象（缺 `no`/`scenes[]`），已跳过"
            )
            continue
        for sc in scene_iter:
            if not isinstance(sc, dict):
                warnings.append(f"第 {idx} 段含非对象场元素，已跳过")
                continue
            no = sc.get("no")
            if isinstance(no, bool) or not isinstance(no, int):
                warnings.append(
                    f"第 {idx} 段含缺 `no`（或非整数）的场对象，无法装配进幕，交形态闸判"
                )
                continue
            if no in scene_owner and scene_owner[no] != idx:
                dupe_scene.add(no)
            scene_owner.setdefault(no, idx)
            scenes_by_no[no] = sc
        for item in part.get("unspecified") or []:
            if not isinstance(item, dict):
                warnings.append(f"第 {idx} 段的 unspecified 含非对象项，已跳过")
                continue
            key = (str(item.get("field")), str(item.get("reason")))
            if key in seen_unspec:
                continue
            seen_unspec.add(key)
            unspecified_out.append(item)

    if dupe_scene:
        warnings.append(
            "场号重复出现于多段（"
            + "、".join(str(n) for n in sorted(dupe_scene))
            + "）——模型越界写了别的场；后到者覆盖先到者，交 R5/场号判据判"
        )

    # ---- 幕骨架装配 ----
    acts_out: list[dict[str, Any]] = []
    assigned: set[int] = set()
    skeleton = head.get("acts") if isinstance(head, dict) else None
    if isinstance(skeleton, list) and skeleton:
        for act in skeleton:
            if not isinstance(act, dict):
                warnings.append("幕骨架含非对象元素，已原样保留（交形态闸判）")
                acts_out.append(act)
                continue
            nos = act.get("scene_nos")
            scenes_for_act: list[dict[str, Any]] = []
            if isinstance(nos, list):
                if not nos:
                    warnings.append(
                        f"幕骨架 scene_nos 为空（act_no={act.get('act_no')!r}）——空幕缺陷，"
                        "该幕装配出空 scenes[]，交形态闸判（复测 r1/r4 实锤形态）"
                    )
                for no in nos:
                    if isinstance(no, bool) or not isinstance(no, int):
                        warnings.append(
                            f"幕骨架 scene_nos 含非整数场号（{no!r}），跳过"
                        )
                        continue
                    sc = scenes_by_no.get(no)
                    if sc is None:
                        warnings.append(
                            f"幕骨架声明了场 {no}，但无对应场段产物——该场缺内容，交形态闸判"
                        )
                        continue
                    if no in assigned:
                        warnings.append(
                            f"场 {no} 被多个幕声明（scene_nos 重叠）——装配进先声明的幕"
                        )
                        continue
                    assigned.add(no)
                    assembled = {k: v for k, v in sc.items() if k != "act_no"}
                    assembled["act_no"] = act.get("act_no")
                    scenes_for_act.append(assembled)
            else:
                warnings.append(
                    f"幕骨架缺 `scene_nos`（act_no={act.get('act_no')!r}），该幕无法装配场"
                )
            act_out = {k: v for k, v in act.items() if k != "scene_nos"}
            act_out["scenes"] = scenes_for_act
            acts_out.append(act_out)
        unclaimed = sorted(set(scenes_by_no) - assigned)
        if unclaimed:
            warnings.append(
                "场段产出的场无幕认领（场号："
                + "、".join(str(n) for n in unclaimed)
                + "）——未装配、**不计入 total_est_seconds**（不伪造归属），"
                "场号集合缺陷交判据判"
            )
    else:
        warnings.append(
            "head 段缺 acts 骨架（或为空）——逐场产物无法装配为幕结构，交形态闸判"
        )

    # ---- 头部键（先到先得只针对 head 段本身；后续段越界重出 ⇒ 告警）----
    if isinstance(head, dict):
        for key in SCRIPT_HEAD_TOP_KEYS:
            if key == "acts":
                continue
            if key in head:
                merged[key] = head[key]
        for idx, part in enumerate(parts, start=1):
            if part is head or not isinstance(part, dict):
                continue
            for key in ("style_bible", "characters", "props", "title"):
                if key in part and part.get(key) != merged.get(key):
                    warnings.append(
                        f"第 {idx} 段越界重出头部键「{key}」且取值不同——"
                        "锚点以头部段为准（先到先得），交判据判"
                    )
    merged["acts"] = acts_out
    merged["unspecified"] = unspecified_out

    # ---- 机械承继/派生（`forbidden_items`/`total_est_seconds`）----
    if isinstance(synopsis, dict):
        merged["forbidden_items"] = json.loads(
            json.dumps(synopsis.get("forbidden_items") or [], ensure_ascii=False)
        )
    elif isinstance(head, dict) and "forbidden_items" in head:
        merged["forbidden_items"] = head["forbidden_items"]
        warnings.append("梗概未传入：forbidden_items 退为 head 段值（无法机械承继）")
    else:
        merged["forbidden_items"] = []
        warnings.append("梗概未传入且 head 段无 forbidden_items——已置空数组，交判据判")

    # ---- 机械求和只计**已装配**的场（QA 证伪 L4 修复）：无幕认领的场若也计入，
    #      会出现「total ≠ Σ(acts 内各场)」的自相矛盾产物（R4 判失败且归因绕远）。
    total = 0
    bad_est = []
    for no in sorted(assigned):
        sc = scenes_by_no.get(no) or {}
        est = sc.get("est_seconds")
        if isinstance(est, bool) or not isinstance(est, (int, float)):
            bad_est.append(no)
            continue
        total += est
    if bad_est:
        warnings.append(
            "以下场次 est_seconds 缺失或非数值（"
            + "、".join(str(n) for n in sorted(bad_est))
            + "）——total_est_seconds 求和已跳过这些场，交 R4 判"
        )
    merged["total_est_seconds"] = total
    return merged, warnings


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
    - `unit:<id>`／`unit:<id>+<id>…`（`丙` 起的多单元组）：头部键全保留＋**该组各单元**＋
      **该组各单元的镜**（按 `shots[].unit_id ∈ 组` 与 `units[].shot_ids` 的**并集**过滤；
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

    uids = segment_unit_ids(seg)
    if not uids:
        return None, [f"段名「{seg}」解析不出单元 id——回退整份注入（不猜测）"]
    uidset = set(uids)
    mine: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    for u in units:
        if not isinstance(u, dict):
            continue
        uid = str(u.get("unit_id"))
        # 去重：上游脏数据里同 id 重复出现时只取首条——否则单单元段的 `units_cap`
        # 会被算成 2（独立 QA 2026-11-17 低优先级项）。
        if uid in uidset and uid not in seen_uids:
            seen_uids.add(uid)
            mine.append(u)
    got = {str(u.get("unit_id")) for u in mine}
    missing_uids = [u for u in uids if u not in got]
    if missing_uids:
        # ⚠️ 组内**任一**单元缺失即回退整份（不得只裁到存在的那个）：部分裁剪等于
        # 「抽掉证据的输入」，会让模型对缺失单元无所依据地补写。
        return None, [
            f"裁剪目标单元「{'、'.join(missing_uids)}」不在上游 units[] 中——回退整份注入（不猜测）"
        ]
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
        and (str(s.get("unit_id")) in uidset or str(s.get("shot_id")) in wanted_ids)
    ]
    if wanted_ids and len(mine_shots) < len(wanted_ids):
        got = {str(s.get("shot_id")) for s in mine_shots}
        missing = sorted(wanted_ids - got)
        warnings.append(
            "单元「" + "、".join(uids) + "」声明的镜在上游 shots[] 中缺 " + str(len(missing)) + " 条（"
            + "、".join(missing[:5]) + "）——按并集如实收窄，缺项交 R9／R41 判"
        )
    scoped["units"] = mine
    scoped["shots"] = mine_shots
    return scoped, warnings

