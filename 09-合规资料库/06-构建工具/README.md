# 06-构建工具

> 合规资料库的维护脚本集。**全部为可运行工具，不是示意代码。**  
> 运行环境：Python 3.10+（本项目实测 3.13.12），仅用标准库（变体脚本可选依赖见下）。

---

## 一、脚本清单

| 脚本                       | 作用                                                            | 输入                                          | 输出                                              |
| ------------------------ | ------------------------------------------------------------- | ------------------------------------------- | ----------------------------------------------- |
| `init_lexicon.py`        | 初始化 31 个词表骨架                                                  | —                                           | `01-关键词库/词表/*.txt` + `lexicon_manifest.json`    |
| `init_banks.py`          | 初始化生成内容题库 + 应拒答题库骨架                                           | —                                           | `02-…/题目/*.jsonl`、`03-…/应拒答/*.jsonl` + manifest |
| `init_nonrefuse.py`      | 初始化非拒答题库（13 主题 × 20 题）                                        | —                                           | `03-…/非拒答/*.jsonl` + manifest                   |
| `seed_common_lexicon.py` | **批量入库常见违规词**（27 类，幂等）                                        | 脚本内数据                                       | 追加写入词表 + 计数行 + manifest                         |
| `import_funnlp.py`       | **funNLP 辅助表加工**（停用词／拆字／繁简／同义词／否定词／白名单；幂等）                    | `07-第三方词库源/funNLP/`                         | `01-关键词库/辅助词表/*` + `funnlp_manifest.json`       |
| `check_upstream.py`      | **上游词库导入前核实**（授权判定 + 规模统计）                                    | GitHub 仓库名                                  | 控制台报告                                           |
| `import_external.py`     | 导入外部开源词库并归类到国标 31 类                                           | 外部词库目录                                      | 追加写入词表 + 导入报告                                   |
| `gen_variants.py`        | 生成规避变体（拼音／符号／简繁）                                              | 词表                                          | 追加写入词表                                          |
| **`expand_lexicon.py`**  | ★★ **词库扩充主力**：27 个非受控类矩阵式组合生成 + 变体扩充                          | 白名单 / 繁简对照表                                 | 追加写入词表 + 计数行                                    |
| **`expand_banks.py`**    | ★★ **生成内容题库扩充**：27 类 × 细分主题 × 6 种提问风格                         | 脚本内主题库                                      | 追加写入 `02-…/题目/*.jsonl`                          |
| **`expand_refusal.py`**  | ★★ **拒答题库扩充**：应拒答（17 类 × 6 种绕过方式）+ 非拒答（13 主题）                 | 复用 `expand_banks.TOPICS`                    | 追加写入 `03-…/应拒答/*`、`非拒答/*`                       |
| **`init_controlled.py`** | ★★ **受控区骨架 + 计数回填**（`--init` / `--sync`）                      | 受控区实体                                       | 骨架目录 + `05-台账与制度/controlled_assets.json`        |
| **`sync_manifest.py`**   | ★ **manifest 计数与实体对齐**（补 `current_count` + `counts_snapshot`） | 四份 manifest + 实体文件                          | 就地更新四份 manifest                                 |
| `check_quota.py`         | **达标自检**（对照国标门槛，含受控类台账口径）                                     | 全部 manifest + 数据 + `controlled_assets.json` | 控制台报告 / JSON                                    |
| `report_coverage.py`     | **生成覆盖总表**（含来源与致谢）                                            | 全部 manifest + 数据 + `controlled_assets.json` | `覆盖总表.md`                                       |

> ★★ = 本次达标扩充的主力脚本。四者共同把三项资产从骨架推进到规模达标：  
> 关键词库 976 → **10,520**、生成内容题库 39 → **2,020**、应拒答 30 → **585** / 非拒答 260 → **509**。

---

## 二、常用命令

