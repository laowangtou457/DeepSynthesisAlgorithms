# `PRO-011` `enforce` 翻转三前置的处置方案

> **文件性质**：方案件（`PRO` 类）。**只出方案与取证，不擅自改动被测对象与判据**。
> **触发**：项目方 2026-11-03 问「`enforce` 仍 `false` 的三条前置（① 直出率 0/2 · ② 重试收敛性未测 · ③ `T-087` 资产侧提质见效）如何修改，给方案」。
> **上游**：`PRO-010`（缺陷 B 处置，已落地批次 1＋2）· `ISSUE-053`（门禁覆盖缺口）· `ISSUE-047`（交付契约与诚实占位互斥）· `T-086`／`T-087`／`T-089`。
> **取证基线**：`03-工程代码/.wb-e2e/artifacts_pro010_obs3/`（2026-11-03 17:11~17:19 真实链路第 3 轮，独立实例 `:8013`，`vLLM`）。
> **撰写**：2026-11-03。本文所有行号**均于当日实测取得**，行数为 `splitlines()` 与 `wc -l` **双向对拍**所得：
> `quality_gate.py` **522** 行 · `output_schema.py` **224** 行 · `run_chain_t086.py` **309** 行 · `config.py` 见各条注记 · `PM-001` L24／L129 为当日实测行号。

---

## §0 结论摘要（先读这一段）

**三条前置不是「三个并列待办」，而是「一条因果链上的三个位置」，且其中两条的现有表述建立在两个不成立的观测上。**

| 前置 | 项目方表述 | 本文核验结论 |
| --- | --- | --- |
| ① 直出率 | 仍 **0/2**（`script` 段新增后仍 0） | **分母错了**：真实分母是 **3**，实测 **0/3**。`script` 段**已跑门禁且未通过**（`R4`／`R6`），但观测脚本 `GATED_STAGES` 硬编码为两段，**把它整段跳过了**（发现 1）。且 `shot_prompt` 段被 `ISSUE-047` 钉死在 0（发现 2）。 |
| ② 重试收敛性 | 未测（`retry_enabled=OFF`，三轮只量到直出率） | **可立即测**，不依赖 ①③。但**必须先校准测量器具**，否则量出一堆不可比的数。且现有脚本**没有收敛性度量**（只有"救回几个"），需补三项。 |
| ③ `T-087` 提质 | 未"见效" | 方向没错，但**"泛提质"无法收敛**：实测 8 个失败项里 `T-087` 只能解 **4 项**，解不了算术派生（`R4`／`R14`）与交付契约（`compliance.copyright`）。需按失败项逐条收窄（§3 线 5 表）。 |

**另外补一条被漏掉的前置**：

> **④ `ISSUE-047` 裁决（`PM-001` L129 已写、但未进三前置清单）** —— `shot_prompt` 段的 `compliance.copyright` BLOCK 是**非模型归因、重试无用**项，`quality_gate.check()` 的 `failures` 含它 ⇒ **该段 `ok` 恒 `false`**。⇒ **只要 `ISSUE-047` 未裁决，`enforce=true` 一开就会把每一份正路产物拒掉，与提质做到多好无关。**

**建议顺序（本文 §4）**：先修尺子（线 0／线 1，1 人日）→ 跑一次真基线 → 并行推 `ISSUE-047` 裁决（线 2）＋ 重试收敛性实测（线 4）→ 再做契约下沉（线 3）与 `T-087` 逐项（线 5）。

---

## §1 三条前置的独立核验

### §1.1 前置①：直出率的分母是错的

**取证**：`artifacts_pro010_obs3/try1/step2.json` → `artifacts.script.quality_gate`：

```json
{"applies": true, "max_attempts": 1, "attempts": 1, "ok": false, "enforced": false,
 "history": [{"attempt": 1, "ok": false, "engine_checks": 7,
   "engine_error_codes": [
     "script · R4 EST_SECONDS_SUM：Σest_seconds=18 ≠ total_est_seconds=90",
     "script · R6 ACT_STRUCTURE：幕数应为 3，实际 1"],
   "retryable": 2, "non_retryable": 0,
   "adequacy_checked": true, "adequacy_ok": false,
   "adequacy_finding_codes": ["script_total_mismatch"],
   "adequacy_finding_details": [{"code":"script_total_mismatch","sum_scene_seconds":18,
     "total_est_seconds":90,"delta_ratio":0.8,"tolerance":0.1,
     "source":"engine_dup","equiv_rule":"R4"}]}]}
```

