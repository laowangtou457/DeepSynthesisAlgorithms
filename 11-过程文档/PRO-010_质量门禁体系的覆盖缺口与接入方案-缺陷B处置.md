# PRO-010 · 质量门禁体系的覆盖缺口与接入方案（缺陷 B 处置）

> **性质**：方案件（**未实施任何改动**）—— 涉及 `T-086` 门禁体系设计口径，须项目方裁决。
> **触发**：项目方 2026-11-03 提出「缺陷 B：`total_duration_ms` ≠ Σ 各镜时长（45000 vs 30000）」，
> 并指明「缺陷 B 的修复点不是模板，而是**『`content_adequacy` 的发现未接入 `quality_gate` 判定』**
> （工程侧缺口）」。
> **编号**：`PRO-010`（`CM-002` §2 `PRO` 类下一起始号）；配套登记 `ISSUE-053`、任务 `T-093`。
> **版本**：V1.0（2026-11-03）

---

## 0 本文用途与边界

1. **用途**：给出「缺陷 B」在工程侧的真实成因链、**逐条核实项目方给出的四步分析**（其中两处需订正），
   并给出**门禁体系侧的修改方案**（含三个待裁决问）。
2. **边界**：**不改模板**（项目方已明确「修复点不是模板」）；**不改 `validate_output.py` 的 `R1`~`R40` 判据**
   （判据水位不动）；**不新增交付契约字段**。
3. ⚠️ **本文所有结论均回原文/实测取证**，行号与计数均为 2026-11-03 盘上实测值。

---

## 1 结论速览

| # | 项目方给出的分析 | 核实结论 |
| --- | --- | --- |
| ① | 剧本层不自洽，`R4`／`R6` **根本没跑**，因 `quality_gate_stages` 默认只含 `storyboard,shot_prompt` | ✅ **成立**（实测见 §2.1／§3.1） |
| ② | 分镜层忠实承继 ⇒ `total` 按「镜数×上限」＝ 3×15000＝45000 | ✅ **成立**（实测见 §3.2） |
| ③ | `content_adequacy` 探测到了（`storyboard_duration_sum_mismatch`）★ 但 `ok=null` ⇒ **发现未接入 `quality_gate` 判定** ⇒ 缺陷漏过 | ⚠️ **前半成立、后半需订正**（见 §2.2）——**「发现未接入」成立**，但「缺陷漏过」的机制不是「`ok=null`」，而是**该段 `ok` 判定根本没被调用**（`applies_to('script')=False` ⇒ 编排层 `break`，`quality_gate.check` 从未执行） |
| ④ | 交付层 `R31` 守恒把它**修正成 15000** ⇒ 掩盖了上游问题 | ❌ **不成立**（实测见 §2.3）—— `R31` 与 `validate_pack.py` **只报错、不修正**；工程侧**无任何代码改写 `total_duration_ms`**（`pack_meta.apply_service_truth` 明写「模型可影响字段一字不改」）。真实机制是：**分镜层的 `R14` 已经报了 `Σ≠total`**，但该失败**在 `enforce=false` 下只留痕不阻断** ⇒ 缺陷不是被掩盖，而是**被降级成了告警** |

> ⭐ **一句话**：缺陷 B 的工程侧根因**不是「探测发现未接入判定」，而是「该段的门禁判定压根没被调用」**
> ——`quality_gate_stages` 默认值把 `script`／`synopsis` 排除在门禁之外，
> 而 `config.py` 的注释给的理由（「上游承继、在分镜段会被同一判据再次抓到」）**经实测不成立**（见 §2.4）。

---

## 2 事实核查（逐条实测，2026-11-03）

### 2.1 ① 剧本层无门禁 —— 成立

实测（构造 `1 幕 1 场 / est=15 / total=125` 的 `script_v1` 产物）：

```
quality_gate_stages = storyboard,shot_prompt
applies_to('script')     = False
applies_to('storyboard') = True
```

