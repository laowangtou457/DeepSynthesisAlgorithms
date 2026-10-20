# storyboard-case01 · 分镜脚本生成

## 1 用例信息

| 项 | 值 |
| --- | --- |
| 用例编号 | `CASE-STB-001` |
| 对应需求 | **SW-006 分镜脚本生成** |
| 模板 | `storyboard_v1` **v2.2.0**（本用例正文构造于 v2.1.0；**v2.2.0 仅收口 `quality_gate` 数值字段的填写口径** —— 骨架不再列出 `move_type_min_required`、`move_types` 补「按镜序抄录后再去重」；故下例的 `quality_gate` 已按新口径删除该字段。v2.1.0 系依导演视角独立评审 `BR-01`~`BR-13` 修订，原 v2.0.0；**v2.1.0 系依导演视角独立评审 `BR-01`~`BR-13` 修订**——补切镜依据、动作守恒、外观边界、幅度速度省略规则、追问出口、质量门二分；output 字段未增删故属次版本。v2.0.0 系随上游 `script_v1` v2.0.0 的 output 契约变更**机械承接**：新增 `shots[].prop_refs` 与 `unspecified` 的 `owner`／`upstream_field`） |
| 上游用例 | `CASE-SCR-001`（`examples/CASE-001_script-case01.md`）——本用例的输入即该用例输出的**已确认剧本** |
| 下游 | `shot_prompt_v1`（SW-007）——直接消费本输出的 `units` / `shots` 做格式投影 |
| 用例来源 | **构造用例**（非真实客户素材；正式交付前须补一组脱敏真实素材） |
| 采样参数 | temperature 0.8 / top_p 0.9 / max_tokens 8192 |
| 记录日期 | 2026-10-13 |

## 2 输入

| 变量 | 取值 |
| --- | --- |
| `script_json` | 见下方「上游剧本摘要」——取自 `CASE-SCR-001` 的输出（**`script_v1` v2.0.0 口径**；v1.0.0 → v2.0.0 的 output 变更：新增 `props[]` 与 `scenes[].props_present`／`sfx_hint`，`unspecified` 增 `owner`／`upstream_field`） |
| `duration_bounds` | `4-15`（默认值，MiniMax H3 口径——本项目唯一 `verified` 的目标模型） |
| `gap_answers` | 无。注意口径：自 `script_v1` v2.0.0 起，凡 `owner=客户` 的缺口其 `fill_stage` 一律为 `script`，**不会流到本层**——故本变量按设计应为空，不是「客户漏答」。缺口续接见评测第 20 项 |
| `shot_density` | 标准 |

### 上游剧本摘要（`script_json`）

| 场 | `no` | `purpose` | 地点／时相 | `present` | `est_seconds` | 台词条数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 建立 | 居民楼楼道口 · 暴雨夜 | CHR-01 | 15 | 2（画外音 1 + 旁白 1） |
| 2 | 2 | 升级 | 雨夜非机动车道 · 暴雨夜 | CHR-01 | 18 | 2（对白 1 + 旁白 1） |
| 3 | 3 | 转折 | 另一片居民区单元门口 · 清晨 | CHR-01 | 18 | 2（对白 1 + 旁白 1） |
| 4 | 4 | 反转 | 居民住宅入户门内侧 · 清晨 | CHR-01、CHR-02 | 15 | 2（对白 2） |
| 5 | 5 | 收束 | 客厅窗边沙发一角 · 清晨 | CHR-01、CHR-02 | 15 | 3（对白 2 + 旁白 1） |
| — | — | — | **合计** | — | **81** | **11 条** |

其他关键下游依赖：`style_bible.style_id = STYLE-01`；`characters` 为 `CHR-01`（外卖员，主角）与 `CHR-02`（住所女主人，情感线）；`props` 为 1 项（`PRP-01` 流浪猫，5 场的 `props_present` 均引用之）；`forbidden_items = []`；`unspecified` 共 **8 项**（全部 `owner=客户`、`fill_stage=script`）；各场另有 `sfx_hint` 供本层 `soundscape` 参考。

> **上游状态**：`CASE-SCR-001` 的输出为**人工构造**、未经模型实测（标「未验证」）。本用例沿用同一前提。

## 3 输出

> **状态：待回填。** 本节为目标输出样例（人工构造），用于固化字段结构与写法基线；**尚未经 Qwen2.5-7B-Instruct 实测**。实测后须替换为模型真实输出并保留原始采样日志。

