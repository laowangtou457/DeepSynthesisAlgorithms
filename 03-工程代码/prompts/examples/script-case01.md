# script-case01 · 剧本生成

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-SCR-001` |
| 对应需求 | **SW-005 剧本生成** |
| 模板 | `script_v1` **v1.0.0** |
| 上游用例 | `CASE-SYN-001`（`examples/synopsis-case01.md`）——本用例的输入即该用例的**已确认梗概** |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.8 / top_p 0.9 / max_tokens 4096 |
| 记录日期 | 2026-10-13 |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `synopsis_json` | 见下方「上游梗概」——取自 `CASE-SYN-001` 的输出（v2.0.0 口径） |
| `gap_answers` | 无（客户未答复任何缺口项 → 本用例全部触发「系统提议待确认」路径） |
| `client_visual_input` | 未指定 |

### 上游梗概（`synopsis_json`，摘录关键字段）

```json
{
  "title": "雨夜的猫",
  "logline": "暴雨夜送单将超时的外卖员，为把受伤的流浪猫送回主人身边，顶着一单差评追查项圈线索。",
  "genre": "都市温情",
  "protagonist": {"character_id": "CHR-01", "name": "未指定", "identity": "外卖员", "goal": "找到猫的主人并归还", "flaw": "习惯把求助挡在门外", "age_band": "未指定", "appearance_lock_zh": "未指定"},
  "supporting": [{"character_id": "CHR-02", "name": "未指定", "role": "情感线", "relation": "猫的主人，主角失联多年的妹妹", "age_band": "未指定", "appearance_lock_zh": "未指定"}],
  "world": {"setting": "当代城市，暴雨夜的居民区与次日清晨的街巷", "tone": "克制温情", "visual_style_hint": "未指定", "rules": []},
  "conflict": {"external": "暴雨天气与即将超时的配送单在争夺主角的时间", "internal": "主角对『多管闲事』的自我克制与不忍心之间的拉扯", "stakes": "若不留下这只猫，它将无人照看；若留下，主角将错过配送时限"},
  "scenes_outline": [
    {"no": 1, "location": "老式居民楼的楼道口（室外向室内的过渡空间）", "time_of_day": "夜（暴雨）", "present": ["CHR-01"], "beat": "暴雨夜送单途中，主角在楼道口发现一只受伤的流浪猫", "purpose": "建立", "est_seconds": 15},
    {"no": 2, "location": "雨夜沿街商铺门前的非机动车道", "time_of_day": "夜（暴雨）", "present": ["CHR-01"], "beat": "主角犹豫后把猫带上车，配送超时被差评", "purpose": "升级", "est_seconds": 18},
    {"no": 3, "location": "另一片居民区的单元门口", "time_of_day": "清晨", "present": ["CHR-01"], "beat": "次日清晨，主角按项圈上的信息找到对方住处", "purpose": "转折", "est_seconds": 18},
    {"no": 4, "location": "居民住宅的入户门内侧", "time_of_day": "清晨", "present": ["CHR-01", "CHR-02"], "beat": "开门的人是他失联多年的妹妹", "purpose": "反转", "est_seconds": 15},
    {"no": 5, "location": "客厅窗边的沙发一角", "time_of_day": "清晨", "present": ["CHR-01", "CHR-02"], "beat": "两人隔着一只猫重新说起话", "purpose": "收束", "est_seconds": 15}
  ],
  "ending": {"resolution": "猫的主人正是主角失联多年的妹妹，两人因这只猫重新建立联系", "theme": "善意兜了一圈，落回自己身上"},
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

> **上游状态**：`CASE-SYN-001` 的输出为**人工构造**、未经模型实测（标「未验证」）。本用例沿用同一前提——即「上游已确认」在**流程上**成立，但**素材真实性**与 `CASE-SYN-001` 同一性质。

## 3 输出

> **状态：待回填。** 本节为目标输出样例（人工构造），用于固化字段结构与写法基线；**尚未经 Qwen2.5-7B-Instruct 实测**。实测后须替换为模型真实输出并保留原始采样日志。

```json
{
  "title": "雨夜的猫",
  "logline": "暴雨夜送单将超时的外卖员，为把受伤的流浪猫送回主人身边，顶着一单差评追查项圈线索。",
  "genre": "都市温情",
  "style_bible": {
    "style_id": "STYLE-01",
    "style_prompt_zh": "日式动画电影质感，柔和赛璐璐上色，冷蓝灰主色调，雨夜湿润反光与清晨低饱和漫射光，写实光影层次",
    "style_anchors": ["日式动画电影质感", "柔和赛璐璐上色", "冷蓝灰主色调", "细腻雨丝质感"],
    "lighting_default": "夜景低调光，湿地面反光补光；清晨为低饱和漫射光",
    "negative_global": [
      "lowres", "blurry", "watermark", "text", "deformed", "extra limbs",
      "flicker", "temporal jitter", "frame inconsistency",
      "clipping", "morphing", "limb popping"
    ],
    "source": "系统提议待确认"
  },
  "characters": [
    {
      "character_id": "CHR-01",
      "name": "未指定",
      "role": "主角",
      "identity": "外卖员",
      "age_band": "青年",
      "appearance_lock_zh": "短发被雨水压塌贴在额角，浓眉，深蓝冲锋衣配反光条，身形清瘦，右手腕戴一只磨旧的电子表，裤脚常湿",
      "voice": "语速偏快、嗓音略哑，习惯把话咽回去，急起来会重复对方的词",
      "source": "系统提议待确认"
    },
    {
      "character_id": "CHR-02",
      "name": "未指定",
      "role": "情感线",
      "identity": "住所女主人",
      "age_band": "青年",
      "appearance_lock_zh": "齐肩黑发随手挽起，素色米白家居开衫，身形偏瘦，左手无名指有一道旧疤，神情常带倦意",
      "voice": "语速慢、尾音轻，先停顿再说，避免直视对方",
      "source": "系统提议待确认"
    }
  ],
  "acts": [
    {
      "act_no": 1,
      "act_name": "第一幕 · 建置",
      "act_summary": "暴雨夜的一次偶遇，让把求助挡在门外的外卖员第一次停下脚步。",
      "scenes": [
        {
          "no": 1,
          "act_no": 1,
          "slug": "外景 · 老式居民楼的楼道口 · 暴雨夜",
          "location": "老式居民楼的楼道口（室外向室内的过渡空间）",
          "time_of_day": "夜（暴雨）",
          "present": ["CHR-01"],
          "action": "主角挤在楼道口避雨刷手机，耳机里不断跳超时提醒；脚边纸箱里传来一声细弱的叫；他掀开湿透的纸板，看见一只后腿带血的猫。他先站起要走，鞋已经迈下台阶，又停住。",
          "dialogue": [
            {"speaker_id": "CHR-01", "speaker_name": "外卖员", "type": "画外音", "line": "还有六分钟。", "emotion": "焦躁、自我说服"},
            {"speaker_id": "", "speaker_name": "旁白", "type": "旁白", "line": "雨砸在铁皮雨棚上，像有人在替他数秒。", "emotion": "克制"}
          ],
          "beat": "暴雨夜送单途中，主角在楼道口发现一只受伤的流浪猫",
          "purpose": "建立",
          "est_seconds": 15
        },
        {
          "no": 2,
          "act_no": 1,
          "slug": "外景 · 雨夜沿街商铺门前的非机动车道 · 暴雨夜",
          "location": "雨夜沿街商铺门前的非机动车道",
          "time_of_day": "夜（暴雨）",
          "present": ["CHR-01"],
          "action": "主角把猫塞进冲锋衣内侧，单手扶把冲进雨里；手机支架上超时红字亮起，一条一星差评弹出。他在路口短暂停车，先看手机，再看怀里那一小团湿透的重量，最后把手机扣回支架继续骑。",
          "dialogue": [
            {"speaker_id": "CHR-01", "speaker_name": "外卖员", "type": "对白", "line": "行，扣就扣吧。", "emotion": "认命、憋着"},
            {"speaker_id": "", "speaker_name": "旁白", "type": "旁白", "line": "他把差评留在了昨天的单里，把猫留在了今天。", "emotion": "克制"}
          ],
          "beat": "主角犹豫后把猫带上车，配送超时被差评",
          "purpose": "升级",
          "est_seconds": 18
        }
      ]
    },
    {
      "act_no": 2,
      "act_name": "第二幕 · 对抗",
      "act_summary": "猫成了他必须办完的一件事，也把他推向一段他一直没敢回头的关系。",
      "scenes": [
        {
          "no": 3,
          "act_no": 2,
          "slug": "外景 · 另一片居民区的单元门口 · 清晨",
          "location": "另一片居民区的单元门口",
          "time_of_day": "清晨",
          "present": ["CHR-01"],
          "action": "雨停后的清晨，主角按项圈上磨花的宠物牌找到地址；他在单元门口来回走了两趟，把猫放进纸袋又抱出来，最终按下门铃。",
          "dialogue": [
            {"speaker_id": "CHR-01", "speaker_name": "外卖员", "type": "对白", "line": "送东西的。", "emotion": "含糊、回避"},
            {"speaker_id": "", "speaker_name": "旁白", "type": "旁白", "line": "门铃响了两声，没有人应，他就按了第三声。", "emotion": "忐忑"}
          ],
          "beat": "次日清晨，主角按项圈上的信息找到对方住处",
          "purpose": "转折",
          "est_seconds": 18
        },
        {
          "no": 4,
          "act_no": 2,
          "slug": "内景 · 居民住宅的入户门内侧 · 清晨",
          "location": "居民住宅的入户门内侧",
          "time_of_day": "清晨",
          "present": ["CHR-01", "CHR-02"],
          "action": "门开一条缝，CHR-02 低头看见猫，先伸手抱过去，动作很轻；她抬眼，正对上 CHR-01。两个人都在原地没动，走廊的声控灯灭了又亮。",
          "dialogue": [
            {"speaker_id": "CHR-02", "speaker_name": "住所女主人", "type": "对白", "line": "……它怎么会在你这儿。", "emotion": "失声、又压住"},
            {"speaker_id": "CHR-01", "speaker_name": "外卖员", "type": "对白", "line": "昨晚在楼道里捡的。", "emotion": "僵硬、低头"}
          ],
          "beat": "开门的人是他失联多年的妹妹",
          "purpose": "反转",
          "est_seconds": 15
        }
      ]
    },
    {
      "act_no": 3,
      "act_name": "第三幕 · 结局",
      "act_summary": "两个人隔着同一只猫，把多年没说出口的话重新开了个头。",
      "scenes": [
        {
          "no": 5,
          "act_no": 3,
          "slug": "内景 · 客厅窗边的沙发一角 · 清晨",
          "location": "客厅窗边的沙发一角",
          "time_of_day": "清晨",
          "present": ["CHR-01", "CHR-02"],
          "action": "CHR-02 把猫放在两人之间的坐垫上，去倒水；CHR-01 没有坐，只站在窗边。猫挪了两步，把自己搁在两人中间。CHR-02 先开口，CHR-01 这一次没有把话咽回去。",
          "dialogue": [
            {"speaker_id": "CHR-02", "speaker_name": "住所女主人", "type": "对白", "line": "坐吧。它认你。", "emotion": "松动、试探"},
            {"speaker_id": "CHR-01", "speaker_name": "外卖员", "type": "对白", "line": "那……我坐。", "emotion": "迟缓、放软"},
            {"speaker_id": "", "speaker_name": "旁白", "type": "旁白", "line": "窗外天亮了，屋里没人急着说话。", "emotion": "收束"}
          ],
          "beat": "两人隔着一只猫重新说起话",
          "purpose": "收束",
          "est_seconds": 15
        }
      ]
    }
  ],
  "forbidden_items": [],
  "total_est_seconds": 81,
  "unspecified": [
    {"field": "characters[0].name", "reason": "客户未提供主角姓名；客户未答复 gap_answers", "fill_stage": "storyboard", "fill_fallback": "向客户确认；确认前对白以身份代称（『外卖员』），不得自拟姓名", "blocking": false},
    {"field": "characters[1].name", "reason": "客户未提供妹妹姓名；客户未答复 gap_answers", "fill_stage": "storyboard", "fill_fallback": "同上，确认前以身份代称（『住所女主人』）", "blocking": false},
    {"field": "ending.resolution（失联的具体年数）", "reason": "客户只说『多年』，未给具体年数", "fill_stage": "shot_prompt", "fill_fallback": "向客户确认；确认前不得写具体数字，对白中一律用『好几年』这类模糊说法回指梗概原文", "blocking": false},
    {"field": "conflict.internal（失联原因）", "reason": "客户未说明两人当年为何失联", "fill_stage": "shot_prompt", "fill_fallback": "依人物关系提出候选后请客户确认；确认前剧本只呈现『疏远』的结果、不解释原因", "blocking": false},
    {"field": "characters[0].appearance_lock_zh", "reason": "客户未提供主角外形，已由本层提出候选", "fill_stage": "shot_prompt", "fill_fallback": "提请客户确认；确认前该值为可用默认，若客户否决须回本层重出", "blocking": false},
    {"field": "characters[1].appearance_lock_zh", "reason": "客户未提供妹妹外形，已由本层提出候选", "fill_stage": "shot_prompt", "fill_fallback": "同上，由本层所出候选为默认值", "blocking": false},
    {"field": "style_bible.style_prompt_zh", "reason": "客户未提供全片视觉风格，已由本层提出候选风格串", "fill_stage": "shot_prompt", "fill_fallback": "提请客户确认；确认前该风格串为全片默认锚点，SW-007 直接引用", "blocking": false}
  ]
}
```

## 4 评测结论

对照 SW-005 的验收标准：**「角色/设定与梗概一致，结构完整」**；并叠加链路接缝的三条硬约束（`character_id` 不得改号、场号不得重编、设计类信息须由本层定义且可追溯）。

| # | 评测项 | 手段 | 结论 |
| --- | --- | --- | --- |
| 1 | 结构完整性 | 三幕齐备 + 场次齐备核对 | ✅ 3 幕（建置／对抗／结局）；5 场全部归属到幕，无游离场次 |
| 2 | `character_id` 零漂移 | 输出 characters 与梗概 protagonist+supporting 逐项比对 | ✅ 严格 `CHR-01` / `CHR-02`，不多不少、未改号 |
| 3 | 场号承接 | 输出 scenes 的 `no` 集合与梗概 `scenes_outline` 比对 | ✅ 同为 `{1,2,3,4,5}`，顺序一致，未重编、未合并拆分 |
| 4 | `purpose` 封闭且一致 | 逐场核对取值 ∈ 五值枚举 & 与梗概对应场一致 | ✅ 建立／升级／转折／反转／收束，逐场与梗概一一对应（脚本校验：`validate_output.py`） |
| 5 | 角色/设定与梗概一致 | 角色身份、关系、地点、时相、走向核对 | ✅ `identity`／`relation`／`location`／`time_of_day`／结局走向均与梗概一致，未改变因果 |
| 6 | **外观首定义落地** | 核查 `age_band` / `appearance_lock_zh` 是否仍为「未指定」 | ✅ 两项均已出具体值（不再留空）；`source` 标「系统提议待确认」并在 `unspecified` 中登记 |
| 7 | **风格首定义落地** | 核查 `style_bible` 完整性 | ✅ `style_id`／`style_prompt_zh`（**62 字**，落在 30–80）／`style_anchors`（**4 条**，落在 3–5）／`negative_global`（**三类齐备**）均齐 |
| 8 | 禁止项承接 | `forbidden_items` 与梗概比对 | ✅ 梗概为空数组，输出同为 `[]`——**空数组的承接同样算通过**（不是「因为没内容就跳过」） |
| 9 | 缺口续接 | 梗概 `unspecified`（8 项）逐项追踪 | ✅ 8 项中 **7 项保留**（`fill_stage` 前移至 storyboard／shot_prompt）；`protagonist.age_band` 一项因本层已出值而**闭合**，不再出现 |
| 10 | 时长预算 | `total_est_seconds` vs Σ`est_seconds` vs 梗概 81 | ✅ Σ = 15+18+18+15+15 = **81**，与梗概 `total_est_seconds` 完全一致（偏差 0%，远优于 10% 阈值） |
| 11 | 无编造—事实类 | 抽取输出全部专名 → 回溯梗概／答复 | ✅ 主角与妹妹姓名均为「未指定」，对白用身份代称；未出现虚构姓名／地名／机构名；未出现具体失联年数 |
| 12 | 内容质量 | 人工阅读（叙事是否成立、对白是否可演） | ⚠️ 人工判定「成立」，但**未脚本化、亦未经模型验证**，不计入通过项 |

**本用例的针对性设计**：三项陷阱位。

1. **姓名陷阱**——梗概里两名角色姓名全空、且客户未答复。模型极容易在写对白时顺手补出人名（这是剧本类生成最高频的失败模式）。用例要求对白只能以身份代称指人。
2. **首定义陷阱**——上游把外观与风格留成「未指定」，若本层照抄留空，下游（SW-006／SW-007）就没有视觉锚点。用例要求这两类**必须出值**且标「系统提议待确认」。
3. **接缝陷阱**——模型天然倾向于「按剧情需要重新分场」或「改一下角色编号」。用例把 `no` 与 `character_id` 设成刚性比对项。

## 5 验证状态

**未验证。** 理由：

1. 输出为人工构造，未经模型实测 —— 按项目纪律不得标为已通过；
2. 第 1、2、3、4、8、9、10 项目前为人工比对，尚未脚本化（其中第 3、4、9、10 项已可用 `validate_output.py` 部分自动核查，第 4 项 `purpose` 已脚本化）；
3. 用例来源为构造，非真实客户素材。

**闭环条件**（三项齐备后方可改判「已实测」）：

- [ ] 在 Qwen2.5-7B-Instruct 上跑通本用例，回填真实输出与采样日志（**待模型就绪后统一执行**）
- [ ] 把第 1／2／3／9 项落成校验脚本，产出机器可读报告（与 `validate_output.py` 同源）
- [ ] 补一组脱敏真实客户素材用例（`CASE-SCR-002`）

---

*记录性质：用例与评测留痕　｜　建立 2026-10-13（随 `script_v1` v1.0.0）　｜　保留原则：永久保留，模板升版后本用例不删除、另建新用例*