⇒ 编排层 `dialogue_service.py` L874 `gate_applies = quality_gate.applies_to(tpl_stage)` 为 `False`
⇒ L998 `if not gate_applies: break` ⇒ **`quality_gate.check` 从未被调用**。

**绕过 `applies_to` 强行跑同一产物**，判据**完全能抓**：

```
ok=False  checked=True  engine_checks=2
errors:
  script · R5 REQUIRED_KEYS（script）：缺 ['title','logline','genre','style_bible',…]
  script · R1 PURPOSE_ENUM：越界/缺失 1 处 → acts[0].scenes[0].purpose 缺失
  script · R4 EST_SECONDS_SUM：Σest_seconds=15 ≠ total_est_seconds=125   ★
  script · R6 ACT_STRUCTURE：幕数应为 3，实际 1                          ★
  script · R20 DIALOGUE_TYPE_ENUM：越界/缺失 1 处
retryable = 上述 5 项全部（分类正确，无一落入 non_retryable）
```

⇒ **`R4`／`R6` 判据存在、正确、且被正确归类为「可重试」**。缺的只是**调用**。

### 2.2 ③ 「探测发现未接入判定」—— 成立；「`ok=null` ⇒ 缺陷漏过」—— 需订正

**成立的部分**：`content_adequacy` 确实探测到了，且**未接入** `quality_gate`：

```
content_adequacy.assess("storyboard", …)
  → ok=False  findings=['storyboard_duration_sum_mismatch']
  metrics={'shots':3,'sum_shot_ms':45000,'total_duration_ms':30000, …}
```

而 `content_adequacy` 的 7 个 finding code 在 `validate_output.py` 中**全部零命中**
（`script_total_mismatch`／`scene_below_duration_floor`／`storyboard_duration_sum_mismatch`／
`unit_size_out_of_range`／`scene_coverage_incomplete`／`script_no_scenes`／
`synopsis_total_missing_or_nonpositive`）⇒ **它们是独立于 `R` 判据族的另一套口径**，
按 `T-085` 的裁决（2026-10-16）「**只判不拦**」**刻意不进入门禁**。

⚠️ **但 7 个 code 中有一部分在 `R` 族里有等效判据**（逐条核对 `validate_output.py`）：

| adequacy code | 等效 `R` 判据 | 状态 |
| --- | --- | --- |
| `script_total_mismatch` | **`R4` EST_SECONDS_SUM**（L536） | 有等效，但**只在 `script` 形态跑**，而 `script` 不在门禁段 ⇒ **实际不跑** |
| `scene_below_duration_floor` | **`R22` SCENE_DURATION_FLOOR**（L731） | 同上 |
| `unit_size_out_of_range` | **`R10` UNIT_SIZE**（L850） | 有等效，`storyboard` 段**已在跑** |
| `storyboard_duration_sum_mismatch` | **`R14` DURATION_SUM** | 有等效，`storyboard` 段**已在跑**（见 §2.4） |
| `script_no_scenes` | `R6` 近似（幕/场非空） | 同 `R4` |
| `synopsis_total_missing_or_nonpositive` | — | 无等效 |
| **`scene_coverage_incomplete`** | **无等效** | ⭐ **唯一不可替代的判据**（详见 §2.5） |

**需订正的部分**：「`ok=null` ⇒ 缺陷漏过」的机制表述不准。
实测 `content_adequacy` 对同一产物返回 **`ok=False`**（不是 `null`）；
而 `quality_gate` 侧的 `ok` 为 `None` 的原因是**根本没调用**（`gate_applies=False` ⇒
`quality_verdict` 保持 `None` ⇒ 留痕 `quality_gate_ok=None`）。
⇒ **准确表述**：缺陷漏过是因为**「这一段没有门禁判定」**，而非「判定了但结论为 null」。

### 2.3 ④ 「交付层 `R31` 修正成 15000、掩盖上游问题」—— 不成立

实测三处：

