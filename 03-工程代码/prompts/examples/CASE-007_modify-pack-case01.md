# modify-pack-case01 · `target_stage=pack` 的对话式修改与零漂移校验

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-MOD-002` |
| 对应需求 | **SW-002 对话式修改**（通用迭代入口：对「当前阶段产物」做定向修改、保持跨阶段一致性；异常＝修改意见含糊时澄清） |
| 主模板 | `modify_v1` **v1.1.0**（业务链路**支撑模板**，**刻意不填 `stage`**——与链路阶段正交，见其版本说明） |
| 连带模板 | `check_consistency_v1` **v1.1.0**（一致性校验侧，`pair_role=before_after`） |
| 产物形态参照 | `CASE-002_shot-prompt-case01.md`（**交付包形态**）。⚠️ 本用例**自带一份精简交付包**（**1 单元 / 3 镜 / 15000ms**，取自 `CASE-002` 的第 1 单元并按契约重新对齐总时长）而非引用其全文——理由同 `CASE-006`：让「修改前 ↔ 修改后」**可逐字比对** |
| 用例来源 | **构造用例**（修改意见为人为设计，含 6 处陷阱位；正式使用前须补一组脱敏真实客户意见） |
| 采样参数 | temperature 0.2 / top_p 0.85 / top_k 40 / max_tokens 8192（**受约束解码**；温度取全库最低档）。⚠️ 低温**不是**「顺手多改」的防线（成因是模型自认为的"规范化"，不是采样随机性）——真正的防线是 `guards` 第 1 条的全文差异清单。 |
| 记录日期 | 2026-10-14 |
| **验证状态** | ⚠️ **未验证**——未跑模型。以下产物为**人工按模板纪律构造**，用于固化判据口径与陷阱位；实测须待模型就绪后由 `tests/` 下的负向样本与人工抽检（SW-002 验收要求 **≥30 例**，口径见 `PRO-003`）共同承担 |

> **⚠️ 本用例与 `CASE-006` 的分工（两份用例各管一半，不可互相替代）**：`CASE-006` 的 `target_stage=storyboard`，覆盖**四类阶段产物**的常规形态；本用例的 `target_stage=pack`，覆盖**只有交付包才存在**的两个专属问题——
> ① **正交性溯源的可落地性**（`MR-13`）：`meta.generation_trace` **只有交付包有**，四类阶段产物顶层没有 `meta` 段，其「改过一轮」只能靠服务层会话留档；
> ② **「字段 → 正文」牵连**（`MR-14`）：交付包受「八维双落地」（规范 §4.1）约束，改一个维度字段**必然**牵连该镜的中英两段正文——这是交付包**特有**的牵连类型，分镜层不存在。

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `target_stage` | **`pack`** —— 被改对象是**交付包**（`shot_prompt` 阶段的产物，形态 `pack`）。⚠️ 该值取自**产物自身**的阶段属性，**不是**本模板的运行阶段（`modify_v1` 无 `stage`）；且按 `R38` 的映射，`pack` 与 `shot_prompt` **同映射到交付包形态**，本用例取前者（更直白） |
| `current_artifact` | 见 **§2.1**（1 单元 / 3 镜 / 15000ms） |
| `modification_request` | 见 **§2.2**（客户原话，**一句、单个意图**） |
| `change_context` | **无**（首轮修改） |
| `upstream_artifact` | **无** —— ⚠️ 本用例**两种理由叠加**，都须被显式登记：① `target_stage=pack` 是链路**末端**，本层本就没有上游模板产物；② 本用例刻意不注入服务层的 `artifact` 差分基准。故「零漂移只能以当前产物自身为基准」这一**局限**必须写进 `unresolved`，而不是被悄悄省略 |
| `locked_paths` | `meta.pack_id`、`aigc_meta.AIGC.ProduceID`、`style_bible.style_id`、`shots[*].shot_id`、`units[*].unit_id`、`units[*].shot_ids`、`shots[*].scene_no`、`shots[*].character_refs`、`shots[*].prop_refs`（**锚本体 8 项中的 7 项 + 引用面 4 项全锁**；未锁的是 `character_id`／`prop_id` —— 本用例无「换角色出演」类请求） |

### 2.1 修改前产物（`current_artifact`）

```json
{
  "schema_version": "2.1.0",
  "meta": {
    "pack_id": "FR-PK-20261014-CASE0007",
    "title": "雨夜的猫",
    "created_at": "2026-10-14T10:00:00+08:00",
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
      "session_id": "SESS-CASE-0007",
      "task_id": "TASK-CASE-0007",
      "stage_chain": [
        "synopsis",
        "script",
        "storyboard",
        "shot_prompt"
      ],
      "templates": [
        {
          "id": "synopsis_v1",
          "version": "2.0.0"
        },
        {
          "id": "script_v1",
          "version": "2.0.0"
        },
        {
          "id": "storyboard_v1",
          "version": "2.1.0"
        },
        {
          "id": "shot_prompt_v1",
          "version": "2.0.0"
        }
      ],
      "model": {
        "name": "Qwen2.5-7B-Instruct",
        "backend": "vllm",
        "revision": "main"
      }
    },
    "compliance": {
      "safety_check": {
        "input": "passed",
        "output": "passed",
        "checked_at": "2026-10-14T09:59:40+08:00"
      },
      "copyright_check": {
        "status": "passed",
        "note": "原创内容，无改编来源"
      },
      "marking_check": {
        "explicit": "present",
        "implicit": "present"
      },
      "statement_id": "FR-ST-20261014-CASE0007"
    },
    "aspect_ratio_default": "16:9",
    "total_duration_ms": 15000,
    "notes": "【精简用例 · 2026-10-14 由 CASE-002 的第 1 单元裁剪并重新对齐总时长】仅保留 U01／3 镜／15000ms。除 `pack_id`／`statement_id`／`session_id`／`task_id`／`created_at`／`total_duration_ms`／本说明为用例独立取值外，字段集与其余取值**逐字取自 CASE-002**（该包已过 `R26`~`R36` 与交付门禁 `BLOCK 0`）。裁剪目的：让 pack 形态的「修改前 ↔ 修改后」**可逐字比对**（14 镜的规模会让变更说明与漂移报告淹没在噪声里）。⚠️ 本包为**人工构造样本、未经模型实测**。"
  },
  "style_bible": {
    "style_id": "STYLE-01",
    "style_prompt_zh": "日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和，写实光影层次",
    "style_prompt_en": "Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation, realistic lighting layers",
    "style_anchors": [
      "日式动画电影质感",
      "柔和赛璐璐上色",
      "冷灰蓝主色调",
      "克制低饱和"
    ],
    "lighting_default": "practical_light",
    "negative_global": [
      "lowres",
      "blurry",
      "watermark",
      "text",
      "deformed",
      "extra limbs",
      "flicker",
      "temporal jitter",
      "frame inconsistency",
      "clipping",
      "morphing",
      "limb popping"
    ]
  },
  "characters": [
    {
      "character_id": "CHR-01",
      "name": "未指定",
      "appearance_lock_zh": "短发、浓眉，深蓝色外卖冲锋衣（配反光条），身形清瘦，右手腕戴一只磨旧的电子表",
      "appearance_lock_en": "short hair, thick brows, a dark blue delivery jacket with reflective strips, lean build, a worn digital watch on the right wrist",
      "forbidden": [
        "发型变化",
        "服装颜色变化"
      ]
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
      "shot_ids": [
        "S01-SH001",
        "S01-SH002",
        "S01-SH003"
      ],
      "soundscape": "暴雨拍打铁皮雨棚的密集声，楼道口积水顺台阶往下淌",
      "music": "N/A",
      "notes": "单人戏，按单人替身法则处理"
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
      "character_refs": [
        "CHR-01"
      ],
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
      "character_refs": [
        "CHR-01"
      ],
      "prop_refs": [
        "PRP-01"
      ],
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
      "character_refs": [
        "CHR-01"
      ],
      "prop_refs": [
        "PRP-01"
      ],
      "dialogue": "雨砸在铁皮雨棚上，像有人在替他数秒。",
      "sfx": "雨声、纸箱刮过水泥地的摩擦声",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜，故有 transition_out"
    }
  ],
  "forbidden_items": [],
  "aigc_meta": {
    "AIGC": {
      "Label": "1",
      "ContentProducer": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "ProduceID": "FR-PK-20261014-CASE0007",
      "ReservedCode1": "",
      "ContentPropagator": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
      "PropagateID": "FR-PK-20261014-CASE0007",
      "ReservedCode2": ""
    }
  }
}
```
⚠️ 本包**三镜均带 `lighting`（纯词表值）**——`R32` 对交付包要求「纯词表值」（说明文字移入正文），
与分镜层的「词表值——中文光位说明」**形态不同**，勿混。三镜**均非 `static`／`pov`**，故**均带** `amplitude`／`speed`
（`R26` 只禁 `static`／`pov` 携带这两个键，不是「一律禁止」）。

### 2.2 客户修改意见原文（`modification_request`）

```text
第 1 镜别用远景了，改成中景。
```

## 3 动笔前的意图拆解（模板 `system` 硬性约束 3 + `task` 第一步）

| 意图 | 客户原话片段（`basis`） | 改哪里（`target_path`） | 原值（`before`，逐字摘自 §2.1） | 新值（`after`） | 牵连？ |
| --- | --- | --- | --- | --- | --- |
| ① 第 1 镜景别由远景改为中景 | 「第 1 镜别用远景了，改成中景」 | `shots[0].shot_size` | `wide` | `medium` | **有**：交付包受「八维双落地」约束（规范 §4.1）——每个维度须**同时** ①有字段承载 ②**写进 `prompt_zh`／`prompt_en` 正文**（模型读的是文本，不是字段） |

**1 条意图 → 3 条记录**：意图 ① 的两个**正文承载位置**（中文／英文）**各占一条记录、共用同一 `basis`**——
这不是「过拆」，而是本用例的核心：**只改字段不改正文，等于把「中景」这个决定锁在 JSON 里，
模型读到的仍是「远景」**。⚠️ 该形态**没有独立的 `upstream_impact` 取值**，归入 `other`，
但 `intent` **必须写明正文落点（中／英、第几镜）**（评审 `MR-14`）——否则「改了字段没改正文」在变更说明里看不出来。

## 4 修改后产物 + 变更说明（`modify_v1` 的完整输出）

```json
{
  "modify_version": "1.1.0",
  "target_stage": "pack",
  "artifact": {
    "schema_version": "2.1.0",
    "meta": {
      "pack_id": "FR-PK-20261014-CASE0007",
      "title": "雨夜的猫",
      "created_at": "2026-10-14T10:00:00+08:00",
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
        "session_id": "SESS-CASE-0007",
        "task_id": "TASK-CASE-0007",
        "stage_chain": [
          "synopsis",
          "script",
          "storyboard",
          "shot_prompt"
        ],
        "templates": [
          {
            "id": "synopsis_v1",
            "version": "2.0.0"
          },
          {
            "id": "script_v1",
            "version": "2.0.0"
          },
          {
            "id": "storyboard_v1",
            "version": "2.1.0"
          },
          {
            "id": "shot_prompt_v1",
            "version": "2.0.0"
          },
          {
            "id": "modify_v1",
            "version": "1.1.0"
          }
        ],
        "model": {
          "name": "Qwen2.5-7B-Instruct",
          "backend": "vllm",
          "revision": "main"
        }
      },
      "compliance": {
        "safety_check": {
          "input": "passed",
          "output": "passed",
          "checked_at": "2026-10-14T09:59:40+08:00"
        },
        "copyright_check": {
          "status": "passed",
          "note": "原创内容，无改编来源"
        },
        "marking_check": {
          "explicit": "present",
          "implicit": "present"
        },
        "statement_id": "FR-ST-20261014-CASE0007"
      },
      "aspect_ratio_default": "16:9",
      "total_duration_ms": 15000,
      "notes": "【精简用例 · 2026-10-14 由 CASE-002 的第 1 单元裁剪并重新对齐总时长】仅保留 U01／3 镜／15000ms。除 `pack_id`／`statement_id`／`session_id`／`task_id`／`created_at`／`total_duration_ms`／本说明为用例独立取值外，字段集与其余取值**逐字取自 CASE-002**（该包已过 `R26`~`R36` 与交付门禁 `BLOCK 0`）。裁剪目的：让 pack 形态的「修改前 ↔ 修改后」**可逐字比对**（14 镜的规模会让变更说明与漂移报告淹没在噪声里）。⚠️ 本包为**人工构造样本、未经模型实测**。"
    },
    "style_bible": {
      "style_id": "STYLE-01",
      "style_prompt_zh": "日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和，写实光影层次",
      "style_prompt_en": "Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation, realistic lighting layers",
      "style_anchors": [
        "日式动画电影质感",
        "柔和赛璐璐上色",
        "冷灰蓝主色调",
        "克制低饱和"
      ],
      "lighting_default": "practical_light",
      "negative_global": [
        "lowres",
        "blurry",
        "watermark",
        "text",
        "deformed",
        "extra limbs",
        "flicker",
        "temporal jitter",
        "frame inconsistency",
        "clipping",
        "morphing",
        "limb popping"
      ]
    },
    "characters": [
      {
        "character_id": "CHR-01",
        "name": "未指定",
        "appearance_lock_zh": "短发、浓眉，深蓝色外卖冲锋衣（配反光条），身形清瘦，右手腕戴一只磨旧的电子表",
        "appearance_lock_en": "short hair, thick brows, a dark blue delivery jacket with reflective strips, lean build, a worn digital watch on the right wrist",
        "forbidden": [
          "发型变化",
          "服装颜色变化"
        ]
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
        "shot_ids": [
          "S01-SH001",
          "S01-SH002",
          "S01-SH003"
        ],
        "soundscape": "暴雨拍打铁皮雨棚的密集声，楼道口积水顺台阶往下淌",
        "music": "N/A",
        "notes": "单人戏，按单人替身法则处理"
      }
    ],
    "shots": [
      {
        "shot_id": "S01-SH001",
        "unit_id": "U01",
        "scene_no": 1,
        "shot_no": 1,
        "shot_size": "medium",
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
        "prompt_zh": "中景：暴雨夜的居民楼楼道口，一个外卖员拎着外卖箱站在檐下，半边肩还在雨里；他侧身往墙里挪了半步，背贴墙面站定，视线压在手机屏上。镜头从楼道口外三米、齐腰高度缓缓前推，停在他的肩背，雨幕堆在身后，浅景深把身后的雨帘化开。人落在画面右三分，左侧三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘；空间轴左为楼道口、右为街面，全集不越此轴。楼道感应灯在他下半张脸上打出一道硬边，街灯反光从积水里泛上来。雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
        "prompt_en": "A medium shot of a delivery rider sheltering at the entrance of an old residential building on a stormy night, a delivery box in one hand and one shoulder still in the rain. He shifts half a step toward the wall and settles with his back against it, eyes on his phone. The camera pushes in with small amplitude at slow speed from three meters out at waist height, stopping on his shoulders and back with the rain curtain piling up behind him, holding a shallow depth of field so the rain behind him falls out of focus. He sits in the right third of the frame with the deep entrance shaft filling the left third, spray from the ground pressing the lower edge. The space axis runs from the dark entrance on the left to the bright street on the right, uncrossed throughout. A practical light from the motion-sensor lamp cuts a hard edge across the lower half of his face while streetlight reflects up from the standing water. Rain runs down his sleeve in a steady stream, pooling at his feet and dimpling under fresh drops. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
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
        "character_refs": [
          "CHR-01"
        ],
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
        "character_refs": [
          "CHR-01"
        ],
        "prop_refs": [
          "PRP-01"
        ],
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
        "character_refs": [
          "CHR-01"
        ],
        "prop_refs": [
          "PRP-01"
        ],
        "dialogue": "雨砸在铁皮雨棚上，像有人在替他数秒。",
        "sfx": "雨声、纸箱刮过水泥地的摩擦声",
        "transition_in": "cut",
        "transition_out": "fade_out",
        "notes": "单元末镜，故有 transition_out"
      }
    ],
    "forbidden_items": [],
    "aigc_meta": {
      "AIGC": {
        "Label": "1",
        "ContentProducer": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
        "ProduceID": "FR-PK-20261014-CASE0007",
        "ReservedCode1": "",
        "ContentPropagator": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
        "PropagateID": "FR-PK-20261014-CASE0007",
        "ReservedCode2": ""
      }
    }
  },
  "change_log": [
    {
      "op_id": "MOD-01",
      "intent": "第 1 镜景别由远景改为中景（**字段**）",
      "target_path": "shots[0].shot_size",
      "op_type": "replace",
      "before": "wide",
      "after": "medium",
      "basis": "第 1 镜别用远景了，改成中景",
      "upstream_impact": "other"
    },
    {
      "op_id": "MOD-02",
      "intent": "第 1 镜**中文正文**同步景别表述（MOD-01 的正文承载位置：中文）",
      "target_path": "shots[0].prompt_zh",
      "op_type": "replace",
      "before": "远景：暴雨夜的居民楼楼道口，一个外卖员拎着外卖箱站在檐下，半边肩还在雨里；他侧身往墙里挪了半步，背贴墙面站定，视线压在手机屏上。镜头从楼道口外三米、齐腰高度缓缓前推，停在他的肩背，雨幕堆在身后，浅景深把身后的雨帘化开。人落在画面右三分，左侧三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘；空间轴左为楼道口、右为街面，全集不越此轴。楼道感应灯在他下半张脸上打出一道硬边，街灯反光从积水里泛上来。雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "after": "中景：暴雨夜的居民楼楼道口，一个外卖员拎着外卖箱站在檐下，半边肩还在雨里；他侧身往墙里挪了半步，背贴墙面站定，视线压在手机屏上。镜头从楼道口外三米、齐腰高度缓缓前推，停在他的肩背，雨幕堆在身后，浅景深把身后的雨帘化开。人落在画面右三分，左侧三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘；空间轴左为楼道口、右为街面，全集不越此轴。楼道感应灯在他下半张脸上打出一道硬边，街灯反光从积水里泛上来。雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪。日式动画电影质感，柔和赛璐璐上色，冷灰蓝主色调，克制低饱和。",
      "basis": "第 1 镜别用远景了，改成中景",
      "upstream_impact": "other"
    },
    {
      "op_id": "MOD-03",
      "intent": "第 1 镜**英文正文**同步景别表述（MOD-01 的正文承载位置：英文）",
      "target_path": "shots[0].prompt_en",
      "op_type": "replace",
      "before": "A wide shot of a delivery rider sheltering at the entrance of an old residential building on a stormy night, a delivery box in one hand and one shoulder still in the rain. He shifts half a step toward the wall and settles with his back against it, eyes on his phone. The camera pushes in with small amplitude at slow speed from three meters out at waist height, stopping on his shoulders and back with the rain curtain piling up behind him, holding a shallow depth of field so the rain behind him falls out of focus. He sits in the right third of the frame with the deep entrance shaft filling the left third, spray from the ground pressing the lower edge. The space axis runs from the dark entrance on the left to the bright street on the right, uncrossed throughout. A practical light from the motion-sensor lamp cuts a hard edge across the lower half of his face while streetlight reflects up from the standing water. Rain runs down his sleeve in a steady stream, pooling at his feet and dimpling under fresh drops. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "after": "A medium shot of a delivery rider sheltering at the entrance of an old residential building on a stormy night, a delivery box in one hand and one shoulder still in the rain. He shifts half a step toward the wall and settles with his back against it, eyes on his phone. The camera pushes in with small amplitude at slow speed from three meters out at waist height, stopping on his shoulders and back with the rain curtain piling up behind him, holding a shallow depth of field so the rain behind him falls out of focus. He sits in the right third of the frame with the deep entrance shaft filling the left third, spray from the ground pressing the lower edge. The space axis runs from the dark entrance on the left to the bright street on the right, uncrossed throughout. A practical light from the motion-sensor lamp cuts a hard edge across the lower half of his face while streetlight reflects up from the standing water. Rain runs down his sleeve in a steady stream, pooling at his feet and dimpling under fresh drops. Japanese anime film look, soft cel shading, cool grey-blue palette, restrained low saturation.",
      "basis": "第 1 镜别用远景了，改成中景",
      "upstream_impact": "other"
    }
  ],
  "unresolved": [
    {
      "type": "limitation",
      "field": "（全局）漂移基准",
      "reason": "本轮未提供上游产物——`target_stage=pack` 是链路的**末端**，本层没有对应的上游模板产物，零漂移只能以「修改前的当前产物」自身为基准",
      "need": "服务层注入 `upstream_artifact` 后由 `check_consistency_v1` 复跑一次，方可与上游事实交叉验证",
      "blocking": false
    },
    {
      "type": "finding",
      "field": "meta.generation_trace.templates",
      "reason": "本轮的「改过一轮」事实落在 `meta.generation_trace.templates` 追加的一条（`modify_v1` v1.1.0）。⚠️ 该追加是本层**规定动作**（模板阶段纪律复述），**不属「顺手多改」**，也**不写入 `change_log`**（其 `basis` 无法指回客户原话）；`stage_chain` 保持原 4 值**不追加**（枚举封闭）。此处登记以便复核",
      "need": "无（本层规定动作）；服务层留档的轮次号与之对应",
      "blocking": false
    }
  ],
  "clarification": {
    "needed": false,
    "questions": []
  }
}
```
⚠️ **两处必须看懂的地方**：

1. **`before`／`after` 是逐字全文，不是节选**——`MOD-02`／`MOD-03` 的字段是正文全文（265 字／1113 字符），
   因为 `R38` 第 ⑤ 条的**取值级自洽**要求 `artifact[target_path]` **逐字等于** `after`。
   长文本字段的代价就在这里：**容不下「（原文节选）」这类省略写法**（模板 `examples` 为可读性以节选示意，实际产物不行）。
2. **`meta.generation_trace.templates` 追加了一条** `{"id": "modify_v1", "version": "1.1.0"}`——这是本层
   「修改确实发生过」的落点（见模板 `guards` 的阶段纪律复述）。⚠️ 该追加**不写入 `change_log`**（其 `basis`
   无法指回客户原话），而由 `guards` 第 1 条**明文豁免**出「顺手多改」的判定；`stage_chain` 保持原 4 值**不追加**（枚举封闭）。

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
      "category": "setting",
      "item": "第 1 镜景别（shots[0].shot_size）",
      "value_a": "wide",
      "value_b": "medium",
      "location_b": "shots[0].shot_size",
      "verdict": "drift",
      "action": "属本轮修改意图（对应 change_log 的 MOD-01）；before_after 口径下不判责任，由人对照 change_log 确认"
    },
    {
      "finding_id": "DR-02",
      "category": "setting",
      "item": "第 1 镜中文正文的景别表述（shots[0].prompt_zh 的起首两字）",
      "value_a": "远景：",
      "value_b": "中景：",
      "location_b": "shots[0].prompt_zh",
      "verdict": "drift",
      "action": "正文承载位置的景别词随 MOD-01 同步（对应 MOD-02）；正文其余文字逐字未变（该字段全文共 265 字）"
    },
    {
      "finding_id": "DR-03",
      "category": "setting",
      "item": "第 1 镜英文正文的景别表述（shots[0].prompt_en 的起首四词）",
      "value_a": "A wide shot of",
      "value_b": "A medium shot of",
      "location_b": "shots[0].prompt_en",
      "verdict": "drift",
      "action": "同上（对应 MOD-03）；正文其余文字逐字未变（该字段全文共 1113 字符，仍在 v2.1 上限 1200 之内）"
    },
    {
      "finding_id": "DR-04",
      "category": "number",
      "item": "第 2 镜时长（shots[1].duration_ms）",
      "value_a": "5000",
      "value_b": "5000",
      "location_b": "shots[1].duration_ms",
      "verdict": "consistent",
      "action": "未被点名，逐字未变（数字类**逐处登记**：第 2 镜单独一条）"
    },
    {
      "finding_id": "DR-05",
      "category": "number",
      "item": "第 3 镜时长（shots[2].duration_ms）",
      "value_a": "5000",
      "value_b": "5000",
      "location_b": "shots[2].duration_ms",
      "verdict": "consistent",
      "action": "未被点名，逐字未变（数字类**逐处登记**：第 3 镜单独一条）——与 DR-04 分列，正是为了不把「逐处性」抹掉"
    },
    {
      "finding_id": "DR-06",
      "category": "number",
      "item": "整片总时长（meta.total_duration_ms）",
      "value_a": "15000",
      "value_b": "15000",
      "location_b": "meta.total_duration_ms",
      "verdict": "consistent",
      "action": "未被点名，逐字未变；与 Σ 单镜时长自洽（5000 × 3 ＝ 15000）"
    },
    {
      "finding_id": "DR-07",
      "category": "anchor",
      "item": "锚与编号全量比对（本体 8 项 + 引用面 4 项，清单见 CFG-007【封闭枚举登记】）",
      "value_a": "CHR-01 / PRP-01 / 1,1,1 / S01-SH001..003 / U01 / STYLE-01 / FR-PK-20261014-CASE0007 / 同 pack_id",
      "value_b": "CHR-01 / PRP-01 / 1,1,1 / S01-SH001..003 / U01 / STYLE-01 / FR-PK-20261014-CASE0007 / 同 pack_id",
      "location_b": "shots[*] 与 units[*] 全域",
      "verdict": "consistent",
      "action": "本次已扫锚：锚与编号共 12 项（本体 8 + 引用面 4，本包**全部在场**）、合计 28 处全部一致（零容忍类整体复述）——本条**不得省略**：缺此条则无法区分「锚全部一致」与「根本没查锚」。⚠️ 本行 location_b 为全量复述的代表落点（锚类条目**豁免** `location_b` 形式校验）"
    }
  ],
  "summary": {
    "checked_count": 7,
    "drift_count": 3,
    "verdict": "drift"
  }
}
```
## 6 陷阱位（6 处，均为人为植入的失败模式）

