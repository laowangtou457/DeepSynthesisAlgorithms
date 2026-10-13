# delivery · 交付产物工程资产

> 本目录是 **NORM-DELIVERY-001《分镜提示词交付规范 v1.3》**（现行版）的工程实现资产。
> 规范正文：[`01-架构设计/分镜提示词交付规范-v1.3.md`](../../01-架构设计/分镜提示词交付规范-v1.3.md)（V1.0 / V1.1 / V1.2 保留于同目录，供沿革对照）
> ⚠️ **资产自身版本号不随规范版本号变动**：本目录各资产的 `v1.1.0` 等版本号是其**自身修订号**；规范 **V1.1→V1.3 技术内容逐字未变**（V1.2 仅改内部编号体系、V1.3 仅澄清 §3.7.5 转场口径），故本目录 Schema／配置／词表／校验脚本**均无需改动**，本次仅订正「规范引用版本」文字。
> 对应需求：SW-007、SW-013、SW-014、SW-022、SW-025、SW-026、SW-I04、SYS-018、SYS-019
> 评审依据：`10-评审记录/分镜提示词交付规范-v1.0-导演视角评审意见.md`（23 条）

---

## 一、目录结构

```
delivery/
├── README.md                         本文件
├── validate_pack.py                  ★ 交付前校验门禁（规范 §8.3，18 项自检）
├── schemas/
│   ├── shot_prompt_pack.v1.schema.json   提示词包 JSON Schema（规范 §3，v1.1.0）
│   └── manifest.v1.schema.json           交付清单 Schema（规范 §1.4，v1.1.0）
├── config/
│   ├── shot_vocab.yaml               镜头词表：景别/运镜/光学/高度/滚转/光照/转场 + 三向映射（规范 §3.7）
│   └── model_adapters.yaml           ★ 多模型适配规则 + 优先级 + 核对覆盖表（规范 §6）
├── templates/
│   ├── compliance_statement_v1.md    交付合规声明模板（规范 §8.2，18 项自检）
│   └── audit_report_sample.txt       ★ 镜头语言质量门报告示例（随包留档 qa/audit_report.txt）
├── examples/
│   ├── demo_pack.json                示例提示词包（1 单元 / 3 镜 / 15 秒，通过全部质量门）
│   └── demo_manifest.json            示例交付清单（含 18 项自检、质量门结论、人工核对记录）
└── assets/
    ├── overlay_intro_*.png           标识素材：片头卡（横/竖版）
    ├── overlay_corner_*.png          标识素材：角标（横/竖版，含透明通道）
    ├── overlay_spec.json             素材规格（GB 硬指标 + 本项目取值）
    └── ASSETS.md                     素材说明与候选样式对照
```

---

## 二、三层结构 ↔ 本目录资产对应

| 规范层 | 资产 |
| --- | --- |
| **第 1 层 · 内容质量层**（八维 / 质量门 / 单元 / 语速） | `shot_prompt_pack.v1.schema.json` 的 `units` / `shot_language` / `action` / `camera.*` 定义 + `config/shot_vocab.yaml: eight_dimensions` + `validate_pack.py` 质量门 + `templates/audit_report_sample.txt` |
| **第 2 层 · 模型适配层** | `config/model_adapters.yaml`（11 维适配 + 核对覆盖表）+ `config/shot_vocab.yaml` 的 `model_map`（三向映射）+ `config/model_adapters.yaml: negative_policy` |
| **第 3 层 · 交付形态层** | 四件套（`schemas/` + `examples/` + `assets/` + `templates/compliance_statement_v1.md`）+ `validate_pack.py` 门禁 |

### 交付四件套 ↔ 本目录资产

| 交付物 | 生成依据 |
| --- | --- |
| ① 分镜提示词集 | `schemas/shot_prompt_pack.v1.schema.json` + `config/shot_vocab.yaml` |
| ② AIGC 元数据块 | `schemas/shot_prompt_pack.v1.schema.json` 的 `aigc_meta` 定义 + 规范 §5 |
| ③ 标识素材包 | `assets/`（PNG + `overlay_spec.json`） |
| ④ 交付合规声明 | `templates/compliance_statement_v1.md` |
| 随包留档：质量门报告 | `templates/audit_report_sample.txt` → 交付时落盘为 `qa/audit_report.txt` |
| 模型适配输出 | `config/model_adapters.yaml` |
| 交付清单 | `schemas/manifest.v1.schema.json` |

---

## 三、使用方法

### 3.1 校验一个提示词包（交付前门禁）

```bash
python validate_pack.py                          # 校验 examples/ 下全部示例
python validate_pack.py path/to/shot_prompt_pack.json
python validate_pack.py --no-quality-gate <pack> # 仅中间态调试用
```

退出码 `0` = 通过；`1` = 存在 **BLOCK** 级问题（不允许生成交付包）。
`WARN` 级问题不阻断，但须人工确认并记录。

依赖：`jsonschema`、`pyyaml`。

### 3.2 校验内容（v1.1）

