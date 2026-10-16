# delivery · 交付产物工程资产

> 本目录是 **NORM-DELIVERY-001《分镜提示词交付规范 v2.2》**（现行版）的工程实现资产。
> 规范正文：[`01-架构设计/SPEC-007_分镜提示词交付规范-v2.2.md`](../../01-架构设计/SPEC-007_分镜提示词交付规范-v2.2.md)（V1.0 ~ V2.1 保留于同目录，供沿革对照）
> ⚠️ **资产自身版本号不随规范版本号变动**：本目录各资产的 `v1.1.0` 等版本号是其**自身修订号**。⚠️ **但规范 V2.0 属结构变更**（`T-054`~`T-056` 契约升版批次）：顶层增 `props[]`／`forbidden_items`、镜头增 `prop_refs`、`prompt_en` 上限 900 → 1200——故本目录**交付契约资产随之升版**（`CFG-006` Schema 的 `schema_version` **1.1.0 → 2.0.0**、两个示例包同升、`validate_pack.py` 判据引用同步）；**规范 V2.1 为约束次版本**（`ISSUE-016`／`ISSUE-017`）：`schema_version` **2.0.0 → 2.1.0**、`stage_chain` 枚举补 `revise`，示例包与用例包同步升 **2.1.0**；`CFG-001` 适配配置／`CFG-002` 镜头词表不受影响。
> 对应需求：SW-007、SW-013、SW-014、SW-022、SW-025、SW-026、SW-I04、SYS-018、SYS-019
> 评审依据：`10-评审记录/REV-D-017-02_分镜提示词交付规范-v1.0-导演视角评审意见.md`（23 条）

---

## 一、目录结构

