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
#          职责边界三条——
#            · **不定义外观与风格**（首定义在剧本层）、**不重述外观细节**，只引用 style_ref、character_refs
#              与 prop_refs（道具锚，2026-10-13 随剧本层新增 props[] 一并承接）；
#            · **不写 prompt_zh／prompt_en 正文、不做模型适配、不写 AIGC 元数据块**——那些属 SW-007（编译表达层）；
#            · 字段名与《分镜提示词交付规范》§3.5（units[]）／§3.6（shots[]）**逐字对齐**，
#              使 SW-007 的适配从「重新设计」降级为「格式投影」。
#          八维覆盖为**两层口径**（依规范 §4.1／§4.3）：景别／运镜**每镜必有**；
#            角度／光学／构图／轴线／光线／画面结果六维按 §4.2 覆盖率阈值在**单元与整片层面**达标，
#            **不要求每镜八维全开**。镜号 shot_no 与单元编号 unit_id 由本层首次分配。
#          11 项质量门阈值与容差算法直接引用参照实现 `audit_shots.py` 的 `GATE`（不得另立一套）。
#
#   —— 产物契约的静态校验见同目录 validate_output.py（**R1~R22 共 22 条**：
#      梗概/剧本层 8 条 + 分镜层 13 条 + 通用 1 条，
#      含 purpose 封闭枚举、dialogue.type 枚举、缺口台账 owner 责任归属与 11 项镜头语言质量门）。
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
#   transition  cut｜fade_in｜fade_out｜dissolve｜wipe（单侧表达：由后一镜 transition_in 承接）
# ============================================================

schema_version: "1.0.0"
description: 提示词模板统一结构约定，所有 templates/*.yaml 遵循本规范
