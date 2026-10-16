<#
.SYNOPSIS
    安装并落位 WSL2（发行版装到 E 盘，避开 C 盘容量瓶颈）。

.DESCRIPTION
    对应任务 T-012 / 部署手册 OPS-002 §3。
    本脚本**只做三件事**：启用两个可选组件、安装 WSL 内核与默认版本、把发行版
    导入到 E 盘的专用目录。**不装 vLLM**（那是 Linux 侧 provision-vllm.sh 的职责）。

    落 E 盘的理由：C 盘实测余量偏紧（2026-10-15 实测 30.2 GB），WSL2 的虚拟磁盘
    （ext4.vhdx）会随发行版、pip 缓存与容器镜像持续增长；放 C 盘有挤爆系统盘风险。
    依据《硬件级需求文档》§10.1「C 盘只放运行环境」。

.PARAMETER Distribution
    要安装的发行版。默认 Ubuntu-24.04（WSL2 原生支持最好）。

.PARAMETER InstallRoot
    发行版落盘根目录（**必须是 Windows 盘路径**）。默认 E:\wsl。

.PARAMETER SkipComponentEnable
    跳过「启用可选组件」步骤（组件已启用时用，避免重复提权）。

.PARAMETER SkipRebootCheck
    跳过「是否需重启」的中断检查（自动化场景；请自行确认重启时机）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-wsl2.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-wsl2.ps1 -Distribution Ubuntu-22.04 -InstallRoot F:\wsl

.NOTES
    ⚠️ **本文件必须保留 UTF-8 BOM**。原因：Windows PowerShell 5.1（Desktop，本机实测
    5.1.26100.9711）读取 `.ps1` 时按 **ANSI 代码页（本机 gb2312）** 解码，**无 BOM 的
    UTF-8 中文脚本会被误解码**，破坏引号配对、报出与真实代码无关的语法错误。
    （本脚本实测：无 BOM → 7 处假语法错误；加 BOM → 0 错误。）

    ⚠️ 行尾为 **LF**（本仓库受控文件规范）。

    Exit code：0 = 成功；2 = 非管理员；3 = 组件启用后需重启；4 = 安装失败。

    校验方式（改动后请复跑，不依赖肉眼检查）：
        powershell -NoProfile -Command "$e=$null;[Management.Automation.Language.Parser]::ParseFile('<本文件路径>',[ref]$null,[ref]$e);if($e){$e|%{$_.Message}}else{'PARSE OK'}"
#>

[CmdletBinding()]
param(
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$InstallRoot = 'E:\wsl',
    [switch]$SkipComponentEnable,
    [switch]$SkipRebootCheck
)

$ErrorActionPreference = 'Stop'
$script:ExitOk = 0; $script:ExitNotAdmin = 2; $script:ExitNeedReboot = 3; $script:ExitFail = 4

function Write-Step { param([string]$Msg) Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Msg) Write-Host "    [OK] $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "    [WARN] $Msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$Msg) Write-Host "    [ERROR] $Msg" -ForegroundColor Red }

# 调用 wsl.exe 并**把 UTF-16LE 输出转成可读文本**，同时回传退出码。
# ⚠️ 为什么需要它（2026-10-15 实测教训）：
#    ① wsl.exe 输出是 **UTF-16LE**，PowerShell 直接显示是一串乱码问号；
#    ② `& wsl.exe ... 2>&1` 会把错误流并入输出，若丢弃（`$null =`）就**看不到失败原因**；
#    ③ **只看 $LASTEXITCODE 不可靠**——组件刚启用未重启时，wsl 可能返回错误文本而退出码仍为 0，
#       只看退出码会**假报成功**。故调用方须同时校验「退出码 + 实际产物」。
function Invoke-Wsl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$WslArgs)
    # ⚠️ 必须 try/catch：`wsl.exe` 可能因**权限不足／被安全软件拦截／文件缺失**而
    #    直接抛 NativeCommandFailedException（`ResourceUnavailable`）——
    #    此时既无退出码也无输出。若不捕获，脚本会以未处理的异常终止（exit 1），
    #    既不是成功也不是本脚本约定的失败码，调用方无法判别。**统一归一为 exit 1。**
    try {
        $raw = & wsl.exe @WslArgs 2>&1
        $code = $LASTEXITCODE
        $text = (($raw | ForEach-Object { ($_ -replace "`0", '') }) -join "`n")
        return [pscustomobject]@{ ExitCode = $code; Text = $text; LaunchFailed = $false }
    } catch {
        return [pscustomobject]@{
            ExitCode     = 1
            Text         = "wsl.exe 未能启动：$($_.Exception.Message)"
            LaunchFailed = $true
        }
    }
}

