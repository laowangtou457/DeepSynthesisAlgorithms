# 开发历史 · 定位 vLLM「启动后期崩溃」真因 · 根治 venv 的 `PATH` 归位缺陷

| 项目 | 内容 |
| --- | --- |
| 记录编号 | DEV-20261015-010 |
| 记录时间 | 2026-10-15 17:50 |
| 动作类型 | **诊断（无日志崩溃点定位）** / **修复（部署脚本）** / 文档修订（`OPS-002` V1.6 → **V1.7**）/ **自我纠偏（误判纠正）** |
| 触发来源 | 用户反馈「**检查一下报错原因**」—— 现场**只有终端输出、无任何日志文件**（脚本末步是 `exec`，输出不落盘），且未提供报错文本 |
| 涉及目录 | `04-部署运维/scripts/` · `04-部署运维/`（手册） · `11-过程文档/开发历史/` |
| 状态 | ✅ **崩溃点已定位到「flashinfer 采样内核 JIT」且真因已给出**（`ninja` 不在 `PATH`）；✅ **脚本缺陷已根治**（venv 自动归位 + 工具链门禁）并**五路分支实测全绿**；🟡 **vLLM 起服务与受约束解码端到端仍未实跑** ⇒ `T-012` **不关闭** |

---

## 1 动作摘要

