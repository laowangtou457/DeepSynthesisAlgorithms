# 交付合规声明

| 项目 | 内容 |
| --- | --- |
| 声明编号 | {{statement_id}} |
| 提供者 | {{provider}} |
| 内容编号（pack_id） | {{pack_id}} |
| 交付时间 | {{created_at}} |
| 声明版本 | v1（模板 compliance_statement_v1.md） |

---

## 一、交付物清单

| # | 交付物 | 文件 | 说明 |
| --- | --- | --- | --- |
| 1 | 分镜提示词集（通用规范） | `shot_prompt_pack.json` | 结构化提示词包，含全局风格与角色锚点 |
| 1b | 分镜提示词集（模型适配） | `exports/<model>/*.txt` | 按目标模型适配的导入格式 |
| 2 | AIGC 元数据块 | 随 pack 与各导出文件 | 隐式标识，格式依 GB 45438—2025 附录 E |
| 3 | 标识素材包 | `assets/overlay_intro_*.png`、`assets/overlay_corner_*.png` | 片头卡与角标（横竖两版） |
| 4 | 本交付合规声明 | `COMPLIANCE.md` | 本文件 |
| — | 导出文件 | `exports/shot_prompt_pack.{csv,xlsx,md}` | 均含显式标识 |

## 二、生成溯源

| 项 | 内容 |
| --- | --- |
| 生成系统 | {{system}} v{{system_version}} |
| 生成模型 | {{model_name}}（后端 {{model_backend}}） |
| 提示模板 | {{template_list}} |
| 生成链路 | {{stage_chain}} |
| 会话 ID / 任务 ID | {{session_id}} / {{task_id}} |
| 元数据内容编号 | {{produce_id}} |

## 三、标识方法说明

### 3.1 文本侧标识（本系统自主落地）

| 类型 | 内容 |
| --- | --- |
| 显式标识文案 | `{{explicit_text}}` |
| 显式标识位置 | 对话/写作界面的显著位置；导出文件的**首尾**（按格式差异化注入） |
| 隐式标识 | AIGC 元数据块，字段：`Label` / `ContentProducer` / `ProduceID` / `ReservedCode1` / `ContentPropagator` / `PropagateID` / `ReservedCode2`（全文件仅一份） |

### 3.2 素材侧标识（供成片使用）

| 素材 | 建议位置 | 文字高度 | 持续时长 | 依据 |
| --- | --- | --- | --- | --- |
| 片头卡 `overlay_intro_*` | 视频**起始画面** | ≥ 画面最短边的 **6%** | **3 秒** | GB 45438—2025 §5.4（法定下限：5% / 2 秒） |
| 角标 `overlay_corner_*` | 画面**右下角**（竖版底部居中偏下） | ≥ 画面最短边的 **6%** | ≥ 3 秒，建议全片保留 | 同上 |

> 具体使用步骤见随包《标识落地指引》与各素材规格文件 `assets/overlay_spec.json`。

## 四、标识落地义务与使用责任

请您在使用本交付物生成视频并**对外传播**时，按上述素材与说明加注人工智能生成合成内容的标识。

依据《人工智能生成合成内容标识办法》**第八条**，服务提供者应当在用户服务协议中明确生成合成内容标识的方法、样式等规范；**第九条**，用户在申请不含显式标识的内容时，服务提供者应当在用户服务协议中明确用户的标识义务和使用责任后提供。您作为内容使用者与传播者，负有相应的标识义务与使用责任。

## 五、禁止行为告知

依据《人工智能生成合成内容标识办法》**第十条**，任何组织和个人不得恶意删除、篡改、伪造、隐匿本办法规定的生成合成内容标识，不得为他人实施上述行为提供工具或者服务。

> 本系统**不提供**任何去除、关闭或隐藏标识的功能；如发现标识缺失或被篡改，请勿传播该内容。

## 六、适用人群、场合与用途

| 项 | 内容 |
| --- | --- |
| 适用人群 | {{audience}} |
| 适用场合 | {{occasion}} |
| 适用用途 | {{purpose}} |
| 禁止用途 | 不得用于伪造他人言论、真实人物形象或误导公众的场景；不得用于法律法规禁止的其他用途 |

## 七、自检结论

> 依据规范 NORM-DELIVERY-001 **v1.1 §8.3**（交付前自检 **18 项**，逐项必须通过）。

| # | 检查项 | 结果 | 检查时间 | 检查人 |
| --- | --- | --- | --- | --- |
| 1 | 输入内容安全检测 | {{check_safety_input}} | {{ts}} | {{operator}} |
| 2 | 输出内容安全复检 | {{check_safety_output}} | {{ts}} | {{operator}} |
| 3 | 版权 / 改编风险校验 | {{check_copyright}} | {{ts}} | {{operator}} |
| 4 | 提示词包结构校验（Schema） | {{check_schema}} | {{ts}} | {{operator}} |
| 5 | 一致性校验（锚点引用 / 单元引用 / 时长合计） | {{check_consistency}} | {{ts}} | {{operator}} |
| 6 | 元数据块完整性与唯一性 | {{check_meta}} | {{ts}} | {{operator}} |
| 7 | 导出文件显式标识注入 | {{check_export_mark}} | {{ts}} | {{operator}} |
| 8 | 标识素材包完整性 | {{check_assets}} | {{ts}} | {{operator}} |
| 9 | 合规声明要素齐全 | pass | {{ts}} | {{operator}} |
| 10 | 交付包无密钥、离线可用 | pass | {{ts}} | {{operator}} |
| 11 | 系统内无去标识功能入口 | pass | {{ts}} | {{operator}} |
| 12 | 适配输出与核对状态一致 | {{check_adapter}} | {{ts}} | {{operator}} |
| **13** | **镜头语言质量门（11 阈值全通过）** | {{check_quality_gate}} | {{ts}} | {{operator}} |
| **14** | **台词—时长校验（每镜 ≤ 9 字/秒）** | {{check_dialogue_rate}} | {{ts}} | {{operator}} |
| **15** | **动作复杂度—时长预算校验** | {{check_action_budget}} | {{ts}} | {{operator}} |
| **16** | **生成单元划分正确（每单元 2–3 镜、单元内运镜不重复、无单镜单元）** | {{check_units}} | {{ts}} | {{operator}} |
| **17** | **目标模型不支持负向字段时无负向残留** | {{check_negative_residue}} | {{ts}} | {{operator}} |
| **18** | **角色一致性 / 跨镜连续性人工核对** | {{check_human_review}} | {{ts}} | {{operator}} |

检查方法：{{method}}
质量门报告：`qa/audit_report.txt`（随包留档，留存期 ≥ 6 个月）

---

本声明由本系统自动生成，与交付物同源留档，可随时调取以配合监督检查。

**留存期：不少于 6 个月**（对齐《人工智能生成合成内容标识办法》第九条的日志留存要求，并覆盖自检记录、镜头语言质量门报告、人工核对记录、声明副本与生成溯源记录）。

---

*模板文件：`03-工程代码/delivery/templates/compliance_statement_v1.md` ｜规范依据：NORM-DELIVERY-001 v1.1 §8*