| # | 陷阱 | 错在哪 | 正确处置 |
| --- | --- | --- | --- |
| 1 | 改了 `shots[0].shot_size`，**没改正文** | **八维双落地的失守**——字段说中景、正文仍写「远景：」，模型实际读到的还是远景。⚠️ **没有任何脚本会报错**（`R27`／`R29` 均不比对「字段与正文是否同源」） | 正文必须同步（MOD-02／MOD-03）；漏改即「真牵连漏改」 |
| 2 | 顺手把**全篇**的景别词统一成「中景」口径 | **顺手多改**（客户只点名第 1 镜）——没有任何字段会因此报错 | 回退原值；若要改须记入 `unresolved` 等客户确认 |
| 3 | 改景别的同时把 `shots[0].camera.optics` 也改成 `deep_focus` | **假牵连**：景别与光学是**两个维度**，客户未点名光学 | 判 `upstream_impact=none`、不动 |
| 4 | 把 `meta.pack_id` 或 `aigc_meta.AIGC.ProduceID` 一起改了 | **改锚**（且 `ProduceID` 按规范必须**恒等于** `meta.pack_id`，改一处即两处失守） | 命中 `locked_paths` → 不改动、转 `fallback.locked_violation` |
| 5 | 客户追一句「整体再精致一点」 | **含糊**——程度词无判据 | `clarification.needed=true`、`change_log` **置空**、`artifact` 逐字不变，转 `guard_clarify_v1` 追问 |
| 6 | 客户追一句「风格换成水墨」 | **越权**——改 `style_bible`＝改设定，须重走 `shot_prompt` 段成包 | 不产出改动，转 `fallback.out_of_scope`，记 `unresolved` 并说明「须 `revise_v1` 重新成包」 |