1. **`R31` 是「双守恒」判据，只报错不修正**（`validate_output.py` L1597~L1631）：
   ```
   problems.append(f"meta.total_duration_ms={total} ≠ Σ各镜 duration_ms={s}")
   problems.append(f"镜数与上游不一致：上游 {len(up_shots)} vs 本层 {len(shots)}")
   problems.append(f"与上游逐镜不一致（镜号或时长被改动）→ {diff[:6]}")
   problems.append(f"总时长与上游不一致：上游 {up_total} vs 本层 {total}")
   ```
   命中即 `err(...)` ⇒ **报错，无任何赋值/归一/改写语句**。
2. **交付门禁 `validate_pack.py` 同样只报错**：L262~L267
   `f"meta.total_duration_ms={total} 与镜头时长合计 {ssum} 不一致"` ⇒ 产出 `BLOCK`，**不修正**。
3. **工程侧无任何代码改写 `total_duration_ms`**：全仓 `grep` 仅命中**读取**与**判据**，
   `pack_meta.apply_service_truth` 的 docstring 明写
   「⚠️ **模型可影响字段一字不改**（`title`／`total_duration_ms`／`notes`／`shots`／`units`／…）」。

⇒ **真实机制是「被降级成告警」而非「被修正掩盖」**：分镜层 `R14` 已报
`storyboard · R14 DURATION_SUM：Σduration_ms=45000 ≠ total_duration_ms=30000`，
但因 `quality_gate_enforce=false`（分阶段上线默认）⇒ 只留痕、不阻断。

### 2.4 ⚠️ `config.py` 给「上游段不设闸」的理由经实测不成立

`core/config.py` L134~L137 的注释原文：

> ⚠️ 默认只对 `storyboard`（分镜）与 `shot_prompt`（交付包）两段启用：
> `ISSUE-038` 的实测失败**全部**落在分镜段及其下游；梗概／剧本段虽有 `R4` 同源问题，
> 但那是**上游承继**、在分镜段会被**同一判据**再次抓到 ⇒ 对上游段重复设闸只增加重试成本。

**实测反证**：`script` 与 `storyboard` 是**两把不同的锁**，不是同一把：

| 层 | 判据 | 判的对象 | 在另一层会重跑吗 |
| --- | --- | --- | --- |
| 剧本层 | `R4` | `total_est_seconds` vs Σ**场** `est_seconds` | ❌ 分镜层跑的是 `R14`，判的是 `total_duration_ms` vs Σ**镜** `duration_ms` |
| 剧本层 | `R6` | `acts` 恰为 3 幕 | ❌ 分镜层**无对应判据**（分镜层不承载幕结构） |
| 分镜层 | `R14` | `total_duration_ms` vs Σ**镜** `duration_ms` | ❌ 剧本层**无对应判据** |

⇒ **剧本层 `R4` 失败不会被分镜层 `R14` 抓到**（不同字段、不同层级、不同单位）。
项目方实测到的「分镜层忠实承继 ⇒ total=45000」恰恰**证明了这一点**：
剧本层的错误**被算术继承**到了分镜层，但**继承后分镜层自己的 `R14` 只审自己的 Σ 与 total**，
审不出「这个 total 是从上游错误继承来的」。

⇒ ⚠️ **「上游段重复设闸只增加重试成本」这一理由不成立**（成本论证有效，但**前提**「会被同一判据抓到」是错的）。

### 2.5 ⭐ `scene_coverage_incomplete` 是唯一无等效判据、且不可替代

实测：`storyboard` 段**已在跑**的 `R10`／`R14`／`R19` 全部只审**段内**，
**无任何判据审「分镜是否覆盖了剧本的全部场次」**。
而这恰是 `T-085`／`ISSUE-045` 实测的**最严重缺陷形态**：
「`r4` 分镜 **3 镜只覆盖第 1 场**、第 2~5 场**全部漏拍**，而 `unspecified` 里
**没有任何**漏拍说明 ⇒ 模板最核心的『动作守恒』硬约束**静默失效**」。

