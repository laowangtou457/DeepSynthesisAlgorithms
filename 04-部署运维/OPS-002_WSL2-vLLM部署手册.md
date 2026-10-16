# WSL2 + vLLM 部署手册（`OPS-002`）

> **任务**：`T-012`（D-006：Qwen2.5-7B 部署手册——vLLM 启动参数、显存调优、OOM 排查、单卡 10 并发配置）
> **决策依据**：`PRO-006`《`T-004` 生成链路接入·开工方案与引擎选型对比》§3 —— **2026-10-15 项目方裁决取路线 A（WSL2 + vLLM）**
> **状态**：🟢 **服务已起成，端到端校验中** —— Windows 侧（组件 / 重启 / 虚拟化 / 发行版落盘）**已全部完成**；
> Linux 侧 **vLLM 0.31.0 已装成**（`~/vllm-venv`，pip 26.2.1），**`--serve-only` 走完 `0/5`~`5/5`，
> `Application startup complete.` @2026-10-15 18:10:42，监听 `http://0.0.0.0:8001`**。实测生效值见 **§5.1**。
> 启动后期曾连踩**两层**真因，均已根治：① `ninja` 不在 `PATH`（**§4.1.1**）
> ② **`nvcc`(13.4) 与 CUDA 头文件(13.0) 版本不一致**，被 CCCL **硬性**拒绝（**§4.1.2**、**§6.2**）——
> 后者现由脚本**自动检测并响亮降级**（`VLLM_USE_FLASHINFER_SAMPLER=0`，不改变产物口径）。
> 判据链与「无日志时如何定位」见 **§6.1**。
> ✅ **服务连通性与受约束解码已做端到端校验**（2026-10-15 18:24–18:26）：`/v1/models` **200**；
> 受约束解码经**严格形式 ＋ 对照组**证实确实生效；用**真实 `CFG-006` schema 生成 2 次**，
> 得出**受约束解码的能力边界**（**§4.3.1**：结构层直出即合规、**门禁层 0/2**）。
> §7 待实测清单**仍不得跳过**（连发多段、10 并发 TTFT/TPOT；⚠️ 2026-10-16 订正：**门禁层直出率已实测**、应用侧 `/ready` 已实测）。**2026-10-16 新增一条窗口边界结论**：`--max-model-len` 提到 **32768** 后 `storyboard` 段**一次通过**（`ISSUE-032` 解除），但 **`shot_prompt` 段的「输入自身」约 5.0 万 tokens**（＝模板把上游重复插入 5 次／3 次所致）⇒ **提窗这条路已走到 Qwen2.5-7B 的原生上限**；且实测证明**`segment` 拆段只减输出、不减输入** ⇒ 见 **§5 与 §7.3**、`ISSUE-037`。
> **版本**：V1.14 ｜ **日期**：2026-10-16

---

## 1 本手册的边界

| 做 | 不做 |
| --- | --- |
| 给出可复制粘贴的安装与启动路径 | **不下载模型权重**（本机已有，零拷贝复用） |
| 给出启动参数基线与调优方法 | **不编造实测数字**（显存、吞吐、并发一律标 `<待实测>`） |
| 给出 OOM 排查决策树 | **不替代交付门禁**（产物合法性由 `validate_pack.py` 判） |
| 给出上机核对清单 | **不改动任何提示词/契约资产** |

**分层纪律**：部署侧只管「服务起得来、跑得稳」，**产物对不对由门禁判**。两者不得互相代偿。

---

## 2 本机环境基线（2026-10-15 实测）

| 项 | 实测值 | 对本手册的影响 |
| --- | --- | --- |
| 操作系统 | Windows 11 25H2（build **26200.9711**） | ✅ 远超 WSL2 的 19041 门槛 |
| 虚拟化 | `HypervisorPresent=**True**`（重启后实测）；`VirtualizationFirmwareEnabled` 重启后为 `False` 属**内核接管、非异常**（见 §3.5.1） | ✅ 虚拟化平台已就绪；`systeminfo` 报 `A hypervisor has been detected.` |
| GPU | **NVIDIA GeForce RTX 4090**，compute_cap **8.9**，**23028 MiB** | ✅ 支持 BF16 + FlashAttention-2（`T-010` 路线成立） |
| 驱动 | **610.88** | ✅ 远超 WSL2 直通门槛（560.94 起） |
| 系统盘余量 | **C: 30.2 GB** | ⚠️ 偏紧 → 发行版**必须落 E 盘**（E 余 515.5 GB） |
| WSL 现状 | ✅ **已可用**（2026-10-15 14:11）：两个可选组件 `Enabled`，发行版 **`Ubuntu`** 经 §3.3 **手动路径**导入，落 `E:\wsl\Ubuntu\ext4.vhdx`（1.3 GB） | §4 即为 Linux 侧供给指引 |
| 模型权重 | `E:\models\Qwen2.5-7B-Instruct`，4 分片 ≈**15.2 GB**（BF16 全量，Apache-2.0） | ✅ `/mnt/e/models` 零拷贝，**无需重下** |

> ⚠️ **本文档中除本节外的一切数值均为待实测基线**，不得据以填写验收报告。

---

## 3 Windows 侧：安装并落位 WSL2

脚本：`scripts/install-wsl2.ps1`（**必须保留 UTF-8 BOM**，原因见 §3.6）

### 3.1 执行

```powershell
# 管理员 PowerShell（右键 →「以管理员身份运行」）
cd E:\深度合成算法工程材料\04-部署运维\scripts
powershell -ExecutionPolicy Bypass -File .\install-wsl2.ps1
```

参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `-Distribution` | `Ubuntu-24.04` | 发行版 |
| `-InstallRoot` | `E:\wsl` | **落盘根目录**（务必非系统盘） |
| `-SkipComponentEnable` | 关 | 组件已启用时跳过，避免重复提权 |
| `-SkipRebootCheck` | 关 | 自动化场景跳过重启中断 |

退出码：`0` 成功 ｜ `2` 非管理员 ｜ `3` 组件启用后需重启 ｜ `4` 安装失败。

> ⚠️ **必须经 `powershell -ExecutionPolicy Bypass -File` 调用**，不可直接 `.\install-wsl2.ps1`：
> 本机执行策略 `Machine`／`CurrentUser`／`Process` **均为 `Undefined`**（即默认 `Restricted`），
> 直接调用会被拦。**也不可用 `python` 执行**——那是把 PowerShell 脚本当 Python 解析
> （实测报 `SyntaxError: invalid character '（'` —— 报错位置在第 3 行的中文全角括号，**与脚本语法无关**）。
>
> **首次执行的实测结果（2026-10-15）**：退出码 **3**，两个可选组件均已 `Enabled`，
> `RebootPending: True` ⇒ **重启 Windows 后重跑同一命令**即继续。
>
> ⚠️ 组件启用时 `Enable-WindowsOptionalFeature` 会**狂刷进度条**（实测数百行、淹没脚本自身输出）；
> 脚本已用 `-LogPath` 重定向到 `E:\wsl\_logs\enable-*.log`。

### 3.1.1 ⚠️ 实测踩坑：「退出码 0 ≠ 安装成功」（**脚本已修正**）

**首轮实跑的症状**：组件启用 ✅、WSL 更新 ✅、四步落盘步骤 a~d **全部打印出来**、
`[OK] 发行版已落位：E:\wsl\Ubuntu-24.04`，但**紧接着**就打出
`[WARN] 未找到 ...\ext4.vhdx`。事后核查 `E:\wsl`：**只有 `_logs` 空目录，无 vhdx、无 tar、无发行版**。

**根因（三重，均已修正）**：

| # | 缺陷 | 修正 |
| --- | --- | --- |
| 1 | b/c/d 三步（`--export`／`--unregister`／`--import`）**完全没有退出码检查**，且 `2>&1` 把错误流丢进 `$null` | 每步都检查并**回显 wsl 的原始输出** |
| 2 | **只看 `$LASTEXITCODE` 不可靠** —— `wsl.exe` 在「组件刚启用未重启」时可能返回错误文本而退出码仍为 0 | 改为「退出码 ＋ 实际产物」**双重校验**：步骤 a 后查 `wsl -l -q` 是否含目标发行版；步骤 b 后查 tar 是否存在；步骤 d 后查 `ext4.vhdx` 是否生成 |
| 3 | **收尾自检只打 WARN 就 `exit 0`** —— 假成功从「自检」这里漏了过去 | 终态校验不过**一律 `exit 4`**，并在正文打印「本次安装未成功」 |

> ⚠️ **教训（本工程通用）**：**「执行完」不等于「成功」**。凡自动化动作，
> 终态必须有**可观测的产物判据**（文件存在／注册表条目／清单可查），
> 不能以「步骤都跑过了」为准。这与 `ISSUE-023`（派生基线未随生成器复现）
> 是同一族——**「本应同时更新/验证的两件事只做了一件」**。

> ⚠️ 附带修正两处：`wsl.exe` 输出为 **UTF-16LE**，直接显示是乱码
> （首轮实跑输出中那串 `貫ㄋ…` 即是），现由 `Invoke-Wsl` 统一去 NUL 并回传退出码；
> `VERSION 2` 检测正则原写 `(?m)VERSION\s+2` —— **它匹配的是表头列名、恒为真、形同虚设**，
> 现改为匹配数据行行尾（`^\s*\*?\s*\S+\s+\S+\s+2\s*$`，已 6/6 用例验证）。

### 3.2 落盘策略（为何要「装 → 导出 → 注销 → 导入」）

`wsl --install` **不支持直接指定安装路径**，发行版一律先落 `%LOCALAPPDATA%\Packages`。故脚本用四步搬迁：

```
装到默认位置 → wsl --export 到 E:\wsl\Ubuntu-24.04.tar
             → wsl --unregister（**释放 C 盘占用**）
             → wsl --import 到 E:\wsl\Ubuntu-24.04
```

⚠️ **`--unregister` 是删除操作**：若跳过它，C 盘会**同时留着两份**发行版（默认位置 + E 盘），白占约 1–2 GB。脚本已按序执行，但**请在执行前确认 E 盘 tar 已成功生成**（见退出码 4 的处理）。

### 3.3 备用路径：手动下载镜像 ＋ `import-distro.ps1`

若重启后 `install-wsl2.ps1` 的 `--install` 仍失败，走**手动路径**。

**实测根因（2026-10-15 第三轮）**：`wsl --install` 报
`Wsl/InstallDistro/WININET_E_CONNECTION_RESET` —— 它要从
`raw.githubusercontent.com` 拉发行版清单，**下载时连接被重置**。
本机 GitHub HTTPS 走代理 `127.0.0.1:7890`，而该代理**间歇性失败**
（同一 URL 用 `Invoke-WebRequest` 复测 **6/6 成功** ⇒ 抖动而非不通）。

**操作（两条任选）**：

| 方式 | 步骤 |
| --- | --- |
| **A（推荐）** | `powershell -ExecutionPolicy Bypass -File .\import-distro.ps1` —— **无需参数**，脚本自动下载 → 解包 → 导入 |
| **B（浏览器手工）** | 下载 `https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl`（**371 MB**）放入 `E:\distros`，再跑同一命令（自动识别） |

> ⚠️⚠️ **`.wsl` 的真实格式与扩展名给人的直觉相反**（2026-10-15 实测纠错）：
> `ubuntu-24.04.5-wsl-amd64.wsl` **不是 zip 容器** —— 其文件头是 `1f 8b 08`（gzip），
> `zipfile.is_zipfile()` 返回 `False`。它实质是**一个 gzip 压缩的 rootfs tar**
> （内部顶层即 `bin/ etc/ dev/ usr/`），**不含** `manifest.json` / `install.tar.gz`。
> 按「zip 容器」写的解包代码会直接抛 `BadZipFile: File is not a zip file`。
> ⇒ 脚本已改为**先判 zip、否则按 gzip / 裸 tar 处理**（两种形态都兼容）。
>
> ⚠️ **`wsl --import` 只接受 raw tar**，不接受 gzip / zip ⇒ 必须先在本地解成 raw tar 再导入。
>
> ⚠️ **Windows 自带 `tar.exe` 读不了 zip**（实测报「This does not look like a tar archive」，
> 尽管底层是 libarchive）；`Add-Type`＋`System.IO.Compression` 亦被本机安全策略拦截
> ⇒ 压缩容器一律交给 **Python** 处理。
>
> ⚠️ Ubuntu 官方**只提供 `.wsl` 形态**，实测
> `cloud-images.ubuntu.com/wsl/releases/...rootfs.tar.gz` 等**直链全部 404**
> （服务器明确响应，非网络问题）⇒ **不要凭猜测拼路径**。
> 权威来源＝微软官方清单 `DistributionInfo.json`。

> ⚠️ **三种传输方式的实测结果**（后续脚本直接照用）：
> `WebClient.DownloadFile` ❌ 被安全策略拦截（download cradle）｜
> `Start-BitsTransfer` ❌ 被拦截（静默后台下载）｜
> **`Invoke-WebRequest` ✅ 可用**（同一 URL 6/6 成功）。

> ⚠️ **镜像为何放 `E:\distros` 而非工程目录**：项目目录是 **Git 仓库**，
> 第三方二进制（371 MB 级）入库会撑大仓库，且 `.git/hooks/pre-push` 的真名扫描
> **覆盖不了二进制内容** ⇒ 等于绕开脱敏防线（同 `T-079` 行确立的纪律）；
> 镜像属**外部依赖**，不入 `CM-002` 取号表。详见 `E:\distros\README-发行版镜像存放说明.md`。

`import-distro.ps1` 的五道校验（均已实跑验证）：

| 校验 | 行为 |
| --- | --- |
| 组件状态 ＋ **待重启标记** | 未重启 ⇒ 直接拒绝并给出重启指令（**首轮失败的真正根因**） |
| 占位符 ＋ 目录为空 | 含 `<>\|:*?"` ⇒ 提示正确用法；无镜像 ⇒ **自动下载**（2 源 × 3 重试） |
| 大小（≥100 MB）＋ **结构有效性** | 404 错误页、空文件 ⇒ 拒绝；镜像按 **gzip / zip 双兼容** 规整为 raw tar，再以 **Python 全量扫描 ＋ rootfs 布局判据**校验（**不用 `tar.exe` 退出码**，见 §3.3.1 ③） |
| **终态：`ext4.vhdx` 是否生成** | 未生成 ⇒ `exit 4` 并保留中间件供重试（**不再假成功**） |

---

### 3.3.1 ⚠️ 实测踩坑：解包与校验环节曾有三处缺陷（**脚本已修正**）

手动路径**连续两轮**实跑失败：第一轮报错只有一行 `Traceback (most recent call last):` 就断了，
**看不出任何原因**；修完再跑，又被**判据错误**拦下。合计**三个独立缺陷**：

| # | 缺陷 | 后果 | 修正 |
| --- | --- | --- | --- |
| ① | Python 片段需要 **2 个** 参数（`src, dst`），PowerShell 只传了 `src` | `sys.argv[2]` 越界 ⇒ `IndexError: list index out of range` | 改为 `Invoke-Native $pyCmd @($pyFile, $TarPath, $inner)` |
| ② | 脚本开头 `$ErrorActionPreference = 'Stop'`，而 **PS 5.1 会把原生程序写入 stderr 的每一行都升级为终止性错误**（`NativeCommandError`） | traceback 只剩第一行，**真正的报错行永远看不到**，等于把①藏起来了 | 新增 `Invoke-Native` 包装：调用期间**临时降级为 `Continue`**，跑完还原 |
| ③ | **拿 `tar.exe` 的退出码当完整性门禁** | 该 tar **结构完好**（49190 成员、末尾 2048 字节全零＝正确 EOA、总长是 10240 整数倍），但因归档里 **2 个名字异常的条目**（Ubuntu 打包侧遗留，名字含字面 `\x2d`）＋ 1 个含非 ASCII（`ő`）的证书软链，bsdtar **列出 49188/49190 条却返回退出码 1** ⇒ 好镜像被判「文件损坏」**拒绝导入** | 改用 **Python（`tarfile`）** 权威校验：全量扫描成员数 ＋ **确认 rootfs 布局**（顶层须有 `etc` / `usr`）；`tar.exe` 降级为**参考列表**，非零退出码**只提示、不拦截** |

