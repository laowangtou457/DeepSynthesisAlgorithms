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
#               —— 与《分镜提示词交付规范 v1.1》§3.2 的 stage_chain 枚举对齐，
#                  用于下游按链路顺序编排模板、并写入交付包的 generation_trace.stage_chain
#   —— 业务链路模板的「锚点首定义」约定（2026-10-13 定案，经导演视角两轮评审）：
#       ① 角色外观（age_band / appearance_lock_zh）与全片风格串的**首次定义责任在剧本阶段**
#          （stage=script，SW-005）；梗概阶段（stage=synopsis，SW-004）只做「占位 + 缺口登记」，
#          不得越权定义、不得编造——凡客户未提供者一律写「未指定」并登记进 unspecified。
#       ② 角色稳定标识 character_id 由链路最上游（synopsis）分配，全链路不得改号——
#          name 可为「未指定」，character_id 不可为空。
#       ③ 下游各阶段的 scene_no 一律沿用 synopsis 模板 scenes_outline 的 no，不得重新编号。
#       ④ 剧本阶段（stage=script，SW-005）承接①并「落地」：synopsis 只做占位与缺口登记的角色外观
#          （age_band / appearance_lock_zh）与全片风格串（style_bible），在剧本层**首次定义**——
#          客户未提供时由本层提出具体候选、标 source「系统提议待确认」并登记台账，
#          **不得照抄「未指定」**（照抄等于把缺口原样抛给下游，下游将无锚点可用）。
#          区分原则：**事实类**（人名／地名／机构名／年代／数值）不得编造；
#                    **设计类**（角色外观／风格串／配色）本层负责定义，但须可追溯、可推翻。
#          另：剧本层只做「剧本化编排」，**不做镜头切分**——切镜属分镜脚本阶段（stage=storyboard，SW-006）。
#
#   —— 产物契约的静态校验见同目录 validate_output.py（首批 6 条规则，含 purpose 封闭枚举）。
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
#   stage       synopsis｜script｜storyboard｜shot_prompt｜revise
#   task_type   generate｜summarize｜rewrite｜extract｜guard
# ============================================================

schema_version: "1.0.0"
description: 提示词模板统一结构约定，所有 templates/*.yaml 遵循本规范