**⇒ `script` 段确实被门禁判过、确实未通过**（`R4`＋`R6`，两项均可重试）。
且 `PRO-010` 批次 1-B 的**去重规则在此实测生效**：`script_total_mismatch` 被标 `source="engine_dup"`、`equiv_rule="R4"`、**未进 `retryable`** —— 同一失败没有计两次。

**但汇总里看不到它**。原因在观测脚本 `03-工程代码/.wb-e2e/run_chain_t086.py` L49：

```python
#: 门禁默认只对这两段生效（`quality_gate_stages = "storyboard,shot_prompt"`）。
GATED_STAGES = ("storyboard", "shot_prompt")
```

该常量**硬编码**，注释里引的还是**旧默认值**。而 `config.py` L159 已于本轮改为 `"script,storyboard,shot_prompt"`。脚本 L199 据此**整段跳过**：

```python
if name not in GATED_STAGES:
    say(f"  {si}. {name} http=200（{took:.0f}s）｜未入门禁段（不参与收敛性统计）")
    continue
```

L255 的汇总也只取 `GATED_STAGES`：

```python
verdicts = [r["stages"][s] for r in runs for s in GATED_STAGES if s in r["stages"]]
```

⇒ **"`script` 段新增后仍 0/2"应订正为**：
> 「`script` 段已计入门禁且首轮未通过（`R4`／`R6`）；**观测脚本未统计它** ⇒ 真实分母 **3**、实测 **0/3**，`script` 段 `0/1`。」

⚠️ 这与 `DEV-20261016-008` 的教训**同族**：那次是「启动器自称核实了 `retry_enabled`、代码里其实没取」，本轮是「脚本以为只两段、配置已三段」。**共同的失效形态是「测量器具与生效配置不一致，而器具自己不知道」**。

### §1.2 前置②：重试收敛性 —— 当前连"能不能测"都不成立

`run_chain_t086.py` 的汇总只有四个量：`direct`／`passed`／`undecided`／`failed`，加一句 `retried` 与 `retried_saved` 计数。**没有"第 2 次与第 1 次的失败项差集"** ⇒ 分不出 `T-086` 实测发现的两种形态：

- `shot_prompt`：两次失败项**逐条一致**（"改不动"）
- `storyboard`：**每轮换一批**（"换一批"）

这两种形态对 `enforce` 的含义**完全相反**：前者说明重试纯浪费（该归 `non_retryable`）；后者说明重试在采样空间里游走、有救回可能。⇒ **不补这项度量，开着重试跑 3 轮也回答不了"收敛性"**。

### §1.3 前置③：`T-087` 的失败项归属

`obs3` 实测失败项共 **8 条**（`script` 2 · `storyboard` 4 · `shot_prompt` 2 引擎 ＋ 2 交付 BLOCK，其中 `unit.camera_dup` 与 `R11` 同源）。按「谁能解」归类见 §3 线 5。**结论：`T-087`（资产侧）最多解 4 条，占一半。**

---

## §2 四个实测发现（本文的事实基础）

### 发现 1 · 测量器具失准（§1.1）
`GATED_STAGES` 硬编码两段 ⇒ `script` 段的门禁结论**产生了但被丢弃**。**所有历史"直出率"的分母都不可比**（本轮之前 2 段、本轮起配置 3 段）。

### 发现 2 · `shot_prompt` 段直出率被 `ISSUE-047` 结构性钉死在 0

`obs3/try1` 的 `shot_prompt`：
```
pack_block_codes: [
  "compliance.copyright｜版权/改编风险校验**未校验**（未接入／占位）→ 阻断交付（SW-015；规范 §8.3 第 3 项）",
  "unit.camera_dup｜单元 U01 内运镜类型重复：['push_in'] → 单元内运镜类型不得重复（§4.3）"]
non_retryable = 1
```

`compliance.copyright` 被 `_NON_RETRYABLE_MARKERS`（`quality_gate.py` L93~L104，含 `"compliance"`）**正确**归为不可重试。而 `check()` L465 与 L489：

```python
failures = list(engine_out["errors"]) + list(pack_out["blocks"])
if failures:
    ok = False
```

⇒ **`pack_blocks` 非空 ⇒ `ok` 恒 `False`**。这条 BLOCK 的来源是**服务层刻意留的诚实占位**（`pack_meta.apply_service_truth` 的既有口径），模型与资产都改不动它。

