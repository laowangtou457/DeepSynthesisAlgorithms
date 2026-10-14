# revise-case01 · 提示词解析重构（客户自带素材入口）

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-REV-001` |
| 对应需求 | **SW-008 提示词解析重构**（重构入口层／链路的第二个起点） |
| 模板 | `revise_v1` **v1.0.0**（业务链路第 5 段，**并行入口**：客户自带素材时不跑前四段） |
| 上游用例 | **无**（本层是全链路唯一**没有模板上游**的一段；输入＝客户素材 + 服务层注入的 `pack_meta`，输出＝交付包 + **独立缺口台账**） |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.6 / top_p 0.9 / max_tokens 8192（**受约束解码**，FSM = `delivery/schemas/CFG-006_shot_prompt_pack.v1.schema.json`。⚠️ 本层温度低于 SW-007 的 0.7——要**忠实于客户素材**，风险不是句式呆滞而是把客户写的东西改掉） |
| 记录日期 | 2026-10-14 |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `source_material` | 客户提供的**逐镜提示词清单**（自由文本，含平台方言与制作备注），全文见下 |
| `source_kind` | **`prompt_list`** —— 素材**已切镜**（客户自己给了「镜头一…镜头六」），故本层**不得改变镜头数量与时序**（粒度守恒） |
| `pack_meta` | **服务层注入**（非模型生成）——`pack_id = FR-PK-20261014-CASE0005`、`created_at = 2026-10-14T15:00:00+08:00`、`task_type = text_to_video`、`stage_chain = ["revise"]`、`templates = [revise_v1 v1.0.0]`；`session_id`／`task_id`／`statement_id`／`generator`／`compliance` 见输出 |
| `client_visual_input` | **已提供**（客户给的参考图描述，用于②锚定步）：「主角参考图：短发女性，黑发及耳，右侧发梢别一枚银色小发夹；米白色针织开衫，深灰高领内搭；斜挎一只旧深棕帆布包。」→ 其来源标 **`客户提供`**，与「系统提议待确认」区分 |
| `segment` | `all` —— ⚠️ **本用例取 `all` 仅为「演练与校验」**：只有拿到一份完整包才能跑 `validate_pack.py` 门禁。生产环境 6 镜按 `auto` 走 `package_head` + 逐单元（共 3 次调用）＋ `gap_ledger`（1 次） |
| `gap_answers` | 无（首轮，客户尚未答复任何缺口） |

### 2.1 客户素材原文（`source_material`）

```text
【夜班便利 第3集｜阿岚线】--ar 16:9 --style raw --v 6
整体风格：写实日剧质感，冷调低饱和，雨夜低照度，胶片颗粒轻
禁止出现：真实品牌 logo、血腥画面

第1场 便利店门口，深夜，雨刚停。
镜头一：全景；镜头从阿岚背后慢慢推上去，停在她后颈。（备注：这场交给美术，灯先不急定）
镜头二：中景；阿岚蹲下去，把便利袋放在长椅上，系鞋带。镜头不动。
镜头三：特写；她手边那袋关东煮，热气在冷空气里往上飘。镜头往上抬一点。

第2场 便利店内，接第1场，仍是她一个人。
镜头四：中景；她口袋里的手机亮起来，她低头看。镜头跟着她往前带半步。
镜头五：近景；她抬眼看向货架尽头，眼神停住。她低声说「你还没走啊」。镜头轻微晃一下。
镜头六：空镜；货架尽头那盏灯闪了两下。镜头往后拉出去，收在整排货架。