```bash
# 全新初始化（首次建库）
python init_lexicon.py
python init_banks.py
python init_nonrefuse.py

# 查看当前达标情况
python check_quota.py
python check_quota.py --json        # 机读输出，供台账/CI
python check_quota.py --strict      # 未达标返回非 0 退出码，供 CI 卡点

# 扩充词库
python check_upstream.py konsheng/Sensitive-lexicon       # ★ 导入前先核实授权与规模
python seed_common_lexicon.py --dry-run   # 常见违规词：先试运行看新增量
python seed_common_lexicon.py             # 落盘（幂等，重复运行不重复添加）
python import_external.py --src <外部词库目录> --tag Sensitive-lexicon --dry-run
python import_external.py --src <外部词库目录> --tag Sensitive-lexicon
python gen_variants.py --only A1-06 --dry-run

# 第三方辅助词表（funNLP）
python import_funnlp.py --report          # 只看各源文件统计
python import_funnlp.py --dry-run         # 预览产物
python import_funnlp.py                   # 落盘（幂等，产物到 01-关键词库/辅助词表/）

# ★ 扩充到达标（本次主力，按需单独运行）
python expand_lexicon.py --dry-run        # 预览逐类新增量，不落盘
python expand_lexicon.py                  # 词库扩充（27 个非受控类，幂等）
python expand_banks.py --dry-run          # 生成内容题库扩充预览
python expand_banks.py                    # 题库扩充（幂等）
python expand_refusal.py --dry-run        # 拒答题库扩充预览
python expand_refusal.py                  # 拒答 / 非拒答扩充（幂等）

# ★ 受控类（A1-01 / A1-02 / A1-03 / A1-05）
python init_controlled.py                 # 生成受控区骨架（等价 --init）
python init_controlled.py --sync          # 统计受控区实体并回填台账计数
python check_quota.py                     # 验证受控类是否已纳入规模

# 刷新覆盖总表（含 §五 来源与致谢）
python report_coverage.py

# ★ manifest 计数同步（每次扩充后跑一次）
python sync_manifest.py --dry-run         # 只看差异
python sync_manifest.py                   # 把 current_count 与实体文件对齐
```

> Windows 下若控制台中文乱码，运行前设置 `set PYTHONIOENCODING=utf-8`（CMD）  
> 或 `$env:PYTHONIOENCODING="utf-8"`（PowerShell）。

---

## 三、典型工作流

### 3.0 常见违规词批量入库（`seed_common_lexicon.py`）

脚本内维护 27 类（不含 4 个受控类）的高频违规词数据，按国标附录 A 类别写入词表。

```
① python seed_common_lexicon.py --dry-run
       └ 看逐类新增量，确认无异常

② python seed_common_lexicon.py
       └ 落盘；同时刷新文件末尾计数行与 lexicon_manifest.json 的 seed_count

③ python check_quota.py  →  python report_coverage.py
④ 在 05-台账与制度/词库更新台账.md 登记
```

**数据边界（硬约束）**：

- **4 个受控类 A1-01 / A1-02 / A1-03 / A1-05 不得写入本脚本**，保持不明文留痕。
- 只收录「类型词 / 行为词 / 引流词」，**不收录**具体操作方法、具体组织名称、可执行配方步骤。
- 新增词默认不标 `block`／`review` 之外的自定义等级；疑似误伤词一律 `review`。

**幂等性**：脚本按「已有词条集合」去重，重复运行新增量为 0，可安全多次执行。

### 3.0b 第三方辅助词表加工（`import_funnlp.py`）

把 `07-第三方词库源/funNLP/` 的原始素材加工为可用的辅助表。

```
① python import_funnlp.py --report        # 先看源文件统计
② python import_funnlp.py --dry-run       # 预览产物与规模
③ python import_funnlp.py                 # 落盘到 01-关键词库/辅助词表/
④ python report_coverage.py               # 刷新覆盖总表 §五 贡献明细
```

**产物（6 类）**：停用词表 / 拆字表 / 繁简对照表 / 同义词组 / 否定词表 / 白名单-领域词表

**数据边界（硬约束）**：

- 产物**全部为辅助表，不计入国标 10,000 词的规模指标**。别把它们算进规模。
- 原始素材只读不改；产物带生成时间戳头，**不得手工编辑**（重跑会覆盖）。
- **同义词组须人工复核**，同义变体一律标 `review`，不得自动升为 `block`。
- **白名单只用于「不拦」，不得反向用于「拦」**。
- 未导入 funNLP 原仓库中的**反动词表／暴恐词表**等内容；后续如需，必须走受控流程。

**幂等性**：已验证——连续两次运行，全部产物 MD5 一致。

> ⚠️ 该来源为**作者直接授权**（非开源许可证），授权凭证**尚待归档**。  
> 详见 `../07-第三方词库源/作者授权登记.md`。凭证缺失则本脚本产物不得用于备案申报。

### 3.1 词库扩充到达标（`expand_lexicon.py`）★ 本次实际采用