## 7 评测项（逐项可判）

| # | 评测项 | 判据 | 本用例结果 |
| --- | --- | --- | --- |
| 1 | 输出形态 | 顶层恰好 6 键（`modify_version`／`target_stage`／`artifact`／`change_log`／`unresolved`／`clarification`） | ✅ |
| 2 | `artifact` 完整性 | 是**完整交付包**（可直接替换原包），非 diff 片段 | ✅（1 单元 / 3 镜 / 九键齐备） |
| 3 | `target_stage` 回显与形态相符 | 与输入一致（`pack`），且 `artifact` 形态与之相符（`pack` → `pack`） | ✅ |
| 4 | `change_log` 条数 | 1 条意图 → 3 条记录（字段 + 中文正文承载 + 英文正文承载） | ✅ |
| 5 | `op_id` 形态与唯一性 | 形如 `MOD-\d{2}`、全表唯一、不跳号（MOD-01/02/03） | ✅ |
| 6 | `target_path` 可达性 | 每条路径都能在 `artifact` 中解析到（**`insert`／`delete` 豁免**，改判反向检查） | ✅（三条均 `replace`，三条路径均可解析） |
| 7 | `op_type` 取值 | ∈ {replace, normalize, insert, delete} | ✅（三条均 replace） |
| 8 | `before`／`after` 逐字性 | 与 §2.1／§4 **逐字全文**相同（非节选、非推算） | ✅（`wide`／265 字正文／1113 字符正文，均全文照录） |
| 9 | `basis` 指回性 | 每条 `basis` 是客户原话的逐字片段 | ✅（三条同源） |
| 10 | 同源牵连共用 `basis` | MOD-01／02／03 的 `basis` 相同 | ✅ |
| 11 | 未点名处逐字保持 | §2.1 与 §4 的**内容**差异**恰好 3 处** | ✅；另**规定动作** 1 处（`generation_trace.templates` 追加，见 §9 边界） |
| 12 | 锚与编号零变化 | 12 项（本体 8 + 引用面 4）逐字相同 | ✅ |
| 13 | 枚举取值合法 | `shot_size=medium` 在 6 值内；三镜均非 `static`／`pov`，**均带** `amplitude`／`speed`；`lighting` 为**纯词表值**（交付包口径） | ✅ |
| 14 | `unresolved` 形态 | 每条恰好 **5** 键、`blocking` 为**布尔**、`type` 在枚举内 | ✅（2 条：`limitation`／`finding`，均 `false` 布尔） |
| 15 | 上游基准局限已登记 | `upstream_artifact` 为空时 `unresolved` 必有一条说明该局限 | ✅（第 1 条） |
| 16 | `clarification` 形态 | 恰好 2 键；`needed=false` 时 `questions` 为空数组 | ✅ |
| 17 | 报告四类全覆盖 | 漂移报告含 number／setting／anchor 三类（本包无 proper_noun 可查） | ✅ |
| 18 | 报告 anchor 类整体复述 | 锚类即使一致也有汇总条目（DR-07） | ✅ |
| 19 | 报告自洽复算 | `checked_count`＝清单条数；`drift_count`＝非 consistent 条数；`verdict` 随之 | ✅（7／3／drift） |
| 20 | 报告不越界 | 只报告，产物零改动 | ✅ |
| 21 | `focus` 回显与缩范围声明 | 顶层含 `focus` 且与输入一致；`focus=全篇` 时 anchor 条目含「本次已扫锚」 | ✅（`focus="全篇"`；DR-07 已写明） |
| 22 | 逐处性（同一类数值的每一处各占一条） | 未点名的第 2／3 镜时长与总时长**各占一条**，未合并 | ✅（DR-04／DR-05／DR-06 分列） |
| 23 | **pack 专属 · 溯源追加已落地** | `target_stage=pack` 时「改过一轮」落 `meta.generation_trace.templates`；且 `stage_chain` **保持原值不追加** | ✅（追加 `modify_v1`；`stage_chain` 仍 4 值） |
| 24 | **pack 专属 · 正文落点已写明** | 「字段 → 正文」牵连的 `intent` **必须**写明正文落点（中／英、第几镜） | ✅（MOD-02「中文」／MOD-03「英文」） |