**⇒ 在 `ISSUE-047` 裁决前，`shot_prompt` 段直出率在结构上不可能 > 0；`enforce=true` 一开，该段全部产物会被如实拒绝。**

`PM-001` L24／L129 其实已写过这条（「`enforce=true` 的前置**新增 `ISSUE-047` 裁决**」），但它**没有进入三前置清单**，容易被当成"已经算进 `T-087` 了"。

### 发现 3 · 三段失败是一个源头的三级传导，不是三个独立失败

同一会话 `sess_34c084824ed4`：

| 段 | 实测 | 传导 |
| --- | --- | --- |
| `script` | `acts=1`（`R6` 要求 3）· `total_est_seconds=90` vs Σ场秒 `18`（`R4`，偏差 80%） | 源头 |
| `storyboard` | `shots=3`／`units=1`（1 幕 1 场只能出 3 镜）· `total_duration_ms=0` vs Σ`15000`（`R14`） | 镜数被上游压死；`total=0` 是把骨架里的 `0` 抄了下来 |
| `shot_prompt` | `R31 PACK_DURATION_LOCK：上游 0 vs 本层 15000` | 直接继承上游的 `0` |

⇒ 这解释了 `T-086` 实测的"分镜段每轮换一批失败"：**分镜的形态随上游剧本质量摆动**，不是分镜段自身随机。
⇒ 也说明**只在分镜段提质（`T-087` 原始范围）收益有限**，必须先稳住剧本段。

### 发现 4 · 判据要求的东西，受约束解码一个都没约束

`output_schema.load_engine_schema()`（L180~201）：`shot_prompt` 走**契约文件型**（`CFG-006`），其余三段走**派生型** —— 而派生型是：

> 「`REQUIRED_TOP_KEYS` 现算的 `required` 投影 …… `required` 之外**刻意不设 `properties` 类型、更不封 `additionalProperties`**」（`artifact_contract.py` L43~L48）

⇒ 中间三段的受约束解码**只保证"顶层键齐备"**，对内部结构（幕数／场数／镜数／时长和／枚举取值）**零约束**。逐条对照：

| 判据 | 要求 | 解码期是否约束 | 能否用 schema 表达 |
| --- | --- | --- | --- |
| `R6` | `acts` **恰为 3 幕** | ❌ 无 | ✅ `minItems:3,maxItems:3` |
| `R10` | 单元规模 ∈ {2,3} | ❌ 无 | ⚠️ 部分（`minItems`／`maxItems` 需单元边界在 schema 中可表达） |
| `R14` | Σ`duration_ms` == `total_duration_ms` | ❌ 无 | ❌ **JSON Schema 无法表达跨字段求和** |
| `R11` | 单元内运镜类型不重复 | ❌ 无 | ❌ `uniqueItems` **被引擎拒收已剥除**（`output_schema.py` L66） |
| `R32` | `lighting` 为纯词表 code | ❌ 无 | ✅ `enum` |
| `R23` | 不得重述外观锚 | ❌ 无 | ❌ 语义判据，非 schema 可表达 |

**⇒ 这是"直出率上不去"的结构性根因**：判据全部在**事后**判，解码期**不设防**，模型在合法空间里随机游走。

⚠️ **能力边界（必须如实写明）**：**"契约下沉"能解 `R6`／`R32`／部分 `R10`，不能解 `R14`／`R4`／`R11`／`R23`。** 前三条是 schema 能表达的，后四条不是。**不要把"加了 schema 就都能好"当成结论。**

---

## §3 处置方案（六条线）

### 线 0 · 校准测量器具（**必做先做**，0.5 人日）

**做什么**
1. `run_chain_t086.py` 的 `GATED_STAGES` **不再硬编码** —— 改为从环境变量 `APP_QUALITY_GATE_STAGES` 解析（与 `serve8010.py` 传给实例的是同一个变量），解析结果**打印并核对**。
2. **前提自检扩项**：与既有的 `retry_premise` 并列，新增一行 `stages_premise`：
   - 服务端生效值 vs 脚本解析值**必须相等**，不等则**响亮告警并中止**（`premise_verdict=stages_mismatch`）。
3. 汇总输出**分段分列**：`script 0/1 · storyboard 0/1 · shot_prompt 0/1`，不再只给一个合并值。

