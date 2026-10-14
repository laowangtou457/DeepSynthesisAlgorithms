# ============================================================
# 提示词模板 · 结构约定说明
# ============================================================
# 本目录所有模板遵循统一结构，便于工程加载与备案说明。
#
# 【字段说明】
#   id          唯一标识，与 CFG-008_manifest.yaml 一致
#   name        中文名称
#   version     版本号（主.次.修订），修改必须升版本
#   task_type   generate | summarize | rewrite | extract | guard
#   stage       业务链路阶段（仅 AI 漫剧业务链路模板填写，其他模板留空）：
#                 synopsis | script | storyboard | shot_prompt | revise
#               —— 与《分镜提示词交付规范 **v2.0**》§3.2 的 stage_chain 枚举对齐
#                  （2026-10-14 三次更新：v1.1 → v1.2 → v1.3 → **现行版 v2.0**；v2.0 为**结构变更**——
#                    §3.1 顶层 六段 → **八段**（增 `props[]`／`forbidden_items`）、§3.6 增 `prop_refs`、
#                    §3.7.6 长度建议值上修；**§3.2 的 stage_chain 枚举本身未变**。规范正文现由
#                    `01-架构设计/SPEC-005_分镜提示词交付规范-v2.0.md` 承载，`SPEC-004` v1.3 及更早保留不删），
#                  用于下游按链路顺序编排模板、并写入交付包的 generation_trace.stage_chain
#   —— 业务链路模板的「锚点首定义」约定（2026-10-13 定案，经导演视角两轮评审）：
#       ① 角色外观（age_band / appearance_lock_zh）、全片风格串与道具／关键物件外观（props）
#          的**首次定义责任在剧本阶段**（stage=script，SW-005）；梗概阶段（stage=synopsis，SW-004）
#          只做「占位 + 缺口登记」，不得越权定义、不得编造——凡客户未提供者一律写「未指定」并登记进 unspecified。
#       ② 角色稳定标识 character_id 由链路最上游（synopsis）分配，全链路不得改号——
#          name 可为「未指定」，character_id 不可为空。
#       ③ 下游各阶段的 scene_no 一律沿用 synopsis 模板 scenes_outline 的 no，不得重新编号。
#       ④ 剧本阶段（stage=script，SW-005）承接①并「落地」：synopsis 只做占位与缺口登记的角色外观
#          （age_band / appearance_lock_zh）、全片风格串（style_bible）与道具／关键物件外观（props），
#          在剧本层**首次定义**——客户未提供时由本层提出具体候选、标来源「系统提议待确认」并登记台账，
#          **不得照抄「未指定」**（照抄等于把缺口原样抛给下游，下游将无锚点可用）。
#          ⚠️ **设计类的判定用「规则式」，不用枚举清单**（2026-10-13 依 `SR-05` 修订）：
#             **凡 output 中带 `design_source` 字段的值即为设计类**——枚举清单会漏，
#             `voice`（声线）与「道具／关键物件外观」都曾漏在清单之外，导致这类字段归属无主、
#             模型行为不可预测、校验脚本无法判定其合规性。
#          来源标注**分两层、不得合并**（依 `SR-10`）：`source` 记**承继类**（name／role／identity，
#             取值 客户提供｜承继上游）；`design_source` 记**本层首定义的设计类**
#             （age_band／appearance_lock_zh／voice，以及 style_bible、props 各元素，
#              取值 客户提供｜系统提议待确认）——合并标注会把「承继的上游事实」与「本层新生成的设计」
#              混为一谈，使备案举证无法区分「哪些内容来自客户、哪些是系统生成的」。
#          另：剧本层只做「剧本化编排」，**不做镜头切分**——切镜属分镜脚本阶段（stage=storyboard，SW-006）。
#       ⑤ 分镜脚本阶段（stage=storyboard，SW-006）是**导演决策层**：决定「切几刀、每刀切在哪、每一镜怎么拍」；
#          职责边界四条（第四条 2026-10-13 依 `BR-01`~`BR-13` 评审补充）——
#            · **不定义外观与风格**（首定义在剧本层）、**不重述外观细节**，只引用 style_ref、character_refs
#              与 prop_refs（道具锚，2026-10-13 随剧本层新增 props[] 一并承接）；
#              ⚠️ **边界的判据**：锚串（`appearance_lock_zh`）里的**字串**不得出现在逐镜语义字段
#              （action.*／shot_language.*／camera.from|to／notes）——承接 action 里的**动作对象**可以，
#              写外观**特征词**（颜色／材质／饰件／磨损／款式）不可以；逐镜语义字段只写**瞬时状态**。
#              该判据已脚本化（validate_output.py **R23**，3-gram 比对，需 `--script` 提供上游）；
#            · **不写 prompt_zh／prompt_en 正文、不做模型适配、不写 AIGC 元数据块**——那些属 SW-007（编译表达层）；
#            · 字段名与《分镜提示词交付规范》§3.5（units[]）／§3.6（shots[]）**逐字对齐**，
#              使 SW-007 的适配从「重新设计」降级为「格式投影」。
#              ⚠️ **但本层产出是该字段集的「真子集」**（依 `BR-09` 修正）：镜头级 `style_ref`（规范标必须、
#              §3.8 列阻断）、`prompt_zh`／`prompt_en`（必须）、`aspect_ratio`（应当）、`negative_prompt`（可）
#              均**不在本层产出**，须由 SW-007 补齐——不得把「逐字对齐」读成「投影＝拷贝」；
#            · **双守恒**（依 `BR-03`）：台词守恒**加**动作守恒——剧本每场 `action` 的每个节点都要落到
#              某一镜的 action.change／shot_language.result 上；只保住台词而丢了动作是最隐蔽的失败。
#            · **切镜依据**（依 `BR-01`，规范 §4.1 为「必须」）：每个切点必须踩在一个新信息节点上；
#              相邻两镜只差距离或轻微角度时应合并为一次运镜而不是切镜。
#          八维覆盖为**两层口径**（依规范 §4.1／§4.3）：景别／运镜**每镜必有**；
#            角度／光学／构图／轴线／光线／画面结果六维按 §4.2 覆盖率阈值在**单元与整片层面**达标，
#            **不要求每镜八维全开**。镜号 shot_no 与单元编号 unit_id 由本层首次分配。
#          11 项质量门阈值与容差算法直接引用参照实现 `audit_shots.py` 的 `GATE`（不得另立一套）。
#          ⚠️ **11 项须二分**（依 `BR-12`）：**结构性约束**（单元镜数 ∈[2,3]、单元内运镜不重复、
#            `static`／`pov` 不带幅度速度、景别／运镜每镜必有、单场镜数 ≤⌊场秒数÷4s⌋）写进生成约束、必须满足；
#            **统计性阈值**（覆盖率／占比／类型数）是全片/全单元统计量，模型写第 k 镜时无从知道自己是否越限，
#            写进生成约束只换来一份失真的自查声明——故标注为「交付前脚本复算」，
#            `quality_gate` 的数值字段降为**可选参考**（填写即须与复算一致，见 R25）。
#
#       ⑥ 分镜提示词阶段（stage=shot_prompt，SW-007）是**编译表达层**：SW-006 决定「切几刀、切在哪、
#          每镜怎么拍」，本层决定「**怎么把这些决策写成目标模型读得懂的话**」。一句话边界——
#          **不改变任何导演决策，只把决策翻译成表达并补全结构**。
#          职责边界五条（2026-10-13 随 `shot_prompt_v1` 建立）：
#            · **承继守恒**（本层第一条纪律）：`shot_id`／`unit_id`／`scene_no`／`shot_no`／
#              `units[].shot_ids`／`duration_ms`／`shot_size`／`camera.*`／`action.*`／`shot_language.*`／
#              `dialogue`／`sfx`／`transition_*`／`character_refs`／`prop_refs`／`soundscape`／`music`
#              一律**原样承继**。**尤其不得改 `duration_ms`**——它是导演决策，也是与 `total_duration_ms`
#              一致性的凭据；若台词语速超标，那是上游缺陷，须回退剧本层／分镜层，不得在本层悄悄改秒数。
#              该纪律已脚本化（**R31**，逐镜比对需 `--storyboard`）。
#            · **补出必填字段**：SW-006 的产出是规范字段集的**真子集**，镜头级 `style_ref`（规范标必须、
#              §3.8 列阻断项）、`prompt_zh`／`prompt_en`（必须）、`aspect_ratio`／`negative_prompt`（应当／可）
#              均由本层补齐。**这是 SW-007 存在的理由**（**R27**）。
#            · **双上游**（本层独有）：分镜层只给**引用**、锚的**内容**在剧本层，故本层是全链路唯一
#              需要两份上游的一段——`script_json` 出**锚**（character_id／character_refs 所指的外观与声线）、
#              `storyboard_json` 出**决策**（镜序／景别／运镜／时长／action 落点）。
#            · **八维双落地**（规范 §4.1）：每个维度须**同时** ① 有字段承载 ② 写进 `prompt_zh`／`prompt_en`
#              **正文**——模型读到的是文本，不是字段。八维落点承自 SW-006，本层只负责「写进正文」。
#              ⚠️ 与规范 §3.7.6 的**旧**长度建议（40–120 字）曾有张力——该张力已由 **v2.0 上修**
#                 （中文 **90–280 字** / 英文 **450–1200 字符**）化解；实测长镜 150–260 字**落在新建议区间内**。
#            · **不做模型适配**（刻意边界）：规范 §6.1「基准唯一 + 单向投影」＋§6.3「语言倾向不得覆盖
#              模型硬约束」＋§6.1「配置化：新增模型＝改 `CFG-001_model_adapters.yaml` 不改代码」——
#              把适配写进模板，等于每接一个模型就要改一次提示词。适配在交付后的服务层完成。
#          **三处必要改写**（全链路唯一允许「不逐字承继」的地方，须在 `meta.notes` 留痕）：
#            ① `lighting`／`lighting_default` 的「词表值 + 中文光位说明」形态须**拆分**——字段取**纯词表 code**，
#               说明移入 prompt 正文；上游若给了词表外的描述性说法，按语义映射到最近词表值并写明（禁自造 code）。
#               该校验见 **R32**。
#            ② `notes` 须**删除内部标注**（如「本镜对应 action 节点①」——那是给编制者看的，不是给模型看的）。
#            ③ `camera.amplitude`／`camera.speed` 若为 `medium`／`normal`，**规范化为空串**（语义无损等价）。
#          **交付包无 `unspecified` 字段**（规范 §3.1 顶层**八段**无台账段）：本层**不输出、不搬运、不重编号**
#          缺口台账——上游台账留在上游产物自身；本层的映射与回退说明写进 `meta.notes`。
#          **分段策略**：`segment` 变量三粒度——`all`（整包，仅短片）／`package_head`（只出
#          `schema_version`+`meta`+`style_bible`+`characters`+`aigc_meta`）／`unit:<unit_id>`（只出该单元与其成员镜）。
#          **按「生成单元」切而非按字数硬切**——规范 §3.5 明写「生成单元＝一次生成调用所提交的完整分镜块」，
#          故**分段粒度与业务语义粒度一致**（按字数硬切会产生「半句话的镜头」）。
#          **元数据不得编造**：`pack_id`／`created_at`／`session_id`／`task_id`／`statement_id`／
#          `provider_code`／`compliance.*` 一律取自服务层注入的 `pack_meta`；缺失写占位符
#          （`{{PROVIDER_CODE}}` 等），**不得自拟**——自拟会使「编号 → 生成记录」的反查断链（规范 §5.2）。
#
#   ★ **设计类来源在分镜层的判定口径**（依 `BR-04` 写明，不留空白）：
#       本层（storyboard）的产出**不属 SCHEMA 意义上的设计类内容**——本层是导演决策层，产出的是
#       「怎么拍」（切点／镜号／景别／运镜／八维落点／时长），属**技艺表达**而非**内容设计**；
#       SCHEMA 的设计类指**内容性设计**（角色外观／全片风格串／道具外观），其**首定义责任在剧本层**。
#       **唯一例外**：本层若自主提议了具体配乐织体（`units[].music` 非 `N/A`），该项属本层新产生的设计内容
#       → 按既有机制在 `unspecified` 台账登记来源（`owner=客户`／`fill_stage=storyboard`／`upstream_field` 空串），
#       **不新增 `design_source` 字段**。✅ **已定案（2026-10-13，`ISSUE-007` 闭环）**：规范 §3.5 的
#       `units[]` **不增设**该字段（理由与触发条件见 `12-项目管理/PM-001_任务清单.md` §8 的 ISSUE-007 行）。
#
#   ★ **设计类来源在提示词层的判定口径**（2026-10-13 随 `shot_prompt_v1` 写明）：
#       本层（shot_prompt）**不新建任何设计类内容**——它是编译表达层，角色外观／全片风格串／道具外观
#       一律**搬运**上游（剧本层）已定义的锚，`style_bible` 与 `characters[].appearance_lock_*` 逐字承继。
#       故本层产出**不涉及 `design_source`**，也不在交付包内登记缺口台账（见 ⑥ 末段）。
#
#   —— 产物契约的静态校验见同目录 validate_output.py（**R1~R36 共 36 条**：
#      梗概/剧本层 9 条 + 分镜层 13 条 + 交付包层 11 条 + 跨层 3 条（R23／R24 需 `--script`，
#      R31 需 `--storyboard`）+ 通用 1 条，
#      含 purpose 封闭枚举、dialogue.type 枚举、缺口台账 owner 责任归属、11 项镜头语言质量门、
#      外观锚重述检测（R23）、道具覆盖检测（R24）、质量门自声明复算（R25）、
#      运镜幅度／速度省略规则（R26）、交付包必备结构（R27）、外观复用检测（R28）、
#      提示词正文卫生（R29）、AIGC 元数据块规则（R30）、时长守恒（R31）、光照词表纯度（R32）、
#      交付包留空口径（R33）、英文运镜句独立成句（R34）、**道具锚一致性**（R35，v2.0 起由
#      「`prop_refs` 禁入」**反转为正向判据**）
#      与**契约外字段禁入**（R36，字段集直接读交付 schema，不另立清单））。
#      ⚠️ **负向验证纪律**：只跑通过样本证明不了校验器有效——新增规则必须构造越界样本验证能触发。
#         R26~R36 已逐条验证（**32 个越界样本全部 EXIT=1；3 个已知盲区**登记在案，见 R31／R33 条目；
#         脚本落点 `tests/negtest_pack_rules.py`，可复现）。
#   variables   变量清单，加载时校验必填项
#   sampling    推荐采样参数（服务层默认值，可被请求覆盖）
#   sections    提示分节，按固定顺序拼装：
#                 system   角色、能力边界、禁止事项
#                 task     任务定义与目标
#                 context  上下文素材占位
#                 output   输出约束（格式/长度/语气）
#                 examples 少样本示例
#               —— 顺序固定，不可调换，避免素材被误当指令
#   guards      运行时追加的约束（按失败模式定向加工）
#   fallback    信息不足或异常时的兜底行为
#
# 【拼装规则】
#   服务层按 sections 顺序渲染，每节以固定标记符包裹：
#     <|system|> ... <|/system|>
#     <|task|>   ... <|/task|>
#   素材类内容一律置于 context 节，不进入 system/task 节。
#
# 【模板语法】
#   {variable}          变量插值
#   {variable?default}  带默认值插值
#   条件段落由服务层处理，模板内不写逻辑
# ============================================================