用户报告上一轮 vLLM 启动失败，但**没有贴出报错文本**，现场也**没有留下任何日志文件**。本轮改走**「文件系统写入痕迹取证」**：从 Windows 侧（本会话非管理员、沙箱禁用 `wsl.exe`）读 `\\wsl$\Ubuntu\`，用**崩溃时刻被最后写入的文件**反推崩溃点。

结论：**v0.31.0 已装成、模型已读、`torch.compile` 已过，进程最后死在 `flashinfer` 采样内核的 JIT 编译上**；真因是 **`ninja` 不在 `PATH` 里** —— 脚本用**绝对路径**调 venv 解释器，**并不会激活 venv**，因此 `<venv>/bin`（`ninja` 的唯一落点）从未进入 `PATH`。

⚠️ 本轮**一并纠正了 AI 自己的一次误判**（§3.6）：一度据 `ls -d <路径>` 的失败把「WSL 内没有 `g++`」当成并列真因，实际 `g++` / `gcc` / `ld` **全部已装**——`\\wsl$` 上对**符号链接**做单路径 `ls -d` / `stat` 会报 `Input/output error`，被误读成「文件不存在」。**该教训已写入手册 §6.1 与工程记忆。**

| 项 | 结果 |
| --- | --- |
| 诊断 | 崩溃点＝`~/.cache/flashinfer/0.7.0.post1/89/cached_ops/sampling`（17:38:12 为**最后一次写入**）；真因＝`PATH` 缺 `<venv>/bin` ⇒ `ninja` 不可见 |
| 脚本 | `provision-vllm.sh`：新增**运行环境归位**（venv `bin` ＋ pip 版 CUDA 工具链 `bin` 入 `PATH`，`CUDA_HOME` 兜底）＋ **工具链门禁**（缺 `ninja`/`g++` 默认停下，可显式降级）＋ 路径归一化改用 `command -v` ＋ `cd/pwd` |
| 手册 | `OPS-002` V1.6 → **V1.7**：**新增 §4.1.1**（编译工具链与 PATH 归位）、**新增 §6.1**（不一定是 OOM：先按崩溃点定位）、§7.1 回填四项、§10 修订行 |
| 验证 | **五路分支实测全绿** ＋ 静态校验（`bash -n` / 纯 LF / 无 BOM）＋ 三处插入**逐处回读** |
| 未闭环 | **vLLM 真正起服务 ＋ 受约束解码端到端未实跑** |

---

## 2 变更明细

### 2.1 `04-部署运维/scripts/provision-vllm.sh`（修复；**无新增、无删除**文件）

| 变更对象 | 变更前 | 变更后 | 说明 |
| --- | --- | --- | --- |
| 运行环境归位 | **无**（只把 `PY_BIN` 当绝对路径用） | 认 `<venv>/pyvenv.cfg` ⇒ 把 `<venv>/bin` **前置**进 `PATH`、导出 `VIRTUAL_ENV` | **真因根治**：不激活 venv 就调 venv 解释器，`PATH` 里**没有** venv 的 `bin` ⇒ `ninja` 不可见 |
| pip 版 CUDA 工具链 | **无** | 探测 `site-packages/nvidia/cu13`（或 `nvidia/cuda_nvcc`）⇒ 其 `bin/` 入 `PATH`；`CUDA_HOME` **未设置时**兜底指向它（**已设置则不覆盖**） | 本机既无 `/usr/local/cuda` 也无 `/usr/bin/nvcc`，而 JIT 需要 `nvcc`/`ptxas` |
| 工具链门禁 | **无**（缺了要到启动后期才炸） | 查 `ninja` / `g++`；**默认 `die`** 并给两条处置；`ALLOW_NO_TOOLCHAIN=1` ⇒ 只告警 ＋ 设 `VLLM_USE_FLASHINFER_SAMPLER=0`（退化 PyTorch 原生采样）；`DRY_RUN=1` ⇒ **只告警不阻断** | 「失败要早、要指着真因」；干跑不阻断是**既有纪律**（§4.1 V1.4 的教训） |
| 解释器路径归一化 | `dirname "$(readlink -f "$PY_BIN")"` | `command -v` ＋ `cd "$(dirname …)" && pwd` | `readlink -f` 在 **MSYS/Git Bash** 下可能返回 `C:/…` 形式，而 `PATH` 里**冒号是分隔符** ⇒ 该条目会被**静默截成两段**（Linux 侧无此问题，但同一脚本要在两类环境可靠） |
| `PY_IN_VENV` | 无条件由 python 探测覆盖 | `PY_IN_VENV="${PY_IN_VENV:-…}"` | 与前面的 `pyvenv.cfg` 判据**保持一致**，避免两处结论打架 |
| 头部注释 | — | 新增 `ALLOW_NO_TOOLCHAIN=1` 一行 | 开关必须可被 `--help` 看到 |

### 2.2 `04-部署运维/OPS-002_WSL2-vLLM部署手册.md`（V1.6 → **V1.7**）

| 变更对象 | 内容 |
| --- | --- |
| **新增 §4.1.1** | 「编译工具链与 PATH 归位（**必做**）」：表列 `ninja` / `g++` / `nvcc` 各自**谁在调、缺了会怎样**；写清本机实测（`ninja` 只在 `~/vllm-venv/bin/`）；给出两条处置命令；说明脚本**已自动完成 ②**、以及新门禁与 `ALLOW_NO_TOOLCHAIN` 语义 |
| **新增 §6.1** | 「不一定是 OOM：先按**崩溃点**定位」：给出**无日志时靠写入痕迹判据**的 6 行表（`ENGINE_CONTEXT` / `torch_compile_cache` / **0 字节** `flashinfer_jit.log` / 空 `cached_ops` ＋ 残留 lock / `kern.log` 无 OOM Killer / **最后一个被写入的文件即崩溃点**）；并记入 `\\wsl$` 上 **`ls -d` / `stat` 对符号链接报 `Input/output error`** 的误判陷阱 |
| §7.1 | 回填 4 项（pip **26.2.1** 就位、`build-essential` 就位、vLLM **0.31.0**、编译工具链状态**及其例外**＝`ninja` 不在 `PATH`），并把「当前卡点」由「无 pip」改写为「flashinfer JIT」 |
| 头部状态块 | 改为「vLLM 0.31.0 已装成 / 引擎已初始化 / **当前卡点＝flashinfer JIT**」 |
| §10 | 新增 **V1.7** 行（**脚本按标记切分插入，未手抄长表格行** —— 见既有纪律） |

### 2.3 未改动

- **`import-distro.ps1` / `install-wsl2.ps1`（Windows 侧）**：与本次现象无关，**未动**。
- **仓库内其它文档**：未动。**本轮未做任何 Git 操作。**

---

## 3 取证过程（**无日志时的定位手法**，可复用）

前提：本会话**非管理员**且沙箱**禁用 `wsl.exe`** ⇒ 全部证据来自 `\\wsl$\Ubuntu\` 只读访问。

### 3.1 先排除「还有活着的进程」

列 `\\wsl$\Ubuntu\proc\*\cmdline`：只剩两个 `-bash`（470 / 535）与系统服务，**无 `pip` / `python` 残留** ⇒ 安装**已结束**，不是「还在跑」。

### 3.2 取用户终端的**真实环境变量**（比问用户可靠）

读 `\\wsl$\Ubuntu\proc\{470,535}\environ`：

```
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:…:/snap/bin
```

⇒ **`PATH` 里没有 `~/vllm-venv/bin`**，且**没有** `VIRTUAL_ENV`、**没有** `CUDA_HOME`、**没有** `VLLM_*`。这是后面所有推断的支点。

### 3.3 判定「崩在启动的哪一段」

| 证据 | 结论 |
| --- | --- |
| `~/.config/vllm/usage_stats.json` 存在，含 `"context": "ENGINE_CONTEXT"`、`"model_architecture": "Qwen2ForCausalLM"`、`gpu_type` RTX 4090、`cuda_runtime` 13.0、`dtype` bf16、`max_model_len` 16384 | **模型配置已读、引擎已初始化** ⇒ 崩在**启动后期**；驱动 / 权重 / 显存路径**全部排除** |
| `~/.cache/vllm/torch_compile_cache/`（含 `rank_0_0/backbone`、`torch_aot_compile`）有内容；`~/.triton/cache/` 有 `.so` | `torch.compile` **已跑过** ⇒ 与 triton 无关 |
| `~/.cache/flashinfer/0.7.0.post1/89/flashinfer_jit.log` **存在但 0 字节**；同级 `cached_ops/sampling/` **空目录**；`cached_ops/tmp/sampling.lock` **残留** | **JIT 在产生任何编译输出之前就失败**（`89` = sm_89 = 4090） |
| `kern.log` / `dmesg` **无** `Out of memory: Killed process`（最后一条内核记录停在 16:58） | **不是 OOM Killer** ⇒ 显存方向排除 |

### 3.4 时间线（把崩溃点钉死）

| 时刻 | 事件 |
| --- | --- |
| 17:35:57 | `~/vllm-venv/bin/vllm` 生成 ⇒ **pip 安装结束** |
| 17:36:13 | `~/.cache/vllm/modelinfos/…Qwen2ForCausalLM.json` ⇒ 读到模型配置 |
| 17:36:21 | `flashinfer_jit.log` 创建（**0 字节**） |
| 17:36:22 | `usage_stats.json` 写入 ⇒ 引擎初始化（`ENGINE_CONTEXT`） |
| 17:37:56 / 17:37:57 | `torch_compile_cache` / `.triton/cache` ⇒ **编译阶段通过** |
| **17:38:12** | **`cached_ops/sampling` ＋ `sampling.lock`（此后无任何写入）** ⇒ **崩溃点** |

### 3.5 关键依赖事实

- `flashinfer_python-0.7.0.post1` 的 `METADATA` 明写 **`Requires-Dist: ninja`** ⇒ pip 把 `ninja`（1.13.2）装进了 **`~/vllm-venv/bin/ninja`**；
- **`/usr/bin/ninja` 不存在**（`ls /usr/bin | grep '^ninja'` 无命中）；
- 用户在 16:52 已装好 **`build-essential`**（`dpkg.log` 记为 `status installed`），`/usr/bin` 下 `gcc` / `g++` / `ld` / `cc` / `c++` / `x86_64-linux-gnu-g++-13` **均在**；
- `/usr/local/cuda` **不存在**、`/usr/bin/nvcc` **不存在**，但 pip 版整套 CUDA 工具链在
  `~/vllm-venv/lib/python3.12/site-packages/nvidia/cu13/bin/`（`nvcc` / `ptxas` / `nvlink` / `cudafe++` …）。

⇒ **真因**：`PATH` 缺 `<venv>/bin` ⇒ flashinfer JIT **找不到 `ninja`** ⇒ 在产生任何编译输出前中止（**这正是日志为 0 字节的原因**）。

### 3.6 ⚠️ 本轮的一次误判与纠偏（如实登记）

诊断中期，我用 `ls -d "//wsl$/Ubuntu/usr/bin/g++"` 得到**空结果**，据此**曾判定「WSL 内根本没有 C++ 编译器」**，并把它与 `ninja` 并列为真因。

**该结论是错的。** 复核方式：`ls //wsl$/Ubuntu/usr/bin/ | grep -E '^(gcc|g\+\+|ld)'` —— 六个编译器**全在**；`dpkg.log` 亦记为「16:52 已成功安装 `build-essential`」。追加验证 `ls -la <单个 gcc 路径>` ⇒ 报 **`Input/output error`**：