## 8 自检表

| 检查 | 结果 |
| --- | --- |
| `current_artifact` 与 `modify_v1` 输出的 `artifact` **内容**差异**恰好 3 处** | ✅ 逐字比对（`shots[0].shot_size`／`shots[0].prompt_zh`／`shots[0].prompt_en`） |
| 另有 1 处**规定动作**差异（`meta.generation_trace.templates` 追加） | ✅ 已豁免出「顺手多改」判定（`guards` 1 明文），并登记于 `unresolved` |
| 差异与 `change_log` **一一对应**（无「多改」） | ✅ 3 处内容差异 ↔ 3 条记录 |
| 客户意图全部落实（无「漏改」） | ✅ 1 条意图 → 字段 + 中英正文三处均已落地 |
| 数字零漂移（除被点名者） | ✅ 三镜时长 5000／5000／5000 与总时长 15000 逐字未变 |
| 设定零漂移（除被点名者） | ✅ 运镜／构图／轴线／画面结果／声音设计／光质逐字未变 |
| 锚与编号零漂移 | ✅ 12 项（本体 8 + 引用面 4）全部逐字相同 |
| 总时长自洽 | ✅ 5000+5000+5000 ＝ 15000 ＝ `meta.total_duration_ms` |
| `ProduceID` 恒等于 `pack_id` | ✅ 两处均为 `FR-PK-20261014-CASE0007` |
| `static` 镜未携带 `amplitude`／`speed` | ✅ 本包无 `static` 镜；三镜均非 `static`／`pov`，携带合法 |
| 枚举值合法 | ✅ `medium` 在 `shot_size` 六值内 |
| `lighting` 覆盖与形态 | ✅ 3/3 镜；**纯词表值**（交付包口径），§2.1 与 §4 逐字相同 |
| `prompt_en` 长度在上限内 | ✅ 1113 ≤ 1200（v2.1 上限） |
| `locked_paths` 无命中 | ✅ 三条记录的目标路径均不在锁定清单内 |
| 模板版本常量 | ✅ `modify_version="1.1.0"` 与 `TPL-015` 文件版本一致；`check_version="1.1.0"` 与 `TPL-016` 一致 |
| 报告三数自洽 | ✅ 7／3／drift |
| 逐处性（同一类数值的每一处各占一条） | ✅ 未点名的第 2／3 镜时长与总时长**各占一条**（DR-04／05／06），未合并 |
| 报告缩范围声明（本轮为全篇，故写「本次已扫锚」） | ✅ DR-07 的 `action` 已写明并给出实比项数（12 项 / 28 处） |
| 产物标注验证状态 | ⚠️ **未验证**（未跑模型） |

