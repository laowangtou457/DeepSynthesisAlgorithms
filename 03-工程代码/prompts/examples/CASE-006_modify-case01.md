# modify-case01 · 对话式修改与跨阶段一致性校验（产物迭代入口）

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-MOD-001` |
| 对应需求 | **SW-002 对话式修改**（通用迭代入口：对「当前阶段产物」做定向修改、保持跨阶段一致性；异常＝修改意见含糊时澄清） |
| 主模板 | `modify_v1` **v1.1.0**（业务链路**支撑模板**，**刻意不填 `stage`**——与链路阶段正交，见其版本说明） |
| 连带模板 | `check_consistency_v1` **v1.1.0**（一致性校验侧，`pair_role=before_after`） |
| 产物形态参照 | `CASE-003_storyboard-case01.md`（分镜产物形态）。⚠️ 本用例**自带一份精简产物**（4 镜 / 2 单元）而非引用该用例全文——目的是让「修改前 ↔ 修改后」**可逐字比对**；`CASE-003` 的产物规模（13 镜）会让变更说明与漂移报告淹没在噪声里 |
| 用例来源 | **构造用例**（修改意见为人为设计，含 6 处陷阱位；正式使用前须补一组脱敏真实客户意见） |
| 采样参数 | temperature 0.2 / top_p 0.85 / top_k 40 / max_tokens 8192（**受约束解码**；温度取全库最低档）。⚠️ **订正（`v1.1.0` 依评审 §3.2 温度项）**：低温**不是**「顺手多改」的防线——多改的成因是模型自认为的"规范化"，**不是采样随机性**；真正的防线是 `guards` 第 1 条的全文差异清单。 |
| 记录日期 | 2026-10-14 |
| **验证状态** | ⚠️ **未验证**——未跑模型。以下产物为**人工按模板纪律构造**，用于固化判据口径与陷阱位；实测须待模型就绪后由 `tests/` 下的负向样本与人工抽检（SW-002 验收要求 **≥30 例**）共同承担 |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `target_stage` | **`storyboard`** —— 被改对象是**分镜脚本阶段**的产物。⚠️ 该值取自**产物自身**的阶段属性，**不是**本模板的运行阶段（`modify_v1` 无 `stage`） |
| `current_artifact` | 见 **§2.1**（4 镜 / 2 单元 / 18000ms） |
| `modification_request` | 见 **§2.2**（客户原话，**两句、含两个独立意图**） |
| `change_context` | **无**（首轮修改） |
| `upstream_artifact` | **无** —— ⚠️ 本用例刻意如此：这样「零漂移只能以当前产物自身为基准」这一**局限**就必须被显式登记进 `unresolved`（模板 `guards` 的「上游基准明示核对」），而不是被悄悄省略 |
| `locked_paths` | `shots[*].shot_id`、`units[*].unit_id`、`units[*].shot_ids`、`shots[*].scene_no`、`shots[*].character_refs`、`title`（锚与编号，以及本用例额外锁定的产目标题） |

### 2.1 修改前产物（`current_artifact`）

```json
{
  "title": "夜班便利 · 第3集",
  "genre": "都市悬疑短剧",
  "style_ref": "STYLE-01",
  "aspect_ratio_default": "16:9",
  "total_duration_ms": 18000,
  "units": [
    {
      "unit_id": "U01",
      "scene_no": 1,
      "shot_ids": ["S01-SH001", "S01-SH002"],
      "soundscape": "雨刚停，屋檐断续滴水；远处偶有车声",
      "music": "N/A",
      "notes": "对应剧本第 1 场 action 节点①②（空间／主体）"
    },
    {
      "unit_id": "U02",
      "scene_no": 1,
      "shot_ids": ["S01-SH003", "S01-SH004"],
      "soundscape": "店内冷柜低频嗡鸣；雨声转闷",
      "music": "N/A",
      "notes": "对应剧本第 1 场 action 节点③④（状态／收束）"
    }
  ],
  "shots": [
    {
      "shot_id": "S01-SH001",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 1,
      "shot_size": "wide",
      "camera": {
        "move": "push_in",
        "amplitude": "small",
        "speed": "slow",
        "from": "楼道口外三米、齐腰高度",
        "to": "停在 CHR-01 肩背",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 5000,
      "shot_language": {
        "composition": "CHR-01 落在画面右三分，左三分之一是楼道纵深",
        "axis": "空间轴：画面左＝楼道口（暗）、画面右＝街面（亮）",
        "result": "雨水顺袖口成股下淌，在脚边积出一小滩"
      },
      "action": {
        "start": "CHR-01 背身站在楼道口外",
        "change": "雨幕在她肩后收窄",
        "end": "她抬手抹了一下后颈"
      },
      "lighting": "neon_night——沿街招牌的暖光落在湿路面上，右半画面被垫亮",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "notes": "对应剧本第 1 场 action 节点①"
    },
    {
      "shot_id": "S01-SH002",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 2,
      "shot_size": "full",
      "camera": {
        "move": "static",
        "from": "CHR-01 蹲在长椅前，袋口朝向镜头",
        "to": "保持不动",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus"
      },
      "duration_ms": 4000,
      "shot_language": {
        "composition": "CHR-01 居中偏低，长椅横穿画面下三分之一",
        "axis": "沿用 U01 空间轴，不越轴",
        "result": "鞋带被系紧，袋口的热气在冷空气里淡下去"
      },
      "action": {
        "start": "CHR-01 蹲下",
        "change": "把手里的便利袋放到长椅上",
        "end": "系好鞋带"
      },
      "lighting": "practical_light——店内灯管从背后透出，长椅面上泛一层冷白",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "notes": "对应剧本第 1 场 action 节点②"
    },
    {
      "shot_id": "S01-SH003",
      "unit_id": "U02",
      "scene_no": 1,
      "shot_no": 3,
      "shot_size": "close_up",
      "camera": {
        "move": "tilt_up",
        "amplitude": "small",
        "speed": "slow",
        "from": "袋口特写、热气起点",
        "to": "抬起至 CHR-01 下颌线",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 5000,
      "shot_language": {
        "composition": "袋口落在画面中心，前景遮住 CHR-01 的下半张脸",
        "axis": "沿用 U01 空间轴",
        "result": "热气在冷空气里拉成一条细白线"
      },
      "action": {
        "start": "CHR-01 低头看袋口",
        "change": "视线随热气上移",
        "end": "眼神停住"
      },
      "lighting": "practical_light——冷柜灯自下打上来，热气在光柱里显形",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "notes": "对应剧本第 1 场 action 节点③"
    },
    {
      "shot_id": "S01-SH004",
      "unit_id": "U02",
      "scene_no": 1,
      "shot_no": 4,
      "shot_size": "medium",
      "camera": {
        "move": "pull_out",
        "amplitude": "small",
        "speed": "slow",
        "from": "CHR-01 半身",
        "to": "退出至便利店整排货架",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus"
      },
      "duration_ms": 4000,
      "shot_language": {
        "composition": "末帧收在货架纵深，CHR-01 退为左下角剪影",
        "axis": "沿用 U01 空间轴",
        "result": "画面收束在冷白灯管与货架之间"
      },
      "action": {
        "start": "CHR-01 仍蹲在长椅前",
        "change": "机位后拉，环境纳入画面",
        "end": "人物留在画面左下"
      },
      "lighting": "practical_light——货架灯管沿纵深排开，末帧收在冷白灯管之间",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "notes": "对应剧本第 1 场 action 节点④"
    }
  ],
  "forbidden_items": ["真实品牌 logo", "血腥画面"],
  "unspecified": [
    {
      "field": "shots[*].duration_ms",
      "upstream_field": "",
      "reason": "上游剧本未给任何单镜时长，本层按动作量估时",
      "owner": "算法作者",
      "fill_stage": "storyboard",
      "fill_fallback": "按动作节点数与语速上限估时，交付前由人工复核",
      "blocking": false
    }
  ],
  "quality_gate": {
    "static_ratio": 0.25,
    "move_type_count": 4
  }
}
```

⚠️ 4 镜均带 `lighting`（**分镜层口径**：`词表值——中文光位说明`，与 `CASE-003` 同形态；
`R32` 的「纯词表值」只约束**交付包**）。这不是可省的美化项——本产物被 examples 扫描按
`storyboard` 形态送进 `validate_output.py` 的 `R19` 质量门，`光线覆盖` 门槛为 **40%**；
缺该字段会让**本用例自身**在闸门上留下 FAIL（首次运行即发生过，已据实补上）。

### 2.2 客户修改意见原文（`modification_request`）

```text
第一镜太短了，拉到 6 秒。另外第二镜的景别改成中景。
```

## 3 动笔前的意图拆解（模板 `system` 硬性约束 3 + `task` 第一步）

| 意图 | 客户原话片段（`basis`） | 改哪里（`target_path`） | 原值（`before`，逐字摘自 §2.1） | 新值（`after`） | 牵连？ |
| --- | --- | --- | --- | --- | --- |
| ① 第 1 镜延长至 6 秒 | 「第一镜太短了，拉到 6 秒」 | `shots[0].duration_ms` | `5000` | `6000` | **有**：整片总时长必须随之变（`duration_sum`） |
| ② 第 2 镜景别改中景 | 「第二镜的景别改成中景」 | `shots[1].shot_size` | `full` | `medium` | **无**（判别点，见 §6 陷阱位 5） |

**两条意图 → 三条记录**：意图 ① 的**牵连位置**（`total_duration_ms`）**另占一条记录、共用同一 `basis`**——
这不是「过拆」，而是定向修改与守恒的正确接法（模板 `task` 第二步）。

## 4 修改后产物 + 变更说明（`modify_v1` 的完整输出）

```json
{
  "modify_version": "1.1.0",
  "target_stage": "storyboard",
  "artifact": {
    "title": "夜班便利 · 第3集",
    "genre": "都市悬疑短剧",
    "style_ref": "STYLE-01",
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 19000,
    "units": [
      {
        "unit_id": "U01",
        "scene_no": 1,
        "shot_ids": ["S01-SH001", "S01-SH002"],
        "soundscape": "雨刚停，屋檐断续滴水；远处偶有车声",
        "music": "N/A",
        "notes": "对应剧本第 1 场 action 节点①②（空间／主体）"
      },
      {
        "unit_id": "U02",
        "scene_no": 1,
        "shot_ids": ["S01-SH003", "S01-SH004"],
        "soundscape": "店内冷柜低频嗡鸣；雨声转闷",
        "music": "N/A",
        "notes": "对应剧本第 1 场 action 节点③④（状态／收束）"
      }
    ],
    "shots": [
      {
        "shot_id": "S01-SH001",
        "unit_id": "U01",
        "scene_no": 1,
        "shot_no": 1,
        "shot_size": "wide",
        "camera": {
          "move": "push_in",
          "amplitude": "small",
          "speed": "slow",
          "from": "楼道口外三米、齐腰高度",
          "to": "停在 CHR-01 肩背",
          "height": "eye_level",
          "roll": "level",
          "optics": "shallow_focus"
        },
        "duration_ms": 6000,
        "shot_language": {
          "composition": "CHR-01 落在画面右三分，左三分之一是楼道纵深",
          "axis": "空间轴：画面左＝楼道口（暗）、画面右＝街面（亮）",
          "result": "雨水顺袖口成股下淌，在脚边积出一小滩"
        },
        "action": {
          "start": "CHR-01 背身站在楼道口外",
          "change": "雨幕在她肩后收窄",
          "end": "她抬手抹了一下后颈"
        },
        "lighting": "neon_night——沿街招牌的暖光落在湿路面上，右半画面被垫亮",
        "character_refs": ["CHR-01"],
        "prop_refs": [],
        "notes": "对应剧本第 1 场 action 节点①"
      },
      {
        "shot_id": "S01-SH002",
        "unit_id": "U01",
        "scene_no": 1,
        "shot_no": 2,
        "shot_size": "medium",
        "camera": {
          "move": "static",
          "from": "CHR-01 蹲在长椅前，袋口朝向镜头",
          "to": "保持不动",
          "height": "eye_level",
          "roll": "level",
          "optics": "deep_focus"
        },
        "duration_ms": 4000,
        "shot_language": {
          "composition": "CHR-01 居中偏低，长椅横穿画面下三分之一",
          "axis": "沿用 U01 空间轴，不越轴",
          "result": "鞋带被系紧，袋口的热气在冷空气里淡下去"
        },
        "action": {
          "start": "CHR-01 蹲下",
          "change": "把手里的便利袋放到长椅上",
          "end": "系好鞋带"
        },
        "lighting": "practical_light——店内灯管从背后透出，长椅面上泛一层冷白",
        "character_refs": ["CHR-01"],
        "prop_refs": ["PRP-01"],
        "notes": "对应剧本第 1 场 action 节点②"
      },
      {
        "shot_id": "S01-SH003",
        "unit_id": "U02",
        "scene_no": 1,
        "shot_no": 3,
        "shot_size": "close_up",
        "camera": {
          "move": "tilt_up",
          "amplitude": "small",
          "speed": "slow",
          "from": "袋口特写、热气起点",
          "to": "抬起至 CHR-01 下颌线",
          "height": "eye_level",
          "roll": "level",
          "optics": "shallow_focus"
        },
        "duration_ms": 5000,
        "shot_language": {
          "composition": "袋口落在画面中心，前景遮住 CHR-01 的下半张脸",
          "axis": "沿用 U01 空间轴",
          "result": "热气在冷空气里拉成一条细白线"
        },
        "action": {
          "start": "CHR-01 低头看袋口",
          "change": "视线随热气上移",
          "end": "眼神停住"
        },
        "lighting": "practical_light——冷柜灯自下打上来，热气在光柱里显形",
        "character_refs": ["CHR-01"],
        "prop_refs": ["PRP-01"],
        "notes": "对应剧本第 1 场 action 节点③"
      },
      {
        "shot_id": "S01-SH004",
        "unit_id": "U02",
        "scene_no": 1,
        "shot_no": 4,
        "shot_size": "medium",
        "camera": {
          "move": "pull_out",
          "amplitude": "small",
          "speed": "slow",
          "from": "CHR-01 半身",
          "to": "退出至便利店整排货架",
          "height": "eye_level",
          "roll": "level",
          "optics": "deep_focus"
        },
        "duration_ms": 4000,
        "shot_language": {
          "composition": "末帧收在货架纵深，CHR-01 退为左下角剪影",
          "axis": "沿用 U01 空间轴",
          "result": "画面收束在冷白灯管与货架之间"
        },
        "action": {
          "start": "CHR-01 仍蹲在长椅前",
          "change": "机位后拉，环境纳入画面",
          "end": "人物留在画面左下"
        },
        "lighting": "practical_light——货架灯管沿纵深排开，末帧收在冷白灯管之间",
        "character_refs": ["CHR-01"],
        "prop_refs": [],
        "notes": "对应剧本第 1 场 action 节点④"
      }
    ],
    "forbidden_items": ["真实品牌 logo", "血腥画面"],
    "unspecified": [
      {
        "field": "shots[*].duration_ms",
        "upstream_field": "",
        "reason": "上游剧本未给任何单镜时长，本层按动作量估时",
        "owner": "算法作者",
        "fill_stage": "storyboard",
        "fill_fallback": "按动作节点数与语速上限估时，交付前由人工复核",
        "blocking": false
      }
    ],
    "quality_gate": {
      "static_ratio": 0.25,
      "move_type_count": 4
    }
  },
  "change_log": [
    {
      "op_id": "MOD-01",
      "intent": "第 1 镜时长由 5 秒延长至 6 秒",
      "target_path": "shots[0].duration_ms",
      "op_type": "replace",
      "before": "5000",
      "after": "6000",
      "basis": "第一镜太短了，拉到 6 秒",
      "upstream_impact": "duration_sum"
    },
    {
      "op_id": "MOD-02",
      "intent": "整片总时长随第 1 镜连带同步（MOD-01 的牵连位置）",
      "target_path": "total_duration_ms",
      "op_type": "replace",
      "before": "18000",
      "after": "19000",
      "basis": "第一镜太短了，拉到 6 秒",
      "upstream_impact": "duration_sum"
    },
    {
      "op_id": "MOD-03",
      "intent": "第 2 镜景别由 full 改为 medium",
      "target_path": "shots[1].shot_size",
      "op_type": "replace",
      "before": "full",
      "after": "medium",
      "basis": "第二镜的景别改成中景",
      "upstream_impact": "none"
    }
  ],
  "unresolved": [
    {
      "type": "limitation",
      "field": "（全局）漂移基准",
      "reason": "本轮未提供上游产物，零漂移只能以「修改前的当前产物」自身为基准",
      "need": "服务层注入 upstream_artifact 后由 check_consistency_v1 复跑一次，方可与上游事实交叉验证",
      "blocking": false
    },
    {
      "type": "finding",
      "field": "quality_gate.static_ratio",
      "reason": "脚本复算结果为 0.25，与填写值一致；但本产物仅 4 镜，统计量样本过小，参考意义有限",
      "need": "镜数 ≥8 后再行复算",
      "blocking": false
    }
  ],
  "clarification": { "needed": false, "questions": [] }
}
```

## 5 跨阶段一致性校验报告（`check_consistency_v1` 的输出）

以 §2.1（`artifact_a`）为基准、§4 的 `artifact`（`artifact_b`）为待检，`pair_role=before_after`。

```json
{
  "check_version": "1.1.0",
  "pair_role": "before_after",
  "focus": "全篇",
  "findings": [
    {
      "finding_id": "DR-01",
      "category": "number",
      "item": "第 1 镜时长（shots[0].duration_ms）",
      "value_a": "5000",
      "value_b": "6000",
      "location_b": "shots[0].duration_ms",
      "verdict": "drift",
      "action": "属本轮修改意图（对应 change_log 的 MOD-01）；before_after 口径下不判责任，由人对照 change_log 确认"
    },
    {
      "finding_id": "DR-02",
      "category": "number",
      "item": "整片总时长（total_duration_ms）",
      "value_a": "18000",
      "value_b": "19000",
      "location_b": "total_duration_ms",
      "verdict": "drift",
      "action": "与 DR-01 同源牵连（对应 MOD-02），差值 1000ms 与单镜增量一致，无需额外处置"
    },
    {
      "finding_id": "DR-03",
      "category": "setting",
      "item": "第 2 镜景别（shots[1].shot_size）",
      "value_a": "full",
      "value_b": "medium",
      "location_b": "shots[1].shot_size",
      "verdict": "drift",
      "action": "属本轮修改意图（对应 change_log 的 MOD-03）"
    },
    {
      "finding_id": "DR-04",
      "category": "number",
      "item": "第 3 镜时长（shots[2].duration_ms）",
      "value_a": "5000",
      "value_b": "5000",
      "location_b": "shots[2].duration_ms",
      "verdict": "consistent",
      "action": "未被点名，逐字未变（数字类**逐处登记**：第 3 镜单独一条）"
    },
    {
      "finding_id": "DR-05",
      "category": "number",
      "item": "第 4 镜时长（shots[3].duration_ms）",
      "value_a": "4000",
      "value_b": "4000",
      "location_b": "shots[3].duration_ms",
      "verdict": "consistent",
      "action": "未被点名，逐字未变（数字类**逐处登记**：第 4 镜单独一条）—— 与 DR-04 分列，正是为了不把「逐处性」抹掉"
    },
    {
      "finding_id": "DR-06",
      "category": "anchor",
      "item": "锚与编号全量比对（本体 8 项 + 引用面 4 项，清单见 CFG-007【封闭枚举登记】）",
      "value_a": "S01-SH001..004 / U01,U02 / [S01-SH001,S01-SH002],[S01-SH003,S01-SH004] / 1,1,1,1 / [CHR-01]×4 / []、[PRP-01]、[PRP-01]、[] / STYLE-01",
      "value_b": "S01-SH001..004 / U01,U02 / [S01-SH001,S01-SH002],[S01-SH003,S01-SH004] / 1,1,1,1 / [CHR-01]×4 / []、[PRP-01]、[PRP-01]、[] / STYLE-01",
      "location_b": "shots[*] 与 units[*] 全域",
      "verdict": "consistent",
      "action": "本次已扫锚：锚与编号共 11 项（本体 8 + 引用面 3；本产物无 prop_id 本体键）、合计 34 处全部一致（零容忍类整体复述）——本条**不得省略**：缺此条则无法区分「锚全部一致」与「根本没查锚」。⚠️ 本行 location_b 为全量复述的代表落点（锚类条目**豁免** `location_b` 形式校验）"
    }
  ],
  "summary": { "checked_count": 6, "drift_count": 3, "verdict": "drift" }
}
```

## 6 陷阱位（6 处，均为人为植入的失败模式）

| # | 陷阱 | 错在哪 | 正确处置 |
| --- | --- | --- | --- |
| 1 | 把「镜头」全篇统一改成「机位」 | **顺手多改**（客户没要求）——没有任何字段会因此报错 | 回退原值；若要改须记入 `unresolved` 等客户确认 |
| 2 | 顺手修掉 §2.1 里的一处错别字 | 同上——**「客户没要求改的错别字也是客户确认过的内容」** | 回退并记 `unresolved` |
| 3 | 把 `shots[0].character_refs` 由 `["CHR-01"]` 改成 `["CHR-02"]` | **改锚**——下游引用会指向不存在的对象，且产物自身仍自洽 | 命中 `locked_paths` → 不改动、转 `fallback.locked_violation` |
| 4 | 客户追一句「这段不够紧张，你看着改改」 | **含糊**——程度词无判据 | `clarification.needed=true`、`change_log` **置空**、`artifact` 逐字不变，转 `guard_clarify_v1` 追问 |
| 5 | 认为「改了景别，`camera.from/to` 也必须跟着改」 | **假牵连**：本题 SH002 的 `camera.from/to` 只描述**空间位置**（「蹲在长椅前，袋口朝向镜头」），不含取景范围描述 | 判 `upstream_impact=none`；⚠️ 反向陷阱同样存在——**真牵连漏改**（如只改单镜时长不改总时长） |
| 6 | 客户追一句「把结局改成她没等到人」 | **越权**——改故事走向不属本层 | 不产出改动，转 `fallback.out_of_scope`，记 `unresolved` 并说明「须走前四段重做或 `revise_v1` 重新成包」 |

## 7 评测项（逐项可判）

| # | 评测项 | 判据 | 本用例结果 |
| --- | --- | --- | --- |
| 1 | 输出形态 | 顶层恰好 6 键（`modify_version`／`target_stage`／`artifact`／`change_log`／`unresolved`／`clarification`） | ✅ |
| 2 | `artifact` 完整性 | 是**完整产物**（可直接替换原产物），非 diff 片段 | ✅（含全部 4 镜） |
| 3 | `target_stage` 回显 | 与输入一致（`storyboard`） | ✅ |
| 4 | `change_log` 条数 | 2 条意图 → 3 条记录（MOD-01 的牵连位置另占一条） | ✅ |
| 5 | `op_id` 形态与唯一性 | 形如 `MOD-\d{2}`、全表唯一、不跳号（MOD-01/02/03） | ✅ |
| 6 | `target_path` 可达性 | 每条路径都能在 `artifact` 中解析到（**`insert`／`delete` 豁免**，改判反向检查） | ✅（`shots[0].duration_ms`／`total_duration_ms`／`shots[1].shot_size`；三条均 `replace`） |
| 7 | `op_type` 取值 | ∈ {replace, normalize, insert, delete} | ✅（三条均 replace） |
| 8 | `before` 逐字性 | 与 §2.1 逐字相同（非推算值） | ✅（`18000` 取自原件，非由 5000→6000 反推） |
| 9 | `basis` 指回性 | 每条 `basis` 是客户原话的逐字片段 | ✅ |
| 10 | 同源牵连共用 `basis` | MOD-01／MOD-02 的 `basis` 相同 | ✅ |
| 11 | 未点名处逐字保持 | §2.1 与 §4 的差异**恰好 3 处** | ✅（正文本用例已逐字对齐，只此 3 处） |
| 12 | 锚与编号零变化 | 7 类锚与编号逐字相同 | ✅ |
| 13 | 枚举取值合法 | `shot_size=medium` 在 6 值内；`static` 镜**省略** `amplitude`／`speed` 键（非空串）；`lighting` 4 镜全覆盖且为分镜层「词表值——说明」形态（过 `R19` 光线覆盖门槛 40%） | ✅ |
| 14 | `unresolved` 形态 | 每条恰好 **5** 键、`blocking` 为**布尔**、`type` 在枚举内 | ✅（2 条：`limitation`／`finding`，均 `false` 布尔） |
| 15 | 上游基准局限已登记 | `upstream_artifact` 为空时 `unresolved` 必有一条说明该局限 | ✅（第 1 条） |
| 16 | `clarification` 形态 | 恰好 2 键；`needed=false` 时 `questions` 为空数组 | ✅ |
| 17 | 报告四类全覆盖 | 漂移报告含 number／setting／anchor 三类（本用例无 proper_noun 可查） | ✅ |
| 18 | 报告 anchor 类整体复述 | 锚类即使一致也有汇总条目（DR-06） | ✅ |
| 19 | 报告自洽复算 | `checked_count`＝清单条数；`drift_count`＝非 consistent 条数；`verdict` 随之 | ✅（6／3／drift） |
| 20 | 报告不越界 | 只报告，产物零改动 | ✅ |
| 21 | `focus` 回显与缩范围声明 | 顶层含 `focus` 且与输入一致；`focus=全篇` 时 anchor 条目含「本次已扫锚」 | ✅（`focus="全篇"`；DR-06 已写明） |
| 22 | 逐处性（同一类数值的每一处各占一条） | 未点名的第 3／4 镜时长**各占一条**，未合并 | ✅（DR-04／DR-05 分列） |

## 8 自检表

| 检查 | 结果 |
| --- | --- |
| `current_artifact` 与 `modify_v1` 输出的 `artifact` 差异**恰好 3 处** | ✅ 逐字比对（`shots[0].duration_ms`／`total_duration_ms`／`shots[1].shot_size`） |
| 差异与 `change_log` **一一对应**（无「多改」） | ✅ 3 处差异 ↔ 3 条记录 |
| 客户意图全部落实（无「漏改」） | ✅ 2 条意图均有记录 |
| 数字零漂移（除被点名者） | ✅ SH003 5000、SH004 4000 未变 |
| 设定零漂移（除被点名者） | ✅ 运镜／构图／轴线／画面结果／声音设计逐字未变 |
| 锚与编号零漂移 | ✅ 7 类全部逐字相同 |
| 总时长自洽 | ✅ 6000+4000+5000+4000 ＝ 19000 ＝ `total_duration_ms` |
| `static` 镜未携带 `amplitude`／`speed` | ✅ SH002 **省略键**（非空串） |
| 枚举值合法 | ✅ `medium` 在 `shot_size` 六值内 |
| `lighting` 覆盖与形态 | ✅ 4/4 镜；分镜层「词表值——说明」，§2.1 与 §4 逐字相同 |
| `locked_paths` 无命中 | ✅ 三条记录的目标路径均不在锁定清单内 |
| 模板版本常量 | ✅ `modify_version="1.1.0"` 与 `TPL-015` 文件版本一致；`check_version="1.1.0"` 与 `TPL-016` 一致 |
| 报告三数自洽 | ✅ 6／3／drift |
| 逐处性（同一类数值的每一处各占一条） | ✅ 未点名的第 3／4 镜时长**各占一条**（DR-04／DR-05），未合并，逐处性未被抹掉 |
| 报告缩范围声明（本轮为全篇，故写「本次已扫锚」） | ✅ DR-06 的 `action` 已写明并给出实比项数 |
| 产物标注验证状态 | ⚠️ **未验证**（未跑模型） |

## 9 与工程判据的对应

本用例的两个产物形态由 `validate_output.py` 的两条判据承担（**形态 `modify` 与 `drift_report`**，
2026-10-14 随本用例一并落地；越界样本见 `tests/negtest_pack_rules.py` 的**变更说明**与**漂移报告**两段）：

| 判据 | 形态 | 覆盖的本用例评测项 |
| --- | --- | --- |
| **R38** `MODIFY_SHAPE` | `modify` | 项 1（顶层恰好 6 键）／项 3（`target_stage` 落在封闭 5 值内）／项 5（`op_id` 形如 `MOD-\d{2}`、唯一不跳号）／项 6（`target_path` 可达，**`insert`／`delete` 豁免**）／项 7（`op_type` 取值）／项 14（`unresolved` 每条 **5** 键、`type` 在枚举内、`blocking` 为布尔）／项 16（`clarification` 恰好 2 键）；另加四条**追加**判据：`target_stage` 与 `artifact` 形态须相符、`clarification.needed=true` 时 `change_log` 必空、**取值级自洽三条**（`artifact[target_path]` 应＝`after`／应≠`before`／`delete` 后应不存在）、**转出形态**（`change_log` 空且非澄清态时 `unresolved` 必须非空） |
| **R39** `DRIFT_REPORT_SHAPE` | `drift_report` | 项 17（四类中「锚类必须有交代」）／项 18（锚类汇总条目**必须存在**）／项 19（`summary` 三数复算自洽）／项 21（`focus` 回显 + 缩范围声明复检）／项 22（`location_b` 形式，锚类豁免）；另加一条**追加**判据：`findings` 不得为空数组 |

⚠️ **判据的能力边界（如实登记，不得靠"看起来对"蒙混）**——下列评测项**无脚本判据**：

| 评测项 | 为何判不了 |
| --- | --- |
| 项 2（`artifact` 完整性） | R38 只能判「它**像**一份产物」（形态可识别、与 `target_stage` 相符）；「是否真的只差被点名的那几处」需外部基准 |
| 项 8（`before` 逐字性）／项 9（`basis` 指回性）／项 10（同源牵连共用 `basis`） | 需 `current_artifact` 与客户原话原文才能比对，而本产物**不含**这两者 |
| 项 11（未点名处逐字保持）／项 12（锚与编号零变化） | 同上——而**这两项恰是 SW-002 最核心的两项** |
| 项 4 的反向（**真牵连漏改**，如只改单镜时长不改总时长） | 同项 11——「该改的改了没有」须与 `current_artifact` 逐处比对（陷阱位 5 的另一半） |
| 项 13（枚举取值合法） | 由**第 1 个 JSON 块**（`storyboard` 形态）经 R16／R17／R19 覆核；R38 **刻意不递归**校验 `artifact` 内部 |
| 项 15（上游基准局限已登记） | 「`upstream_artifact` 是否为空」在单文件内不可知 |
| 项 20（报告不越界） | 需两份被检产物才能证明「一字未改」 |

上述无判据项由**模板 `guards` 的自检项 + 人工抽检**承担（SW-002 验收要求 ≥30 例）。
若日后要脚本化项 8／11／12，须为 `validate_output.py` 增设 `--before` 参数（同 R31 需 `--storyboard` 的模式）。

⚠️ **已知盲区（`tests/negtest_pack_rules.py` 登记；`v1.1.0` 依评审 `MR-02`／`MR-15` 由两条改三条）**：

| 盲区 | 为何仍无判据 |
| --- | --- |
| 「顺手多改」（改动未被 `change_log` 覆盖的字段） | 需 `current_artifact` 作外部基准 |
| 「`before` 写成空串」 | 同上（`before` 的逐字性须与原件比对） |
| 「**改了却没写记录**」（`change_log` 空而 `artifact` 变了） | 同上——**注意它与"伪记录"不是一回事** |

✅ **「伪记录」（记录说改了、产物里没改）已不再是盲区**：`v1.1.0` 的 R38 第 ⑤ 条**取值级自洽**
把它变为**可判**（`artifact[target_path]` 应≠`before`）。原文曾**漏登记**它、并误称其已被 R38 拦下
（评审 `MR-02` 即针对此处）。

**不把无判据的事写成"已覆盖"，是本工程反复出现的一类缺陷的根因。**