```
delivery/
├── README.md                         本文件
├── validate_pack.py                  ★ 交付前校验门禁（规范 §8.3，18 项自检）
├── tools/                            ★ 生成器与判据（可重跑；`*.py` 属编号豁免类）
│   ├── export_models.py              ②各模型适配文本生成器（规范 §6.8 两段式；**配置驱动**）
│   ├── validate_exports.py           适配层判据 E1~E12 + 负向样本自测（`--selftest`）
│   └── md_to_docx.py                 阅读版导出件生成器（`**/*_阅读版.docx`，见 CM-002 §3 第 7 类）
├── schemas/
│   ├── CFG-006_shot_prompt_pack.v1.schema.json   提示词包 JSON Schema（规范 §3，v2.0.0）
│   └── CFG-005_manifest.v1.schema.json           交付清单 Schema（规范 §1.4，v1.1.0）
├── config/
│   ├── CFG-002_shot_vocab.yaml               镜头词表：景别/运镜/光学/高度/滚转/光照/转场 + 三向映射（规范 §3.7）
│   └── CFG-001_model_adapters.yaml           ★ 多模型适配规则 + 优先级 + 核对覆盖表 + **逐模型导出声明**（规范 §6，v1.2.0）
├── templates/
│   ├── AST-004_compliance_statement_v1.md    交付合规声明模板（规范 §8.2，18 项自检）
│   └── AST-003_audit_report_sample.txt       ★ 镜头语言质量门报告示例（随包留档 qa/audit_report.txt）
├── examples/
│   ├── CFG-004_demo_pack.json                示例提示词包（1 单元 / 3 镜 / 15 秒，通过全部质量门）
│   ├── CFG-003_demo_manifest.json            示例交付清单（含 18 项自检、质量门结论、人工核对记录）
│   └── _exports_demo/                        ★ 适配文本示例基线（`exports/<model>/<model>.txt`，脚本生成件）
└── assets/
    ├── overlay_intro_*.png           标识素材：片头卡（横/竖版）
    ├── overlay_corner_*.png          标识素材：角标（横/竖版，含透明通道）
    ├── AST-002_overlay_spec.json             素材规格（GB 硬指标 + 本项目取值）
    └── AST-001_ASSETS.md                     素材说明与候选样式对照
```

> ⚠️ **本次补齐目录树的一处陈旧**：`tools/` 目录由 `T-070`（`md_to_docx.py`）引入时**未同步进本节目录树**（与 `ISSUE-019` 同族：同一动作未一次扫尽同源处），今随 SW-025 落地一并补齐。

---

## 二、三层结构 ↔ 本目录资产对应

| 规范层 | 资产 |
| --- | --- |
| **第 1 层 · 内容质量层**（八维 / 质量门 / 单元 / 语速） | `CFG-006_shot_prompt_pack.v1.schema.json` 的 `units` / `shot_language` / `action` / `camera.*` 定义 + `config/CFG-002_shot_vocab.yaml: eight_dimensions` + `validate_pack.py` 质量门 + `templates/AST-003_audit_report_sample.txt` |
| **第 2 层 · 模型适配层** | `config/CFG-001_model_adapters.yaml`（11 维适配 + 核对覆盖表 + 逐模型 `export_rules` 导出声明）+ `config/CFG-002_shot_vocab.yaml` 的 `model_map`（三向映射）+ `config/CFG-001_model_adapters.yaml: negative_policy`+ **运行态** `tools/export_models.py`（生成 `exports/<model>/<model>.txt`）与 `tools/validate_exports.py`（判据 E1~E12） |
| **第 3 层 · 交付形态层** | 四件套（`schemas/` + `examples/` + `assets/` + `templates/AST-004_compliance_statement_v1.md`）+ `validate_pack.py` 门禁 |

### 交付四件套 ↔ 本目录资产

| 交付物 | 生成依据 |
| --- | --- |
| ① 分镜提示词集 | `schemas/CFG-006_shot_prompt_pack.v1.schema.json` + `config/CFG-002_shot_vocab.yaml` |
| ② AIGC 元数据块 | `schemas/CFG-006_shot_prompt_pack.v1.schema.json` 的 `aigc_meta` 定义 + 规范 §5 |
| ③ 标识素材包 | `assets/`（PNG + `AST-002_overlay_spec.json`） |
| ④ 交付合规声明 | `templates/AST-004_compliance_statement_v1.md` |
| 随包留档：质量门报告 | `templates/AST-003_audit_report_sample.txt` → 交付时落盘为 `qa/audit_report.txt` |
| 模型适配输出 | `config/CFG-001_model_adapters.yaml`（规则）+ `tools/export_models.py`（**生成** `exports/<model>/<model>.txt`）+ `tools/validate_exports.py`（**校验**） |
| 交付清单 | `schemas/CFG-005_manifest.v1.schema.json` |

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
| **时长边界** | 整秒校验；上下限取自 `config/CFG-001_model_adapters.yaml`（不在脚本内硬编码模型数值） |
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

> ⚠️ **实测踩坑**：适配文本做硬换行排版时，**不得把 `The camera` 拆到两行**——校验器只认连续字符串，拆开后该镜会被判「缺少运镜句」，而人眼看不出。本目录 `examples/CFG-004_demo_pack.json` 对应的适配示例已按此规则排版并实测通过。

### 3.4 生成各模型适配文本（SW-025 · `exports/<model>/<model>.txt`）

```bash
python tools/export_models.py examples/CFG-004_demo_pack.json            # 全部已配置模型
python tools/export_models.py <pack.json> --models minimax_h3,kling     # 指定模型
python tools/export_models.py <pack.json> --out /path/to/pkg --json     # 指定输出根 + JSON 摘要
```

输出落 `<out>/<model_code>/<export_filename>`（默认 `examples/_exports_demo/`，**脚本生成件**）。
**生成器只做三件事**：① 字段 code → 目标模型字面（`CFG-002` 的 `model_map` 投影）；
② 按 `CFG-001` 逐模型 `export_rules` 追加模型专属行（镜头语言 / 负向字段 / 台词语言标签 / 音轨）；
③ 按规范 §6.6 做**可见的**降级处置与告警。**不改写、不重组、不润色正文**，`duration_ms` 一律原样承继。

### 3.5 校验适配文本（适配层判据 E1~E12 + 基线可复现 E13）

```bash
python tools/validate_exports.py                     # 校验 examples/_exports_demo 下全部
python tools/validate_exports.py <file_or_dir>
python tools/validate_exports.py --selftest          # 负向样本自测（每条判据须可触发）
python tools/validate_exports.py --repro             # 基线可复现性检查（E13）
```

退出码 `0` = 通过；`1` = 存在 **BLOCK**。

| 判据 | 内容 | 依据 |
| --- | --- | --- |
| E1 | 两段式结构（标识区 → 固定分隔行 → 提示词区）齐备且顺序正确 | §6.8 |
| E2 | 提示区含「复制说明」句 | §6.8 |
| E3 | 按生成单元分块，单元分隔行格式合规 | §6.8 |
| E4 | 块内镜头顺序按 `scene_no` → `shot_no` 升序 | §6.8 |
| E5 | 每镜必备画面描述文本 + 时长 + 画幅 | §6.8 |
| E6 | 提示词区不含 AIGC 元数据块 | §6.8、§5.3 |
| E7 | 提示词区不得出现内部 code（含赋值形态兜底） | §3.7.2 |
| E8 | 不得出现下游 API 地址／密钥字样 | SYS-018 |
| E9 | 目标模型不支持负向字段时**一字不得残留** | §6.4、§8.3 第 17 项 |
| E10 | `verify_status != verified` 必须打「适配参数待核对」，且不得标为已验证 | §13 NT-03、§6.6 |
| E11 | UTF-8 无 BOM、行尾 LF | §6.8 |
| E12 | 每镜正文字符数 ≤ 该模型 `max_prompt_chars` | §6.6 |
| **E13** | **基线可复现**：用**现行**生成器重跑，与目标目录**逐文件一致**（仅忽略 `生成时间`） | §6.7、`CM-001` §5 |

> **E13 为什么必要（不是凑数）**：E1~E12 判的是**文本本身合不合规**，判不出**这份基线还是不是现行代码的产物**。
> `T-072` 自查即实测到该盲区——生成器在基线落盘后又被修订（词表括注去除、负向标签按半角/全角冒号决定是否加空格），
> 而基线未重跑，于是**闸门会继续放行一份谁也复现不出来的文本**。E13 把「基线必须能由现行生成器复现」变成机器判据：
> **改了生成器/`CFG-001`/`CFG-002` 而不重跑基线 ⇒ BLOCK**（见 §五 第 5 条）。

> **E7 的口径（刻意不写严）**：只对**带下划线的 code**（`push_in` / `close_up` / `eye_level`…）做子串判定；
> 纯小写单词型 code（`static` / `wide` / `level` …）与**英文正文同形**——模型要求的正文本来就写 "static shot"，
> 对它们做子串匹配会把**正确输出判成泄漏**。故这类 code 改由**赋值形态**（`push_in:` / `= push_in` / `[push_in]`）检出。

> **两层校验的职责分界（不要混）**：`validate_pack.py` 校验**提示词包**（门禁⑮ 的时长上下限取自 `CFG-001`，
> 但那是**读配置**、不校验适配文本）；`tools/validate_exports.py` 校验**适配文本本身**。两者互补，缺一不可。
> `README` §3.3 的文本口径质量门（`audit_shots.py`）仍是第三把尺子。

---

## 四、当前状态与待办

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 提示词包 Schema | 可用 | **v2.0.0**；示例包已通过校验 |
| 交付清单 Schema | 可用 | v1.1.0 |
| 镜头词表 | 可用 | 运镜对齐 H3 官方 20 类；含弃用别名迁移表与三向映射 |
| 多模型适配规则 | 🟡 **部分待核对** | **MiniMax H3 = `verified`**（运镜/时长 4–15s 整数/7,000 字符/无负向字段/切镜 5 短语均已按实测回填）；**Seedance / 即梦 / 可灵 = `partial`**（结构写法已核对，字数与时长上限待官方核对）。见规范 §13 **NT-03**（已升级为交付阻断项） |
| **多模型适配文本**（`exports/`） | ✅ **可用（2026-10-14 落地）** | `tools/export_models.py` 生成、`tools/validate_exports.py` 校验（判据 **E1~E12** ＋ **E13 基线可复现**）；示例基线 `examples/_exports_demo/`（5 模型：`minimax_h3`／`seedance`／`dreamina`／`kling`／`other`）**BLOCK 0**；负向样本自测 **18/18 符合预期**；`--repro` **BLOCK 0（5/5 文件可由现行生成器复现）**。`CFG-001` 升 **v1.2.0**（新增 `explicit_mark_text` + 逐模型 `export_rules` + `literal_reject_patterns`；**11 维适配值与 limits 逐字未变**） |
| 提供者编码 | 🟡 **占位** | `{{PROVIDER_CODE}}` 待分配后回填，回填前不得用于正式交付（规范 §13 **NT-02**） |
| 标识素材 | ✅ **已定案并落实（SYS-Q15，2026-10-14）** | **角标**（边角常驻、不做片头卡）· `dark_pill` · 角标短文案 `AI生成`；已用开放授权字体 **Noto Sans SC**（SIL OFL 1.1，`wght=700`）重生成 8 素材（规范 §7.5、§13 **NT-04 字体选定 ✅ 已闭环**；**NT-05 样式选定 ✅ 已随定案闭环**） |
| 合规声明模板 | ✅ 可用 | 8 项要素 + 18 项自检 |
| 质量门报告 | ✅ 可用 | 示例见 `templates/AST-003_audit_report_sample.txt`；交付时须逐包生成 |

> **脱钩原则再确认**：本目录**不含**任何下游平台 API 地址、密钥字段或调用逻辑；适配仅做格式与写法转换（SYS-018）。

---

## 五、变更约定

1. 修改 `schemas/` 或 `config/` 后，必须重跑 `validate_pack.py`，确保示例包仍通过。
2. 新增模型适配**只改 `config/CFG-001_model_adapters.yaml`，不改代码**（SW-025 验收标准）；且**必须先在 `CFG-002_shot_vocab.yaml` 的 `model_map` 补齐该模型的字面**（规范 §6.7）。⚠️ **逐模型的导出差异（镜头语言句是否追加、负向字段标签、台词语言标签、转场是否单独成行、使用说明条）一律写进该模型的 `export_rules`**——生成器 `tools/export_models.py` 内**不得出现任何模型名或模型特有分支**，这是"不改代码"可被机器验证的前提。
3. 新增词表取值只改 `config/CFG-002_shot_vocab.yaml`。
4. **三层不得交叉引用数值**：第 3 层资产（Schema / 声明模板 / 导出规范）不得出现模型参数；模型数值一律放 `config/CFG-001_model_adapters.yaml`（规范 §0.4 编写纪律 4）。
5. **改了生成器或 `CFG-001`／`CFG-002` 之后，必须重跑基线并过 E13**：`python tools/export_models.py`（重跑 `examples/_exports_demo/`）→ `python tools/validate_exports.py --repro`（必须 BLOCK 0）。⚠️ 基线是**派生件**，不重跑就会变成「谁也复现不出来」的陈旧证据，而 E1~E12 **判不出这一点**——这正是 E13 存在的理由。
5. 规范正文与本目录资产须同步变更，并在规范 §14 修订记录中留痕。

---

*建立 2026-10-12 ｜ 规范依据 NORM-DELIVERY-001（建立时 v1.1；**现行 V2.2**，见文首）｜ v1.1 依导演视角评审 23 条修订；V2.0 依 `T-054`~`T-056` 契约升版批次 ｜ 2026-10-14 补 `tools/export_models.py` + `tools/validate_exports.py`（SW-025 运行态落地，`CFG-001` → **v1.2.0**）并补齐 `tools/` 目录树遗漏*