⇒ 这是 `content_adequacy` 相对 `R` 族的**唯一净增能力**，
也是「`content_adequacy` 应否接入门禁」这个问题的**真正价值所在**。

---

## 3 根因链（三层，缺一不可）

```
① 配置层：quality_gate_stages = "storyboard,shot_prompt"（config.py L138）
   │  ⇒ applies_to('script') = False
   │  ⇒ 编排层 L997「if not gate_applies: break」
   ▼
② 调用层：quality_gate.check() 对 script/synopsis 段从未执行
   │  ⇒ R4/R6/R22/R5/R1/R20 全部不跑（实测：强行跑则全部命中）
   │  ⇒ 重试回路（quality_gate_retry_enabled）对上游段完全不生效
   ▼
③ 接入层：content_adequacy 的 findings（ISSUE-045 裁决「只判不拦」）
   ⇒ 不进 retryable / non_retryable ⇒ 不触发重试、不进阻断判定
   ⇒ 其中 scene_coverage_incomplete 在 R 族无等效判据 ⇒ 永久只留痕
```

⚠️ **② 与 ③ 是两个独立缺口**：即使把 ③ 接上（adequacy 进判定），
`script` 段仍**不会**被门禁判（`applies_to` 仍为 `False`）⇒ **必须同时解 ① 与 ③**。

---

## 4 修改方案（三条候选，**推荐 A+B 并行**）

### 候选 A · 扩展门禁段覆盖（解缺口 ①）

**改动**：`core/config.py` 的 `quality_gate_stages` 默认值
`"storyboard,shot_prompt"` → `"synopsis,script,storyboard,shot_prompt"`。

**收益**：剧本层 `R4`／`R6`／`R22` 立即生效（判据已在、已在离线跑、分类已验证为 `retryable`）。

**代价与风险**（**须如实告知项目方**）：
- 上游段单段耗时远小于下游（`storyboard` 约 130 s／`shot_prompt` 约 304 s），
  但**上游段失败会导致整链重跑** ⇒ 总耗时增量须实测。
- ⚠️ **上游段直出率可能同样为 0** ⇒ 若 `quality_gate_retry_enabled=true`，
  上游段每次都会走满重试 ⇒ **成倍放大耗时**。这与 `config.py` L152~L158
  已写的「为什么默认关重试」是同一顾虑，**候选 A 不改变该顾虑**。
- ⚠️ **`R6` 的口径存疑**：`R6` 要求「`acts` **恰为 3 幕**」——这是**固定 3 幕**的硬约束。
  若本期支持「客户自带素材」路径（`SW-008` 并行入口层）而幕数不固定，
  则 `R6` 会**误报**。⇒ **候选 A 若采纳，须先核 `R6` 是否仅对 `SW-004`~`SW-007` 链路生效**。

**最小风险变体 A′**：**只加 `script`**（不加 `synopsis`）——
`synopsis` 层 `content_adequacy` 只有一条「`total_est_seconds` 存在且为正」，
无等效 `R` 判据，价值最低、风险相同 ⇒ **建议先不加**。

### 候选 B · `content_adequacy` findings 接入门禁判定（解缺口 ③）

**改动**：`quality_gate.py` 的 `check()` 增加一路输入——`content_adequacy` 的 findings；
按**分层**折算为 `retryable`：

| finding code | 折算 | 理由 |
| --- | --- | --- |
| `scene_coverage_incomplete` | **retryable**（模型可影响：多写几场） | ⭐ 无等效 `R` 判据，价值最高 |
| `script_total_mismatch` | retryable | 与 `R4` 同源（**若采纳 A 则重复，须去重**） |
| `storyboard_duration_sum_mismatch` | retryable | 与 `R14` 同源（**须去重**） |
| `unit_size_out_of_range` | retryable | 与 `R10` 同源（**须去重**） |
| `scene_below_duration_floor` | retryable | 与 `R22` 同源（**须去重**） |
| `script_no_scenes` / `synopsis_total_missing_or_nonpositive` | retryable | 无等效判据 |

