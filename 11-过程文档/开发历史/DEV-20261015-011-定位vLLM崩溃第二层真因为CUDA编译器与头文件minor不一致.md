# 开发历史 · 定位 vLLM 崩溃**第二层**真因 · `nvcc` 与 CUDA 头文件 minor 不一致（CCCL 硬性拒绝）

| 项目 | 内容 |
| --- | --- |
| 记录编号 | DEV-20261015-011 |
| 记录时间 | 2026-10-15 17:58 |
| 动作类型 | **诊断（拿到全量日志后的真因定位）** / **修复（部署脚本）** / 文档修订（`OPS-002` V1.7 → **V1.8**）/ 上游归因（依赖漂移） |
| 触发来源 | 用户贴出**原始报错文本**（`Engine core initialization failed … Failed core proc(s): {}` 一长段 traceback） |
| 涉及目录 | `04-部署运维/scripts/` · `04-部署运维/`（手册） · `11-过程文档/开发历史/` |
| 状态 | ✅ **上一层缺陷（`ninja` 不在 `PATH`）已被现场证实修好**（日志打印 `[OK] 工具链: ninja=… g++=…`）；✅ **本轮真因已定位到「`nvcc` 13.4 vs 头文件 13.0」并由脚本自动检测/降级**，**四路分支实测全绿**；🟡 **vLLM 起服务与受约束解码端到端仍未实跑** ⇒ `T-012` **不关闭** |

---

## 1 动作摘要

用户贴出的 traceback 末尾是：

```
RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
```

**关键在 `Failed core proc(s): {}` 是空的** —— 这一层不带任何信息。本轮据三点推进：

1. **用户上一轮已按建议加了 `tee`** ⇒ `~/vllm-serve.log`（64 KB）**存在**，不必再靠文件写入痕迹反推；
2. 读 **vLLM 源码**确认该 `RuntimeError` 的抛出条件（`vllm/v1/engine/utils.py:1348` 一带），坐实「真因在日志上方」；
3. 在日志上方取到**逐字真因**：

```
.../flashinfer/data/cccl/libcudacxx/include/cuda/std/__cccl/cuda_toolkit.h:41:8:
error: #error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
```

结论：**上一轮（`DEV-20261015-010`）的 `ninja` 归位确实生效了 —— JIT 这次真的进入编译，是 `nvcc` 编译本身失败。**
真因＝**CUDA 编译器与 CUDA 头文件 minor 不一致**：`nvcc` **13.4** ／ 头文件 `CUDART_VERSION 13000`（**13.0**）。

| 项 | 结果 |
| --- | --- |
| 诊断 | 崩溃点＝flashinfer 采样内核 JIT 的 `nvcc` 编译；真因＝**CCCL 硬性要求 `nvcc` 与头文件 `major.minor` 严格相等，实测 13.4 ≠ 13.0** |
| 上游归因 | 元包 `cuda-toolkit 13.0.3.0` 声明自洽组合 `nvcc/crt==13.0.88.*` ＋ `runtime==13.0.96.*`；`tilelang`（`nvidia-cuda-nvcc>=13.0.48`）与 `humming-kernels`（未钉版）把 `nvcc` 拉高 ⇒ **依赖漂移** |
| 脚本 | `provision-vllm.sh`：新增 **CUDA 版本一致性自检** ＋ **响亮降级**（设 `VLLM_USE_FLASHINFER_SAMPLER=0`）＋ `REQUIRE_FLASHINFER_SAMPLER=1` 强制严格 ＋ 启动参数区新增「采样后端」行 |
| 手册 | `OPS-002` V1.7 → **V1.8**：**新增 §4.1.2**（CUDA 编译器与头文件必须同 minor）、**新增 §6.2**（读懂 `Engine core initialization failed`）、§7.1／§7.2 回填、§10 修订行 |
| 验证 | **四路分支实测全绿** ＋ 干跑走完 `5/5` ＋ `bash -n` ＋ 纯 LF / 无 BOM ＋ 修订表**逐行回读** |
| 未闭环 | **vLLM 真正起服务 ＋ 受约束解码端到端未实跑**；根治命令（§4.1.2 ①）尚未执行 ⇒ 样本仍走降级路径 |

---

## 2 证据链

### 2.1 「上一层已修好」的直接证据（日志 `0/5` 段）

