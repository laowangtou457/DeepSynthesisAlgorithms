"""链路产物的**形态契约** —— 运行期唯一真值来源（`ISSUE-042` 根治）。

为什么要这个模块
----------------
`ISSUE-042` 的现象是「**上游是非法 JSON，链路照常推进**」：分镜段产物是一段**被截断的 JSON**
（13,252 字符，`finish_reason` 却是 `stop`），却被当作「已完成」入库、状态机照常推进，
下游拿到这份不可解析的上游仍继续生成，并**自行编造**缺失的 `units`／`shots`。

彻查后的**根因只有一条**：**「产物形态契约」在运行期没有任何落点**——
中间三段的产物形态只存在于两份**非运行期**的载体里：

| 载体 | 性质 | 运行期可用？ |
| --- | --- | --- |
| `prompts/CFG-007_SCHEMA.md` | 人读文档 | ❌ |
| `prompts/validate_output.py`（R1~R40） | **离线**门禁脚本 | ❌（且服务层纪律禁止引入工程侧脚本依赖） |

于是同一个空洞在三处显形（实测均有证据）：

1. **约束解码建不起来** —— `output_schema.STAGE_SCHEMA` 只登记了 `shot_prompt`，
   故 `synopsis`／`script`／`storyboard` 三段的 `constrained_decoding` **恒为 `false`**
   （第 3 轮真跑日志三处实证）⇒ 模型自由生成，**可以产出截断 JSON**；
2. **生成后无从校验** —— 单段计划的产物走 `final_text = texts[0]`，**根本不经过任何解析**
   （多段路径碰巧会经 `parse_json_object`，但那是「合并」的必要步骤、不是「校验」环节）
   ⇒ 产物是否合法**取决于 `segment` 取值**，是**偶然**而非**设计**；
3. **下游无从拒绝** —— 没有判定，就只剩「继续」。

本模块补的就是这个落点：把形态契约变成**运行期可读**的东西，并让三条通路
（受约束解码 / 生成后自检 / 下游准入）**共用同一份真值**。

真值来源（**不另立口径**）
--------------------------
本模块**不新造任何字段集**，只把既有真值搬进运行期，逐项登记出处：

- `SHAPE_SIGNATURES` ← `prompts/validate_output.py` 的 `detect_shape()`（同一顺序、同一口径）；
- `REQUIRED_TOP_KEYS` ← 同文件的 `rule_required_keys()`（判据 **R5**）；
- `REQUIRED_TOP_KEYS["pack"]` ← **直接复用** `app/services/segment.py` 的
  `REQUIRED_TOP_KEYS`（该常量与 `CFG-006_shot_prompt_pack.v1.schema.json` 的顶层 `required`
  逐字一致；此处 import 而非抄写，**避免出现第二份会陈旧的清单**）。

⚠️ **本模块只判「形态」，不判「合规」**：字段级／取值级判据（R26~R36 等）属**交付层**
（`delivery/validate_pack.py`），服务层**刻意不引入**——见 `output_schema.py` 的模块注记。

⚠️ **受约束解码的 schema 是「投影」不是「第二真值」**：`derived_engine_schema()` 由
`REQUIRED_TOP_KEYS` 现算，`required` 之外**刻意不设 `properties` 类型、更不封
`additionalProperties`** —— 实测依据：`synopsis` 的真实产物顶层有 14 键，比 R5 的 11 项
**多出** `covered_points`／`genre`／`logline_parts` 三个契约外键，**封 `additionalProperties`
会当场把合法产物判死**。故只约束「必需键必须在」，不约束「不得有别的键」
（「多余键」由交付层 **R36** 承担，两处不重复）。
"""

from __future__ import annotations

from typing import Any, NamedTuple

from app.core.errors import AppError
from app.services.segment import REQUIRED_TOP_KEYS as _PACK_REQUIRED_TOP_KEYS
from app.services.segment import parse_json_object