## 9 与工程判据的对应

本用例的三个产物形态由 `validate_output.py` 的三条判据承担（**形态 `pack`／`modify`／`drift_report`**）：

| 判据 | 形态 | 覆盖的本用例评测项 |
| --- | --- | --- |
| **`R26`~`R36`**（交付包层 11 条） | `pack` | §2.1 的**修改前产物**按 `pack` 形态整包送检——`R27` 表层八段 + 逐镜 14 字段、`R30` AIGC 元数据块、`R31` 时长守恒、`R32` 光照词表纯度、`R33` 留空口径、`R34` 英文运镜句、`R35` 道具锚一致性、`R36` 契约外字段禁入 等 |
| **`R38` `MODIFY_SHAPE`** | `modify` | 项 1／3／5／6／7／14／16；另加四条**追加**判据：`target_stage` 与 `artifact` 形态须相符、`clarification.needed=true` 时 `change_log` 必空、**取值级自洽三条**、**转出形态** |
| **`R39` `DRIFT_REPORT_SHAPE`** | `drift_report` | 项 17／18／19／21／22；另加一条**追加**判据：`findings` 不得为空数组 |
| **`R40` `DRIFT_ARCHIVE_SHAPE`** | `drift_report`（**归档件**） | ⚠️ **本用例不触发**——本用例的漂移报告是**未归档的原始产物**（承载文件 `CASE-007_modify-pack-case01.md` 不含 `.drift.`），而 R40 的触发条件是**声明式**的（basename 含 `.drift.`）。**归档件**的形态判据由 `tests/negtest_pack_rules.py` 的 `DRIFT_ARCHIVE_CASES`（**5 条越界样本 ＋ 1 条盲区**）承担；正式归档件的命名与落点见规范 **`SPEC-008` V2.3 §1.4／§8.4** |