```
[OK] venv 归位：VIRTUAL_ENV=/root/vllm-venv（/root/vllm-venv/bin 已加入 PATH）
[OK] CUDA 工具链归位：/root/vllm-venv/lib/python3.12/site-packages/nvidia/cu13（…/bin 已加入 PATH）
[OK] 工具链: ninja=/root/vllm-venv/bin/ninja  g++=/usr/bin/g++
```

⇒ `DEV-20261015-010` 的修复**在真机上生效**（此前 `ninja` 不可见）。

### 2.2 真因原文（日志 99 行起，`EngineCore pid=54241`）

```
FAILED: [code=1] .../cached_ops/sampling/csrc_sampling.cuda.o
 <nvcc 命令行> … -isystem .../nvidia/cu13/include … -c .../flashinfer/data/csrc/sampling.cu
In file included from .../cccl/libcudacxx/include/cuda/std/__cccl/cuda_capabilities.h:24,
                 ...
                 from .../flashinfer/data/include/flashinfer/sampling.cuh:26,
                 from .../flashinfer/data/csrc/sampling.cu:16:
.../libcudacxx/include/cuda/std/__cccl/cuda_toolkit.h:41:8: error: #error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
ninja: build stopped: subcommand failed.
```

⇒ **`ninja: Entering directory` 出现了、`FAILED: [code=1]` 出现了** —— 与上一轮「JIT 在产生输出前就失败（日志 0 字节）」是**完全不同的形态**。

### 2.3 判定条件（读 CCCL 源码，逐字）

`flashinfer/data/cccl/libcudacxx/include/cuda/std/__cccl/cuda_toolkit.h`：

```cpp
#ifndef CCCL_DISABLE_CTK_COMPATIBILITY_CHECK
#  if _CCCL_CUDA_COMPILATION()
#    if !_CCCL_CUDACC_EQUAL((CUDART_VERSION / 1000), (CUDART_VERSION % 1000) / 10)
#      error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
#    endif
#  endif
#endif
```

⇒ 把**头文件**的 `CUDART_VERSION` 拆成 `major.minor`（`/1000`、`%1000/10`），与**编译器**
`__CUDACC_VER_MAJOR__/MINOR__` **严格相等**比较。**差一个 minor 即 `#error`。**

### 2.4 版本实测（`~/vllm-venv` 内，逐包取证）

| 组件 | 实际安装版本 | 推出 | 提供 |
| --- | --- | --- | --- |
| `nvidia-cuda-nvcc` | **13.4.92** | nvcc **13.4** | `nvidia/cu13/bin/nvcc` |
| `nvidia-cuda-crt` | **13.4.92** | 13.4 | `nvidia/cu13/include/crt/*.h` |
| `nvidia-cuda-runtime` | **13.0.96** | `CUDART_VERSION **13000**` ⇒ **13.0** | `nvidia/cu13/include/cuda_runtime_api.h` |
| 元包 `cuda-toolkit` | 13.0.3.0 | —— | 它**声明**的组合：`nvcc==13.0.88.*` ＋ `crt==13.0.88.*` ＋ `runtime==13.0.96.*` |

**成因（依赖漂移）**：`grep Requires-Dist` 全量扫了三处——

- `cuda-toolkit 13.0.3.0`：`nvidia-cuda-nvcc==13.0.88.*`（**钉死**，但只在 `extra == 'nvcc'/'all'` 生效）
- `tilelang 0.1.12`：`nvidia-cuda-nvcc>=13.0.48`（**松**）
- `humming-kernels 0.1.16`：`nvidia-cuda-nvcc`（**未钉版**，`extra == "cu13"`）

⇒ 解析器取了最新 `13.4.92`，而 `nvidia-cuda-runtime` **没有对应 minor 的新版**（头文件停在 13.0.96）⇒ **编译器与头文件被拆成两套 minor**。

### 2.5 附带发现：vLLM 的自动降级**有盲区**（值得记）

`vllm/v1/sample/ops/topk_topp_sampler.py::flashinfer_sampler_supported()` 本应「发现 JIT 不可用 ⇒ 自动退回原生采样」，
其预判走 `_flashinfer_jit_unsupported_reason(capability)`。但该预判**只覆盖 SM 架构不支持 / SM 数 ≤ 16** 一类问题，
**覆盖不到**「要到真正编译那一刻才炸」的版本不兼容 ⇒ 它判定「可用」，随后在 warmup 阶段崩掉。
**⇒ 版本一致性不能指望 vLLM 自己兜底，必须由部署侧前置检查。**

