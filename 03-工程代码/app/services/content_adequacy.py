"""产物**内容足量性**探测（`ISSUE-045`）—— **只判、只留痕，不阻断**。

为什么与形态闸分开
------------------
`ISSUE-042` 的形态闸判的是「**结构**」：可解析 → 形态相符 → 必需键齐备。
它**正确地**拦下了被截断的 JSON，但「**合法 JSON ＋ 内容严重欠生成**」能整整齐齐穿过
全部三道闸。四轮真跑留下的三份实证：

    r5 剧本：`acts` 仅 **1 幕 1 场**、该场 `est_seconds=15`，而 `total_est_seconds` 自报 **108**
             ⇒ Σ场秒与声明总时长差 **7.2 倍**；客户端目标 **150–180 秒**
    r4 分镜：**3 镜只覆盖第 1 场**，第 2~5 场**全部漏拍**，而 `unspecified` 里
             **没有任何**漏拍说明 ⇒ 模板最核心的「动作守恒」硬约束**静默失效**
    A/B 对照：同一提示词跑 12 次，「3 镜 / 只覆盖第 1 场」在**不带受约束解码**时
             **6/6 稳定发生**（零方差）⇒ 不是偶发噪声，是本段的一个**吸引子**

⇒ 这是与 `ISSUE-042` **同族但不同层**的空洞：运行期**有「结构」判据、没有「内容」判据**。
   离线门禁 `validate_output.py` 里这些判据**早就有**（`R4`／`R10`／`R14`／`R22`），
   只是**没有运行期落点** —— 与 `ISSUE-042` 的根因形态**完全同构**（第三/第四处显形）。

⚠️ **为什么只判不拦**（2026-10-16 项目方裁决）
----------------------------------------------
字段级算术自洽与覆盖度属**质量**维度，不是**准入**维度。真实模型产物**普遍**不自洽：
本工程四轮真跑中，**凡产出分镜者 `Σ镜头时长 ≠ total_duration_ms`，无一轮例外**。
若设为阻断，则**所有真实产物都会被拦下、链路不可用**。故本模块的结论**只进日志与产物留痕**，
供离线门禁、人工抽检以及「是否重试」的后续回路消费 —— **绝不改变生成流程**。
（分层口径与 `SafetyService`「服务层只判定、编排层阻断」一脉相承：**判定与执行分离**。）

与形态闸的判据边界（**不得互相越界**）
--------------------------------------
- 形态闸（`artifact_contract`）：**结构**——能不能解析、顶层键齐不齐。**可阻断**。
- 本模块：**内容**——算得对不对、覆盖全不全。**只留痕**。
两者**都**运行、「结构不过」与「内容不足」在留痕上**分成两组字段**，不得合并成一个布尔。
"""

from __future__ import annotations

from typing import Any

from app.services.segment import parse_json_object
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger("content_adequacy")

#: 剧本层「Σ场秒 vs 声明总时长」的允许偏差 —— **取自模板原文**：
#: `TPL-008` 要求「与目标时长的偏差超过 **10%** 时须在 `unspecified` 中登记原因」。
#: ⇒ 超过 10% 即「须登记原因」，本模块把它机器化（**不判它是否登记了**，那是 `R37` 的事）。
SCRIPT_TOTAL_TOLERANCE = 0.10

#: 单场 `est_seconds` 下限 —— 取自 `validate_output.py` **`R22`**（规范两侧共同口径）：
#: 单镜时长下限 4s × 生成单元最少 2 镜 ＝ 8 秒；低于此**切不出任何合规单元**。
SCENE_DURATION_FLOOR_SECONDS = 8

#: 生成单元成员数取值 —— 取自 `validate_output.py` **`R10`**（规范 §4.3）：1 镜单元结构性不合格。
UNIT_SIZE_ALLOWED = frozenset({2, 3})


