# shot-prompt-case01 · 分镜提示词生成

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-SHP-001` |
| 对应需求 | **SW-007 分镜提示词生成**（编译表达层） |
| 模板 | `shot_prompt_v1` **v2.0.0**（**v2.0.0 系依契约升版批次 `T-054`／`T-055`／`T-056` 合并为同一次动作**——`output` 顶层新增 `props`／`forbidden_items`、逐镜新增 `prop_refs`，**属 output 字段增删，故升主版本**。历史：v1.1.0 系依**导演视角独立评审 `PR-01`~`PR-15`** 修订，该评审因**会话隔离未满足**而**降级使用**，只作设计期参考、不作独立背书） |
| 上游用例（双上游） | `CASE-SCR-001`（`examples/CASE-001_script-case01.md`，**出锚**：`style_bible`／`characters`／`props`）＋ `CASE-STB-001`（`examples/CASE-003_storyboard-case01.md`，**出决策**：`units`／`shots`／`total_duration_ms`） |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.7 / top_p 0.9 / max_tokens 8192（**受约束解码**，FSM = `delivery/schemas/CFG-006_shot_prompt_pack.v1.schema.json`） |
| 记录日期 | 2026-10-13 |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `storyboard_json` | 取自 `CASE-STB-001` 的输出（`storyboard_v1` v2.1.0 口径）：**5 单元 / 14 镜 / 81000ms** |
| `script_json` | 取自 `CASE-SCR-001` 的输出（`script_v1` v2.0.0 口径）：提供 `style_bible`（`STYLE-01`）、`characters`（`CHR-01`／`CHR-02`）、`props`（`PRP-01`）、`forbidden_items = []` |
| `pack_meta` | **服务层注入**（非模型生成）——`pack_id = FR-PK-20261013-CASE0001`、`created_at = 2026-10-13T16:20:00+08:00`、`task_type = text_to_video`、`session_id`／`task_id`／`statement_id`／`generator`／`compliance` 见输出 |
| `segment` | `all` —— ⚠️ **本用例取 `all` 仅为「演练与校验」**：只有拿到一份完整包才能跑 `validate_pack.py` 门禁。**生产环境 14 镜必须分段**（模板规定总镜数 > 6 时应当分段），分段计划见 §5 陷阱位 8 |
| `gap_answers` | 无。注意口径：自 `script_v1` v2.0.0 起，凡 `owner=客户` 的缺口其 `fill_stage` 一律为 `script`／`storyboard`，**不会流到本层**——故本变量按设计应为空，不是「客户漏答」 |

### 双上游摘要

**① 锚（来自 `script_json`，`CASE-SCR-001`）**

| 项 | 值 |
| --- | --- |
| `style_bible.style_id` | `STYLE-01` |
| `style_bible.style_prompt_zh` | 日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和，写实光影层次（**36 字**） |
| `style_bible.style_anchors` | 4 条（日式动画电影质感／柔和赛璐璐上色／冷灰蓝主色调／克制低饱和） |
| `style_bible.lighting_default` | 夜景：低调光，湿地面反光补光；清晨：低饱和漫射光（**分时相差异写在此处**） |
| `style_bible.style_prompt_en` | ⚠️ **上游无此字段**（规范 §3.3 标「应当」）→ **由本层补出** |
| `characters` | `CHR-01`（name **未指定**／identity 外卖员）· `CHR-02`（name **未指定**／identity 住所女主人） |
| `props` | `PRP-01`（流浪猫。**v2.0 起由交付包顶层 `props[]` 承载**，并逐镜以 `prop_refs` 引用：`prop_id`／`name`／`role`／`appearance_lock_zh` **原样承继**、`appearance_lock_en` 由本层补出；上游台账字段 `design_source` **不入包**） |

**② 决策（来自 `storyboard_json`，`CASE-STB-001`）**

| 单元 | 场 | 镜号 | 镜数 | 时长 |
| --- | --- | --- | --- | --- |
| U01 | 1 | S01-SH001~003 | 3 | 15000ms |
| U02 | 2 | S02-SH001~003 | 3 | 18000ms |
| U03 | 3 | S03-SH001~003 | 3 | 18000ms |
| U04 | 4 | S04-SH001~002 | 2 | 15000ms |
| U05 | 5 | S05-SH001~003 | 3 | 15000ms |
| — | — | **合计** | **14 镜** | **81000ms** |

> **上游状态**：`CASE-SCR-001` 与 `CASE-STB-001` 的输出均为**人工构造**、未经模型实测（标「未验证」）。本用例沿用同一前提——即「上游已确认」在**流程上**成立，但**素材真实性**与两个上游用例同一性质。

## 3 输出

> **状态：待回填。** 本节为目标输出样例（人工构造），用于固化字段结构与写法基线；**尚未经 Qwen2.5-7B-Instruct 实测**。实测后须替换为模型真实输出并保留原始采样日志。
>
> ✅ **本包已过「产物侧静态门禁」**（`validate_output.py` **53/0/0**），**且交付门禁 `validate_pack.py` 为 0 BLOCK**（**v2.0 起**）。原本唯一一条 BLOCK 是 `S01-SH001` 的 `prompt_en` 超 schema 上限 900 字符——**该条属契约级缺陷**（上限值本身待复核，评审 `PR-07`），已随 **`T-056` 把上限上修至 1200 字符**而归零（**本层始终不压缩维度**——压缩会违反 §4.1 八维双落地）。详见 §4 第 27 项、§6 第 4 项。
> 本包**仍是人工构造的结构基线**，**不是模型实测产物**——「脚本全绿」只证明结构与规则自洽，**不证明模型能生成**。真正可交付的包必须在模型就绪后由 `shot_prompt_v1` **v2.0.0** 产出、再过同一套门禁。详见 §6。

```json
{
  "schema_version": "2.0.0",
  "meta": {
    "pack_id": "FR-PK-20261013-CASE0001",
    "title": "雨夜的猫",
    "created_at": "2026-10-13T16:20:00+08:00",
    "task_type": "text_to_video",
    "unsupported_task_types": [
      "keyframe_completion：需 Ref2VA 六段式骨架与 350-500 词 detailed_description，本期不作适配",
      "reference_generation：需 Ref2VA 全参考模式与素材上限体系，本期不作适配",
      "video_editing：需下游编辑接口与素材回传通道，本期不作适配",
      "video_continuation：需上游成片片段作为输入，本期不作适配",
      "audio_reuse：需独立音轨输入与对齐机制，本期不作适配",
      "audio_reference：同上，本期不作适配"
    ],
    "generator": {
      "system": "AI 漫剧剧本与分镜提示词生成系统",
      "version": "0.1.0",
      "provider": "{{PROVIDER_NAME}}",
      "provider_code": "{{PROVIDER_CODE}}"
    },
    "generation_trace": {
      "session_id": "SESS-CASE-0001",
      "task_id": "TASK-CASE-0001",
      "stage_chain": ["synopsis", "script", "storyboard", "shot_prompt"],
      "templates": [
        { "id": "synopsis_v1", "version": "2.0.0" },
        { "id": "script_v1", "version": "2.0.0" },
        { "id": "storyboard_v1", "version": "2.1.0" },
        { "id": "shot_prompt_v1", "version": "2.0.0" }
      ],
      "model": { "name": "Qwen2.5-7B-Instruct", "backend": "vllm", "revision": "main" }
    },
    "compliance": {
      "safety_check": { "input": "passed", "output": "passed", "checked_at": "2026-10-13T16:19:40+08:00" },
      "copyright_check": { "status": "passed", "note": "原创内容，无改编来源" },
      "marking_check": { "explicit": "present", "implicit": "present" },
      "statement_id": "FR-ST-20261013-CASE0001"
    },
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 81000,
    "notes": "【未验证包 · 人工构造 · v2.0 依契约升版修订】① 字段投影（规则①）：上游 style_bible.lighting_default 为描述性串（含分时相差异），交付包该字段要求纯词表值，已按语义映射为 practical_light（雨夜实景补光为全片统一光质基底）；因逐镜 lighting 均已给出真值，该默认值实际不被引用。上游 12 处 lighting 的「词表值——中文光位说明」已拆分：字段只留词表 code，中文光位说明移入 prompt_zh、英文说明移入 prompt_en。② 【v1.1 更正 · 评审 PR-02】原口径「amplitude／speed 的 medium／normal 规范化为空串」**已废止**——交付 schema 的枚举不含空串，写空串会被门禁判 `'' is not one of [...]`（实测 23 条 BLOCK）。新口径：**所有留空一律省略该键**（amplitude／speed／optics／transition_in／transition_out／ref_image），本包已按此重出。上游 S03-SH002 的 camera 幅度已按 storyboard_v1 v2.1.0 硬性约束 6 留空，本层即省略 amplitude 键。③ 【条件改写留痕 · 规则④ · 评审 PR-03】全包唯一一处：S02-SH003 的 shot_language.composition 上游留空、而交付 schema 该字段 required 且 minLength 1，已**仅从本镜已有字段派生**（依 shot_size=full、本镜 action 与 camera.from／to 推得「人与车停在路口的侧影整个入画，路口灯柱在画面右缘」）。另 S02-SH001 的 shot_language.result 曾有无依据措辞改写（『反光带』→『路面反光』），已按评审 PR-03 **回退上游原文**。④ 【缺口可见性登记 · 评审 §3-B】本包所依据的上游未闭合缺口共 9 条，按可机器读形式逐条登记（本层不搬运、不改写、不重编号上游台账——规范 §3.1 顶层八段无台账字段）：[GAP] shots[].character_refs ← characters[0].appearance_lock_zh | owner=客户 | fill_stage=script | 客户未提供主角外形，剧本层已提候选待确认，确认前候选即全片默认锚。[GAP] shots[].character_refs ← characters[1].appearance_lock_zh | owner=客户 | fill_stage=script | 同上（CHR-02）。[GAP] style_ref ← style_bible.style_prompt_zh | owner=客户 | fill_stage=script | 客户未提供全片视觉风格，剧本层已提候选待确认，确认前该串为全片默认锚。[GAP] shots[].prop_refs ← props[0].appearance_lock_zh | owner=客户 | fill_stage=script | 客户未提供猫的品种与外观，剧本层已提候选待确认；候选即全片默认锚。**v2.0 起本层已输出顶层 props[] 与逐镜 prop_refs**（见 ⑦），该缺口不再是「无处落地」。[GAP] units[4].music ← 无上游字段 | owner=客户 | fill_stage=storyboard | 客户未提供音乐方案，本层按收束段节奏提议织体（单音符钢琴，间隔 3–4 秒一次）待确认，否决则改。[GAP] shots[].dialogue ← characters[*].name／ending.resolution | owner=客户 | fill_stage=script | 主角姓名、妹妹姓名、具体年数、失联原因四项未闭合，对白一律以身份代称与模糊说法处理，不阻塞交付。⑤ 【v2.0 已解 · 原评审 PR-07 提示】prompt_en 的 schema 上限原为 900 字符，与「八维必须写进正文」在中长镜上不可兼得（本包 S01-SH001 = 1113 字符超限）。**v2.0 已把上限上修至 1200 字符**（定值依据见规范 §3.7.6：实测最长 1113 ／ p95 941 ／ 均值 778），本包 1113 已在限内——该条 BLOCK 随之归零。⑥ 【v2.0 已解 · 原自查发现 ISSUE-012】上游**顶层** `forbidden_items` 原在交付包**无对应容器**，本层曾不搬运该字段。**v2.0 起交付契约已增顶层 `forbidden_items`**（规范 §3.1.1 三层边界：客户业务层 `forbidden_items` 进包／质量层 `negative_global` 管画质伪影／法定合规层 `A1-0x` 分类码与词条**绝不进包**）——本包已按契约产出该段（上游三处均为空数组，故本段为 `[]`）。⚠️ 与 `characters[].forbidden` **语义不同**：后者是**角色级**禁忌（防角色外观漂移），前者是**全片内容级**禁忌。R36 仍机器化「契约外键禁入」（检查九处）。⑦ 【v2.0 契约升版 · 本包已随升】三处结构变更合并为同一次动作：① 新增顶层 `props[]`（道具锚）与逐镜 `prop_refs`（14 镜中 10 镜为 [\"PRP-01\"]、4 镜为空数组 []，与上游 CASE-STB-001 逐镜一致）；② 新增顶层 `forbidden_items`（承接客户侧禁忌；本包为空数组 []）；③ `prompt_en` 上限 900 → 1200 字符。`schema_version` 1.1.0 → 2.0.0，模板 `shot_prompt_v1` 1.1.0 → 2.0.0。**`prop_refs` 恢复承继列、`forbidden_items` 进入承继列**——v1.1 的「不输出」处置随契约补齐**已撤销**（`ISSUE-011`／`ISSUE-012` 闭环）。"
  },
  "style_bible": {
    "style_id": "STYLE-01",
    "style_prompt_zh": "日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和，写实光影层次",
    "style_prompt_en": "Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation, realistic lighting layers",
    "style_anchors": ["日式动画电影质感", "柔和赛璐璐上色", "冷灰蓝主色调", "克制低饱和"],
    "lighting_default": "practical_light",
    "negative_global": [
      "lowres", "blurry", "watermark", "text", "deformed", "extra limbs",
      "flicker", "temporal jitter", "frame inconsistency",
      "clipping", "morphing", "limb popping"
    ]
  },
  "characters": [
    {
      "character_id": "CHR-01",
      "name": "未指定",
      "appearance_lock_zh": "短发、浓眉，深蓝色外卖冲锋衣（配反光条），身形清瘦，右手腕戴一只磨旧的电子表",
      "appearance_lock_en": "short hair, thick brows, a dark blue delivery jacket with reflective strips, lean build, a worn digital watch on the right wrist",
      "forbidden": ["发型变化", "服装颜色变化"]
    },
    {
      "character_id": "CHR-02",
      "name": "未指定",
      "appearance_lock_zh": "齐肩黑发随手挽起，素色米白家居开衫，身形偏瘦，左手无名指有一道旧疤",
      "appearance_lock_en": "shoulder-length black hair pinned up loosely, a plain off-white cardigan, slim build, an old scar on the ring finger of the left hand",
      "forbidden": ["发型变化", "服装颜色变化"]
    }
  ],
  "props": [
    {
      "prop_id": "PRP-01",
      "name": "流浪猫",
      "role": "核心道具：串联主角与妹妹的信物，全片唯一把两人连起来的物件",
      "appearance_lock_zh": "中华田园猫，橘白相间，左后腿有一道旧伤，颈上系一条磨花的皮质项圈，项圈上挂一枚磨花的金属宠物牌",
      "appearance_lock_en": "a Chinese rural cat, orange and white, an old wound on the left hind leg, a scuffed leather collar with a worn metal tag"
    }
  ],
  "units": [
    {
      "unit_id": "U01",
      "scene_no": 1,
      "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"],
      "soundscape": "暴雨拍打铁皮雨棚的密集声，楼道口积水顺台阶往下淌",
      "music": "N/A",
      "notes": "单人戏，按单人替身法则处理"
    },
    {
      "unit_id": "U02",
      "scene_no": 2,
      "shot_ids": ["S02-SH001", "S02-SH002", "S02-SH003"],
      "soundscape": "电动车电机声、轮胎劈开积水的哗声、雨打头盔的密集声",
      "music": "N/A",
      "notes": "骑行段，单元内三镜运镜各不相同"
    },
    {
      "unit_id": "U03",
      "scene_no": 3,
      "shot_ids": ["S03-SH001", "S03-SH002", "S03-SH003"],
      "soundscape": "清晨居民区鸟叫、远处垃圾车、雨后滴水、门铃与门内脚步声",
      "music": "N/A",
      "notes": "单人戏，空间轴由单元门与通道构成"
    },
    {
      "unit_id": "U04",
      "scene_no": 4,
      "shot_ids": ["S04-SH001", "S04-SH002"],
      "soundscape": "门轴轻响、走廊声控灯电流声、室外滴水、室内安静",
      "music": "N/A",
      "notes": "对手戏：以门缝分侧建立屏幕方位，保证不跳轴"
    },
    {
      "unit_id": "U05",
      "scene_no": 5,
      "shot_ids": ["S05-SH001", "S05-SH002", "S05-SH003"],
      "soundscape": "客厅挂钟走针、猫爪在坐垫上的窸窣、窗外早市远景",
      "music": "单音符钢琴，间隔 3–4 秒一次，音量低于环境音"
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
        "to": "停在 CHR-01 肩背，雨幕堆在身后",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "远景：暴雨夜的居民楼楼道口，一个外卖员拎着外卖箱站在檐下，半边肩还在雨里；他侧身往墙里挪了半步，背贴墙面站定，视线压在手机屏上。镜头从楼道口外三米、齐腰高度缓缓前推，停在他的肩背，雨幕堆在身后，浅景深把身后的雨帘化开。人落在画面右三分，左侧三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘；空间轴左为楼道口、右为街面，全集不越此轴。楼道感应灯在他下半张脸上打出一道硬边，街灯反光从积水里泛上来。雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A wide shot of a delivery rider sheltering at the entrance of an old residential building on a stormy night, a delivery box in one hand and one shoulder still in the rain. He shifts half a step toward the wall and settles with his back against it, eyes on his phone. The camera pushes in with small amplitude at slow speed from three meters out at waist height, stopping on his shoulders and back with the rain curtain piling up behind him, holding a shallow depth of field so the rain behind him falls out of focus. He sits in the right third of the frame with the deep entrance shaft filling the left third, spray from the ground pressing the lower edge. The space axis runs from the dark entrance on the left to the bright street on the right, uncrossed throughout. A practical light from the motion-sensor lamp cuts a hard edge across the lower half of his face while streetlight reflects up from the standing water. Rain runs down his sleeve in a steady stream, pooling at his feet and dimpling under fresh drops. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "CHR-01 拎着外卖箱站在楼道口檐下，半边肩在雨里",
        "change": "侧身往墙里挪半步，耳机里跳出一声超时提醒",
        "end": "背贴墙面站定，视线压在手机屏上"
      },
      "shot_language": {
        "composition": "CHR-01 落在画面右三分，左三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘",
        "axis": "空间轴：画面左＝楼道口（暗）、画面右＝街面（亮），整场不越此轴",
        "result": "雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "dialogue": "还有六分钟。",
      "sfx": "雨砸铁皮雨棚声、外卖箱塑料提手摩擦声",
      "transition_in": "fade_in",
      "notes": "单人镜，用具名锚点（稳定指称『外卖员／the delivery rider』）指向 CHR-01"
    },
    {
      "shot_id": "S01-SH002",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 2,
      "shot_size": "close_up",
      "camera": {
        "move": "tilt_down",
        "amplitude": "small",
        "speed": "slow",
        "from": "CHR-01 膝下的湿砖",
        "to": "停在脚边被雨水泡软的纸箱",
        "height": "high",
        "roll": "level",
        "optics": "rack_focus"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "近景：外卖员膝下的湿砖，以及他脚边一只被雨水泡软的纸箱。镜头从湿砖缓缓下摇，停在那只纸箱上。他掀开湿透的纸板，箱底蜷着一只后腿带血的猫，它抬了一下头。机位取俯角，焦点从湿砖转移到纸箱边缘——焦点转移等于剪了一刀但没切镜头。纸箱占画面下三分之一，上方是垂落的雨帘，构图极简；空间轴沿用本场（楼道内·街面外）。逆光里雨丝显形，纸箱边缘被勾出一道湿亮的光边。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A close-up shot of the wet brick below the delivery rider's knees and a rain-soaked cardboard box at his feet. The camera tilts down with small amplitude at slow speed from the wet brick and settles on the cardboard box. He lifts the sodden flap and a cat with a bleeding hind leg lies curled at the bottom, raising its head once. The high angle works with a rack focus that carries attention from the wet brick to the box edge, cutting without cutting. The box fills the lower third of the frame with hanging rain above it; the composition is deliberately spare. The space axis carries over from the scene, entrance inward on one side and street outward on the other. Backlight makes the rain streaks visible and rims the box edge with a wet gleam. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "视线压在手机屏上",
        "change": "脚边纸箱传来一声细弱的叫，他掀开湿透的纸板",
        "end": "看见一只后腿带血的猫蜷在箱底"
      },
      "shot_language": {
        "composition": "构图极简，纸箱占画面下三分之一，上方是垂落的雨帘",
        "axis": "沿用本场空间轴（楼道内·街面外）",
        "result": "纸板被掀开，箱底蜷着一只后腿带血的猫，它抬了一下头"
      },
      "lighting": "rim_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "sfx": "纸箱里细弱的猫叫、雨声转低",
      "transition_in": "cut",
      "notes": "道具 PRP-01 本镜入画；本镜不承载角度以外的额外处理"
    },
    {
      "shot_id": "S01-SH003",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 3,
      "shot_size": "full",
      "camera": {
        "move": "pull_out",
        "amplitude": "small",
        "speed": "slow",
        "from": "蹲着的背影与脚边的纸箱",
        "to": "拉开到楼道口的整块纵深，人缩在画面一角",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "全景：外卖员站起、鞋已迈下台阶，又停住，蹲回去把纸箱往墙根挪了半尺，重新站定，目光落在箱子上。镜头从他蹲着的背影与脚边的纸箱缓缓后拉，拉开到楼道口的整块纵深，人缩在画面一角，大景深让人、箱与楼道同时可读。人与纸箱压在画面左下，右侧大片是空的楼道；空间轴沿用本场。楼道感应灯把人的影子投到墙上，随下蹲的动作拉长。纸箱在地面留下一道被拖出的湿痕。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A full shot: the delivery rider stands, one foot already off the step, then stops and crouches back to drag the box half a foot toward the wall before straightening, eyes on it. The camera pulls out with small amplitude at slow speed from his crouched back and the box at his feet, opening out to the full depth of the entrance with the man tucked into a corner of the frame; the deep focus keeps man, box and passage readable at once. The pair sit in the lower left while the empty entrance fills the right. The space axis carries over from the scene. A practical lamp casts his shadow on the wall, stretching as he crouches. The box leaves a wet drag mark on the concrete. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "站起，鞋已迈下台阶",
        "change": "停住，蹲回去把纸箱往墙根挪了半尺",
        "end": "重新站定，目光落在箱子上"
      },
      "shot_language": {
        "composition": "人与纸箱压在画面左下，右侧大片是空的楼道",
        "axis": "沿用本场空间轴（楼道内·街面外）",
        "result": "纸箱被往墙根挪了半尺，地上留下一道被拖出的湿痕"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "dialogue": "雨砸在铁皮雨棚上，像有人在替他数秒。",
      "sfx": "雨声、纸箱刮过水泥地的摩擦声",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜，故有 transition_out"
    },
    {
      "shot_id": "S02-SH001",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 1,
      "shot_size": "medium",
      "camera": {
        "move": "tracking",
        "speed": "fast",
        "from": "车侧后方半米、略低",
        "to": "追平车侧、与车身并行稳住",
        "height": "eye_level",
        "roll": "level"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：一个外卖员单手扶把、另一只手按住怀里鼓起的一团，身体前倾压低，脚下一蹬加速，车身稳住，冲进前方雨幕。镜头自他车侧后方半米、略低处起幅，快速跟拍，追平车侧后与车身并行稳住。他居中偏左，雨幕在镜头前拉成斜线，湿路面的反光占据画面下方三分之一；镜头始终在他右侧同一侧跟随，不换边，全集不越轴。沿街招牌的暖光在湿路面上拖出长条反光，随车速被拉长。车轮劈开积水，水花向两侧甩出并溅上裤脚。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A medium shot of a delivery rider steering one-handed, his other hand pressed over a small shape bundled at his chest. He leans forward and pedals hard, then steadies as the bike drives into the rain ahead. The camera tracks with fast speed from half a metre behind and slightly below the bike, closing up and running level with it. He sits left of centre while the rain smears into diagonals across the lens and wet-road reflection fills the lower third. The camera stays on his right side throughout, never crossing the axis. Warm shopfront neon drags long reflections down the wet asphalt, stretching with his speed. The wheels split the standing water, throwing spray out to both sides and up onto his trousers. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "单手扶把，另一只手按住怀里鼓起的一团",
        "change": "身体前倾压低，脚下一蹬加速",
        "end": "车身稳住，冲进前方雨幕"
      },
      "shot_language": {
        "composition": "CHR-01 居中偏左，雨幕在镜头前拉成斜线，湿路面的反光占据画面下方三分之一",
        "axis": "空间轴：镜头始终在 CHR-01 右侧同一侧跟随，不换边",
        "result": "车轮劈开积水，水花向两侧甩出并溅上裤脚，反光带随车速被拉长"
      },
      "lighting": "neon_night",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "sfx": "电机声、雨打头盔的密集声",
      "transition_in": "fade_in",
      "notes": "单人镜；speed 取 fast 是强调加速，amplitude 为默认值故留空"
    },
    {
      "shot_id": "S02-SH002",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 2,
      "shot_size": "close_up",
      "camera": {
        "move": "pan_left",
        "amplitude": "small",
        "speed": "slow",
        "from": "手机支架上的超时红字",
        "to": "停回 CHR-01 的下半张脸",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "近景：外卖员的眼睛瞟向支架，视线在超时红字上停住，嘴角向下按，随后移开、落向怀里。镜头从手机支架上的红字缓缓左摇，停回他的下半张脸，浅景深把屏幕与背景隔开。红字与脸各占一半，画面被手机屏的光切成左右两块；空间轴手机恒在画面左、脸恒在画面右。手机屏的冷光自下而上打在脸上，与街灯暖光对撞。一条一星差评从屏幕顶端弹入并停在正中，把红字压下去。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A close-up: the delivery rider's eyes flick to the mount and stop on the red overtime numerals, the corner of his mouth pressing down before he looks away toward what he is carrying. The camera pans left with small amplitude at slow speed from the red numerals on the phone mount and settles back on the lower half of his face, a shallow depth of field separating screen from background. Numerals and face share the frame, split left and right by the phone's glow. The phone stays frame-left and his face frame-right throughout. Cold screen light rakes upward across his face against the warm streetlight. A one-star review pops in from the top and settles dead centre, pushing the red numerals down. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "眼睛瞟向支架",
        "change": "视线在红字上停住，嘴角向下按",
        "end": "视线移开，落向怀里"
      },
      "shot_language": {
        "composition": "红字与脸各占一半，画面被手机屏的光切成左右两块",
        "axis": "空间轴：手机恒在画面左、脸恒在画面右",
        "result": "一条一星差评从屏幕顶端弹入并停在正中，把红字压下去"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "dialogue": "行，扣就扣吧。",
      "sfx": "提示音、雨声",
      "transition_in": "cut",
      "notes": "单人镜；本镜不承载道具入画"
    },
    {
      "shot_id": "S02-SH003",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 3,
      "shot_size": "full",
      "camera": {
        "move": "pedestal_up",
        "speed": "slow",
        "from": "路边牙石高度、车轮与积水",
        "to": "升到平视，人与车停在路口的侧影整个入画",
        "height": "eye_level",
        "roll": "level"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "全景：外卖员在路口短暂停车，低头看手机，随后视线转向怀里那一小团湿透的重量，抬手把手机扣回支架，重新拧动油门。镜头从路边牙石高度、车轮与积水起幅，缓缓升到平视，他与车停在路口的侧影整个入画。路口灯柱恒在画面右缘，空间轴不换边。雨后夜色的青蓝底子打底，被商铺霓虹补上暖边。他把手机扣回支架时，指节在支架上停了一秒才松开。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A full shot: the delivery rider pulls over briefly at a junction and checks his phone, then turns his gaze to the soaked weight in his arms, flips the phone back onto the mount and twists the throttle again. The camera pedestals up with slow speed from kerb height among wheels and standing water, rising to eye level so he and the bike are framed whole at the junction. The lamp post stays at the right edge of frame throughout and the axis side never changes. The after-rain night sits on a blue-hour base with warm shopfront neon edging it. As he flips the phone back, his knuckles rest on the mount for a beat before letting go. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "在路口短暂停车，低头看手机",
        "change": "视线转向怀里那一小团湿透的重量",
        "end": "抬手把手机扣回支架，重新拧动油门"
      },
      "shot_language": {
        "composition": "人与车停在路口的侧影整个入画，路口灯柱在画面右缘",
        "axis": "空间轴：路口灯柱恒在画面右缘",
        "result": "他把手机扣回支架，指节在支架上停了一秒才松开"
      },
      "lighting": "blue_hour",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "dialogue": "他把差评留在了昨天的单里，把猫留在了今天。",
      "sfx": "雨声渐缓、远处车流涉水声",
      "transition_in": "cut",
      "transition_out": "dissolve",
      "notes": "单元末镜；本镜不承载构图与光学维"
    },
    {
      "shot_id": "S03-SH001",
      "unit_id": "U03",
      "scene_no": 3,
      "shot_no": 1,
      "shot_size": "wide",
      "camera": {
        "move": "push_in",
        "amplitude": "small",
        "speed": "slow",
        "from": "小区通道口、整栋楼入画",
        "to": "停在单元门与站在门前的人",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "远景：清晨，一个外卖员站在单元门外，怀里抱着纸袋；他低头看了看怀里的纸袋，把它换到另一只手，上前半步，停在门铃前抬手。镜头自小区通道口、整栋楼入画起幅，缓缓前推，停在单元门与站在门前的人，大景深交代空间关系。他在画面下三分之一居中，单元门洞是画面上方的暗方块，两侧绿化带做前景框；空间轴单元门恒在画面正上、通道恒在画面下。清晨低饱和漫射光下，墙面的潮痕与苔色都显出来。他换手时，脚下的湿砖上留下一个浅浅的转身印。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A wide shot at daybreak: a delivery rider stands in front of a block entrance with a paper bag held against his chest. He glances down at the bag, moves it to his other hand, takes half a step forward and raises a hand to the bell. The camera pushes in with small amplitude at slow speed from the estate walkway with the whole block in frame, settling on the entrance and the man before it; the deep focus lays out the space. He sits centred in the lower third with the dark doorway a block above him and planting on both sides framing the foreground. The doorway stays top-centre and the walkway bottom throughout. Low-saturation morning diffusion brings out the damp streaks and moss on the wall. As he swaps hands, a faint turn-print stays on the wet brick underfoot. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "站在单元门外，怀里抱着纸袋",
        "change": "低头看了看怀里的纸袋，把它换到另一只手",
        "end": "上前半步，停在门铃前抬手"
      },
      "shot_language": {
        "composition": "CHR-01 在画面下三分之一居中，单元门洞是画面上方的暗方块，两侧绿化带做前景框",
        "axis": "空间轴：单元门恒在画面正上、通道恒在画面下",
        "result": "他把纸袋换到另一只手，脚下的湿砖上留下一个浅浅的转身印"
      },
      "lighting": "overcast",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "dialogue": "送东西的。",
      "sfx": "鸟叫、远处垃圾车、雨后滴水",
      "transition_in": "dissolve",
      "notes": "单人镜；大景深交代空间关系"
    },
    {
      "shot_id": "S03-SH002",
      "unit_id": "U03",
      "scene_no": 3,
      "shot_no": 2,
      "shot_size": "medium",
      "camera": {
        "move": "arc",
        "speed": "slow",
        "from": "门铃面板正前",
        "to": "绕到 CHR-01 侧后，把背影与门框一起收进画面",
        "height": "eye_level",
        "roll": "dutch"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：外卖员的手指悬在门铃上方，按下第一声铃，随后把手收回身侧，肩膀绷住。镜头从门铃面板正前起幅，以弧形环绕缓缓绕到他的侧后，把他的背影与门框一起收进画面；机位略作荷兰角倾斜，外化按铃那一刻的失衡感。门框在画面左侧形成垂直边，他的背影偏右，走廊深处是唯一亮处；空间轴门框恒在左、走廊纵深深处恒在画面中心。走廊声控灯自上而下，把门框边缘照出一道白线；灯亮起又灭掉，他脚边的影子跟着缩短又拉长。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A medium shot: the delivery rider's finger hovers over the bell, presses once, then withdraws to his side with his shoulders locked. The camera arcs with slow speed around from directly in front of the panel to behind his shoulder, bringing his back and the door frame into the same frame, tilted into a slight dutch angle that externalises the imbalance of the moment. The frame edge stands as a vertical on the left, his back sits right, and the corridor depth is the only lit area. The frame edge stays left and the corridor depth stays centre throughout. A practical lamp overhead draws a white line along the frame edge, switching on and off so the shadow at his feet shortens and stretches again. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "手指悬在门铃上方",
        "change": "按下第一声铃",
        "end": "手收回身侧，肩膀绷住"
      },
      "shot_language": {
        "composition": "门框在画面左侧形成垂直边，CHR-01 的背影偏右，走廊深处是唯一亮处",
        "axis": "空间轴：门框恒在左、走廊纵深深处恒在画面中心",
        "result": "走廊声控灯亮起又灭掉，他脚边的影子跟着缩短又拉长"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "sfx": "门铃两声、门内无人应答、灯管电流声",
      "transition_in": "cut",
      "notes": "单人镜；荷兰角外化「按铃时的失衡感」，move 未取滚转类故 roll 可填"
    },
    {
      "shot_id": "S03-SH003",
      "unit_id": "U03",
      "scene_no": 3,
      "shot_no": 3,
      "shot_size": "close_up",
      "camera": {
        "move": "tilt_down",
        "amplitude": "small",
        "speed": "slow",
        "from": "门缝里露出的门框顶缘",
        "to": "停在猫的颈侧与抱着它的手",
        "height": "high",
        "roll": "level",
        "optics": "rack_focus"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "近景：外卖员的视线停在门上，随后低头看向怀里的猫，指腹在猫颈上停了一下，像是在确认什么。镜头从门缝里露出的门框顶缘缓缓下摇，停到猫的颈侧与抱着它的手；机位取俯角，焦点从门缝转移到猫的颈侧——焦点转移等于剪了一刀但没切镜头。猫蜷在画面中心，手指的边缘被压在画框下缘；空间轴门缝的光恒在画面上缘。门缝里漏出的室内暖光从侧面切进来，把指节照出层次；他的指腹在猫颈上来回碾过两下。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A close-up: the delivery rider's gaze rests on the door, then drops to the cat in his arms, a fingertip resting on its neck as if checking something. The camera tilts down with small amplitude at slow speed from the top edge of the frame visible through the door gap and settles on the cat's neck and the hands holding it. The high angle works with a rack focus that carries attention from the gap to the neck, cutting without cutting. The cat curls at frame centre with the fingertips pressed against the lower edge. The light through the gap stays along the top of frame throughout. Warm interior light spills sideways from the gap and layers the knuckles; his fingertip presses twice across the cat's neck. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "视线停在门上",
        "change": "低头看向怀里的猫",
        "end": "指腹在猫颈上停了一下，像是在确认什么"
      },
      "shot_language": {
        "composition": "猫蜷在画面中心，手指的边缘被压在画框下缘",
        "axis": "空间轴：门缝的光恒在画面上缘",
        "result": "焦点从门缝落到猫的颈侧，那里被指腹来回碾过两下"
      },
      "lighting": "side_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "dialogue": "门铃响了两声，没有人应，他就按了第三声。",
      "sfx": "门铃第三声、门内脚步声由远及近",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜；焦点转移等于剪了一刀但没切镜头"
    },
    {
      "shot_id": "S04-SH001",
      "unit_id": "U04",
      "scene_no": 4,
      "shot_no": 1,
      "shot_size": "medium",
      "camera": {
        "move": "static",
        "from": "固定机位，门缝高度、平视",
        "to": "固定不动，仅在门开合时随门框轻微位移",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 8000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：门只开了一条缝，门里的人半张脸藏在门后；她低头看见猫，伸手把它抱过去，动作很轻，随后抬眼，正对上门外的人，两个人都没动。镜头固定在门缝高度、平视不动，只在门开合时随门框轻微位移，浅景深把门外的人虚在近处。门缝把画面纵向切开：她在右（门内），他在左（门外），两人各占一半；对手戏屏幕方位固定，视线轴沿门缝相交，始终不越轴。走廊声控灯从他背后打来，把她的半张脸留在门内暗部。门缝从一条线开到一掌宽，声控灯灭掉又亮起，两道光在门框上交替。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A medium shot: the door stands ajar and the woman inside keeps half her face behind it. She looks down at the cat, reaches for it and lifts it gently, then raises her eyes and meets the man's, and neither of them moves. The camera holds a static shot at the height of the gap, level and still, shifting only slightly with the door frame as the door swings, a shallow depth of field blurring the man close to lens. The gap splits the frame vertically: she is right, inside; he is left, outside; each takes half. The screen positions hold and the eyelines meet along the gap without crossing the axis. A practical lamp overhead behind him leaves half her face in the dark interior. The gap widens from a line to a palm's width as the lamp clicks off and on, two lights trading places along the door frame. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "门只开了一条缝，CHR-02 的脸半藏在门后",
        "change": "CHR-02 低头看见猫，伸手把它抱过去，动作很轻",
        "end": "CHR-02 抬眼，正对上 CHR-01，两个人都在原地没动"
      },
      "shot_language": {
        "composition": "门缝把画面纵向切开：CHR-02 在右（门内），CHR-01 在左（门外），两人各占一半",
        "axis": "对手戏屏幕方位：CHR-02 恒在画面右、CHR-01 恒在画面左，视线轴沿门缝相交",
        "result": "门缝从一条线开到一掌宽，走廊声控灯灭掉又亮起，两道光在门框上交替"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "dialogue": "……它怎么会在你这儿。",
      "sfx": "门轴轻响、声控灯电流声、室外滴水",
      "transition_in": "fade_in",
      "notes": "对手戏：以门缝分侧做画面区隔；静止镜内有门缝与灯光在变，不违「禁无结果的静止」"
    },
    {
      "shot_id": "S04-SH002",
      "unit_id": "U04",
      "scene_no": 4,
      "shot_no": 2,
      "shot_size": "close_up",
      "camera": {
        "move": "push_in",
        "amplitude": "small",
        "speed": "slow",
        "from": "门缝中线、两人之间的空隙",
        "to": "停在 CHR-01 低下的脸",
        "height": "high",
        "roll": "level",
        "optics": "rack_focus"
      },
      "duration_ms": 7000,
      "aspect_ratio": "16:9",
      "prompt_zh": "近景：门外的人视线停在对方脸上，随后低下头，把视线移向怀里的手套，手指在身侧收拢，肩膀塌下去。镜头从门缝中线、两人之间的空隙缓缓前推，停在他低下的脸；机位取俯角，焦点从门缝滑到他的睫毛上——焦点转移等于剪了一刀但没切镜头。他的脸压在画面下三分之二，门框上缘留出细窄的亮带；轴线沿用本场，她恒在画面右（本镜仅以虚化的门框边缘入画），他恒在左。走廊残光勾出他的侧脸轮廓，正面几乎无光；他睫毛上挂着一滴没落下的水。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A close-up: the man outside holds his gaze on her face, then drops his head, eyes sliding to the gloves in his arms, fingers curling at his sides and his shoulders sinking. The camera pushes in with small amplitude at slow speed from the centre line of the gap and the space between them, settling on his lowered face. The high angle works with a rack focus that slides from the gap to his lashes, cutting without cutting. His face presses into the lower two thirds with a narrow band of light along the top of the frame. The axis holds: she stays right, entering only as a softened door-frame edge, and he stays left. Leftover corridor light rims his profile while his face stays almost unlit, and a drop of water hangs unspent on his lashes. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "视线停在对方脸上",
        "change": "低下头，把视线移向怀里的手套",
        "end": "手指在身侧收拢，肩膀塌下去"
      },
      "shot_language": {
        "composition": "CHR-01 的脸压在画面下三分之二，门框上缘留出细窄的亮带",
        "axis": "沿用本场轴线：CHR-01 恒在左、CHR-02 恒在右（本镜 CHR-02 仅以虚化的门框边缘入画）",
        "result": "焦点从门缝滑到 CHR-01 的睫毛上，睫毛上挂着一滴没落下的水"
      },
      "lighting": "rim_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": [],
      "dialogue": "昨晚在楼道里捡的。",
      "sfx": "室内安静、门缝里的空气声",
      "transition_in": "cut",
      "transition_out": "cut",
      "notes": "对手戏；单元末镜，transition_out 交代出点"
    },
    {
      "shot_id": "S05-SH001",
      "unit_id": "U05",
      "scene_no": 5,
      "shot_no": 1,
      "shot_size": "full",
      "camera": {
        "move": "pan_right",
        "amplitude": "small",
        "speed": "slow",
        "from": "沙发一角的坐垫",
        "to": "停到站在窗边的 CHR-01",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "全景：她把猫放在两人之间的坐垫上，起身去倒水；他没有坐，站在窗边，手插在口袋里。镜头从沙发一角的坐垫缓缓右摇，停到站在窗边的他，大景深让沙发、地板与窗同时可读。沙发与窗分列画面左右，中间是空着的大片地板，猫在两者之间挪动；对手戏屏幕方位固定——她恒在画面左（沙发侧）、他恒在画面右（窗侧），视线轴横贯画面、不越轴。清晨窗外漫射光从他背后进来，在室内形成大面积柔和过渡。猫从坐垫上挪了两步，把自己搁在两人之间的地板上，尾巴慢慢收拢。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A full shot: she sets the cat on the cushion between them and gets up to pour water, while he stays on his feet by the window with his hands in his pockets. The camera pans right with small amplitude at slow speed from the cushion on the sofa arm to him at the window, the deep focus keeping sofa, floor and window readable at once. Sofa and window hold the left and right of frame with bare floor between them and the cat shifting across it. The screen positions hold, she frame-left by the sofa and he frame-right by the window, and the eyeline runs across the frame without crossing the axis. Diffused morning light through the window comes in behind him and softens the whole room. The cat shuffles two steps off the cushion and settles itself on the floor between them, its tail curling in slowly. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "CHR-02 把猫放在两人之间的坐垫上",
        "change": "CHR-02 起身去倒水，CHR-01 没有坐",
        "end": "CHR-01 站在窗边，手插在口袋里"
      },
      "shot_language": {
        "composition": "沙发与窗分列画面左右，中间是空着的大片地板，猫在两者之间挪动",
        "axis": "对手戏屏幕方位：CHR-02 恒在画面左（沙发侧）、CHR-01 恒在画面右（窗侧），视线轴横贯画面",
        "result": "猫从坐垫上挪了两步，把自己搁在两人之间的地板上，尾巴慢慢收拢"
      },
      "lighting": "soft_key_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "dialogue": "坐吧。它认你。",
      "sfx": "挂钟走针、猫爪在坐垫上的窸窣",
      "transition_in": "cut",
      "notes": "对手戏：两人分置画面左右并以大片空地做区隔，主体唯一性明确"
    },
    {
      "shot_id": "S05-SH002",
      "unit_id": "U05",
      "scene_no": 5,
      "shot_no": 2,
      "shot_size": "medium",
      "camera": {
        "move": "truck_right",
        "amplitude": "small",
        "speed": "slow",
        "from": "CHR-01 身侧半米",
        "to": "右移到窗框边，把窗户与外面的天亮一起收进画面",
        "height": "eye_level",
        "roll": "level"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：他站在窗边不动，随后转身、绕开地板上的猫，走向画面左侧，坐到坐垫边缘，肩膀放松下来，松开插在口袋里的手。镜头从他身侧半米缓缓右移，右移到窗框边，把窗户与外面的天亮一起收进画面。他在画面右三分之一，左侧留出通往沙发方向的室内纵深；轴线沿用本场，她在左、他在右。窗前光把他的影子投在地板上，随他走动移过猫的身体。他坐到坐垫边缘时，坐垫陷下一道褶。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "A medium shot: he stands still at the window, then turns, steps around the cat on the floor and walks toward the left of frame, sitting down on the edge of the cushion with his shoulders easing and his hands coming out of his pockets. The camera trucks right with small amplitude at slow speed from half a metre off his side, moving to the window frame so the window and the brightening sky beyond come into the same frame. He sits in the right third with interior depth toward the sofa opening on the left, and the axis holds with her left and him right. Window light throws his shadow across the floor, sliding over the cat as he moves. When he settles on the cushion edge, the cushion takes a crease under him. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "站在窗边不动",
        "change": "转身，绕开地板上的猫，走向画面左侧",
        "end": "坐到坐垫边缘，肩膀放松下来"
      },
      "shot_language": {
        "composition": "CHR-01 在画面右三分之一，左侧留出通往沙发方向的室内纵深",
        "axis": "沿用本场轴线：CHR-02 在左、CHR-01 在右",
        "result": "他松开插在口袋里的手，绕过猫，坐到坐垫边缘，坐垫陷下一道褶"
      },
      "lighting": "soft_key_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "dialogue": "那……我坐。",
      "sfx": "布料摩擦、挂钟走针",
      "transition_in": "cut",
      "notes": "对手戏；本镜不承载光学维"
    },
    {
      "shot_id": "S05-SH003",
      "unit_id": "U05",
      "scene_no": 5,
      "shot_no": 3,
      "shot_size": "extreme_wide",
      "camera": {
        "move": "static",
        "from": "固定机位，客厅全景、平视略高",
        "to": "固定不动",
        "height": "high",
        "roll": "level"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "大远景：两个人和猫各坐坐垫一端，猫在中间；谁都没有开口，只有光在变，屋里的东西各自停在自己的位置上。镜头固定在客厅全景、平视略高，全镜不动。两个人和猫落在画面下三分之一，上方三分之二是窗与天亮；空间轴窗恒在画面右、门洞恒在画面左。清晨漫射光均匀铺开，室内没有硬阴影；窗外天色由青灰转为浅白，屋里的影子边缘跟着变软。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "prompt_en": "An extreme wide shot: the two of them sit at opposite ends of the cushion with the cat between them. Neither speaks; only the light moves, and everything in the room stays where it is. The camera holds a static shot from slightly above eye level on the whole living room, unmoving throughout. The pair and the cat occupy the lower third with window and growing daylight filling the upper two thirds. The window stays right and the doorway stays left throughout. Flat morning diffusion leaves no hard shadow indoors as the sky outside shifts from slate grey to pale white and the edges of every shadow in the room soften with it. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "action": {
        "start": "两个人各坐坐垫一端，猫在中间",
        "change": "谁都没有开口，只有光在变",
        "end": "屋里的东西各自停在自己的位置上"
      },
      "shot_language": {
        "composition": "两个人和猫落在画面下三分之一，上方三分之二是窗与天亮",
        "axis": "空间轴：窗恒在画面右、门洞恒在画面左",
        "result": "窗外天色由青灰转为浅白，屋里的影子边缘跟着变软"
      },
      "lighting": "overcast",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "dialogue": "窗外天亮了，屋里没人急着说话。",
      "sfx": "挂钟、窗外早市远景、猫的呼吸",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜兼全片末镜；静止镜内有光在变，不违「禁无结果的静止」；本镜不承载光学维"
    }
  ],
  "forbidden_items": [],
  "aigc_meta": {
    "AIGC": {
      "Label": "1",
      "ContentProducer": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "ProduceID": "FR-PK-20261013-CASE0001",
      "ReservedCode1": "",
      "ContentPropagator": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "PropagateID": "FR-PK-20261013-CASE0001",
      "ReservedCode2": ""
    }
  }
}
```

## 4 评测结论

对照 SW-007 的验收标准：**「提示词集可被主流视频模型直接消费；角色/场景/镜头描述完整、无歧义、可直接投喂」**；并叠加规范 §3 字段契约、§4.1 八维双条件、§3.4 外观只定义一次、§5 AIGC 元数据、§6.1 基准唯一五组口径。

| # | 评测项 | 手段 | 结论 |
| --- | --- | --- | --- |
| 1 | 交付包结构完整 | 顶层**八段**（`schema_version`／`meta`／`style_bible`／`characters`／**`props`**／`units`／`shots`／**`forbidden_items`**／`aigc_meta`）逐段核对 | ✅ **9 个顶层键**齐备（必备 6 段 + 可选段 `characters`／`props`／`forbidden_items`）；每镜 **14 个**必备字段齐备（**v2.0 起**，新增 `prop_refs`） |
| 2 | **承继守恒（不改导演决策）** | 交付包与 `CASE-STB-001` 逐字段 diff | ✅ 14 镜的 `shot_id`／`unit_id`／`scene_no`／`shot_no`／`duration_ms`／`shot_size`／`camera.*`／`action.*`／`shot_language.*`／`dialogue`／`sfx`／`transition_*`／`character_refs`／**`prop_refs`** **逐项相同**；差异仅**三类必改 + 一类条件改写** + 本层补出字段。⚠️ **v2.0 更正（`ISSUE-011` 闭环）**：上游 `shots[].prop_refs` **回到承继列**——v1.1 把它移出的两条理由（「交付规范 §3.6 无该字段」「交付 schema `shot.properties` 无该键」）**随 V2.0 契约补齐而全部消失**；本包 14 镜 `prop_refs` 与上游 `CASE-STB-001` **逐项相同**（10 镜 `["PRP-01"]`、4 镜 `[]`）。同理上游**顶层** `forbidden_items` 自 v2.0 起**原样承继**（本包与上游同为 `[]`）。 |
| 3 | 镜数与镜序守恒 | `shots` 数、`units[].shot_ids` 顺序 | ✅ 同为 14 镜 / 5 单元（3+3+3+2+3）；镜序不变 |
| 4 | 时长守恒 | Σ`duration_ms` 与 `meta.total_duration_ms`、上游 `total_duration_ms` 三方比对 | ✅ 均为 **81000ms**，三方一致（本层未改时长） |
| 5 | **补出的必填字段**（本层存在的理由） | 逐镜核对 `style_ref`／`prompt_zh`／`prompt_en`／`aspect_ratio` | ✅ 14 镜全部补出；`style_ref` 恒为 `STYLE-01`（§3.8 阻断项已满足）。⚠️ 另 **`prop_refs`** 属 `shot.required`（v2.0 起）但**由本层承继、非补出**——见第 2 项与第 20 项 |
| 6 | 顶层锚补齐 | `style_bible` / `characters[]` / **`props[]`** 完整性 | ✅ `style_prompt_en`（上游缺）与 `appearance_lock_en` ×2（角色）+ ×1（道具）均由本层补出且与中文同义；**`props[]`** 的 `prop_id`／`name`／`role`／`appearance_lock_zh` 与上游**逐字一致**（上游台账字段 `design_source` **不入包**） |
| 7 | **八维双落地** | 14 镜 × 8 维 = 112 格，逐格在正文中找出对应句 | ✅ 112 格全部有字段承载且能定位到正文句（详见 §5 陷阱位 1） |
| 8 | 外观只定义一次 | 把 `appearance_lock_zh` 与 `appearance_lock_en` 的特征词在 14 镜正文中扫描 | ✅ **0 命中**——正文无「短发／浓眉／深蓝色／冲锋衣／反光条／齐肩黑发／米白／开衫／旧疤」等特征词 |
| 9 | **单人替身法则** | 逐镜判定主体数，核查单角色镜是否有稳定指称 | ⚠️→✅ **v1.1 更正并整改（评审 PR-05）**：原自评「单人镜每镜都出现稳定指称」**失实**——实测英文侧 6/9 镜用简写 `the rider`、`S03-SH003` **中英双侧皆无**（仅 `his`／「他」）。**已整改**：JSON 块内 4 处 `the rider` → `the delivery rider`；`S03-SH003`、`S03-SH002` 的起句补具名锚点。**复验：9 个单人镜中英双侧均有稳定指称，`the rider` 残留 0 处** |
| 10 | 指称一致性 | 同一角色全片指称词组去重 | ⚠️→✅ **v1.1 更正并整改（评审 PR-05）**：原自评「无第二套指称」**失实**（中文侧有「外卖员」与「他」混用、英文侧 `the delivery rider` 与 `the rider` 并存）。**已整改**：英文侧统一为 `the delivery rider`；并补 `meta.notes` 的**指称映射声明**（`CHR-01 → 外卖员／the delivery rider`、`CHR-02 → 门里的人／the woman inside`），使 `guards` 的指称扫描有**机器可比对的依据**（评审 PR-06）。⚠️ **仍须人工复核**：多角色镜（第 4／5 场）中文用「门里的人／门外的人／她／他」、英文用 `the woman inside`／`the man outside`／`she`／`he`——多角色同框时模型可依上下文区分，**本条未按单人镜口径强制**；本层暂无指称一致性脚本判据（登记为后续项） |
| 11 | 景别与运镜每镜必有 | 14 镜 `shot_size`／`camera.move` 取值合法性 | ✅ 全部取规范枚举值；无自造词 |
| 12 | 幅度／速度省略规则 | `amplitude`／`speed` 取值集合 | ✅ 只出现 `small`／`slow`／`fast`，其余**省略该键**（**v1.1 更正 · 评审 PR-02**：原为「写空串」，但交付 schema 的枚举**不含空串** → 改「留空即省略键」）；**无 `medium`／`normal`** |
| 13 | static／pov 不带幅度速度 | S04-SH001／S05-SH003 | ✅ 两镜**均省略 `amplitude`／`speed` 两个键**（留空口径见第 12 项） |
| 14 | 转场单侧表达 | 单元内非末镜的 `transition_out` | ✅ 单元内非末镜**省略 `transition_out` 键**；`fade_out`／`dissolve`／`cut` 只出现在单元末镜；单元边界＝末镜出点＋首镜入点（两个半段） |
| 15 | `lighting` 为纯词表值 | 14 镜 `lighting` + `style_bible.lighting_default` | ✅ 全部为词表 code（**投影规则①已拆分**，中文光位说明移入正文）；上游描述性 `lighting_default` 已按语义映射并写进 `meta.notes` |
| 16 | 风格锚点封闭 | `style_anchors` 之外的风格词在正文中扫描 | ✅ 正文风格句只用 4 条锚的中英文对应；**未出现**「水彩」「厚涂」等清单外风格词 |
| 17 | 负向词不进正文 | 扫描「（负向：…）」「Negative prompt:」「no …」类残留 | ✅ 0 命中；负向意图一律承载在 `negative_global`，未写进 `prompt_*` |
| 18 | 正文不含模型参数指令 | 扫描 `--ar`／`--v`／`--style` 等 | ✅ 0 命中；画幅走 `aspect_ratio` 结构字段 |
| 19 | 要素顺序与运镜独立成句 | 逐镜核对顺序；英文侧找 `The camera` 独立句（**v1.1 起由 R34 脚本判据兜底**） | ⚠️ **v1.1 更正（评审 PR-04）**：原自评「（14 镜中 8 镜有运镜）全部独立成句」**失实**——实测 **`S01-SH002` 违反**（`as the camera tilts down…` 为**小写从句、并入起句**）。已修该镜中英正文（起句改「景别 + 主体／环境」名词短语、运镜另起独立句），并新增 **R34** 使该形态**可脚本核查**——这类失败**人眼看不出来**（句子读起来很自然），无判据必漏。要素顺序本身合规 |
| 20 | 引用完整性（§3.8 阻断项） | `style_ref`／`character_refs`／**`prop_refs`** 命中校验 | ✅ `STYLE-01` 命中；`CHR-01`／`CHR-02` 命中；`PRP-01` 命中——**引用它的镜头数 = 10**（与上游一致）。⚠️ **v2.0 更正**：该结论在 v1.1 下**不成立**（当时交付包不含该字段），随契约补齐**现已成立**；**R35** 自 v2.0 起由「本层不得输出该键」**反转为正向「道具锚一致性」**（每镜必备该键 + 逐项命中 `props[].prop_id`） |
| 21 | `units` 约束 | 单元镜数 ∈[2,3]、单元内运镜不重复 | ✅ 3/3/3/2/3；各单元内 `camera.move` 无重复 |
| 22 | AIGC 元数据块 | 唯一性、`ProduceID` 与 `pack_id` 同值、字段齐全 | ✅ 仅一份；`ProduceID = PropagateID = meta.pack_id`；`ContentPropagator` 首次写入与 `ContentProducer` 同值；7 字段齐全 |
| 23 | 元数据非编造 | `pack_id`／`created_at`／`session_id`／`task_id`／`statement_id` 回查 `pack_meta` | ✅ 六项均为注入值或占位符；**无自拟值** |
| 24 | 缺口台账未越权 **+ 缺口可见性** | 交付包是否出现 `unspecified`；`meta.notes` 是否登记所依据的上游缺口 | ✅ 未出现 `unspecified`（规范 §3.1 顶层**八段**无此字段）；上游台账保持原状、未改写未搬运。**v1.1 补（评审 §3-B）**：`meta.notes` 已按**可机器读**形式逐条登记 **9 条上游未闭合缺口**（`[GAP] 字段路径 \| owner \| fill_stage \| fill_fallback 摘要`）——把「交付后不可见」降为「可见但仍不动台账」 |
| 25 | **本层规则脚本化并逐条负向验证** | `validate_output.py` 的交付包形态规则 **R26~R36** 全跑 | ✅ 正向：**53 项通过 / 0 失败 / 0 警告**（整工程 4 个用例）；负向（`tests/negtest_pack_rules.py`）：**32 个越界样本全部 `EXIT=1`**（R26×2 / R27×3 / R28×2 / R29×3 / R30×3 / R31×4 / R32×2 / **R33×6 / R34×2 / R35×2 / R36×3**）；另 **3 个已知盲区**如预期不触发（登记于 `../../03-工程代码/prompts/CFG-007_SCHEMA.md` 与脚本内盲区段） |
| 26 | **与交付门禁脚本结论一致（双脚本对拍）** | 同一份包分别投喂 `prompts/validate_output.py`（R19 质量门）与 `delivery/validate_pack.py`（门禁⑫），比对结论 | ✅ **修正后一致**：两脚本均判「整片 + 5 个单元 11 项全通过」。⚠️ **修正前不一致**：门禁脚本对 **U04（2 镜 / 1 static）** 报 BLOCK，而另两处（`validate_output.py` R19 与参照实现 `audit_shots.py`）判通过——根因是门禁脚本**判据用比例直接比阈值**、废弃了自带 `_allow()` 的容差算法（详见 §5 陷阱位 12）。现两脚本均为「门禁 BLOCK 0」，与 `CFG-004_demo_pack.json` 回归结果一并留档 |
| 27 | **与交付契约的四个冲突点：v2.0 起全部清除** | 门禁脚本带 schema 全量跑；逐条对照评审 PR-01／PR-02／PR-07／自查 `ISSUE-012` | ✅ **v2.0 起四项全解**。① **PR-02 留空口径** → **本层内解**（全包 41 处留空改「省略键」，v1.1 已完成），门禁 BLOCK **24 → 1**；② **PR-01 `prop_refs` 无落点** → **契约侧补齐**（规范 §3.6 增 `prop_refs` + 顶层增 `props[]`），本层恢复承继，`ISSUE-011` **闭环**；③ **PR-07 `prompt_en` 上限 900 字符** → **契约侧上修**（900 → **1200**，实测 1113 已在内），`ISSUE-015` **闭环**，该 BLOCK **归零**；④ **上游顶层 `forbidden_items` 无容器**（**自查发现**，见陷阱位 16）→ **契约侧增设容器**，本层原样承继，`ISSUE-012` **闭环**；**R36** 仍机器化「契约外字段禁入」。**结论：交付门禁 0 BLOCK 是契约缺陷被真正修好后的结果，不是把产物改到「看起来能过」** |

## 5 陷阱位（本用例专门埋设的失败模式）

| # | 陷阱 | 说明 | 本用例的正确处理 |
| --- | --- | --- | --- |
| 1 | **八维双落地 vs 长度建议（v2.0 已化解）** | 规范 §4.1 要求八维**同时**写进正文，**v1.3 及更早**的 §3.7.6 又建议单镜 40–120 字（中文）。八维全承载的镜头实测下不来——1 个镜头要写清景别＋运镜（含起止）＋角度＋光学落点＋构图＋轴线＋光线＋画面结果＋风格，中文普遍在 **150–200 字** | 本用例**按八维优先**书写（150–200 字）。**v2.0 已把 §3.7.6 的建议值上修为中文 90–280 字／英文 450–1200 字符**（`T-056`），本用例全部镜头**落在新建议区间内**——**该张力是规范自身的缺陷，已随契约升版一并修正**；`CFG-006` schema 的 `prompt_zh` 上限 600、`prompt_en` 上限 1200，容纳无碍 |
| 2 | **上游字段值形态与交付包 schema 冲突** | 上游 `lighting` 与 `style_bible.lighting_default` 允许「词表值 + 中文光位说明」（如 `practical_light——楼道感应灯在下半张脸上打出一道硬边`），而交付包 schema 要求该字段匹配 `^[a-z][a-z_]*$` | **拆分**：字段只留词表 code，中文光位说明移入 `prompt_zh`、英文移入 `prompt_en`（见 S01-SH001 的光线句）。这是**投影规则①**，属「三类必改 + 一类条件改写」中的一类（v1.1 起表述统一，原写「唯一允许不逐字承继的两处之一」不够准确） |
| 3 | **上游取值不在词表内** | `style_bible.lighting_default` = 「夜景：低调光，湿地面反光补光；清晨：低饱和漫射光」——**词表 15 值里没有「低调光」** | 按语义映射为 `practical_light`（雨夜实景补光为全片光质基底），并在 `meta.notes` **写明映射依据与「该默认值实际不被引用」**；**不得自造 code**。上游的分时相差异已由 14 镜的逐镜 `lighting` 分别承载 |
| 4 | **`name` 为「未指定」时如何满足单人替身法则** | 规范 §4.4 要求单角色镜用「**具名锚点**」，但本案两名角色的 `name` 都是「未指定」，而事实类信息**不得编造**（不能自拟「陈默」） | 给出**可执行替代口径**：用剧本层已定义的 `identity` 作**稳定指称**（中文「外卖员」／英文 `the delivery rider`），且**全片一致**。锚点的本质是**唯一且不变**，不是「必须是人名」——这是评估第 9/10 项的依据 |
| 5 | **外观只定义一次 vs 正文信息量** | 14 镜里「他伸手把猫抱过去」「雨水顺袖口下淌」这类动作对象极易被写成「穿深蓝色冲锋衣的外卖员」 | 正文**一个外观特征词都不写**；道具与角色只以稳定指称 + 瞬时状态出现。评估第 8 项做了**反向扫描**（0 命中）而非只做正向抽查 |
| 6 | **上游残留的口径违规** | `CASE-STB-001` 的 S03-SH002 残留 `camera.amplitude = "medium"`——违反 `storyboard_v1` v2.1.0 硬性约束 6（`medium` 为默认值应留空），且**当轮校验器无判据**（`CFG-007_SCHEMA.md` 声称由「R13」判，而 R13 实为时长区间——**该声称有误**） | **两侧各修一处**：① 上游用例改为 `""`（源头修正）；② 本层按投影规则③**规范化**（`medium` 与「留空」语义无损等价，不算改决策）——⚠️ **v1.1 更正**：规范化的**表达方式**由「写空串」改为「**省略该键**」（见陷阱位 13）；③ 新增脚本判据 **R26 MOVE_PARAM_OMISSION**；④ 更正 `CFG-007_SCHEMA.md` 的错误声称。**这条是上一轮遗留缺陷的自查发现，如实登记** |
| 7 | **元数据不得编造** | 模型最擅长的「补一个看起来对的编号」——`pack_id` 按 §5.2 格式自拟、`created_at` 编一个合理时间 | `meta` 六项全部取自注入的 `pack_meta`；`provider_code` 未分配时写 `{{PROVIDER_CODE}}` 占位（**不编**）。评估第 23 项专查此项 |
| 8 | **分段策略** | 14 镜 × 八维双写 ≈ 1.2 万字符以上，一次直出必然截断或后半段漂移 | 本用例 `segment = all` **仅为拿到一份完整包跑门禁**；生产环境必须分段：`package_head` → `unit:U01` → `unit:U02` → `unit:U03` → `unit:U04` → `unit:U05`，共 6 次调用。⚠️ **v1.1 修正（评审 PR-08）**：模板的 `segment` **默认值已由 `all` 改为 `auto`**（按上游镜数自动决定），并把「输出超单次窗口」列入 `fallback.output_too_long`——原默认值 `all` 与模板自述「超长必然截断」**自相矛盾**。分段粒度＝规范 §3.5「生成单元＝一次生成调用所提交的完整分镜块」的粒度，**不是按字数硬切**。⚠️ 另：**分段产物不可能单独过交付包 schema**（评审 PR-09，已更正模板示例 3 的失实表述） |
| 9 | **`U01.notes` 的内部标注** | 上游 `U01.notes` 含「本单元三镜分别对应剧本第 1 场 action 的三个节点（①空间 ②主体 ③状态），无空切」——这是**内部校验标注**，不应进交付物 | 按投影规则②清理为「单人戏，按单人替身法则处理」；同理 14 镜的 `notes` 全部删除「本镜对应 action 节点①」类内部标注 |
| 10 | **上游 12 处 `lighting` 的中文说明未丢失** | 拆字段时最容易把中文光位说明直接删掉（删了就等于丢了「光在干什么」——而这正是 §4.4「禁无光的镜头」要防的） | 逐处**移入正文**而非丢弃：中文说明进 `prompt_zh` 的光线句、英文进 `prompt_en`；字段侧只留 code。评估第 15 项与第 7 项共同覆盖 |
| 11 | **中英判据的语义尺度错配**（R28 首跑实测） | 外观复用检测若对**中英锚串统一取 3 字符**：中文 3 字已是语义单位，英文 3 字符只是**词内片段**——`the`（来自 "the right wrist"）、`old`（来自 "an old scar"）会在**任何一段英文正文**里命中。首跑即报 **773 处命中**，规则形同失效（14 镜几乎每镜都被判「复述外观」） | **两侧判据分别定义**：中文取**连续 3 字**、英文取**连续 3 个实词**（先剔停用词）。修正后本用例 14 镜正文 **0 命中**，且评估第 8 项的「反向扫描 0 命中」结论才真正成立。教训：**跨语言规则的阈值不能按字符数平移** |
| 12 | **小样本下的占比门槛离散化**（门禁脚本既有缺陷，本轮自查发现） | `delivery/validate_pack.py` 的门禁⑫对「静止镜占比 40%」「单一运镜占比 35%」两条**用了比例直接比阈值**，而**报错文案却引用 `_allow(...)` 的绝对个数**——n=2 时 1/2 = 50% > 40% 必判 FAIL，但容差算法的本意正是 `max(1, ceil(ratio*n))`，2 镜单元**允许 1 个**。后果：同一份包，门禁脚本报 **BLOCK** 而 `validate_output.py` R19 与参照实现 `audit_shots.py` 都判**通过**——**两个校验器对同一产物结论相反**（实测 U04：2 镜 / 1 static） | 按参照实现修正判据为**计数比较**（`static_cnt > _allow(...)`）并统一文案；修正后门禁 **BLOCK 1 → 0**，与另两处一致，`CFG-004_demo_pack.json` 回归不变。该缺陷只在**短单元**暴露（整片 14 镜时比例判定凑巧同结果），说明**边界样本必须进回归**。本脚本 docstring 早已声明「容差算法与 `audit_shots.py` 一致」，此处属**实现与自述不符**——与本轮 R26 的「口径写了却没判据」同一性质：**依赖人记住的口径等于没有口径** |
| 13 | **「留空」的两种表达：空串 vs 省略键**（P0 · 评审 PR-02） | 上游把「不强调／不适用」表达为**空串**（`amplitude: ""`、`transition_out: ""`），本层原投影规则③也「规范化为空串」。但交付 schema 的**枚举与 vocabRef 不含空串**（`amplitude` 三值、`speed` 三值、`optics` 五值、`transition_in/out` 五值；`lighting` pattern `^[a-z][a-z_]*$`），`characters[].ref_image` 亦为 `type:string` 不允 `null` | **改「留空即省略该键」**——JSON Schema 里「键缺失」与「值为空」是两件事，且**可选字段的键缺失天然合法**。全包 41 处留空改省略键后，门禁 BLOCK **24 → 1**（余 1 条为 `prompt_en` 上限，**v2.0 已上修至 1200、现已归零**）。**教训：把「语义上的空」映射成「字符串上的空」，会在契约边界上翻车**；新增判据 **R33** 兜底 |
| 14 | **上游有、交付契约无的字段 —— v2.0 契约侧补齐**（P0 · 评审 PR-01 → `ISSUE-011`） | **v1.1 时的困境**：上游 `storyboard_v1` 的 `shots[].prop_refs`（道具锚引用）**不在交付规范 §3.6 的镜头字段集**里（当时规范全文无「道具」二字，已逐字核对），而交付 schema 的 `shot` 是 `additionalProperties:false`——**承继它会被门禁判「多余属性」**，不承继则道具锚的结构化落地在最后一公里断掉 | **v1.1 的临时处置**（**现已撤销**）：本层不输出该结构键，道具信息只由正文承载；同时登记 `ISSUE-011` 提请定案。**v2.0 的正式解法**（`T-054`）：契约侧**三项同改**——规范 §3.6 增 `prop_refs`、§3.4.1 增顶层 `props[]`（与 `characters[]` 同构）、schema 同步（`prop_refs` 进 `shot.required` 13 → 14）。**本层随之恢复承继，R35 由「禁入」反转为正向「道具锚一致性」**。**与陷阱位 6 同源：模板承诺了契约不接受的字段，等于给自己埋了一个必爆的雷**——这次拆掉的是雷本身，不是绕着走 |
| 15 | **门禁脚本的风格漂移误报：子串包含 ≠ 词元匹配**（本轮自查发现） | `delivery/validate_pack.py` 门禁⑯ 用 `w in v` 判「正文是否出现锚点清单外的风格词」；而词表 `style_tags` 含「赛璐璐上色」、本片锚点是「**柔和**赛璐璐上色」→ 正文**逐字复述锚点**反被判「清单外风格词」（**9 镜误报**） | 判据修两条：① 清单词若被任一锚点**包含**，则不视为「清单外」；② 比对前先把正文里的**锚点原文剔除**，再在剩余文本里找清单外词。修正后误报归零。这与本层 **R28 的中英尺度错配同源**——都是「**字符串粒度 ≠ 语义粒度**」：R28 是「3 字符 ≠ 3 个词」，本条是「子串 ≠ 词元」 |
| 16 | **判据只查「必备」不查「多余」：清单外字段无人管**（本轮自查发现 · 承接评审 PR-14） | 评审 PR-14 指出「两处清单不一致会留下『清单外字段无人管』的漏洞」。顺着这条**去查模板自身**，发现**第 6 处**不一致——模板头部注释的承继清单列 `forbidden_items` 而漏 `notes`，与 `system` 硬性约束 1／`guards` 的 diff 清单**不符**；再往下查**判据侧**：`R27` 只校「必备字段是否齐备」，**不校「是否多出契约外字段」** → 任何上游带来的、规范里没有的字段都能悄悄进入交付包，**到门禁才被 `additionalProperties:false` 拦下（拦得太晚，且只看得到一条汇总报错）** | 两侧都补：① 模板三处清单**逐项对齐**（并显式写明「上游顶层字段按投影表处理，不在承继清单内」）；② 新增 **R36 NO_EXTRA_KEY**——检查顶层／`shots[]`／`units[]`／`characters[]`／**`props[]`**／**顶层 `forbidden_items`**／`meta`／`style_bible`／`aigc_meta` **九处**（v2.0 起）是否出现契约外键，且字段集**直接读交付 schema**（`single source of truth`，刻意不另写一份会陈旧的清单）——**这正是它的设计价值：v2.0 契约扩容时本条零改动**（它不持有清单，只持有「读 schema」这一个动作）。**顺带查出 `ISSUE-012`**：上游顶层 `forbidden_items` 在交付包**当时无容器**（规范 §3.1 顶层六段无它；§3.3 `negative_global` 覆盖的是**画质与伪影**、非「内容层禁忌」；`meta.compliance` 亦非其容器），而 `CFG-008_manifest.yaml` 却写「**须原样承继**」→ v1.1 一并更正为「不搬运 + 登记缺口」；**v2.0 契约侧增设该容器后，本层改为原样承继（`ISSUE-012` 闭环）**。**教训：判据只管「该有的在不在」，不管「不该有的在不在」，漏洞就一定从后门进来** |

## 6 验证状态

| # | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 模板 `shot_prompt_v1` **v2.0.0** 结构自检 | ✅ 通过 | `validate_templates.py`：YAML 解析、五节齐备、变量引用一致（声明 5 / 引用 5）。整目录口径：**57 通过 / 8 失败 / 2 警告**，8 项失败全属既有 `T-036`（通用模板缺 `context` 节），**本轮零新增**。⚠️ 行数沿革：533（v1.0.0）→ **660**（v1.1.0）→ **716 行**（v2.0.0），各版 YAML 解析均复验通过 |
| 2 | 产物 JSON 静态契约自检 | ✅ **通过（2026-10-13 补测；v2.0.0 复验）** | `validate_output.py`（交付包形态 **R26~R36**）**53 项通过 / 0 失败 / 0 警告**。⚠️ 此项为**静态契约**校验，**不等于**「模型能生成合规产物」 |
| 3 | 规则有效性（负向验证） | ✅ **通过（2026-10-13 补测；v2.0.0 扩样）** | 逐条构造越界样本（`tests/negtest_pack_rules.py`）：**32 个样本全部 `EXIT=1`**（R26×2 / R27×3 / R28×2 / R29×3 / R30×3 / R31×4 / R32×2 / R33×6 / R34×2 / **R35×2** / R36×3）；另 **3 个已知盲区**如预期不触发并登记在案（**合计 35 项全符合预期**）。只跑通过样本证明不了校验器有效——此步不可省 |
| 4 | 交付门禁脚本 `validate_pack.py` | ✅ **BLOCK 0（2026-10-14 带 schema 复跑）——v2.0 起归零** | 本包**可直接投喂**该门禁脚本（这正是 SW-007 输出形态定为「直接产出交付包 JSON」的收益）。**BLOCK 24 → 1（v1.1 本层内解留空口径）→ 0（v2.0 契约侧上修 `prompt_en` 上限至 1200 字符）**。原剩余 1 条为 `shots/0/prompt_en is too long`（`S01-SH001` = 1113 > 旧上限 900）——**本层不压缩维度**（压缩违反 §4.1 八维双落地），由**契约责任方按 `T-056` 上修**后归零。WARN 均可解释：`provider.code`（占位符未回填，正式交付前须补）+ `gate.pass`（质量门通过的**信息性** WARN，非问题）。⚠️ 首跑曾另报 1 个 BLOCK（U04 小样本占比离散化）——经裁定为**门禁脚本自身缺陷**并已修正，见 §5 陷阱位 12 与评估第 26 项 |
| 5 | 本用例作为「**模型实测**证据」 | ❌ **不成立** | 本节输出为**人工构造的结构基线**，非模型产物。**不得**把「结构看起来对」或「脚本全绿」当成「模型已能生成」——§3 的 14 镜 JSON 是**目标形态**，不是 Qwen2.5-7B-Instruct 的真实输出 |
| 6 | 模型实测（Qwen2.5-7B-Instruct） | ⏳ **待做** | 需 GPU 环境（T-012 已解锁）；实测后须替换 §3 为本模型的**真实输出**并保留原始采样日志 |
| 7 | 与上游零偏差 | ✅ 结构层面成立（**v2.0 起不再需要「扣除契约外字段」的例外**） | 镜数 / 镜序 / 时长 / 角色引用 / **道具引用**与 `CASE-STB-001` 逐项一致（评估第 2~4、20 项）；R31 已脚本化镜数／镜序／时长三条不变量，R35 脚本化 `prop_refs` 的「齐备 + 命中」。⚠️ **v1.1 说明（已作废）**：当时上游 `shots[].prop_refs` 与**顶层** `forbidden_items` 均**不属于**「应与上游一致」的范围（交付契约无对应容器）——**v2.0 契约补齐后两者均已进承继列**（`ISSUE-011`／`ISSUE-012` 闭环），故本项**回归朴素口径：上游有的锚与禁忌容器，本层逐项一致** |

**闭环条件**：① 模型就绪后由 `shot_prompt_v1`（**v2.0.0**）产出真实包；② 真实包过 `validate_output.py`（交付包形态 **R26~R36** 全通过）**且** `validate_pack.py` **0 BLOCK**；③ 对 H3 适配投喂文本跑 `audit_shots.py --gate`。**三项齐备后方可从「未验证」改为「已验证」。** 当前状态：**② 两半均已成立**（53/0/0 且门禁 0 BLOCK，基于本人工构造基线）；① ③ 均未做。故整体仍标 **未验证**——② 成立只说明**结构与规则自洽**，不构成「模型能生成」的证据。

⚠️ **本用例已知残留（v1.1 起登记；v2.0 复核订正）**：① `S02-SH003` 的 `shot_language.composition` 属**条件改写**（投影规则④派生），其与上游的一致性需在**上游补值后**回归复核——**仍待**。② 原文「`S03-SH003` 的稳定指称缺失、`CHR-01` 中英指称并存两套词组（评估第 9／10 项）**尚未逐镜整改**」**与实测不符**（**v2.0 自查订正**）：脚本复核 14 镜正文，`the rider` 残留 **0 处**，`S03-SH002`／`S03-SH003` 起句均已含 `the delivery rider`／「外卖员」——**PR-05 的整改已完成**，原句系整改前的遗留描述（该矛盾正是「**结论表与检查表须分开维护**」的风险点）。**仍未落地的只有「指称一致性脚本判据」本身**（多角色镜口径亦未按单人镜强制，见评估第 10 项），已登记为后续项。