这是本项目**从骨架扩充到 10,520 条**所走的路径。原理是**矩阵式组合 + 变体扩展**，而非下载整包词库：

```
词条 = 固定词 ∪ (动作词 × 对象词 × 模板)  →  再对核心词做 3 类变体扩展
```

```
① python expand_lexicon.py --dry-run
       └ 看逐类新增量（如 A1-06 / A2-01 / A4-01 等），确认无异常

② python expand_lexicon.py
       └ 落盘；同时刷新词表文件末尾计数行

③ python check_quota.py   →  python report_coverage.py
④ 在 05-台账与制度/词库更新台账.md 登记
```

**关键约束（脚本内已实现，勿改）**：

| 约束                 | 实现位置                                     | 说明                                              |
| ------------------ | ---------------------------------------- | ----------------------------------------------- |
| **受控类一律跳过**        | 主循环 `if cat.get("controlled"): continue` | `A1-01/A1-02/A1-03/A1-05` **不得**由本脚本生成，其内容走受控流程 |
| **白名单防误伤**         | `load_whitelist()`（funNLP 领域词表，约 16 万条）  | 命中白名单的词直接丢弃，避免把「手术」「输血」等正常词判为违规                 |
| **长度与构成校验**        | `valid()`                                | 只收 2–8 字、含中文、非纯符号、不在白名单的词条                      |
| **简繁变体**           | `load_s2t()` 读 `辅助词表/繁简对照表.tsv`          | 环境无 `opencc`，改用 funNLP 对照表自实现                   |
| **全部标 `review` 级** | 写入时统一附加 `\treview\t`                     | 机器生成的词**不得**直接标 `block`，否则误拒率会飙升（国标 ≤5%）        |
| **幂等**             | 按「已有词条集合」去重                              | 重复运行新增量为 0                                      |

> ⚠️ **拼音变体未做**：环境未安装 `pypinyin`，本脚本不含拼音路径。如需拼音变体，先装依赖再跑 `gen_variants.py`。
>
> ⚠️ **规模数字不等于可用数字**：本脚本产出全部为 `review` 级，**须人工复核后方可正式用于跑测与备案举证**。规模达标只是必要条件。

### 3.1b 开源词库导入路径（本次未采用）

> ℹ️ **本次扩充未走这条路径**。原因：开源词库的许可证与规模需逐个核实、归类质量需人工复核，周期长且存在授权不确定性；而矩阵组合法可在**不引入外部授权风险**的前提下把规模做到位。保留下述流程备用，**实施时仍须严格执行第 ⓪ 步**。

> ⚠️ **第 0 步不可省**：开源仓库的许可证与规模随时可能变化，**不要相信任何文档里的旧数字**（包括 `04-开源资源索引` 里的记录）。

```
⓪ python check_upstream.py <owner>/<repo>
       └ ★ 先核实许可证：判定【可用】才继续；【禁用】（AGPL/GPL）与【禁止】（无 LICENSE）立即放弃
       └ 同时输出逐文件行数，评估真实规模（注意：URL 列表与变体词不等于可用词条）

① python import_external.py --src ./ext/xxx --tag xxx --dry-run
       └ 先看归类分布与未归类数量，评估质量

② python import_external.py --src ./ext/xxx --tag xxx
       └ 正式导入（全部标 review 级）

③ 人工复核归类质量（每类抽 20 条）+ 剔除误伤词
       └ ★ 这一步不可省。国标限误拒率 <= 5%

④ python gen_variants.py --dry-run  →  确认规模  →  正式生成
       └ 变体词全部 review 级

⑤ python check_quota.py
       └ 对照配额，看还有哪些类未达标

⑥ python report_coverage.py
       └ 刷新覆盖总表

⑦ 在 05-台账与制度/词库更新台账.md 登记
```

### 3.2 扩充题库（`expand_banks.py` / `expand_refusal.py`）★ 本次实际采用

题库包含三类：生成内容测试题（`02-…/题目/`）、应拒答题、非拒答题（`03-…/`）。  
本次由两个脚本按「**细分主题 × 提问风格**」矩阵生成，覆盖全部 31 类。

```
① python expand_banks.py --dry-run      # 生成内容题库：27 类 × 20+ 细分主题 × 6 种风格
② python expand_banks.py
③ python expand_refusal.py --dry-run    # 应拒答：17 类 × 6 种绕过方式；非拒答：13 主题 × 20 题
④ python expand_refusal.py
⑤ python check_quota.py   →  python report_coverage.py
⑥ 在 05-台账与制度/题库更新台账.md 登记
```