⚠️ **判据的能力边界（如实登记，不得靠"看起来对"蒙混）**——下列评测项**无脚本判据**：

| 评测项 | 为何判不了 |
| --- | --- |
| 项 2（`artifact` 完整性） | `R38` 只能判「它**像**一份产物」（形态可识别、与 `target_stage` 相符）；「是否真的只差被点名的那几处」需外部基准 |
| 项 8（`before`／`after` 逐字性）／项 9（`basis` 指回性）／项 10（同源牵连共用 `basis`） | 需 `current_artifact` 与客户原话原文才能比对，而本产物**不含**这两者 |
| 项 11（未点名处逐字保持）／项 12（锚与编号零变化） | 同上——而**这两项恰是 SW-002 最核心的两项** |
| 项 4 的反向（**真牵连漏改**：改了字段没改正文） | 同项 11；⚠️ **pack 形态下这条最要紧**——「八维双落地」是交付包的核心约束，而**字段与正文是否同源没有任何脚本判据** |
| 项 13（枚举取值合法） | 由**第 1 个 JSON 块**（`pack` 形态）经 `R26`~`R36` 覆核；`R38` **刻意不递归**校验 `artifact` 内部 |
| 项 15（上游基准局限已登记） | 「`upstream_artifact` 是否为空」在单文件内不可知 |
| 项 20（报告不越界） | 需两份被检产物才能证明「一字未改」 |
| 项 23（溯源追加）／项 24（正文落点） | 均属**自由文本／元数据**层，无结构判据 |