```json
{
  "title": "雨夜的猫",
  "genre": "都市温情",
  "style_ref": "STYLE-01",
  "aspect_ratio_default": "16:9",
  "total_duration_ms": 81000,
  "units": [
    {
      "unit_id": "U01",
      "scene_no": 1,
      "shot_ids": ["S01-SH001", "S01-SH002", "S01-SH003"],
      "soundscape": "暴雨拍打铁皮雨棚的密集声，楼道口积水顺台阶往下淌",
      "music": "N/A",
      "notes": "单人戏，按单人替身法则处理：每镜具名锚点指向 CHR-01；本单元三镜分别对应剧本第 1 场 action 的三个节点（①空间 ②主体 ③状态），无空切"
    },
    {
      "unit_id": "U02",
      "scene_no": 2,
      "shot_ids": ["S02-SH001", "S02-SH002", "S02-SH003"],
      "soundscape": "电动车电机声、轮胎劈开积水的哗声、雨打头盔的密集声",
      "music": "N/A",
      "notes": "骑行段，单元内三镜运镜各不相同（tracking／pan_left／pedestal_up）"
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
      "shot_language": {
        "composition": "CHR-01 落在画面右三分，左三分之一是被雨帘遮住的楼道纵深，前景溅起的水花压住画面下缘",
        "axis": "空间轴：画面左＝楼道口（暗）、画面右＝街面（亮），整场不越此轴",
        "result": "雨水顺着袖口成股下淌，在脚边积出一小滩，又被新雨点打出密密的涟漪"
      },
      "action": {
        "start": "CHR-01 拎着外卖箱站在楼道口檐下，半边肩在雨里",
        "change": "侧身往墙里挪半步，耳机里跳出一声超时提醒",
        "end": "背贴墙面站定，视线压在手机屏上"
      },
      "lighting": "practical_light——楼道感应灯在下半张脸上打出一道硬边，街灯反光从积水面泛上来",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "ref_image": null,
      "dialogue": "还有六分钟。",
      "sfx": "雨砸铁皮雨棚声、外卖箱塑料提手摩擦声",
      "transition_in": "fade_in",
      "transition_out": "",
      "notes": "单人镜，用具名锚点指向 CHR-01；本镜对应 action 节点①（空间：街面→檐下）"
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
      "shot_language": {
        "composition": "构图极简，纸箱占画面下三分之一，上方是垂落的雨帘",
        "axis": "沿用本场空间轴（楼道内·街面外）",
        "result": "纸板被掀开，箱底蜷着一只后腿带血的猫，它抬了一下头"
      },
      "action": {
        "start": "视线压在手机屏上",
        "change": "脚边纸箱传来一声细弱的叫，他掀开湿透的纸板",
        "end": "看见一只后腿带血的猫蜷在箱底"
      },
      "lighting": "rim_light——雨丝在逆光里显形，纸箱边缘被勾出一道湿亮的光边",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "",
      "sfx": "纸箱里细弱的猫叫、雨声转低",
      "transition_in": "cut",
      "transition_out": "",
      "notes": "本镜对应 action 节点②（主体：发现道具）——猫入画，故 prop_refs 标 PRP-01；单人镜，用具名锚点"
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
      "shot_language": {
        "composition": "人与纸箱压在画面左下，右侧大片是空的楼道",
        "axis": "沿用本场空间轴（楼道内·街面外）",
        "result": "纸箱被往墙根挪了半尺，地上留下一道被拖出的湿痕"
      },
      "action": {
        "start": "站起，鞋已迈下台阶",
        "change": "停住，蹲回去把纸箱往墙根挪了半尺",
        "end": "重新站定，目光落在箱子上"
      },
      "lighting": "practical_light——感应灯把人的影子投到墙上，随下蹲的动作拉长",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "雨砸在铁皮雨棚上，像有人在替他数秒。",
      "sfx": "雨声、纸箱刮过水泥地的摩擦声",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "本镜对应 action 节点③（状态：离开→留下）；单元末镜，故填 transition_out；本镜不承载构图维之外的特别处理"
    },
    {
      "shot_id": "S02-SH001",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 1,
      "shot_size": "medium",
      "camera": {
        "move": "tracking",
        "amplitude": "",
        "speed": "fast",
        "from": "车侧后方半米、略低",
        "to": "追平车侧、与车身并行稳住",
        "height": "eye_level",
        "roll": "level",
        "optics": ""
      },
      "duration_ms": 6000,
      "shot_language": {
        "composition": "CHR-01 居中偏左，雨幕在镜头前拉成斜线，湿路面的反光占据画面下方三分之一",
        "axis": "空间轴：镜头始终在 CHR-01 右侧同一侧跟随，不换边",
        "result": "车轮劈开积水，水花向两侧甩出并溅上裤脚，反光带随车速被拉长"
      },
      "action": {
        "start": "单手扶把，另一只手按住怀里鼓起的一团",
        "change": "身体前倾压低，脚下一蹬加速",
        "end": "车身稳住，冲进前方雨幕"
      },
      "lighting": "neon_night——沿街招牌的暖光在湿路面上拖出长条反光，随车速拉长",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "",
      "sfx": "电机声、雨打头盔的密集声",
      "transition_in": "fade_in",
      "transition_out": "",
      "notes": "单人镜；猫在怀里入画，故 prop_refs 标 PRP-01；本镜不承载光学维；speed 取 fast 是**强调**加速，amplitude 为默认值故留空"
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
      "shot_language": {
        "composition": "红字与脸各占一半，画面被手机屏的光切成左右两块",
        "axis": "空间轴：手机恒在画面左、脸恒在画面右",
        "result": "一条一星差评从屏幕顶端弹入并停在正中，把红字压下去"
      },
      "action": {
        "start": "眼睛瞟向支架",
        "change": "视线在红字上停住，嘴角向下按",
        "end": "视线移开，落向怀里"
      },
      "lighting": "practical_light——手机屏的冷光自下而上打在脸上，与街灯暖光对撞",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "ref_image": null,
      "dialogue": "行，扣就扣吧。",
      "sfx": "提示音、雨声",
      "transition_in": "cut",
      "transition_out": "",
      "notes": "单人镜；本镜不承载角度维以外的特殊处理，光学取浅景深隔离屏幕与背景"
    },
    {
      "shot_id": "S02-SH003",
      "unit_id": "U02",
      "scene_no": 2,
      "shot_no": 3,
      "shot_size": "full",
      "camera": {
        "move": "pedestal_up",
        "amplitude": "",
        "speed": "slow",
        "from": "路边牙石高度、车轮与积水",
        "to": "升到平视，人与车停在路口的侧影整个入画",
        "height": "eye_level",
        "roll": "level",
        "optics": ""
      },
      "duration_ms": 6000,
      "shot_language": {
        "composition": "",
        "axis": "空间轴：路口灯柱恒在画面右缘",
        "result": "他把手机扣回支架，指节在支架上停了一秒才松开"
      },
      "action": {
        "start": "在路口短暂停车，低头看手机",
        "change": "视线转向怀里那一小团湿透的重量",
        "end": "抬手把手机扣回支架，重新拧动油门"
      },
      "lighting": "blue_hour 打底、neon_night 补边——雨后夜色的青蓝底子，被商铺霓虹补上暖边",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "他把差评留在了昨天的单里，把猫留在了今天。",
      "sfx": "雨声渐缓、远处车流涉水声",
      "transition_in": "cut",
      "transition_out": "dissolve",
      "notes": "单元末镜；视线转向怀里 — 猫入画，故 prop_refs 标 PRP-01；本镜不承载构图与光学维"
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
      "shot_language": {
        "composition": "CHR-01 在画面下三分之一居中，单元门洞是画面上方的暗方块，两侧绿化带做前景框",
        "axis": "空间轴：单元门恒在画面正上、通道恒在画面下",
        "result": "他把纸袋换到另一只手，脚下的湿砖上留下一个浅浅的转身印"
      },
      "action": {
        "start": "站在单元门外，怀里抱着纸袋",
        "change": "低头看了看怀里的纸袋，把它换到另一只手",
        "end": "上前半步，停在门铃前抬手"
      },
      "lighting": "overcast——清晨低饱和漫射光，墙面的潮痕与苔色都显出来",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "送东西的。",
      "sfx": "鸟叫、远处垃圾车、雨后滴水",
      "transition_in": "dissolve",
      "transition_out": "",
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
        "amplitude": "",
        "speed": "slow",
        "from": "门铃面板正前",
        "to": "绕到 CHR-01 侧后，把背影与门框一起收进画面",
        "height": "eye_level",
        "roll": "dutch",
        "optics": ""
      },
      "duration_ms": 6000,
      "shot_language": {
        "composition": "门框在画面左侧形成垂直边，CHR-01 的背影偏右，走廊深处是唯一亮处",
        "axis": "空间轴：门框恒在左、走廊纵深深处恒在画面中心",
        "result": "走廊声控灯亮起又灭掉，他脚边的影子跟着缩短又拉长"
      },
      "action": {
        "start": "手指悬在门铃上方",
        "change": "按下第一声铃",
        "end": "手收回身侧，肩膀绷住"
      },
      "lighting": "practical_light——走廊声控灯自上而下，把门框边缘照出一道白线",
      "character_refs": ["CHR-01"],
      "prop_refs": [],
      "ref_image": null,
      "dialogue": "",
      "sfx": "门铃两声、门内无人应答、灯管电流声",
      "transition_in": "cut",
      "transition_out": "",
      "notes": "单人镜；dutch 荷兰角外化「按铃时的失衡感」，move 未取滚转类故 roll 可填"
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
      "shot_language": {
        "composition": "猫蜷在画面中心，手指的边缘被压在画框下缘",
        "axis": "空间轴：门缝的光恒在画面上缘",
        "result": "焦点从门缝落到猫的颈侧，那里被指腹来回碾过两下"
      },
      "action": {
        "start": "视线停在门上",
        "change": "低头看向怀里的猫",
        "end": "指腹在猫颈上停了一下，像是在确认什么"
      },
      "lighting": "side_light——门缝里漏出的室内暖光从侧面切进来，把指节照出层次",
      "character_refs": ["CHR-01"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "门铃响了两声，没有人应，他就按了第三声。",
      "sfx": "门铃第三声、门内脚步声由远及近",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜；rack_focus 等于剪了一刀但没切镜头"
    },
    {
      "shot_id": "S04-SH001",
      "unit_id": "U04",
      "scene_no": 4,
      "shot_no": 1,
      "shot_size": "medium",
      "camera": {
        "move": "static",
        "amplitude": "",
        "speed": "",
        "from": "固定机位，门缝高度、平视",
        "to": "固定不动，仅在门开合时随门框轻微位移",
        "height": "eye_level",
        "roll": "level",
        "optics": "shallow_focus"
      },
      "duration_ms": 8000,
      "shot_language": {
        "composition": "门缝把画面纵向切开：CHR-02 在右（门内），CHR-01 在左（门外），两人各占一半",
        "axis": "对手戏屏幕方位：CHR-02 恒在画面右、CHR-01 恒在画面左，视线轴沿门缝相交",
        "result": "门缝从一条线开到一掌宽，走廊声控灯灭掉又亮起，两道光在门框上交替"
      },
      "action": {
        "start": "门只开了一条缝，CHR-02 的脸半藏在门后",
        "change": "CHR-02 低头看见猫，伸手把它抱过去，动作很轻",
        "end": "CHR-02 抬眼，正对上 CHR-01，两个人都在原地没动"
      },
      "lighting": "practical_light——走廊声控灯从 CHR-01 背后打来，把 CHR-02 的半张脸留在门内暗部",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "……它怎么会在你这儿。",
      "sfx": "门轴轻响、声控灯电流声、室外滴水",
      "transition_in": "fade_in",
      "transition_out": "",
      "notes": "对手戏：以门缝分侧做画面区隔（§3.4 禁止「同一层景深且无位置分工」）；静止镜内有门缝与灯光在变，不违「禁无结果的静止」"
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
      "shot_language": {
        "composition": "CHR-01 的脸压在画面下三分之二，门框上缘留出细窄的亮带",
        "axis": "沿用本场轴线：CHR-01 恒在左、CHR-02 恒在右（本镜 CHR-02 仅以虚化的门框边缘入画）",
        "result": "焦点从门缝滑到 CHR-01 的睫毛上，睫毛上挂着一滴没落下的水"
      },
      "action": {
        "start": "视线停在对方脸上",
        "change": "低下头，把视线移向怀里的手套",
        "end": "手指在身侧收拢，肩膀塌下去"
      },
      "lighting": "rim_light——走廊残光勾出 CHR-01 的侧脸轮廓，正面几乎无光",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": [],
      "ref_image": null,
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
      "shot_language": {
        "composition": "沙发与窗分列画面左右，中间是空着的大片地板，猫在两者之间挪动",
        "axis": "对手戏屏幕方位：CHR-02 恒在画面左（沙发侧）、CHR-01 恒在画面右（窗侧），视线轴横贯画面",
        "result": "猫从坐垫上挪了两步，把自己搁在两人之间的地板上，尾巴慢慢收拢"
      },
      "action": {
        "start": "CHR-02 把猫放在两人之间的坐垫上",
        "change": "CHR-02 起身去倒水，CHR-01 没有坐",
        "end": "CHR-01 站在窗边，手插在口袋里"
      },
      "lighting": "soft_key_light——清晨窗外漫射光从 CHR-01 背后进来，在室内形成大面积柔和过渡",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "坐吧。它认你。",
      "sfx": "挂钟走针、猫爪在坐垫上的窸窣",
      "transition_in": "cut",
      "transition_out": "",
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
        "roll": "level",
        "optics": ""
      },
      "duration_ms": 5000,
      "shot_language": {
        "composition": "CHR-01 在画面右三分之一，左侧留出通往沙发方向的室内纵深",
        "axis": "沿用本场轴线：CHR-02 在左、CHR-01 在右",
        "result": "他松开插在口袋里的手，绕过猫，坐到坐垫边缘，坐垫陷下一道褶"
      },
      "action": {
        "start": "站在窗边不动",
        "change": "转身，绕开地板上的猫，走向画面左侧",
        "end": "坐到坐垫边缘，肩膀放松下来"
      },
      "lighting": "soft_key_light——窗前光把 CHR-01 的影子投在地板上，随他走动移过猫的身体",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "那……我坐。",
      "sfx": "布料摩擦、挂钟走针",
      "transition_in": "cut",
      "transition_out": "",
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
        "amplitude": "",
        "speed": "",
        "from": "固定机位，客厅全景、平视略高",
        "to": "固定不动",
        "height": "high",
        "roll": "level",
        "optics": ""
      },
      "duration_ms": 5000,
      "shot_language": {
        "composition": "两个人和猫落在画面下三分之一，上方三分之二是窗与天亮",
        "axis": "空间轴：窗恒在画面右、门洞恒在画面左",
        "result": "窗外天色由青灰转为浅白，屋里的影子边缘跟着变软"
      },
      "action": {
        "start": "两个人各坐坐垫一端，猫在中间",
        "change": "谁都没有开口，只有光在变",
        "end": "屋里的东西各自停在自己的位置上"
      },
      "lighting": "overcast——清晨漫射光均匀铺开，室内没有硬阴影",
      "character_refs": ["CHR-01", "CHR-02"],
      "prop_refs": ["PRP-01"],
      "ref_image": null,
      "dialogue": "窗外天亮了，屋里没人急着说话。",
      "sfx": "挂钟、窗外早市远景、猫的呼吸",
      "transition_in": "cut",
      "transition_out": "fade_out",
      "notes": "单元末镜兼全片末镜；静止镜内有光在变，不违「禁无结果的静止」；本镜不承载光学维"
    }
  ],
  "forbidden_items": [],
  "unspecified": [
    {"field": "shots[].dialogue", "upstream_field": "characters[0].name", "reason": "客户未提供主角姓名，剧本层未闭合；本层仅在对白中以身份代称呈现，未获得可写进台词的姓名", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层向客户追问；确认前对白一律以身份代称（『外卖员』），本层不得自拟姓名——不闭合亦可交付（全片无一处需要写出姓名）", "blocking": false},
    {"field": "shots[].dialogue", "upstream_field": "characters[1].name", "reason": "客户未提供妹妹姓名，剧本层未闭合；同上", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层向客户追问；确认前对白以身份代称（『住所女主人』）——不闭合亦可交付", "blocking": false},
    {"field": "shots[].dialogue", "upstream_field": "ending.resolution", "reason": "客户只说『多年』，未给具体年数；剧本层未闭合，本层故未在任何镜的台词中写具体数字", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层向客户追问；确认前对白一律用『好几年』这类模糊说法——不闭合亦可交付", "blocking": false},
    {"field": "units[].notes", "upstream_field": "conflict.internal", "reason": "客户未说明两人当年为何失联；本层只呈现『疏远』的结果，未在单元注释中解释原因", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层向客户追问；确认前只呈现疏远结果、不解释原因——不闭合亦可交付", "blocking": false},
    {"field": "shots[].character_refs", "upstream_field": "characters[0].appearance_lock_zh", "reason": "客户未提供主角外形，剧本层已提出候选，尚待客户确认；本层只引用 `CHR-01`、不落外观文字，故确认与否不影响本层产物", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层提请客户确认；确认前剧本层候选即全片默认锚，本层照常引用——不闭合亦可交付；若客户否决须回剧本层重出，届时本用例的 `prop_refs`／`character_refs` 引用不变", "blocking": false},
    {"field": "shots[].character_refs", "upstream_field": "characters[1].appearance_lock_zh", "reason": "客户未提供妹妹外形，剧本层已提出候选，尚待客户确认；本层同样只引用 `CHR-02`", "owner": "客户", "fill_stage": "script", "fill_fallback": "同上，剧本层候选为该角色默认锚——不闭合亦可交付", "blocking": false},
    {"field": "style_ref", "upstream_field": "style_bible.style_prompt_zh", "reason": "客户未提供全片视觉风格，剧本层已提出候选风格串，尚待客户确认；本层恒引用 `STYLE-01`，不重述风格内容", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层提请客户确认；确认前该风格串为全片默认锚，本层与 SW-007 均照常引用——不闭合亦可交付", "blocking": false},
    {"field": "shots[].prop_refs", "upstream_field": "props[0].appearance_lock_zh", "reason": "客户未提供猫的品种与外观，剧本层已提出候选（上游梗概无道具字段，属剧本层新产生的缺口）；本层只引用 `PRP-01`、不描写道具外观", "owner": "客户", "fill_stage": "script", "fill_fallback": "由剧本层提请客户确认；确认前该候选即全片默认道具锚——不闭合亦可交付；若客户否决须回剧本层重出，本层引用关系不变", "blocking": false},
    {"field": "units[4].music", "upstream_field": "", "reason": "客户未提供音乐方案；剧本层无音乐字段，本项为**本层新产生的缺口**——本层按收束段节奏提议了配乐织体，尚待客户确认", "owner": "客户", "fill_stage": "storyboard", "fill_fallback": "由本层向客户追问；确认前 4 个单元沿用 `N/A`、U05 按本层所提织体（单音符钢琴，间隔 3–4 秒一次）执行；客户若否决，改为整片统一 `N/A` 或替换织体——不闭合亦可交付", "blocking": false}
  ],
  "quality_gate": {
    "shot_count": 14,
    "static_shot_count": 2,
    "move_types": ["arc", "pan_left", "pan_right", "pedestal_up", "pull_out", "push_in", "static", "tilt_down", "tracking", "truck_right"],
    "self_check": "运镜覆盖 14/14=100%、景别覆盖 14/14=100%；静止镜 2/14=14%（上限 40%，允许 max(1,ceil(0.40×14))=6 个）；运镜类型 10 种（下限 min(5,max(2,⌈14/4⌉))=4 种）；单一运镜最多为 push_in 3/14=21%（上限 35%，允许 5 个）；角度覆盖 14/14=100%（≥40%）；光学覆盖 9/14=64%（≥30%）；构图覆盖 13/14=93%（≥50%）；轴线覆盖 14/14=100%（≥30%，对手戏镜强制已满足）；光线覆盖 14/14=100%（≥40%）；画面结果覆盖 14/14=100%（≥60%）。逐单元复算（U01–U05）：成员数分别为 3/3/3/2/3，均在 [2,3]；单元内运镜类型无重复；3 镜单元运镜类型数 3 ≥ 下限 2、2 镜单元 2 ≥ 下限 2。11 项全部通过。"
  }
}
```