同一函数首行即 `if not envs.VLLM_USE_FLASHINFER_SAMPLER: return False`，
⇒ `VLLM_USE_FLASHINFER_SAMPLER=0` 是**官方支持、确定性生效**的绕行路径（`envs.py` 默认 `True`）。

---

## 3 变更明细

### 3.1 `04-部署运维/scripts/provision-vllm.sh`（新增检查 + 处置；**无新增、无删除**文件）

| 变更对象 | 变更前 | 变更后 | 说明 |
| --- | --- | --- | --- |
| CUDA 版本一致性自检 | **无** | 读 `$CUDA_HOME/include/cuda_runtime_api.h` 的 `CUDART_VERSION` ⇒ `major.minor`；读 `nvcc --version` 的 `release X.Y`；**比对** | 把「要真编译才炸」的缺陷**前置**到体检阶段 |
| 不一致时的处置 | —— | **响亮降级**：打印两边版本＋后果＋两条处置；设 `VLLM_USE_FLASHINFER_SAMPLER=0` | **策略刻意与 §4.1.1「缺工具即 `die`」不同**，理由见下 |
| 强制严格开关 | —— | `REQUIRE_FLASHINFER_SAMPLER=1` ⇒ 不一致直接 `die` | 追求性能时可恢复严格 |
| 启动参数区 | —— | 新增一行 **`采样后端`**（`flashinfer（默认）` / `PyTorch 原生（VLLM_USE_FLASHINFER_SAMPLER=0）`） | 让**实际生效的采样路径进日志**，便于事后举证 |
| 头部注释 | —— | 新增 `REQUIRE_FLASHINFER_SAMPLER=1` 一行 | 开关必须能被 `--help` 看到 |

> **为什么这里「响亮降级」而不是像缺工具那样 `die`（决策，非疏漏）**：
> ① flashinfer 采样只是**加速路径**；vLLM 源码 `flashinfer_sample()` 的 docstring 明写其与原生路径
> *"statistically equivalent"*；② 该内核**只做 top-k/top-p 采样**，**不参与受约束解码**
> （后者在 logits 处理阶段）⇒ **不改变产物口径**；③ 缺工具是**必须补**的环境缺陷（`apt` 一条命令），
> 而版本不一致时**拒绝启动的代价远大于收益**。该理由已同时写入脚本注释与手册 §4.1.2。

### 3.2 `04-部署运维/OPS-002_WSL2-vLLM部署手册.md`（V1.7 → **V1.8**）

| 章节 | 变更 |
| --- | --- |
| 头部 | 状态改写为「卡点＝flashinfer 采样内核 JIT 失败，共**两层**真因」；版本 → **V1.8** |
| **§4.1.2（新增）** | 「CUDA 编译器与头文件必须**同 minor**」：报错原文、CCCL 判定式、版本实测表、依赖漂移成因、`Failed core proc(s): {}` 的误导性、两条处置、脚本自动检测说明、**策略差异的显式理由** |
| **§6.2（新增）** | 「读懂 `Engine core initialization failed`：`Failed core proc(s): {}` 为空＝真因在**上方**」：源码层解释、**「日志行 → 含义 → 去处」对照表**（未进 ninja／进了 ninja 但 FAILED／CCCL `#error`／头文件找不到／真 OOM）、**vLLM 自动降级盲区**的记录 |
| §7.1 | 新增进展块（17:56 第二次实跑）；新增未通过项「**CUDA 编译器与头文件版本一致**」 |
| §7.2 | 新增「实测记录」：17:51–17:53 首次真起服务失败；**反证 `tee` 不是可选项** |
| §10 | 新增 **V1.8** 行（**脚本按标记插入，未手抄长行**；逐行回读确认 V1.0~V1.8 完好） |

---

## 4 复验与验证边界