（注：片尾字幕后面再补，本集先出画面。）
```

### 2.2 动笔前必须产出的三件事（模板 `system` 硬性约束 2）

**① `source_kind` 判定 = `prompt_list`。** 素材自带「镜头一…镜头六」的划分 → **粒度守恒生效**：本层**不得**改镜头数量与时序，**不得**补切镜。

**② 叙事骨架（解析结果）**

| 项 | 解析结果 |
| --- | --- |
| 场次 | 2 场（第 1 场：便利店门口／深夜／雨刚停；第 2 场：便利店内／接第 1 场） |
| 镜头 | 6 镜（3 + 3），客户已给景别 4 处、运镜 4 处、时长 0 处 |
| 台词 | **1 处**，原文＝「你还没走啊」（**事实类，一字不改**） |
| 动作 | 放袋、蹲下、系鞋带；看手机；抬眼、视线停住；灯闪 |
| 风格 | 素材已给（「写实日剧质感，冷调低饱和，雨夜低照度，胶片颗粒轻」）→ **原样承继**为 `style_anchors` |
| 禁忌 | 素材已给（真实品牌 logo、血腥画面）→ **原样承继**为 `forbidden_items` |

**③ 缺口清单（逐条落台账，见 §3 第 2 个 JSON 块）**

| # | 缺口 | 类别 | 本层处置 |
| --- | --- | --- | --- |
| 1 | 「阿岚」是全名还是昵称 | **事实类** | 原样照录称呼 + 登记台账（不得自拟全名） |
| 2 | 便利袋的外观 | **设计类** | 由本层**提议候选**（`系统提议待确认`）+ 登记台账 |
| 3 | 关东煮杯的外观 | **设计类** | 同上 |
| 4 | 「眼神停住」的视线对象 | **事实类歧义** | 不得自拟 + 登记台账 |
| 5 | 台词「你还没走啊」的说话对象 | **事实类歧义** | **原样照录**不改写 + 登记台账 |

> **上游状态**：本层**无模板上游**（这是它与其他四段最根本的差别）；`source_material` 为**人工构造**的客户素材，未经真实客户交付。故「素材真实性」与 `CASE-001`~`CASE-004` 同一性质，不构成真实素材证据。

## 3 输出

> **状态：待回填。** 本节为目标输出样例（人工构造），用于固化字段结构与写法基线；**尚未经 Qwen2.5-7B-Instruct 实测**。实测后须替换为模型真实输出并保留原始采样日志。
>
> **本层产出两个独立产物**：① 交付包（第 1 个 JSON 块，可投喂 `validate_pack.py` 门禁）；② **缺口台账**（第 2 个 JSON 块，**独立落盘为 `<pack_id>.unspecified.json`，不在交付包内**）。交付包**没有** `unspecified` 段——规范 §3.1 顶层八段中无此段，塞进去会被判据 `R36` 与 schema 的 `additionalProperties: false` 拒收。

### 3.1 交付包（`shot_prompt_pack`，2 单元 / 6 镜 / 32000ms）

```json
{
  "schema_version": "2.0.0",
  "meta": {
    "pack_id": "FR-PK-20261014-CASE0005",
    "title": "夜班便利 · 第3集（客户自带素材重构）",
    "created_at": "2026-10-14T15:00:00+08:00",
    "task_type": "text_to_video",
    "unsupported_task_types": [
      "keyframe_completion：需 Ref2VA 六段式骨架与 350-500 词 detailed_description，本期不作适配",
      "reference_generation：需 Ref2VA 全参考模式与素材上限体系，本期不作适配",
      "video_editing：同上",
      "video_continuation：同上",
      "audio_reuse：同上",
      "audio_reference：同上"
    ],
    "generator": {
      "system": "AI 漫剧剧本与分镜提示词生成系统",
      "version": "0.1.0",
      "provider": "{{PROVIDER_NAME}}",
      "provider_code": "{{PROVIDER_CODE}}"
    },
    "generation_trace": {
      "session_id": "SESS-CASE-0005",
      "task_id": "TASK-CASE-0005",
      "stage_chain": ["revise"],
      "templates": [
        { "id": "revise_v1", "version": "1.0.0" }
      ],
      "model": { "name": "Qwen2.5-7B-Instruct", "backend": "vllm", "revision": "main" }
    },
    "compliance": {
      "safety_check": { "input": "passed", "output": "passed", "checked_at": "2026-10-14T14:59:40+08:00" },
      "copyright_check": { "status": "passed", "note": "素材由客户提供并声明为原创；本包未使用第三方素材" },
      "marking_check": { "explicit": "present", "implicit": "present" },
      "statement_id": "FR-ST-20261014-0005"
    },
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 32000,
    "notes": "【source_kind】prompt_list——客户提供逐镜提示词清单（含平台方言与制作备注）；素材已切镜，故按粒度守恒**未改变镜头数量与时序**（2 场 6 镜原样保留），本层**未补切镜**。【解析要点】① 场次 2；② 素材「空镜」不是景别值，按语义映射为 shot_size=full 并在正文写明「画面内无人物」，此行即映射留痕；③ 「镜头不动」「镜头轻微晃一下」「跟着她往前带半步」等口语运镜已规范化；④ 素材首行的 --ar／--style／--v 与两处制作备注属**平台参数与冗余指令**，进结构化字段或整体丢弃、**不进正文**。【词表映射依据】「慢慢推上去」→push_in+speed=slow；「往上抬一点」→tilt_up；「往前带半步」→tracking；「轻微晃一下」→shake_slight+amplitude=small；「往后拉出去」→pull_out；「胶片颗粒轻」→film_grain=light；光位由本层按场景选定（第 1 场店面招牌与玻璃门灯管→practical_light；第 2 场店内顶灯→top_light）。【design_source 二分的登记位置】交付包**无** design_source 字段（契约外键会被 R36 拒收），故「客户提供／系统提议待确认」的区分登记在缺口台账与本节——CHR-01 外观来自 client_visual_input（客户提供），PRP-01／PRP-02 外观由本层提议（系统提议待确认）。【指称映射】CHR-01 → 中文「阿岚」／英文 Alan，全片一致。【未纳入项】素材结尾提及的「片尾字幕」不属交付包字段集，未纳入本轮产出。【台账】[LEDGER] FR-PK-20261014-CASE0005.unspecified.json | 条目数=5 | blocking=0"
  },
  "style_bible": {
    "style_id": "STYLE-01",
    "style_prompt_zh": "写实日剧质感，冷调低饱和，雨夜低照度，胶片颗粒轻",
    "style_prompt_en": "realistic Japanese TV-drama look, cool low-saturation palette, low-key rainy-night lighting, light film grain",
    "style_anchors": ["写实日剧质感", "冷调低饱和", "雨夜低照度", "胶片颗粒轻"],
    "color_palette": ["#15202B", "#2F3E4A", "#7C8B96"],
    "lighting_default": "practical_light",
    "film_grain": "light",
    "negative_global": [
      "lowres", "blurry", "watermark", "text overlay", "extra fingers", "deformed", "extra limbs",
      "flicker", "temporal jitter", "frame inconsistency",
      "clipping", "morphing", "limb popping"
    ]
  },
  "characters": [
    {
      "character_id": "CHR-01",
      "name": "阿岚",
      "appearance_lock_zh": "女性，黑发及耳，右侧发梢别一枚银色小发夹，米白色针织开衫、深灰高领内搭，斜挎一只旧深棕帆布包",
      "appearance_lock_en": "woman with ear-length black hair, a small silver hairclip on the right, off-white knit cardigan over a dark grey turtleneck, worn dark-brown canvas crossbody bag",
      "forbidden": ["发型长度变化", "发夹位置变化", "开衫颜色变化"]
    }
  ],
  "props": [
    {
      "prop_id": "PRP-01",
      "name": "便利袋",
      "role": "角色随身物",
      "appearance_lock_zh": "半透明塑料提袋，袋口拧成一束，侧面印着褪色的蓝色店招字样",
      "appearance_lock_en": "translucent plastic carrier bag, mouth twisted into a knot, a faded blue shopfront wordmark printed on the side"
    },
    {
      "prop_id": "PRP-02",
      "name": "关东煮纸杯",
      "role": "场景道具",
      "appearance_lock_zh": "带盖的白色纸杯，杯壁挂着细密水汽，杯沿插着一支竹签",
      "appearance_lock_en": "lidded white paper cup, fine condensation beading on its wall, a bamboo skewer angled through the lid"
    }
  ],
  "units": [
    {
      "unit_id": "U01",
      "scene_no": 1,
      "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"],
      "soundscape": "雨停后的滴水声，便利店门内传出的冰柜低鸣，远处偶有车辆驶过积水",
      "music": "N/A",
      "notes": "单人戏，按单人替身法则处理：每镜点名一个光源并写出它在这一镜做了什么；静止镜内有在动的动作（放袋、系鞋带）且已写出"
    },
    {
      "unit_id": "U02",
      "scene_no": 2,
      "shot_ids": ["S02-SH001", "S02-SH002", "S02-SH003"],
      "soundscape": "冰柜低鸣持续，脚步落在瓷砖上的回声，货架灯管细微的电流声",
      "music": "N/A",
      "notes": "单人戏；末镜为素材所称的「空镜」，画面内无人物，故该镜 character_refs 为空数组（语义映射见 meta.notes）"
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
        "speed": "slow",
        "height": "high",
        "roll": "level",
        "optics": "long_lens_compression",
        "from": "阿岚背后约两米、略高于头顶的机位，画面带进整片湿街与卷帘门",
        "to": "沿她的背影向前推送，收在她后颈与招牌光晕之间"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "远景：深夜的便利店门口，雨刚停，路面低洼里积着一摊水，映着招牌的黄绿光斑。阿岚背对镜头站在门外的长椅旁，人在画面右侧只占很小一块，左侧留出大片湿漉漉的街面和一扇卷帘门。机位落在她身后约两米、略高于头顶，画面由整片湿街与她的背影一同向前推近。玻璃门内侧的白灯管把她的肩线勾出一道冷边，门外没有第二个人。一缕白气从她耳侧升起，随着镜头推进被画面边缘裁去，最后收在她后颈与招牌光晕之间。整体为写实日剧质感、冷调低饱和的雨夜低照度影调，带轻微胶片颗粒。",
      "prompt_en": "Wide shot of a convenience-store entrance late at night, the rain just stopped, puddles on the pavement holding smears of the shop sign's yellow-green light. Alan stands with her back to the lens beside the bench outside, small in the right third of the frame, with a broad stretch of wet street and a shuttered roll-up door filling the left. The camera pushes in slowly from a position behind her at a height a little above her head, long-lens compression flattening the street into shallow layers. White tubes behind the glass door trace a cool edge along her shoulder line, and nobody else is outside. A thread of breath rises past her ear and is cropped away by the frame edge as the move settles on the nape of her neck and the glow of the sign. Realistic Japanese TV-drama look, cool low-saturation rainy-night low key, light film grain.",
      "action": {
        "start": "背对镜头静立在长椅旁，双手垂在身侧",
        "change": "肩线微微一沉，一缕白气从耳侧升起",
        "end": "保持静立，白气被画面边缘裁去"
      },
      "shot_language": {
        "composition": "人物落在画面右三分之一并只占很小一块，左侧留出大片湿街作负空间，卷帘门与玻璃门在背景构成一道横向分割",
        "axis": "空间轴自店门（右）向街道深处（左）延伸，本镜确立轴线；后两镜沿用不自越",
        "result": "积水被滴水打出同心涟漪、招牌光斑在水面上轻轻晃动"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "sfx": "雨停后的滴水声、远处车辆驶过积水",
      "transition_in": "cut"
    },
    {
      "shot_id": "S01-SH002",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 2,
      "shot_size": "medium",
      "camera": {
        "move": "static",
        "height": "low",
        "roll": "level",
        "optics": "deep_focus",
        "from": "固定机位，与蹲姿时的视线齐平，落在长椅与店门的交界",
        "to": "全镜不动，动感全部由画面内的动作提供"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：阿岚在便利店门外的长椅前蹲下，先把便利袋搁在椅面上，再低头去系鞋带；她落在画面偏左，右后方是亮着的店面玻璃，纵深处能看清整条街的招牌层次。机位固定在与她蹲姿视线齐平的高度，全镜不动，动感全部由画面内的动作提供。招牌的黄绿光从上方压下来，在她手背和袋口上留出清楚的明暗分界。提手在她松手时弹了一下，又垂下去贴住椅面。冷调低饱和的雨夜低照度影调，写实日剧质感。",
      "prompt_en": "Medium shot outside the store, where Alan crouches in front of the bench, sets a carrier bag down on the seat and bends to tie a lace, sitting in the left half of the frame with the lit shop glass behind her right shoulder and the street's stacked signs still readable deep in the background. The camera holds a static position at the low height of her crouch, so the only movement comes from what happens inside the frame. The sign's yellow-green light presses down from above and draws a clean edge between the lit backs of her hands and the shadow under the bag. The handle flicks up as she lets go, then settles flat against the seat. Realistic Japanese TV-drama look, cool low-saturation rainy-night low key.",
      "action": {
        "start": "站着，双手提着便利袋",
        "change": "蹲下并把便利袋搁到椅面，随后低头去系鞋带",
        "end": "鞋带系好，双手仍停在鞋面上"
      },
      "shot_language": {
        "composition": "人物占画面偏左，右侧留出亮着的店面玻璃作亮块，纵深中招牌层次形成三级景深",
        "axis": "沿用 U01 空间轴，人物仍朝画面右侧的店门，不自越",
        "result": "便利袋提手弹起又落下贴住椅面、湿街面上滴水仍在落"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "sfx": "塑料袋摩擦声、鞋带收紧的声音",
      "transition_in": "cut"
    },
    {
      "shot_id": "S01-SH003",
      "unit_id": "U01",
      "scene_no": 1,
      "shot_no": 3,
      "shot_size": "close_up",
      "camera": {
        "move": "tilt_up",
        "speed": "slow",
        "height": "low",
        "roll": "level",
        "optics": "shallow_focus",
        "from": "贴近椅面上的纸杯，略低于杯口",
        "to": "沿杯身向上摇，落在阿岚的下颌与扑面而来的白气上"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "特写：长椅面上的关东煮纸杯，杯壁挂着水汽，几缕白气在冷空气里笔直往上飘，杯里的汤汁轻轻晃、映着招牌的黄绿。阿岚的下颌与半张侧脸从画面上缘进入，呼出的白气与杯口的热气混在一起。机位贴近椅面、略低于杯口，浅景深让身后整条湿街化成一团柔和的散景光斑；画面沿杯身向上摇，最后停在她的下颌与扑面而来的白气上。冷调低饱和的雨夜低照度影调，写实日剧质感，轻微胶片颗粒。",
      "prompt_en": "Close-up of a paper cup of oden on the bench, condensation beading on its wall and steam rising in straight threads through the cold air, the broth inside rocking gently and catching the sign's yellow-green glow. Alan's jaw and half of her cheek enter from the top edge of the frame, her breath folding into the steam off the cup. The camera tilts up slowly from a position level with the seat and a touch below the rim, with a shallow depth of field so the wet street behind melts into soft bokeh, finishing on her jaw and the breath rolling forward. Realistic Japanese TV-drama look, cool low-saturation rainy-night low key, light film grain.",
      "action": {
        "start": "纸杯静置在椅面上，白气直线上升",
        "change": "画面沿杯身上摇，她的下颌与侧脸进入画面上缘",
        "end": "停在下颌与白气，热气继续上飘"
      },
      "shot_language": {
        "composition": "纸杯占画面下半并居中偏右，画面上缘让出人物下颌的进入空间，浅景深把背景压成一片柔和光斑",
        "axis": "沿用 U01 空间轴，人物仍位于店门一侧，不自越",
        "result": "白气持续上升并被冷空气拉直、汤汁晃动在杯壁上留下移动的水光"
      },
      "lighting": "practical_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-02"],
      "sfx": "纸杯里汤水轻晃、夜里的虫鸣",
      "transition_in": "cut",
      "transition_out": "fade_out"
    },
    {
      "shot_id": "S02-SH001",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 1,
      "shot_size": "medium",
      "camera": {
        "move": "tracking",
        "speed": "slow",
        "height": "eye_level",
        "roll": "level",
        "optics": "deep_focus",
        "from": "阿岚右后方半步，随她一同前移",
        "to": "与她并肩，收在手机屏幕那一点光上"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "中景：便利店内，冷白的顶灯沿货架排成一列，阿岚侧身自画面左侧往纵深处走，右手里攥着的手机忽然亮起，把她的手指和半张脸映成一块偏冷的亮面；她停在两排货架之间，低下头去看。机位从她右后方半步起幅，与她同步前移，稳稳跟到与她并肩的位置，最后停在手机屏幕那一点光上。货架上的价签与整排商品在深景深里保持清楚，顶灯的白光在她头顶压出一层平直的光。冷调低饱和影调，写实日剧质感。",
      "prompt_en": "Medium shot inside the store, where rows of cold white ceiling tubes run the length of the shelves. Alan crosses from frame left and walks deeper along the aisle, the phone in her right hand flaring to life and turning her fingers and part of her cheek into a cool bright plane; she stops between two shelf runs and looks down at it. The camera tracks slowly from half a step behind her right shoulder, moving with her and settling alongside her, ending on that single point of light on the screen. Price cards and the whole shelf face stay readable in deep focus, and the ceiling light lays a flat bright film across the top of her head. Cool low-saturation palette, realistic Japanese TV-drama look.",
      "action": {
        "start": "侧身站在货架通道口，右手攥着手机",
        "change": "迈步向纵深走两步，手机在手里亮起，她低下头",
        "end": "停在两排货架之间，视线落在屏幕上"
      },
      "shot_language": {
        "composition": "人物自画面左侧向纵深移动，两排货架形成平直的透视收束线，屏幕的亮点成为画面中最亮的落点",
        "axis": "本单元新场，空间轴沿货架通道自画面前方向纵深，机位随人物不越轴",
        "result": "屏幕光在她手指上移动、货架灯管在画面顶端持续亮着"
      },
      "lighting": "top_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "sfx": "冰柜低鸣、脚步落在瓷砖上的回声",
      "transition_in": "fade_in"
    },
    {
      "shot_id": "S02-SH002",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 2,
      "shot_size": "close_up",
      "camera": {
        "move": "shake_slight",
        "amplitude": "small",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus",
        "from": "与她视线齐平、略偏她右侧的机位",
        "to": "极轻微地晃了一下，随即回到原位"
      },
      "duration_ms": 5000,
      "aspect_ratio": "16:9",
      "prompt_zh": "近景：阿岚抬起眼，视线越过眼前的货架，落在通道尽头，眼神停住；顶灯的白光从上方直落，在她眼下一道很浅的影。机位与她的视线齐平、略偏她右侧，机身极轻微地晃了一下又回到原位，浅景深把最近一排商品的边缘化成一条柔边。她嘴唇轻动，低声说了一句话。冷调低饱和影调，写实日剧质感，轻微胶片颗粒。",
      "prompt_en": "Close-up of Alan lifting her eyes, her gaze travelling past the shelf in front of her and stopping somewhere down the aisle. The camera shakes very slightly from a position level with her eyeline and a little to her right, then returns to where it started, with a shallow depth of field softening the nearest row of goods into a single edge. Ceiling light falls straight down from above and leaves a very shallow shadow under her eyes. Her lips move once as she says something quietly. Realistic Japanese TV-drama look, cool low-saturation rainy-night low key, light film grain.",
      "action": {
        "start": "低头看着屏幕，睫毛压下去",
        "change": "抬起眼，视线越过货架停在通道尽头",
        "end": "眼神停住，嘴唇轻动后收住"
      },
      "shot_language": {
        "composition": "面部占据画面中心偏左，右侧留出货架通道的纵深，最近一排商品的柔边压在画面下缘",
        "axis": "沿用 U02 的货架通道轴，视线越过货架但仍朝纵深方向，不自越",
        "result": "货架灯管在浅景深里化成一片柔光、她呼出的白气在画面下缘轻轻散开"
      },
      "lighting": "top_light",
      "style_ref": "STYLE-01",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "dialogue": "你还没走啊",
      "sfx": "她自己的呼吸、冰柜的低鸣",
      "transition_in": "cut"
    },
    {
      "shot_id": "S02-SH003",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 3,
      "shot_size": "full",
      "camera": {
        "move": "pull_out",
        "speed": "slow",
        "height": "high",
        "roll": "level",
        "optics": "wide_angle_distortion",
        "from": "贴近货架尽头那根灯管的高机位",
        "to": "缓缓后退拉出，收在整排货架的纵深上"
      },
      "duration_ms": 6000,
      "aspect_ratio": "16:9",
      "prompt_zh": "全景：便利店内没有人物入画，货架通道一直伸到画面深处，冷白顶灯把每一排商品的顶面都照出一条亮线；尽头那根灯管闪了两下，明暗在整条通道上连着跳了两回。机位贴近尽头灯管、位置偏高，画面缓缓后退拉出，广角把两侧货架向外推、通道随之变宽变深，最后收在整排货架排成的纵深处。地面瓷砖映着一层薄薄的反光。冷调低饱和影调，写实日剧质感，轻微胶片颗粒。",
      "prompt_en": "Full shot inside the store with nobody in frame, the aisle running deep toward the back wall, cold ceiling tubes laying a bright line along the top of every shelf run. The tube at the far end flickers twice, and the whole aisle brightens and dips with it. The camera pulls out slowly from a high position close to that end tube, a wide angle pushing the shelves apart so the aisle widens and deepens, finally settling on the receding rows. A thin sheen sits on the floor tiles. Realistic Japanese TV-drama look, cool low-saturation rainy-night low key, light film grain.",
      "action": {
        "start": "货架通道空着，灯管稳定亮着",
        "change": "尽头灯管闪了两下，明暗沿通道跳了两回",
        "end": "灯管恢复常亮，画面停在整排货架的纵深上"
      },
      "shot_language": {
        "composition": "通道以对称透视收束在画面中心深处，两侧货架构成向外的斜线，无人物占位",
        "axis": "沿用 U02 的货架通道轴，镜头沿轴后退，方向不变",
        "result": "灯管闪烁时整条通道的明暗连着变化两次、地面反光随之明灭"
      },
      "lighting": "top_light",
      "style_ref": "STYLE-01",
      "character_refs": [],
      "prop_refs": [],
      "sfx": "灯管电流的滋滋声、冰柜低鸣",
      "transition_in": "cut",
      "transition_out": "fade_out"
    }
  ],
  "forbidden_items": ["真实品牌 logo", "血腥画面"],
  "aigc_meta": {
    "AIGC": {
      "Label": "1",
      "ContentProducer": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "ProduceID": "FR-PK-20261014-CASE0005",
      "ReservedCode1": "",
      "ContentPropagator": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "PropagateID": "FR-PK-20261014-CASE0005",
      "ReservedCode2": ""
    }
  }
}
```

### 3.2 缺口台账（**独立产物**：`FR-PK-20261014-CASE0005.unspecified.json`）

> ⚠️ **本块不是交付包的一部分**。链路前段的台账「留在上游产物自身、随交付包一并交付」；**本层没有上游**，故台账必须**另行产出**、与交付包同批落盘。`meta.notes` 中以 `[LEDGER] …` 行给出文件名与条目数指引（可机器读）。

```json
{
  "unspecified": [
    {
      "field": "characters[0].name",
      "upstream_field": "",
      "reason": "素材给出称呼「阿岚」，但未说明是全名还是昵称；事实类信息不得编造，故原样照录称呼并登记待确认",
      "owner": "客户",
      "fill_stage": "revise",
      "fill_fallback": "以素材称呼先行拍摄；客户确认全名后如需变更，须重出受影响的镜（6 镜全部含该指称）",
      "blocking": false
    },
    {
      "field": "props[0].appearance_lock_zh",
      "upstream_field": "",
      "reason": "素材未描述便利袋外观；本层按场景提议候选（design_source=系统提议待确认），须客户确认",
      "owner": "客户",
      "fill_stage": "revise",
      "fill_fallback": "以本层提议的候选先行拍摄；若客户给出实物图，须重出 S01-SH002（唯一入画镜）",
      "blocking": false
    },
    {
      "field": "props[1].appearance_lock_zh",
      "upstream_field": "",
      "reason": "素材未描述关东煮纸杯外观；本层按场景提议候选（design_source=系统提议待确认），须客户确认",
      "owner": "客户",
      "fill_stage": "revise",
      "fill_fallback": "以本层提议的候选先行拍摄；若客户给出实物图，须重出 S01-SH003（唯一入画镜）",
      "blocking": false
    },
    {
      "field": "shots[4].action.change",
      "upstream_field": "",
      "reason": "素材只写「看向货架尽头，眼神停住」，未说明视线落在什么上（人在镜头六才出现，是灯还是别的东西未定）；事实类歧义不得自拟",
      "owner": "客户",
      "fill_stage": "revise",
      "fill_fallback": "按「看到货架尽头那盏灯闪」处理（依据素材镜头六的空镜作连续性推断），不闭合亦可交付",
      "blocking": false
    },
    {
      "field": "shots[4].dialogue",
      "upstream_field": "",
      "reason": "台词原文为素材所给（「你还没走啊」），本层原样照录、未作任何润色；素材未给标点与说话对象，而语义上指向对话方、素材又称本场「仍是她一个人」（事实类歧义）",
      "owner": "客户",
      "fill_stage": "revise",
      "fill_fallback": "按自语处理：画外不出现第二人、不加对上反打镜（与素材「仍是她一个人」一致），不闭合亦可交付",
      "blocking": false
    }
  ]
}
```

## 4 评测结论

对照 SW-008 的验收标准：**「客户自带素材（剧本／提示词清单／旧交付包／混合）经一次调用即可重构为本系统标准交付包；素材中已明确的事实类信息与镜头意图一字不改；缺口全部可追溯并单独产出」**；并叠加规范 §3 字段契约、§4.1 八维双条件、§3.4 外观只定义一次、§5 AIGC 元数据。

| # | 评测项 | 手段 | 结论 |
| --- | --- | --- | --- |
| 1 | 交付包结构完整 | 顶层**八段／9 键**逐段核对；每镜 **14** 个必备字段核对 | ✅ 9 个顶层键齐备（必备 6 段 + 可选段 `characters`／`props`／`forbidden_items`）；6 镜的 14 个必备字段齐备 |
| 2 | **素材守恒（第一条纪律）** | 把 `source_material` 的事实类字符串与台词原文逐条在交付包里找回去 | ✅ **台词原文 1 处逐字相同**（`dialogue = "你还没走啊"`，**未加标点、未改语气**）；素材未给的人名／地名一处未编造；**唯一未逐字保留的素材字符串是「空镜」（非事实类，属词表外方言，已映射并留痕）** |
| 3 | **粒度守恒（第二条纪律）** | 核对镜头数量与时序与素材一致；核查有无补切镜 | ✅ 素材 6 镜 → 交付包 6 镜（S01-SH001~003 / S02-SH001~003），**镜数、镜序、场次归属全部一致**；`meta.notes` 明写「本层未补切镜」 |
| 4 | **五类必改白名单** | 交付包与素材做差异清单，逐条标注属五类中的哪一类 | ✅ 全部差异可归入五类：① 形态改写（自由文本→字段，6 镜全部）；② 规范化（8 处，见 `meta.notes` 映射依据）；③ 拆分（「镜头从背后慢慢推上去」→字段取码+说明入正文）；④ 删冗余（`--ar 16:9`／`--style raw`／`--v 6`／2 处制作备注）；⑤ 补缺口（时长 6 处、`soundscape`／`music` 2 处、道具外观 2 处）。**标不出类别的差异 0 处** |
| 5 | **锚的二分** | 逐个设计类字段问「这个值素材里有吗」 | ✅ `CHR-01.appearance_lock_*` 来自 `client_visual_input`（**客户提供**）；`PRP-01`／`PRP-02` 的外观由本层提议（**系统提议待确认**，台账有对应条目）。⚠️ 该区分**不落在交付包字段上**——契约无 `design_source` 键（写入即被 R36 拒收），故落 **台账 + `meta.notes`**（见 §5 陷阱位 4） |
| 6 | **台账独立产出** | 交付包内是否出现 `unspecified`；台账是否为独立产物 | ✅ 交付包**无** `unspecified`（规范 §3.1 顶层八段）；台账为**独立 JSON 产物**，5 条，七项字段齐备；`meta.notes` 含可机器读的 `[LEDGER] … 条目数=5 \| blocking=0` |
| 7 | 缺口可追溯 | 台账条目 ↔ 交付包字段路径 | ✅ 5 条全部指向包内真实字段路径（`characters[0].name`／`props[0].appearance_lock_zh`／`props[1].appearance_lock_zh`／`shots[4].action.change`／`shots[4].dialogue`） |
| 8 | **八维双落地** | 6 镜 × 8 维 = 48 格，逐格在正文中找出对应句 | ✅ 48 格全部有字段承载且能定位到正文句（角度／光学两维 100% 覆盖，见 §5 陷阱位 6） |
| 9 | 外观只定义一次 | 把 `appearance_lock_zh`／`_en` 的特征词在 6 镜正文中扫描 | ✅ **0 命中**——正文未出现「短发／黑发／及耳／发夹／针织／开衫／高领／帆布／米白／深棕」等特征词；人物一律以稳定指称「阿岚」／`Alan` 出现 |
| 10 | **单人替身法则与指称一致性** | 逐镜判定主体数；核查单角色镜指称；把「`character_id` ↔ 指称词组」映射写进 `meta.notes` | ✅ 5 个单角色镜（S01-SH001~003、S02-SH001~002）中英双侧均用具名指称「阿岚」／`Alan`，**无「他／她」单用**；S02-SH003 为无人物空镜（`character_refs = []`），不适用；`meta.notes` 已写映射声明 |
| 11 | 风格承继与锚点封闭 | `style_anchors` 与素材风格句比对；正文扫描 `style_anchors` 之外的风格词 | ✅ 素材 4 个风格短语**原样承继**为 4 条锚（未增未减）；正文风格句只用这 4 条的中英对应；**未出现**「日式动画」「赛璐璐」「厚涂」「水彩」等清单外风格词 |
| 12 | 负向词不进正文 | 扫描「（负向：…）」「Negative prompt:」类残留 | ✅ 0 命中；`negative_global` 按三类组织（通用图像项／视频时域项／形变延续项），未写进 `prompt_*` |
| 13 | 正文不含模型参数指令 | 扫描 `--ar`／`--v`／`--style` 等 | ✅ 0 命中；素材首行的三个平台参数只驱动 `aspect_ratio` 字段与 `film_grain`，**未进正文** |
| 14 | 幅度／速度省略规则 | `amplitude`／`speed` 取值集合 | ✅ 只出现 `small`／`slow`／`fast`-级的值（本包 `speed=slow`×4、`amplitude=small`×1）；其余**省略该键**；**无 `medium`／`normal`、无空串** |
| 15 | static／pov 不带幅度速度 | S01-SH002 | ✅ 该镜**省略** `amplitude`／`speed` 两个键 |
| 16 | 转场单侧表达与单元边界 | 单元内非末镜的 `transition_out` | ✅ 单元内非末镜**省略 `transition_out` 键**；`fade_out` 只出现在两个单元末镜；单元边界＝U01 末镜 `transition_out=fade_out` ＋ U02 首镜 `transition_in=fade_in`（**两个半段**，非「两头都写」） |
| 17 | `lighting` 为纯词表值 | 6 镜 `lighting` + `style_bible.lighting_default` | ✅ 全部为词表 code（`practical_light`×3／`top_light`×3／默认 `practical_light`）；素材**未给光位**，由本层按场景选定并在 `meta.notes` 写明依据；**未自造 code** |
| 18 | 引用完整性（§3.8 阻断项） | `style_ref`／`character_refs`／`prop_refs` 命中校验 | ✅ `STYLE-01` 命中；`CHR-01` 命中；`PRP-01`（1 镜）／`PRP-02`（1 镜）命中；S02-SH003 的 `character_refs` 为空数组（空镜），**未写空串** |
| 19 | `units` 约束 | 单元镜数 ∈[2,3]、同场、单元内运镜不重复、`shot_ids` 顺序即镜序 | ✅ 3 + 3；各单元内同场；U01 运镜 push_in／static／tilt_up、U02 tracking／shake_slight／pull_out，**各单元内无重复**；镜序递增 |
| 20 | 时长与自洽 | 逐镜整秒、区间 4–15s、Σ与 `total_duration_ms` | ✅ 6000/5000/5000/5000/5000/6000，均整秒且在区间内；Σ = **32000ms** = `meta.total_duration_ms` |
| 21 | 台词语速 | `dialogue` 字数 ÷ 秒数 ≤ 9 | ✅ 「你还没走啊」5 字 ÷ 5s = **1.0 字/秒** |
| 22 | AIGC 元数据块 | 唯一性、`ProduceID` 与 `pack_id` 同值、字段齐全 | ✅ 仅一份；`ProduceID = PropagateID = meta.pack_id`；`ContentPropagator` 首次写入与 `ContentProducer` 同值；7 字段齐全 |
| 23 | 元数据非编造 | `pack_id`／`created_at`／`session_id`／`task_id`／`statement_id` 回查 `pack_meta` | ✅ 六项均为注入值或占位符（`{{PROVIDER_CODE}}`）；**无自拟值** |
| 24 | `forbidden_items` 承继与三层边界 | 与素材「禁止出现」行比对；扫描是否混入受控词库分类码 | ✅ 原样承继 2 条（真实品牌 logo／血腥画面）；**未混入** `A1-01`~`A1-08` 分类码或受控词条 |
| 25 | **本层规则脚本化** | `validate_output.py` 的交付包形态规则 **R26~R37** 全跑 | ✅ 正向：见 §6 第 2 项 |
| 26 | **与交付门禁脚本结论一致** | 同一份包分别投喂 `prompts/validate_output.py` 与 `delivery/validate_pack.py`，比对结论 | ⚠️→✅ 见 §6 第 4 项：门禁**留 1 条 BLOCK**，且该 BLOCK 是**契约缺陷的可见证据**（`ISSUE-017`），**不是本层实现缺陷**——处置口径同 `ISSUE-015`：**留 BLOCK 可见、改契约而非改产物** |

## 5 陷阱位（本用例专门埋设的失败模式）

| # | 陷阱 | 说明 | 本用例的正确处理 |
| --- | --- | --- | --- |
| 1 | **「顺手润色」客户的台词**（本层最隐蔽的失守） | 素材写「她低声说『你还没走啊』」——没有问号、没有第二个人的回应。模型极易改成「你怎么还没走？」或补一句对方的话 | **原文照录**：`dialogue = "你还没走啊"`，不加标点、不改语序。事实类（含台词原文）**一字不改**。这类改写**读起来更顺、且没有任何字段会因此报错**——`guards` 的「素材守恒扫描」就是为它设的 |
| 2 | **「空镜」不是景别** | 素材写「镜头六：空镜」。「空镜」是行业口语，指**画面内无人物**，不是 `shot_size` 的六个值之一；直接填进 `shot_size` 会被判据否掉 | 按语义**规范化**为 `shot_size = "full"`，并在 `prompt_zh`／`prompt_en` 正文写明「画面内没有人」、`character_refs` 取空数组；**映射依据写进 `meta.notes`**（② 规范化的留痕义务） |
| 3 | **平台参数与制作备注**（④ 删冗余） | 素材首行 `--ar 16:9 --style raw --v 6`；镜一备注「这场交给美术，灯先不急定」；结尾「片尾字幕后面再补」 | `--ar 16:9` → 只驱动 `aspect_ratio` 字段；`--style raw`／`--v 6` **整体丢弃**（不映射、不留痕，属平台方言）；**两处制作备注一个字都不进正文与 `notes`**（内部批注不是给模型看的）；「片尾字幕」不属交付包字段集，在 `meta.notes` 的「未纳入项」如实说明 |
| 4 | **`design_source` 在交付包里**（契约真相：根本没有这个键） | 本层的「锚的二分」与链路前段同口径，但**交付包**的 `characters[]`／`props[]` 是 `additionalProperties: false`、**没有** `design_source` 键——照链路前段的写法往包里塞，会被 `R36` 拒收 | 二分**只落在台账 + `meta.notes`**：`CHR-01` 外观来自 `client_visual_input`（客户提供，**不进台账**）；`PRP-01`／`PRP-02` 由本层提议（系统提议待确认，**进台账**）。⚠️ **这条是本轮自查发现的模板缺陷**：`TPL-014` 的版本说明与示例 2 原写「`design_source = …`」直接落在字段上——**已修正为「登记在台账与 `meta.notes`」**（见 §6 第 5 项） |
| 5 | **台账塞进交付包** | 台账是「缺口清单」，与交付包同批交付，很容易被合并成一个文件 | **必须独立产出**：交付包顶层是**八段／9 键**、无 `unspecified`；台账落 `<pack_id>.unspecified.json`。塞进去会被 `R36`（顶层只允许契约字段集内的键）与 schema 的 `additionalProperties: false` 拒收——**且是两道不同的闸** |
| 6 | **一次性景物被误建成道具锚** | 素材里的长椅、卷帘门、玻璃门、手机、货架都「有外观」 | 道具锚的判据是**「跨镜重复出现且需锁定外观」**：本包只建 2 个（便利袋、关东煮纸杯，各自入画 1 镜且是**动作对象**）；长椅等为一次性布景，只出现在正文里，**不建锚**（建了反而会因「引用它的镜数」与「无外观依据」两头落空） |
| 7 | **「留空」的两种表达：空串 vs 省略键** | 客户素材未给的字段（`transition_out`、`sfx`、`dialogue`、`negative_prompt`）最容易被写成 `""` | 一律**省略该键**：本包 S01-SH001／SH002 与 S02-SH001／SH003 **不出现** `transition_out` 键；S01-SH001~003 与 S02-SH001、SH003 **不出现** `dialogue` 键。JSON Schema 里「键缺失」与「值为空」是两件事——`R33` 兜底 |
| 8 | **`blocking` 全填 false 的惰性** | 台账五条是同一个字段，最省事的写法就是一路 `false` | **逐条问一句「这条不闭合，整包还能不能交付？」**——本期五条均为「可先行拍摄、确认后如需变更须重出受影响的镜」类，故 `blocking` 全为 `false` **是判定的结果、不是默认值**。若有一条属「不闭合则整包不可交付」（如画幅未定、客户素材授权未取得），必须填 `true` 并阻断交付 |
| 9 | **`stage_chain` 填了没跑过的阶段** | 本层「一段抵四段」，最容易顺手填 `["synopsis","script","storyboard","shot_prompt"]`——**那四段模板本层一次都没跑**（`templates` 里只有 `revise_v1`） | **照实填 `["revise"]`**。⚠️ 这会触发 **`ISSUE-017`**：交付 schema 的 `stage_chain.items.enum` 目前只有四值（`synopsis｜script｜storyboard｜shot_prompt`），而其 `description` 与规范正文均写「与 SYS-Q11 确认的 **5 段链路**一致」——**枚举缺 `revise`**。故本包在 `validate_pack.py` 上会留 **1 条 BLOCK**。**该 BLOCK 是契约缺陷的可见证据，不是本层实现缺陷**；处置候选：(a) 规范 + schema 同批补 `revise`（＝规范**次版本**，须新文件）；(b) 维持四值、本层复用 `shot_prompt`（**不推荐，溯源失真**）。**拍板前照实填**——**伪造溯源比报一条 BLOCK 严重得多** |
| 10 | **「镜头轻微晃一下」的幅度落在哪个字段** | 素材用自然语言描述幅度。`amplitude` 的登记口径是「仅在**需要强调**时出现 `small`／`large`」，`medium` 通常省略 | 判为**幅度确有指定**（「轻微」是幅度语义、非泛泛形容）→ `amplitude = "small"`（② 规范化）；而 `speed` 素材未涉及 → **省略该键**。⚠️ 若判为「不强调」则应**两个键都省略**、把「轻微」写进正文——两种处置都合规，但**必须先判定再落笔，不能一半省略一半瞎填** |
| 11 | **单元边界＝两半段，不是「两头都写」** | U01 末镜出 U02 首镜进，容易在 U01 末镜写 `transition_out` 又在 U02 首镜写 `transition_out`，或在**单元内非末镜**写 `transition_out` | U01：SH001／SH002 无 `transition_out`，SH003 有（末镜）；U02：SH001 用 `transition_in=fade_in` 承接入点、SH003 用 `transition_out=fade_out` 表达出点。**同一单元内部**由后一镜的 `transition_in` 单侧承接，**非末镜一律不得填 `transition_out`**（`R18`） |
| 12 | **素材自带的风格词要不要整条进锚** | 素材的风格句是四个短语（「写实日剧质感」「冷调低饱和」「雨夜低照度」「胶片颗粒轻」），而词表的风格标签是**另一套粒度**（如「日式动画电影质感」） | **原样承继、不拆分、不翻译成词表标签**：4 条整条进 `style_anchors`（规范 §3.3「固定 3–5 条」）。⚠️ 关键在**外延**——词表标签里的「写实电影质感」与素材给的「写实日剧质感」**不是一回事**（一个是电影质感、一个是日剧质感），按词表标签去替换会把客户的风格改掉，那属于**禁止的改写**（不在五类之内） |

## 6 验证状态

| # | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 模板 `revise_v1` **v1.0.0** 结构自检 | ✅ 通过 | `validate_templates.py`：YAML 解析、五节齐备、变量引用一致（声明 6 / 引用 6）、必填变量 `source_material`／`source_kind`／`pack_meta`、`stage=revise`。整目录口径：**64 通过 / 8 失败 / 2 警告**（SW-008 前为 57/8/2；+4 为清单恢复可解析、+5 为本模板五项检查、+2 为本用例的两个 JSON 块），8 项失败全属既有 `T-036`（通用模板缺 `context` 节），**本轮零新增** |
| 2 | 产物 JSON 静态契约自检 | ✅ 通过（2026-10-14 补测） | `validate_output.py`：本用例的**两个 JSON 块**分形态各跑一套——**交付包**（`pack`）**11 项**（R26／R27／R28／R29／R30／R31／R32／R33／R34／R35／R36）＋ **独立台账**（`ledger`）**3 项**（R37／R2／R21）= **14 项全部通过**。整工程口径：**67 通过 / 0 失败 / 0 警告**（SW-008 前为 53/0/0；**新增的 14 项全部来自本用例**）。⚠️ 此项为**静态契约**校验，**不等于**「模型能生成合规产物」 |
| 3 | 规则有效性（负向验证） | ✅ 通过（2026-10-14 补测） | `tests/negtest_pack_rules.py`：**39 个越界样本 + 4 个已知盲区 = 43 项全部符合预期**（SW-008 前为 32+3=35）。本轮为 **R37 新增 7 个越界样本**——顶层混装契约外键／缺 `fill_fallback`／缺 `upstream_field`／`blocking` 写成字符串 `"false"`／`fill_stage` 写成 `storyboard`／多出 `design_source`／`unspecified` 为空数组；另登记 **1 个已知盲区**（`reason`／`fill_fallback` 写成空串——R37 **刻意不判**文本质量，判它等于自造比契约更严的私有口径，同 R33 的取舍）。只跑通过样本证明不了校验器有效——此步不可省 |
| 4 | 交付门禁脚本 `validate_pack.py` | ⚠️ **BLOCK 1（且已知、已登记）** | 本包**可直接投喂**门禁脚本。1 条 BLOCK 的原文为 `meta/generation_trace/stage_chain/0: 'revise' is not one of ['synopsis', 'script', 'storyboard', 'shot_prompt']`——**这正是 `ISSUE-017` 的可见证据**（契约枚举缺 `revise`），**不是本层产物错误**。除该条外**零 BLOCK**；WARN 均可解释（`provider.code` 占位待回填 + 质量门通过的信息性 WARN）。**处置口径同 `ISSUE-015`：留 BLOCK 可见、改契约而非改产物**——把产物改成 `["shot_prompt"]` 能让门禁变绿，但那是**伪造溯源** |
| 5 | 本轮自查发现并修正的**三处**缺陷 | ✅ 已修正 | **① 模板语义错**：`TPL-014` 的版本说明与示例 2 原写「设计类字段标 `design_source = …`」——但**交付包契约根本没有 `design_source` 键**（`characters[]`／`props[]` 均 `additionalProperties: false`），照此写法产出会被 `R36` 拒收。**已改为「二分登记在缺口台账与 `meta.notes`」**（`TPL-014` ＋ `CFG-008_manifest.yaml` ＋ `CFG-007_SCHEMA.md` 三处同口径）。<br>**② 模板与清单的 5 处 YAML 语法缺陷**：标量行首 `**` 被解析为 alias／plain scalar 内的 ASCII 冒号空格／值以 `{` 开头被当作 flow mapping／反引号作首字符／双引号标量提前闭合。⚠️ **后果不是「报一个错」而是「检查静默中断」**：`CFG-008_manifest.yaml` 一解析失败，`validate_templates.py` 就从 **62 项检查掉到 5 项**——**看起来只是「失败 1 项」，实际是 57 项检查根本没跑**。<br>**③ 校验器缺陷**：`validate_output.py` 的 `scan_examples()` **未在每个文件开始时重置 `UPSTREAM`**，后一个用例会**静默继承**前一个用例的上游。实测：**无上游**的 `CASE-005` 因继承 `CASE-002` 的分镜上游，被判 R31「时长不守恒 3 处」——**一条纯净的产物报出一条纯属继承的错**。该缺陷只在「新增用例」时暴露（此前四个文件里最后一个 `CASE-004` 是 synopsis 形态，根本不跑 R23／R24／R31）。已修复。<br>三处一并留痕 `DEV-20261014-007` |
| 6 | 本用例作为「**模型实测**证据」 | ❌ **不成立** | 本节输出为**人工构造的结构基线**，非模型产物。**不得**把「结构看起来对」或「脚本全绿」当成「模型已能生成」——§3 的两个 JSON 是**目标形态**，不是 Qwen2.5-7B-Instruct 的真实输出 |
| 7 | 模型实测（Qwen2.5-7B-Instruct） | ⏳ **待做** | 需 GPU 环境（T-012 已解锁）；实测后须替换 §3 为**真实输出**并保留原始采样日志；并须补一组**脱敏后的真实客户素材**（本用例的素材是构造的） |

**闭环条件**：① 模型就绪后由 `revise_v1`（v1.0.0）产出真实包；② 真实包过 `validate_output.py`（交付包形态 R26~R36 + 台账 R37 全通过）**且** `validate_pack.py` 除 `ISSUE-017` 外 **0 BLOCK**；③ 对 H3 适配投喂文本跑 `audit_shots.py --gate`。**三项齐备后方可从「未验证」改为「已验证」。** 当前状态：**② 已成立**（基于本人工构造基线）；① ③ 均未做。故整体仍标 **未验证**。

⚠️ **本用例已知残留**：① `ISSUE-017`（`stage_chain` 枚举缺 `revise`）**待项目方裁决**——裁决为 (a) 后，本包与 `TPL-014` 均**零改动**即变绿（改的是契约）；② 本层的两条核心纪律（**素材守恒**／**粒度守恒**）**目前无脚本判据**——它们需要与 `source_material` 原文比对，而交付包脚本拿不到客户素材。当前由模板 `guards` 的 8 条【增量】自检项与人工复核承担，**已登记为后续项**（候选：为 `revise` 层单独做一个带 `--source` 的比对脚本）。