## 4 评测结论

对照 SW-006 的验收标准：**「每个场景镜头完整、参数可读」**；并叠加规范 §4.1–§4.6 的镜头语言质量口径与三条链路接缝。

| # | 评测项 | 手段 | 结论 |
| --- | --- | --- | --- |
| 1 | 场景镜头完整 | 5 场是否都有镜头、每镜字段是否齐备 | ✅ 5 场均切镜（3/3/3/2/3 共 **14 镜**），`shots` 顶层字段每镜齐备 |
| 2 | 参数可读（字段值合法） | 枚举类字段逐项核对 | ✅ 景别取六值之一、运镜取 20 类之一、角度／滚转／光学均取规范词表值；无自造中文词（脚本校验：`validate_output.py`） |
| 3 | `character_id` 零漂移 | `character_refs` 与剧本 `characters` 比对 | ✅ 只出现 `CHR-01` / `CHR-02`，无改号、无新增角色 |
| 4 | 场号承接 | `shots[].scene_no` 集合与剧本 `scenes[].no` 比对 | ✅ 同为 `{1,2,3,4,5}`；`units[].scene_no` 一一对应；切镜只在场内部进行 |
| 5 | `style_ref` 承接 | 是否等于剧本 `style_bible.style_id` | ✅ 恒为 `STYLE-01`，全片唯一 |
| 6 | **本层不越权（外观）** | ① 逐镜语义字段是否含**锚内**外观特征词（**脚本 R23**：角色与道具 `appearance_lock_zh` 的 3-gram 比对）；② 是否重定义风格 | ✅ 脚本判定：14 镜语义字段**均未重述外观锚**（比对 3 个锚）。⚠️ **如实认领：本项在 v2.1.0 前是「人工判定且判错」**——旧版用例有 4 镜出现锚内字串（`S01-SH001`「冲锋衣／反光条」、`S02-SH001`／`S05-SH001`「冲锋衣」、`S03-SH003`「磨花的」），旧自评却判「✅ 全文未出现」，**与原文冲突**。已按 `BR-02` 修正并**落成脚本判据 R23**。⚠️ 残余：「**锚外**新增外观描写」仍属人工判据（见第 19 项） |
| 7 | 单元构成 | `units[].shot_ids` 长度与成员归属、镜序 | ✅ 长度分别为 3/3/3/2/3，全部落在 **[2,3]**；无 1 镜单元；每镜 `unit_id` 双向命中；`shot_ids` 按镜序递增（R9 增补） |
| 8 | 单元内运镜不重复 | 逐单元比对 `camera.move` | ✅ U01 push_in/tilt_down/pull_out；U02 tracking/pan_left/pedestal_up；U03 push_in/arc/tilt_down；U04 static/push_in；U05 pan_right/truck_right/static |
| 9 | **质量门 11 项** | 按 `audit_shots.py` 的 `GATE` 与容差算法逐项复算 | ✅ 11 项全通过（14 镜）；类型数 10 ≥ 4、静止 2 ≤ 6、单一最多（push_in）3 ≤ 5 |
| 10 | **质量门自声明与复算一致**（`BR-10` 新增） | `quality_gate` 的 **3 个数值字段**（`shot_count`／`static_shot_count`／`move_types`）vs 由 `shots` 复算的真值 | ✅ 逐项一致（脚本 R25）。**此前无此判据**——模型可写「11 项全通过」而无人比对；现填错即报错 |
| 11 | 时长口径 | `total_duration_ms` vs Σ vs 剧本 81s | ✅ Σ = 5+5+5+6+6+6+6+6+6+8+7+5+5+5 = **81000ms = 81 秒**，与剧本 `total_est_seconds` **零偏差**；全部为整秒且落在 4–15 区间 |
| 12 | 台词—时长（语速） | 逐镜台词字数 ÷ 秒数 ≤ 9 | ✅ 最长一处为 S02-SH003：22 字 ÷ 6s ≈ 3.7 字/秒，远低于 9 |
| 13 | **台词守恒** | 剧本 11 条台词逐条追踪 | ✅ 11 条全部落到 14 镜中的 11 镜，顺序未打乱，无丢失、无新增（含 4 条旁白） |
| 14 | **动作守恒**（`BR-03` 新增，本版最要紧的一条） | 逐场把剧本 `action` 拆成节点清单，核对每个节点是否落到某镜的 `action.change`／`shot_language.result` | ✅ 5 场节点数 3/3/3/3/3，**每个节点均有对应镜**。第 1 场 3 镜分别对应 ①空间（避雨）②主体（**发现猫**）③状态（离开→留下）。⚠️ **如实认领：本项在 v2.1.0 前是空洞**——旧版第 1 场只有 2 镜（躲雨抹脸／抬头看楼），**beat「发现受伤的猫」一镜都没有**，而台词一句没丢，故所有守恒判据都「通过」。已按 `BR-03` 补齐 |
| 15 | 转场单侧表达 | 相邻镜衔接是否只写一次 | ✅ 单元**内部**由后一镜 `transition_in` 表达；`transition_out` 只出现在 5 个单元末镜。**单元边界＝前一单元末镜的出点 + 后一单元首镜的入点（两个半段）**，按 `BR-07` 明确的口径**不算「两头都写」** |
| 16 | 声音口径 | `soundscape` / `music` 是否有值、`music` 是否含抽象情绪词 | ✅ 5 个单元均有 `soundscape`；`music` 4 个为 `N/A`、1 个为具体织体描述（「单音符钢琴，间隔 3–4 秒一次」），**无抽象情绪词**；该织体已按 `BR-04` 口径在 `unspecified` 登记来源 |
| 17 | 单人替身法则与两条禁律 | 单人镜是否具名锚点；§4.4 两条禁律的**适用范围** | ✅ 4 个单人单元均以具名锚点指向 CHR-01；2 个静止镜（`S04-SH001` 对手戏 / `S05-SH003`）均写了「在动的东西」（门缝与灯光的交替／天色转白），无空镜。**按 `BR-13` 与规范原文对齐：两条禁律适用于「所有静止／无人戏镜头」，不限单人戏**——本用例的对手戏静止镜正是按全局口径处理的 |
| 18 | 禁止项承接 | `forbidden_items` 与剧本比对 | ✅ 剧本为空数组，输出同为 `[]`——**空数组的承接同样算通过** |
| 19 | **道具承接** | ① `prop_refs` 是否只引用已定义 `prop_id`；② 是否越权描写道具外观；③ **某场 `props_present` 非空时该场至少要有一镜标出**（**脚本 R24**） | ✅ `prop_refs` 全片只出现 `PRP-01`（已定义，无新增道具、无悬空引用）；14 镜中 **10 镜**标 `PRP-01`（U01 2 ／ U02 2 ／ U03 2 ／ U04 1 ／ U05 3），其余 4 镜为空数组。脚本 R24：**5 个有道具的场均有镜头把道具标出**。⚠️ **如实认领：本项在 v2.1.0 前有 2 场（第 1、2 场）整场漏标**——第 1 场因「发现猫」的镜头被删而连带漏标，第 2 场猫在怀里却标空数组。已按 `BR-03` 补齐并**落成脚本判据 R24**。外观描写：脚本 R23 判**未重述锚**；「**锚外**新增外观描写」属人工判据、**暂无可靠脚本判据**（旧版 `S03-SH003`「磨花的宠物牌／划痕／洗不掉的旧泥」即此类，已删除） |
| 20 | **缺口续接与责任归属** | ① 剧本 `unspecified`（8 项）逐项追踪；② 每条 `owner` 与 `fill_stage` 是否合规；③ `upstream_field` 是否能映射回剧本真实字段 | ✅ 8 项**全部保留**，且 `owner` 一律为「客户」、`fill_stage` **一律为 `script`**（**不得前移**）；`upstream_field` 8 条**逐条命中**剧本 `unspecified[].field` 真值（`characters[0].name`／`characters[1].name`／`ending.resolution`／`conflict.internal`／`characters[0].appearance_lock_zh`／`characters[1].appearance_lock_zh`／`style_bible.style_prompt_zh`／`props[0].appearance_lock_zh`），无悬空路径。另新增 **1 项本层缺口**（`units[4].music`，`upstream_field` 为空串、`fill_stage=storyboard`——由本层发起追问），共 **9 项** |
| 21 | `owner=客户` 不得前移（负向判据） | 逐条断言 `fill_stage != shot_prompt` | ✅ 9 项中 `owner=客户` 者 9 项，`fill_stage` 取值集合为 `{script, storyboard}`，**`shot_prompt` 零出现**（脚本校验：`validate_output.py` R21 的 storyboard 分支） |
| 22 | 内容质量 | 人工阅读（镜头语言是否丰富、是否有真重复动作、**每镜是否都带新信息**） | ⚠️ 人工判定「丰富且不重复」，但**未脚本化、亦未经模型验证**，不计入通过项 |