| 验证项 | 方式 | 结果 |
| --- | --- | --- |
| 语法 | `bash -n provision-vllm.sh` | ✅ 通过 |
| 行尾 / 编码 | Python 逐字节 | ✅ **CR=0**、**无 BOM**、606 行 |
| 分支①不一致→降级 | 替身 `nvcc`(13.4) ＋ 替身 `cuda_runtime_api.h`(13000) | ✅ 打印 `[WARN] CUDA 编译器与头文件版本不一致：nvcc 13.4 ／ CUDART 13.0`，`采样后端 = PyTorch 原生（VLLM_USE_FLASHINFER_SAMPLER=0）`，退出码 0 |
| 分支②一致→放行 | 替身 `nvcc`(13.0) | ✅ 打印 `[OK] CUDA 工具链一致：nvcc 13.0 == 头文件 CUDART_VERSION 13000（13.0）`，`采样后端 = flashinfer（默认）` |
| 分支③`REQUIRE_FLASHINFER_SAMPLER=1`＋不一致 | 同上 | ✅ 打印 `[ERROR]` 与两条例行处置，**退出码 1** |
| 分支④`PATH` 无 `nvcc` | 不提供 `nvcc` | ✅ 告警「未探测到」并继续（退出码 0），**不崩** |
| 端到端干跑 | `DRY_RUN=1 --serve-only` | ✅ 走完 `0/5`~`5/5`，参数区含新增「采样后端」行 |

> ⚠️ **验证边界（如实登记）**：
> - 本会话沙箱**没有 WSL**（非管理员、`wsl.exe` 被程序黑名单拦截），上述分支用**替身二进制**驱动，**未在真机 WSL 内复跑**；
> - **`nvcc` = 13.4 已【直读】证实**：沙箱无法执行 Linux ELF，故**不能跑 `nvcc --version`**；改从**二进制本体**取
>   其内嵌的横幅字符串 —— `grep -a -o -m1 'Cuda compilation tools, release [0-9.]*' <CUDA_HOME>/bin/nvcc`
>   输出 **`Cuda compilation tools, release 13.4`**（`nvidia/cu13/bin/nvcc`，37 426 800 字节），
>   并与 `nvidia_cuda_nvcc-13.4.92.dist-info` 的 `Version: 13.4.92` **互相印证** ⇒ **非推定**。
>   头文件侧同理直读：`#define CUDART_VERSION  13000`（`nvidia/cu13/include/cuda_runtime_api.h`）。
> - ⚠️ **注意：结论本身有更强的逻辑保证，不依赖版本号的精确取值** —— 已知头文件为 **13.0**、CCCL 要求两者相等、
>   而该 `#error` **确实被触发** ⇒ **编译器必然不等于 13.0**。「恰好是 13.4」是额外的定量信息，不是结论的前提。
> - **根治命令尚未执行**（§4.1.2 ①），故「版本对齐后 flashinfer 采样可正常工作」**仍属预期而非实测**。

---

## 5 纪律与教训（写入工程记忆）

1. **`Failed core proc(s): {}` 为空时，真因一定在日志上方** —— vLLM v1 的这条 `RuntimeError` 只是**末端兜底**，
   且**映射可能为空**。看到它不要就地分析，先把**上方 `EngineCore` 子进程的 traceback** 取出来。
2. **`tee` 不是可选项** —— 脚本末步是 `exec`，输出默认不落盘。上一轮因此「现场无日志」只能靠文件痕迹反推；
   本轮有了 64 KB 日志，**真因是逐字读出来的**，差别就是「推断」与「确证」。
3. **「报错指向的组件」未必是「缺陷所在的组件」** —— 报错出自 flashinfer（CCCL），
   但缺陷在 **CUDA 工具链组件版本**（`nvcc` vs `runtime`）。⇒ 看到 `#error` 先问**判定条件是什么**，再回推输入。
4. **pip 环境的「版本自洽」不能默认成立** —— 同一命名空间（`nvidia/cu13/`）下的文件可能来自**不同 minor 的轮子**；
   元包的精确 pin 会被别的包的松 pin / 未钉版依赖**冲掉**。⇒ 涉及 **JIT 编译**的环境，必须**显式校验编译器与头文件版本**。
5. **`PATH` 里的替身路径不要用 `C:/…` 形式**（本轮复现）：MSYS/Git Bash 下**冒号是分隔符**，
   `PATH="C:/x:$PATH"` 会被**静默截成两段** —— 与 `DEV-20261015-010` 记的 `readlink -f` 是**同一族坑**，**实跑才暴露**。

---

*记录性质：工程推进过程留痕　｜　编号 `DEV-20261015-011`　｜　保留原则：永久保留*
