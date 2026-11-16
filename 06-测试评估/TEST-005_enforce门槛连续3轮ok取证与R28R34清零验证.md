# TEST-005 `enforce=true` 门槛「连续 ≥3 轮 `ok=True`」取证

- **日期**：2026-11-16（16:20:59 ~ 16:43:28）
- **触发**：项目方指令「连续 ≥3 轮 ok=True｜开测」
- **依据**：`PM-001` §8 `ISSUE-038` 行末「`enforce=true` 门槛＝接受约 4% 残留并配重试／另案解伪 gram」两条口径已于同日裁决（`DEV-20261116-004`），余下唯一硬条件即**连续 ≥3 轮产物级 `ok=True`**
- **状态**：**门槛未通过** —— `best_streak = 0 / 3`。但**`R28`／`R34` 在全部有包轮次中零命中**（投影规则⑤⑥ 的机制化效果得到独立验证）；阻断项已转移到**运镜单调**、**单元结构**、**上游剧本形态**三类，另有一类**流程项在自动跑测中恒假**
- **可复现性**：驱动 `.wb-e2e/_enforce3_driver.py`（3 轮串跑）＋ `.wb-e2e/_enforce3_engine_check.py`（engine 层补判）；原始日志与产物留 `.wb-e2e/`（**不入库**），本报告只写计数与码名

> ⚠️ 本报告**不把「会话跑完」当成「质量通过」**：判据要求三条同时成立——① 会话 `completed`、② 包落盘含 `manifest.json`、③ `gate_report.json` 的 `blocked=false` 且 `block_count=0`。超时／异常一律记 `ok=False`，**不重试、不掩盖**（重试会破坏「连续」语义）。

---

## 一、结论先行

三句话：

1. **门槛未过：0/3**。两轮跑到交付包（554 s／658 s）均被门禁拦下，第三轮在剧本段就中止（136 s，`acts[2]` 不是对象）。
2. **`R28`／`R34` 已清零**：对两轮产物补跑 engine 层判据，`R28 PACK_APPEARANCE_ECHO` 与 `R34 EN_CAMERA_SENTENCE` **均为 0 命中**——这是投影规则⑥／⑤ 上线后**首次在无人工干预的连跑中得到交叉验证**（此前证据是离线回放 75 份历史产物）。
3. **真正拦住 `enforce=true` 的是三件别的事**：`R11`／`R19` 运镜单调（2/2 轮）、单元结构与道具锚（1/2 轮）、上游剧本 `acts` 元素形态（1/3 轮）；此外 `human_review.missing` **在自动跑测中必然成立**（无人工台账），属**验收判据定义问题**，不是模型缺陷。

---

## 二、跑测口径自证（`ISSUE-086`／`T-111` 教训的落地）

| 项 | 实测值 | 取证方式 |
| --- | --- | --- |
| 模型 | `Qwen2.5-14B-Instruct-AWQ`（`max_model_len=32768`） | `GET /v1/models` → 200 |
| 接入 | 隧道 `127.0.0.1:18001` → GPU 机 `127.0.0.1:8000` | `_tunnel_18001.py`（自愈版） |
| 服务 | `127.0.0.1:8010`，`inference_backend=vllm` | `GET /health`、`GET /ready`（`prompts: ok (16 templates)`） |
| **guided 模式** | **`response_format`** | 进程内 `get_settings().vllm_guided_decoding_mode` —— **不是**读 `.env` 文本 |
| 单调用超时 | **1200 s**（生产 `.env` 仍 600 s） | 启动时环境变量覆盖；`ISSUE-090` 口径差异，已在此登记 |
| 门禁开关 | `quality_gate_enforce=False`、`quality_gate_retry_enabled=False` | 取证期只记录、不拦截、不重试 ⇒ 本轮**没有重试兜底**，结果更严格 |

> **为什么强调 guided**：`MEMORY` 已固化「启动头必须打印 guided 实际取值并与服务端交叉校验」——`ISSUE-086` 曾因 `cwd` 不是 `03-工程代码` 而静默丢失该配置，导致 8 轮无效跑测、约 3.6 h GPU 白烧。本次驱动在**开跑前**做前置自检，任一项不过即退出码 2、不开跑。