> ⚠️ **②是一条通用纪律**：凡「脚本设了 `Stop` ＋ 又要 `2>&1` 收集外部程序输出」，
> 都必须用 `Invoke-Native` 这类包装，**不能直接写 `& exe ... 2>&1`** ——
> 否则外部程序的报错会被吞成一行，而且**静态语法检查完全查不出来**（Parser 全绿）。
>
> ⚠️ **③是一条通用纪律，与 §3.1.1 互为镜像**：
> §3.1.1 的教训是「**退出码 0 ≠ 成功**」（wsl 静默失败）；
> 本次是「**退出码非 0 ≠ 失败**」—— 外部工具的退出码**只在语义明确时**才是判据。
> 本工具链已两次踩在同一族上，故凡以外部程序退出码作门禁时，**必须同时给出「为什么这个码可信」的依据**；
> 语义不明时，应改用**能表达意图的替代判据**（此处＝「是不是 rootfs 布局」，而非「tar 命令满不满意」）。
>
> ⚠️ 附带修正两条：
> ① 原 `tar.exe -tf $TarPath | Select-Object -First 5` 有隐患 —— `-First` 提前掐断管道会让
> `tar.exe` 收到 broken pipe 并**返回非 0**，又是一个假失败源（已改为整份收下再取前 5 行）；
> ② `Invoke-Wsl` 里同样是裸 `& wsl.exe ... 2>&1`，会让 wsl 的真实报错被替换成「wsl.exe 未能启动」
> （方向完全错），已同样降级 EAP。

**已备好的中间产物**（可跳过解包，直接进导入）：
`E:\distros\Ubuntu-24.04-rootfs.tar`（**1216.5 MB**，49190 条目，`ustar` 魔数正确，
顶层为 `usr/ var/ etc/ run/ dev/ root/` ＋ usrmerge 软链；Python 权威校验耗时约 **1.8 s**）。
脚本按体积取 `E:\distros` 下**最大**的候选包，故会选中该 tar 并**跳过解包**，直接 `wsl --import`。

---

### 3.4 为什么不落 C 盘

`REQ-001` §10.1 约定「C 盘只放运行环境」，权重与数据落 E/F。而 WSL2 的 `ext4.vhdx` 会随 **发行版 + pip 缓存（torch/vLLM 的 CUDA 轮子约 8–10 GB）+ 容器镜像**持续增长——本质是「数据」，不应占系统盘。C 盘 30.2 GB 余量下，这是**硬约束**而非偏好。

### 3.5 GPU 直通

WSL2 需 **Windows 侧 NVIDIA 驱动 ≥ 560.94**（本机 610.88 ✅）。装完发行版后须核对：

```bash
nvidia-smi --query-gpu=name,compute_cap,memory.total,driver_version --format=csv
```

- **能列出 GPU** → 直通成功，进入 §4；
- **报 command not found** → 驱动未生效，重启 Windows 后复测；
- **能列出但 CUDA 不可用** → Linux 侧装 CUDA runtime（`torch` 自带轮子通常已含，无需另装）。

> ⚠️ **不要在 WSL2 内 `apt install nvidia-driver`**：WSL2 的 GPU 驱动由 **Windows 侧**提供，Linux 内安装会冲突。

### 3.5.1 ⚠️⚠️ 虚拟化判据：重启后字段会「翻转」，**别只看一个字段**（脚本已修正）

**症状**：重启 Windows 后重跑 `install-wsl2.ps1`，脚本报
`[WARN] BIOS 虚拟化（Intel VT-x / AMD-V）未开启 —— WSL2 无法启动` 并退出。**但虚拟化其实完全正常。**

**根因**：`Win32_Processor.VirtualizationFirmwareEnabled` 与 `SLAT` 这两个字段
反映的是 **BIOS 层的 VT-x/AMD-V 与 SLAT 设置**。一旦 **Hypervisor 加载**（即启用
`VirtualMachinePlatform`／Hyper-V 后重启），内核会**接管这两个字段**，
Windows **不再暴露其真实值** ⇒ **报 `False`，但不等于虚拟化不可用**。

**本机实测对照**（同一台机器，仅因是否重启而不同）：

| 字段 | 重启前 | 重启后 | 含义 |
| --- | --- | --- | --- |
| `HypervisorPresent` | `False` | **`True`** | ✅ **首选判据**：True 即虚拟化平台内核已加载 |
| `VirtualizationFirmwareEnabled` | `True` | **`False`** | ⚠️ 重启后被内核接管，报 False **不代表不可用** |
| `SLAT` | `True` | **`False`** | ⚠️ 同上 |

**交叉验证口径（最可靠）** —— `systeminfo` 会输出：
```
Hyper-V Requirements:  A hypervisor has been detected.
                        Features required for Hyper-V will not be displayed.
```
出现 `A hypervisor has been detected.` 即证明 **Hypervisor 已加载**，虚拟化可用。

**修正后的判定逻辑**（`install-wsl2.ps1` §1）：

| 优先级 | 判据 | 结论 |
| --- | --- | --- |
| **首选** | `HypervisorPresent = True` | ✅ 放行（虚拟化平台内核已就绪） |
| 次选 | `VirtualizationFirmwareEnabled = True` | ✅ 放行（BIOS 已开，但组件刚启用尚未重启时的正常形态） |
| 均 False | 两者皆假 | ❌ 才是真的未开启，提示进 BIOS |

> ⚠️ **教训（与 §3.1.1 同族）**：这是本工程第二次出现**「同一指标在不同状态下取值不同，
> 而判据只认其中一个」**导致的假失败。判定系统状态时，
> **必须选「语义稳定」的那个字段，并对「会翻转的字段」明确注释其翻转条件**。
> 若无判据，本次会被永久卡在「虚拟化未开启」，而实际早已就绪。

### 3.6 ⚠️ 脚本编码陷阱（必读）

本机为 **Windows PowerShell 5.1（Desktop，实测 5.1.26100.9711）**。该版本读取 `.ps1` 时按 **ANSI 代码页（本机 gb2312）** 解码 —— **UTF-8 无 BOM 的中文脚本会被误解码**，破坏引号配对，报出与真实代码无关的语法错误。

实测对照：

| 文件编码 | 解析器结果 |
| --- | --- |
| UTF-8 **无 BOM** | ❌ **7 处语法错误**（假阳性，行 44/58/98/132/166…） |
| UTF-8 **有 BOM** | ✅ **0 错误**（4 参数 + 4 函数全部正确解析） |

**故：`install-wsl2.ps1` 必须带 BOM**。改动该文件后请复跑语法校验：

```powershell
powershell -NoProfile -Command "$e=$null;[Management.Automation.Language.Parser]::ParseFile('<路径>',[ref]$null,[ref]$e);if($e){$e|%{$_.Message}}else{'PARSE OK'}"
```

### 3.7 ⚠️ 打开 WSL 时的「localhost 代理」提示（**无害，可忽略**）

进入 WSL 时会打印这样一行：

```
wsl: 检测到 localhost 代理配置，但未镜像到 WSL。NAT 模式下的 WSL 不支持 localhost 代理。
```

**这不是错误 —— WSL 已经正常启动。**

**成因**：WSL 的 `autoProxy`（默认开启）会读取 Windows 的 WinINET 代理设置
（本机实测 `ProxyEnable=1`、`ProxyServer=127.0.0.1:7890`）。而 **NAT 模式下 WSL 的
`127.0.0.1` 是它自己的回环**，宿主上的 7890 在 WSL 内并不存在，所以 WSL **不镜像**该配置，
只给一行提示。

> ✅ **反过来说这是好事**：正因为「**不镜像**」，WSL 内**不会**被塞进一个指向空地址的
> `http_proxy` —— 否则 pip / apt 会**全部连不上**。提示只是在告诉你「我不会假装帮你转发」。

| 你的需求 | 处置 |
| --- | --- |
| **本手册路径（走国内 pip 源，直连）** | **忽略即可**，零影响 —— §4.1 用国内镜像直连，不经代理 |
| 只想让这行提示消失（保持 NAT 模式） | 在 `%USERPROFILE%\.wslconfig` 写入 `[wsl2]` ＋ `autoProxy=false`，再 `wsl --shutdown`（**本机该文件尚不存在**，需新建） |
| 想让 WSL 内真的能用上宿主代理 | 见下方 **§3.7.1** |

> ⚠️ **务必先确认没被塞进坏代理**：进 WSL 后执行
> ```bash
> env | grep -i proxy || echo "NO-PROXY-ENV"
> ```
> 输出 `NO-PROXY-ENV` ⇒ 直连干净（**预期**），可放心继续；
> 若出现 `127.0.0.1:7890` ⇒ NAT 下该地址**不可达**，pip / apt 会全数失败，
> 需要 `unset http_proxy https_proxy`，或按 §3.7.1 换成**可达的宿主地址**。

### 3.7.1 让 WSL 用上 Windows 的代理（**三条路，按推荐度排序**）

**为什么直接用不了**：本机代理客户端（`iKuuuVPNCore`）**只监听 `127.0.0.1:7890`**。
2026-10-15 实测 `netstat`：

```
TCP    127.0.0.1:7890    0.0.0.0:0    LISTENING    20980
```

而 NAT 模式下 WSL 的 `127.0.0.1` 是**它自己的回环**，宿主上的 7890 在 WSL 内并不存在。
另实测：从宿主的 `172.30.224.1` / `192.168.20.38` / `26.26.26.1` 三处访问 `:7890`
**均为 `000`（连不上）** ⇒ 确认是「**仅绑回环**」，不是防火墙拦截。

| # | 做法 | 适用 / 代价 |
| --- | --- | --- |
| **A** | **客户端里打开「允许局域网 / Allow LAN」** | 最省事。打开后监听地址变为 `0.0.0.0:7890`，WSL 内改用 `http://172.30.224.1:7890`。⚠️ **客户端若没有这个开关则此路不通**（iKuuu 类客户端不一定提供） |
| **B** | `.wslconfig` 设 `networkingMode=mirrored` | 微软官方做法：改完 `wsl --shutdown` 再进，WSL 内 **`127.0.0.1:7890` 直接可达**。⚠️ 代价是**改变 WSL 网络行为**；本机还装有 TAP 类虚拟网卡（`LetsTAP`），镜像模式与这类网卡偶有冲突 ⇒ 改动前先记录原状 |
| **C** | 宿主上把 7890 转发到非回环地址 | `netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=7891 connectaddress=127.0.0.1 connectport=7890`（**需管理员**，另需放行入站 7891），WSL 内用 `http://172.30.224.1:7891` |

> ⚠️ **先掂量值不值得**：vLLM 轮子（6~8 GB）走**国内镜像直连**已有 **12.3 MB/s**（§4.1 实测表），
> 8 分钟量级；走代理虽可达 **62 MB/s**，但要多做上面这些改动、且会动到网络模式。
> **先按 §4.1 换源；只有换源后仍明显偏慢，才去动代理。**

**宿主地址不用手算** —— 在 WSL 内执行：

```bash
ip route show default | awk '{print $3}'     # 输出即宿主在 WSL 网段上的地址（本机当前为 172.30.224.1）
```

打通后**在 WSL 内**验证：

```bash
curl -sI -x http://172.30.224.1:7890 -m 10 https://pypi.org/simple/ | head -1   # 期望 HTTP/… 200
```

## 4 Linux 侧：安装并启动 vLLM

脚本：`scripts/provision-vllm.sh`

### 4.1 执行（四步）

> ✅ **发行版已就位（2026-10-15 14:11 实测）**：经 §3.3 **手动路径**导入，
> 实例已落 `E:\wsl\Ubuntu\ext4.vhdx`（**1.3 GB**，已生成）；Windows 侧确认
> `RTX 4090 / compute_cap 8.9 / 23028 MiB / 驱动 610.88`（✅ ≥ 直通门槛 560.94）。
>
> ⚠️ **发行版注册名以 `wsl -l -v` 的实际输出为准**。本机经手动路径导入，名字由 tar 文件名推导
> （`Ubuntu-24.04-rootfs.tar` → 取首个 `[-_.]` 前段）＝ **`Ubuntu`**；
> 而路径 A（`install-wsl2.ps1 -Distribution Ubuntu-24.04`）会是 `Ubuntu-24.04`。
> **两者不同名**，下文一律写成 `wsl -d Ubuntu`，你若走路径 A 请自行替换。

**① 进发行版**（已有窗口则跳过）

```bash
wsl -d Ubuntu
```

**② 前置体检**（约 30 秒 —— 先确认 GPU 直通，否则 §③ 必然失败）

```bash
nvidia-smi                      # 应列出 RTX 4090
```

- 列出 GPU → 直通成功，继续；
- `command not found` → 见 §3.5（**切勿在 Linux 内 `apt install nvidia-driver`**）。

```bash
python3 --version && df -h / && free -g
```

- `df -h /` 的 `Avail` 需 ≥ **10 GB**（vLLM ＋ torch ＋ CUDA 运行库轮子合计约 5~8 GB）；
- Ubuntu 24.04 自带 python3.12，满足 vLLM 轮子要求。

```bash
env | grep -i proxy || echo "NO-PROXY-ENV"     # 确认没被塞进 NAT 下不可达的 localhost 代理
```

- 期望 `NO-PROXY-ENV` ⇒ 直连干净，继续；
- 若打印出 `127.0.0.1:7890` ⇒ **NAT 下该地址不可达**，须 `unset http_proxy https_proxy`（详见 §3.7）。

**③ 补齐 pip（**一次性**，Ubuntu 系统 python 默认不带）**

Ubuntu 24.04 的系统 python **不自带 pip**，且**显式禁用 `ensurepip`**（发行版策略）。
`2026-10-15` 实跑 `DRY_RUN=1 bash provision-vllm.sh`，实测停在 `2/5` 并报：

```
[WARN] pip 不可用
[ERROR] 系统 python3 无 pip，且 Debian/Ubuntu 已禁用 ensurepip（正常策略，非故障）。
```

> ⚠️ **这是发行版策略，不是环境损坏**（PEP 668 `externally-managed-environment`）
> —— 不要据此判断「WSL 装坏了」而去重装发行版。

**方案 ②（推荐）：venv 隔离** —— 不污染系统 python，将来重装只需删目录

```bash
apt-get update && apt-get install -y python3-venv && python3 -m venv ~/vllm-venv
```

**方案 ①：装系统 pip** —— 更短，但后续安装须带 `--break-system-packages`（脚本会自动加上）

```bash
apt-get update && apt-get install -y python3-pip
```

> 脚本会**自动识别 venv**：`PY_BIN` 指向 venv 时**自动摘掉** `--break-system-packages`
> （venv 内没有 `EXTERNALLY-MANAGED` 标记，该开关无意义），并额外打印 `(venv)` 标记。
> 2026-10-15 三路实测：非 venv → `--break-system-packages`；venv → 空；显式设 `PIP_ARGS` → 原样尊重。

> ⚠️ 若 `apt-get` 极慢或超时，先确认网络：`getent hosts archive.ubuntu.com`；
> WSL 内可用 `unset http_proxy https_proxy`（见 §3.7）后再重试。