**为什么**
- 直接决定 ① 的分母。
- 与 `DEV-20261016-008` 的 `premise_verdict` 同一纪律：**器具必须自证与生效配置一致**。

**代价**：只改 `.wb-e2e/` 下的观测脚本（**已入 `.gitignore`，不影响交付物**）。
**验收**：脚本输出里能看到 `stages_premise=script,storyboard,shot_prompt`，且 `step2.json` 的门禁结论出现在汇总里。

### 线 1 · 直出率拆成三个口径（0.5 人日，与线 0 同批）

**做什么**：汇总层把单一 `direct` 拆成三个独立计数（**只改汇总口径，不动服务层**）：

| 口径 | 定义 | 用途 |
| --- | --- | --- |
| `direct_by_stage` | 每段各自的 `attempts==1 and ok is True` | 定位瓶颈段 |
| `direct_contract` | 含 `non_retryable` 的真实通过率（现状口径） | 回答"能不能交付" |
| `direct_model` | **剔除** `non_retryable` 项后的通过率 | 衡量 `T-087` 的提质效果 |

实现依据：`QualityVerdict.as_record()`（`quality_gate.py` L266~299）**已输出** `retryable_codes`／`non_retryable_codes` ⇒ `direct_model` 可由"`ok is False` 且 `non_retryable_codes` 为空"直接算出，**无需改服务层**。

**为什么**：单一 `direct` 把三种不同性质的失败（模型随机／资产缺陷／交付契约缺口）混在一个分母里，**既不能指导提质，也不能作 `enforce` 准入**。

**验收**：同一次跑测能同时给出 `0/3`（contract）与 `1/3`（model，假设只剩 `compliance`）这类**可解释的差**。

### 线 2 · `ISSUE-047` 裁决落实（1~1.5 人日，**需项目方先裁决**）

**这是 `enforce` 的第一硬前置，且不属 `T-087`。**

`PRO-007` 已出具方案并取证：交付判据用**否定式**把「未取得」读成「未通过」，与同文件对 `provider_code` 占位的 `WARN` 处理**口径不一致**；候选③（给 `safety_check` 加 `skipped`）**技术不可行**（该枚举根本没有此值）。

**三条可选路径**：

| 路径 | 动作 | 代价 | 风险 |
| --- | --- | --- | --- |
| **A**（`PRO-007` 推荐向） | `CFG-006` 的 `compliance.*` 增设「未接入／未知」档，`validate_pack.py` 对该档出 **`WARN`** 而非 `BLOCK` | 改交付契约枚举 | 需定 `schema_version` 是否升级；"什么算合规"的口径变化**须留痕举证** |
| **B** | `quality_gate.check()` 内把 `compliance.*` 单独成组（`contract_blocks`），**不进 `ok`**，`enforce` 时单独拒绝 | 只改服务层 | **削弱"诚实占位"刚性** —— 在本工程语境里是把"未接入"的风险从阻断降为旁路，**不推荐** |
| **C** | 先接版权校验（`T-008`），把占位变真值 | 依赖外部素材与法务 | 最正，但周期不可控 |

⚠️ **本方案不擅自选路**，列 §6 Q1 请裁决。

### 线 3 · 契约下沉：让判据要求的东西在解码期就成立（2~3 人日）

**做什么**：为 `script`／`storyboard` 增**受约束解码 schema**（**不必成为交付契约**，只作引擎约束）：

```
script:      acts        → minItems:3, maxItems:3        （对应 R6）
             acts[].scenes → minItems:1
             est_seconds → minimum:1
             total_est_seconds → minimum:1
storyboard:  shots       → minItems:1（按上游场数定下限）
             shots[].duration_ms → minimum:1000
             total_duration_ms → minimum:1               （对应 R14 的"不能为 0"半边）
             lighting    → enum（引用光照词表）             （对应 R32）
```

**引擎支持性已实测**：`output_schema.py` L59~L60 记载「`pattern`×16／`enum`×19／`minItems`×7／`maxItems`／`minLength`／`minimum`／`multipleOf`／`const`／`oneOf`／`$ref`×9／`format` **全部可通过**」，**只有 `uniqueItems` 被拒**。⇒ 上表全部可行。

**为什么**：这是唯一能把"随机游走"变成"确定性"的路径。`T-089` 实测「不带约束 **6/6 稳定落入只覆盖第 1 场**」正是解码期无约束的直接后果。