#: 形态 → 顶层**必需**键（唯一真值来源见模块 docstring；前两项与判据 R5 逐字一致）。
#:
#: ⚠️ 修改本表 === 修改契约：须同步 `prompts/validate_output.py` 的 R5，
#: 并复核 `REQUIRED_TOP_KEYS["pack"]` 仍与 `CFG-006` schema 的顶层 `required` 一致。
REQUIRED_TOP_KEYS: dict[str, tuple[str, ...]] = {
    "synopsis": (
        "title",
        "logline",
        "protagonist",
        "supporting",
        "world",
        "conflict",
        "scenes_outline",
        "ending",
        "forbidden_items",
        "total_est_seconds",
        "unspecified",
    ),
    "script": (
        "title",
        "logline",
        "genre",
        "style_bible",
        "characters",
        "props",
        "acts",
        "forbidden_items",
        "total_est_seconds",
        "unspecified",
    ),
    "storyboard": (
        "title",
        "genre",
        "style_ref",
        "aspect_ratio_default",
        "total_duration_ms",
        "units",
        "shots",
        "forbidden_items",
        "unspecified",
        "quality_gate",
    ),
    "pack": _PACK_REQUIRED_TOP_KEYS,
}

#: 链路阶段（`dialogue_service` 的生成目标阶段名）→ 产物形态。
#:
#: ⚠️ 与产物形态**同名者三、异名者一**：`shot_prompt` 阶段的产物就是**交付包**（形态 `pack`）
#: ——这与 `CFG-007_SCHEMA.md` 的 `target_stage` 登记口径**同源**（该处亦写明二者同映射到 `pack`）。
STAGE_TO_SHAPE: dict[str, str] = {
    "synopsis": "synopsis",
    "script": "script",
    "storyboard": "storyboard",
    "shot_prompt": "pack",
}


def detect_shape(doc: Any) -> str | None:
    """按产物顶层**签名键**识别形态；无法识别返回 `None`。

    ⚠️ **顺序敏感**（与 `validate_output.py::detect_shape` 同序同口径）：
    交付包（`pack`）与分镜脚本（`storyboard`）**都有 `units` 与 `shots`**，
    故必须先判 `pack`（凭 `aigc_meta` ＋ `schema_version`，二者是分镜层不产出的字段），
    否则交付包会被误判为分镜脚本。

    ⚠️ 缺口台账（`ledger`）与对话式修改两种形态同理**按签名键认定**，而非「顶层键集完全相等」——
    否则一旦混装进别的键，形态就变成 `None`、对应判据反而永远不跑，
    缺陷刚好藏在判据的盲区里（该取舍与离线脚本的既有实现一致）。
    """
    if not isinstance(doc, dict):
        return None
    if "aigc_meta" in doc and "schema_version" in doc:
        return "pack"
    if isinstance(doc.get("unspecified"), list) and not any(
        k in doc for k in ("acts", "shots", "units", "scenes_outline", "aigc_meta")
    ):
        return "ledger"
    if "change_log" in doc or "modify_version" in doc:
        return "modify"
    if "pair_role" in doc or "check_version" in doc:
        return "drift_report"
    if "acts" in doc:
        return "script"
    if "shots" in doc and "units" in doc:
        return "storyboard"
    if "scenes_outline" in doc:
        return "synopsis"
    return None


def missing_required(shape: str, doc: Any) -> tuple[str, ...]:
    """该形态下**缺失**的顶层必需键（按真值表次序）。"""
    need = REQUIRED_TOP_KEYS.get(shape)
    if need is None or not isinstance(doc, dict):
        return ()
    return tuple(k for k in need if k not in doc)


def derived_engine_schema(shape: str) -> dict[str, Any] | None:
    """由形态真值**现算**受约束解码用的 JSON Schema（`required` 投影）。

    设计取舍（**刻意如此，不是遗漏**）：
    - 只给 `required` ＋ 空 schema 的 `properties`（＝「这些键必须在，值是什么不管」）；
    - **不设 `additionalProperties: false`** —— 见模块 docstring 的实测依据；
    - **不写字段类型** —— 类型真值只在 `CFG-006`（交付包）与 `validate_output.py`（中间层）
      里有，凭空补类型＝**自造比契约更严的私有口径**（本工程已多次登记该类缺陷）。

    返回 `None` 表示该形态无派生契约（当前四形态全部有）。
    """
    need = REQUIRED_TOP_KEYS.get(shape)
    if need is None:
        return None
    return {
        "type": "object",
        "properties": {k: {} for k in need},
        "required": list(need),
    }