**④ 跑供给脚本**

```bash
cd /mnt/e/*/04-*/scripts            # 通配符展开，免手敲中文路径
DRY_RUN=1 PY_BIN=~/vllm-venv/bin/python bash provision-vllm.sh   # 先干跑：只打印参数，不装、不启动
```

> **方案 ②（venv）的前缀自 2026-10-16 起可省略**：脚本在未显式指定 `PY_BIN` 时会**自动探测 `~/vllm-venv`**
> （探不到才回落系统 `python3`，并响亮提示）。原因见 §4.1.3「解释器自动探测」——
> 漏写前缀**不会**提示「venv 未找到」，而是**静默降级成系统解释器**，并连带把「运行环境归位」与
> 「CUDA 版本一致性自检」两段**整段跳过**。
> ⚠️ **走方案 ①（系统 pip）时必须显式写 `PY_BIN=/usr/bin/python3`** ——
> 否则自动探测会优先选中已存在的 `~/vllm-venv`。显式传参**永远优先**，脚本化场景仍建议写全。
>
> `DRY_RUN=1` **不会因缺 pip 或缺 vLLM 而中断**（2026-10-15 实测）——
> 它会一路打印到 `5/5` 的完整启动参数，正是干跑的目的所在。

确认参数无误后正式执行（**必须显式指定 pip 源** —— 见下方实测，源选错差 32 倍）：

```bash
PY_BIN=~/vllm-venv/bin/python PIP_INDEX=cn bash provision-vllm.sh
```

**pip 源吞吐实测（2026-10-15）** —— ⚠️ 这张表**只认「持续」口径**：

| 源 | 简写 | 短窗（8 s 单流） | **持续** | 结论 |
| --- | --- | --- | --- | --- |
| `mirrors.aliyun.com` | `aliyun` | 0.38 ／ **21.92** | **0.31** | ❌ **不要用** |
| `repo.huaweicloud.com` | `huawei` | 23.05 | <待现场测> | ✅ 优先候选 |
| `mirrors.cloud.tencent.com` | `cn` | 12.33 ／ 4.43 | <待现场测> | ✅ 优先候选 |
| `pypi.org` | — | 15.60 | <待现场测> | 可用 |
| `mirrors.ustc.edu.cn` | `ustc` | 11.7 ／ 403 | — | 时好时坏 |
| `pypi.tuna.tsinghua.edu.cn` | `tuna` | **403** | — | ❌ 不可用 |

> 阿里云的「持续 0.31 MB/s」不是估算：一次真实的 pip 安装（累计 **2.5 GB / 224 个对象**）
> 按缓存文件的完成时间**逐个反算**得到，区间 0.20~0.37、**极稳定** —— 稳定得不像拥塞，
> 更像被按住了（令牌桶/按来源限速）。异路径旁证：另一条出口上两次探测同为 0.18、0.21 MB/s。

> ⚠️⚠️ **本表在 V1.6 做过一次「口径订正」，务必看懂**：
> 1. V1.2 把**阿里云列为「采用」**，依据是「200 / 0.57 s」——那只是对一个**几十 KB 索引页**发 HEAD，
>    **根本测不出吞吐**。教训一：**小文件响应快 ≠ 带宽大；可达性 ≠ 吞吐**，两者要分开测。
> 2. V1.5 改用「真实轮子 + 12 s 短窗」排名，把阿里云判成 **0.38 MB/s「极慢」**——**方向对了，但数值仍不可信**：
>    同一天稍后再测，**同一个阿里云**短窗读数变成 **21.92 MB/s**（差 **57 倍**）；腾讯云同日也是 12.33 ↔ 4.43。
>    ⇒ 教训二：**「哪个源快」不是源的固定属性，而是测量时点**；短窗单流常只吃到 CDN 的**突发额度**。
> 3. **真正能预测 pip 下载速度的只有「持续」口径**。本机实例：阿里云短窗 **21.92**，而 pip 实际持续
>    **0.31** —— 落差 **70 倍**，这就是「测速 22 MB/s、实际下载 0.3 MB/s」的全部答案。

**不确定当前哪个最快 ⇒ 现场测，别凭印象（更别只看一列）**：

```bash
bash provision-vllm.sh --speedtest      # 快测全部源 + 对前 2 名做持续测；不装、不启动、不落盘
```

> 输出**两列**（`快测` / `持续`）与**衰减**百分比。**选源只看「持续」列**：衰减 >60% 说明该源
> 短窗读数骗人（突发额度），衰减接近 100% 基本等于「下不动」。
> 会顺带打印**本次是否走了代理** —— 有代理时 `pypi.org` 常反而最快，不打印这句排序会显得没道理。
>
> 可调开关（环境变量）：`SPEEDTEST_WINDOW`（快测窗口，默认 8 s）、
> `SPEEDTEST_SUSTAIN`（持续窗口，默认 30 s）、`SPEEDTEST_TOP`（做持续测的源数，默认 2，`0` = 全部）。
> 例：`SPEEDTEST_WINDOW=5 SPEEDTEST_SUSTAIN=60 SPEEDTEST_TOP=0 bash provision-vllm.sh --speedtest`。

脚本五段：环境体检 → 校验权重 → 装 vLLM → 版本/端口核对 → 启动。

> ⚠️ **Ubuntu 系统 `python3` 无 pip 时的预期行为**：Debian / Ubuntu **显式禁用 `ensurepip`**
> （报 `ensurepip is disabled in Debian/Ubuntu for the system python`）⇒ 脚本会停下并给出两条处置
> （`apt-get install -y python3-pip`，或建 venv 后 `PY_BIN=~/vllm-venv/bin/python bash provision-vllm.sh`）。
> **这属发行版策略，不是环境损坏** —— 按提示装完重跑即可。

> `--serve-only`：跳过安装，仅按现参数起服务（已装过、只想重启时用）。
> `PIP_INDEX` 留空 = pip 官方默认源；支持简写 `cn / ustc / huawei / aliyun / tuna / pypi`，也可直接给完整 URL。
> `PIP_PROXY=http://<宿主地址>:7890` 让 pip 走代理（宿主地址取法见 §3.7.1）；
> `PIP_RETRIES`（默认 5）／`PIP_TIMEOUT`（默认 60 s）用于弱网下抗中断 —— 轮子很大，默认值容易中途断；
> `PIP_RESUME_RETRIES`（默认 5）＝**断点续传**次数（`--resume-retries`，**需 pip ≥ 23.1**；
> 脚本会先探测 pip 版本，**低版本不下发**这个参数 —— 否则 pip 会以 unknown option 直接退出）。
> ⚠️ 这项别关：`torch`/`cudnn` 这类几百 MB 的轮子下到 90% 断线时**接着下**，而不是从 0 重来 ——
> 在 0.3 MB/s 量级的链路上，这是能省下几十分钟的关键开关。
>
> ⚠️ **换源会让此前下载的进度作废**：pip 的 HTTP 缓存**按完整 URL 索引**（键就是 URL），换源 = 全部重下。
> 所以换源前先算一笔账，别拍脑袋：
>
> | 口径 | 算式 | 本机 2026-10-15 实例 |
> | --- | --- | --- |
> | 不换源的剩余时间 | 剩余量 ÷ 旧源持续速率 | ≈ 3~4 GB ÷ 0.31 MB/s ⇒ **3 小时以上** |
> | 换源的代价 | — | 已攒 **2.5 GB** 作废（但那是 2 小时才攒出来的，本就低效） |
> | 换源的收益 | 全量 6~8 GB ÷ 新源持续速率 | 新源持续 ≥10 MB/s ⇒ **≈10 分钟** |
>
> ⇒ **该换就换，缓存不值得留恋**；但**必须先用 `--speedtest` 的「持续」列**做依据 ——
> 别凭短窗读数（尤其别凭「阿里云 21.92，挺快」那种）就下决定，这正是上一轮踩的坑。
>
> 💡 6~8 GB 的下载建议放后台跑，免得终端一关就断：
> ```bash
> nohup env PY_BIN=~/vllm-venv/bin/python PIP_INDEX=cn bash provision-vllm.sh > ~/vllm-install.log 2>&1 &
> tail -f ~/vllm-install.log
> ```

### 4.1.1 ⚠️ 编译工具链与 PATH 归位（**必做**，2026-10-15 实测踩坑）

vLLM 不是「装完就能跑」的纯 Python 包：**运行期会 fork 子进程去调外部可执行文件**。

| 外部程序 | 谁在调 | 缺了会怎样 |
| --- | --- | --- |
| `ninja` | flashinfer 的 JIT 编译（`ninja` 是 flashinfer 的**硬依赖**，pip 装到 `<venv>/bin/ninja`，**系统 `/usr/bin` 下没有**） | 启动**后期**崩在 flashinfer JIT，且 `flashinfer_jit.log` 为 **0 字节**、无任何编译输出 |
| `g++` / `cc` | torch inductor 的 `cpp_wrapper`、C++ 扩展 | 编译期报找不到编译器 |
| `nvcc` / `ptxas` | flashinfer / cutlass-dsl 的 JIT | 报 `CUDA_HOME` 相关错误 |

**本机实测（2026-10-15）**：`build-essential` 已装（`g++` / `ld` / `cc` 都在），但 **`ninja` 只存在于
`~/vllm-venv/bin/`**，而**未激活 venv** 时它不在 `PATH` 里 —— 于是 vLLM 于 17:38 崩在 flashinfer
采样内核的 JIT 上，日志却**什么都没留下**（现场特征与判据见 **§6.1**）。同时系统里**既无**
`/usr/local/cuda` **也无** `/usr/bin/nvcc`，而 pip 包已把整套 CUDA 工具链铺在
`~/vllm-venv/lib/python3.12/site-packages/nvidia/cu13/`（`bin/include/lib/nvvm` 齐备 ⇒ 就是一个标准 `CUDA_HOME`）。

**两条处置（建议都做）**：

```bash
# ① 系统级补齐（不依赖 venv 是否被激活）
sudo apt-get update && sudo apt-get install -y ninja-build build-essential

# ② 让运行时能看到 venv 与 pip 版 CUDA 工具链
export PATH="$HOME/vllm-venv/bin:$PATH"
export CUDA_HOME="$HOME/vllm-venv/lib/python3.12/site-packages/nvidia/cu13"
```

> ✅ **`provision-vllm.sh` 现已自动完成 ②**：只要 `PY_BIN` 落在 venv 内（认 `pyvenv.cfg`），脚本就把
> 该 venv 的 `bin/` 与 pip 版 CUDA 工具链的 `bin/` **追加进 `PATH`**，并在 `CUDA_HOME` 未设置时兜底
> 指向 `nvidia/cu13`（已设置则**不覆盖**）。⇒ **不必再手工 `source activate`** —— 脚本是用**绝对路径**
> 调解释器的，本来就不会激活 venv，**这正是上一轮踩坑的机制**。
>
> 脚本另加**工具链门禁**：缺 `ninja` / `g++` 时**默认直接停下**并给出上面两条命令（**不再静默降级**）；
> 确实不想装时用 `ALLOW_NO_TOOLCHAIN=1` 显式降级 —— 此时脚本设 `VLLM_USE_FLASHINFER_SAMPLER=0`，
> 退化为 PyTorch 原生采样（可用，略慢）。`DRY_RUN=1` 下**只告警不阻断**（干跑必须能走到打印启动参数）。

### 4.1.2 ⚠️ CUDA 编译器与头文件必须**同 minor**（2026-10-15 实测：第二层真因）

补上 `ninja`（§4.1.1）之后，JIT **这次真的跑起来了**，但**编译失败**——报的是：

```
.../flashinfer/data/cccl/libcudacxx/include/cuda/std/__cccl/cuda_toolkit.h:41:8:
error: #error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
```

该文件的判定条件是**硬性的**，编译任何 `.cu` 都会走到：

```cpp
#  if _CCCL_CUDA_COMPILATION()
#    if !_CCCL_CUDACC_EQUAL((CUDART_VERSION / 1000), (CUDART_VERSION % 1000) / 10)
#      error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
```

⇒ **`nvcc` 的 `major.minor` 必须与 CUDA 头文件的 `major.minor` 完全相等；差一个 minor 也直接 `#error`。**

**本机实测（`~/vllm-venv` 内）版本表**：

| 组件 | 实际安装 | 由此推出的版本 | 提供什么 |
| --- | --- | --- | --- |
| `nvidia-cuda-nvcc` | **13.4.92** | `nvcc` **13.4** | `nvidia/cu13/bin/nvcc`（编译器） |
| `nvidia-cuda-crt` | **13.4.92** | 13.4 | `nvidia/cu13/include/crt/*.h` |
| `nvidia-cuda-runtime` | **13.0.96** | `CUDART_VERSION **13000**` ⇒ **13.0** | `nvidia/cu13/include/cuda_runtime_api.h`（**头文件**） |
| 元包 `cuda-toolkit` | 13.0.3.0 | 它**声明**的自洽组合＝`nvcc/crt==13.0.88.*` ＋ `runtime==13.0.96.*` | — |

**13.4 ≠ 13.0 ⇒ 必然失败。**

> **取证手法（不依赖「能不能执行二进制」）**：受限环境里执行不了 Linux ELF 时，
> **直接从二进制本体取内嵌横幅**，并直读头文件宏：
> ```bash
> grep -a -o -m1 'Cuda compilation tools, release [0-9.]*' "$CUDA_HOME/bin/nvcc"   # → release 13.4
> grep -m1 '#define CUDART_VERSION' "$CUDA_HOME/include/cuda_runtime_api.h"        # → #define CUDART_VERSION  13000
> ```
> 本机两条命令的输出即上表数值（**直读，非由包版本推定**）。
> ⚠️ 另注：**结论本身不依赖版本号的精确取值** —— 已知头文件 13.0 ＋ CCCL 要求两者相等 ＋ 该 `#error` 确被触发
> ⇒ **编译器必然 ≠ 13.0**；「恰好是 13.4」只是额外的定量信息，不是结论的前提。
 成因是**依赖漂移**：`cuda-toolkit` 把 `nvcc` 钉在 `13.0.88.*`，
但 `tilelang` 只要求 `nvidia-cuda-nvcc>=13.0.48`、`humming-kernels` 更未钉版 ⇒ pip 解析时把 `nvcc` 拉到了最新的 **13.4.92**，
而 `nvidia-cuda-runtime`（头文件来源）**没有对应的 13.4 版**，于是编译器与头文件被拆成了两套 minor。

> ⚠️ **症状具有强误导性**：vLLM 只抛
> `RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): **{}**` ——
> **`Failed core proc(s): {}` 是空的**，真因**被打印在它上方**（`Engine core` 子进程自己的 traceback）。
> ⇒ **必须 `tee` 日志**（见 §4.1 第 ⑤ 步）才能看到；否则就会像本工程 17:36 那次一样「现场无日志」，只能靠 §6.1 反推。

**两条处置**：

```bash
# ① 根治（推荐）—— 恢复上游 cuda-toolkit 声明的自洽组合，之后即可不再降级
~/vllm-venv/bin/pip install "nvidia-cuda-nvcc==13.0.88.*" "nvidia-cuda-crt==13.0.88.*"
rm -rf ~/.cache/flashinfer        # ⚠️ 换了编译器必须清旧 JIT 缓存，否则可能复用失败产物
```

```bash
# ② 绕开 flashinfer 采样内核（即时可用，不需要再下轮子）
VLLM_USE_FLASHINFER_SAMPLER=0     # vllm/envs.py 默认 True；置 0 是官方支持的一等路径
```

