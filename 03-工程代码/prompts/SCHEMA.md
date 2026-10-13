# ============================================================
# 提示词模板 · 结构约定说明
# ============================================================
# 本目录所有模板遵循统一结构，便于工程加载与备案说明。
#
# 【字段说明】
#   id          唯一标识，与 manifest.yaml 一致
#   name        中文名称
#   version     版本号（主.次.修订），修改必须升版本
#   task_type   generate | summarize | rewrite | extract | guard
#   stage       业务链路阶段（仅 AI 漫剧业务链路模板填写，其他模板留空）：
#                 synopsis | script | storyboard | shot_prompt | revise
#               —— 与《分镜提示词交付规范 v1.2》§3.2 的 stage_chain 枚举对齐
#                  （2026-10-13 更新：原引 v1.1，现行版为 **v1.2**；v1.2 仅改内部待办编号体系，
#                    §3.2 的技术内容与 v1.1 逐字相同，故本处引用对齐不涉及口径变化），
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
#   ★ **设计类来源在本层的判定口径**（依 `BR-04` 写明，不留空白）：
#       本层（storyboard）的产出**不属 SCHEMA 意义上的设计类内容**——本层是导演决策层，产出的是
#       「怎么拍」（切点／镜号／景别／运镜／八维落点／时长），属**技艺表达**而非**内容设计**；
#       SCHEMA 的设计类指**内容性设计**（角色外观／全片风格串／道具外观），其**首定义责任在剧本层**。
#       **唯一例外**：本层若自主提议了具体配乐织体（`units[].music` 非 `N/A`），该项属本层新产生的设计内容
#       → 按既有机制在 `unspecified` 台账登记来源（`owner=客户`／`fill_stage=storyboard`／`upstream_field` 空串），
#       **不新增 `design_source` 字段**。⚠️ 待决项见 `ISSUE-007`（规范 §3.5 的 units[] 是否增该字段）。
#
#   —— 产物契约的静态校验见同目录 validate_output.py（**R1~R25 共 25 条**：
#      梗概/剧本层 9 条 + 分镜层 13 条 + 跨层 2 条（需 `--script`）+ 通用 1 条，
#      含 purpose 封闭枚举、dialogue.type 枚举、缺口台账 owner 责任归属、11 项镜头语言质量门、
#      外观锚重述检测（R23）、道具覆盖检测（R24）与质量门自声明复算（R25））。
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
#                  仅在需要强调幅度时出现 small／large 两值。校验：`validate_output.py` R13（禁 medium 等）。
#   speed       slow｜fast（2026-10-13 依 `BR-08` 登记）
#               —— 与规范 §3.7.2 一致：`normal` **通常省略**，本层一律**留空字符串**；
#                  仅在需要强调速度时出现 slow／fast 两值。校验：`validate_output.py` R13（禁 normal 等）。
#   transition  cut｜fade_in｜fade_out｜dissolve｜wipe（单侧表达：由后一镜 transition_in 承接）
#               —— ⚠️ **单元边界口径（2026-10-13 依 `BR-07` 裁定）**：规范 §3.7.5 自身措辞存在
#                  「衔接由后一镜单侧表达」与「前镜 transition_out 用于单元末镜」互斥；本层裁定为
#                  **两个半段**——单元**末镜**用 `transition_out` 表达出点、下一单元**首镜**用
#                  `transition_in` 承接入点，二者**不算「两头都写」**（单元内部的镜间转场仍严格单侧）。
#                  ⚠️ 待项目方确认是否回改规范措辞（已登记 `ISSUE-008`）。
#   shot_ids    镜序号（`units[].shot_ids`）**必须按镜序递增**，且单元内各镜必须同场
#               （2026-10-13 依 `BR-11` 登记；校验：`validate_output.py` R9 增补段）。
#               —— 「顺序即镜序」：跨镜头双向引用（`unit_refs`）依赖此约定才可逆。
# ------------------------------------------------------------
# 【跨层校验（需 `--script` 指定上游剧本输出）】
#   上游契约类判据不属枚举，但其**取值来源**在本块，故一并登记其真值口径：
#   R23 REWRITE_LOCK   逐镜语义字段（`shot.start/change/end`、`shot_language.composition/axis/result`）
#                      **不得重述**上游 `characters[].appearance_lock_zh` / `props[].appearance_lock_zh`
#                      的外观特征词（标点切段后 3-gram 比对）。外观定义权归剧本层（见 §职责边界 ⑤）。
#   R24 PROP_COVERAGE  某场 `props_present` 非空 → 该场**至少一镜**须标出对应 `prop_refs`。
#                      （守恒律的物件侧：道具入画必须可追溯，不得只在剧本层存在。）
#   R25 GATE_SELF_CHECK `quality_gate` 数值字段**可选**；一旦填写，须等于脚本复算真值（防伪证）。
# ============================================================

schema_version: "1.0.0"
description: 提示词模板统一结构约定，所有 templates/*.yaml 遵循本规范