# ============================================================
# 【封闭枚举登记】（唯一真值来源）
#   —— 改动任一枚举，须同步 templates/、examples/ 与 validate_output.py（三者不一致即为缺陷）：
#   purpose     建立｜升级｜转折｜反转｜收束
#   fill_stage  synopsis｜script｜storyboard｜shot_prompt
#   owner       算法作者｜客户｜运维 —— **缺口台账的闭合责任人**（剧本层 `unspecified[].owner`，2026-10-13 依 `SR-02` 新增）。
#               硬规则：**owner=客户 者，fill_stage 必须为本层 `script`**——下游（分镜／提示词）职责上
#               无法补叙事事实与设计确认；不得为「看起来有人接手」而把「待客户确认」推给下游阶段。
#   dialogue.type  对白｜旁白｜画外音（剧本层 `acts[].scenes[].dialogue[].type`，2026-10-13 依 `SR-09` 登记）
#   design_source / source  来源标注**分两层**（剧本层，2026-10-13 依 `SR-10` 拆分）：
#               `source` = 承继类字段的来源 客户提供｜承继上游
#               `design_source` = 本层首定义的设计类 客户提供｜系统提议待确认
#               **判定规则：凡 output 中带 `design_source` 的值即为设计类**（规则式，不用枚举清单）
#   stage       synopsis｜script｜storyboard｜shot_prompt｜revise
#   task_type   generate｜summarize｜rewrite｜extract｜guard
#   shot_size   extreme_wide｜wide｜full｜medium｜close_up｜extreme_close_up（规范 §3.7.1，6 值）
#   camera.move 运镜 20 类内部语义标签（规范 §3.7.2）：static｜push_in｜pull_out｜zoom_in｜zoom_out｜
#               pan_left｜pan_right｜tilt_up｜tilt_down｜truck_left｜truck_right｜pedestal_up｜
#               pedestal_down｜arc｜tracking｜shake_slight｜shake_strong｜pov｜roll_cw｜roll_ccw
#               —— static 与 pov 不得携带 amplitude／speed
#   amplitude   small｜large（2026-10-13 依 `BR-08` 登记）
#               —— 与规范 §3.7.2 一致：`medium` **通常省略**，本层一律**留空字符串**；
#                  仅在需要强调幅度时出现 small／large 两值。
#                  校验：`validate_output.py` **R26**（禁 medium 等默认值当必填值）。
#                  ⚠️ **更正（2026-10-13，随 SW-007 自查发现）**：本行此前写「校验：R13（禁 medium 等）」，
#                     **该声称有误**——R13 实为**单镜时长区间**（DURATION_BOUNDS），与幅度无关。
#                     后果：v2.1.0 已把该口径写进 `storyboard_v1` 硬性约束 6，**却无任何脚本判据**，
#                     用例 `CASE-003_storyboard-case01.md` 的 S03-SH002 因而残留 `amplitude="medium"` 未被发现。
#                     现已补 R26 判据（同时作用于分镜脚本与交付包）并修正上游用例。**登记即契约，不得虚指。**
#   speed       slow｜fast（2026-10-13 依 `BR-08` 登记）
#               —— 与规范 §3.7.2 一致：`normal` **通常省略**，本层一律**留空字符串**；
#                  仅在需要强调速度时出现 slow／fast 两值。
#                  校验：`validate_output.py` **R26**（同上一处更正：原写 R13 系误指）。
#   transition  cut｜fade_in｜fade_out｜dissolve｜wipe（单侧表达：**仅指同一单元内部**，由后一镜 transition_in 承接）
#               —— ✅ **单元边界口径（2026-10-13 依 `BR-07` 裁定；`ISSUE-008` 已闭环）**：规范 §3.7.5 原文
#                  的「衔接由后一镜单侧表达」与「前镜 transition_out 仅用于单元末镜」在单元边界**字面互斥**；
#                  **规范已回改（V1.3 §3.7.5）**——「单侧表达」明确限定为**同一生成单元内部**（非末镜一律不得填
#                  `transition_out`），并增补「**单元边界＝两半段**」一行——单元**末镜**用 `transition_out`
#                  表达出点、下一单元**首镜**用 `transition_in` 承接入点，二者**不算「两头都写」**。
#                  **本登记与规范 V1.3 逐字同口径**，无需再作差异标注。
#                  校验：`validate_output.py` R18（单元内非末镜不得填 transition_out）。
#   shot_ids    镜序号（`units[].shot_ids`）**必须按镜序递增**，且单元内各镜必须同场
#               （2026-10-13 依 `BR-11` 登记；校验：`validate_output.py` R9 增补段）。
#               —— 「顺序即镜序」：跨镜头双向引用（`unit_refs`）依赖此约定才可逆。
#   lighting    光照 15 值（规范 §3.7.5，2026-10-13 随 SW-007 登记入本块的**唯一真值来源**）：
#               soft_key_light｜hard_key_light｜rim_light｜backlight｜side_light｜top_light｜under_light｜
#               practical_light｜volumetric_light｜golden_hour｜blue_hour｜overcast｜neon_night｜
#               candlelight｜moonlight
#               —— 与 `delivery/config/CFG-002_shot_vocab.yaml` 的 `lighting` 段一致；
#                  **上游（分镜层）允许写「词表值——中文光位说明」**，但**交付包（shot_prompt）只允许纯词表值**
#                  （schema `additionalProperties: false` 且字段类型为 string）→ 本层须**拆分**：
#                  字段留词表 code、说明移入 prompt 正文（投影规则①）。
#                  校验：`validate_output.py` **R32**（须为纯词表值；同时校 `shots[].lighting` 与
#                  `style_bible.lighting_default`）。
#   style_anchors 风格锚点**封闭**（规范 §3.3，2026-10-13 随 SW-007 登记）：
#               交付包 `prompt_zh`／`prompt_en` 正文**不得出现 `style_bible.style_anchors` 之外的风格词**——
#               闭集来源为 `delivery/config/CFG-002_shot_vocab.yaml` 的 `style_tags`（脚本内置为常量 `KNOWN_STYLE_TAGS`）。
#               校验：`validate_output.py` **R29**（③ 风格锚点封闭一项）。
#   negative_*  负向意图**只走容器字段**（`style_bible.negative_global` / `shots[].negative_prompt`），
#               **不得进 prompt 正文**（正文须转写为正向约束句）。校验：`validate_output.py` **R29**（② 负向残留）。
#   AIGC.*      AIGC 元数据块 7 字段（规范 §5.1，2026-10-13 随 SW-007 登记）：
#               Label｜ContentProducer｜ProduceID｜ReservedCode1｜ContentPropagator｜PropagateID｜ReservedCode2
#               —— `Label` 恒为字符串 "1"；`ProduceID` 必须 = `meta.pack_id`；
#                  `PropagateID` = `ProduceID`、`ContentPropagator` = `ContentProducer`（首次写入的取值规则）；
#                  文件中**仅一份**。校验：`validate_output.py` **R30**。
#               该块是**规则区不是生成区**：字段由服务层注入的 `pack_meta` 拼接，模型不得自拟（见 ⑥ 末段）。
# ------------------------------------------------------------
# 【跨层校验（需 `--script` 指定上游剧本输出）】
#   上游契约类判据不属枚举，但其**取值来源**在本块，故一并登记其真值口径：
#   R23 REWRITE_LOCK   逐镜语义字段（`shot.start/change/end`、`shot_language.composition/axis/result`）
#                      **不得重述**上游 `characters[].appearance_lock_zh` / `props[].appearance_lock_zh`
#                      的外观特征词（标点切段后 3-gram 比对）。外观定义权归剧本层（见 §职责边界 ⑤）。
#   R24 PROP_COVERAGE  某场 `props_present` 非空 → 该场**至少一镜**须标出对应 `prop_refs`。
#                      （守恒律的物件侧：道具入画必须可追溯，不得只在剧本层存在。）
#   R25 GATE_SELF_CHECK `quality_gate` 数值字段**可选**；一旦填写，须等于脚本复算真值（防伪证）。
# ------------------------------------------------------------
# 【交付包层校验（形态 `pack`；SW-007）】
#   R26 MOVE_PARAM_OMISSION `camera.amplitude` ∈ {空串, small, large}、`camera.speed` ∈ {空串, slow, fast}；
#                           `medium`／`normal` 是「通常省略」的默认值。⚠️ **上游侧**允许写空串；
#                           **交付包侧**则由 R33 要求「留空即省略键」（枚举不含空串）——两条合读见 R33。
#                           ⚠️ **同时作用于分镜脚本与交付包**——这是修 SCHEMA 错指的同一处缺口（见 amplitude 条目）。
#   R27 PACK_REQUIRED       顶层 **6 个 required 段**（`schema_version`／`meta`／`style_bible`／`units`／
#                           `shots`／`aigc_meta`）齐备；`characters`／`props`／`forbidden_items` 为
#                           **可选段**（v2.0 起，与 `characters` 同口径：应当有、无则为空数组）；
#                           每镜必备 **14 字段**（与 schema `$defs/shot.required` **逐字一致**，v2.0 增 `prop_refs`）；
#                           `style_ref` 命中 `style_bible.style_id`（§3.8 阻断项）；`character_refs` 命中已定义角色；
#                           **`prop_refs` 命中 `props[].prop_id`**（v2.0 起，§3.4.1）。
#   R28 PACK_APPEARANCE_ECHO 正文（`prompt_zh`／`prompt_en`）不得复述 `characters[].appearance_lock_zh|_en`。
#                           ⚠️ **两侧判据不同**：中文取**连续 3 字**、英文取**连续 3 个实词**（先剔停用词）——
#                           英文 3 个字符只是词内片段（`the`／`old`），2026-10-13 首跑即误报 773 处。
#   R29 PACK_PROMPT_HYGIENE ① 无模型参数指令；② 无负向残留写法；③ 风格锚点封闭（见 style_anchors 条目）。
#   R30 AIGC_META           见 AIGC.* 条目。
#   R31 PACK_DURATION_LOCK  **需 `--storyboard`**：① `meta.total_duration_ms` = Σ各镜 `duration_ms` 自洽；
#                           ② 与上游分镜的**镜数／镜序／逐镜 `duration_ms`** 逐项相同（承继守恒的判据）。
#                           ⚠️ **已知盲区两条**（登记而非修复）：(a) 未提供上游时，若同时改单镜时长**与**总时长，
#                              两者仍自洽、无外部真值可比；(b) `meta.total_duration_ms` 在 schema 的
#                              `meta.required` 里**是可选的**，缺失时本层无从守恒。
#                              → **结论：校验交付包时须始终带 `--storyboard`。**
#   R32 LIGHTING_VOCAB      见 lighting 条目。
#   R33 PACK_NO_EMPTY_STRING **交付包可选字段不得为空串**——留空须「省略该键」（依评审 PR-02 新增）。
#                           覆盖 `camera.amplitude/speed/height/roll/optics`、`transition_in/out`（枚举）
#                           与 `lighting`（vocabRef `^[a-z][a-z_]*$`）；`characters[].ref_image`
#                           为 `type:string`，**null 亦不合法**，须省略键。
#                           ⚠️ 与门禁**严格对齐**，不写比契约更严的私有口径：`shots[].ref_image` 在 schema
#                              为 `oneOf[string,null]`、null **合法**，故**刻意不报**（已登记为已知盲区）。
#                           背景：原口径「medium／normal 规范化为空串」会产出**不合法**的包
#                              （实测：21 处空串 + 2 处 characters 非法 null → 23 条门禁 BLOCK）。
#   R34 EN_CAMERA_SENTENCE  英文正文须含以 `The camera` **起句的独立句**（依评审 PR-04 新增）。
#                           判据 `(?:^|[.!?]\s+)The camera\b`——`static`／`pov` 也须有运镜句，只是不带幅度速度。
#                           实测 `S01-SH002` 曾把小写 `as the camera …` 并入起句（**人眼看不出来**）。
#   R35 PROP_ANCH_CONSISTENCY **道具锚一致性（v2.0 起，正向判据）**——**取代** v1.1~v1.3 的
#                           `NO_PROP_REFS`（「交付包 `shots[]` 不得出现 `prop_refs`」）。
#                           ⚠️ **为什么反转而不是删掉**：旧判据的**设立前提**是「交付规范 §3.6 与交付
#                              schema 均无该字段」（当时规范全文无「道具」二字），而 **v2.0 已补齐契约**
#                              （规范 §3.4.1 增顶层 `props[]`、§3.6 增 `prop_refs`；schema 同步并列入
#                              `shot.required`）⇒ **旧前提消失，判据撤销并反转为正向**：
#                             ① 每镜**必须有** `prop_refs` 键（无道具为**空数组** `[]`，**不得写空串**）；
#                             ② 每项**必须命中** `props[].prop_id`，否则**阻断**（道具锚断裂）；
#                             ③ 与上游 storyboard 的逐镜取值**逐项一致**（承继守恒，R31 覆盖）。
#                           ✅ **`ISSUE-011` 已闭环**（2026-10-14 项目方拍板取 (a)）——本条由
#                              「把契约缺口机器可见化」转为「**守住补齐后的契约**」。
#   R36 NO_EXTRA_KEY        交付包**只允许出现契约字段集内的键**（依评审 PR-14 新增）。
#                           PR-14 的担忧是「两处清单不一致会留下『**清单外字段无人管**』的漏洞」——
#                             根因是判据只查「必备」（R27）不查「多余」：任何上游带来的、规范里
#                             没有的字段（v2.0 之前为 `shots[].prop_refs`、顶层 `forbidden_items`）
#                             都能悄悄进入交付包，到门禁才被 `additionalProperties:false` 拦下
#                             （**拦得太晚，且只看得到一条汇总报错**）。⚠️ **v2.0 起二者已进契约**，
#                             不再是「多余键」——但本条**依然有效且更必要**：今后任何上游新增字段
#                             仍会先经此闸口。
#                           ⚠️ **字段集直接读交付 schema**（`single source of truth`，
#                             落点 `delivery/schemas/CFG-006_shot_prompt_pack.v1.schema.json` 的
#                             `properties` 与 `$defs`），**刻意不另写一份会陈旧的清单**；
#                             schema 不可读时**跳过（不伪判）**——与 R33 的取舍一致。
#                           检查 **九处**（v2.0 起）：顶层／`shots[]`／`units[]`／`characters[]`／
#                             **`props[]`**／**顶层 `forbidden_items`**／`meta`／`style_bible`／`aigc_meta`。
#                           ✅ **设计价值在此显形**：v2.0 契约扩容时本条**零改动**——它不持有清单，
#                              只持有「读 schema」这一个动作，故 schema 一升它自动跟随。
#                           与 **R35** 的关系：R35 是 `prop_refs` 的**定向**判据（正向：须存在且命中），
#                             R36 是**通用**闸门（反向：不得有多余键）；两条并存、方向相反，R36 兜住
#                             今后所有同类。
#                           ✅ **`ISSUE-012` 已闭环**（2026-10-14 拍板取 (a)：顶层增设 `forbidden_items`
#                              独立容器）。⚠️ **边界不变**：该容器只承接**客户侧禁忌**（上游 `must_avoid`），
#                              **不得**放入受控词库分类码／词条（规范 §3.1.1 三层边界）。
# ============================================================

schema_version: "1.0.0"
description: 提示词模板统一结构约定，所有 templates/*.yaml 遵循本规范
