# script-case01 · 剧本生成

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-SCR-001` |
| 对应需求 | **SW-005 剧本生成** |
| 模板 | `script_v1` **v2.0.0**（原 v1.0.0；本次依导演视角独立评审 `SR-01`~`SR-11` 修订） |
| 上游用例 | `CASE-SYN-001`（`examples/CASE-004_synopsis-case01.md`）——本用例的输入即该用例的**已确认梗概** |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.8 / top_p 0.9 / max_tokens 4096 |
| 记录日期 | 2026-10-13（v2.0.0 口径对齐同日完成） |

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
    "style_prompt_zh": "日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和，写实光影层次",
    "style_anchors": ["日式动画电影质感", "柔和赛璐璐上色", "冷灰蓝主色调", "克制低饱和"],
    "lighting_default": "夜景：低调光，湿地面反光补光；清晨：低饱和漫射光（分时相差异写在此处，不写进风格锚）",
    "negative_global": [
      "lowres", "blurry", "watermark", "text", "deformed", "extra limbs",
      "flicker", "temporal jitter", "frame inconsistency",
      "clipping", "morphing", "limb popping"
    ],
    "design_source": "系统提议待确认"
  },
  "characters": [
    {
      "character_id": "CHR-01",
      "name": "未指定",
      "role": "主角",
      "identity": "外卖员",
      "source": "承继上游",
      "age_band": "青年",
      "appearance_lock_zh": "短发、浓眉，深蓝色外卖冲锋衣（配反光条），身形清瘦，右手腕戴一只磨旧的电子表",
      "voice": "语速偏快、嗓音略哑，习惯把话咽回去，急起来会重复对方的词",
      "design_source": "系统提议待确认"
    },
    {
      "character_id": "CHR-02",
      "name": "未指定",
      "role": "情感线",
      "identity": "住所女主人",
      "source": "承继上游",
      "age_band": "青年",
      "appearance_lock_zh": "齐肩黑发随手挽起，素色米白家居开衫，身形偏瘦，左手无名指有一道旧疤",
      "voice": "语速慢、尾音轻，先停顿再说，避免直视对方",
      "design_source": "系统提议待确认"
    }
  ],
  "props": [
    {
      "prop_id": "PRP-01",
      "name": "流浪猫",
      "role": "核心道具：串联主角与妹妹的信物，全片唯一把两人连起来的物件",
      "appearance_lock_zh": "中华田园猫，橘白相间，左后腿有一道旧伤，颈上系一条磨花的皮质项圈，项圈上挂一枚磨花的金属宠物牌",
      "design_source": "系统提议待确认"
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
          "props_present": ["PRP-01"],
          "action": "主角挤在楼道口避雨刷手机，耳机里不断跳超时提醒（空间：街面→楼道口的檐下）；脚边纸箱里传来一声细弱的叫，他掀开湿透的纸板，看见一只后腿带血的猫（主体变化：发现道具）；他先站起要走，鞋已经迈下台阶，又停住（状态：离开→留下），蹲回去把纸箱往墙根挪了半尺。",
          "sfx_hint": ["雨砸在铁皮雨棚上的闷响", "耳机里跳出的超时提示音", "纸箱里细弱的猫叫"],
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
          "props_present": ["PRP-01"],
          "action": "主角把猫塞进冲锋衣内侧，单手扶把冲进雨里（空间：楼道口→骑行中的街面）；手机支架上超时红字亮起，一条一星差评弹出（主体变化：接到差评）；他在路口短暂停车，先看手机，再看怀里那一小团湿透的重量（状态：看手机→看猫），最后把手机扣回支架继续骑。",
          "sfx_hint": ["雨打在冲锋衣上的密集声", "电动车电机低鸣", "差评弹窗的提示音"],
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
          "props_present": ["PRP-01"],
          "action": "雨停后的清晨，主角沿着门牌号往巷子深处走，脚步在最后一个单元门口停住（空间：巷口→目标单元门口）；他先看纸袋里露出来的猫耳，再低头核对项圈上磨花的宠物牌，把纸袋换到另一只手（主体状态：确认了地址与身份）；抬手要按门铃时又缩回来，转身对着单元门来回走了两趟，最后把猫抱出来贴在胸口，按下门铃（状态：犹豫→决断）。",
          "sfx_hint": ["雨停后的清晨：远处早点摊的锅气声、零星鸟叫", "布鞋踩过积水的轻响", "单元门铃的两声回响（无人应，又按第三声）"],
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
          "props_present": ["PRP-01"],
          "action": "门开一条缝，CHR-02 低头看见猫，先伸手抱过去，动作很轻（主体变化：猫易手）；她抬眼，正对上 CHR-01（状态：看猫→看人）；两个人都在原地没动，走廊的声控灯灭了又亮（空间状态：明→暗→明），谁也没有先开口。",
          "sfx_hint": ["声控灯『啪』的一声亮起，又灭", "门轴轻响", "走廊里极轻的呼吸声"],
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
          "props_present": ["PRP-01"],
          "action": "CHR-02 把猫放在两人之间的坐垫上，转身去倒水（空间：门口→客厅）；CHR-01 没有坐，只站在窗边，身体半侧向屋里（状态：站在门外的人→走进屋里的人）；猫挪了两步，把自己搁在两人中间（主体变化：三人关系的空间位置被重新摆定）；CHR-02 先开口，CHR-01 这一次没有把话咽回去。",
          "sfx_hint": ["窗外清晨的鸟声", "倒水时玻璃杯轻碰桌面的声", "猫爪落在坐垫上的闷响"],
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
    {"field": "characters[0].name", "upstream_field": "protagonist.name", "reason": "客户未提供主角姓名；客户未答复 gap_answers", "owner": "客户", "fill_stage": "script", "fill_fallback": "向客户追问；确认前对白以身份代称（『外卖员』）、画面不出现姓名——不闭合亦可交付", "blocking": false},
    {"field": "characters[1].name", "upstream_field": "supporting[0].name", "reason": "客户未提供妹妹姓名；客户未答复 gap_answers", "owner": "客户", "fill_stage": "script", "fill_fallback": "同上；确认前以身份代称（『住所女主人』）、画面不出现姓名——不闭合亦可交付", "blocking": false},
    {"field": "ending.resolution（失联的具体年数）", "upstream_field": "ending.resolution", "reason": "客户只说『多年』，未给具体年数", "owner": "客户", "fill_stage": "script", "fill_fallback": "向客户追问；确认前不得写具体数字，对白中一律用『好几年』这类模糊说法回指梗概原文——不闭合亦可交付", "blocking": false},
    {"field": "conflict.internal（失联原因）", "upstream_field": "conflict.internal", "reason": "客户未说明两人当年为何失联", "owner": "客户", "fill_stage": "script", "fill_fallback": "向客户追问；确认前剧本只呈现『疏远』的结果、不解释原因——不闭合亦可交付", "blocking": false},
    {"field": "characters[0].appearance_lock_zh", "upstream_field": "protagonist.appearance_lock_zh", "reason": "客户未提供主角外形，已由本层提出候选", "owner": "客户", "fill_stage": "script", "fill_fallback": "提请客户确认；确认前该候选即全片默认锚点，不闭合亦可交付；若客户否决须回本层重出", "blocking": false},
    {"field": "characters[1].appearance_lock_zh", "upstream_field": "supporting[0].appearance_lock_zh", "reason": "客户未提供妹妹外形，已由本层提出候选", "owner": "客户", "fill_stage": "script", "fill_fallback": "同上，由本层所出候选为默认值；客户否决须回本层重出", "blocking": false},
    {"field": "style_bible.style_prompt_zh", "upstream_field": "world.visual_style_hint", "reason": "客户未提供全片视觉风格，已由本层提出候选风格串", "owner": "客户", "fill_stage": "script", "fill_fallback": "提请客户确认；确认前该风格串为全片默认锚点，SW-007 直接引用——不闭合亦可交付", "blocking": false},
    {"field": "props[0].appearance_lock_zh", "upstream_field": "", "reason": "客户未提供猫的品种与外观，已由本层提出候选（上游梗概无道具字段，故本项为本层新产生的缺口）", "owner": "客户", "fill_stage": "script", "fill_fallback": "提请客户确认；确认前该候选即全片默认道具锚，不闭合亦可交付", "blocking": false}
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
| 4 | `purpose` 封闭且一致 | 逐场核对取值 ∈ 五值枚举 & 与梗概对应场一致 | ✅ 建立／升级／转折／反转／收束，逐场与梗概一一对应（脚本校验：`validate_output.py` R1） |
| 5 | 角色/设定与梗概一致 | 角色身份、关系、地点、时相、走向核对 | ✅ `identity`／`relation`／`location`／`time_of_day`／结局走向均与梗概一致，未改变因果 |
| 6 | **外观首定义落地** | 核查 `age_band` / `appearance_lock_zh` 是否仍为「未指定」 | ✅ 两项均已出具体值（不再留空）；`design_source` 标「系统提议待确认」并在 `unspecified` 中登记 |
| 7 | **风格首定义落地** | 核查 `style_bible` 完整性 | ✅ `style_id`／`style_prompt_zh`（**36 字**，落在 30–80）／`style_anchors`（**4 条**，落在 3–5）／`negative_global`（**三类齐备**）均齐 |
| 8 | **锚的跨场适用性**（SR-01 新增） | 把全片 5 场的 `slug`（地点·时相）与两个锚**逐项对照**，凡锚中含该场不成立者即判不合格 | ✅ 2 场雨夜 + 3 场清晨与两个锚**全部相容**：外观串 5 项（短发／浓眉／冲锋衣／清瘦／旧电子表）与场景无关；风格锚 4 条无一条含雨／雨丝／夜／晨等时相词。**分时相光照差异全部落在 `lighting_default`** |
| 9 | 禁止项承接 | `forbidden_items` 与梗概比对 | ✅ 梗概为空数组，输出同为 `[]`——**空数组的承接同样算通过**（不是「因为没内容就跳过」） |
| 10 | **缺口续接 + 责任归属**（SR-02/SR-03） | 梗概 `unspecified`（8 项）逐项追踪；核 `owner` / `fill_stage` / `upstream_field` | ✅ 上游 8 项 → 本层 **8 项**（7 项保留 + 1 项新增）：`protagonist.age_band` 因本层已出值而**闭合**；7 项保留者的 `owner` 全为 `客户`、`fill_stage` 全为 `script`（本层）、`upstream_field` 逐条对上上游路径；新增 1 项（`props[0].appearance_lock_zh`）的 `upstream_field` 为空串（上游无此字段）。**无一项被推给 storyboard／shot_prompt** |
| 11 | **时长预算（纵向 + 横向）**（SR-08） | ① `total_est_seconds` vs Σ`est_seconds` vs 梗概 81；② 逐场核 `est_seconds ≥ 8`（＝单镜下限 4s × 单元最少 2 镜） | ✅ ① Σ = 15+18+18+15+15 = **81**，与梗概零偏差（远优于 10% 阈值）；② 最小场 15 秒 ≥ 8 秒，5 场全部通过——即每场都撑得起下游的最小生成单元 |
| 12 | 无编造—事实类 | 抽取输出全部专名 → 回溯梗概／答复 | ✅ 主角与妹妹姓名均为「未指定」，对白用身份代称；未出现虚构姓名／地名／机构名；未出现具体失联年数 |
| 13 | **设计类规则式覆盖**（SR-05 新增） | 凡 output 中带 `design_source` 的值即为设计类，核查其是否都出值且来源可追溯 | ✅ 带 `design_source` 者共 **5 处**（`style_bible`、CHR-01、CHR-02、PRP-01 各 1 处，1 处为风格串）——**含此前无主的 `voice` 与道具外观**，全部出值、全部标「系统提议待确认」、全部在 `unspecified` 中有对应条目。**未出现"两边都不属于"的字段** |
| 14 | **道具首定义**（SR-05 新增） | 核查 `props[]` 容器与 `props_present` 引用 | ✅ `props` 非空（1 项 `PRP-01`）；5 场的 `props_present` 均引用 `["PRP-01"]`，无悬空引用；道具外观串只写固有特征（品种／毛色／旧伤／项圈），**未混入「毛发湿透」「沾了泥」等瞬时状态** |
| 15 | **`action` 节点密度**（SR-06 新增） | 逐场数「状态／空间／主体发生变化」的节点数 | ✅ 5 场节点数依次为 3 / 3 / 3 / 3 / 3（**均 ≥ 3**）：含此前最勉强的场 3——已由"到达→按铃"两节点增强为"巷口→单元门口（空间）／核对项圈（主体状态）／折返后抱猫按铃（状态）"三节点 |
| 16 | **声音线索结构化**（SR-07 新增） | 核查 `sfx_hint` 字段是否存在、是否含非散文的音效条目 | ✅ 5 场 `sfx_hint` 全部非空（各 3 条）；此前散落在 `action` 叙述与旁白正文里的声音（雨砸铁皮雨棚、超时提示音、门铃回响）已落成可机器读的条目 |
| 17 | **语速可核查**（SR-04 新增） | 逐句核 `字数 ÷ 所在场 est_seconds ≤ 9`（规范 §4.5 交付门禁） | ✅ 5 场台词密度依次约 1.6 / 1.6 / 1.4 / 1.3 / 1.9 字/秒，全片 ≈ **1.5 字/秒**，全部远低于 9。⚠️ **如实标注：本用例的语速远未触及阈值**——该约束在本用例中**未形成压力测试**，只证明"可核查"。真正的语速边界须由实测时的**反向样本**（单场台词塞满）覆盖 |
| 18 | **来源二分**（SR-10 新增） | 核查 `source` 与 `design_source` 是否分列 | ✅ 两名角色的 `source`（承继自梗概的 name／role／identity）与 `design_source`（本层首定义的 age_band／appearance_lock_zh／voice）**分别标注**，未合为一个对象级来源 |
| 19 | 内容质量 | 人工阅读（叙事是否成立、对白是否可演） | ⚠️ 人工判定「成立」，但**未脚本化、亦未经模型验证**，不计入通过项 |

> **一处口径更正（SR-08 附带发现，须留存）**：本用例早先版本及 `REQ-TPL-SCR-001a` §2① 曾表述为「下游要把**每一场**切成 **2–3 个生成单元**」。经评审方核对，《分镜提示词交付规范》§4.3 全文**并无**「每场 2–3 个单元」的明文（该节只规定"每单元 2–3 镜、单元内运镜不重复、一镜只属一单元"），且下游用例 `CASE-STB-001` 实测为**每场 1 个单元**。
> **正确口径**：下游在**场内部**按"新信息节点"划分生成单元，每单元含 2–3 镜；**本层给出的场 `est_seconds` 事实上是该场的"镜数预算"**。第 11 项的横向校验（`est_seconds ≥ 8`）即按此口径设立。**原表述已更正，不再沿用。**

**本用例的针对性设计**：五项陷阱位。

1. **姓名陷阱**——梗概里两名角色姓名全空、且客户未答复。模型极容易在写对白时顺手补出人名（这是剧本类生成最高频的失败模式）。用例要求对白只能以身份代称指人。
2. **首定义陷阱**——上游把外观与风格留成「未指定」，若本层照抄留空，下游（SW-006／SW-007）就没有视觉锚点。用例要求这两类**必须出值**且标「系统提议待确认」。
3. **锚的跨场陷阱**（SR-01 新增，本版最要紧的一条）——全片 2 场雨夜 + 3 场清晨。模型极易把"当下的雨夜状态"写进只定义一次的锚（湿发、湿裤脚、"细腻雨丝质感"），**锚会自己制造跨场漂移**。用例要求锚只写固有特征，时相元素归 `lighting_default`。
4. **责任错配陷阱**（SR-02 新增）——7 项"客户未提供"的缺口，模型极易因为猜不到该填什么阶段而一律前移到 `storyboard`／`shot_prompt`（"看起来有人接手"）。用例要求 `owner=客户` 者 `fill_stage` 回归 `script`，并在 `fill_fallback` 写明"不闭合亦可交付"的依据。
5. **接缝陷阱**——模型天然倾向于「按剧情需要重新分场」或「改一下角色编号」。用例把 `no` 与 `character_id` 设成刚性比对项。

## 5 验证状态

**未验证。** 理由：

1. 输出为人工构造，未经模型实测 —— 按项目纪律不得标为已通过；
2. 第 1、2、3、5、8、10、13、14、15、16、18 项目前为人工比对，尚未全部脚本化（其中第 3、4、10、11 项已可用 `validate_output.py` 自动核查）；
3. 用例来源为构造，非真实客户素材。

**闭环条件**（三项齐备后方可改判「已实测」）：

- [ ] 在 Qwen2.5-7B-Instruct 上跑通本用例，回填真实输出与采样日志（**待模型就绪后统一执行**）
- [ ] 把第 1／2／3／8／13／15 项落成校验脚本，产出机器可读报告（与 `validate_output.py` 同源）
- [ ] 补一组脱敏真实客户素材用例（`CASE-SCR-002`）

---

*记录性质：用例与评测留痕　｜　建立 2026-10-13（随 `script_v1` v1.0.0）；**v2.0.0 口径对齐同日完成**（依导演视角独立评审 `SR-01`~`SR-11`）　｜　保留原则：永久保留，模板升版后本用例不删除、另建新用例*
