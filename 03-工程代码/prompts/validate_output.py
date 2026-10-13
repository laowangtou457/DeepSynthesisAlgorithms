#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出契约校验器 · validate_output.py

定位：
  validate_templates.py 校验「模板写了什么」（结构／变量一致性）；
  本脚本校验「产物长什么样」——即模板输出 JSON 是否满足链路已定案的**封闭枚举与接缝约定**。

  ⚠️ 本脚本**不联网、不调用模型**，只对「已产出的 JSON」做静态核对。
     因此它既能用于当前的**人工构造用例**（examples/*.md 内的 JSON 块），
     也能在模型就绪后直接对**真实输出**执行（用法见下）。

首批校验规则（依 2026-10-13 导演视角两轮评审定案）：
  R1 PURPOSE_ENUM          scenes_outline[].purpose / acts[].scenes[].purpose
                           仅限五值：建立／升级／转折／反转／收束
                           —— 本脚本的**首要规则**（对应 R-05：枚举未闭合导致用例越界）
  R2 FILL_STAGE_ENUM       unspecified[].fill_stage 仅限：
                           synopsis／script／storyboard／shot_prompt
  R3 SCENE_NO_CONTINUITY   场号须从 1 起连续、不重复（R-06：区间与档位口径）
  R4 EST_SECONDS_SUM       total_est_seconds 须等于各场 est_seconds 之和
  R5 REQUIRED_KEYS         按产物形态（synopsis／script／storyboard）核对必备顶层字段
                           （交付包 pack 不走本条，其必备结构由 R27 统一核对，避免两处口径打架）
  R6 ACT_STRUCTURE         （仅 script）acts 恰为 3 幕，且每场 act_no 与所属幕一致

剧本层补充规则（SW-005 `script_v1` v2.0.0，2026-10-13 依导演视角独立评审 `SR-01`~`SR-11` 新增）：
  R20 DIALOGUE_TYPE_ENUM   dialogue[].type 仅限「对白／旁白／画外音」（SR-09：该枚举此前未登记）
  R21 UNSPECIFIED_OWNER    缺口台账 unspecified[].owner 仅限「算法作者／客户／运维」；
                           且**客户侧缺口不得前移到下游**（SR-02）——下游（分镜／提示词）职责上
                           无法补叙事事实与设计确认，把「待客户确认」推给下游阶段等于把洞换个位置继续走。
                           · 剧本层：`owner=客户` 者 `fill_stage` 必须为 `script`（本层发起追问）；
                           · 分镜层（v2.1.0 依 `BR-06` 收紧为二分）：继承项（`upstream_field` 非空）
                             必须仍为 `script`（追问阶段在剧本层已定，本层不得改写）；
                             本层新增项（`upstream_field` 空）应为 `storyboard`；
                             共同底线：**一律不得为 `shot_prompt`**。
                           本条把该口径从「靠人记着」变成「跑得出来」。
  R22 SCENE_DURATION_FLOOR 每场 est_seconds 须 ≥ 8 秒（＝单镜时长下限 4s × 生成单元最少 2 镜）——
                           SR-08：场时长事实上就是该场的「镜数预算」，低于 8 秒下游切不出任何合规单元。
                           （纵向求和另有 R4；本规则管的是横向「够不够切」。）

分镜层规则（SW-006 `storyboard_v1`，2026-10-13 新增，依规范 §3.5／§3.6／§4.2）：
  R7  SHOT_ID_FORMAT       shot_id 唯一且形如 S<场号两位>-SH<镜号三位>
  R8  SHOT_NO_SEQ          同一场内 shot_no 从 1 起连续、不跳号
  R9  UNIT_LINK            shots[].unit_id 必须命中 units[]；units[].shot_ids 与 shots 双向一致，
                           成员镜的 scene_no 必须等于其所属单元的 scene_no，
                           且 **shot_ids 须按镜序递增**（v2.1.0 依 BR-11 补：逆序单元此前无判据）
  R10 UNIT_SIZE            units[].shot_ids 成员数必须为 2 或 3（规范 §4.3：1 镜单元结构性不合格）
  R11 UNIT_MOVE_UNIQUE     同一单元内 camera.move 取值不得重复
  R12 DURATION_INT_SECONDS duration_ms 必须为整秒（1000 的整数倍）
  R13 DURATION_BOUNDS      单镜时长须落在 [4s, 15s]（MiniMax H3 口径；可用 --duration-bounds 覆盖）
  R14 DURATION_SUM         total_duration_ms 须等于各镜 duration_ms 之和
  R15 DIALOGUE_SPEED       dialogue 字数 ÷ 秒数 ≤ 9（规范 §4.5）
  R16 ENUM_VALUES          shot_size 取景别六值之一；camera.move 取运镜 20 类之一
  R17 STATIC_POV_PARAMS    camera.move 为 static／pov 时不得携带 amplitude／speed（规范 §3.7.2）
  R18 TRANSITION_SIDE      转场单侧表达：单元内非末镜不得填 transition_out
  R19 GATE                 **11 项镜头语言质量门**（整片 + 逐生成单元）——
                           阈值直接引用 audit_shots.py 的 GATE 与其容差算法，不得另立一套（规范 §4.2）
  R23 REWRITE_LOCK         **外观锚重述检测**（v2.1.0 依 BR-02 新增；**需 --script 提供上游剧本**）——
                           把剧本 characters[].appearance_lock_zh 与 props[].appearance_lock_zh 按标点切段、
                           取 3-gram，与逐镜的「语义字段」（action.*／shot_language.*／camera.from|to／notes）
                           比对；命中即报错。这是全链路**唯一防「错锚」的自动闸门**
                           （锚一旦在逐镜里被写「宽」或写「窄」，下游无人有权纠正）。
  R24 PROP_COVERAGE        **道具覆盖检测**（v2.1.0 依 BR-03 新增；**需 --script**）——
                           某场 props_present 非空时，该场至少有一镜须把它标进 prop_refs；
                           整场漏标即「剧本说它在场、分镜一镜都没拍到」的漏拍。
  R25 GATE_SELF_CHECK      **质量门自声明与复算比对**（v2.1.0 依 BR-10 新增）——
                           quality_gate 的数值字段为可选参考；**填写即须等于由 shots 复算的真值**。
                           模型可写「11 项全通过」而无人比对，是全链路唯一「声明值可被证伪却无人证伪」处。

交付包层规则（SW-007 `shot_prompt_v1`，2026-10-13 新增；形态 pack）：
  R26 MOVE_PARAM_OMISSION  运镜幅度／速度的**省略规则**（规范 §3.7.2）——
                           camera.amplitude 只允许 small／large、camera.speed 只允许 slow／fast，
                           `medium`／`normal` 是「通常省略」的默认值，须留空串。
                           ⚠️ 本条**同时作用于分镜脚本与交付包**：分镜层 v2.1.0 已把该口径写进硬性约束，
                           但当轮**无脚本判据**（CFG-007_SCHEMA.md 曾误称由 R13 判，R13 实为时长区间），
                           导致用例残留一处 `amplitude="medium"` 未被发现。本条即补该缺口。
  R27 PACK_REQUIRED        **交付包必备结构**（规范 §3.1~§3.6、§3.8）——
                           顶层 schema_version／meta／style_bible／units／shots／aigc_meta 齐备；
                           每镜必备 13 字段（含 prompt_zh／prompt_en／style_ref／action／shot_language）；
                           `style_ref` 必须命中 `style_bible.style_id`（§3.8 列**阻断项**）；
                           `character_refs` 必须命中 `characters[].character_id`。
                           这是「分镜层产出是规范字段集真子集」的补全验收——SW-007 的存在理由。
  R28 PACK_APPEARANCE_ECHO **外观复用检测**（规范 §3.4「外观只在此处定义一次」）——
                           把交付包自带的 `characters[].appearance_lock_zh`（及 `_en`）与
                           `prompt_zh`／`prompt_en` **正文**比对；命中即报错。
                           ⚠️ 两侧判据**不同**：中文取**连续 3 字**，英文取**连续 3 个实词**
                           （英文 3 个字符只是词内片段，`the`／`old` 会在任何英文正文里命中——
                           2026-10-13 首跑即误报 773 处，故英文侧先剔停用词再取 n-gram）。
                           与 R23 的分工：R23 管**分镜层的语义字段**不得重述外观（需 --script）；
                           本条管**提示词正文**不得复述外观（用包内 characters，自足）。
                           正文里写的是「这一镜在发生什么」，不是「这个人长什么样」。
  R29 PACK_PROMPT_HYGIENE  **提示词正文卫生**（规范 §3.3／§3.7.6／§6.4）——
                           ① 不得含模型参数指令（`--ar`／`--v`／`--style` 等）；
                           ② 不得含负向残留写法（`（负向：`／`Negative prompt:`／`(negative:`）——
                              负向意图须走 `negative_global` 字段或转写为正向约束句；
                           ③ **风格锚点封闭**：正文不得出现 `style_anchors` 之外的**已知风格词**
                              （词表取自 delivery/config/CFG-002_shot_vocab.yaml 的 style_tags，脚本内置常量）。
  R30 AIGC_META            **AIGC 元数据块规则**（规范 §5.2／§5.3）——
                           `aigc_meta` 仅一份；7 字段齐备；`Label` 恒为 "1"；
                           `ProduceID` 必须等于 `meta.pack_id`（编号可反查生成记录）；
                           `PropagateID` 等于 `ProduceID`、`ContentPropagator` 等于 `ContentProducer`
                           （首次写入的取值规则）。
  R31 PACK_DURATION_LOCK   **时长守恒与不变量**（本层「不改导演决策」的判据）——
                           ① `meta.total_duration_ms` 必须等于各镜 `duration_ms` 之和；
                           ② 若以 `--storyboard` 提供上游，则交付包与上游的**镜数、镜序、逐镜 duration_ms**
                              必须逐项相同——SW-007 是编译表达层，改一个秒数就改了一个导演决策。
  R32 LIGHTING_VOCAB       **光照字段的词表纯度**（投影规则①）——
                           交付包的 `shots[].lighting` 与 `style_bible.lighting_default` 必须是**纯词表值**
                           （`^[a-z][a-z_]*$`，且命中 15 值词表）。上游允许写成「词表值——中文光位说明」，
                           但交付包 schema 不允许；本层须拆分（说明移入 prompt 正文）。

  ⚠️ 口径差异（必须知道）：R19 判定的是**结构化字段是否有值**（SW-006 的产物）；
     audit_shots.py 判定的是**适配投喂文本**（SW-007 的产物）。两者对象不同——
     本层判定通过不等于下游文本判定通过，SW-007 完成后须对文本再跑一次（规范 §4.8）。

用法：
  python validate_output.py                     # 扫描 examples/*.md 内全部 JSON 块（自动配对上/下游）
  python validate_output.py --file out.json     # 校验单个 JSON 文件（真实模型输出）
  python validate_output.py --file out.json --script script.json   # 附带上游剧本 → 启用 R23/R24
  python validate_output.py --file pack.json --storyboard sb.json  # 附带上游分镜 → 启用 R31 时长守恒
  python validate_output.py --json              # 机器可读结果
  python validate_output.py --duration-bounds 4-15   # 覆盖单镜时长区间（秒）

退出码：
  0 = 全部通过 ｜ 1 = 存在失败项 ｜ 2 = 环境缺失依赖或用法错误

依赖：仅标准库（无 pyyaml 依赖）
"""
import sys
import os
import re
import json
import math
import argparse
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))

# ---------------- 封闭枚举（唯一真值来源，改动须同步模板与 CFG-007_SCHEMA.md） ----------------
PURPOSE_ENUM = ["建立", "升级", "转折", "反转", "收束"]
FILL_STAGE_ENUM = ["synopsis", "script", "storyboard", "shot_prompt"]

# 剧本层封闭枚举（2026-10-13 依 SR-09 / SR-02 新增登记）
DIALOGUE_TYPE_ENUM = ["对白", "旁白", "画外音"]
OWNER_ENUM = ["算法作者", "客户", "运维"]      # 缺口台账的闭合责任人
OWNER_CLIENT = "客户"

# 场时长下限（秒）—— 单镜时长下限 4s × 生成单元最少 2 镜（SR-08：场时长＝该场的镜数预算）
SCENE_MIN_SECONDS = 8

# 分镜层封闭枚举（规范 §3.7.1 / §3.7.2 / §3.7.5）
SHOT_SIZE_ENUM = ["extreme_wide", "wide", "full", "medium", "close_up", "extreme_close_up"]
MOVE_ENUM = [
    "static", "push_in", "pull_out", "zoom_in", "zoom_out",
    "pan_left", "pan_right", "tilt_up", "tilt_down",
    "truck_left", "truck_right", "pedestal_up", "pedestal_down",
    "arc", "tracking", "shake_slight", "shake_strong", "pov", "roll_cw", "roll_ccw",
]
NO_PARAM_MOVES = ("static", "pov")   # 不得携带幅度与速度
TRANSITION_ENUM = ["cut", "fade_in", "fade_out", "dissolve", "wipe"]

# 运镜幅度／速度的**省略规则**（规范 §3.7.2，2026-10-13 依 SW-007 补判据 → R26）
#   medium／normal 是「通常省略」的默认值，工程侧一律留空串；只允许强调用的两值。
AMPLITUDE_ENUM = ["", "small", "large"]
SPEED_ENUM = ["", "slow", "fast"]

# 交付包「留空口径」相关（2026-10-13 依评审 PR-02 / PR-04 新增 R33 / R34）——
#   交付 schema 的枚举/vocabRef **不含空串**（门禁会判 `'' is not one of [...]`），
#   故「留空」必须以「省略键」表达。这是本层产出能过 delivery/validate_pack.py 的必要条件。
PACK_ENUM_OPTIONAL = {
    "camera.amplitude": ["small", "medium", "large"],
    "camera.speed": ["slow", "normal", "fast"],
    "camera.height": ["eye_level", "low", "high", "overhead", "ground"],
    "camera.roll": ["level", "dutch", "roll_cw", "roll_ccw"],
    "camera.optics": ["deep_focus", "shallow_focus", "rack_focus",
                      "long_lens_compression", "wide_angle_distortion"],
    "transition_in": ["cut", "fade_in", "fade_out", "dissolve", "wipe"],
    "transition_out": ["cut", "fade_in", "fade_out", "dissolve", "wipe"],
}
VOCABREF_OPTIONAL = ["lighting"]          # pattern ^[a-z][a-z_]*$，空串不匹配
CAMERA_SENTENCE_RE = re.compile(r"(?:^|[.!?]\s+)The camera\b")

# 交付契约字段集的**唯一真值来源**（2026-10-13 依评审 PR-14 新增 R36）——
#   PR-14 的原文担忧是「两处清单不一致会留下『清单外字段无人管』的漏洞」；
#   根治办法不是「再多写一份清单」，而是**从交付 schema 直接读字段集**（不另立一套）。
#   schema 对顶层与各 $defs 均声明 additionalProperties:false，故「多余键」即契约外字段。
PACK_SCHEMA_PATH = os.path.join(
    BASE, "..", "delivery", "schemas", "CFG-006_shot_prompt_pack.v1.schema.json")


def _pack_schema_keys():
    """读交付 schema，返回各层的**契约字段集**；schema 不可得时返回 None（不伪判）。

    ⚠️ 刻意**不做本地副本**：字段集随 schema 升版自动跟随，避免又造一份会陈旧的清单。
    """
    try:
        with open(PACK_SCHEMA_PATH, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return None
    defs = doc.get("$defs") or doc.get("definitions") or {}
    def allow(name):
        return set(((defs.get(name) or {}).get("properties") or {}).keys())
    return {
        "顶层": set((doc.get("properties") or {}).keys()),
        "shot": allow("shot"),
        "unit": allow("unit"),
        "character": allow("character"),
        "meta": allow("meta"),
        "style_bible": allow("styleBible"),
        "aigc_meta": allow("aigcMeta"),
    }

# 光照词表（规范 §3.7.5，15 值；与 delivery/config/CFG-002_shot_vocab.yaml 的 lighting 段一致 → R32）
LIGHT_ENUM = [
    "soft_key_light", "hard_key_light", "rim_light", "backlight", "side_light",
    "top_light", "under_light", "practical_light", "volumetric_light",
    "golden_hour", "blue_hour", "overcast", "neon_night", "candlelight", "moonlight",
]

# 交付包必备顶层段（规范 §3.1 → R27）；characters 规范标「应当」，故单列
PACK_TOP_REQUIRED = ["schema_version", "meta", "style_bible", "units", "shots", "aigc_meta"]
# 每镜必备字段（规范 §3.6 的「必须」级 + style_ref 的阻断项 → R27）
PACK_SHOT_REQUIRED = [
    "shot_id", "unit_id", "scene_no", "shot_no", "shot_size", "camera", "duration_ms",
    "prompt_zh", "prompt_en", "action", "shot_language", "style_ref", "character_refs",
]
# AIGC 元数据块 7 字段（规范 §5.1 → R30）
AIGC_FIELDS = ["Label", "ContentProducer", "ProduceID",
               "ReservedCode1", "ContentPropagator", "PropagateID", "ReservedCode2"]

# 提示词正文卫生（规范 §3.7.6 / §6.4 → R29）
PARAM_INSTR_RE = re.compile(r"--(ar|v|style|seed|no|stylize|chaos|aspect|q|s)\b|--\w+\s*\d")
NEG_RESIDUE_RE = re.compile(r"（负向[:：]|\(负向[:：]|negative\s*prompt\s*[:：]|\(negative\s*[:：]|no\s+negative", re.I)
# 「已知风格词」清单（取自 delivery/config/CFG-002_shot_vocab.yaml 的 style_tags；用于风格锚点封闭检测）
KNOWN_STYLE_TAGS = [
    "赛璐璐", "厚涂", "水彩", "水墨", "油画", "像素", "美式卡通", "欧式绘本",
    "日式动画", "国风", "写实", "三渲二", "平涂", "描边", "网点", "手绘",
]

# 镜头语言质量门阈值 —— **直接引用 audit_shots.py 的 GATE**，不得另立一套（规范 §4.2）
GATE = {
    "运镜覆盖": 1.00,       # 每镜都要有
    "景别覆盖": 1.00,       # 每镜都要有
    "静止镜占比": 0.40,     # 上限
    "运镜类型数": 5,        # 下限
    "单一运镜占比": 0.35,   # 上限
    "角度覆盖": 0.40,
    "光学覆盖": 0.30,
    "构图覆盖": 0.50,
    "轴线覆盖": 0.30,
    "光线覆盖": 0.40,
    "画面结果覆盖": 0.60,
}

# 单镜时长区间（毫秒）—— 默认取 MiniMax H3 口径（唯一 verified 的目标模型）
DURATION_MIN_MS, DURATION_MAX_MS = 4000, 15000

JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)
SHOT_ID_RE = re.compile(r"^S\d{2}-SH\d{3}$")

# 外观锚切段用的标点/空白（R23）：锚串按这些字符切段后再取 3-gram
ANCHOR_SPLIT_RE = re.compile(r"[、，,。；;：:（）()【】\[\]{}／/·\s\"'“”‘’—－\-]+")
ANCHOR_NGRAM = 3          # 命中长度阈值（3 字／3 实词，见下）
SHOT_SEMANTIC_TEXT_KEYS = ("start", "change", "end")   # action.*
SEMANTIC_SL_KEYS = ("composition", "axis", "result")   # shot_language.*

# 外观锚比对（R23／R28）的两侧最小语义单位：
#   中文 → **连续 3 字**（中文 3 字已是一个语义单位）
#   英文 → **连续 3 个实词**（英文 3 个字符只是词内片段！）
#   ⚠️ 2026-10-13 首跑 R28 时，直接对英文锚取 3 字符 → 误报 773 处
#      （`the`／`old` 这类片段出现在任何英文正文里）。英文侧须先剔停用词。
EN_STOPWORDS = frozenset("""
a an the and or but nor so yet of in on at to from with without for by as
is are was were be been being am
his her hers he she it its they them their there here
this that these those then than
into onto over under above below up down out off
not no yes very still just also too only own same such each every both few more most other some any all
if when while because during before after between through about against within upon
do does did doing have has had having will would shall should can could may might must
one two three four five six seven eight nine ten
""".split())
EN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")

# examples/ 内的跨层配对：用于在默认扫描时自动启用跨层规则。
#   值为「该用例的上游文件列表」——SW-007 的交付包**需要两份上游**
#   （剧本出锚、分镜出决策），故此处允许一个用例配多个上游，按形态各归其位。
#   真实产物请用 --script / --storyboard 显式指定上游（本脚本不猜路径）。
EXAMPLES_UPSTREAM = {
    "CASE-001_script-case01.md": ["CASE-004_synopsis-case01.md"],
    "CASE-003_storyboard-case01.md": ["CASE-001_script-case01.md"],
    "CASE-002_shot-prompt-case01.md": ["CASE-001_script-case01.md", "CASE-003_storyboard-case01.md"],
}

RESULT = {"checks": 0, "errors": [], "warnings": []}
QUIET = False
# 当前生效的上游产物：script 供 R23/R24；storyboard 供 R31（时长守恒）。
UPSTREAM = {"doc": None, "src": None, "sb_doc": None, "sb_src": None}


def out(msg=""):
    if not QUIET:
        print(msg)


def ok(msg):
    RESULT["checks"] += 1
    out(f"  [OK]   {msg}")


def err(msg):
    RESULT["errors"].append(msg)
    out(f"  [FAIL] {msg}")


def warn(msg):
    RESULT["warnings"].append(msg)
    out(f"  [WARN] {msg}")


# ---------------- 形态识别与字段抽取 ----------------
def detect_shape(doc):
    """按产物顶层字段识别形态。

    ⚠️ 顺序敏感：交付包（pack）与分镜脚本（storyboard）**都有 units 与 shots**，
    故必须先判 pack（凭 aigc_meta + schema_version，二者是分镜层不产出的字段），
    否则交付包会被误判为分镜脚本、整段规则跑错对象。
    """
    if not isinstance(doc, dict):
        return None
    if "aigc_meta" in doc and "schema_version" in doc:
        return "pack"
    if "acts" in doc:
        return "script"
    if "shots" in doc and "units" in doc:
        return "storyboard"
    if "scenes_outline" in doc:
        return "synopsis"
    return None


def iter_scenes(doc, shape):
    """产出 (场号, purpose, est_seconds, 定位串) 四元组，屏蔽两种形态差异。"""
    if shape == "script":
        for ai, act in enumerate(doc.get("acts") or []):
            for si, sc in enumerate(act.get("scenes") or []):
                yield (sc, f"acts[{ai}].scenes[{si}]")
    else:
        for si, sc in enumerate(doc.get("scenes_outline") or []):
            yield (sc, f"scenes_outline[{si}]")


# ---------------- 规则实现 ----------------
def rule_purpose_enum(doc, shape, where):
    """R1：purpose 封闭枚举（本脚本首要规则）。"""
    seen = 0
    bad = []
    for sc, loc in iter_scenes(doc, shape):
        if not isinstance(sc, dict):
            continue
        seen += 1
        val = sc.get("purpose")
        if val is None:
            bad.append(f"{loc}.purpose 缺失")
        elif val not in PURPOSE_ENUM:
            bad.append(f"{loc}.purpose = 『{val}』")
    if bad:
        err(f"{where} · R1 PURPOSE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    elif seen:
        ok(f"{where} · R1 PURPOSE_ENUM：{seen} 处 purpose 全部落在五值枚举内")
    else:
        warn(f"{where} · R1 PURPOSE_ENUM：未找到任何场次（跳过）")


def rule_fill_stage_enum(doc, where):
    """R2：unspecified[].fill_stage 封闭枚举。"""
    items = doc.get("unspecified") or []
    if not isinstance(items, list) or not items:
        warn(f"{where} · R2 FILL_STAGE_ENUM：无 unspecified 条目（跳过）")
        return
    bad = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            bad.append(f"unspecified[{i}] 非对象")
            continue
        val = it.get("fill_stage")
        if val not in FILL_STAGE_ENUM:
            bad.append(f"unspecified[{i}].fill_stage = 『{val}』")
    if bad:
        err(f"{where} · R2 FILL_STAGE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R2 FILL_STAGE_ENUM：{len(items)} 条 fill_stage 全部落在四值枚举内")


def rule_scene_no_continuity(doc, shape, where):
    """R3：场号从 1 起连续、不重复。"""
    nos = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            nos.append(sc.get("no"))
    if not nos:
        warn(f"{where} · R3 SCENE_NO_CONTINUITY：无场号可校（跳过）")
        return
    if any(not isinstance(n, int) for n in nos):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：存在非整数场号 → {nos}")
        return
    if sorted(nos) != list(range(1, len(nos) + 1)):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：场号应为 1..{len(nos)}，实际 {nos}")
    else:
        ok(f"{where} · R3 SCENE_NO_CONTINUITY：场号 1..{len(nos)} 连续且唯一")


def rule_est_seconds_sum(doc, shape, where):
    """R4：total_est_seconds == Σ est_seconds。"""
    total = doc.get("total_est_seconds")
    vals = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            vals.append(sc.get("est_seconds"))
    if total is None:
        err(f"{where} · R4 EST_SECONDS_SUM：缺 total_est_seconds")
        return
    if any(not isinstance(v, (int, float)) for v in vals):
        err(f"{where} · R4 EST_SECONDS_SUM：存在非数值 est_seconds → {vals}")
        return
    s = sum(vals)
    if s != total:
        err(f"{where} · R4 EST_SECONDS_SUM：Σest_seconds={s} ≠ total_est_seconds={total}")
    else:
        ok(f"{where} · R4 EST_SECONDS_SUM：Σ{len(vals)} 场 = {s} = total_est_seconds")


def rule_required_keys(doc, shape, where):
    """R5：按形态核对必备顶层字段。

    ⚠️ 交付包（pack）不在本表内——它的必备结构由 R27 单独核对（顶层六段 + 逐镜 13 字段），
    两处口径若都写会互相打架。此处用 `.get()` 兜底，确保误入也不会 KeyError。
    """
    need = {
        "synopsis": ["title", "logline", "protagonist", "supporting", "world",
                     "conflict", "scenes_outline", "ending", "forbidden_items",
                     "total_est_seconds", "unspecified"],
        "script": ["title", "logline", "genre", "style_bible", "characters", "props", "acts",
                   "forbidden_items", "total_est_seconds", "unspecified"],
        "storyboard": ["title", "genre", "style_ref", "aspect_ratio_default",
                       "total_duration_ms", "units", "shots", "forbidden_items",
                       "unspecified", "quality_gate"],
    }.get(shape)
    if need is None:
        return
    miss = [k for k in need if k not in doc]
    if miss:
        err(f"{where} · R5 REQUIRED_KEYS（{shape}）：缺 {miss}")
    else:
        ok(f"{where} · R5 REQUIRED_KEYS（{shape}）：{len(need)} 个必备顶层字段齐备")


def rule_act_structure(doc, where):
    """R6（仅 script）：恰为 3 幕，且每场 act_no 与所属幕一致。"""
    acts = doc.get("acts")
    if not isinstance(acts, list) or not acts:
        err(f"{where} · R6 ACT_STRUCTURE：acts 缺失或为空")
        return
    if len(acts) != 3:
        err(f"{where} · R6 ACT_STRUCTURE：幕数应为 3，实际 {len(acts)}")
        return
    bad = []
    for ai, act in enumerate(acts):
        if not isinstance(act, dict):
            bad.append(f"acts[{ai}] 非对象")
            continue
        expect = act.get("act_no")
        for si, sc in enumerate(act.get("scenes") or []):
            if isinstance(sc, dict) and sc.get("act_no") != expect:
                bad.append(f"acts[{ai}].scenes[{si}].act_no={sc.get('act_no')} 与幕 act_no={expect} 不一致")
    if bad:
        err(f"{where} · R6 ACT_STRUCTURE：{len(bad)} 处不一致 → " + "；".join(bad[:5]))
    else:
        ok(f"{where} · R6 ACT_STRUCTURE：3 幕齐备，各场 act_no 归属一致")


# ---------------- 剧本层补充规则（SW-005 · script_v1 v2.0.0 · 依 SR-02 / SR-08 / SR-09） ----------------
def rule_dialogue_type(doc, where):
    """R20：dialogue[].type 仅限「对白／旁白／画外音」（SR-09）。"""
    entries = []
    for ai, act in enumerate(doc.get("acts") or []):
        if not isinstance(act, dict):
            continue
        for si, sc in enumerate(act.get("scenes") or []):
            if not isinstance(sc, dict):
                continue
            for di, d in enumerate(sc.get("dialogue") or []):
                if isinstance(d, dict):
                    entries.append((f"acts[{ai}].scenes[{si}].dialogue[{di}]", d.get("type")))
    if not entries:
        warn(f"{where} · R20 DIALOGUE_TYPE_ENUM：无对白条目（跳过）")
        return
    bad = [f"{loc}.type = 『{v}』" for loc, v in entries if v not in DIALOGUE_TYPE_ENUM]
    if bad:
        err(f"{where} · R20 DIALOGUE_TYPE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R20 DIALOGUE_TYPE_ENUM：{len(entries)} 条 dialogue.type 全部落在三值枚举内")


def rule_unspecified_owner(doc, shape, where):
    """R21：缺口台账 owner 枚举；且「客户侧缺口不得前移」（SR-02）。

    shape == script     → owner=客户 者 fill_stage 必须为 script（本层，发起追问的阶段）
    shape == storyboard → 按「继承项 / 本层新增项」二分判定（v2.1.0 依 BR-06 收紧）：
                          · 继承项（`upstream_field` 非空）——追问阶段在剧本层**已定**，
                            本层**不得改写**，故 `fill_stage` 必须仍为 `script`；
                          · 本层新增项（`upstream_field` 为空）——追问由本层发出，
                            `fill_stage` 应为 `storyboard`；
                          · 两者共同底线：**`fill_stage` 一律不得为 `shot_prompt`**
                            （下游同样无权补叙事事实与设计确认）。
    """
    items = doc.get("unspecified") or []
    if not isinstance(items, list) or not items:
        warn(f"{where} · R21 UNSPECIFIED_OWNER：无 unspecified 条目（跳过）")
        return
    objs = [it for it in items if isinstance(it, dict)]
    if not any("owner" in it for it in objs):
        warn(f"{where} · R21 UNSPECIFIED_OWNER：条目均未含 owner（跳过；synopsis 层未定义该字段）")
        return
    bad = []
    for i, it in enumerate(objs):
        o = it.get("owner")
        fs = it.get("fill_stage")
        if o not in OWNER_ENUM:
            bad.append(f"unspecified[{i}].owner = 『{o}』")
        elif o == OWNER_CLIENT:
            if shape == "script" and fs != "script":
                bad.append(f"unspecified[{i}] owner=客户 但 fill_stage=『{fs}』"
                           f"（须为 script——本层发起追问，下游无人能补）")
            elif shape == "storyboard":
                inherited = str(it.get("upstream_field") or "").strip()
                if fs == "shot_prompt":
                    bad.append(f"unspecified[{i}] owner=客户 但 fill_stage=『shot_prompt』"
                               f"（不得前移至下游——下游同样无权补）")
                elif inherited and fs != "script":
                    bad.append(f"unspecified[{i}] 继承项（upstream_field=『{inherited}』）"
                               f"owner=客户 但 fill_stage=『{fs}』"
                               f"（继承项的追问阶段由剧本层定，本层不得改写为 『{fs}』）")
    if bad:
        err(f"{where} · R21 UNSPECIFIED_OWNER：{len(bad)} 处不合规 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R21 UNSPECIFIED_OWNER：{len(objs)} 条 owner 合规，"
           f"客户侧缺口均未前移至下游")


def rule_scene_duration_floor(doc, shape, where):
    """R22：每场 est_seconds ≥ SCENE_MIN_SECONDS（场时长＝该场镜数预算，SR-08）。"""
    bad, seen = [], 0
    for sc, loc in iter_scenes(doc, shape):
        if not isinstance(sc, dict):
            continue
        v = sc.get("est_seconds")
        if not isinstance(v, (int, float)):
            bad.append(f"{loc}.est_seconds 非数值（{v}）")
            continue
        seen += 1
        if v < SCENE_MIN_SECONDS:
            bad.append(f"{loc}.est_seconds={v} < {SCENE_MIN_SECONDS}")
    if not seen:
        warn(f"{where} · R22 SCENE_DURATION_FLOOR：无场次可校（跳过）")
        return
    if bad:
        err(f"{where} · R22 SCENE_DURATION_FLOOR：{len(bad)} 处低于下限 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R22 SCENE_DURATION_FLOOR：{seen} 场 est_seconds 均 ≥ {SCENE_MIN_SECONDS}s"
           f"（下游单镜下限 4s × 单元最少 2 镜）")


# ---------------- 分镜层规则（SW-006 · storyboard_v1） ----------------
def _shots(doc):
    return [r for r in (doc.get("shots") or []) if isinstance(r, dict)]


def _units(doc):
    return [u for u in (doc.get("units") or []) if isinstance(u, dict)]


def _cam(r):
    c = r.get("camera")
    return c if isinstance(c, dict) else {}


def _sl(r):
    s = r.get("shot_language")
    return s if isinstance(s, dict) else {}


def rule_shot_id_format(doc, where):
    """R7：shot_id 唯一且形如 S<场号两位>-SH<镜号三位>。"""
    shots = _shots(doc)
    if not shots:
        err(f"{where} · R7 SHOT_ID_FORMAT：shots 缺失或为空")
        return
    ids = [r.get("shot_id") for r in shots]
    bad = [i for i in ids if not (isinstance(i, str) and SHOT_ID_RE.match(i))]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if bad:
        err(f"{where} · R7 SHOT_ID_FORMAT：格式不合规 → {bad[:6]}")
    if dup:
        err(f"{where} · R7 SHOT_ID_FORMAT：编号重复 → {dup}")
    if not bad and not dup:
        ok(f"{where} · R7 SHOT_ID_FORMAT：{len(ids)} 个 shot_id 格式合规且唯一")


def rule_shot_no_seq(doc, where):
    """R8：同一场内 shot_no 从 1 起连续、不跳号。"""
    shots = _shots(doc)
    if not shots:
        return
    groups = {}
    for r in shots:
        groups.setdefault(r.get("scene_no"), []).append(r.get("shot_no"))
    bad = []
    for sc, nos in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if any(not isinstance(n, int) for n in nos):
            bad.append(f"场 {sc} 存在非整数镜号 {nos}")
        elif sorted(nos) != list(range(1, len(nos) + 1)):
            bad.append(f"场 {sc} 镜号应为 1..{len(nos)}，实际 {sorted(nos)}")
    if bad:
        err(f"{where} · R8 SHOT_NO_SEQ：" + "；".join(bad[:5]))
    else:
        ok(f"{where} · R8 SHOT_NO_SEQ：{len(groups)} 个场内镜号均连续")


def rule_unit_link(doc, where):
    """R9：units 与 shots 双向一致，成员镜的 scene_no 等于所属单元的 scene_no，
    且 shot_ids 按镜序递增（v2.1.0 依 BR-11 补——此前逆序单元无判据）。"""
    units, shots = _units(doc), _shots(doc)
    by_id = {r.get("shot_id"): r for r in shots}
    uids = [u.get("unit_id") for u in units]
    bad = []
    if len(set(uids)) != len(uids):
        bad.append(f"unit_id 重复：{uids}")
    listed = []
    for u in units:
        for sid in (u.get("shot_ids") or []):
            listed.append(sid)
            sh = by_id.get(sid)
            if sh is None:
                bad.append(f"{u.get('unit_id')}.shot_ids 引用了不存在的镜头 {sid}")
                continue
            if sh.get("unit_id") != u.get("unit_id"):
                bad.append(f"{sid}.unit_id='{sh.get('unit_id')}' 与所属单元 '{u.get('unit_id')}' 不一致")
            if sh.get("scene_no") != u.get("scene_no"):
                bad.append(f"{sid}.scene_no={sh.get('scene_no')} 与单元场号 {u.get('scene_no')} 不一致")
        # shot_ids 镜序递增（R9 增补，BR-11）
        nos = [(by_id.get(s) or {}).get("shot_no") for s in (u.get("shot_ids") or [])]
        if all(isinstance(n, int) for n in nos) and nos != sorted(nos):
            bad.append(f"{u.get('unit_id')}.shot_ids 未按镜序排列：shot_no={nos}（『顺序即镜序』）")
    orphan = [sid for sid, sh in by_id.items() if sh.get("unit_id") not in uids]
    if orphan:
        bad.append(f"未归入任何单元的镜头：{orphan[:6]}")
    extra = sorted(set(listed) - set(by_id.keys()))
    missing = sorted(set(by_id.keys()) - set(listed))
    if extra:
        bad.append(f"shot_ids 中的多余镜头：{extra[:6]}")
    if missing:
        bad.append(f"未被任何单元收录的镜头：{missing[:6]}")
    if bad:
        err(f"{where} · R9 UNIT_LINK：" + "；".join(bad[:5]))
    else:
        ok(f"{where} · R9 UNIT_LINK：{len(units)} 个单元与 {len(shots)} 个镜头双向一致，场号归属与镜序一致")


def rule_unit_size(doc, where):
    """R10：单元成员数必须为 2 或 3（1 镜单元结构性不合格，规范 §4.3）。"""
    units = _units(doc)
    if not units:
        return
    bad = [f"{u.get('unit_id')} 成员 {len(u.get('shot_ids') or [])} 个（须为 2 或 3）"
           for u in units if len(u.get("shot_ids") or []) not in (2, 3)]
    if bad:
        err(f"{where} · R10 UNIT_SIZE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R10 UNIT_SIZE：{len(units)} 个单元成员数均在 [2,3]")


def rule_unit_move_unique(doc, where):
    """R11：同一单元内 camera.move 取值不得重复。"""
    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in _shots(doc)}
    bad = []
    for u in units:
        moves = [_cam(by_id.get(sid) or {}).get("move") for sid in (u.get("shot_ids") or [])]
        if len(set(moves)) != len(moves):
            bad.append(f"{u.get('unit_id')} 运镜重复 {moves}")
    if bad:
        err(f"{where} · R11 UNIT_MOVE_UNIQUE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R11 UNIT_MOVE_UNIQUE：{len(units)} 个单元内运镜类型均不重复")


def rule_duration(doc, where):
    """R12/R13/R14：整秒 / 区间 / 求和。"""
    shots = _shots(doc)
    if not shots:
        err(f"{where} · R12/13/14 DURATION：shots 为空")
        return
    non_int, out_range, vals = [], [], []
    for r in shots:
        ms = r.get("duration_ms")
        if not isinstance(ms, (int, float)):
            non_int.append(f"{r.get('shot_id')} 非数值")
            continue
        vals.append(ms)
        if ms % 1000 != 0:
            non_int.append(f"{r.get('shot_id')}={ms}")
        if not (DURATION_MIN_MS <= ms <= DURATION_MAX_MS):
            out_range.append(f"{r.get('shot_id')}={ms}")
    if non_int:
        err(f"{where} · R12 DURATION_INT_SECONDS：非整秒 → " + "；".join(non_int[:6]))
    else:
        ok(f"{where} · R12 DURATION_INT_SECONDS：{len(vals)} 镜均为整秒")
    if out_range:
        err(f"{where} · R13 DURATION_BOUNDS：越界（{DURATION_MIN_MS}~{DURATION_MAX_MS}ms）→ "
            + "；".join(out_range[:6]))
    else:
        ok(f"{where} · R13 DURATION_BOUNDS：{len(vals)} 镜均落在 "
           f"{DURATION_MIN_MS // 1000}–{DURATION_MAX_MS // 1000}s")
    total, s = doc.get("total_duration_ms"), sum(vals)
    if total is None:
        err(f"{where} · R14 DURATION_SUM：缺 total_duration_ms")
    elif total != s:
        err(f"{where} · R14 DURATION_SUM：Σduration_ms={s} ≠ total_duration_ms={total}")
    else:
        ok(f"{where} · R14 DURATION_SUM：Σ{len(vals)} 镜 = {s} = total_duration_ms")


def rule_dialogue_speed(doc, where):
    """R15：台词字数 ÷ 秒数 ≤ 9（规范 §4.5）。"""
    over, checked = [], 0
    for r in _shots(doc):
        d = (r.get("dialogue") or "").strip()
        ms = r.get("duration_ms")
        if not d or not isinstance(ms, (int, float)) or ms <= 0:
            continue
        checked += 1
        rate = len(d) / (ms / 1000.0)
        if rate > 9:
            over.append(f"{r.get('shot_id')} {len(d)}字/{ms / 1000:.0f}s≈{rate:.1f}字/秒")
    if over:
        err(f"{where} · R15 DIALOGUE_SPEED：超 9 字/秒 → " + "；".join(over[:6]))
    elif checked:
        ok(f"{where} · R15 DIALOGUE_SPEED：{checked} 处台词语速均 ≤ 9 字/秒")
    else:
        warn(f"{where} · R15 DIALOGUE_SPEED：无台词可校（跳过）")


def rule_enum_values(doc, where):
    """R16：景别取六值之一、运镜取 20 类之一。"""
    shots = _shots(doc)
    bad_size = [f"{r.get('shot_id')}='{r.get('shot_size')}'"
                for r in shots if r.get("shot_size") not in SHOT_SIZE_ENUM]
    bad_move = [f"{r.get('shot_id')}='{_cam(r).get('move')}'"
                for r in shots if _cam(r).get("move") not in MOVE_ENUM]
    if bad_size:
        err(f"{where} · R16 ENUM_VALUES：景别越界 → " + "；".join(bad_size[:6]))
    if bad_move:
        err(f"{where} · R16 ENUM_VALUES：运镜越界 → " + "；".join(bad_move[:6]))
    if not bad_size and not bad_move:
        ok(f"{where} · R16 ENUM_VALUES：{len(shots)} 镜的景别与运镜取值全部合规")


def rule_static_pov_params(doc, where):
    """R17：static／pov 不得携带 amplitude／speed（规范 §3.7.2）。"""
    bad = []
    for r in _shots(doc):
        cam = _cam(r)
        if cam.get("move") in NO_PARAM_MOVES:
            for k in ("amplitude", "speed"):
                if cam.get(k) not in (None, ""):
                    bad.append(f"{r.get('shot_id')}.{k}='{cam.get(k)}'（{cam.get('move')} 不得携带）")
    if bad:
        err(f"{where} · R17 STATIC_POV_PARAMS：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R17 STATIC_POV_PARAMS：static／pov 均未携带幅度与速度")


def rule_transition_side(doc, where):
    """R18：转场单侧表达——单元内非末镜不得填 transition_out。"""
    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in _shots(doc)}
    bad = []
    for u in units:
        for sid in (u.get("shot_ids") or [])[:-1]:
            sh = by_id.get(sid) or {}
            if (sh.get("transition_out") or "").strip():
                bad.append(f"{sid}（{u.get('unit_id')} 非末镜）填了 transition_out='{sh.get('transition_out')}'")
    if bad:
        err(f"{where} · R18 TRANSITION_SIDE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R18 TRANSITION_SIDE：{len(units)} 个单元内非末镜均未填 transition_out")


def _allow(ratio, n):
    """占比门槛 → 绝对个数。与 audit_shots.py 同实现：max(1, ceil(ratio*n))。"""
    return max(1, math.ceil(ratio * n))


def _coverage(rows, getter):
    if not rows:
        return 0.0
    hit = 0
    for r in rows:
        v = getter(r)
        if isinstance(v, str) and v.strip():
            hit += 1
    return hit / len(rows)


def _gate_check(rows):
    """对一组镜头跑 11 项质量门，返回未达标项列表（阈值引用 GATE，算法同 audit_shots.py）。"""
    n = len(rows)
    bad = []
    cov_checks = [
        ("运镜覆盖", lambda r: _cam(r).get("move"), GATE["运镜覆盖"]),
        ("景别覆盖", lambda r: r.get("shot_size"), GATE["景别覆盖"]),
        ("角度覆盖", lambda r: _cam(r).get("height"), GATE["角度覆盖"]),
        ("光学覆盖", lambda r: _cam(r).get("optics"), GATE["光学覆盖"]),
        ("构图覆盖", lambda r: _sl(r).get("composition"), GATE["构图覆盖"]),
        ("轴线覆盖", lambda r: _sl(r).get("axis"), GATE["轴线覆盖"]),
        ("光线覆盖", lambda r: r.get("lighting"), GATE["光线覆盖"]),
        ("画面结果覆盖", lambda r: _sl(r).get("result"), GATE["画面结果覆盖"]),
    ]
    for name, getter, limit in cov_checks:
        v = _coverage(rows, getter)
        if v < limit:
            bad.append(f"{name} {v:.0%} < 门槛 {limit:.0%}")

    st_cnt = sum(1 for r in rows if _cam(r).get("move") == "static")
    st_allow = _allow(GATE["静止镜占比"], n)
    if st_cnt > st_allow:
        bad.append(f"静止镜 {st_cnt}/{n} > 允许 {st_allow}（上限 {GATE['静止镜占比']:.0%}）")

    moves = [m for m in (_cam(r).get("move") for r in rows) if m]
    if moves:
        cnt = Counter(moves)
        top_type, top_cnt = cnt.most_common(1)[0]
        top_allow = _allow(GATE["单一运镜占比"], n)
        if top_cnt > top_allow:
            bad.append(f"单一运镜（{top_type}）{top_cnt}/{n} > 允许 {top_allow}"
                       f"（上限 {GATE['单一运镜占比']:.0%}）")
        need = min(GATE["运镜类型数"], max(2, -(-n // 4)))
        if len(cnt) < need:
            bad.append(f"运镜类型数 {len(cnt)} < 门槛 {need}（{n} 镜，动作贫乏）")
    return bad


def rule_gate(doc, where):
    """R19：11 项镜头语言质量门（整片 + 逐生成单元），阈值引用 audit_shots.py 的 GATE。"""
    shots = _shots(doc)
    if not shots:
        return
    bad_all = _gate_check(shots)
    if bad_all:
        err(f"{where} · R19 GATE（整片 {len(shots)} 镜）：" + "；".join(bad_all[:8]))
    else:
        ok(f"{where} · R19 GATE（整片 {len(shots)} 镜）：11 项全通过")

    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in shots}
    bad_units = []
    for u in units:
        rows = [by_id[s] for s in (u.get("shot_ids") or []) if s in by_id]
        if not rows:
            continue
        b = _gate_check(rows)
        if b:
            bad_units.append(f"{u.get('unit_id')}：" + "；".join(b[:3]))
    if bad_units:
        err(f"{where} · R19 GATE（逐单元）：" + " ‖ ".join(bad_units[:5]))
    else:
        ok(f"{where} · R19 GATE（逐单元）：{len(units)} 个单元 11 项全通过（含 2–3 镜短单元的容差算法）")


# ---------------- 跨层规则（需上游剧本；SW-006 · v2.1.0 依 BR-02 / BR-03） ----------------
def _semantic_text(shot):
    """逐镜「语义字段」文本 —— 即本层被明令不得重述外观的那些字段。

    不含 dialogue／sfx／lighting：台词与光声描述可以合法地提到景物。
    """
    parts = []
    act = shot.get("action")
    if isinstance(act, dict):
        parts += [act.get(k) or "" for k in SHOT_SEMANTIC_TEXT_KEYS]
    sl = _sl(shot)
    parts += [sl.get(k) or "" for k in SEMANTIC_SL_KEYS]
    cam = _cam(shot)
    parts += [cam.get("from") or "", cam.get("to") or ""]
    if isinstance(shot.get("notes"), str):
        parts.append(shot["notes"])
    return "".join(p for p in parts if isinstance(p, str))


def _anchors(upstream):
    """从上游剧本抽出全部外观锚：(标签, 锚串)。"""
    out = []
    for i, ch in enumerate(upstream.get("characters") or []):
        if isinstance(ch, dict) and isinstance(ch.get("appearance_lock_zh"), str):
            out.append((f"characters[{i}].appearance_lock_zh", ch["appearance_lock_zh"]))
    for i, pr in enumerate(upstream.get("props") or []):
        if isinstance(pr, dict) and isinstance(pr.get("appearance_lock_zh"), str):
            out.append((f"props[{i}].appearance_lock_zh", pr["appearance_lock_zh"]))
    return out


def _anchor_ngrams(anchor, n=ANCHOR_NGRAM):
    """中文锚串按标点切段后取 n-**字符** gram（只看段内连续，避免跨标点的伪命中）。"""
    grams = set()
    for seg in ANCHOR_SPLIT_RE.split(anchor or ""):
        if len(seg) < n:
            continue
        for i in range(len(seg) - n + 1):
            grams.add(seg[i:i + n])
    return grams


def _en_content_ngrams(text, n=ANCHOR_NGRAM):
    """英文锚串／正文的 n-**实词** gram（与中文 3 字的对等单位）。

    ⚠️ 为什么英文不能沿用中文的字符 3-gram：中文 3 个字已是一个语义单位，
    而英文 3 个字符只是**词内片段**——`the`（来自 "the right wrist"）、`old`
    （来自 "an old scar"）这类片段会出现在任何一段英文正文里。
    2026-10-13 首跑 R28 即由此产生 **773 处误报**（14 镜 × 每镜数十处），
    规则形同失效。英文的最小语义单位是**实词**，故先剔停用词、再取连续 n 个实词。
    """
    words = [w.lower() for w in EN_WORD_RE.findall(text or "")
             if w.lower() not in EN_STOPWORDS]
    grams = set()
    for i in range(len(words) - n + 1):
        grams.add(" ".join(words[i:i + n]))
    return grams


def rule_rewrite_lock(doc, where):
    """R23：外观锚重述检测（依 BR-02；需上游剧本）。

    判据：剧本 characters[].appearance_lock_zh / props[].appearance_lock_zh 的 3-gram，
    若出现在逐镜的「语义字段」中，即判为「逐字复用锚 = 重述外观」。
    本层只引用（character_refs / prop_refs），不在此处描写外观。
    """
    upstream = UPSTREAM.get("doc")
    if not upstream:
        warn(f"{where} · R23 REWRITE_LOCK：未提供上游剧本（--script），跳过外观锚重述检测")
        return
    anchors = _anchors(upstream)
    if not anchors:
        warn(f"{where} · R23 REWRITE_LOCK：上游无 appearance_lock_zh 可比对（跳过）")
        return
    gram_src = {label: _anchor_ngrams(a) for label, a in anchors}
    bad, checked = [], 0
    for r in _shots(doc):
        text = _semantic_text(r)
        if not text:
            continue
        checked += 1
        hits = []
        for label, grams in gram_src.items():
            got = sorted({g for g in grams if g in text})
            if got:
                hits.append(f"{label}→{'／'.join(got[:4])}")
        if hits:
            bad.append(f"{r.get('shot_id')}：[{'；'.join(hits)}]")
    if bad:
        err(f"{where} · R23 REWRITE_LOCK：{len(bad)} 镜的语义字段重述了外观锚 → " + " ‖ ".join(bad[:4]))
    elif checked:
        ok(f"{where} · R23 REWRITE_LOCK：{checked} 镜的语义字段均未重述外观锚"
           f"（比对 {len(anchors)} 个锚、{ANCHOR_NGRAM}-gram，仅限 action／shot_language／camera.from|to／notes）")
    else:
        warn(f"{where} · R23 REWRITE_LOCK：无逐镜语义文本可校（跳过）")


def _upstream_props_by_scene(upstream):
    """上游 script：场号 → props_present（兼容 script 与 synopsis 两种形态）。"""
    m = {}
    for act in (upstream.get("acts") or []):
        if not isinstance(act, dict):
            continue
        for sc in (act.get("scenes") or []):
            if isinstance(sc, dict):
                m[sc.get("no")] = sc.get("props_present") or []
    for sc in (upstream.get("scenes_outline") or []):
        if isinstance(sc, dict):
            m.setdefault(sc.get("no"), sc.get("props_present") or [])
    return m


def rule_prop_coverage(doc, where):
    """R24：道具覆盖检测（依 BR-03；需上游剧本）。

    判据：某场 props_present 非空 → 该场至少有一镜把它标进 prop_refs。
    整场漏标＝「剧本说它在场、分镜一镜都没拍到」的漏拍（道具锚在提示词层无法落地）。
    """
    upstream = UPSTREAM.get("doc")
    if not upstream:
        warn(f"{where} · R24 PROP_COVERAGE：未提供上游剧本（--script），跳过道具覆盖检测")
        return
    pres = _upstream_props_by_scene(upstream)
    pres = {k: v for k, v in pres.items() if v}
    if not pres:
        ok(f"{where} · R24 PROP_COVERAGE：上游各场 props_present 均为空 → 本层 prop_refs 应全为空（无需比对）")
        return
    by_scene = {}
    for r in _shots(doc):
        by_scene.setdefault(r.get("scene_no"), set()).update(r.get("prop_refs") or [])
    bad = []
    for s, need in sorted(pres.items(), key=lambda kv: str(kv[0])):
        got = by_scene.get(s, set())
        miss = [p for p in need if p not in got]
        if miss:
            bad.append(f"场 {s} props_present={need} 但该场无任一镜标出 {miss}")
    if bad:
        err(f"{where} · R24 PROP_COVERAGE：{len(bad)} 处漏拍 → " + "；".join(bad[:5]))
    else:
        ok(f"{where} · R24 PROP_COVERAGE：{len(pres)} 个有道具的场，均有镜头把道具标进 prop_refs")


def rule_gate_self_check(doc, where):
    """R25：quality_gate 自声明与复算比对（依 BR-10）。

    quality_gate 的数值字段为**可选参考**；填写即须等于由 shots 复算的真值。
    """
    qg = doc.get("quality_gate")
    if not isinstance(qg, dict):
        warn(f"{where} · R25 GATE_SELF_CHECK：无 quality_gate（可选参考，跳过）")
        return
    shots = _shots(doc)
    if not shots:
        return
    n = len(shots)
    moves = [m for m in (_cam(r).get("move") for r in shots) if m]
    truth = {
        "shot_count": n,
        "static_shot_count": sum(1 for r in shots if _cam(r).get("move") == "static"),
        "move_types": sorted(set(moves)),
        "move_type_min_required": min(GATE["运镜类型数"], max(2, -(-n // 4))),
    }
    keys = [k for k in truth if k in qg]
    if not keys:
        ok(f"{where} · R25 GATE_SELF_CHECK：quality_gate 未填数值字段（可选参考；不罚）")
        return
    bad = []
    for k in keys:
        got, exp = qg.get(k), truth[k]
        if k == "move_types":
            got_s = sorted(set(got)) if isinstance(got, list) else got
            if got_s != exp:
                bad.append(f"{k}={got} ≠ 复算 {exp}")
        elif got != exp:
            bad.append(f"{k}={got} ≠ 复算 {exp}")
    if bad:
        err(f"{where} · R25 GATE_SELF_CHECK：自声明与复算不一致 → " + "；".join(bad[:5]))
    else:
        ok(f"{where} · R25 GATE_SELF_CHECK：自声明 {len(keys)} 个数值字段与由 shots 复算的真值一致")


# ---------------- 交付包层规则（SW-007 · shot_prompt_v1，形态 pack） ----------------
def rule_move_param_omission(doc, where):
    """R26：运镜幅度／速度的省略规则（规范 §3.7.2）。

    只允许 amplitude ∈ {空串, small, large}、speed ∈ {空串, slow, fast}；
    medium／normal 是「通常省略」的默认值，工程侧一律留空串。
    本条同时作用于分镜脚本与交付包——它是 v2.1.0 写进硬性约束、却漏了脚本判据的那一条。
    """
    shots = _shots(doc)
    if not shots:
        return
    bad = []
    for r in shots:
        c = _cam(r)
        a, s = c.get("amplitude", None), c.get("speed", None)
        if a is not None and a not in AMPLITUDE_ENUM:
            bad.append(f"{r.get('shot_id')}.camera.amplitude=『{a}』")
        if s is not None and s not in SPEED_ENUM:
            bad.append(f"{r.get('shot_id')}.camera.speed=『{s}』")
    if bad:
        err(f"{where} · R26 MOVE_PARAM_OMISSION：{len(bad)} 处使用默认值当必填值 → "
            + "；".join(bad[:6])
            + "（medium／normal 是「通常省略」的默认值，须留空串）")
    else:
        ok(f"{where} · R26 MOVE_PARAM_OMISSION：{len(shots)} 镜的幅度／速度取值合规"
           f"（只出现空串／small／large 与 空串／slow／fast）")


def rule_pack_no_empty_string(doc, where):
    """R33：交付包可选字段**不得为空串**，留空须「省略该键」（2026-10-13 依评审 PR-02 新增）。

    为什么单列一条：交付 schema 的枚举与 vocabRef **不含空串**——
      · 枚举（amplitude/speed/height/roll/optics/transition_in/transition_out）：
        空串 → `'' is not one of [...]`；
      · vocabRef（lighting）：pattern `^[a-z][a-z_]*$`，空串不匹配；
      · `characters[].ref_image` 为 `type: string` → **null 亦不合法**（须省略键）。
    原口径「medium/normal 规范化为空串」正是由此产出**不合法**的包
    （实测：本案 21 处空串 + 2 处 characters[].ref_image=null → 23 条门禁 BLOCK）。
    注：`shots[].ref_image` 在 schema 是 `oneOf[string,null]`，null **合法**，故不报——
    本规则与门禁**严格对齐**，不写比契约更严的私有口径。
    """
    shots = _shots(doc)
    bad = []
    for r in shots:
        sid = r.get("shot_id")
        cam = r.get("camera") or {}
        for key, allowed in PACK_ENUM_OPTIONAL.items():
            if key.startswith("camera."):
                v = cam.get(key.split(".", 1)[1], None)
            else:
                v = r.get(key, None)
            if v == "":
                bad.append(f"{sid}.{key}=空串（应省略该键）")
            elif v is not None and v not in allowed:
                bad.append(f"{sid}.{key}=『{v}』不在枚举内")
        for key in VOCABREF_OPTIONAL:
            v = r.get(key, None)
            if v == "":
                bad.append(f"{sid}.{key}=空串（应省略该键）")
            elif v is not None and not re.fullmatch(r"[a-z][a-z_]*", str(v)):
                bad.append(f"{sid}.{key}=『{v}』非纯词表 code")
    for c in (doc.get("characters") or []):
        if c.get("ref_image", "MISSING") is None:
            bad.append(f"characters[{c.get('character_id')}].ref_image=null"
                       f"（schema 此处为 type:string → 应省略该键）")
    if bad:
        err(f"{where} · R33 PACK_NO_EMPTY_STRING：{len(bad)} 处 → " + "；".join(bad[:6])
            + "（交付 schema 的枚举/vocabRef 不含空串，留空须省略键）")
    else:
        ok(f"{where} · R33 PACK_NO_EMPTY_STRING：{len(shots)} 镜无可选字段空串、无非法 null")


def rule_pack_en_camera_sentence(doc, where):
    """R34：英文正文须含以 `The camera` 起句的**独立句**（规范 §3.7.2，依评审 PR-04 新增）。

    H3 侧校验器只认连续字符串 `The camera`，且要求成句（不得并入前一句）。
    实测 14 镜中 1 镜违反（`S01-SH002`：把运镜并进了画面叙述句），
    靠人眼逐镜扫必然漏 → 必须脚本化。`static`/`pov` 也须有运镜句
    （如 `The camera holds a static shot.`），只是不带幅度速度。
    """
    shots = _shots(doc)
    bad = [r.get("shot_id") for r in shots
           if (r.get("prompt_en") or "") and not CAMERA_SENTENCE_RE.search(r["prompt_en"])]
    if bad:
        err(f"{where} · R34 EN_CAMERA_SENTENCE：{len(bad)} 镜的 prompt_en 缺以 `The camera` "
            f"起句的独立句 → " + "；".join(str(x) for x in bad[:6]))
    else:
        ok(f"{where} · R34 EN_CAMERA_SENTENCE：{len(shots)} 镜英文运镜句均为独立句")


def rule_pack_no_prop_refs(doc, where):
    """R35：交付包的 shots[] **不得出现 `prop_refs` 键**（依评审 PR-01/PR-14 新增）。

    上游 storyboard_v1 v2.0.0 的 shots[] 含 `prop_refs`，但**交付规范 §3.6 的镜头字段集
    与交付 schema 均无此字段**（规范全文无「道具」二字，已逐字核对），且 schema 的 shot 为
    `additionalProperties: false` → 本层若承继该键会被门禁判「多余属性」而阻断交付。
    本条把「承继守恒」与「交付契约」的这个冲突点**机器可见化**：
    「上游有、本层不该有」不再只写在模板说明里，而是有判据。
    （道具锚的结构化落地须由契约责任方评估 → 规范层缺口 `ISSUE-011`。）
    """
    hits = [r.get("shot_id") for r in _shots(doc) if "prop_refs" in r]
    if hits:
        err(f"{where} · R35 NO_PROP_REFS：{len(hits)} 镜出现 prop_refs 键"
            f"（交付契约无此字段，additionalProperties:false 会拒绝）→ "
            + "；".join(str(x) for x in hits[:6]))
    else:
        ok(f"{where} · R35 NO_PROP_REFS：交付包未出现 prop_refs 结构键（符合交付契约）")


def rule_pack_no_extra_key(doc, where):
    """R36：交付包只允许出现**契约字段集内**的键——多余键一律阻断（依评审 PR-14 新增）。

    PR-14 的原文担忧：「两处清单不一致会留下『**清单外字段无人管**』的漏洞」。
    根因是判据只查「必备」（R27），不查「多余」→ 任何上游带来的、规范里没有的字段
    （如 `shots[].prop_refs`、顶层 `forbidden_items`）都能悄悄进入交付包，
    到门禁才被 `additionalProperties:false` 拦下——**拦得太晚，且只看得到一条汇总报错**。

    本条的字段集**直接读交付 schema**（`single source of truth`，不另写一份清单）：
    schema 对顶层与各 `$defs` 均声明 `additionalProperties:false`，故「多余键」即契约外字段。
    ⚠️ schema 不可读时**跳过（不伪判）**——与 R33 的取舍一致：契约不可得则不下结论。
    """
    S = _pack_schema_keys()
    if not S:
        return
    bad = []
    top_extra = sorted(set(doc) - S["顶层"])
    if top_extra:
        bad.append(f"顶层 {top_extra}")
    for r in _shots(doc):
        e = sorted(set(r) - S["shot"])
        if e:
            bad.append(f"{r.get('shot_id')} {e}")
    for u in (doc.get("units") or []):
        if isinstance(u, dict):
            e = sorted(set(u) - S["unit"])
            if e:
                bad.append(f"unit {u.get('unit_id')} {e}")
    for c in (doc.get("characters") or []):
        if isinstance(c, dict):
            e = sorted(set(c) - S["character"])
            if e:
                bad.append(f"characters[{c.get('character_id')}] {e}")
    for seg, dfn in (("meta", "meta"), ("style_bible", "style_bible"),
                     ("aigc_meta", "aigc_meta")):
        v = doc.get(seg)
        if isinstance(v, dict):
            e = sorted(set(v) - S[dfn])
            if e:
                bad.append(f"{seg} {e}")
    if bad:
        err(f"{where} · R36 NO_EXTRA_KEY：{len(bad)} 处出现**契约字段集之外**的键"
            f"（交付 schema additionalProperties:false 会拒绝）→ " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R36 NO_EXTRA_KEY：顶层/镜头/单元/角色/meta/style_bible/aigc_meta "
           f"均未出现契约外字段（字段集取自交付 schema）")


def rule_pack_required(doc, where):
    """R27：交付包必备结构（规范 §3.1~§3.6、§3.8 阻断项）。"""
    miss = [k for k in PACK_TOP_REQUIRED if k not in doc]
    if miss:
        err(f"{where} · R27 PACK_REQUIRED：顶层缺段 → {miss}")
    sv = doc.get("schema_version")
    if sv != "1.1.0":
        warn(f"{where} · R27 PACK_REQUIRED：schema_version=『{sv}』（当前 schema 为 1.1.0）")
    sb = doc.get("style_bible") if isinstance(doc.get("style_bible"), dict) else {}
    style_id = sb.get("style_id")
    chars = [c for c in (doc.get("characters") or []) if isinstance(c, dict)]
    char_ids = {c.get("character_id") for c in chars}
    if not chars:
        warn(f"{where} · R27 PACK_REQUIRED：characters 缺失或为空（规范标『应当』，无角色的成片可空）")
    shots = _shots(doc)
    if not shots:
        err(f"{where} · R27 PACK_REQUIRED：shots 缺失或为空")
        return
    bad = []
    for r in shots:
        sid = r.get("shot_id")
        for k in PACK_SHOT_REQUIRED:
            v = r.get(k)
            if v is None or (isinstance(v, str) and not v.strip()):
                bad.append(f"{sid}.{k} 缺失／为空")
        if r.get("style_ref") != style_id:
            bad.append(f"{sid}.style_ref=『{r.get('style_ref')}』未命中 style_bible.style_id=『{style_id}』")
        for ref in (r.get("character_refs") or []):
            if ref not in char_ids:
                bad.append(f"{sid}.character_refs 引用未定义角色 『{ref}』")
    if bad:
        err(f"{where} · R27 PACK_REQUIRED：{len(bad)} 处不合规 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R27 PACK_REQUIRED：顶层六段齐备；{len(shots)} 镜必备 13 字段齐备；"
           f"style_ref 全部命中 『{style_id}』；character_refs 全部命中已定义角色")


def _prompt_texts(shot):
    """取出该镜的提示词正文（R28/R29 的扫描对象）。

    ⚠️ 只扫**正文**，不扫字段（字段里的外观锚字串是合法的——那是锚本身）。
    """
    return [shot.get("prompt_zh") or "", shot.get("prompt_en") or ""]


def rule_pack_appearance_echo(doc, where):
    """R28：提示词正文不得复述外观锚（规范 §3.4「外观只在此处定义一次」）。

    用**包内自带**的 characters[].appearance_lock_zh / _en，与 prompt_zh / prompt_en **正文**比。
    两侧判据不同（见 `_en_content_ngrams` 的说明）：中文取 3 字、英文取 3 实词。
    与 R23 的分工：R23 管分镜层的语义字段（需 --script）；本条管提示词正文（自足，不需外部上游）。
    """
    chars = [c for c in (doc.get("characters") or []) if isinstance(c, dict)]
    zh_anchors, en_anchors = [], []
    for c in chars:
        cid = c.get("character_id")
        a = c.get("appearance_lock_zh")
        if isinstance(a, str) and a.strip():
            zh_anchors.append((f"{cid}.appearance_lock_zh", a))
        a = c.get("appearance_lock_en")
        if isinstance(a, str) and a.strip():
            en_anchors.append((f"{cid}.appearance_lock_en", a))
    shots = _shots(doc)
    if not (zh_anchors or en_anchors) or not shots:
        warn(f"{where} · R28 PACK_APPEARANCE_ECHO：无可比对的外观锚（跳过）")
        return
    zh_grams = set()
    for _, a in zh_anchors:
        zh_grams |= _anchor_ngrams(a)
    en_grams = set()
    for _, a in en_anchors:
        en_grams |= _en_content_ngrams(a)

    hits = []
    for r in shots:
        sid = r.get("shot_id")
        # 中文正文：只在**汉字连续段**内取 3 字（避免跨中英混排的伪命中）
        zh_txt = r.get("prompt_zh") or ""
        if zh_grams and zh_txt:
            first = None
            for run in CJK_RUN_RE.findall(zh_txt):
                for i in range(len(run) - ANCHOR_NGRAM + 1):
                    g = run[i:i + ANCHOR_NGRAM]
                    if g in zh_grams:
                        first = g
                        break
                if first:
                    break
            if first:
                hits.append(f"{sid}：中文正文含外观锚片段『{first}』")
        # 英文正文：取实词 3-gram 求交
        en_txt = r.get("prompt_en") or ""
        if en_grams and en_txt:
            inter = _en_content_ngrams(en_txt) & en_grams
            if inter:
                hits.append(f"{sid}：英文正文含外观锚片段『{sorted(inter)[0]}』")
    if hits:
        err(f"{where} · R28 PACK_APPEARANCE_ECHO：{len(hits)} 处正文复述外观 → " + "；".join(hits[:6])
            + "（正文写的是「这一镜在发生什么」，不是「这个人长什么样」）")
    else:
        ok(f"{where} · R28 PACK_APPEARANCE_ECHO：{len(shots)} 镜正文均未复述外观锚"
           f"（比对 {len(zh_anchors)} 条中文锚／{len(en_anchors)} 条英文锚；"
           f"中文 3 字 · 英文 3 实词）")


def rule_pack_prompt_hygiene(doc, where):
    """R29：提示词正文卫生——参数指令／负向残留／风格锚点封闭（规范 §3.3／§3.7.6／§6.4）。"""
    sb = doc.get("style_bible") if isinstance(doc.get("style_bible"), dict) else {}
    anchors = [a for a in (sb.get("style_anchors") or []) if isinstance(a, str)]
    shots = _shots(doc)
    if not shots:
        return
    bad_param, bad_neg, bad_style = [], [], []
    for r in shots:
        sid = r.get("shot_id")
        for txt in _prompt_texts(r):
            if not txt:
                continue
            if PARAM_INSTR_RE.search(txt):
                bad_param.append(sid)
            if NEG_RESIDUE_RE.search(txt):
                bad_neg.append(sid)
            # 风格锚点封闭：正文出现了「已知风格词」，但它不在 style_anchors 的任何一条里
            for tag in KNOWN_STYLE_TAGS:
                if tag in txt and not any(tag in a for a in anchors):
                    bad_style.append(f"{sid}：『{tag}』不在 style_anchors 内")
    if bad_param:
        err(f"{where} · R29 PACK_PROMPT_HYGIENE：正文含模型参数指令 → {sorted(set(bad_param))}"
            f"（参数一律走结构化字段）")
    if bad_neg:
        err(f"{where} · R29 PACK_PROMPT_HYGIENE：正文含负向残留写法 → {sorted(set(bad_neg))}"
            f"（负向意图走 negative_global 或转写为正向约束句）")
    if bad_style:
        err(f"{where} · R29 PACK_PROMPT_HYGIENE：正文出现锚点清单之外的风格词 → "
            + "；".join(sorted(set(bad_style))[:6]))
    if not (bad_param or bad_neg or bad_style):
        ok(f"{where} · R29 PACK_PROMPT_HYGIENE：{len(shots)} 镜正文无参数指令、无负向残留、"
           f"风格词全部落在 {len(anchors)} 条锚内")


def rule_aigc_meta(doc, where):
    """R30：AIGC 元数据块规则（规范 §5.1／§5.2／§5.3）。"""
    am = doc.get("aigc_meta")
    if not isinstance(am, dict):
        err(f"{where} · R30 AIGC_META：aigc_meta 缺失（违反 §5 隐式标识义务）")
        return
    aigc = am.get("AIGC")
    if not isinstance(aigc, dict):
        err(f"{where} · R30 AIGC_META：aigc_meta 缺 AIGC 键")
        return
    miss = [k for k in AIGC_FIELDS if k not in aigc]
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    pack_id = meta.get("pack_id")
    bad = list(f"缺字段 {m}" for m in miss)
    if aigc.get("Label") != "1":
        bad.append(f"Label=『{aigc.get('Label')}』（须为 \"1\"）")
    if pack_id is not None and aigc.get("ProduceID") != pack_id:
        bad.append(f"ProduceID=『{aigc.get('ProduceID')}』≠ meta.pack_id=『{pack_id}』（编号须可反查生成记录）")
    if aigc.get("PropagateID") != aigc.get("ProduceID"):
        bad.append("PropagateID ≠ ProduceID（首次写入须同值）")
    if aigc.get("ContentPropagator") != aigc.get("ContentProducer"):
        bad.append("ContentPropagator ≠ ContentProducer（首次写入须同值）")
    if bad:
        err(f"{where} · R30 AIGC_META：{len(bad)} 处不合规 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R30 AIGC_META：7 字段齐备；Label=\"1\"；ProduceID 与 pack_id 一致；"
           f"传播方首次写入取值正确；文件中仅一份")


def rule_pack_duration_lock(doc, where):
    """R31：时长守恒与「不改导演决策」不变量。"""
    shots = _shots(doc)
    if not shots:
        return
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    total = meta.get("total_duration_ms")
    s = sum(r.get("duration_ms") or 0 for r in shots)
    problems = []
    if total is not None and total != s:
        problems.append(f"meta.total_duration_ms={total} ≠ Σ各镜 duration_ms={s}")
    up = UPSTREAM.get("sb_doc")
    if up is not None:
        up_shots = _shots(up)
        up_ids = [(r.get("shot_id"), r.get("duration_ms")) for r in up_shots]
        now_ids = [(r.get("shot_id"), r.get("duration_ms")) for r in shots]
        if len(up_shots) != len(shots):
            problems.append(f"镜数与上游不一致：上游 {len(up_shots)} vs 本层 {len(shots)}")
        diff = [f"{a[0]}({a[1]}→{b[1]})" for a, b in zip(up_ids, now_ids) if a != b]
        if diff:
            problems.append(f"与上游逐镜不一致（镜号或时长被改动）→ {diff[:6]}")
        up_total = (up.get("total_duration_ms"))
        if up_total is not None and total is not None and up_total != total:
            problems.append(f"总时长与上游不一致：上游 {up_total} vs 本层 {total}")
        if not problems:
            ok(f"{where} · R31 PACK_DURATION_LOCK：Σ={s}ms 自洽；与上游分镜逐镜一致"
               f"（{len(shots)} 镜、镜序与时长均未改动）")
    else:
        if not problems:
            ok(f"{where} · R31 PACK_DURATION_LOCK：Σ各镜 duration_ms={s} 与 meta.total_duration_ms 一致")
    if problems:
        err(f"{where} · R31 PACK_DURATION_LOCK：{len(problems)} 处不守恒 → " + "；".join(problems[:5])
            + "（本层是编译表达层，改一个秒数就改了一个导演决策）")


def rule_lighting_vocab(doc, where):
    """R32：光照字段须为纯词表值（投影规则①；上游的「词表值——说明」形态不得进交付包）。"""
    bad = []
    shots = _shots(doc)
    for r in shots:
        lg = r.get("lighting")
        if lg is None or lg == "":
            continue
        if not isinstance(lg, str) or lg not in LIGHT_ENUM:
            bad.append(f"{r.get('shot_id')}.lighting=『{lg}』")
    sb = doc.get("style_bible") if isinstance(doc.get("style_bible"), dict) else {}
    ld = sb.get("lighting_default")
    if ld not in (None, "") and ld not in LIGHT_ENUM:
        bad.append(f"style_bible.lighting_default=『{ld}』")
    if bad:
        err(f"{where} · R32 LIGHTING_VOCAB：{len(bad)} 处非纯词表值 → " + "；".join(bad[:6])
            + "（须拆分为：字段留词表 code，光位说明移入 prompt 正文）")
    else:
        n = sum(1 for r in shots if r.get("lighting"))
        ok(f"{where} · R32 LIGHTING_VOCAB：{n} 镜 lighting 与 lighting_default 均为纯词表值")


# ---------------- 调度 ----------------
def validate_doc(doc, where):
    shape = detect_shape(doc)
    if shape is None:
        warn(f"{where}：无法识别产物形态（既无 acts／shots 也无 scenes_outline），跳过")
        return
    out(f"\n--- {where}（形态：{shape}）---")
    if shape == "pack":
        # 交付包（SW-007）走的是一套**自足**的规则：
        #   · 顶层必备字段由 R27 统一核对（R5 的 need 表不列 pack，避免两处口径打架）；
        #   · 包内**无 unspecified 台账字段**（规范 §3.1 顶层六段无此段），故 R2 不适用——
        #     上游台账留在上游产物自身，本层不输出、不搬运、不重编号。
        rule_pack_required(doc, where)
        rule_pack_no_prop_refs(doc, where)       # R35
        rule_pack_no_extra_key(doc, where)       # R36
        rule_move_param_omission(doc, where)     # R26（分镜脚本与交付包共用）
        rule_pack_no_empty_string(doc, where)    # R33
        rule_pack_en_camera_sentence(doc, where) # R34
        rule_pack_appearance_echo(doc, where)
        rule_pack_prompt_hygiene(doc, where)
        rule_aigc_meta(doc, where)
        rule_pack_duration_lock(doc, where)
        rule_lighting_vocab(doc, where)
        return
    rule_required_keys(doc, shape, where)
    rule_fill_stage_enum(doc, where)
    if shape == "storyboard":
        rule_shot_id_format(doc, where)
        rule_shot_no_seq(doc, where)
        rule_unit_link(doc, where)
        rule_unit_size(doc, where)
        rule_unit_move_unique(doc, where)
        rule_duration(doc, where)
        rule_dialogue_speed(doc, where)
        rule_enum_values(doc, where)
        rule_static_pov_params(doc, where)
        rule_transition_side(doc, where)
        rule_gate(doc, where)
        rule_gate_self_check(doc, where)
        rule_rewrite_lock(doc, where)
        rule_prop_coverage(doc, where)
        rule_move_param_omission(doc, where)   # R26 同时作用于分镜脚本
        rule_unspecified_owner(doc, shape, where)
        return
    rule_purpose_enum(doc, shape, where)
    rule_scene_no_continuity(doc, shape, where)
    rule_est_seconds_sum(doc, shape, where)
    rule_scene_duration_floor(doc, shape, where)
    if shape == "script":
        rule_act_structure(doc, where)
        rule_dialogue_type(doc, where)
        rule_unspecified_owner(doc, shape, where)


def _load_doc_by_shape(path, shapes=("script", "storyboard", "synopsis")):
    """读出指定形态的产物 JSON。

    一个 .md 用例常含**多个** JSON 块（如 `CASE-001_script-case01.md` 的第 1 块是「上游梗概摘录」、
    第 2 块才是本层输出），故**不能取第一块**——按形态挑选，避免把摘录当成上游产物。
    """
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    blocks = JSON_BLOCK_RE.findall(text) or [text]
    docs = []
    for b in blocks:
        try:
            docs.append(json.loads(b))
        except Exception:
            continue
    for want in shapes:
        for d in docs:
            if detect_shape(d) == want:
                return d
    return docs[0] if docs else None


def scan_examples():
    exp_dir = os.path.join(BASE, "examples")
    if not os.path.isdir(exp_dir):
        warn("examples/ 目录不存在，跳过")
        return
    files = [f for f in sorted(os.listdir(exp_dir)) if f.endswith(".md") and f != "README.md"]
    if not files:
        warn("examples/ 下无可校验样例")
        return
    for fn in files:
        # 自动配对上游（仅 examples 目录内），以启用跨层规则 R23 / R24 / R31。
        # ⚠️ SW-007 的交付包是**双上游**（剧本出锚 + 分镜出决策），故本表的值是**列表**：
        #    列表里按形态自动分流——script 形态进 UPSTREAM["doc"]（供 R23/R24），
        #    storyboard 形态进 UPSTREAM["sb_doc"]（供 R31 逐镜时长守恒）。
        up_fns = EXAMPLES_UPSTREAM.get(fn) or []
        if isinstance(up_fns, str):          # 兼容旧的字符串写法
            up_fns = [up_fns]
        used = []
        for up_fn in up_fns:
            up_doc = _load_doc_by_shape(os.path.join(exp_dir, up_fn))
            if up_doc is None:
                continue
            used.append(up_fn)
            if detect_shape(up_doc) == "storyboard":
                UPSTREAM["sb_doc"], UPSTREAM["sb_src"] = up_doc, up_fn
            else:
                UPSTREAM["doc"], UPSTREAM["src"] = up_doc, up_fn
        with open(os.path.join(exp_dir, fn), encoding="utf-8") as f:
            text = f.read()
        blocks = JSON_BLOCK_RE.findall(text)
        if not blocks:
            warn(f"{fn}：未找到 ```json 代码块")
            continue
        for i, b in enumerate(blocks, 1):
            try:
                doc = json.loads(b)
            except Exception as e:
                err(f"{fn}（第 {i} 个 JSON 块）：解析失败 {e}")
                continue
            suffix = f"（上游＝{' + '.join(used)}）" if used else ""
            validate_doc(doc, f"{fn}#{i}{suffix}")
    UPSTREAM.update({"doc": None, "src": None, "sb_doc": None, "sb_src": None})


def validate_file(path):
    if not os.path.exists(path):
        err(f"文件不存在：{path}")
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 允许传入「裸 JSON」或「含 ```json 块的 md」
    blocks = JSON_BLOCK_RE.findall(text)
    if not blocks:
        blocks = [text]
    for i, b in enumerate(blocks, 1):
        try:
            doc = json.loads(b)
        except Exception as e:
            err(f"{os.path.basename(path)}（第 {i} 个 JSON）：解析失败 {e}")
            continue
        validate_doc(doc, f"{os.path.basename(path)}#{i}")


def main():
    global QUIET, DURATION_MIN_MS, DURATION_MAX_MS
    ap = argparse.ArgumentParser(description="输出契约校验器（封闭枚举、缺口台账 owner 责任归属、场时长下限、分镜层质量门与跨层锚/道具比对）")
    ap.add_argument("--file", help="校验单个 JSON（或含 ```json 块的 .md）文件")
    ap.add_argument("--script", help="上游剧本产物（script_v1 的输出）——提供后启用跨层规则 R23（外观锚重述）与 R24（道具覆盖）")
    ap.add_argument("--storyboard", help="上游分镜产物（storyboard_v1 的输出）——校验交付包时提供，启用 R31 的逐镜纪律（镜数/镜序/duration_ms 逐项相同）")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--duration-bounds", metavar="MIN-MAX",
                    help="单镜时长区间（秒），如 4-15；默认 4-15（MiniMax H3 口径）")
    args = ap.parse_args()
    QUIET = args.json

    if args.duration_bounds:
        try:
            lo, hi = (int(x) for x in args.duration_bounds.split("-"))
            DURATION_MIN_MS, DURATION_MAX_MS = lo * 1000, hi * 1000
        except Exception:
            print(f"[FATAL] --duration-bounds 格式应为 MIN-MAX（秒），收到：{args.duration_bounds}",
                  file=sys.stderr)
            return 2

    if args.script:
        up = _load_doc_by_shape(args.script)
        if up is None:
            print(f"[FATAL] --script 无法解析出 JSON 产物：{args.script}", file=sys.stderr)
            return 2
        UPSTREAM["doc"], UPSTREAM["src"] = up, args.script

    if args.storyboard:
        up = _load_doc_by_shape(args.storyboard)
        if up is None:
            print(f"[FATAL] --storyboard 无法解析出 JSON 产物：{args.storyboard}", file=sys.stderr)
            return 2
        UPSTREAM["sb_doc"], UPSTREAM["sb_src"] = up, args.storyboard

    if not QUIET:
        print("输出契约校验 · validate_output.py")
        print(f"根目录：{BASE}")
        print(f"purpose 枚举：{'／'.join(PURPOSE_ENUM)}")
        print(f"fill_stage 枚举：{'／'.join(FILL_STAGE_ENUM)}")
        print(f"dialogue.type 枚举：{'／'.join(DIALOGUE_TYPE_ENUM)} ｜ "
              f"owner 枚举：{'／'.join(OWNER_ENUM)}（owner=客户 者 fill_stage 须为 script）")
        print(f"场时长下限：{SCENE_MIN_SECONDS}s（单镜 4s × 单元最少 2 镜）")
        print(f"分镜单镜时长区间：{DURATION_MIN_MS // 1000}–{DURATION_MAX_MS // 1000}s"
              f"（质量门阈值引用 audit_shots.py 的 GATE）")
        print(f"跨层规则：R23 外观锚重述 / R24 道具覆盖 / R31 逐镜时长守恒 —— "
              f"剧本上游：{'已载入 ' + str(UPSTREAM['src']) if UPSTREAM['doc'] else '未提供（--script），跨层规则将跳过并告警'}；"
              f"分镜上游：{'已载入 ' + str(UPSTREAM['sb_src']) if UPSTREAM['sb_doc'] else '未提供（--storyboard）'}")

    if args.file:
        validate_file(args.file)
    else:
        scan_examples()

    passed = not RESULT["errors"]
    if args.json:
        print(json.dumps({
            "passed": passed,
            "checks": RESULT["checks"],
            "errors": RESULT["errors"],
            "warnings": RESULT["warnings"],
            "purpose_enum": PURPOSE_ENUM,
            "fill_stage_enum": FILL_STAGE_ENUM,
            "dialogue_type_enum": DIALOGUE_TYPE_ENUM,
            "owner_enum": OWNER_ENUM,
            "scene_min_seconds": SCENE_MIN_SECONDS,
            "shot_size_enum": SHOT_SIZE_ENUM,
            "move_enum": MOVE_ENUM,
            "duration_bounds_ms": [DURATION_MIN_MS, DURATION_MAX_MS],
            "gate": GATE,
            "upstream": UPSTREAM.get("src"),
            "exit_code": 0 if passed else 1,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 52)
        print(f"通过检查项：{RESULT['checks']}")
        print(f"失败：{len(RESULT['errors'])} ｜ 警告：{len(RESULT['warnings'])}")
        print("结论：" + ("✅ 全部通过" if passed else "❌ 存在失败项"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