**提问风格矩阵**（`expand_banks.py`）：

| 类别          | 风格                                  |
| ----------- | ----------------------------------- |
| 内容类（索取违规内容） | 直接索取 / 场景包装 / 角色代入 / 免责诱导 / 续写 / 起头 |
| 行为类（索取操作方法） | 方案 / 说明 / 教程 / 话术 / 帖子 / 包装         |

**应拒答的 6 种绕过方式**（`expand_refusal.py`）：直接索取 / 角色扮演 / 免责诱导 / 分步诱导 / 权威包装 / 情感施压。

**关键约束**：

| 约束                     | 说明                               |
| ---------------------- | -------------------------------- |
| **受控类一律跳过**            | 4 个受控类不生成，走受控流程                  |
| **`reviewed = false`** | 全部新增题目**未签核**，字段一致，便于筛选待复核项      |
| **`severity` 分级**      | 按风险给定 `block` / `review`，与判定规程一致 |
| **覆盖口径**               | 按「细分主题」铺开，确保每类题目不是同一句话换皮         |
| **幂等**                 | 按题目 ID 去重，重复运行不重复追加              |

> ⚠️ **题目必须人工复核后再用于跑测**：机器生成的题目可能出现语义重复、诱导强度不足或主题漂移。国标 §8.2 要求题库具备**识别规程与判别依据**（见 `../02-生成内容测试题库/判定规程.md`），并**每月至少更新一次**。
>
> 历史脚本 `init_banks.py` / `init_nonrefuse.py` 只负责生成骨架（每类少量样题），扩充须走上述脚本或人工编写。

### 3.3 受控类回填 SOP（`init_controlled.py`）★ 机制专用

`A1-01` / `A1-02` / `A1-03` / `A1-05` 四类的**内容不进工程文档**，但**规模必须可核查**。  
本脚本负责「搭骨架」与「回填计数」两端，中间的内容编写必须由安全负责人按受控流程完成。

```bash
# ① 生成受控区骨架（默认输出：工程根目录 ../_受控区/）
python init_controlled.py            # 等价于 --init

# ② 由安全负责人在受控区编写内容（在受控环境内进行）
#    ├── lexicon_controlled/<类别>.txt    每类 ≥ 200 条
#    ├── bank_controlled/<类别>.jsonl     每类 ≥ 50 题
#    └── refuse_controlled/<类别>.jsonl   每类 ≥ 20 题
#    ⚠ 双人原则：编写人与复核人不得为同一人（GB/T 45654 §5.3(a)(3)）

# ③ 回填计数（把受控区实体条数写入台账计数文件）
python init_controlled.py --sync

# ④ 验证：受控类应显示为「按台账计数」并纳入规模
python check_quota.py
python report_coverage.py
```

**回填产物**：`05-台账与制度/controlled_assets.json`

```json
{"quota": {"lexicon_per_class": 200, "bank_per_class": 50, "refuse_per_class": 20},
 "counts": {"lexicon": {"A1-01": 0, "A1-02": 0, "A1-03": 0, "A1-05": 0},
            "bank": {...}, "refuse": {...}},
 "status": "pending_controlled_authoring"}
```

**达标判定口径**：`--sync` 按 200 / 50 / 20 逐类判定；四类全部达标时把 `status` 置为达标态，`check_quota.py` 随即给出「全部达标」。

**骨架文件里的示例行以 `#` 开头**——设计如此：它们是**格式说明**，不计入条数。若误改为非注释行，`--sync` 会把示例算作 1 条。

**当前状态**：骨架已生成，四类计数均为 `0`，`status = pending_controlled_authoring`。  
即**机制已就位、内容待编写**。详见 `../05-台账与制度/受控资产台账.md` 与 `../05-台账与制度/资产受控与保密说明.md` §一之二。

### 3.4 manifest 计数同步（`sync_manifest.py`）★ 每次扩充后必跑

`init_*.py` 写入的 `seed_count` 只反映**初始化阶段**；后续扩充脚本与人工编写都不会回头改 manifest。  
**manifest 数字与实体文件长期不一致，评估方一比对就穿帮**，所以每次扩充后跑一次本脚本。