---

## 三、三轮结果

| 轮 | 会话 | 产物包 | 时长 | 终态 | 门禁 | `ok` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `sess_1ee8eb7f4350` | `…-PK-20261116-4FDD2DFE` | 554 s | `completed` | **5 BLOCK / 9 WARN** | ❌ |
| 2 | `sess_81e222e11481` | `…-PK-20261116-FCAC2B0D` | 658 s | `completed` | **7 BLOCK / 10 WARN** | ❌ |
| 3 | `sess_ba8d16b1e1e3` | 无（未到交付段） | 136 s | `draft_script` | — | ❌ |

`best_streak = 0`，`gate_passed = false`。两轮的导出（json/md/csv/xlsx/txt 五格式）均 **200**，说明**交付链路本身是通的**，卡的是内容质量门。

---

## 四、阻断项分解

### 4.1 `R28`／`R34`：零命中（本轮最重要的正面结论）

engine 层补判（`.wb-e2e/_enforce3_engine_check.py`，对包内 `pack.json` 直接跑 `quality_gate.check`）：

| 判据 | 轮 1 | 轮 2 | 说明 |
| --- | --- | --- | --- |
| `R28 PACK_APPEARANCE_ECHO` | **0** | **0** | 投影规则⑥ 子句级删除生效（无 `skipped_unresolvable` 遗留） |
| `R34 EN_CAMERA_SENTENCE` | **0** | **0** | 投影规则⑤ 运镜句合成生效 |

⇒ 「约 4% 残留」在本次 n=2 有包样本中**未复现**（样本小，不作统计结论），但**机制确实在生效**。

### 4.2 模型侧：运镜单调（`R11` ＋ `R19`）—— 2/2 轮

| 轮 | 引擎判据 | 门禁判据 |
| --- | --- | --- |
| 1 | `R11 UNIT_MOVE_UNIQUE`：U01 运镜重复 `['push_in','push_in']` | 整片 6 镜 push_in **4/6 > 允许 3**；U01 2 镜 push_in **2/2 > 允许 1**，类型数 **1 < 门槛 2** |
| 2 | `R11`：U01 运镜重复 `['static','static']` | U01 静止镜 **2/2 > 允许 1（40%）**、单一运镜 `static` **2/2 > 允许 1（35%）**、类型数 **1 < 2** |

门槛公式（`validate_output.py`）：单一运镜占比 ≤35%、运镜类型数 ≥ `min(5, max(2, ⌈n/4⌉))` ⇒ **2 镜单元被要求至少 2 种运镜**，等于禁止任何重复。

⚠️ **这与 `TPL-009` 的「同一运镜不得连续使用」是两条独立约束**，但都指向同一件事：产物**整片仅 6 镜、单元仅 2 镜**，几乎没有运镜调度空间。实测两轮均为 6 镜 3 单元：轮 1 `push_in×3, pan_right, push_in, pan_left`（整片 push_in 4/6 超线 ＋ U01 两镜同 `push_in`）；轮 2 `push_in, tilt_down, pan_left, pan_right, static, static`（**整片最单一 2/6＝33% 在线内**，但末两镜组成的单元同为 `static` ⇒ 单元级 `R11` ＋ 类型数 1 < 2 挂）。历史 9~15 镜时该码失败率 3/6~5/6（`ISSUE-038` 行登记）；本次整片只有 6 镜时变成 **2/2 必挂**。

### 4.3 结构与锚点：单元、道具、风格词（1/2 轮，第 2 轮）

- `unit.duplicate_id`：`units[].unit_id` 出现 `['U01','U01','U01']`（三个同名单元）
- `unit.shot_missing`：单元 U01 引用不存在的 `S01-SH003`（断链）
- `R27 PACK_REQUIRED`：`S01-SH002.prop_refs` 引用未定义道具 `PRP-01`；`R35 PROP_ANCH_CONSISTENCY` 同源（`PRP-01` 不在 `props[].prop_id`）
- `R29 PACK_PROMPT_HYGIENE`：正文出现 `写实`（不在 `style_anchors` 内）