> **为什么 ② 是可接受的**：vLLM 源码里 `flashinfer_sample()` 的 docstring 明写其与原生路径
> *"statistically equivalent"*，且该内核**只做 top-k/top-p 采样**，**不参与受约束解码**
> （后者在 logits 处理阶段）⇒ **不改变产物口径**，只是略慢。`vllm/v1/sample/ops/topk_topp_sampler.py`
> 的 `flashinfer_sampler_supported()` **第一件事**就是读这个变量，置 0 确定性生效。

> ✅ **`provision-vllm.sh` 现已自动检测**：它读 `$CUDA_HOME/include/cuda_runtime_api.h` 的 `CUDART_VERSION`
> 与 `nvcc --version` 的 `release X.Y`，**不一致时响亮降级**（打印两边版本、后果、上面两条命令，并设
> `VLLM_USE_FLASHINFER_SAMPLER=0`），启动参数区会显示「采样后端」的实际取值。
> **要强制严格**（不一致就直接失败）：`REQUIRE_FLASHINFER_SAMPLER=1`。
>
> ⚠️ **此处刻意与 §4.1.1「缺工具链即 `die`」的策略不同**，理由已写在脚本注释里，避免日后被当成疏漏：
> 缺工具是**必须补**的环境缺陷（`apt` 一条命令）；而版本不一致时，flashinfer 采样只是**可选的加速路径**，
> 拒绝启动的代价远大于收益。**策略差异是决策，不是遗漏。**

### 4.1.3 ⚠️ 漏写 `PY_BIN` 前缀会**静默降级**（2026-10-16 实测；脚本已根治）

**症状**：`bash provision-vllm.sh --serve-only` 在第 0 步给出两条容易被放过的 warning，随后死在 3/5：

```
[WARN] nvcc: 未探测到 —— flashinfer JIT 无法编译（pip 版工具链缺失或 CUDA_HOME 未指向）
[WARN] 未取到 CUDART_VERSION（预期路径 /include/cuda_runtime_api.h）—— 跳过版本一致性检查
[ERROR] 无法导入 vllm —— 安装未成功，或当前 python 不是运行 vllm 的那个解释器。
```

**一眼认出的判据**：`预期路径` 显示成 **`/include/cuda_runtime_api.h`** —— 即 `CUDA_HOME` 为空。
而 `CUDA_HOME` 只在脚本判定「解释器位于 venv 内」（认 `pyvenv.cfg`）时才被兜底设置
⇒ **这一行本身就是「用了系统解释器」的铁证**。
⚠️ 别拿版本号判断：第 0 步打印的 `Python: 3.12.3` 是**系统 python**，而 venv 也是 **3.12.3**
⇒ **光看版本号区分不出来**，要看「预期路径」以及有没有那行 `[OK] venv 归位：…`。

**真因**：`PY_BIN` 旧默认值写死为 `python3`，而 venv 方案要求人工**每次**带
`PY_BIN=~/vllm-venv/bin/python` 前缀。漏写时脚本**不会**报「venv 未找到」，而是拿系统解释器继续走：

| 后果 | 说明 |
| --- | --- |
| `PY_ROOT=/usr` 下没有 `pyvenv.cfg` | 「运行环境归位」**整段跳过** ⇒ `<venv>/bin`（`ninja`）与 pip 版 CUDA 工具链都不进 `PATH`，`CUDA_HOME` 不设 |
| 「CUDA 版本一致性自检」被跳过 | 该段取不到 `CUDART_VERSION` 时**只 `warn`、不 `die`** ⇒ **§4.1.2 那层真因被无声绕过** |
| 3/5 导入 `vllm` 失败 | 系统 `python3` 侧没有 vllm（PEP 668 禁止 `pip install`）⇒ **反而是唯一响亮的一步** |

⇒ 属本项目明令禁止的**静默降级**形态：**最该做的前置检查被绕过，只留两条 warning**。
⚠️ 与 §6.1／§6.2 的教训同源 —— **现场报错离真因很远，且「没报错」不等于「检查过了」**。

**处置（已从默认值根治，不只是提示）**：未显式指定 `PY_BIN` 时**自动探测 `~/vllm-venv`**
（探到即用，并打印 `[OK] 解释器：未显式指定 PY_BIN，自动探测到 venv ⇒ …`）；
探不到才回落 `python3`，且**响亮提示**可能失败的原因。显式传参**永远优先**
（`PY_BIN=/usr/bin/python3 bash $0` 可强制用系统解释器；走**方案 ①** 时必须这样写）。

**当下正确命令**（两种写法等价，新脚本下前缀可省）：

```bash
cd /mnt/e/*/04-*/scripts
bash provision-vllm.sh --serve-only                                  # 自动探测 venv（推荐）
PY_BIN=~/vllm-venv/bin/python bash provision-vllm.sh --serve-only    # 显式写法（兼容旧脚本）
```

> ✅ **本机 venv 健康性核验结果（2026-10-16，Windows 侧读 `\\wsl$` 取证）**：
> `/root/vllm-venv` 落位正常（`bin/` 含 `python`／`pip`／`vllm`／`ninja`，
> `site-packages/` 含 `vllm`／`torch`／`flashinfer`／`xgrammar`／`nvidia` 全套），
> `pyvenv.cfg` 显示 `version = 3.12.3`、`include-system-site-packages = false`。
> ⇒ **该报错与 venv 是否损坏无关**，纯粹是解释器选错。
> ⚠️ 同一轮核验发现 **`nvidia-cuda-nvcc`／`crt` 又回到 13.4.92**（`runtime` 仍 13.0.96）
> ⇒ §4.1.2 的版本漂移**复发**（`pip install --upgrade vllm` 会重解依赖，把 §4.1.2 的钉版结论冲掉）。
> 这不影响起服务（脚本会按 §4.1.2 **响亮降级**为 `VLLM_USE_FLASHINFER_SAMPLER=0`），
> 但**根治需重跑 §4.1.2 的 ① 命令**，且**每次 `--upgrade vllm` 之后都要复查**。

### 4.2 权重零拷贝

权重在 Windows 的 `E:\models\Qwen2.5-7B-Instruct`，WSL2 下经 `/mnt/e/models/…` 访问。**不复制、不重下**。

⚠️ `/mnt/e` 是 **9p/drvfs 跨文件系统挂载**，跨盘读权重**比 Linux 本地盘慢**。若首次加载明显偏慢，可复制到发行版内部盘：

```bash
cp -r /mnt/e/models/Qwen2.5-7B-Instruct ~/models/   # 约 15.2 GB
# 然后 MODEL_PATH=~/models/Qwen2.5-7B-Instruct bash provision-vllm.sh
```

**取舍**：`/mnt/e` 省 15.2 GB 磁盘、免去复制；`~/models` 读取更快。`<待实测>` 加载耗时差异——未测前不做主张。

### 4.3 ⚠️ 受约束解码字段与引擎版本强相关（**最容易静默失效的一处**）

| vLLM 版本 | 参数形态 | 配置值 |
| --- | --- | --- |
| **≥ 0.12.0** | `structured_outputs: {"json": …}` | `APP_VLLM_GUIDED_DECODING_MODE=structured_outputs` |
| **< 0.12.0** | `guided_json: {…}`（旧字段） | `APP_VLLM_GUIDED_DECODING_MODE=guided_json` |
| 跨引擎兜底 | `response_format: {"type":"json_schema",…}` | `APP_VLLM_GUIDED_DECODING_MODE=response_format` |

**风险**：把旧字段发给新版引擎，**不会报错、会被静默忽略** → 退化为**无约束解码**。此时请求照样返回 200、文本照样像 JSON，但**模型并未受约束** —— 交付包可能偶发不合规，且**极难定位**。

**防护（三重）**：
1. `provision-vllm.sh` 装完**自动打印 vLLM 版本**并提示应设哪个配置值；
2. 应用侧未知形态**显式报错**（`GENERATION_FAILED`），绝不「当作没约束」继续；
3. 上机后按 §7 清单**实测验证**约束生效（不只看返回 200）。

### 4.3.1 ⚠️ 受约束解码的**能力边界**（2026-10-15 实测：真实 `CFG-006` schema）

§4.3 讲的是「参数形态发错会**静默**退化」；本节讲的是「**参数发对了，仍有约束管不到的地方**」。
两者都**不以返回 200 为判据**。

**① `uniqueItems` 是 xgrammar 当前不支持的关键字 → 真实 schema 会被**直接拒收**（400）**

`CFG-006` 的 `units[].shot_ids` 用了 `"uniqueItems": true`。把**完整 schema** 原样放进
`response_format.json_schema.schema` 后，引擎在**编译期**（而非生成期）立即返回，实测耗时约 **0.01 s**：

```json
{"error":{"message":"Grammar error: Unimplemented keys: [\"uniqueItems\"]","code":400}}
```

- **好消息**：这是**响亮失败**（400 ＋ 明确指名关键字），**不是**静默退化 ⇒ 不会被误当成功。
- **实测方法**：逐轮「剥离 → 重发 → 读报错」直到可编译。**结果＝只需剥离 `uniqueItems` 这一处**；
  其余关键字（`pattern`×16、`enum`×19、`minItems`×7、`maxItems`×2、`minLength`/`maxLength`、
  `minimum`、`multipleOf`、`const`、`oneOf`、`$ref`×9、`format`）**全部可通过**。
- **处置**：引擎侧传「剥离 `uniqueItems` 的 schema」，**应用层仍用完整 schema 校验**把该约束补回
  （`validate_pack.py` 走 `jsonschema`，**支持** `uniqueItems`）⇒ 约束不丢失，只是**换了执行位置**。

**② 三类约束引擎侧**根本表达不了** —— 实测两次生成，均**未**通过 `validate_pack.py` 全部门禁**

同一份真实 schema、同一份梗概，生成两次：

| 指标 | 第 1 次（仅 schema 约束） | 第 2 次（提示词另行补足质量门要求） |
| --- | --- | --- |
| `schema` 层（`jsonschema`） | ✅ **0 错** | ✅ **0 错** |
| 产出镜数 / 单元数 | 2 镜 1 单元（正踩 `minItems` 下限） | **4 镜 2 单元** ✅ |
| `camera.optics` 覆盖 | 0%（**未填**） | **100%** ✅ |
| `lighting` 覆盖 | 0%（**未填**） | **100%** ✅ |
| `duration_ms` 对 `CFG-001` 下限 4000 ms | 1000 ms ❌ | 4000/6000/8000 ms ✅ |
| `camera.height` 覆盖 | 100% | **0%** ❌（提示词**明确要求过**，仍全漏填） |
| `meta.total_duration_ms` | 正确 | **12000 ≠ 实际 24000** ❌ |
| `validate_pack.py` 门禁结论 | **4 项 BLOCK** | **3 项 BLOCK** |

**⇒ 结论：`schema` 层「直出即合规」成立；「直出即通过全部门禁」不成立。** 三类约束是**结构性**管不到的：

| 类别 | 本实测例子 | 为何 schema 管不到 |
| --- | --- | --- |
| **可选项的「覆盖率」** | `camera.height`／`optics`／`lighting` 在 schema 里**可选**，但 §5 质量门要求覆盖 ≥ 30~60% | JSON Schema 只约束**单个实例内部**，无法表达「N 个镜头里至少 M 个填了某字段」这类**跨实例统计** |
| **跨字段算术一致** | `meta.total_duration_ms` 必须 = Σ `shots[].duration_ms` | JSON Schema **标准不支持字段间算术**（`draft 2020-12` 无 `$data` 引用） |
| **取值来自另一份文件** | `duration_ms` 下界 4000 ms 在 `config/CFG-001_model_adapters.yaml`，**不在** schema 里 | schema **刻意不引用模型数值**（规范 §0.4 编写纪律 4）⇒ 引擎侧**看不到**该下限 |

**③ 一条实测到的模型行为**：**对 `optional` 字段与「下限值」一律走「最小满足」** ——
只给 `minItems` 要求的 2 镜、`duration_ms` 取下限 1000 ms、省掉全部可选字段。
⇒ **「业务上必填、schema 上可选」的字段是危险区**；且**提示词里明确要求也会被漏填**
（`camera.height` 两轮对照即为证）。

**⇒ 由此确立的链路形态（不得简化）**：

```text
prompt 承载质量门要求      （提高一次通过率，但**不可依赖**）
        ↓
引擎受约束解码            （保证**结构** 100% 合法 —— 这才是它的价值所在）
        ↓
validate_pack.py 门禁     （**必须保留**：捕上面三类覆盖率/算术/外部文件约束）
        ↓
不通过 ⇒ 携带门禁诊断信息重试（而非直接交付） ／ 通过 ⇒ 交付
```

> ⚠️ **本节同时是对 §7.3 第 2 项判据的实测订正**：该项原文写「确认产物**直出即合规**（无需重试）」，
> 实测表明**该判据只在结构层成立**。**门禁＋重试环节不可省** —— §7.3 的验证方法据此更新。

### 4.4 应用侧接线（Windows 侧 `.env`）

```
APP_INFERENCE_BACKEND=vllm
APP_VLLM_BASE_URL=http://127.0.0.1:8001/v1
APP_VLLM_MODEL=Qwen2.5-7B-Instruct
APP_VLLM_GUIDED_DECODING_MODE=structured_outputs   # 按 §4.3 表选
APP_VLLM_MAX_CONCURRENCY=10
```

> ✅ **`127.0.0.1:8001` 可直接互通（已实证，不再只是「通常」）**：2026-10-15 实测，Windows 侧
> `Get-NetTCPConnection -LocalPort 8001` 显示 `127.0.0.1:8001 Listen`，占用进程为
> **`C:\Program Files\WSL\wslrelay.exe`** ⇒ **WSL2 `localhostForwarding` 生效**（本机
> `%USERPROFILE%\.wslconfig` **不存在** ⇒ 走默认 `true`）。Windows 侧 `curl.exe http://127.0.0.1:8001/...`
> 实测 `http=200`（0.007 s）⇒ **无需取 WSL2 IP、无需改监听地址或防火墙**。
> 若将来该项失效，再回退到「取 `wsl hostname -I` 首段」的旧办法（并相应调整监听地址与防火墙）。
> ⚠️ **在 Windows PowerShell 里必须写 `curl.exe`**：裸写 `curl` 命中 PowerShell 的 **alias**
> （`Get-Command curl` 的 `CommandType` 为 `Alias`），会走 `Invoke-WebRequest`，`-s`/`-H`/`-d`/`--max-time`
> **全部不认**（实测报错：`找不到接受实际参数"--max-time"的位置形式参数`）；且 `Invoke-WebRequest`
> **默认吃系统代理** ⇒ 连本地地址都要显式 `--noproxy '*'`。

---

## 5 启动参数基线