**⚠️ 代价与风险**
1. **会成为第二处结构真值** —— 与 `artifact_contract.derived_engine_schema()`（源自 `R5`）并存。**必须定"谁是真值、如何同步"**（§6 Q3），否则重蹈"两处口径打架"。
2. **`R4`／`R14` 的"求和相等"无论如何表达不出来** ⇒ 这两条仍只能靠提示词条款或服务层复算。**不要把线 3 当成 `R4`／`R14` 的解。**
3. `minItems` 会**压缩模型的合法空间**，可能降低多样性；对 `acts` 这种"契约明写 3 幕"的字段无风险，对 `shots` 这类需按场数浮动的字段要保守取值。

**验收**：同一提示词、同一后端，`R6` 失败率从实测的 100%（1/1）降到 0（≥10 次采样），且 `R4`／`R14` 失败率**不变**（证明确实只解了 schema 能解的部分）。

### 线 4 · 重试收敛性实测（1 人日 ＋ 约 50 分钟机时）

**前提**：线 0 完成。

**做什么**
1. 独立实例 `:8014`：`APP_QUALITY_GATE_RETRY_ENABLED=true` ＋ `APP_QUALITY_GATE_ENFORCE=false`（**保持只判不拦**）。
2. 跑 **≥3 轮 × 3 段**（含 `script`）。
3. **补三项收敛性度量**（现有脚本没有，必须新增）：

| 度量 | 定义 | 回答什么 |
| --- | --- | --- |
| `retry_saved` | 第 2 次 `ok=True` ÷ 发生重试的段数 | 重试的"救回率" |
| `retry_delta` | 第 2 次与第 1 次 `retryable_codes` 的**对称差**（几个走了／几个新来） | "改不动" vs "换一批" |
| `retry_worsened` | 第 2 次结构非法而回退（`retry_degraded_fallback` 已留痕） | 重试是否使结果变差 |

**成本（须明确）**：`shot_prompt` 单段实测 ~304 s、`storyboard` ~130 s、`script` ~52 s ⇒ 单轮满额重试最长 ≈ 2×(304+130+52) ≈ **16 min**；3 轮 ≈ **50 min GPU 时间**。

**⚠️ 实测前须先写下的预判（避免事后圆场）**：
> `content_adequacy · scene_coverage_incomplete`（场覆盖度）是**系统性偏差**（`T-089`：不带约束 6/6 稳定只覆盖第 1 场）⇒ **重采样大概率改不动**。
> 若实测证此 ⇒ 该项应改归 `non_retryable`（**不是**"重试没用"），否则每轮白烧 2×。
> 这本身即实测要回答的问题之一，属 `PRO-010` 批次 1-B 把 adequacy 项放进 `retryable` 的**待验证前提**。

**验收**：产出三张表（逐段救回率／失败项差集／变差次数），并对"`scene_coverage_incomplete` 是否该留在 `retryable`"给出**基于数据的结论**。

### 线 5 · `T-087` 从"泛提质"收窄为逐项（1.5~2 人日）

**现状**：`T-087` 表征写「提高首次直出率」，范围是 `TPL-010`／`TPL-008`／`TPL-013`。**"提高直出率"不是可验收的判据**（分母变过、口径未分）。已做 `R25`（`TPL-010` v2.2.0）与 `total_duration_ms` 条款（v2.2.2），但 `obs3` 实测 **`R25` 仍复发**、`total` 仍为 `0`。

**逐项归属表（`obs3` 实测 8 条）**：

| # | 失败项 | 实测形态 | 归因 | `T-087` 可解？ | 处置 |
| --- | --- | --- | --- | --- | --- |
| 1 | `R6` 幕数=1 | `acts=1`（要求 3） | 解码期零约束 ＋ 双峰崩塌（`T-089`） | **部分** | 线 3（`minItems:3`）为**主**；`TPL-008` 条款为**辅** |
| 2 | `R4` Σ≠total（script） | 18 vs 90（偏差 80%） | 算术派生 | ❌ | §6 Q2 |
| 3 | `R14` total=0 | `total_duration_ms=0` vs Σ15000 | 骨架抄 `0` ＋ 算术派生 | **部分** | 线 3（`minimum:1`）＋ §6 Q2 |
| 4 | `R11` 单元内运镜重复 | U01 `['push_in','pan_left','push_in']` | `uniqueItems` 被引擎剥除 | ❌ **技术硬边界** | 提示词条款 ＋ 事后判据（现状）；**可考虑 `unit` 级重试定位** |
| 5 | `R23` 锚重述 | `props[0].appearance_lock_zh→勘探队` | 条款表述不够具体 | ✅ | `TPL-010` 条款**加反例块**（照 `total_duration_ms` v2.2.2 的写法） |
| 6 | `R25` 自检不实 | 自声明 3 个运镜 ≠ 复算 2 个 | v2.2.0 的"机械抄录"条款**未被遵守** | ✅（需复核） | 已做；本轮 **3 镜小样本**，须**多轮×大镜数**复核 |
| 7 | `R32` 光照非纯值 | 4 处 `dark_florescent_lighting`（还拼错） | 词表**未在骨架枚举** | ✅ | `TPL-009` 骨架列 `lighting` 的 **code 枚举**（`enum` 进解码期即线 3） |
| 8 | `compliance.copyright` | 恒定 BLOCK | 交付契约 | ❌ | **线 2**（`ISSUE-047`） |