**本用例的针对性设计**：八项陷阱位。

1. **越权陷阱（外观重述）**——剧本层已把外观、风格与道具定义完毕，本层最易犯的错是「顺手在每镜里重新描写一遍外观」。用例把「逐镜语义字段不出现外观锚字串」设成刚性项（第 6 项），并**已落成脚本判据 R23**（外观锚 3-gram 比对）。⚠️ **本陷阱位曾被我方自评判错**——旧版有 4 镜命中却自判「未出现」，这正是 `BR-02` 所指「尺子比被量的东西先失效」。
2. **切镜依据陷阱**（`BR-01` 新增）——模型容易把「每单元 2–3 镜」读成「每场至少切两刀」，凑出「机位乱换但没讲新东西」的镜头。用例要求**每个切点都对应 `action` 的一个新信息节点**；相邻两镜只差距离或轻微角度即应合并为一次运镜（第 14、22 项）。
3. **动作守恒陷阱**（`BR-03` 新增）——**本用例最硬的一处**：第 1 场是全片起点，其 beat「发现受伤的猫」是唯一的第一推动。旧版把它整个丢掉（13 镜里一镜都没有），而台词一句没丢，**所有守恒判据全部「通过」**。用例把「每场 `action` 的每个节点都要落到某镜」设成刚性项（第 14 项）。
4. **道具漏标陷阱**（`BR-03` 新增）——「剧本说它在场、分镜一镜都没拍到」是纯文本校验查不出的漏拍。用例把「某场 `props_present` 非空则该场至少一镜标出」设成刚性项并**落成脚本判据 R24**（第 19 项）。
5. **单元陷阱**——模型天然倾向于按「一个动作一镜」切，容易切出 1 镜单元或 4 镜以上单元；也容易在一个单元里连续用同一种运镜。用例把「2–3 镜」与「单元内不重复」设成刚性项（第 7、8 项）。
6. **静止陷阱**——收尾镜最容易被写成「空镜」；用例在 `S04-SH001` / `S05-SH003` 刻意用静止镜，验证「静止镜 ≠ 空镜」这条口径被真正执行（第 17 项）。
7. **覆盖率陷阱**——八维**不是每镜全开**（规范 §4.3「单元级达标」）。用例刻意让 `optics` 只覆盖 9/14、`composition` 覆盖 13/14，用于验证「覆盖率门槛」口径**没有被误读成「每镜必须八维全开」**，也没有被误读成「可以为空」（第 9 项）。
8. **缺口责任陷阱**（`SR-02` 新增）——剧本层的 8 项缺口全部是「客户未提供」，最容易被写成「留给下一层去问客户」。用例把 `fill_stage` 的取值集合设成硬判据：**继承的客户缺口必须保持 `script`、本层新产生的客户缺口只能填 `storyboard`，`shot_prompt` 一律不许出现**（第 20、21 项）。