| 参数 | 基线值 | 依据 | 状态 |
| --- | --- | --- | --- |
| `--model` | `/mnt/e/models/Qwen2.5-7B-Instruct` | 零拷贝复用 | 实测路径已确认 |
| `--served-model-name` | `Qwen2.5-7B-Instruct` | 与 `APP_VLLM_MODEL` 对齐 | — |
| `--dtype` | `bfloat16` | `T-010`「不走量化」 | 权重为 BF16 全量 ✅ |
| `--max-model-len` | `32768`（**2026-10-15 由 16384 上修**） | 须 ≥「最长分段提示词 + 8192 输出」 | ✅ **已实测（`DEV-20261015-014`）**：最长分段＝`storyboard` 段 prompt ＝ **14473 tokens**（30252 字符）⇒ 需 ≥ **22665**；**原值 16384 不足**（只剩 1911 输出预算，该段被引擎入口 400 拒收，`ISSUE-032`）。取 32768（Qwen2.5-7B-Instruct **原生支持**）；⚠️ **提窗不额外占显存**（KV 池容量由 `gpu_memory_utilization` 决定，与 `max_model_len` 无关），代价＝满长度并发 5.37x → 约 **2.68x** ⭐ **2026-10-16 补充实测（`DEV-20261016-002`）**：32768 **足以**跑通 `storyboard` 段（真跑 129.7 s／prompt 15133 ＋ completion 5964 tokens ⇒ `ISSUE-032` **解除**）；**但不足**以跑 `shot_prompt` 段 —— 该段**输入自身即 50,358 tokens**（＋8192 ⇒ 58,550），且 **`segment=auto` 拆段不改变输入**（`all`／`package_head`／`unit:U01` ＝ 50,358／50,360／50,366）⇒ **32768 已是本模型原生窗口上限，再往上须 YaRN（改变模型行为）或减输入**（`ISSUE-037`） |
| `--gpu-memory-utilization` | `0.90` | 常规基线 | ✅ **已生效**（日志：等价于无 CUDA graph profiling 的 `0.8959`，见 §5.1） |
| `--max-num-seqs` | `16` | 并发目标 10（`SYS-015`）留 1.6× 余量 | ✅ 已生效；⚠️ **但 KV 容量只够 5.37 路全长度 16384** ⇒ **见 §5.1，10 并发需另定上下文预算** |
| `--enable-prefix-caching` | 开 | Qwen 前缀复用，schema 段落可命中缓存 | ✅ **已生效**（日志 `enable_prefix_caching=True`）；**收益**`<待实测>` |
| 采样后端（脚本注入） | `PyTorch 原生` | `VLLM_USE_FLASHINFER_SAMPLER=0`，理由见 §4.1.2 | ✅ **已生效**并已打印进启动参数区 |
| `--enforce-eager` | 关 | OOM 排查时临时开（见 §6） | — |
| `--host` / `--port` | `0.0.0.0` / `8001` | 回环端口 | — |

> ⚠️ **`max-model-len` 由「推导值」转为「实测值」（2026-10-15）**：原推导依据是 `TPL-009` 声明 `sampling.max_tokens=8192`、加模板正文与 `pack_meta` 后留余量 —— 该推导**方向正确但数值不够**。**实测口径**＝用引擎自身 `POST /tokenize` 对**完整渲染 prompt** 精确计数（**非字符估算**）：最长者＝`storyboard` 段 **14473 tokens** ⇒ 窗口须 ≥ 14473 + 8192 = **22665** `→` 取 **32768**。⚠️ 两条易误判的推论：**(a) 瓶颈在模板自身体量，不在上游产物** —— 模板正文 24438 字符 ≫ 上游 `script_json` 5814 字符，故**上游再长也须按同一算式复核**，而「最长分段」**不是**名字最像交付物的 `shot_prompt`；**(b) 提窗不额外占显存**（见 §5 表注），只降满长度并发。
>
> ⭐⭐ **2026-10-16 补一条更重要的判据（`DEV-20261016-002`，实测）：窗口需求必须按「输入 ＋ 输出」算，而「分段」只能压输出侧。** 分镜段提窗后一次通过（`ISSUE-032` 解除），第 4 段 `shot_prompt` 却**仍在引擎入口被拒**：该段 prompt ＝ **50,358 tokens**（＋模板 `max_tokens` 8192 ⇒ **58,550**）。**归因（实测，非推断）**：`TPL-009` 的正文（固定部分仅 **24,041 字符**）把 `{storyboard_json}` 插入 **5 次**、`{script_json}` **3 次**、`{pack_meta}` **4 次** ⇒ 上游被放大 **2.44 倍**。⚠️ **由此得到一条与本节口径互补的硬结论**：`segment` 拆段**只改变模型「该输出什么」**（模板 `output` 节按 `{segment}` 分支），**输入侧的 `*_json` 无条件全量注入** —— 实测三种粒度渲染后输入 ＝ **50,358／50,360／50,366 tokens（差 ≤8）**。⇒ **「拆段」与「提窗」是两条正交的路**：拆段压输出、提窗扩总窗口；**当输入侧自身超窗时，两者都救不了**，只能 ① 减输入（模板去重 ／ 发送前 minify）或 ② YaRN 外推（改变模型行为）。四案量化见 `ISSUE-037`。
>
> ⭐⭐⭐ **2026-10-16 再补一条「**怎么把输入侧压下来**」的反解口径（`DEV-20261016-003`，实测）**：上一条判据只说明了「**拆段救不了输入侧**」，但**输入侧本身是可压的** —— 该段模板 `TPL-009` 把上游**重复搬运**（`{storyboard_json}` 正文出现 **5 次**、`{script_json}` **3 次**、`{pack_meta}` **4 次** ⇒ 上游放大 **2.44 倍**），而渲染器对 `sections` 内**每一处** `{name}` 一律**全量替换** —— 于是「**指称性引用**」（如「原样承继 `{storyboard_json}`」）被当成了**注入点**。**两条腿合起来把 50,358 压到 17,897 tokens（-64.5%）**：① **模板去重**（正文只留每变量**恰好 1 处**全文注入 ＋ 显式声明「三份全文各只出现一次」）→ **20,324**；② **服务层对上游 JSON 做无损紧凑化**（`json.dumps(…, separators=(",", ":"))`，**只去空白**）→ **17,897**。**⇒ 启动参数基线的正确用法是「先算输入预算，再定 `--max-model-len`」**：`max-model-len ≥ 最长分段（输入 ＋ 输出）`；⚠️ 只按「模板正文 + `max_tokens`」推导会**低估**（V1.11 犯过），只按「单段输入」评估同样不够（V1.13 之后又发现**输入自身**已超窗）。**权威数值以文档的现行版为准**。

### 5.1 本机实测生效值（2026-10-15 18:10，**首次成功起服务**）

> 来源：`~/vllm-serve.log`（按本手册建议加了 `tee`，150 行 / 19.6 KB）。

| 指标 | 实测值 | 出处 |
| --- | --- | --- |
| 引擎版本 | vLLM **0.31.0**（`torch 2.13.0+cu130`，`cuda: True`） | `core.py:129` ／ 脚本 `3/5` |
| 架构解析 | `Qwen2ForCausalLM` | `model.py:699` |
| 生效启动参数 | `dtype=bfloat16, max_seq_len=16384, gpu_memory_utilization=0.9, max_num_seqs=16, enable_prefix_caching=True, enable_chunked_prefill=True, tensor_parallel_size=1` | `core.py:129` |
| 服务监听 | `http://0.0.0.0:8001`；`Application startup complete.` @ **18:10:42** | `entry.py:136` |
| **KV Cache 可用显存** | **4.7 GiB** | `gpu_worker.py:692` |
| **GPU KV Cache 容量** | **88,032 tokens** | `kv_cache_utils.py:2464` |
| **最大并发（按 16384 token/请求）** | **5.37x** | 同上 |
| KV Cache 布局 | `LBNHC` | `utils.py:343` |
| `torch.compile` 耗时 | **10.11 s**（单图 4.54 s，`compile range (1, 2048)`） | `monitor.py:53` |
| CUDA Graph 捕获尺寸 | `[1,2,4,8,16,24,32]`（`max_cudagraph_capture_size=32`） | `core.py:129` |
| 采样后端 | **PyTorch 原生**（`VLLM_USE_FLASHINFER_SAMPLER=0`） | 脚本启动参数区 |

⚠️⚠️ **一条与 `SYS-015` 直接相关的推论**：**「单卡 10 并发」在 16384 全长度下不成立** —— KV Cache 只放得下 **5.37 路** 16384。要满足 10 并发，须 **平均上下文 ≤ 88032 ÷ 10 ≈ 8,803 token**（恰在「16384 − 8192 输出 = 8192 输入」量级，与 `TPL-009` 的 `max_tokens=8192` 相容）。
**⇒ `T-013` 压测必须同时记录「并发数 × 实际上下文长度」两个维度**，只报「10 并发」会掩盖这一硬约束。

⚠️ **两条须记账的运行时提示**（均非故障，但影响口径）：

1. `Default vLLM sampling parameters have been overridden by the model's generation_config.json: {'repetition_penalty': 1.05, 'temperature': 0.7, 'top_k': 20, 'top_p': 0.8}` —— **模型自带 `generation_config.json` 会覆盖 vLLM 默认采样参数**。备案口径若声明了采样参数，须以**这里实际生效的四个值**为准；或显式加 `--generation-config vllm` 关掉该覆盖。
2. `Pinned memory is not available on this platform; falling back to device memory for UVA buffers.` —— **WSL2 不支持 pinned memory**，回退设备内存，属 **WSL 环境固有限制**（不是配置错误），对吞吐有轻微影响，别当故障查。

---

## 6 OOM 排查决策树

按顺序尝试，**每步只改一个参数**并记录结果：

| 症状 | 处置 | 说明 |
| --- | --- | --- |
| 启动即 OOM，`--gpu-memory-utilization 0.90` | 降到 `0.85` → `0.80` | KV Cache 预留不足；权重约占 15.2 GB / 23.0 GB |
| 长提示词 OOM | 优先降 `--max-num-seqs`／开 `--kv-cache-dtype fp8`；**勿**为塞进长 prompt 而降窗口 | 上下文是 KV Cache 主要占用方；⚠️ **方向与 `ISSUE-032` 相反** —— 本机实测最长 prompt 需 **22665** 窗口，**降到 16384 会让主链第 3 段（`storyboard`）在引擎入口直接被 400 拒收** ⚠️ **2026-10-16 补一条反向边界**：「提窗」也有尽头 —— 本机提到 **32768** 后 `storyboard` 段已通，但 `shot_prompt` 段**输入自身 50,358 tokens** ⇒ 即便再提窗也只是把问题推到原生上限之外。**此时正确的动作不是继续提窗，而是减输入**（模板去重／minify），详见 §5 注记与 `ISSUE-037`。|
| 压测中 OOM（短提示词也崩） | 开 `--enforce-eager` | 关 CUDA Graph，省显存、略降速 |
| 仍 OOM | 检查是否有其他进程占显存（`nvidia-smi`） | 浏览器/其他推理服务可能抢占 |
| `--max-num-seqs` 过大导致排队/OOM | 降到 `8`，观察吞吐 | 并发上限与显存强相关 |

⚠️ **不要**用量化（`--quantization awq/gptq`）绕过 OOM —— `T-010` 已决议**不走量化路线**，产物质量口径不得在此被悄悄改掉。

### 6.1 ⚠️ 不一定是 OOM：先按「崩溃点」定位（2026-10-15 实测）

上一轮 vLLM 起不来时现场**没有任何日志文件**（脚本最后一步是 `exec`，输出只在终端）。但**文件系统的
写入痕迹足以定位崩溃点**，不必重跑：

| 观察点 | 含义 |
| --- | --- |
| `~/.config/vllm/usage_stats.json` 存在且含 `"context": "ENGINE_CONTEXT"` | **模型配置已读、引擎已初始化** ⇒ 崩在**启动后期**，别再查驱动与权重 |
| `~/.cache/vllm/torch_compile_cache/` 有内容 | `torch.compile` 已跑过 ⇒ 与 `triton` 无关 |
| `~/.cache/flashinfer/<ver>/<arch>/flashinfer_jit.log` 存在但 **0 字节** | flashinfer **JIT 在产生任何输出前就失败** ⇒ 优先怀疑**编译工具链 / `PATH`**（§4.1.1），**不是** CUDA 或显存 |
| 同级 `cached_ops/<op>/` 是**空目录**、`cached_ops/tmp/<op>.lock` **残留** | 该内核的构建**没跑完**（锁未释放） |
| `dmesg` / `kern.log` **无** `Out of memory: Killed process` | **不是被 OOM Killer 杀掉** ⇒ 别再往显存方向找 |
| 崩溃时刻＝上述文件里**最后一个**被写入的时间 | 该文件对应的环节就是崩溃点（本例：`cached_ops/sampling`） |

> 从 **Windows 侧**也能取到这些证据（无需进 WSL、无需提权）：
> `\\wsl$\Ubuntu\root\.cache\flashinfer\...`、`\\wsl$\Ubuntu\proc\<pid>\{cmdline,environ}`。
> ⚠️ 但 `ls -d <路径>` / `stat` 这类**针对单个路径**的操作，在 `\\wsl$` 上遇到**符号链接**可能报
> `Input/output error` —— 极易被误读成「文件不存在」。**本轮据此差点把已装好的 `g++` 判成缺失。**
> ⇒ **核查「某文件在不在」请用「列目录 ＋ 过滤」，不要用 `ls -d <路径>`。**

### 6.2 ⚠️ 读懂 `Engine core initialization failed`：`Failed core proc(s): {}` 为空＝真因在**上方**

这是 vLLM v1 最容易把人带偏的一条报错。原文长这样：

```
RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
```

**先看那个花括号** —— 它是 `wait_for_engine_startup()` 抛错时带出来的「已结束的核心进程 → 退出码」映射。
**为 `{}` 就说明这一层什么信息都没有**：真正的堆栈是 **`EngineCore` 子进程自己打印的 traceback，位置在它上面**
（源码里，该函数 poll 到「非握手 socket」的事件即抛错，而 `finished_procs()` 恰好为空时就渲染成 `{}`）。
⇒ 只有 `tee` 到文件才拿得到（脚本最后一步是 `exec`，输出**不会**自动落盘）。
**拿到全量日志是唯一出路，别在空的 `{}` 上猜。**

拿到日志后按这张表往下走：

| 日志里出现的行 | 含义 | 去哪儿 |
| --- | --- | --- |
| `[OK] 工具链: ninja=… g++=…`，且**没有** `ninja: Entering directory` | JIT **根本没跑起来**（`PATH` 里没有工具） | §4.1.1 |
| `ninja: Entering directory …` ＋ `FAILED: [code=1]` | 工具**找得到、也真跑了**，**是编译本身失败** ⇒ 看紧随其后的 `nvcc` 段的具体 `error:` | 见下两行 |
| `error: #error "CUDA compiler and CUDA toolkit headers are incompatible"`（`cuda_toolkit.h:41`） | `nvcc` 与 CUDA 头文件 **minor 不一致** | **§4.1.2** |
| `error: cannot find …` / `No such file or directory`（头文件类） | `CUDA_HOME` / `-isystem` 指向不对 | §4.1.1 的归位段 |
| `Out of memory: Killed process`（`kern.log` / `dmesg`） | 真的是 OOM | 本文 §6 决策树 |

> ⚠️ **vLLM 本应有自动降级，但存在盲区**：`flashinfer_sampler_supported()` 会先做一次「能否 JIT」的预判
> （`_flashinfer_jit_unsupported_reason()`），失败就自动退回原生采样。但该预判**只覆盖 SM 架构 / SM 数不足一类问题**，
> **覆盖不到**「CCCL 版本不兼容」这种**要到真正编译那一刻才炸**的情形 ⇒ 它判定「可用」，随后在 warmup 阶段崩掉。
> **⇒ 不能依赖 vLLM 自己兜底，版本一致性必须由部署侧前置检查**（§4.1.2，脚本已加）。

---

## 7 上机核对清单（**`<待实测>` 全部回填后方可关闭 `T-012`**）

### 7.1 环境