# ---------------------------------------------------------------- 0. 提权检查
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err '需要管理员权限。请以「管理员身份」重开 PowerShell 后重试。'
    Write-Host '    右键 PowerShell →「以管理员身份运行」'
    exit $script:ExitNotAdmin
}
Write-Ok '管理员权限已具备'

# ---------------------------------------------------------------- 1. 前置体检
Write-Step '1/5 前置体检'

$build = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
$buildNo = [int](($build -split '\.')[0])
Write-Host "    Windows build : $build"
if ($buildNo -lt 19041) {
    Write-Warn "build $buildNo < 19041，WSL2 需 Windows 10 2004 及以上；建议升级后再装。"
}

# ---- 虚拟化判据（**重启前后口径不同，切勿只看一个字段**）----
# ⚠️ 2026-10-15 实测踩坑：重启后 `VirtualizationFirmwareEnabled` 由 True **翻转为 False**，
#    脚本据此误报「虚拟化未开启」并退出。真相是：**Hypervisor 加载后会接管这三个字段**，
#    Windows 即不再暴露 BIOS 层的 VT-x/SLAT 值 —— **False 不代表虚拟化不可用**。
#    正确的首选判据是 `HypervisorPresent`：True 即表示虚拟化平台内核已加载，WSL2 可用。
#    交叉验证口径（实测）：`systeminfo` 会报
#    「Hyper-V Requirements: A hypervisor has been detected.」
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1

Write-Host "    HypervisorPresent             : $($cs.HypervisorPresent)"
Write-Host "    VirtualizationFirmwareEnabled : $($cpu.VirtualizationFirmwareEnabled)  （Hypervisor 加载后该字段会被接管而报 False，非异常）"
Write-Host "    SLAT                          : $($cpu.SecondLevelAddressTranslationExtensions)"

if ($cs.HypervisorPresent) {
    # 判据 A（首选）：Hypervisor 已加载 ⇒ 虚拟化平台就绪
    Write-Ok '虚拟化已就绪（HypervisorPresent=True，内核已加载 Hyper-V 虚拟机监控程序）'
} elseif ($cpu.VirtualizationFirmwareEnabled) {
    # 判据 B：Hypervisor 未加载但 BIOS 层开启（组件刚启用、尚未重启时的正常形态）
    Write-Ok '虚拟化已在 BIOS 层开启（Hypervisor 尚未加载 —— 若组件刚启用，请重启后重跑）'
} else {
    Write-Err '虚拟化确未开启 —— WSL2 无法启动。'
    Write-Host '    两个判据均为 False（HypervisorPresent 与 VirtualizationFirmwareEnabled）。'
    Write-Host '    处置：进 BIOS 开启 Intel VT-x / AMD-V（SVM Mode）后重试。'
    exit $script:ExitFail
}

$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
Write-Host "    显示适配器: $($gpu.Name)"
Write-Warn '若为 NVIDIA 独显 + 核显并存，WSL2 默认不会直通 GPU；见 OPS-002 §3.5。'

# C 盘余量（落盘决策的依据）
$sysDrive = Get-PSDrive -Name ($env:SystemDrive.TrimEnd(':'))
$sysFreeGB = [math]::Round($sysDrive.Free / 1GB, 1)
Write-Host "    系统盘余量  : $sysFreeGB GB（$($env:SystemDrive)）"
if ($sysFreeGB -lt 30) {
    Write-Warn "系统盘余量仅 ${sysFreeGB} GB —— 发行版**务必**装到非系统盘，见 OPS-002 §3.3。"
}

# ---------------------------------------------------------------- 2. 启用可选组件
if ($SkipComponentEnable) {
    Write-Warn '已按 -SkipComponentEnable 跳过组件启用'
} else {
    Write-Step '2/5 启用可选组件（Microsoft-Windows-Subsystem-Linux / VirtualMachinePlatform）'
    $needReboot = $false
    # ⚠️ `Enable-WindowsOptionalFeature` 会向控制台**狂刷进度条**（实测数百行），
    #    把脚本自身输出彻底淹没。`-LogPath` 把它导向日志文件，终端才读得下去。
    $logDir = Join-Path $InstallRoot '_logs'
    $null = New-Item -ItemType Directory -Force -Path $logDir
    foreach ($feat in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $state = (Get-WindowsOptionalFeature -Online -FeatureName $feat).State
        if ($state -eq 'Enabled') {
            Write-Ok "$feat 已启用"
        } else {
            Write-Host "    启用 $feat （进度输出已重定向到日志）..."
            $log = Join-Path $logDir ("enable-" + $feat + ".log")
            $null = Enable-WindowsOptionalFeature -Online -FeatureName $feat -NoRestart -LogPath $log
            Write-Ok "$feat 已请求启用（详见 $log）"
            $needReboot = $true
        }
    }
    if ($needReboot -and -not $SkipRebootCheck) {
        Write-Warn '组件变更需重启后生效。请重启后重新运行本脚本。'
        exit $script:ExitNeedReboot
    }
}