## 5 验证状态

**未验证。** 理由：

1. 输出为人工构造，未经模型实测 —— 按项目纪律不得标为已通过；
2. 第 1–21 项目前为人工比对，其中第 2、3、4、7、8、9、10、11、12、15、16、18、21 项已可由 `validate_output.py` 自动核查；**第 6 项（外观锚重述，R23）与第 19 项③（道具覆盖，R24）为 v2.1.0 新增的跨层规则**，第 10 项（质量门自声明复算，R25）亦为 v2.1.0 新增；⚠️ **v2.2.0 起** `move_type_min_required` **移出模型声明范围**（它是由镜数推导的阈值，属交付前脚本复算的统计量），故第 10 项只比对 3 个字段 —— 一旦有产物填了它，`R25` **仍会比对**（判据未改，只改了模板不再诱导填）。**第 14 项（动作守恒）与第 19 项②（锚外新增外观描写）暂无脚本判据**，属**待补**项。
3. 用例来源为构造，非真实客户素材。

**闭环条件**（三项齐备后方可改判「已实测」）：

- [ ] 在 Qwen2.5-7B-Instruct 上跑通本用例，回填真实输出与采样日志（**待模型就绪后统一执行**）
- [ ] 把第 1、6、13、14、17 项落成校验脚本，产出机器可读报告（与 `validate_output.py` 同源）；
      **第 14 项「动作守恒」缺可靠脚本判据**（需把上游 `action` 散文拆成节点，属开放式 NLP，宜先做半自动：人工列节点、脚本核覆盖）；第 19 项②（锚外新增外观描写）同属待补
- [ ] 补一组脱敏真实客户素材用例（`CASE-STB-002`）

> ⚠️ **一项已知的口径差异（须在实测时留意）**：本用例的覆盖率是按**结构化字段是否有值**判定的；而 `audit_shots.py` 是按**适配投喂文本**（SW-007 的产物）用正则判定的。两者对象不同——本层判定通过**不等于**下游文本判定通过。SW-007 完成后必须对文本再跑一次质量门（规范 §4.8）。

---

*记录性质：用例与评测留痕　｜　建立 2026-10-13（随 `storyboard_v1` v1.0.0）　｜　保留原则：永久保留，模板升版后本用例不删除、另建新用例*