**去重规则**（**必须**，否则同一失败被计两次、重试成本翻倍）：
> 同一阶段同一 finding，若其**等效 `R` 判据已在本次判定中报出**，则**只保留 `R` 判据那一条**，
> adequacy 那条降级为「佐证」（进留痕明细，不进 `retryable` 计数）。

**留痕要求**（沿用本工程既有纪律）：
- `quality_gate` 的 `QualityVerdict` 增 `adequacy_findings` 字段（**与 `engine_errors` 分开记**，不合并成一个布尔）；
- `checked`／`ok` **分开记**，且 `ok` 仍是三态（`True`／`False`／`None`）；
- 编排层日志 `content_adequacy_findings` 与 `quality_gate_retryable` **两组字段并存**
  ——**结构过了 ≠ 内容够了**（`T-085` 已确立此纪律）。

### 候选 C · 只把 `content_adequacy` 接进**留痕**（最小改动，不改判定）

**改动**：仅在 `quality_gate` 的 `as_record()` 里增 `adequacy_findings` 字段（读现有探测结果，不参与判定）。

**收益**：证据链完整（能举证「这段内容不足量，且已知原因」），**零判定行为变化**、零耗时影响。
**局限**：**不解决缺陷 B**（缺陷仍漏过），只让漏过**可见**。

> ⚠️ **候选 C 单独采纳 = 「如实暴露」而非「修复」**——与 `T-085`（2026-10-16）的裁决一致，
> 但**不满足**项目方「缺陷 B 需修复」的要求。

---

## 5 推荐方案与不裁决时的实务约束

### 5.1 推荐：**A′ + B + C 三件并行**（分两个批次）

| 批次 | 内容 | 理由 |
| --- | --- | --- |
| **批次 1** | **候选 B（去重后接入）** ＋ **候选 C（留痕字段）** | **不改变门禁段覆盖** ⇒ **不引入上游段重试成本**；先让 `content_adequacy` 的结论**进判定与留痕**，其中 `scene_coverage_incomplete`（无等效 `R`）**立即获得阻断能力** |
| **批次 2** | **候选 A′（`quality_gate_stages` 加 `script`）** | 依赖批次 1 的实测数据（上游段重试后通过率）；**须在 `enforce` 仍为 `false` 时先做「只判不拦」的观测** |

⚠️ **批次 2 的前置**：
1. `R6`「恰为 3 幕」的口径须先核（§4 候选 A 的风险项）；
2. 须先在 `enforce=false` 下量出**上游段的重试后通过率**（与 `T-086` 已有口径一致：
   「实测直出率 `passed=true` ＝ 0/3」——若上游段同为 0，则开闸即全拒）。

### 5.2 不裁决时的实务约束（**重要**）

1. **`quality_gate_enforce` 必须保持 `false`**（当前即 `false`）。
   理由：缺陷 B 在 `storyboard` 段**已被 `R14` 抓到**，只是因 `enforce=false` 未阻断；
   若此刻翻 `true`，`storyboard` 段（直出率 0/6）**必然全线被拒** ⇒ 链路不可用。
2. **不得以「后处理修补」兜底**（`T-086` 硬约束原文）：
   `total_duration_ms` 等模型可影响字段**一律不得**由服务层改写
   （`pack_meta.apply_service_truth` 的既有纪律）。
3. **缺陷 B 当前应按「已知缺陷、已留痕、未阻断」如实登记**——
   落点建议：`PM-001` §8 新增 `ISSUE-053`，并在 `T-086` 行注明「`enforce=true` 的前置条件」。

---

## 6 待项目方裁决事项汇总