> ✅ **进度（2026-10-15 17:45）**：Windows 侧全部就绪（组件 `Enabled` ＋ 已重启 ＋ 虚拟化就绪 ＋ 发行版落 E 盘）；
> Linux 侧 **`0/5`~`1/5` 实跑通过**（**GPU 直通成立**）→ **pip 已补齐**（建 `~/vllm-venv`，pip **26.2.1**）
> → **vLLM 0.31.0 装成**（200 个包，缓存 6.5 GB）。
> 当时卡点：**启动后期崩在 flashinfer 的 JIT 编译**（真因＝`ninja` 不在 `PATH`；**非** CUDA / 非显存）
> ⇒ 判据见 **§6.1**、处置见 **§4.1.1**（脚本已自动归位 `PATH`）。
>
> ✅ **进度（2026-10-15 17:56，第二次实跑，**已拿到全量日志**）**：`ninja` 归位**已被证实生效**
> （日志 `0/5` 段打印 `[OK] 工具链: ninja=/root/vllm-venv/bin/ninja  g++=/usr/bin/g++`），
> JIT **进入编译**——但 **`nvcc` 编译失败**：`cuda_toolkit.h:41` 报
> `CUDA compiler and CUDA toolkit headers are incompatible`。
> 真因＝**`nvcc` 13.4 与头文件 `CUDART_VERSION 13000`(13.0) 不一致**（CCCL 要求同 minor）⇒ 见 **§4.1.2**、**§6.2**。
> 处置：**脚本已自动检测并降级**（`VLLM_USE_FLASHINFER_SAMPLER=0`，不改变产物口径）；根治命令见 §4.1.2 ①。
>
> ✅ **进度（2026-10-15 18:10，第三次实跑 —— 服务起成）**：降级路径**一次通过**，
> `Application startup complete.` @ **18:10:42**，监听 `http://0.0.0.0:8001`，`--serve-only` 走完 `0/5`~`5/5`。
> 实测生效值见 **§5.1**（KV Cache **4.7 GiB / 88,032 tokens**、`torch.compile` **10.11 s**、采样后端＝PyTorch 原生）。
> ✅ **进度（2026-10-15 18:24–18:26，服务在跑期间做端到端校验）**：**服务连通性已验证**（§7.2 第 1 项，`http=200`）；
> **受约束解码经「严格形式」证实确实生效**（§7.3 第 1 项 ＋ 对照组）；**用真实 `CFG-006` schema 生成 2 次**，
> 由此得到**受约束解码能力边界**的实测结论（**§4.3.1**）：**结构层直出即合规**（`jsonschema` 校验 2/2 全 0 错）、
> **门禁层 0/2 通过**（`validate_pack.py` 分别 4 项 / 3 项 BLOCK）。
> ⚠️ **仍未验证**：受约束解码的**门禁层直出率**（§7.3 第 2 项判据已订正）／连发多段（§7.3 第 3 项）／
> 10 并发 TTFT·TPOT（§7.3 第 4 项，属 `T-013`）／应用侧 `/ready`（§7.2）⇒ `T-012` **不关闭**。

- [x] **两个可选组件已启用**（`Microsoft-Windows-Subsystem-Linux` ＋ `VirtualMachinePlatform`）—— 2026-10-15 实测
- [x] **已重启 Windows** —— 2026-10-15 13:09:50 实测；待重启标记已清除
- [x] **虚拟化已就绪** —— `HypervisorPresent=True`（重启后实测，见 §3.5.1：另两个字段被内核接管而报 False 属正常）
- [x] **走 §3.3 手动路径导入发行版** —— 2026-10-15 14:11 完成（原「重跑 `install-wsl2.ps1`」一项**由本路径替代**）
- [x] 发行版实例落 **E 盘**：`E:\wsl\Ubuntu\ext4.vhdx`（**1.3 GB**）已生成 —— 实测
- [x] **`VERSION 2` 已确认** —— 实测内核 `6.18.54.1-microsoft-standard-WSL2` ＋ `WSL_DISTRO_NAME=Ubuntu`（2026-10-15 14:26 脚本 `0/5` 输出）
- [ ] ~~`C:\Users\<user>\AppData\Local\Packages\` 下无残留发行版目录~~ —— **本条不适用**：未走路径 A 的 `install → export → unregister` 链路
- [x] **WSL 内 `nvidia-smi` 能列出 RTX 4090** —— 实测 `NVIDIA GeForce RTX 4090, 8.9, 23028 MiB, 610.88` ⇒ **GPU 直通成立**
- [x] **解释器 pip 就位** —— `~/vllm-venv` ＋ pip **26.2.1**（2026-10-15 16:53 由 `pip` 缓存留下的 wheel 时间戳反算）；见 §4.1 ③
- [x] **编译工具链就位** —— `build-essential` 已装（`g++` / `ld` / `cc` 齐，16:52 由 `dpkg.log` 确认）；
> ⚠️ **但 `ninja` 只在 `~/vllm-venv/bin/`，未激活 venv 时不在 `PATH`** ⇒ 即上一轮卡点，见 **§4.1.1**（已修）
- [ ] **CUDA 编译器与头文件版本一致** —— **当前不满足**：`nvcc` **13.4**（`nvidia-cuda-nvcc` 13.4.92）／
> 头文件 `CUDART_VERSION 13000` ⇒ **13.0**（`nvidia-cuda-runtime` 13.0.96）。CCCL 要求**同 minor** ⇒
> flashinfer 采样内核 JIT 必然失败。**处置见 §4.1.2**（② 已由脚本自动降级；① 根治待执行）
- [x] `vllm.__version__` 已确认 —— **0.31.0**（`vllm-0.31.0.dist-info`）⇒ 满足 `≥ 0.12.0`
> ⇒ Windows 侧 `APP_VLLM_GUIDED_DECODING_MODE` **应设 `structured_outputs`**（§4.3 表）；⚠️ 引擎**尚未成功起服务**，该匹配**仍待端到端复核**
> 
> ✅ **进度（2026-10-16 09:10，第四次实跑 —— 以 `MAX_MODEL_LEN=32768` 重启）**：`/v1/models` 实测 **`max_model_len: 32768`**、KV Cache **88,032 tokens**、`Maximum concurrency for 32,768 tokens per request: 2.69x`（与「提窗不额外占显存、仅降满长度并发」的既有结论一致）；降级路径打印 `VLLM_USE_FLASHINFER_SAMPLER=0` ＋「采样后端：PyTorch 原生」。⭐ **顺带在真实环境验证了 §4.1.3 的修复**：日志 `[OK] 解释器：未显式指定 PY_BIN，自动探测到 venv ⇒ /root/vllm-venv/bin/python`＋ `[OK] venv 归位` ＋ `[OK] CUDA 工具链归位` ⇒ **漏写前缀的「静默降级」不再复现**。

### 7.2 服务

> ❌ **实测记录（2026-10-15 17:51–17:53）**：`--serve-only` 首次**真起服务失败**，崩在 flashinfer 采样内核 JIT
> （真因见 **§4.1.2**、读法见 **§6.2**）。这次**有全量日志**（`~/vllm-serve.log`，64 KB）——
> 恰好反证了上一轮「无日志只能靠文件痕迹反推」的代价：**`tee` 不是可选项**。
>
> ✅ **实测记录（2026-10-15 18:09–18:10）**：**服务起成**。脚本自动检测到 CUDA 版本不一致并**响亮降级**
> （`[WARN] CUDA 编译器与头文件版本不一致：nvcc 13.4 ／ CUDART 13.0` → 置 `VLLM_USE_FLASHINFER_SAMPLER=0`），
> 随后 `5/5` 启动成功。⚠️ **脚本末步是 `exec`，不加 `tee` 输出仍不落盘** —— 本次日志（19.6 KB / 150 行）**全靠用户手工 `tee`**。

- [x] **`/v1/models` 返回含 `Qwen2.5-7B-Instruct`** —— 2026-10-15 18:24 **由作业会话在 Windows 侧**实测：
> `curl.exe --noproxy '*' http://127.0.0.1:8001/v1/models` ⇒ **`http=200`，`time=0.0068 s`**，正文
> `{"object":"list","data":[{"id":"Qwen2.5-7B-Instruct",…,"max_model_len":16384,"root":"/mnt/e/models/Qwen2.5-7B-Instruct"}]}`
> ⇒ 模型名、`max_model_len`、权重路径三项均与 §5.1 一致
- [x] **Windows → WSL 回环连通性已实证** —— §4.4 那句「**通常**可直接互通」现已**不再是「通常」**：
> Windows 侧 `Get-NetTCPConnection -LocalPort 8001` 显示 `127.0.0.1:8001  Listen`，占用进程
> **`C:\Program Files\WSL\wslrelay.exe`** ⇒ **WSL2 `localhostForwarding` 生效**
> （`%USERPROFILE%\.wslconfig` **不存在** ⇒ 走默认值 `true`）。
> ⇒ **Windows 侧可直接用 `127.0.0.1:8001`，无需取 WSL2 IP、也无需动监听地址或防火墙。**
- [x] Windows 侧应用 `APP_INFERENCE_BACKEND=vllm` 时 `/ready` 为就绪 —— ✅ **已实测（2026-10-15 收尾真跑，`DEV-20261015-014`）**：`http=200`、`inference_backend=vllm`、`checks.prompts=ok (16 templates)`；启动日志另证安全闸词库灯亮（`lexicon_categories 31 ／ lexicon_words 12578 ／ lexicon_circuit_open false`）
- [x] **实测 KV Cache 与显存** —— KV Cache **4.7 GiB / 88,032 tokens**（`gpu_worker.py:692`、`kv_cache_utils.py:2464`）→ **已回填 §5.1**
- [x] 实测 `--max-model-len` 是否够用最长分段提示词 → 回填 §5 —— ✅ **已实测（2026-10-15）**：最长＝`storyboard` 段 **14473 tokens**，需 ≥ **22665**；**原 16384 不足**（`ISSUE-032`）⇒ 默认值已上修 **32768**；⭐ **2026-10-16 复测并补边界**：32768 **对 `storyboard` 段成立**（该段真跑一次通过，`ISSUE-032` **解除**），**对 `shot_prompt` 段不成立** —— 该段**输入自身 50,358 tokens**（根因＝`TPL-009` 重复插入上游 5 次／3 次；且**拆段不减输入**）⇒ 另立 **`ISSUE-037`**

### 7.3 受约束解码（**最关键**）

- [x] **故意违反 schema 的请求 ⇒ 引擎拒绝（已按**严格形式**验证）** —— 2026-10-15 18:23 实测：
> 提示词**明确索要** schema 之外的 `forbidden_field`（原文：「必须同时包含 only_field 和 forbidden_field，
> 一个都不能少」），而 schema 只允许 `only_field` 且 `additionalProperties: false`；
> 引擎产出 **`{"only_field": "hello"}`** —— **`forbidden_field` 未出现** ⇒ **约束在解码层被强制**，
> 模型**无法**输出 schema 外的字段。
> **对照组**（同一句提示词、**不加** `response_format`）：模型输出 `name/age/gender/address/…` 一大串字段
> 且带 Markdown 围栏 ⇒ **反证上一条不是「模型自己碰巧这么答」**。
- [x] **用真实 `CFG-006` schema 生成** —— 2026-10-15 18:24–18:26 实测 **2 次**，结论分两层：
> ✅ **结构层成立**：**「直出即合规」在 schema 层为真** —— 两次产物的 `jsonschema` 校验均 **0 错**
> （含 `enum`／`pattern`／`minItems`／`required`／`additionalProperties` 全部满足）。
> ❌ **门禁层不成立**：`validate_pack.py` 两次分别为 **4 项 / 3 项 BLOCK**，失败项**全部落在
> schema 结构性管不到的三类**（可选项覆盖率／跨字段算术／取值来自外部文件），详见 **§4.3.1 ②**。
> ⇒ **本项判据据此订正为「结构层直出即合规；门禁层必须保留 ＋ 重试」**，原文「无需重试」不可再用。
- [ ] 连发 ≥3 次不同 `segment`，确认每次返回均通过 `validate_pack.py` —— **仍未做**（**2026-10-16 补充：`segment=auto` 的「多段分支」已被真实触发** —— 上游 15 镜／9 单元 > 阈值 6 ⇒ 计划 **10 段**（`package_head` ＋ `unit:U01…U09`）；**但第 1 段即被引擎入口 400 拒收**，故**循环与合并仍未走通**。⚠️ 同时实测出一条**与本节同源的判据**：**拆段不缩减输入**（三种粒度 50,358／50,360／50,366 tokens）⇒ 拆段**不能**用来解决「输入超窗」，见 §5 注记与 `ISSUE-037`）：
> 前提是「存在一条能让产物通过全部门禁的 prompt」，而按 **§4.3.1 ②** 的实测，**该前提本身尚未成立**
> ⇒ 本项须与「门禁 ＋ 携带诊断信息重试」的链路**一起设计**
- [ ] 实测单卡 **10 并发**下的 TTFT / TPOT / 成功率 → 回填并据此校准 `SYS-015`（`T-013`）
> ⚠️ 压测**必须同时记录「并发数 × 实际上下文长度」** —— KV 只够 **5.37 路 16384**（见 §5.1），
> 只报「10 并发」会掩盖该约束

> ⚠️ **第 7.3 节不得以「返回 200」代替**。必须**验证约束真的生效**（§4.3 已说明静默失效路径）。

### 7.4 待回填汇总（`<待实测>` 台账）

| 项 | 位置 | 回填人 | 状态 |
| --- | --- | --- | --- |
| 显存占用 / KV Cache 块数 | §5.1、§7.2 | 作业会话（自 `~/vllm-serve.log` 取证） | ✅ **KV 4.7 GiB / 88,032 tokens / 5.37x@16384** |
| 模型 `generation_config.json` 覆盖后的**实际生效采样参数** | §5.1 | 作业会话 | ✅ `repetition_penalty 1.05 / temperature 0.7 / top_k 20 / top_p 0.8` |
| `max-model-len` 实际需求 | §5 | 作业会话（引擎自身 `POST /tokenize` 精确计数） | ✅ **14473 tokens（`storyboard` 段）⇒ 需 ≥ 22665**；默认值已提至 **32768**（`ISSUE-032`）；⭐ **2026-10-16 复测**：32768 **对 `storyboard` 段成立**（`ISSUE-032` 解除）；**对 `shot_prompt` 段不成立**（输入自身 **50,358 tokens**；拆段不减输入）⇒ `ISSUE-037`，**须项目方裁决处置方案**|
| 10 并发 TTFT / TPOT / 成功率 | §7.3 | — | ⬜ |
| prefix-caching 实际收益 | §5 | 作业会话（短窗口旁证） | 🟡 观测到 `Prefix cache hit rate` **23.5% → 32.0%**（18:22，同前缀连发 3 次）；**正式收益未测** |
| **受约束解码的能力边界**（`uniqueItems` 不兼容 ＋ 三类管不到的约束） | §4.3.1 | 作业会话（2 次真实 schema 生成实测） | ✅ 见 **§4.3.1** |
| 真实 `CFG-006` 产物**通过 `validate_pack.py` 全部门禁**的次数 | §7.3 | 作业会话 | ✅ **0/2**（**结构层 2/2**；**门禁层 0/2**）—— 见 **§4.3.1 ②** |
| `/mnt/e` vs `~/models` 加载耗时差 | §4.2 | — | ⬜ |
| **门禁层直出率**（`validate_output.py` 检查项通过率） | §7.3 | 作业会话（真跑产物 3 段实测） | ✅ **25/36 ＝ 69.4%**（梗概 5/6 · 剧本 7/9 · 分镜 13/21）；**产物级 `passed=true` ＝ 0/3** ⇒ `ISSUE-038` |

---

## 8 与工程侧的接口约定

| 约定 | 落点 | 纪律 |
| --- | --- | --- |
| 后端契约 | `app/inference/base.py` 的 `TextGenerator` | 服务层不感知 vLLM |
| 后端选择 | `app/inference/registry.py` ＋ `APP_INFERENCE_BACKEND` | 切后端**只改配置**，业务代码零改动 |
| 受约束解码形态 | `app/inference/vllm_backend.py` 的 `_payload` | 形态**收敛在一处**，不在代码里散落 if |
| 分段调用 | `app/services/segment.py` 的 `plan_segments` / `merge_segments` | 部署侧不参与分段逻辑 |
| 产物合法性 | `delivery/validate_pack.py` | **不由部署侧代偿** |