上述无判据项由**模板 `guards` 的自检项 + 人工抽检**承担（SW-002 验收要求 ≥30 例，口径见 `PRO-003`）。
若日后要脚本化项 8／11／12，须为 `validate_output.py` 增设 `--before` 参数（同 `R31` 需 `--storyboard` 的模式）——
**该能力已立项（清单 `T-074`），本次未落地**。⚠️ 该立项号经**一次让号**：原拟 `T-072`（`PM-001` §7 中该号已属 `SW-025`　多模型适配运行态落地）→ 按「以目录内既有文件为准」让号改取 **`T-074`**。⚠️ **`--before` 立项与批次一同号**——`PM-001` §7 的 `T-074` 行原文即「**`SW-002` 决策回执 10 项落实（批次一）＋ `--before` 比对脚本立项**」，二者是**同一次动作的两半**，故**不另占号**（上批曾误判为「两次让号、`--before` 取 `T-075`」，已订正）。

> ⚠️ **本条同时是一处让号与一处误判的收口**：本用例初稿写「已立项（清单 `T-072`）」，而 `T-072` 在 `PM-001` §7 中已属 `SW-025`（多模型适配运行态落地）——属**活跃引用陈旧**（本工程 `ISSUE-019` 一族）。**订正时又一度误判为「两次让号」**（把 `T-074` 读成批次一的台账行）：`T-074` 行的正文同时含批次一与 `--before` 立项两项，**立项号就是 `T-074`**。同批扫尽的另一处见 `PRO-003` §表头「关联」行。