# ---------------------------------------------------------------- 3. 安装 WSL 内核与默认版本
Write-Step '3/5 安装 WSL（Store 版含内核与 WSL2 默认版本）'
$r = Invoke-Wsl --install --no-distribution
if ($r.LaunchFailed) {
    Write-Err $r.Text
    Write-Host '    常见原因：安全软件／组策略拦截 wsl.exe，或系统未安装 WSL 组件。'
    Write-Host '    请检查 Windows 安全中心「病毒和威胁防护」的「勒索软件防护」与第三方杀软拦截记录。'
    exit $script:ExitFail
}
if ($r.ExitCode -ne 0) {
    # 老版本 wsl.exe 不支持 --no-distribution，回落到 --update
    Write-Warn "--install 不可用（exit=$($r.ExitCode)），改用 --update"
    $r = Invoke-Wsl --update
}
if ($r.ExitCode -eq 0) {
    Write-Ok 'WSL 已安装/更新'
} else {
    # ⚠️ 组件刚启用未重启时，wsl 会失败或返回提示文本——**此时不能算成功**。
    Write-Warn "WSL 安装/更新返回 exit=$($r.ExitCode)"
    if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }
    Write-Host '    若提示「需要重启」或虚拟化未生效 → **请先重启 Windows 后重跑本脚本**。'
    Write-Host '    离线兜底：https://github.com/microsoft/WSL/releases 下载 .msi 后本地安装'
}

Write-Step '设置默认版本为 WSL2'
$null = & wsl.exe --set-default-version 2 2>&1
$r = Invoke-Wsl --status
if ($r.Text.Trim()) {
    Write-Host '    wsl --status：'
    $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      $($_.Trim())" }
}

# ---------------------------------------------------------------- 4. 落盘到非系统盘
Write-Step "4/5 落盘 $InstallRoot"
# 装 C 盘的兜底：Import 后 C 盘会留下旧 vhdx，须显式导出再迁，否则两份占盘
$null = New-Item -ItemType Directory -Force -Path $InstallRoot
Write-Ok "落盘根目录就绪：$InstallRoot"

Write-Step "5/5 安装发行版 $Distribution"
$target = Join-Path $InstallRoot $Distribution
$vhdx = Join-Path $target 'ext4.vhdx'
$tar = Join-Path $InstallRoot "$Distribution.tar"