```
ls: cannot access '//wsl$/Ubuntu/usr/bin/gcc': Input/output error
```

⇒ 根因是 **`\\wsl$`（9p 共享）上对符号链接做单路径 `ls -d` / `stat` 会失败**（`gcc` → `gcc-13` → `x86_64-linux-gnu-gcc-13` 是链式符号链接），而我的命令里带了 `|| echo 不存在`，**把 I/O 错误静默翻译成了「不存在」**。

**纪律（已沉淀）**：
1. 在 `\\wsl$` 上核查「某文件在不在」，**用「列目录 ＋ 过滤」**，**不要**用 `ls -d <路径>` / `stat <路径>`；
2. 任何 `… || echo "不存在"` 的写法，都要能区分「**真的没有**」与「**查不动**」—— 本次就是把后者伪装成了前者。

---

## 4 验证

### 4.1 静态校验

| 项 | 结果 |
| --- | --- |
| `bash -n provision-vllm.sh` | 通过 |
| 行尾 / BOM | 纯 LF、无 BOM（CR 字节 0） |
| 手册三处插入 | **逐处回读**：§4.1.1（510 行）、§6.1（620 行）、`V1.7` 行（725 行）均在位，**相邻正文行无被吞并** |

### 4.2 分支实测（Git Bash ＋ 假 `nvidia-smi` ＋ 替身解释器；共 **5 路**）