⇒ 这四项与 `ISSUE-038` 的 `R9`／`R10` 家族同源，属**跨层承继一致性**问题（分镜层定的单元结构与道具，在提示词层被改写/漂移）。

### 4.4 上游剧本形态：`acts[2]` 不是对象（第 3 轮，会话中止）

```
502 GENERATION_FAILED：上游剧本 acts[2] 不是对象，无法推导逐场调用计划（details.index=2, retryable=true）
```

会话停在 `draft_script`，连分镜段都没进。这是**剧本段产物的元素类型缺陷**，与 `ISSUE-042`（形态闸只管结构、上游非法 JSON 仍推进）同族但**更早**：形态闸放过了 `acts[]` 内含非对象元素的情形。

### 4.5 流程项：`human_review.missing` —— 自动跑测中**恒真**

`human_review` 的唯一数据源是人工核对台账（`settings.human_review_ledger`，`delivery_service._load_human_review` 明确要求「**只认人工录入，绝不从模型产物取**」）。跑测环境未配台账 ⇒ 必然：

- `self_check` 第 18 项 `fail`（角色一致性 / 跨镜连续性人工核对完成）
- 清单判据 `human_review.missing` **BLOCK**（「无记录视为未做」）

这不是 bug，是**设计如此**；但它意味着：**只要验收判据包含该项，「连续 ≥3 轮 0 BLOCK」在无人介入时结构上不可达**。这是本报告要请项目方裁决的第一件事。

---

## 五、请裁决的三件事

| # | 问题 | 选项 | 备注 |
| --- | --- | --- | --- |
| **A** | `enforce=true` 的验收判据，是否区分「模型侧 BLOCK」与「流程项 BLOCK」？ | **A1** 只认模型侧 0 BLOCK（排除 `human_review.*`／`self_check` 第 18 项）／**A2** 维持全量 0 BLOCK，但跑测前须由流程方补一份真实人工核对台账／**A3** 维持全量，接受「自动跑测永不可达」、门槛改由人工验收记录 | 推荐 **A1**（流程项在真机留证阶段由 `PM-005` 流程补齐，不参与自动连跑判据） |
| **B** | 运镜单调（`R11`／`R19`）怎么处置？ | **B1** 服务层机制化（按单元内轮转运镜改写 `camera.move`——**改创作决策**，比投影⑤⑥ 越界更远）／**B2** 模板措辞强化（第五版尝试）／**B3** 接受为已知限额，`enforce=true` 时如实拒绝并计入人工复核率 | 推荐先取 **B3** 取数（连跑 10 轮看真实分布），再决定是否 B1 |
| **C** | 上游剧本 `acts[].` 元素类型缺陷 | **C1** 形态闸前移（生成后即校验 `acts` 每元素为对象，fail-fast 并重试）／**C2** 服务层容错（跳过非对象元素） | 推荐 **C1**（fail-fast 比重试整段便宜，且不掩盖模型缺陷） |

---

## 六、可复现命令

```bash
# 1. 隧道（需 GPU 机凭据，环境变量传入，不落盘）
cd .wb-e2e && H3_HOST=<ip> H3_PORT=<port> H3_USER=root H3_PASS=<…> \
  python -u _tunnel_18001.py 8000 18001 0

# 2. 服务（cwd 必须是 03-工程代码；timeout 覆盖 1200）
cd 03-工程代码 && APP_VLLM_TIMEOUT_SECONDS=1200 bash ../.wb-e2e/start_real_local.sh

# 3. 三轮连跑（前置自检不过即退出码 2）
cd .wb-e2e && python -u _enforce3_driver.py 3

# 4. engine 层补判（R28/R34 等）
cd 03-工程代码 && python ../.wb-e2e/_enforce3_engine_check.py
```

产物与日志：`.wb-e2e/_enforce3_summary.json`（判定汇总）、`_enforce3_r{1,2,3}.log`（逐轮日志）、`_enforce3_r{1,2}_gate.json`（门禁明细）、`_enforce3_engine_check.json`（engine 层码）、`real_local/PROVIDER_CODE-PK-20261116-*/`（十份产物）。