if (Test-Path $vhdx) {
    Write-Ok "已存在发行版实例，跳过安装：$target"
    Write-Host "    如需重装：wsl.exe --unregister $Distribution"
} else {
    # 先装到默认位置（%LOCALAPPDATA%\Packages），再导出迁到目标盘，最后注销清理原件。
    # ⚠️ 之所以「装→导出→注销」：wsl --install 不支持直接指定安装路径。
    # ⚠️⚠️ **每步都必须验退出码并检查落盘结果**——2026-10-15 实测教训：
    #    wsl.exe 在「组件刚启用未重启」时会返回错误文本，而 PowerShell 的
    #    `$LASTEXITCODE` 仍可能为 0；若只看退出码就会**假报 [OK]**（本脚本曾如此）。
    #    故本版改为「退出码 + 结果文件/注册表**双重**校验」，任一不满足即失败退出。

    Write-Host '    步骤 a：装到默认位置（临时占 C 盘空间，装完即迁走）'
    $r = Invoke-Wsl --install $Distribution --no-launch
    if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }

    # 双重校验 1：wsl 自身的发行版清单里必须出现该发行版
    $rL = Invoke-Wsl -l -q
    if ($rL.Text -notmatch [regex]::Escape($Distribution)) {
        Write-Err "发行版未注册成功（`wsl -l -q` 中查不到 '$Distribution'，exit=$($rL.ExitCode)）"
        Write-Host '    常见原因与对策：'
        Write-Host '      ① **组件刚启用、Windows 尚未重启** —— wsl 无法真正启动，请先重启再重跑本脚本；'
        Write-Host '      ② Microsoft Store 通道不可用 —— 改为手动安装：'
        Write-Host '         设置 → 系统 → 可选功能 → 查看功能 → 勾选「适用于 Linux 的 Windows 子系统」旁的'
        Write-Host '         「Ubuntu」标记，或直接搜索 Ubuntu 24.04 LTS 安装；'
        Write-Host '      ③ 网络受限 —— 先在浏览器打开 https://aka.ms/enablevirtualization 确认可达。'
        exit $script:ExitFail
    }
    Write-Ok "发行版已注册：$Distribution"

    Write-Host "    步骤 b：导出为 tar（$InstallRoot）"
    $r = Invoke-Wsl --export $Distribution $tar
    if (-not (Test-Path $tar)) {
        Write-Err "导出失败：未生成 $tar（exit=$($r.ExitCode)）"
        if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }
        Write-Host "    发行版仍留在默认位置（C 盘），可手工执行：wsl.exe --export $Distribution `"$tar`""
        exit $script:ExitFail
    }
    $tarMB = [math]::Round((Get-Item $tar).Length / 1MB, 1)
    Write-Ok "导出完成：$tar（$tarMB MB）"

    Write-Host '    步骤 c：注销默认位置的实例（释放 C 盘）'
    # ⚠️ 这是**删除**操作。仅在 tar 已确认生成后执行（上方已校验），否则会丢发行版。
    $r = Invoke-Wsl --unregister $Distribution
    Write-Host "    （exit=$($r.ExitCode)；此步不可回滚，tar 已备份）"

    Write-Host "    步骤 d：从 tar 导入到 $target"
    $r = Invoke-Wsl --import $Distribution $target $tar
    # 双重校验 2：导入目标必须真的出现 ext4.vhdx
    if (-not (Test-Path $vhdx)) {
        Write-Err "导入失败：未生成 $vhdx（exit=$($r.ExitCode)）"
        if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }
        Write-Host "    tar 仍保留在：$tar —— 可手工重试：wsl.exe --import $Distribution `"$target`" `"$tar`""
        exit $script:ExitFail
    }
    Remove-Item $tar -Force -ErrorAction SilentlyContinue
    $sizeGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
    Write-Ok "发行版已落位：$target（ext4.vhdx $sizeGB GB）"
}

# ---------------------------------------------------------------- 收尾自检
Write-Step '安装结果自检'
$r = Invoke-Wsl --status
if ($r.Text.Trim()) {
    $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "    $($_.Trim())" }
}
$r = Invoke-Wsl -l -v
if ($r.Text.Trim()) {
    $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "    $($_.Trim())" }
}

# ⚠️ **收尾自检必须硬失败**，不能只 WARN 后返回 0。
#    2026-10-15 实测教训：脚本曾在此处只打一条 WARN 就 `exit 0`，
#    导致「四步落盘全部失败」被误读为「安装成功」。凡终态校验不过，一律以失败退出。
if (-not (Test-Path $vhdx)) {
    Write-Err "终态校验失败：未找到 $vhdx"
    if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }
    Write-Host '    ⇒ **本次安装未成功**。请按上方提示处理后重跑本脚本（不要据「已执行完成」进入下一步）。'
    exit $script:ExitFail
}
$sizeGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
Write-Ok "虚拟磁盘：$vhdx（$sizeGB GB）"

# 发行版是否真的注册且为 WSL2
# ⚠️ 正则须匹配**数据行的行尾版本号**，不能匹配表头的 'VERSION' 列名
#    （`VERSION\s+2` 会去匹配表头 ⇒ 恒为真、形同虚设）。
#    另须容忍行首的 `*`（标记默认发行版）——它是特殊字符，须显式纳入字符类。
$pattern = '(?m)^\s*\*?\s*\S+\s+\S+\s+2\s*$'
$rL = Invoke-Wsl -l -v
$hasV2 = $rL.Text -match $pattern
if ($hasV2) {
    Write-Ok '发行版清单中确认存在 VERSION 2 的实例'
} else {
    Write-Warn "发行版清单中未见 'VERSION 2'（exit=$($rL.ExitCode)）——请人工确认实际版本"
}

Write-Host ''
Write-Host '下一步：'
Write-Host '  1) 进发行版并初始化用户：'
Write-Host "       wsl.exe -d $Distribution"
Write-Host '  2) 在 Linux 侧执行 provision-vllm.sh 安装 vLLM 并起服务'
Write-Host '  3) 按 OPS-002 §4 核对受约束解码字段与引擎版本是否匹配'
exit $script:ExitOk