⚠️ **本手册不承诺任何产物质量**。服务起得来 ≠ 交付包合规；后者只由门禁判。

---

## 9 与 `OPS-001` 的分工

`OPS-001` 管**硬件**（选型、盘点、到货验收）；`OPS-002` 管**软件环境**（WSL2、vLLM、启动参数、调优、排查）。两者在「§6 上架与环境核对」处衔接——`OPS-001` 负责确认硬件到位，`OPS-002` 负责确认环境可跑。

---

## 10 修订说明

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| **V1.0** | 2026-10-15 | 首版。随 `PRO-006` §3 路线 A 裁决出具；含 `install-wsl2.ps1` ＋ `provision-vllm.sh` 两脚本（均经机器校验）。⚠️ **全部性能数值为待实测基线**，§7 清单未回填，`T-012` **不因本文档关闭**。 |
| **V1.1** | 2026-10-15 | 随手动路径**两轮**实跑纠错增补：① 纠正 `.wsl` 格式判断 —— **它是 gzip 压缩的 rootfs tar，不是 zip 容器**（§3.3 警告块改写）；② 新增 §3.3.1，记录解包／校验环节**三处缺陷**（漏传 Python 参数 ＋ `EAP=Stop` 吞掉原生 stderr ＋ **拿 `tar.exe` 退出码当完整性门禁**）及两条通用纪律；③ §3.3 校验表同步改写；④ 记入已备好的中间产物 `E:\distros\Ubuntu-24.04-rootfs.tar`（1216.5 MB / 49190 条目，已校验）。仍待实测：发行版导入落盘 + vLLM 起服务。 |
| **V1.2** | 2026-10-15 | 随**发行版导入成功、WSL 可启动**推进：① **§4.1 重写为三步执行**（进发行版 → 前置体检 → 跑供给脚本），并**订正发行版注册名** —— 本机经手动路径导入为 **`Ubuntu`**（非路径 A 的 `Ubuntu-24.04`），并说明「以 `wsl -l -v` 实际输出为准」；② 新增**pip 源实测表**（阿里云 ✅ / pypi.org ✅ / 清华源 **403** ❌）与 `PIP_INDEX` 用法，附「**WSL2 内 `127.0.0.1` 不是宿主**、Windows 代理不可直用」的说明与网关取法；③ §2、§7.1 同步回填（组件 / 重启 / 虚拟化 / 落盘四项已勾；`install-wsl2.ps1` 一项由手动路径**替代**、`Packages` 残留一项**不适用**）；④ `provision-vllm.sh` 新增 `PIP_INDEX` 开关、`--help` 改为按注释块截取（不再写死行号）、**pip 兜底分支改写**（Ubuntu 系统 python 禁用 `ensurepip`，原提示会被误读为「环境损坏」）。仍待实测：GPU 直通确认 + vLLM 装起。 |
| **V1.3** | 2026-10-15 | 随首次进入 WSL 的实况反馈增补：**新增 §3.7** —— 解读 `wsl: 检测到 localhost 代理配置，但未镜像到 WSL` 提示（**无害**：WSL 3.0.3.0 的 `autoProxy` 读到 Windows 侧 `127.0.0.1:7890`，NAT 下无法镜像；**正因为不镜像，WSL 内不会被塞进坏 `http_proxy`**），给出「忽略 / `autoProxy=false` / `networkingMode=mirrored`」三条分档处置，并新增 `env \| grep -i proxy` 自检；§4.1 第 ② 步同步加入该校验（期望 `NO-PROXY-ENV`）。 |
| **V1.4** | 2026-10-15 | 随 Linux 侧首轮实跑（`DRY_RUN=1 bash provision-vllm.sh`）反馈增补：① **§4.1 由三步扩为四步**，拆出「**③ 补齐 pip**」——Ubuntu 24.04 系统 python **不自带 pip 且禁用 `ensurepip`**（PEP 668 `externally-managed-environment`，**发行版策略非故障**），给出 venv（推荐）/ 系统 pip 两条处置；② `provision-vllm.sh` 修正**三处**：**`DRY_RUN=1` 不再因缺 pip / 缺 vLLM 而中断**（原停在 `2/5`，走不到打印启动参数——**干跑的意义落空**）、**venv 自动识别**（探测 `sys.prefix != sys.base_prefix` ⇒ 自动摘掉 `--break-system-packages` 并打印 `(venv)` 标记）、**版本比较加保护**（`[[ 未取到 -gt 0 ]]` 会被 bash 判为 `integer expression expected` 并在 `set -e` 下中止）；③ venv 提示的两行改用 `&& \` 续行，**粘成一行也能执行**（终端抄命令常丢换行，本轮已实际发生）；④ §7.1 回填三项实测（**`VERSION 2` 由内核字符串确认**、**WSL 内 `nvidia-smi` 列出 RTX 4090 ⇒ GPU 直通成立**、注册名 `Ubuntu`），新增「解释器 pip 就位」一项。三路分支实测全绿。 |
| **V1.5** | 2026-10-15 | 随「**大轮子下载太慢**」反馈增补，含**一处结论订正**：① **订正 pip 源推荐** —— V1.2 依据「200 / 0.57 s」把**阿里云列为采用**，但那只是**几十 KB 索引页的 HEAD，测不出吞吐**；改用大轮子取样实测后阿里云仅 **0.38 MB/s**（腾讯云 12.3 / USTC 11.7 / 华为 7.5 / pypi 直连 7.0 / **pypi 经宿主代理 62.4**），按 6~8 GB 差 **32 倍**，即「下载太慢」真因 ⇒ §4.1 换表并把 `PIP_INDEX=cn` 定为推荐；② **新增 §3.7.1**：讲清宿主代理**只绑 `127.0.0.1`**（实测非回环地址三处均 `000`）故 WSL 用不了，给出三条打通路径（客户端开 Allow LAN / `.wslconfig` 用 `networkingMode=mirrored` / `netsh portproxy`）与「先换源、再考虑动代理」的取舍；③ `provision-vllm.sh` 新增 **`--speedtest`**（各源取样测吞吐并排序，并打印本次是否走代理）、`PIP_INDEX` **简写**（`cn/ustc/huawei/aliyun/tuna/pypi`）、**`--pip-index`** 参数、**`PIP_PROXY`**（→ `--proxy`）、**`PIP_RETRIES`/`PIP_TIMEOUT`**；④ §4.1 补「换源即作废 pip 缓存（按 URL 索引）」与 `nohup` 后台跑法。`--speedtest` 与 `DRY_RUN` 四路分支已实测全绿。仍待实测：vLLM 装起 + 受约束解码端到端。 |
| **V1.6** | 2026-10-15 | 随「**测速 23 MB/s，实际下载却 0.3 MB/s**」的质疑增补，含**第二处口径订正**：① **订正 V1.5 的源排名口径** —— **短窗（10~12 s）单流读数不可作选源依据**：同一个阿里云同一天短窗 **0.38 ↔ 21.92（差 57 倍）**、腾讯云 12.33 ↔ 4.43；改用**一次真实 pip 安装**（累计 2.5 GB / 224 个对象，按 pip 缓存文件的完成时间**逐个反算**）取得**持续口径**：阿里云 **0.31 MB/s**（区间 0.20~0.37，**极稳定 ⇒ 更像被限速而非拥塞**），仅为短窗读数的 **1/70** ⇒ §4.1 表改为「短窗／持续」双列，并明确**只认持续列**；② `--speedtest` 重构为**快测（全源）＋ 持续测（快测前 N 名）两列＋衰减百分比**，表格字段改**纯 ASCII**（原中文全角括号把 `printf` 的 `%-Ns` 对齐挤歪），失败输出改**逐源可辨**（取材失败／快测失败，含 `403` 与 `http=000` 两类）；③ `provision-vllm.sh` 新增 **`PIP_RESUME_RETRIES`**（→ `--resume-retries`，**先探测 pip ≥ 23.1 再下发** —— 低版本传了会以 unknown option 直接退出）与 `SPEEDTEST_WINDOW` / `SPEEDTEST_SUSTAIN` / `SPEEDTEST_TOP`；④ §4.1 的「换源」段改成**可算的账**（剩余量 ÷ 旧源持续 vs 全量 ÷ 新源持续），并记入本机实例（阿里云已攒 **2.5 GB**，短窗 21.92 但持续 0.31 ⇒ **换源划算**）。新版 `--speedtest` 已实测跑通。仍待实测：vLLM 装起 + 受约束解码端到端。 |
| **V1.7** | 2026-10-15 | 随「**启动后期报错**」定位增补，含**一处部署缺陷根治**：① **新增 §4.1.1「编译工具链与 PATH 归位（必做）」** —— vLLM 运行期会 fork 子进程调外部程序（flashinfer JIT 需 `ninja`、inductor 需 `g++`、JIT 需 `nvcc`），而脚本以**绝对路径**调解释器**不会激活 venv** ⇒ `ninja` 不在 `PATH`。本机实测：`ninja` 只存在于 `~/vllm-venv/bin/`，**系统 `/usr/bin` 下没有**；系统**既无** `/usr/local/cuda` **也无** `/usr/bin/nvcc`（pip 版整套 toolkit 在 `site-packages/nvidia/cu13`，`bin/include/lib/nvvm` 齐备）。② **新增 §6.1「不一定是 OOM：先按崩溃点定位」** —— 给出「**无日志时靠文件系统写入痕迹定位**」的判据表：`usage_stats.json` 含 `ENGINE_CONTEXT` ⇒ 崩在**启动后期**（别再查驱动/权重）；`flashinfer_jit.log` **0 字节** ＋ `cached_ops/<op>/` **空目录** ＋ lock **残留** ⇒ JIT **在产生输出前**已失败（优先怀疑工具链/PATH）；`kern.log` 无 `Out of memory: Killed process` ⇒ **与显存无关**；「最后一个被写入的文件」即崩溃点。并记入 `\\wsl$` 上 **`ls -d` / `stat` 对符号链接报 `Input/output error`**会伪装成「文件不存在」的纪律——**本轮据此差点把已装好的 `g++` 判成缺失**，核查存在性须用「列目录 ＋ 过滤」。③ `provision-vllm.sh`：**自动 venv 归位**（认 `pyvenv.cfg` ⇒ `<venv>/bin` 与 pip 版 CUDA 工具链 `bin` 追加进 `PATH`，`CUDA_HOME` 未设时兜底、已设则不覆盖）、**新增工具链门禁**（缺 `ninja`/`g++` **默认停下**并给两条命令，`ALLOW_NO_TOOLCHAIN=1` 显式降级且设 `VLLM_USE_FLASHINFER_SAMPLER=0`，`DRY_RUN=1` **只告警不阻断**）、**解释器路径归一化改用 `command -v` ＋ `cd/pwd`**（`readlink -f` 在 MSYS 下可能返回含冒号的 `C:/…`，塞入 `PATH` 会被**当成两段而静默失效**）。④ §7.1 回填四项（pip **26.2.1** 就位、`build-essential` 就位、vLLM **0.31.0**、编译工具链状态及其例外）。**五路分支实测全绿**（干跑走完 `5/5`；venv 有/无 `ninja` 两种；`ALLOW_NO_TOOLCHAIN=1` 降级**真正走到启动**；非干跑门禁退出码 1）。仍待实测：vLLM 起服务 ＋ 受约束解码端到端。 |
| **V1.8** | 2026-10-15 | 随**第二次真起服务**（首次拿到**全量日志**）增补，定位到「启动后期崩溃」的**第二层真因**：① **新增 §4.1.2「CUDA 编译器与头文件必须同 minor」** —— 补上 `ninja` 后 JIT **真的进入编译**但**编译失败**，报 `cuda_toolkit.h:41` 的 `#error "CUDA compiler and CUDA toolkit headers are incompatible"`；该判定是 **CCCL 硬性的**：`_CCCL_CUDACC_EQUAL(CUDART_VERSION/1000, (CUDART_VERSION%1000)/10)` ⇒ **`nvcc` 与 CUDA 头文件的 `major.minor` 必须严格相等**。本机实测：`nvidia-cuda-nvcc`/`crt` **13.4.92** vs `nvidia-cuda-runtime` **13.0.96**（`CUDART_VERSION 13000` ⇒ 13.0）⇒ 差一个 minor。**成因＝依赖漂移**：元包 `cuda-toolkit 13.0.3.0` 声明自洽组合 `nvcc/crt==13.0.88.*` ＋ `runtime==13.0.96.*`，而 `tilelang`（`nvidia-cuda-nvcc>=13.0.48`）与 `humming-kernels`（未钉版）把 `nvcc` 拉到最新 13.4.92。② **新增 §6.2「读懂 `Engine core initialization failed`」** —— 讲清 `Failed core proc(s): {}` **为空**意味着**真因被打印在它上方**（`EngineCore` 子进程自己的 traceback），**只有 `tee` 才拿得到**；并给出「日志行 → 含义 → 去处」的对照表（未进入 ninja／进了 ninja 但 FAILED／CCCL `#error`／头文件找不到／真 OOM）。同时记入 **vLLM 自动降级存在盲区**：`flashinfer_sampler_supported()` 的预判只覆盖 SM 架构类问题，**覆盖不到**「要真编译才炸」的版本不兼容 ⇒ 版本一致性**必须由部署侧前置检查**。③ `provision-vllm.sh`：**新增 CUDA 版本一致性自检**（读 `$CUDA_HOME/include/cuda_runtime_api.h` 的 `CUDART_VERSION` 与 `nvcc --version` 的 `release X.Y` 比对），**不一致时响亮降级**（打印两边版本＋后果＋两条处置，并设 `VLLM_USE_FLASHINFER_SAMPLER=0`）；新增 `REQUIRE_FLASHINFER_SAMPLER=1` 可**强制严格**（不一致即 `die`）；启动参数区**新增「采样后端」一行**，把实际生效的采样路径写进日志。⚠️ 该「响亮降级」与 §4.1.1「缺工具即 `die`」**策略刻意不同**，理由（flashinfer 采样是可选加速路径、与原生路径 *statistically equivalent*、**不参与受约束解码**）已写进脚本注释与 §4.1.2，**属决策而非遗漏**。④ §7.1／§7.2 回填本轮实测（`ninja` 归位**被证实生效**；新增「CUDA 版本一致性」未通过项；记录 17:51–17:53 首次起服务失败）。**四路分支实测全绿**（不一致→降级；一致→`[OK]`；`REQUIRE_FLASHINFER_SAMPLER=1`＋不一致→退出码 1；`PATH` 无 `nvcc`→告警不崩），干跑走完 `5/5`，纯 LF、无 BOM。仍待实测：vLLM 起服务 ＋ 受约束解码端到端。 |
| **V1.9** | 2026-10-15 | 随**第三次实跑（`--serve-only` 成功起服务）**增补，**首次回填引擎实测值**：① 新增 **§5.1「本机实测生效值（2026-10-15 18:10，首次成功起服务）」** —— 数据源＝`~/vllm-serve.log`（150 行 / 19.6 KB）：引擎 **vLLM 0.31.0**（`torch 2.13.0+cu130`）／架构 `Qwen2ForCausalLM`／**KV Cache 可用显存 4.7 GiB**／**GPU KV Cache 容量 88,032 tokens**／**最大并发 5.37x @16384**／KV 布局 `LBNHC`／`torch.compile` **10.11 s**（单图 4.54 s）／CUDA Graph 捕获尺寸 `[1,2,4,8,16,24,32]`／服务 `http://0.0.0.0:8001`、`Application startup complete.` @18:10:42。② **记入一条与 `SYS-015` 直接相关的硬约束**：**「单卡 10 并发」在 16384 全长度下不成立** —— KV 容量折算 **5.37 路/16384**；要 10 并发须**平均上下文 ≤ 88032 ÷ 10 ≈ 8,803 token**（恰在「16384 − 8192 输出 = 8192 输入」量级，与 `TPL-009` 的 `max_tokens=8192` 相容）⇒ **`T-013` 压测必须同时记录「并发数 × 实际上下文长度」两个维度**，只报「10 并发」会掩盖该约束。③ **记入两条影响口径的运行时提示**：（a）**模型自带 `generation_config.json` 会覆盖 vLLM 默认采样参数** —— 日志明示实际生效为 `repetition_penalty 1.05 / temperature 0.7 / top_k 20 / top_p 0.8`；备案口径若声明采样参数，须以**实际生效值**为准，或加 `--generation-config vllm` 关掉覆盖；（b）`Pinned memory is not available on this platform` —— **WSL2 不支持 pinned memory**，回退设备内存，属 **WSL 固有限制非配置错误**（影响轻微，勿当故障排查）。④ §5 启动参数基线表**逐项回填状态**（`gpu_memory_utilization` 已生效且日志给出等价口径 `0.8959`；`max-num-seqs` 已生效但标注 KV 约束；`enable_prefix-caching`／`enable_chunked_prefill` 实测为 True；新增「采样后端」行）；§7.1／§7.2 回填本轮实测（**服务起成**、KV Cache 两项打勾），§7.4 `显存/KV` 与**实际生效采样参数**两行标 ✅；§7.2 并明记 **「脚本末步 `exec`，不加 `tee` 输出仍不落盘 —— 本次日志全靠用户手工 `tee`」**。⑤ 沿用批（`DEV-20261015-012`）：**降级路径一次通过**（`[WARN] nvcc 13.4 ／ CUDART 13.0` → `VLLM_USE_FLASHINFER_SAMPLER=0` → `5/5` 启动成功）。⚠️ 仍未验证：`/v1/models` 连通性、**受约束解码端到端**、10 并发 TTFT/TPOT（§7.2／§7.3）⇒ `T-012` **不关闭**。 |
| **V1.10** | 2026-10-15 | 随**服务在跑期间做端到端校验**增补（触发＝用户询问「在新的 PowerShell 窗口跑吗」；由作业会话**在 Windows 侧代跑**全部校验命令）。① **新增 §4.3.1「受约束解码的能力边界」** —— 这是 §4.3 的**下篇**（§4.3 讲「参数形态发错会静默退化」，§4.3.1 讲「参数发对了仍有管不到的地方」）：（a）**`uniqueItems` 是 xgrammar 当前唯一不支持的关键字** ⇒ 真实 `CFG-006` 原样传入即被**编译期**拒收，实测 `{"error":{"message":"Grammar error: Unimplemented keys: [\"uniqueItems\"]","code":400}}`（~0.01 s）；**好消息是响亮失败而非静默退化**；逐轮剥离实测**只需剥离这一处**（`pattern`×16／`enum`×19／`minItems`×7／`maxItems`／`minLength`／`minimum`／`multipleOf`／`const`／`oneOf`／`$ref`×9／`format` **全部可通过**）；处置＝引擎侧剥离该键、**应用层仍用完整 schema 校验**补回（`validate_pack.py` 走 `jsonschema`，支持 `uniqueItems`）⇒ 约束不丢失，只**换执行位置**。（b）**三类约束引擎侧结构性表达不了**，由 2 次真实 schema 生成实测证明（`schema` 层 2/2 全 0 错、**门禁层 0/2**）：**可选项的覆盖率**（`camera.height`／`optics`／`lighting` 在 schema 可选，而质量门要求 ≥30~60% —— JSON Schema 无法表达「N 个实例里至少 M 个填了某字段」这类**跨实例统计**）；**跨字段算术一致**（`meta.total_duration_ms` 须 = Σ`shots[].duration_ms` —— 标准 draft 2020-12 **不支持字段间算术**）；**取值来自另一份文件**（`duration_ms` 下界 4000 ms 在 `CFG-001_model_adapters.yaml`，schema 依规范 §0.4 **刻意不引用**模型数值）。（c）**实测到的模型行为**：对 `optional` 字段与「下限值」一律走**最小满足**（只给 `minItems` 的 2 镜、`duration_ms` 取下限 1000 ms、省掉全部可选字段）；且**提示词里明确要求也会被漏填**（第 2 次生成在提示词第 4 条明写 `camera.height` 必填，结果 4 镜**全漏**）。（d）据此确立**链路形态**：prompt 承载质量门要求（不可依赖）→ 引擎受约束解码（保证**结构**合法，这才是它的价值）→ `validate_pack.py` 门禁（**必须保留**）→ 不通过则携带诊断信息重试。② **§7.2 回填 2 项**：`/v1/models` **200**（`max_model_len=16384`、`root=/mnt/e/models/…` 均与 §5.1 一致）；**Windows→WSL 回环连通性实测**（`wslrelay.exe` 监听 `127.0.0.1:8001`，`.wslconfig` 不存在 ⇒ 默认 `localhostForwarding=true`）⇒ **§4.4 的「通常可直接互通」升格为「已实证」**，并补记 **PowerShell 里必须写 `curl.exe`**（裸 `curl` 是 Alias → `Invoke-WebRequest`，实测 `-s`/`--max-time` 全不认）与「`Invoke-WebRequest` 默认吃系统代理 ⇒ 连本地地址也要 `--noproxy '*'`」。③ **§7.3 四项逐项回填**：第 1 项 ✅ **按严格形式验证**（提示词**明确索要** schema 外的 `forbidden_field`，引擎仍**只**输出 `only_field` ⇒ 约束在**解码层强制**）；**并加做对照组**（同提示词不加 `response_format` ⇒ 模型输出 `name/age/gender/address` 一大串 ＋ Markdown 围栏 ⇒ 反证前者不是「碰巧」）。第 2 项 **判据订正**：原文「直出即合规（无需重试）」**只在结构层成立** —— 实测结构层 **2/2 全 0 错**、**门禁层 0/2**（4 项 / 3 项 BLOCK）⇒ 改为「结构层直出即合规；**门禁层必须保留 ＋ 重试**」。第 3 项 ⬜ **仍未做且不能单独立项**（前提「存在能让产物过门禁的 prompt」按 ② 尚未成立）。第 4 项 ⬜ 属 `T-013`，并标注**必须同时记录「并发数 × 实际上下文长度」**。④ §7.4 台账增 2 行、更新 1 行（`prefix-caching` 记入 `Prefix cache hit rate 23.5% → 32.0%` 短窗口旁证）。**验证**：手册改动逐处回读；`validate_pack.py` 实跑（两次产物分别 4 项 / 3 项 BLOCK，退出码 1）；手册保持**纯 LF**、无 BOM、985 行。⚠️ **仍未验证**：门禁层直出率、连发多段、10 并发 TTFT/TPOT、应用侧 `/ready` ⇒ `T-012` **不关闭**。 |
| **V1.11** | 2026-10-15 | 随**应用侧收尾真跑**增补（触发＝项目方「立刻执行完整收尾」；留痕 `DEV-20261015-014`）：① **§5 参数表 `--max-model-len` 由推导值转为实测值并上修 16384 → 32768** —— 用引擎自身 `POST /tokenize` 对完整渲染 prompt **精确计数**（非字符估算）：最长分段是 **`storyboard` 段 ＝ 14473 tokens**（30252 字符；模板正文 24438 ＋ 上游 `script_json` 5814）⇒ 需窗口 ≥ **22665**，**原 16384 只剩 1911 输出预算**，该段被引擎**入口 400 拒收**（应用如实转 `502 GENERATION_FAILED`，**状态不推进、无假推进**）⇒ 登记 **`ISSUE-032`**；⚠️ 记入两条易误判的推论：**(a) 提窗不额外占显存**（KV 池容量由 `gpu_memory_utilization` 决定，实测 88,032 tokens，与 `max_model_len` **无关**），代价仅为**满长度并发 5.37x → 约 2.68x**；**(b) 瓶颈在模板自身体量、不在上游产物**（模板正文 24438 字符 ≫ 上游 `script_json` 5814 字符）⇒ 「最长分段」**不是**名字最像交付物的 `shot_prompt`。② **§7.2 回填 `/ready` 项**（应用以 `APP_INFERENCE_BACKEND=vllm` 起成，`http=200`、`inference_backend=vllm`、16 模板）＋ **§7.1 回填 `max-model-len` 项**，§7.4 台账同步。③ **§6 OOM 排查表增补反向提示**：长提示词 OOM 时**勿**降窗口（会把主链第 3 段直接挂掉），优先降 `--max-num-seqs` 或开 `--kv-cache-dtype fp8`。④ `provision-vllm.sh` 默认值与启动参数区说明同步。⚠️ **仍未验证**：第 3／4 段真跑（**待提窗重启**）、`segment=auto` 多段分支、连发多段、10 并发 TTFT/TPOT、门禁层直出率 ⇒ `T-012` **不关闭**。 |
| **V1.12** | 2026-10-16 | 随**次日续跑 `T-004` 时的一次起服务失败**增补（触发＝项目方粘贴 `bash provision-vllm.sh --serve-only` 在第 3 步 `[ERROR] 无法导入 vllm` 的现场输出）。① **新增 §4.1.3「漏写 `PY_BIN` 前缀会静默降级」** —— 定位结论：**这次失败与 venv 是否损坏无关**，而是 `PY_BIN` 旧默认值写死 `python3`、人工漏写前缀 ⇒ **静默降级成系统解释器**，并连带把「运行环境归位」与「CUDA 版本一致性自检」**整段跳过**（后者只 `warn` 不 `die`）⇒ **恰恰是 §4.1.2 最费时定位出来的那层真因被无声绕过**。记入**一眼认出的判据**：「预期路径」打印成 `/include/cuda_runtime_api.h`（＝ `CUDA_HOME` 为空）；并记入一条**易误判点**：系统 python 与 venv **同为 3.12.3**，**光看版本号区分不出来**。② **`provision-vllm.sh` 从默认值根治**（不只加提示）：`PY_BIN` 未显式给出时**自动探测 `~/vllm-venv`** 并用之（打印 `[OK] 解释器：…自动探测到 venv`）；探不到才回落 `python3` 并**响亮提示**；**显式传参永远优先**（走方案 ① 须显式写 `PY_BIN=/usr/bin/python3`）。③ §4.1「跑供给脚本」段的「方案 ② **每次都要带上**该前缀」**已订正**为「前缀可省略 ＋ 方案 ① 须显式指定」；脚本 `--help` 注释同步。④ **订正一处本文档自身缺陷**：头部版本号停留在 **V1.10**，而 §10 已有 `V1.11` 行 ⇒ 本轮对齐为 **V1.12**（属上一批遗留的「改版未同步头部」）。⑤ 同一轮**顺带核验** venv 健康性与 **`nvidia-cuda-nvcc`/`crt` 漂移复发**（13.4.92 vs `runtime` 13.0.96）—— 后者不影响起服务（按 §4.1.2 响亮降级），但记入「`--upgrade vllm` 后须复查」。⚠️ 本轮**未新增任何实测通过项**：`§7` 原先未回填的项目（第 3／4 段真跑、`segment=auto` 多段分支、10 并发 TTFT/TPOT、门禁层直出率）**仍`T-012` 不关闭**。 |
| **V1.13** | 2026-10-16 | 随**分镜段真跑通过后的第 4 段新阻断**增补（触发＝项目方报「`5/5` 与 `Application startup complete` 已经出现」；留痕 `DEV-20261016-002`）。① **§5 参数表 `--max-model-len` 行与 §5 注记**：补出**窗口边界的第二条**——32768 **足以**跑 `storyboard`（真跑 129.7 s，`ISSUE-032` **解除**），**不足以**跑 `shot_prompt`（该段**输入自身 50,358 tokens**）。② **补出一条新判据（本版最重要）**：**`segment` 拆段只减输出、不减输入** —— 实测三种粒度渲染后输入 ＝ 50,358／50,360／50,366 tokens（差 ≤8，只来自 `segment` 取值字符串），因模板 `output` 节按 `{segment}` 分支而**输入侧的 `*_json` 无条件全量注入** ⇒ **「拆段」与「提窗」正交，输入侧超窗时两者都救不了**；归因＝`TPL-009` 把上游重复插入（`{storyboard_json}` ×5／`{script_json}` ×3／`{pack_meta}` ×4，固定部分仅 24,041 字符）⇒ 放大 **2.44 倍**。③ **§6 OOM 决策树「长提示词」行补反向边界**：提窗有尽头（原生 32768），此后应**减输入**而非继续提窗。④ **§7.1 增补第四次实跑进度块**（`max_model_len: 32768`／KV 88,032／2.69x@32768 并发；并**在真实环境验证 §4.1.3 的修复**：`[OK] 解释器：未显式指定 PY_BIN，自动探测到 venv`）。⑤ **§7.2／§7.3／§7.4 三处据此订正并回填**：`max-model-len` 项补边界；「连发多段」项改记「多段分支已触发、第 1 段被拒」；**新增「门禁层直出率」行**＝ **25/36 ＝ 69.4%**（产物级 **0/3**，`ISSUE-038`）。⚠️ **仍未验证**：连发 ≥3 次不同 `segment`、10 并发 TTFT/TPOT ⇒ `T-012` **不关闭**；`T-004` 仍判 🟦（第 4 段被 `ISSUE-037` 卡住，**处置方案须项目方裁决**） |
| **V1.14** | 2026-10-16 | 随**第 4 段真跑打通**增补（触发＝项目方裁决「**选 D 方案**」；留痕 `DEV-20261016-003`）。① **§5 注记追加「输入侧预算的反解口径」** —— 补上 V1.13 留下的那一半：V1.13 只说明「**拆段救不了输入侧**」，本版说明**输入侧本身可压**（`TPL-009` 上游重复搬运 2.44 倍 ⇒ **模板去重 50,358 → 20,324** ＋ **服务层无损紧凑化 → 17,897**，合计 **-64.5%**），并给出**正确用法**：「**先算输入预算，再定 `--max-model-len`**」；⚠️ 两次低估的成因各记一条（V1.11 只按「模板正文 + `max_tokens`」推导、V1.13 之后又发现**输入自身**已超窗）。② **无参数值改动** —— `--max-model-len` 仍为 **32768**（本轮第 4 段在 `all` 单包口径下 **26,089 ✅** 通过）。③ **顺带修复一处既有表格结构缺陷（登记 `ISSUE-043`）** —— §10 本表 `V1.3` 行正文的`` `env \| grep -i proxy` `` 处原为**裸竖线**，而 **GFM 要求表格单元格内的竖线一律转义（含行内代码 span 内）** ⇒ 该行被切成 **4 格**（表头 **3 格**），渲染时**多出一列／串列**；已**机械转义**（**零语义变更**） |

> ⚠️ **2026-10-15 复验补记（本轮）**：本表 `V1.3` 与 `V1.4` 两行此前**被相邻行吞并** ——
> `V1.3` **整行在表中不可见**、`V1.4` 仅剩残尾粘在 `V1.5` 行末（属**表格行合并缺陷**，
> 本工程在 `REQ-001` §13 亦有同形前例）。本轮已**按原文逐字拆回**为独立两行、**文本零删改**，
> 并新增 `V1.5` 行。**教训**：用「只匹配行首」的方式给长表格插行，会把**相邻行的内容**一并吃掉 ——
> 插入后**必须回读该行**（本轮即靠回读发现）。
