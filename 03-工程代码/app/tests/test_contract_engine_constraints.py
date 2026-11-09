# -*- coding: utf-8 -*-
"""`T-096` 线 3 契约下沉的**互锁测试**（`PRO-011` 附 4 方案 A；2026-11-04 授权落地）。

⚠️ **为什么必须互锁**：`FIELD_CONSTRAINTS` 是离线判据常量的**运行期投影**——
投影与真值源各自手写 ⇒ 任一侧单独改值 ⇒ 引擎约束与门禁判据分叉
（引擎放行的门禁拦、或引擎拦了判据放行的）⇒ 与 `schema_version` 三处分叉同族
（缺口 B 家族，`PRO-012` 变更三件套纪律的判据↔测试↔枚举登记三同步）。

⚠️ **真值源**：`prompts/validate_output.py` 的 `SHOT_SIZE_ENUM`／`MOVE_ENUM`／
`LIGHT_ENUM`（离线判据常量；上游真值＝`CFG-002_shot_vocab.yaml` 与规范 §3.7）。
`R6`（acts 恰 3 幕）无枚举常量，与 `TPL-008` v2.1.1 模板条款同源（`config.py`
L172~L173 已登记「不是判据与模板冲突」）。

⚠️ **边界（如实登记）**：本测试锁「工程内三处互等」；
「与 `CFG-002` yaml 相等」由 `R32`／`R16` 判据本身在门禁期对拍（该 yaml 是其登记真值源）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from app.services import artifact_contract

ROOT = Path(r"E:\深度合成算法工程材料\03-工程代码")
OUTPUT_VALIDATOR = ROOT / "prompts" / "validate_output.py"
PACK_SCHEMA = ROOT / "delivery" / "schemas" / "CFG-006_shot_prompt_pack.v1.schema.json"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_script_acts_constraint_is_exactly_three() -> None:
    """`R6`：acts 恰为 3 幕 —— 引擎侧 minItems==maxItems==3（与模板条款一致）。

    ⚠️ `minItems` **必须伴随 `items` 键**（2026-11-04 真机实测：`structured_outputs`
    路径下无 `items` 的 `minItems` 引擎编译期 500——见 `FIELD_CONSTRAINTS` 注释）。
    """
    acts = artifact_contract.FIELD_CONSTRAINTS["script"]["acts"]
    assert acts["minItems"] == 3 and acts["maxItems"] == 3
    assert "items" in acts, "minItems 必须伴随 items 键（否则引擎 500，真机实测）"


def test_storyboard_enums_match_offline_validator() -> None:
    """`R16`：景别六值、运镜 20 类 —— 运行期投影与离线判据常量逐值互等。"""
    vo = _load(OUTPUT_VALIDATOR)
    items = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["shots"]["items"]
    assert items["properties"]["shot_size"]["enum"] == vo.SHOT_SIZE_ENUM
    assert items["properties"]["camera"]["properties"]["move"]["enum"] == vo.MOVE_ENUM


def test_storyboard_camera_param_enums_match_pack_optional() -> None:
    """`R19`（角度/光学）· `R17`/`R26`（amplitude/speed/roll）——camera 五参数的
    运行期投影枚举与判据常量 `PACK_ENUM_OPTIONAL` 逐值互等。

    ⚠️ **同族第三处实证**（n=6 复测）：camera 骨架只列 move ⇒ xgrammar 把
    height/optics 一律禁止 ⇒ R19 角度/光学覆盖**恒 0%**（模型无可写路径）。
    补列后仍【不进 required】——判据口径「默认值＝省略键」（R26），
    本测试断言该语义不被破坏。
    """
    vo = _load(OUTPUT_VALIDATOR)
    cam = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["shots"]["items"][
        "properties"
    ]["camera"]
    for key in ("amplitude", "speed", "height", "roll", "optics"):
        assert cam["properties"][key]["enum"] == vo.PACK_ENUM_OPTIONAL[f"camera.{key}"], (
            f"camera.{key} 枚举与判据常量分叉"
        )
    assert cam["required"] == ["move", "height", "optics"], (
        "camera.required 强化为 [move, height, optics]（2026-11-04 两轮实证：解禁＋模板引导"
        "后模型仍整键省略 ⇒ R19 角度/光学恒 0%；required 是生成引导非事后拒绝）；"
        "amplitude/speed/roll 必须维持可选（R26 默认值=省略键口径）"
    )
    assert not {"amplitude", "speed", "roll"} & set(cam["required"])


def test_storyboard_shot_language_skeleton_lists_gate_fields() -> None:
    """`R19` 六维之构图/轴线/画面结果——shot_language 显式列出三字段（判据引用面）。

    判据只查「有值」（覆盖率门槛）、无枚举 ⇒ 骨架只给 type:string、不设 required。
    """
    sl = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["shots"]["items"][
        "properties"
    ]["shot_language"]
    assert set(sl["properties"]) == {"composition", "axis", "result"}
    assert all(v == {"type": "string"} for v in sl["properties"].values())
    assert "required" not in sl, "六维覆盖率门槛 <100%，禁止引擎强制全镜必填"


#: 分镜层（storyboard）shot 的**真值字段集**——`ISSUE-059` 塌缩回归的互锁锚：
#: ⚠️ xgrammar 把 `items.properties` **未列出的字段一律禁止**（2026-11-04 直连探测
#: 三变体实证：窄 schema ⇒ 塌缩 `{shot_size, camera}`；全字段＋required ⇒ 全出）。
#: 故本清单**必须列全**分镜层真值字段——来源（互锁锚）：
#: ① 离线判据引用面：R7（shot_id）/ R8（shot_no）/ R9（unit_id/scene_no）/ R12（duration_ms）
#:    / R16（shot_size/camera.move）/ R32（lighting）；
#: ② T-098 落地前真实产物字段集（`artifacts_t086/try1/step3.json`，17 键全量对拍）；
#: ③ CFG-007 §职责边界 ⑤「真子集」口径（无 style_ref/prompt_zh/prompt_en 等 SW-007 补齐字段）。
#: 任一侧（真产物字段集 ∪ 判据引用面）出现新字段而本清单未更新 ⇒ 本测试红。
STORYBOARD_SHOT_KEYS_REQUIRED = (
    "shot_id", "unit_id", "scene_no", "shot_no", "shot_size", "camera",
    "duration_ms", "action", "shot_language", "dialogue", "sfx", "lighting",
    "transition_in", "transition_out", "character_refs", "prop_refs", "notes",
)


def test_storyboard_shot_items_list_all_fields() -> None:
    """`ISSUE-059` 反塌缩：items.properties 必须列全真值字段集且全部 required。

    ⚠️ 这是**字段完整性**锁，不是枚举锁：窄骨架（只列部分字段）会让 xgrammar
    把未列字段禁止掉 ⇒ 产物字段塌缩（n=6 跑测 4/4 轮复现，R7/R8/R9/R12 全爆）。
    """
    items = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["shots"]["items"]
    props = set(items["properties"])
    required = set(items["required"])
    missing_props = set(STORYBOARD_SHOT_KEYS_REQUIRED) - props
    missing_required = set(STORYBOARD_SHOT_KEYS_REQUIRED) - required
    assert not missing_props, f"items.properties 缺字段（xgrammar 会禁止之）: {missing_props}"
    assert not missing_required, f"items.required 缺字段: {missing_required}"
    assert props == required == set(STORYBOARD_SHOT_KEYS_REQUIRED), (
        "properties 与 required 应恰好等于真值字段集（不多列、不少列）"
    )
    # soundness：不得设无判据依据的 maxItems（R10 推出 minItems≥2；上限无判据依据）
    shots = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["shots"]
    assert shots.get("minItems") == 2
    assert "maxItems" not in shots, "判据层无整片镜数上限，禁止引擎拒判据允许的产物"


def test_pack_vocabref_enum_matches_light_enum() -> None:
    """`T-098`／`R32`：`CFG-006` 的 `vocabRef` 枚举与判据常量 `LIGHT_ENUM` 逐值互等。"""
    vo = _load(OUTPUT_VALIDATOR)
    schema = json.loads(PACK_SCHEMA.read_text(encoding="utf-8"))
    vr = schema["$defs"]["vocabRef"]
    assert vr["enum"] == vo.LIGHT_ENUM
    assert "pattern" not in vr, "pattern 应已由 enum 取代（否则引擎仍放行非词表值）"


def test_storyboard_quality_gate_numeric_fields_engine_forbidden() -> None:
    """`R25` 收口互锁（2026-11-05，`T-087` 余项）：`quality_gate` 引擎字段面仅 `self_check`。

    ⚠️ 依据：`BR-12`「统计量不由模型承诺」＋ 2026-11-04 冒烟实测（17 镜产物
    `shot_count=22 ≠ 复算 17`、`move_types` 混入转场词表值 fade_in/fade_out/cut）。
    v2.2.0 只移 `move_type_min_required` 的「前三个数值字段实测可靠」是 3 镜小样本
    结论，n=17 即崩 ⇒ 引擎收窄到叙述性字段 ⇒ `R25` 回到「未填数值字段不罚」合法态。
    判据 `R25` 零改动（仍逐项比对任何自发填写的数值字段——本约束只作用于受约束
    解码路径）。
    """
    qg = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["quality_gate"]
    assert set(qg["properties"]) == {"self_check"}, (
        "quality_gate 数值字段必须被引擎禁止（xgrammar 未列即禁止）；"
        "若恢复数值字段须连同 v2.2.0→v2.2.4 的全部实测证据一并复审"
    )
    assert qg["properties"]["self_check"] == {"type": "string"}
    assert "required" not in qg, "self_check 是叙述性参考，不强制（对象本身由顶层 required 保底）"
    assert "quality_gate" in artifact_contract.REQUIRED_TOP_KEYS["storyboard"]


def test_storyboard_units_skeleton_matches_pack_contract() -> None:
    """`ISSUE-058` units 骨架互锁：字段集与 required 与 CFG-006 `$defs/unit` 逐项相等。

    ⚠️ **为什么锁 CFG-006**：`R36 NO_EXTRA_KEY` 的唯一真值来源就是交付 schema
    （`_pack_schema_keys()` 直读、不另立副本）——units 字段集的契约真值＝该处
    `properties` 键集；本测试把运行期投影锁到同一真值源，防三处分叉同族缺口。
    首版无 items ⇒ 模型在自由文本上退化 ramble 至 8192（n=6 两轮 storyboard
    "all" 段 `finish_reason=length`，502 `segment_truncated`）。
    """
    schema = json.loads(PACK_SCHEMA.read_text(encoding="utf-8"))
    unit_def = schema["$defs"]["unit"]
    units = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["units"]
    items = units["items"]
    assert set(items["properties"]) == set(unit_def["properties"]), (
        "units 字段集必须与 CFG-006 $defs/unit 相等（R36 契约真值）"
    )
    assert items["required"] == unit_def["required"], (
        "units.required 必须与契约 required 相等（notes 契约级可选）"
    )
    # 引擎边界纪律：minItems 必须伴随 items（否则 structured_outputs 编译 500）
    assert "items" in units and units.get("minItems") == 1
    # soundness：单元数无判据上限，禁止引擎拒判据允许的产物
    assert "maxItems" not in units


def test_storyboard_units_shot_ids_bounds_match_r10() -> None:
    """`R10 UNIT_SIZE`：成员恰为 2 或 3 —— 引擎投影 minItems=2 / maxItems=3。"""
    units = artifact_contract.FIELD_CONSTRAINTS["storyboard"]["units"]
    shot_ids = units["items"]["properties"]["shot_ids"]
    assert shot_ids["minItems"] == 2 and shot_ids["maxItems"] == 3
    assert shot_ids["items"] == {"type": "string"}
    assert shot_ids["type"] == "array"


def test_derived_schema_merges_constraints() -> None:
    """`derived_engine_schema` 必须把 `FIELD_CONSTRAINTS` 合入 properties；未登记键仍为空 schema。"""
    s = artifact_contract.derived_engine_schema("script")
    assert s is not None
    assert s["properties"]["acts"] == {
        "type": "array", "items": {}, "minItems": 3, "maxItems": 3,
    }
    assert s["properties"]["title"] == {}  # 未登记键保持空 schema（不凭空补类型）
    assert s["required"] == list(artifact_contract.REQUIRED_TOP_KEYS["script"])
    # synopsis 无登记条目 ⇒ 全空 schema（行为不变）
    s2 = artifact_contract.derived_engine_schema("synopsis")
    assert all(v == {} for v in s2["properties"].values())  # type: ignore[union-attr]


def test_field_constraints_keys_are_within_required_keys() -> None:
    """约束键必须是该形态顶层必需键的子集（约束一个非必需键 = 自造口径）。"""
    for shape, cons in artifact_contract.FIELD_CONSTRAINTS.items():
        need = artifact_contract.REQUIRED_TOP_KEYS[shape]
        unknown = set(cons) - set(need)
        assert not unknown, f"{shape} 的约束键超出必需键集：{unknown}"