class ShapeVerdict(NamedTuple):
    """形态判定结果（**只描述事实，不抛错**；抛错由调用方裁决）。"""

    shape: str
    #: 判定是否通过（可解析 ＋ 形态相符 ＋ 必需键齐备）
    ok: bool
    #: 实际识别出的形态（解析失败时为 `None`）
    detected: str | None
    #: 缺失的顶层必需键
    missing: tuple[str, ...]
    #: 机器可判的失败原因码（通过时为 `None`）
    reason: str | None
    #: 人类可读的失败说明（通过时为 `None`）
    error: str | None
    #: 解析失败时的补充细节（JSON 位置等）
    error_details: dict[str, Any]

    @property
    def summary(self) -> str:
        """一行式留痕（可入日志与错误 `details`）。"""
        if self.ok:
            return f"形态 {self.shape} ✓"
        return f"形态 {self.shape} ✗（{self.reason}）"


def check_shape(shape: str, text: Any) -> ShapeVerdict:
    """校验一段产物文本是否满足该形态的**形态契约**。

    三层判定，**全部只判形态**：

    1. **可解析** —— 走 `parse_json_object`（围栏／前后缀容忍与工程既有口径**同一套**，
       不另立第二套解析规则），且顶层须为对象；
    2. **形态相符** —— `detect_shape()` 的结果须等于声明的形态
       （挡住「声明是交付包、实际产出分镜脚本」这类张冠李戴）；
    3. **必需键齐备** —— R5 真值表的每一键都在。

    ⚠️ **本函数不抛错**：判定与裁决分开——「谁在什么位置阻断」是编排层的事
    （与 `SafetyService` 的「服务层只判定、编排层阻断」同一分层纪律）。

    ⚠️ **`error_details` 内**刻意不出现 `reason` 这个键名**：`parse_json_object` 的
    `details` 里**本来就有** `reason`（JSON 解析器的报错串），若原样摊平进闸门的
    `details`，会把闸门的**机器可判原因码**覆盖成一句解析器的英文报错
    ——本批实现时已踩（测试当场暴露）。故解析细节一律**收进 `parse` 子对象命名空间**。
    """
    if not isinstance(text, str) or not text.strip():
        return ShapeVerdict(
            shape=shape,
            ok=False,
            detected=None,
            missing=(),
            reason="artifact_empty",
            error="产物为空，无法解析为 JSON 对象",
            error_details={},
        )
    try:
        doc = parse_json_object(text)
    except AppError as exc:
        return ShapeVerdict(
            shape=shape,
            ok=False,
            detected=None,
            missing=(),
            reason="artifact_not_json",
            error=exc.message,
            # ⚠️ 命名空间化：`exc.details` 含 `reason` 键，摊平会覆盖闸门原因码
            error_details={"parse": dict(exc.details)},
        )

    detected = detect_shape(doc)
    if detected != shape:
        return ShapeVerdict(
            shape=shape,
            ok=False,
            detected=detected,
            missing=(),
            reason="artifact_shape_mismatch",
            error=(
                f"产物形态与阶段声明不符：声明「{shape}」，实际识别为"
                f"「{detected or '无法识别'}」"
            ),
            error_details={"declared_shape": shape, "detected_shape": detected},
        )

    missing = missing_required(shape, doc)
    if missing:
        return ShapeVerdict(
            shape=shape,
            ok=False,
            detected=detected,
            missing=missing,
            reason="artifact_missing_required_keys",
            error="产物缺顶层必需键：" + "、".join(missing),
            error_details={
                "declared_shape": shape,
                "missing_keys": list(missing),
                "required_keys": list(REQUIRED_TOP_KEYS[shape]),
            },
        )

    return ShapeVerdict(
        shape=shape,
        ok=True,
        detected=detected,
        missing=(),
        reason=None,
        error=None,
        error_details={},
    )