**⇒ `T-087` 收敛为 4 个可验收子项**：`R23`（加反例）、`R25`（多轮复核）、`R32`（枚举进骨架）、`R6` 的条款辅助（主线 3 在工程侧）。

**收窄 `T-087` 表征的建议写法**：
> 原文「在 `TPL-010`／`TPL-008`／`TPL-013` 侧加约束以提高首次直出率」→ 建议改为「**按实测失败项逐条处置（`R23`／`R25`／`R32` 三项资产侧 ＋ `R6` 条款辅助），验收判据＝对应判据在 ≥5 次采样中失败率为 0**」。
> 理由：原表征的"提高直出率"在当前口径下**不可验收**（分母与口径都在变），且**即使做到 100% 也开不了 `enforce`**（`compliance.copyright` 仍在）。

---

## §4 批次、依赖与顺序

```
线 0 校准器具（0.5d）──┐
线 1 三口径（0.5d）────┴──► 真基线跑测（3 轮 · ~15min 机时）
                                   │
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
   线 4 重试收敛性（1d+50min）  线 2 ISSUE-047（裁决项）  线 5 T-087 逐项（1.5~2d）
              │                    │                     │
              └────────────────────┴──────────┬──────────┘
                                              ▼
                                  线 3 契约下沉（2~3d）
                                              ▼
                                 重新评定 E1/E2/E3（§5）
```

**顺序理由**
1. **线 0／1 必先**：后面所有数字都要和它比；现在没有一条数字是可比的口径。
2. **线 2 是裁决项**，不占我方可控工时，但它是 `shot_prompt` 解锁的唯一钥匙 ⇒ **尽早推动**，与线 4 并行。
3. **线 3 放在基线之后**：要有"改前/改后"对照才能证明它有效（否则又是"自述有效"）。
4. **线 5 与线 3 部分重叠**：`R32` 的 `enum` 实现落在线 3 的 schema 里 ⇒ 两项同批做一个文件，**不要分两批改同一份 schema**。

**合计**：我方工时 **5.5~8 人日**，机时 **≈65 分钟 GPU**，另有线 2 的裁决等待。

---

## §5 `enforce` 翻转的准入判据（建议改写）

**现行表述**（`config.py` L166~167）：「待 `T-087`（资产侧提质）把直出率抬到可用后再翻为 `true`」。
**问题**：「抬到可用」**没有阈值**，不可判定；且它把 `ISSUE-047` 藏在"`T-087`"后面（`T-087` 解不了它）。

**建议改为三条可判定判据**：

| 编号 | 判据 | 当前实测 | 建议门槛 |
| --- | --- | --- | --- |
| **E1** | `shot_prompt` 段 `direct_contract` | **0/1**（被 `ISSUE-047` 钉死） | **≥ 1/1** —— 即至少一轮通过；等价于"`ISSUE-047` 已裁决且落地" |
| **E2** | 三段 `direct_model` **分段**值 | `script 0/1 · storyboard 0/1 · shot_prompt 0/1` | **每段 ≥ 2/3**（3 轮中至少 2 轮首轮即过） |
| **E3** | 重试救回率 `retry_saved / retried` | **未测** | **> 0** —— 证明重试不是纯浪费；若为 0，则应先关掉 `retry_enabled` 再谈 `enforce` |

**为什么分成 `direct_model` 与 `direct_contract`**：`enforce` 拦的是"能不能交付"（contract 口径），而提质改善的是"模型写得好不好"（model 口径）。**用一个数同时考两件事，必然出现"提质做到了却开不了"或"开了却拦掉正路产物"两种错。**

