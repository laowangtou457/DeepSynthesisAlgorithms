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

#: 引擎侧**可表达**的字段级约束（`PRO-011` 线 3 契约下沉；2026-11-04 授权落地）。
#:
#: 背景（真基线实测，`DEV-20261104-009`）：`required` 投影只约束「键必须在」，
#: **不约束取值** ⇒ `R6`（幕数）、`R16`（景别／运镜枚举）在解码期零约束、
#: 只能靠生成后门禁抓 → 重试。其中**离散取值型**判据可由引擎 schema 表达
#: （xgrammar 实测支持 `minItems`×7／`enum`×19，见 `OPS-002` §4.3.1）。
#:
#: ⚠️ **真值归属（`PRO-011` 附 4 方案 A，2026-11-04 授权拍板）**：本表是
#: **判据常量的运行期投影、不是第二真值**——每个条目登记判据出处，且由
#: `app/tests/test_contract_engine_constraints.py` 与离线判据常量**互锁**
#: （任一侧单独改 ⇒ 测试即红，`PRO-012` 变更三件套纪律）。改本表 === 改判据约束面，
#: 须同批核对：① 离线判据（`prompts/validate_output.py`）② 互锁测试 ③ 本表。
#:
#: ⚠️ **声音性（soundness）自查**：约束只能**收窄到判据也要求**的程度——
#: 引擎按本表拒掉的取值，判据层必然也判失败 ⇒ 不会「引擎放过、门禁拦」之外的
#: 「引擎拦了合法产物」。
FIELD_CONSTRAINTS: dict[str, dict[str, Any]] = {
    # R6 ACT_STRUCTURE（仅 script）：acts 恰为 3 幕（TPL-008 v2.1.1 L85/L137/L242/L381 同款条款）。
    # ⚠️ **引擎边界（2026-11-04 真机实测）**：`minItems` **不带 `items` 键**时，
    #    vLLM `structured_outputs`（xgrammar 新路径）**编译期 500**（`OPS-002` §4.3.1
    #    的「minItems 通过」系旧 `guided_json` 路径实测）——故本表所有 `minItems`
    #    **必须伴随 `items` 键**；新增条目须过「structured_outputs 直连探测」。
    "script": {
        "acts": {"type": "array", "items": {}, "minItems": 3, "maxItems": 3},
    },
    # R16 ENUM_VALUES：景别六值、运镜 20 类（validate_output.py L241~L251 常量的运行期投影）
    #
    # ⚠️ **字段塌缩教训（2026-11-04 n=6 跑测 + 直连探测实证，`ISSUE-059`）**：
    #    本条目首版（T-098 批次）的 items 只描述 `shot_size`/`camera.move` 两字段、
    #    **未列其余字段也无 `required`** ⇒ xgrammar 把 `items.properties`
    #    **未列出的字段一律禁止**（`additionalProperties` 缺省被按禁止处理），
    #    4/4 轮 shots 元素塌缩为 `{shot_size, camera}` 两字段、R7/R8/R9/R12 全爆。
    #    直连探测三变体对照（`.wb-e2e/_probe_schema_collapse.py`）：
    #    A 现状窄 schema ⇒ 复现塌缩；B/C 全字段＋required ⇒ 14~17 字段全出
    #    ⇒ **塌缩由「字段清单不全」引起、与 enum 无关**。
    #    ⇒ 纪律：**引擎侧任何 `items.properties` 必须列全该层产物真值字段集**
    #       （真值出处见 `STORYBOARD_SHOT_KEYS` 注记），且**必须带 `required`**。
    "storyboard": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "shot_id": {"type": "string"},
                    "unit_id": {"type": "string"},
                    "scene_no": {"type": "integer"},
                    "shot_no": {"type": "integer"},
                    "shot_size": {
                        "type": "string",
                        "enum": [
                            "extreme_wide", "wide", "full", "medium",
                            "close_up", "extreme_close_up",
                        ],
                    },
                    "camera": {
                        "type": "object",
                        "properties": {
                            "move": {
                                "type": "string",
                                "enum": [
                                    "static", "push_in", "pull_out", "zoom_in", "zoom_out",
                                    "pan_left", "pan_right", "tilt_up", "tilt_down",
                                    "truck_left", "truck_right", "pedestal_up", "pedestal_down",
                                    "arc", "tracking", "shake_slight", "shake_strong",
                                    "pov", "roll_cw", "roll_ccw",
                                ],
                            },
                            # R19 六维（角度/光学）＋ R17/R26 参数面——枚举值＝判据常量
                            # PACK_ENUM_OPTIONAL 的运行期投影。
                            # ⚠️ 全部【不进 required】：判据口径「默认值＝省略键」（R26/R17），
                            #    required 会强制输出枚举值、消灭「省略」路径；
                            #    列入 properties 的意义是**解除 xgrammar 禁止**、给模型可写路径。
                            "height": {
                                "type": "string",
                                "enum": ["eye_level", "low", "high", "overhead", "ground"],
                            },
                            "roll": {
                                "type": "string",
                                "enum": ["level", "dutch", "roll_cw", "roll_ccw"],
                            },
                            "optics": {
                                "type": "string",
                                "enum": [
                                    "deep_focus", "shallow_focus", "rack_focus",
                                    "long_lens_compression", "wide_angle_distortion",
                                ],
                            },
                            # ⚠️ `medium`／`normal` **不在引擎 enum 内**（`ISSUE-065` 裁决 1 修法 A，
                            #    2026-11-06）：`R26` 早已判它们「须省略该键」——引擎却允许生成，
                            #    属「能生成但不合规」的结构错配。段级裁剪使正例密度下降后，模型
                            #    重新开始选这两值（on 臂 163 镜 21 处、off 臂 180 镜零处）。
                            #    修法＝把「事后判」升级为「事中不生成」（与 `R8`/`R14` 回填、C 期
                            #    schema 收窄同族）；直连编译探测已证 xgrammar 接受两值 enum。
                            "amplitude": {
                                "type": "string",
                                "enum": ["small", "large"],
                            },
                            "speed": {
                                "type": "string",
                                "enum": ["slow", "fast"],
                            },
                        },
                        # ⚠️ required 含 height／optics 的理由（2026-11-04 真机两轮实证）：
                        #    引擎解禁＋模板积极引导（TPL-010 v2.2.3）后模型仍**整键省略**
                        #    ⇒ R19 角度／光学覆盖恒 0%。required 化是**生成引导**（非事后
                        #    拒绝）：产物仍全合规（eye_level 是合法枚举值、不在 R26 判禁区；
                        #    R17 只禁 static／pov 携带 amplitude／speed，不管 height／optics）。
                        #    amplitude／speed／roll 维持可选（默认值＝省略键口径，R26）。
                        "required": ["move", "height", "optics"],
                    },
                    "duration_ms": {"type": "integer"},
                    "action": {"type": "object"},
                    # R19 六维之构图/轴线/画面结果——判据只查「有值」（覆盖率门槛），无枚举；
                    # 显式列出字段名使模型有稳定落点（无 properties 时虽放行但模型容易漏写）。
                    "shot_language": {
                        "type": "object",
                        "properties": {
                            "composition": {"type": "string"},
                            "axis": {"type": "string"},
                            "result": {"type": "string"},
                        },
                    },
                    "dialogue": {},
                    "sfx": {},
                    "lighting": {"type": "string"},
                    "transition_in": {"type": "string"},
                    "transition_out": {"type": "string"},
                    "character_refs": {"type": "array", "items": {}},
                    "prop_refs": {"type": "array", "items": {}},
                    "notes": {"type": "string"},
                },
                "required": [
                    "shot_id", "unit_id", "scene_no", "shot_no", "shot_size", "camera",
                    "duration_ms", "action", "shot_language", "dialogue", "sfx", "lighting",
                    "transition_in", "transition_out", "character_refs", "prop_refs", "notes",
                ],
            },
            # minItems=2 由 R10（单元成员须 2 或 3）×「至少 1 单元」推出；
            # **不设 maxItems** —— 判据层无整片镜数上限，soundness 禁止引擎拒判据允许的产物。
            "minItems": 2,
        },
        # ⚠️ **units 骨架（2026-11-04，`ISSUE-058` storyboard 截断根因）**：
        #    首版无 items ⇒ xgrammar 对 units 元素**任意放行**（无字段清单＝自由文本
        #    任意堆叠）⇒ 模型在 `soundscape`/`notes` 等自由文本上退化重复、
        #    n=6 跑测 2/6 轮 storyboard "all" 段真实跑满 8192 tokens 触发
        #    `finish_reason=length`（502 `segment_truncated`，延迟 ≈186s 与全量
        #    生成时间吻合）。补骨架后元素形态固定，退化空间收窄。
        #    真值出处：**CFG-006 `$defs/unit`**（`additionalProperties:false` 的
        #    契约字段集，R36 唯一真值来源）——6 字段与真实产物字段集一致；
        #    `required` 5 项＝契约 required（`notes` 契约级可选）。
        #    `shot_ids` 的 minItems/maxItems＝**R10 UNIT_SIZE**（成员恰为 2 或 3）
        #    的引擎投影——判据硬性口径，soundness 成立。
        #    units 的 minItems=1 由 R9（所有镜头须归入单元）× shots≥2 × R10 推出；
        #    **不设 maxItems** —— 判据层无单元数上限（`ISSUE-058` 产能规划归 SW-006）。
        "units": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string"},
                    "scene_no": {"type": "integer"},
                    "shot_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 3,
                    },
                    "soundscape": {"type": "string"},
                    "music": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["unit_id", "scene_no", "shot_ids", "soundscape", "music"],
            },
        },
        # ⚠️ **quality_gate 数值字段收口（2026-11-05，`T-087` 余项 `R25`）**：
        #    立约前提「数值字段填了就必须等于复算」在 7B 真基线上不成立——
        #    2026-11-04 冒烟实测（17 镜产物）`shot_count=22 ≠ 复算 17`、
        #    `move_types` 混入**转场**词表值（fade_in/fade_out/cut ≠ 运镜枚举）。
        #    v2.2.0 移除 `move_type_min_required` 时保留前三个数值字段所依据的
        #    「shot_count/static_shot_count 实测可靠」是 **3 镜小样本**结论，
        #    n 上到 17 即崩（数数是 7B 的已知弱项）。⇒ 按 `BR-12` 口径
        #    「统计量不由模型承诺」把引擎字段面收窄到**仅 self_check（叙述性）**，
        #    数值字段被 xgrammar 禁止输出 ⇒ `R25` 回到「未填数值字段不罚」合法态。
        #    ⚠️ 声音性说明：本约束比判据**更严**（判据允许正确填写数值字段），
        #      与 camera.height/optics 的 required 化同属「生成引导」先例——产物
        #      不含数值字段时**完全合法可交付**，拒掉的只是「7B 填了必错的路径」；
        #      判据零改动：`R25` 仍逐项比对任何**自发填写**的数值字段
        #      （本约束只作用于受约束解码路径，不审离线产物）。
        "quality_gate": {
            "type": "object",
            "properties": {
                "self_check": {"type": "string"},
            },
        },
    },
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
    """由形态真值**现算**受约束解码用的 JSON Schema（`required` 投影 ＋ 字段级约束）。

    设计取舍（**刻意如此，不是遗漏**）：
    - `required` ＋ 空 schema 的 `properties`（＝「这些键必须在，值是什么不管」）；
    - **不设 `additionalProperties: false`** —— 见模块 docstring 的实测依据；
    - **不凭空补类型** —— 字段级约束**只**来自 `FIELD_CONSTRAINTS`（每条登记判据出处、
      与离线判据常量互锁），`FIELD_CONSTRAINTS` 未登记的键仍为空 schema（`T-096` 线 3）。

    返回 `None` 表示该形态无派生契约（当前四形态全部有）。
    """
    need = REQUIRED_TOP_KEYS.get(shape)
    if need is None:
        return None
    props: dict[str, Any] = {k: {} for k in need}
    for key, constraint in (FIELD_CONSTRAINTS.get(shape) or {}).items():
        props[key] = constraint
    return {
        "type": "object",
        "properties": props,
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