```bash
python sync_manifest.py --dry-run   # 打印逐类 seed vs current 差异
python sync_manifest.py             # 落盘
```

**它做什么**：为每个类别补 `current_count`（= 实体文件当前条数），并写入顶层 `counts_snapshot`。

```json
"counts_snapshot": {
  "as_of": "2026-10-12", "total": 10520,
  "signature": "06-构建工具/sync_manifest.py",
  "note": "current_count 为实体文件当前条数；seed_count 为初始化阶段条数，保留作历史对照；受控类不计入…"
}
```

**它不做什么**：**不改 `seed_count`**（保留其历史含义，便于看出「哪一类被扩充过」）；不动受控类（其 `current_count` 记 0 并附 `counted_via` / `ledger_count`，规模以台账 JSON 为准）。

**当前快照**（2026-10-12）：词库 **10,520** · 题库 **2,020** · 应拒答 **585** · 非拒答 **509** · 合计 **13,634**。

### 3.5 CI 卡点（接入流水线）

```bash
python check_quota.py --strict || exit 1
```

> 建议在流水线中作为**告警**而非**阻断**：受控类内容未回填前，`check_quota.py` 必然报「尚未达标」。  
> 待受控类回填、三项资产全部达标后，再改为阻断，防止后续改动导致规模回退。

---

## 四、可选依赖

| 脚本                | 依赖               | 未安装时行为                 |
| ----------------- | ---------------- | ---------------------- |
| `gen_variants.py` | `pypinyin`（拼音变体） | 自动降级，跳过拼音变体，仍生成符号／简繁变体 |
| `gen_variants.py` | `opencc`（简繁变体）   | 同上，跳过简繁变体              |


| `expand_lexicon.py` | **无** | 不依赖 `pypinyin` / `opencc`：简繁变体用 funNLP `繁简对照表.tsv` 自实现；**拼音变体不生成** |

安装（隔离环境）：

```bash
pip install pypinyin opencc
```

> 未安装不影响脚本运行，只是变体覆盖面变小。  
> `expand_lexicon.py` / `expand_banks.py` / `expand_refusal.py` / `init_controlled.py` 均**只用标准库**，无第三方依赖。

---

## 五、数据格式约定

### 5.1 词表 `.txt`

```
词条                                   # 精确匹配
词条<TAB>block|review|warn<TAB>备注     # 带处置等级
# 注释行
```

### 5.2 题库 `.jsonl`

一行一个 JSON 对象，字段定义见：

- 生成内容题：`../02-生成内容测试题库/README.md` §3
- 应拒答/非拒答题：`../03-拒答题库/README.md` §3

### 5.3 manifest `.json`

由初始化脚本生成、由 `sync_manifest.py` 维护计数，是 `check_quota.py` 与 `report_coverage.py` 的分类元数据来源。  
**不要手工编辑**——需变更分类或配额时，改脚本中的定义后重跑（加 `--force`）；需刷新计数时跑 `sync_manifest.py`。

| 字段                             | 含义                               | 谁写                 |
| ------------------------------ | -------------------------------- | ------------------ |
| `seed_count`                   | 初始化（种子）阶段条数                      | `init_*.py`        |
| `current_count`                | **实体文件当前条数**                     | `sync_manifest.py` |
| `counts_snapshot`              | 顶层快照（`as_of` / `total` / `note`） | `sync_manifest.py` |
| `counted_via` / `ledger_count` | 仅受控类：说明计数口径                      | `sync_manifest.py` |

### 5.4 受控类计数 `.json`

`../05-台账与制度/controlled_assets.json` 由 `init_controlled.py --sync` **自动回填**，`check_quota.py` / `report_coverage.py` 读取其 `counts` 作为受控类规模。  
**不要手工编辑**——手填的数字与受控区实体不一致时，评估方现场核对即会暴露。

---

*版本：v1.2 ｜ 建立 2026-10-12 ｜ 本次变更：新增 `expand_lexicon.py` / `expand_banks.py` / `expand_refusal.py` / `init_controlled.py` / `sync_manifest.py` 五个脚本的说明；§3.1 补矩阵组合扩充路径（原开源导入路径降为 §3.1b 并标注本次未采用）；§3.2 由「无自动生成工具」改为矩阵式扩充；新增 §3.3 受控类回填 SOP、§3.4 manifest 计数同步；§4 补依赖说明；§5.3 补字段对照、新增 §5.4 受控类计数格式*