⚠️ **E1 的隐含后果须写明**：若 `ISSUE-047` 长期不裁决，则 `enforce` **永久不可开** —— 这不是"再等等"，是**结构性的**。若项目方决定"先上 `enforce` 再补版权校验"，则等价于选线 2 路径 B（削弱刚性），须**显式裁决并留痕**。

---

## §6 待裁决（四问）

### Q1 · `ISSUE-047` 走哪条路？
A（`CFG-006` 加"未接入"档，`WARN`）／B（`quality_gate` 把 `compliance.*` 剔出 `ok`）／C（先接 `T-008` 版权校验）。
**本文倾向 A**：它是 `PRO-007` 的取证方向，且与同文件对 `provider_code` 的 `WARN` 口径一致；B 会削弱"诚实占位"刚性，C 周期不可控。
**须一并定**：走 A 时 `CFG-006` 的 `schema_version` 是否升级（按工程硬口径，**改枚举取值域不涉 `output` 字段增删** ⇒ 倾向**不升**，但须裁决确认）。

### Q2 · `total_duration_ms` / `total_est_seconds` 是否改由服务层复算？
这两个字段是**纯派生量**（恒等于子项之和，**无任何创作自由度**），与 `title`／`notes`／`shots` 性质不同。让模型填它，等于让模型做加法，可靠性天然有限（实测 `total=0`／偏差 80%）。
- 若允许服务层复算覆盖 ⇒ `R4`／`R14`／缺陷 B **一次消灭**；
- 代价：**改写模型输出**，触及第一纪律。但 `pack_meta.apply_service_truth` 已有先例（合规字段写入权收归服务层），且其 docstring **明确把 `total_duration_ms` 列进"一字不改"** ⇒ 走这条路等于**改这条口径本身**，须显式裁决。
- 折中：**不覆盖，但在分段生成时把 `total` 作为已知量下发给模型**（"客户侧预算下发"），与 `T-089` 的 `shot_density` 思路同源。

### Q3 · 是否允许为中间三段建"受约束解码 schema"（线 3）？
它**不进交付契约、不改 `schema_version`**，但会成为**第二处结构真值**（与 `artifact_contract` 的 `R5` 投影并存）。
**须定**：谁是真值（建议 `artifact_contract` 仍为真值、schema 为**其投影的超集**，且加一致性测试）／如何同步（建议加一条测试：schema 的 `required` ⊇ `REQUIRED_TOP_KEYS`）。

### Q4 · 重试收敛性实测的机时与结论处置
- 是否接受 **≈50 分钟 GPU ＋ 3 轮**的预算；
- 若实测证明 `scene_coverage_incomplete` 重试改不动，**是否同意把它从 `retryable` 改归 `non_retryable`**（这会让 `PRO-010` 批次 1-B 的" adequacy 项进 `retryable`"收窄为"仅可重采样改变的项"）。

---

## §7 与既有文档／任务的关系

| 对象 | 关系 |
| --- | --- |
| `PRO-010` | 本方案是其**下游**：`PRO-010` 补的是"判据没被调用"，本方案补的是"判据被调用了但直出率上不去，以及上不去该看哪个数" |
| `ISSUE-053` | 本方案的线 0 是该 ISSUE 的**观测侧收尾**（批次 1／2 的观测器具一直没跟上配置） |
| `ISSUE-047` | **升级为 `enforce` 第一硬前置**（见 §2 发现 2、§5 E1） |
| `T-086` | 线 4 是 `T-086` 的待办项之一（"收敛性未验证"）的正式实施 |
| `T-087` | 线 5 建议**改写其表征与验收判据**（见 §3 线 5） |
| `T-089` | 线 3 与 `T-089` 的"触发条件改由客户侧变量驱动"同源，可合并推进 |
| `REQ-005` `SW-004`~`SW-008` | 本方案**不动交付契约字段**；线 2 若走 A 会动枚举取值域，须同步 `REQ-006` |
| 判据水位 | **`R1`~`R40` 零改动**。线 3 只加**解码期约束**，不改判据语义；`content_adequacy` 仍**不计入 `R` 计数** |

---

## §8 本方案明确不做的事