### 9.1 两条 **pack 专属**的边界（本用例首次划出，此前无样本覆盖）

| # | 边界 | 为什么 |
| --- | --- | --- |
| 1 | **`meta.generation_trace` 的溯源追加不属「顺手多改」、不进 `change_log`** | 它是本层的**规定动作**（`MR-13` 的落地形态），而 `guards` 第 1 条的差异清单会把它当成一处「没有对应记录的差异」。**v1.1.0 已在 `guards` 第 1 条明文豁免**，并在 `unresolved` 登记——否则模型要么漏做溯源、要么把它塞进 `change_log` 而写上指不回客户原话的 `basis` |
| 2 | **该追加也不属漂移报告的「四类」比对对象** | 报告的四类＝number／proper_noun／setting／anchor；**溯源元数据不在其列**。⚠️ 这是**刻意划出的边界**，不是遗漏——它的核对由 ① `guards` 1 的正确性（追加是否发生、格式是否合规）② 服务层留档的轮次号 承担。**不得**为了「看起来全」而把它硬塞进某一类 |

### 9.2 与 `CASE-006` 的关系

两份用例**覆盖不同形态、互不替代**：

| | `CASE-006`（`storyboard`） | 本用例（`pack`） |
| --- | --- | --- |
| 零漂移基准 | 无上游（首轮修改） | 无上游（末端阶段 + 刻意不注入） |
| 溯源追加 | **不可落地**（四类阶段产物无 `meta` 段） | ✅ **可落地**（`generation_trace.templates`） |
| 牵连类型 | 数值牵连（单镜时长 → 总时长） | **字段 → 正文**牵连（`MR-14` 的专属形态） |
| 锚清单项数 | 锚与编号 11 项（本产物无 `prop_id` 本体键） | 锚与编号 **12 项全部在场** |
| 特有陷阱 | 改锚（`character_refs` 指向） | 改锚 + **改字段不改正文** + `ProduceID` 恒等约束 |

⚠️ **已知盲区（`tests/negtest_pack_rules.py` 登记；本用例沿用，未新增）**：

| 盲区 | 为何仍无判据 |
| --- | --- |
| 「顺手多改」（改动未被 `change_log` 覆盖的字段） | 需 `current_artifact` 作外部基准 |
| 「`before` 写成空串」 | 同上（`before` 的逐字性须与原件比对） |
| 「**改了却没写记录**」（`change_log` 空而 `artifact` 变了） | 同上——**注意它与"伪记录"不是一回事** |

✅ **「伪记录」（记录说改了、产物里没改）已不再是盲区**：`v1.1.0` 的 `R38` 第 ⑤ 条**取值级自洽**把它变为**可判**。

**不把无判据的事写成"已覆盖"，是本工程反复出现的一类缺陷的根因。**

---

*用例性质：构造用例（**未验证**）　｜　建立 2026-10-14　｜　保留原则：永久保留，模板升版后旧用例不删除*