| 路径 | 输入 | 期望 | 实测 |
| --- | --- | --- | --- |
| A | venv（有 `ninja`）＋ `DRY_RUN=1` | 走完 `0/5`~`5/5`、打印启动参数、只报缺 `g++` | ✅ 一致 |
| B | venv（**无** `ninja`）＋ `DRY_RUN=1` | 报缺 `ninja g++`，**不阻断** | ✅ 一致 |
| C | 同上 ＋ `ALLOW_NO_TOOLCHAIN=1`（非干跑） | 告警 ＋ 设 `VLLM_USE_FLASHINFER_SAMPLER=0`，**并真正走到启动那一步** | ✅ 替身回显 `SAMPLER=0`、`PATH` 首段＝venv `bin` |
| D | 同上、**不给** `ALLOW_NO_TOOLCHAIN` | 在工具链门禁处 `die`，退出码 ≠ 0 | ✅ 报错含两条处置，**退出码 1** |
| E | venv 归位 | `VIRTUAL_ENV` 正确、`PATH` 前置 venv `bin` | ✅ 一致 |

> ⚠️ **为分支实测专门改造过一次脚本**：首轮 A 路实测发现 `PATH` 里加进去的是 `C:/Users/…`（MSYS 形态），
> 带冒号 ⇒ 被当成两段 ⇒ `ninja` 探测失败。据此把 `readlink -f` 换成 `command -v` ＋ `cd/pwd`（§2.1）。
> **若不实跑，这个可移植性缺陷不会被发现** —— 与 `[Parser]::ParseFile` 全绿 ≠ 能运行是同一条纪律。

### 4.3 验证边界（**如实说明**）

- 上述 5 路是在 **Git Bash ＋ 替身**下跑的**逻辑**验证；**WSL 内真机复跑尚未进行**。
- 真机复跑的预期：`ninja` 由 `~/vllm-venv/bin` 命中、`g++` 由 `/usr/bin` 命中 ⇒ **不触发门禁**，
  直接进入启动，并打印 `工具链: ninja=… g++=…`。
- **真因判定属「证据链推断」而非「复现确认」**：崩溃点（flashinfer JIT）由**时间线 ＋ 0 字节日志 ＋ 空 `cached_ops` ＋ 残留 lock**共同钉死，可信度高；但**用户终端上的原始报错文本未取得**，故不做「逐字一致」的主张。

---

## 5 未闭环 / 下一步

1. **在 WSL 内复跑并落日志**（脚本已自动归位 `PATH`，无需手工 `activate`）：

   ```bash
   cd /mnt/e/深度合成算法工程材料/04-部署运维/scripts
   PY_BIN=~/vllm-venv/bin/python bash provision-vllm.sh --serve-only 2>&1 | tee ~/vllm-serve.log
   ```

   日志落 `~/vllm-serve.log` 后**可从 Windows 侧直接读**（`\\wsl$\Ubuntu\root\vllm-serve.log`），便于回厂核查。
2. 若仍失败：按 **§6.1** 取「最后一个被写入的文件」再定位；必要时先 `ALLOW_NO_TOOLCHAIN=1` 验证是否与 flashinfer 相关。
3. 起服务成功后按 **§7.2 / §7.3** 回填（KV Cache 块数、`max-model-len` 是否够用、**10 并发 TTFT/TPOT**、**受约束解码端到端**）。
4. `T-012` **不关闭**。

---

*记录性质：工程推进过程留痕　｜　编号 `DEV-20261015-010`（`DEV` 为**豁免类**，不并入 `CM-002`）　｜　保留原则：永久保留*