1. **不改 `validate_output.py` 判据语义**（`R1`~`R40` 一条不动）。
2. **不改 `schema_version`**（线 2 若裁决走 A，另行评估）。
3. **不擅自开 `enforce`／`retry_enabled`** —— 两者都由 §5 判据与 §6 裁决决定。
4. **不在本方案内改 `T-087` 的资产文件** —— 线 5 是"收窄任务书"，施工须另立批次（`CM-003` 资产域，须走资产变更流程）。
5. **不把"直出率 0/2"当成既有结论引用** —— 该数**分母错**，引用时须写 `0/3`（分段 `0/1 · 0/1 · 0/1`）。

---

## 附 · 取证清单（可复核）

| 结论 | 取证位置 |
| --- | --- |
| `script` 段已判且未通过 | `artifacts_pro010_obs3/try1/step2.json` → `artifacts.script.quality_gate`（`applies=true`／`ok=false`／`R4`＋`R6`） |
| 观测脚本跳段 | `run_chain_t086.py` L49（`GATED_STAGES`）· L199（`continue`）· L255（汇总） |
| `compliance.copyright` 钉死 `shot_prompt` | `artifacts_pro010_obs3/summary.json` → `shot_prompt.hist[0].pack_block_codes`；`quality_gate.py` L93~L104／L465／L489 |
| 三级传导 | `obs3`：`script acts=1,total=90,Σ=18` → `storyboard total=0,Σ=15000,shots=3` → `shot_prompt R31 上游0 vs 本层15000` |
| 解码期零约束 | `output_schema.py` L180~201（`derived` 来源）· `artifact_contract.py` L43~L48（"`required` 之外刻意不设 `properties`"） |
| 引擎支持的键 | `output_schema.py` L59~L60（`minItems`／`minimum`／`enum`／`pattern` 可通过；仅 `uniqueItems` 被拒） |
| 去重规则生效 | `step2.json` → `adequacy_finding_details[0].source="engine_dup", equiv_rule="R4"` |
| `ISSUE-047` 是既有前置 | `PM-001` L24／L129（「`enforce=true` 的前置新增 `ISSUE-047` 裁决」） |

---

## 附 2 · 四问裁决记录（2026-11-04 项目方，本节为追加、不改 §1~§5 正文）

| 问 | 裁决 | 落点 |
| --- | --- | --- |
| Q1 | **路径 A ＋ `schema_version` 不升**（改枚举取值域不涉 `output` 字段增删） | ⭐ 实测核实：`DEV-20261103-004`（并行会话，`PRO-007` 两步）已于 2026-11-03 落地同方向变更（`compliance.*` 三处 enum 增 `not_available` ＋ 判据三态式「未取得→WARN」＋ `pack_id` 占位 pattern，`schema_version` 保持 2.1.0）⇒ **线 2 主体已落地**；余「服务层 `quality_gate` 侧 `pack_blocks` 同步核验」立 `T-095`（并行会话仍在写 `validate_pack.py`，核验批不碰其工作区） |
| Q2 | **折中案**：`total_duration_ms`／`total_est_seconds` **不改服务层复算**，改为**分段生成时作为已知量下发给模型**（"客户侧预算下发"） | 并入 `T-096`（线 3 批次）模板／服务层改动 |
| Q3 | **允许**为中间三段建引擎侧 schema；**真值归属方案由我方提出后项目方拍板**（我方建议稿：`artifact_contract` 仍为真值、schema 为其 `required` 投影的超集，加一条一致性测试 `schema.required ⊇ REQUIRED_TOP_KEYS`） | 并入 `T-096`（线 3） |
| Q4 | **同意** ≈50 min GPU ＋ 3 轮；**预授权**：若实测证实 `scene_coverage_incomplete` 重试改不动 ⇒ 改归 `non_retryable`（收窄 `PRO-010` 批次 1-B 口径） | `T-097`（线 4；观测脚本已就绪，2026-11-04 真基线被 vLLM 崩溃阻断，重启后重跑） |

**执行令**：线 0＋线 1 直接执行 —— **已于 2026-11-04 落地**（留痕 `DEV-20261104-001`：`run_chain_t086.py` 去硬编码＋`stages_premise`＋三口径汇总；`stages_premise` 首跑即抓住器具自身解析 bug，未污染数字）。新任务号：`T-094`（线 0+1，✅ 本批）· `T-095`（线 2 余项核验）· `T-096`（线 3＋Q2＋Q3 方案）· `T-097`（线 4 实测）· `T-098`（线 5 收窄）。
