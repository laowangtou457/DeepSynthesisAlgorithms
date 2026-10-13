# synopsis-case01 · 故事梗概生成

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-SYN-001` |
| 对应需求 | **SW-004 故事梗概生成** |
| 模板 | `synopsis_v1` **v2.0.0**（原 v1.0.0 经导演视角两轮评审后升版，见 `10-评审记录/`） |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.8 / top_p 0.9 / max_tokens 2048 |
| 记录日期 | 2026-10-13（v2.0.0 口径对齐同日） |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `source_input` | 外卖员在暴雨夜救下一只受伤的流浪猫，第二天发现猫的主人是他失联多年的妹妹。 |
| `genre` | 都市温情 |
| `target_duration` | 60-90秒 |
| `audience` | 未指定 |
| `must_include` | ["暴雨夜", "流浪猫"] |
| `must_avoid` | [] |

## 3 输出

> **状态：待回填。** 本节为目标输出样例（人工构造），用于固化字段结构与写法基线；**尚未经 Qwen2.5-7B-Instruct 实测**。实测后须替换为模型真实输出并保留原始采样日志。

```json
{
  "title": "雨夜的猫",
  "logline": "暴雨夜送单将超时的外卖员，为把受伤的流浪猫送回主人身边，顶着一单差评追查项圈线索。",
  "logline_parts": {
    "protagonist": "外卖员",
    "situation": "暴雨夜送单即将超时",
    "goal": "把受伤的流浪猫送回主人身边",
    "obstacle": "暴雨与超时压力随时会让他丢掉这份生计"
  },
  "genre": "都市温情",
  "protagonist": {
    "character_id": "CHR-01",
    "name": "未指定",
    "identity": "外卖员",
    "goal": "找到猫的主人并归还",
    "flaw": "习惯把求助挡在门外",
    "age_band": "未指定",
    "appearance_lock_zh": "未指定"
  },
  "supporting": [
    {"character_id": "CHR-02", "name": "未指定", "role": "情感线", "relation": "猫的主人，主角失联多年的妹妹", "age_band": "未指定", "appearance_lock_zh": "未指定"}
  ],
  "world": {
    "setting": "当代城市，暴雨夜的居民区与次日清晨的街巷",
    "tone": "克制温情",
    "visual_style_hint": "未指定",
    "rules": []
  },
  "conflict": {
    "external": "暴雨天气与即将超时的配送单在争夺主角的时间",
    "internal": "主角对『多管闲事』的自我克制与不忍心之间的拉扯",
    "stakes": "若不留下这只猫，它将无人照看；若留下，主角将错过配送时限"
  },
  "scenes_outline": [
    {"no": 1, "location": "老式居民楼的楼道口（室外向室内的过渡空间）", "time_of_day": "夜（暴雨）", "present": ["CHR-01"], "beat": "暴雨夜送单途中，主角在楼道口发现一只受伤的流浪猫", "purpose": "建立", "est_seconds": 15},
    {"no": 2, "location": "雨夜沿街商铺门前的非机动车道", "time_of_day": "夜（暴雨）", "present": ["CHR-01"], "beat": "主角犹豫后把猫带上车，配送超时被差评", "purpose": "升级", "est_seconds": 18},
    {"no": 3, "location": "另一片居民区的单元门口", "time_of_day": "清晨", "present": ["CHR-01"], "beat": "次日清晨，主角按项圈上的信息找到对方住处", "purpose": "转折", "est_seconds": 18},
    {"no": 4, "location": "居民住宅的入户门内侧", "time_of_day": "清晨", "present": ["CHR-01", "CHR-02"], "beat": "开门的人是他失联多年的妹妹", "purpose": "反转", "est_seconds": 15},
    {"no": 5, "location": "客厅窗边的沙发一角", "time_of_day": "清晨", "present": ["CHR-01", "CHR-02"], "beat": "两人隔着一只猫重新说起话", "purpose": "收束", "est_seconds": 15}
  ],
  "ending": {
    "resolution": "猫的主人正是主角失联多年的妹妹，两人因这只猫重新建立联系",
    "theme": "善意兜了一圈，落回自己身上"
  },
  "covered_points": [
    {"point": "外卖员在暴雨夜救下一只受伤的流浪猫", "covered_in": "scenes_outline[1]"},
    {"point": "猫的主人是他失联多年的妹妹", "covered_in": "scenes_outline[4]"}
  ],
  "forbidden_items": [],
  "total_est_seconds": 81,
  "unspecified": [
    {"field": "protagonist.name", "reason": "客户未提供主角姓名", "fill_stage": "script", "fill_fallback": "由 SW-005 向客户确认；确认前保持未指定", "blocking": false},
    {"field": "supporting[0].name", "reason": "客户未提供妹妹姓名", "fill_stage": "script", "fill_fallback": "由 SW-005 向客户确认；确认前保持未指定", "blocking": false},
    {"field": "ending.resolution（失联的具体年数）", "reason": "客户只说『多年』，未给具体年数", "fill_stage": "script", "fill_fallback": "由 SW-005 依剧情需要与客户确认；确认前不得写具体数字", "blocking": false},
    {"field": "conflict.internal（失联原因）", "reason": "客户未说明两人当年为何失联", "fill_stage": "script", "fill_fallback": "由 SW-005 依人物关系提出候选后请客户确认", "blocking": false},
    {"field": "protagonist.age_band", "reason": "客户未提供主角年龄段", "fill_stage": "script", "fill_fallback": "由 SW-005 依身份与题材提出候选后请客户确认", "blocking": false},
    {"field": "protagonist.appearance_lock_zh", "reason": "客户未提供主角外形", "fill_stage": "script", "fill_fallback": "由 SW-005 依年龄与题材提出候选后请客户确认；确认前不得编造", "blocking": false},
    {"field": "supporting[0].appearance_lock_zh", "reason": "客户未提供妹妹外形", "fill_stage": "script", "fill_fallback": "同上，由 SW-005 定义", "blocking": false},
    {"field": "world.visual_style_hint", "reason": "客户未提供全片视觉风格", "fill_stage": "script", "fill_fallback": "由 SW-005 依 tone 提出候选风格串请客户确认", "blocking": false}
  ]
}
```

## 4 评测结论

对照 SW-004 的验收标准：**「覆盖全部给定要点，无编造事实」**。

| # | 评测项 | 手段 | 结论 |
| --- | --- | --- | --- |
| 1 | 要点覆盖 | `covered_points` 与输入逐条比对 | ✅ 2 / 2 覆盖，无合并、无省略 |
| 2 | 无编造—专名 | 抽取输出全部专名 → 回溯输入 | ✅ 主角名、妹妹名均为「未指定」；未出现虚构姓名／地名／机构名 |
| 3 | 无编造—数值 | 抽取输出全部数字 → 回溯输入 | ✅ 未出现具体失联年数（客户只说「多年」，未写成「八年」）；`est_seconds` 属工程配额、非事实数据，不计入 |
| 4 | 结构合规 | JSON 字段完整性比对 + 场次档位核对 | ✅ 顶层 14 个字段齐备；`scenes_outline` **5 条**。目标时长 60–90 秒属「**60 < t ≤ 180 秒**」档（**5–8 场**），5 条落在区间内（**注：v1.0.0 用例曾误引第一档「3–5 场」口径，已按 R-06 修正**） |
| 5 | 边界处理 | `unspecified` 是否列出待确认项 | ✅ 列出 **8 项**，其中 **4 项为视觉锚点类**（含角色外观、年龄段、风格线索） |
| 6 | 禁用表述 | 扫描绝对化／宣传性词汇 | ✅ 未命中 |
| 7 | 内容质量 | `logline` 与 `logline_parts` 一致性核对 | ✅ `logline_parts` 四要素（主角／处境／目标／阻力）齐备，且与 `logline` 正文一致（**注：v1.0.0 用例的 `logline` 缺「目标／阻力」却被判通过，已按 R-07 修正**） |
| 8 | **视觉锚点下潜**（v2.0.0 新增，依 D-07） | 核查 `unspecified` 是否含角色外形／年龄段／场景／风格类缺失 | ✅ 4 项视觉锚点类缺口全部单列，`fill_stage` 均标 `script` |

**本用例的针对性设计**：第 2、3 两项目标是捕获**编造**——这是梗概类生成最高频的失败模式。客户只给了「外卖员」「妹妹」「多年」三个模糊信息，模型很容易补成「林默」「妹妹叫小雨」「失联八年」。该用例把这三处全部设成陷阱位。第 8 项是新设的第二类陷阱位：**视觉信息全空**，若模型不写进 `unspecified`，就说明「约束的容器」仍未落地。

## 5 验证状态

**未验证。** 理由：

1. 输出为人工构造，未经模型实测 —— 按项目纪律不得标为已通过；
2. 第 1、2、3、6 项目前为人工比对，尚未脚本化（`examples/README.md` §四要求这两层须脚本产出结论）；
3. 用例来源为构造，非真实客户素材。

**闭环条件**（三项齐备后方可改判「已实测」）：

- [ ] 在 Qwen2.5-7B-Instruct 上跑通本用例，回填真实输出与采样日志
- [ ] 把第 1／2／3 项落成校验脚本，产出机器可读报告（对齐 `delivery/validate_pack.py` 的口径）
- [ ] 补一组脱敏真实客户素材用例（`CASE-SYN-002`）

---

*记录性质：用例与评测留痕　｜　建立 2026-10-13　｜　v2.0.0 口径对齐 2026-10-13（依 D-07 / R-05 / R-06 / R-07）　｜　保留原则：永久保留，模板升版后本用例不删除、另建新用例*