def _ok(stage: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {"checked": True, "ok": True, "stage": stage, "findings": [], "metrics": metrics}


def _verdict(stage: str, metrics: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "checked": True,
        "ok": not findings,
        "stage": stage,
        "findings": findings,
        "metrics": metrics,
    }


def assess(stage: str, text: str, upstream: dict[str, str] | None = None) -> dict[str, Any]:
    """对某阶段产物做**内容足量性**判定。

    :param stage: 阶段名（`synopsis` / `script` / `storyboard` / `shot_prompt`）
    :param text: 产物正文（模型输出原文）
    :param upstream: 上游产物正文（键＝变量名，如 `{"script_json": "…"}`）；
                     仅 `storyboard` 的**场覆盖度**判据需要它。

    :return: `{"checked", "ok", "stage", "findings", "metrics"}`
             - `checked=False` ＝ **本阶段未登记内容判据**（**不假装通过**，与既有口径一致）；
             - 解析失败**不在此处报错**（那是形态闸的职责），如实返回 `checked=False` 并记原因。

    ⚠️ **本函数不抛异常、不阻断**（除 `parse_json_object` 的既定语义外全部吞掉）。
    """
    upstream = upstream or {}
    if stage not in _ASSESSORS:
        return {"checked": False, "ok": None, "stage": stage, "findings": [], "metrics": {}}
    try:
        doc = parse_json_object(text)
    except AppError as exc:  # 解析不归本模块管；形态闸已判过，这里只是拿不到数
        return {
            "checked": False,
            "ok": None,
            "stage": stage,
            "findings": [{"code": "unparsable_for_adequacy", "reason": str(exc)[:120]}],
            "metrics": {},
        }
    except Exception as exc:  # noqa: BLE001 探测模块不得成为新的失败点
        logger.warning(
            "content_adequacy_probe_failed",
            extra={"extra_fields": {"stage": stage, "error": type(exc).__name__}},
        )
        return {
            "checked": False,
            "ok": None,
            "stage": stage,
            "findings": [{"code": "probe_error", "error": type(exc).__name__}],
            "metrics": {},
        }
    try:
        return _ASSESSORS[stage](doc, upstream)
    except Exception as exc:  # noqa: BLE001 同上：**畸形字段不得让探测变成新的失败点**
        logger.warning(
            "content_adequacy_probe_failed",
            extra={"extra_fields": {"stage": stage, "error": type(exc).__name__}},
        )
        return {
            "checked": False,
            "ok": None,
            "stage": stage,
            "findings": [{"code": "probe_error", "error": type(exc).__name__}],
            "metrics": {},
        }
    return _ASSESSORS[stage](doc, upstream)


# --------------------------------------------------------------------- 剧本层
def _assess_script(doc: dict[str, Any], _upstream: dict[str, str]) -> dict[str, Any]:
    """`script_v1`：**算术自洽** ＋ **非空** ＋ **单场时长下限**。"""
    acts = doc.get("acts") or []
    scenes = [s for a in acts if isinstance(a, dict) for s in (a.get("scenes") or []) if isinstance(s, dict)]
    declared = doc.get("total_est_seconds")
    scene_sum = sum(int(s.get("est_seconds") or 0) for s in scenes)
    metrics = {
        "acts": len(acts),
        "scenes": len(scenes),
        "sum_scene_seconds": scene_sum,
        "total_est_seconds": declared,
    }
    findings: list[dict[str, Any]] = []
    if not scenes:
        findings.append({"code": "script_no_scenes", "acts": len(acts)})
    if isinstance(declared, (int, float)) and declared > 0:
        delta = abs(scene_sum - declared) / float(declared)
        metrics["total_delta_ratio"] = round(delta, 4)
        if delta > SCRIPT_TOTAL_TOLERANCE:
            # ⚠️ 口径取自模板：>10% 即「须在 unspecified 中登记原因」——
            #    本判据只说「不自洽」，**不判它登记没登记**（那是 `R37`）。
            findings.append(
                {
                    "code": "script_total_mismatch",
                    "sum_scene_seconds": scene_sum,
                    "total_est_seconds": declared,
                    "delta_ratio": round(delta, 4),
                    "tolerance": SCRIPT_TOTAL_TOLERANCE,
                }
            )
    else:
        findings.append({"code": "script_total_missing_or_nonpositive", "total_est_seconds": declared})
    short = [s.get("no") for s in scenes if int(s.get("est_seconds") or 0) < SCENE_DURATION_FLOOR_SECONDS]
    if short:
        findings.append(
            {"code": "scene_below_duration_floor", "scenes": short, "floor_seconds": SCENE_DURATION_FLOOR_SECONDS}
        )
    return _verdict("script", metrics, findings)


# --------------------------------------------------------------------- 分镜层
def _assess_storyboard(doc: dict[str, Any], upstream: dict[str, str]) -> dict[str, Any]:
    """`storyboard_v1`：**时长守恒** ＋ **单元规模** ＋ **场覆盖度**。"""
    shots = [s for s in (doc.get("shots") or []) if isinstance(s, dict)]
    units = [u for u in (doc.get("units") or []) if isinstance(u, dict)]
    declared = doc.get("total_duration_ms")
    shot_sum = sum(int(s.get("duration_ms") or 0) for s in shots)
    covered = sorted({s.get("scene_no") for s in shots if s.get("scene_no") is not None}, key=str)
    metrics = {
        "shots": len(shots),
        "units": len(units),
        "sum_shot_ms": shot_sum,
        "total_duration_ms": declared,
        "scenes_covered": covered,
    }
    findings: list[dict[str, Any]] = []
    if not shots:
        findings.append({"code": "storyboard_no_shots"})
    if isinstance(declared, (int, float)) and declared > 0:
        if shot_sum != declared:
            # 口径同离线 `R14`：**必须严格相等**（不留容差）。
            findings.append(
                {"code": "storyboard_duration_sum_mismatch", "sum_shot_ms": shot_sum, "total_duration_ms": declared}
            )
    else:
        findings.append({"code": "storyboard_total_missing_or_nonpositive", "total_duration_ms": declared})

    bad_units = [
        {"unit_id": u.get("unit_id"), "size": len(u.get("shot_ids") or [])}
        for u in units
        if len(u.get("shot_ids") or []) not in UNIT_SIZE_ALLOWED
    ]
    if bad_units:
        findings.append({"code": "unit_size_out_of_range", "units": bad_units, "allowed": sorted(UNIT_SIZE_ALLOWED)})

    # ---- 场覆盖度：**本模块最有价值的判据**（「只覆盖第 1 场」的直接证据）----
    expected = _expected_scenes(upstream.get("script_json"))
    if expected is not None:
        metrics["scenes_expected"] = expected
        missing = [no for no in expected if no not in covered]
        if missing:
            findings.append(
                {
                    "code": "scene_coverage_incomplete",
                    "scenes_expected": expected,
                    "scenes_covered": covered,
                    "scenes_missing": missing,
                }
            )
    return _verdict("storyboard", metrics, findings)


# --------------------------------------------------------------------- 梗概层
def _assess_synopsis(doc: dict[str, Any], _upstream: dict[str, str]) -> dict[str, Any]:
    """`synopsis_v1`：只判「声明总时长存在且为正」—— 该层无更硬的内生判据。"""
    declared = doc.get("total_est_seconds")
    metrics = {"total_est_seconds": declared}
    if not isinstance(declared, (int, float)) or declared <= 0:
        return _verdict("synopsis", metrics, [{"code": "synopsis_total_missing_or_nonpositive"}])
    return _ok("synopsis", metrics)


def _expected_scenes(script_text: str | None) -> list[Any] | None:
    """从上游剧本取「应有的场次号」清单；取不到返回 `None`（**不猜、不静默当作齐全**）。"""
    if not script_text:
        return None
    try:
        doc = parse_json_object(script_text)
    except Exception:  # noqa: BLE001 上游不可解析时本判据**不出结论**
        return None
    nos = [
        s.get("no")
        for a in (doc.get("acts") or [])
        if isinstance(a, dict)
        for s in (a.get("scenes") or [])
        if isinstance(s, dict) and s.get("no") is not None
    ]
    return sorted(nos, key=str) or None


#: 阶段 → 判定器。**未登记的阶段＝不判**（返回 `checked=False`），不得假装通过。
_ASSESSORS = {
    "synopsis": _assess_synopsis,
    "script": _assess_script,
    "storyboard": _assess_storyboard,
}

#: 需要上游的判据（用于 `deliver` 时按需取变量，避免无谓解析）。
NEEDS_UPSTREAM = frozenset({"storyboard"})