| # | 事项 | 选项 | 编制侧建议 |
| --- | --- | --- | --- |
| 1 | **是否解缺陷 B** | 解 ／ 不解（维持登记） | ⭐ **建议解** —— 它让「上游缺陷静默继承到下游」，属**功能性缺陷**而非优化项；且**分镜层 `R14` 已经在报同一个问题**，说明判据侧已有共识 |
| 2 | **门禁段覆盖** | A（加 `script`+`synopsis`）／**A′（只加 `script`）**／C（不加） | 🔶 **建议 A′** —— `synopsis` 层无等效判据、价值最低；且须先核 `R6` 的「恰为 3 幕」是否与「客户自带素材」路径冲突 |
| 3 | **`content_adequacy` 接入方式** | B（进判定＋去重）／C（仅留痕）／B+C | ✅ **建议 B+C 并行** —— B 解缺陷、C 保证据链；**去重规则必须同时落**，否则同一失败被计两次、重试成本翻倍 |
| 4 | **是否先跑「只判不拦」观测** | 先观测 ／ 直接开 | ⚠️ **建议先观测** —— 与 `T-086` 既有方法论一致（直出率 0/6 时开闸即全拒）；观测期内 `enforce` 保持 `false` |
| 5 | **是否走外部评审** | 走 ／ 不走 | 🔶 **建议不走**（属**工程侧接线缺口**，不改判据、不改契约、不改模板）—— 但须在 `DEV` 留痕中写明「**门禁段覆盖扩大**是本工程首次，属口径变更」并登记进 `CM-003` 追溯矩阵 |

---

## 7 明确不做（边界）

- ❌ **不改模板**（`TPL-` 系列零改动）—— 项目方已明确「修复点不是模板」；
  ⚠️ 且 `T-087` 已在做资产侧提质（`R25` 已闭环），两条线须**分别留痕、不混记**。
- ❌ **不改 `validate_output.py` 的 `R1`~`R40`** —— 判据水位**保持 40 条不变**，
  `content_adequacy` 仍是**留痕级探测、不计入 `R` 计数**（`CM-002` §7 `V1.16` 的既有口径）。
- ❌ **不改交付契约**（`CFG-006` schema、`SPEC-008` 零改动）—— 本缺口是**判定接线**，与契约无关。
- ❌ **不翻转 `quality_gate_enforce`** —— 见 §5.2 第 1 条。
- ❌ **不代项目方裁决 `R6` 的「恰为 3 幕」口径** —— 属 `REQ-005`／`TPL-008` 的需求侧口径，
  须项目方或独立评审定。

---

## 8 配套登记建议（裁决通过后执行，本轮**未做**）

| 对象 | 动作 |
| --- | --- |
| `PM-001` §8 | 新增 **`ISSUE-053`**：「`script` 段无门禁覆盖 ＋ `content_adequacy` findings 未接入判定 ⇒ 上游缺陷静默继承到下游」（来源：项目方 2026-11-03 缺陷 B 实测） |
| `PM-001` §7 | 新增 **`T-093`**：「`T-086` 门禁体系覆盖缺口处置（候选 A′／B／C）」，前置＝`ISSUE-053` 裁决 |
| `PM-001` `T-086` 行 | 补「`enforce=true` 的前置条件」＝ `ISSUE-053` 闭环 ＋ 上游段重试后通过率实测 |
| `CM-002` | 登记 `PRO-010`（`PRO` 类 9 份 → **10 份（001~010）**） |
| `CM-003` | 「门禁段覆盖扩大」首次发生 ⇒ 登记追溯（`T-086` 行的判据来源列须补 `content_adequacy`） |

---

*本文为方案件，**未实施任何改动**。§2 的全部结论均回 2026-11-03 盘上实测
（`quality_gate.py` 342 行 · `content_adequacy.py` 257 行 · `config.py` `quality_gate_stages` L138 ·
`dialogue_service.py` L874／L998／L1038 · `validate_output.py` `R4` L536／`R6` L581／`R10` L850／
`R14`／`R22` L731／`R31` L1597 · `validate_pack.py` L262）*