| 类别 | 检查项 |
| --- | --- |
| 结构 | JSON Schema 校验（字段、类型、枚举、必填） |
| 一致性 | `style_ref` / `character_refs` / `unit_id` 引用是否命中；时长合计是否等于 `total_duration_ms` |
| **生成单元** | 每单元 2–3 镜、无单镜单元、单元内运镜类型不重复、每镜头归属于唯一单元、`soundscape`/`music` 齐备 |
| **镜头语言质量门** | 11 项阈值（逐单元 + 整片），含容差算法 `max(1, ceil(比值 × 镜数))` 与运镜类型数下限 `min(5, max(2, ⌈镜数/4⌉))` |
| **台词—时长** | 每镜语速 ≤ 9 字/秒，超标给出建议时长 |
| **时长边界** | 整秒校验；上下限取自 `config/model_adapters.yaml`（不在脚本内硬编码模型数值） |
| **运镜合法性** | `static`/`pov` 不得携带幅度/速度；`camera.roll` 与 `camera.move` 不得重复计；已弃用别名（follow/handheld/crane_up/crane_down/orbit）阻断 |
| **负向归位** | 目标模型不支持负向字段时，扫描「（负向：…）」「Negative prompt:」等残留并阻断 |
| **风格锚点** | `style_anchors` 存在且 3–5 条；提示词中出现锚点清单之外的已知风格词则告警 |
| 标识 | AIGC 元数据块存在、字段齐全、`ProduceID` 与 `pack_id` 一致、全文件仅一份 |
| 合规 | 内容安全检测状态、标识完整性、合规声明编号 |
| 词表 | `shot_size` / `camera.*` / `lighting` / `transition_*` 取值须在词表中 |
| 交付清单 | 四件套齐备 + 质量门报告、导出文件含显式标识与两段式、**18 项自检**齐全且无 fail、人工核对记录含结果/时间/检查人 |

### 3.3 质量门的第二道尺子（对投喂文本）

`validate_pack.py` 的质量门是**结构化字段口径**；规范 §4.2 还要求对**适配投喂文本**跑一次文本口径的审计：

```bash
python audit_shots.py <H3适配投喂文本> --gate -u    # 逐单元
```

**两道都通过才算数**，报告落盘为交付包内 `qa/audit_report.txt`。

> ⚠️ **实测踩坑**：适配文本做硬换行排版时，**不得把 `The camera` 拆到两行**——校验器只认连续字符串，拆开后该镜会被判「缺少运镜句」，而人眼看不出。本目录 `examples/demo_pack.json` 对应的适配示例已按此规则排版并实测通过。

---

## 四、当前状态与待办

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 提示词包 Schema | 可用 | v1.1.0；示例包已通过校验 |
| 交付清单 Schema | 可用 | v1.1.0 |
| 镜头词表 | 可用 | 运镜对齐 H3 官方 20 类；含弃用别名迁移表与三向映射 |
| 多模型适配规则 | 🟡 **部分待核对** | **MiniMax H3 = `verified`**（运镜/时长 4–15s 整数/7,000 字符/无负向字段/切镜 5 短语均已按实测回填）；**Seedance / 即梦 / 可灵 = `partial`**（结构写法已核对，字数与时长上限待官方核对）。见规范 §13 **NT-03**（已升级为交付阻断项） |
| 提供者编码 | 🟡 **占位** | `{{PROVIDER_CODE}}` 待分配后回填，回填前不得用于正式交付（规范 §13 **NT-02**） |
| 标识素材 | 🟡 **候选样式** | 供 SYS-Q15 定稿选择；正式交付前须替换为**授权字体**重新生成（规范 §7.5、§13 **NT-04/NT-05**） |
| 合规声明模板 | ✅ 可用 | 8 项要素 + 18 项自检 |
| 质量门报告 | ✅ 可用 | 示例见 `templates/audit_report_sample.txt`；交付时须逐包生成 |

> **脱钩原则再确认**：本目录**不含**任何下游平台 API 地址、密钥字段或调用逻辑；适配仅做格式与写法转换（SYS-018）。

---

## 五、变更约定

1. 修改 `schemas/` 或 `config/` 后，必须重跑 `validate_pack.py`，确保示例包仍通过。
2. 新增模型适配**只改 `config/model_adapters.yaml`，不改代码**（SW-025 验收标准）；且**必须先在 `shot_vocab.yaml` 的 `model_map` 补齐该模型的字面**（规范 §6.7）。
3. 新增词表取值只改 `config/shot_vocab.yaml`。
4. **三层不得交叉引用数值**：第 3 层资产（Schema / 声明模板 / 导出规范）不得出现模型参数；模型数值一律放 `config/model_adapters.yaml`（规范 §0.4 编写纪律 4）。
5. 规范正文与本目录资产须同步变更，并在规范 §14 修订记录中留痕。

---

*建立 2026-10-12 ｜ 规范依据 NORM-DELIVERY-001 v1.1 ｜ 依导演视角评审 23 条修订*
