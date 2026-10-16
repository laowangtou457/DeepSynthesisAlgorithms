<#
.SYNOPSIS
    从**手动下载的发行版 tar** 导入到指定盘（WSL2 落盘）。

.DESCRIPTION
    为什么单独一个脚本（2026-10-15 实测背景）：

    `install-wsl2.ps1` 的发行版安装依赖 `wsl --install <Distro>` 从 **Microsoft Store 通道**下载，
    该通道在部分网络环境／组件刚启用未重启时会**静默失败**（退出码仍为 0，但什么都没装）。
    本脚本改走**手工路径**，成功率与可观测性都更高：

        ① 浏览器下载发行版 tar（Ubuntu 官方 cloud-images 提供，~600 MB）；
        ② 本脚本校验 tar 有效性（不是空文件、不是错误页）；
        ③ `wsl --import` 落到指定盘（默认 E 盘，避开 C 盘）；
        ④ **逐项校验落盘结果**（`ext4.vhdx` 是否生成、清单是否含 VERSION 2）。

    下载地址（官方、无需登录）：
        https://cloud-images.ubuntu.com/wsl/releases/  → 选 `Ubuntu-24.04` 的 `.wsl` 或 rootfs tar
        https://learn.microsoft.com/windows/wsl/install-manual#download-distributions

.PARAMETER TarPath
    已下载的发行版包路径（`.tar` / `.tar.gz` / `.wsl` 三者皆可）。
    **可省略** —— 留空则自动扫描 `$MirrorDir` 下最大的镜像包。

.PARAMETER InstallRoot
    落盘根目录（**务必非系统盘**）。默认 `E:\wsl`。

.PARAMETER DistributionName
    注册名（可与文件名不同）。留空则取 tar 文件名的前缀。

.PARAMETER MirrorDir
    镜像存放目录。默认 `E:\distros`（**工程目录之外** —— 第三方二进制不入 Git，
    依据见该目录下的 `README-发行版镜像存放说明.md`）。

.PARAMETER Force
    目标目录已存在时，先 `wsl --unregister` 再导入（**不可回滚**）。

.EXAMPLE
    # 推荐：镜像放进 E:\distros 后直接跑，无需任何参数
    .\import-distro.ps1

.EXAMPLE
    # 或显式指定文件
    .\import-distro.ps1 -TarPath "E:\distros\ubuntu-24.04-server-cloudimg-amd64-root.tar.gz"

.NOTES
    ⚠️ 本文件**必须保留 UTF-8 BOM**（Windows PowerShell 5.1 按 ANSI 解码 `.ps1`，详见 install-wsl2.ps1 头注）。
    ⚠️ 行尾 LF。
    Exit code：0 = 成功；2 = 非管理员；4 = 失败。
#>

[CmdletBinding()]
param(
    [string]$TarPath = '',            # 留空 = 自动扫描 $MirrorDir；仍无则自动下载
    [string]$InstallRoot = 'E:\wsl',  # 发行版实例落盘位置（勿放 C 盘）
    [string]$DistributionName = '',
    [string]$MirrorDir = 'E:\distros',  # 镜像存放目录（工程目录之外，见该目录 README）
    [string]$Flavor = 'Ubuntu-24.04',  # 自动下载时的发行版规格
    [switch]$NoDownload,              # 禁止自动下载（只用手工放好的包）
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$script:ExitOk = 0; $script:ExitNotAdmin = 2; $script:ExitFail = 4

function Write-Step { param([string]$Msg) Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Msg) Write-Host "    [OK] $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "    [WARN] $Msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$Msg) Write-Host "    [ERROR] $Msg" -ForegroundColor Red }

function Invoke-Wsl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$WslArgs)
    # ⚠️ 与 Invoke-Native 同一纪律：调用期间把 EAP 降为 Continue。
    #    本脚本全局设了 `$ErrorActionPreference = 'Stop'`，而 PS 5.1 会把原生程序写入 stderr 的
    #    **每一行**都升级为终止性 NativeCommandError ⇒ 只要 wsl.exe 往 stderr 写一行，
    #    就会被下面的 catch 接走，于是**真实的 wsl 报错被替换成「wsl.exe 未能启动」**，
    #    错误信息指向完全错误的方向（明明启动了、只是参数或状态不对）。
    #    降级后：stderr 照常收进 Text 供上层打印，LaunchFailed **只表示真正的进程启动失败**
    #    （wsl.exe 不在 PATH / 被安全策略拦截）。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = & wsl.exe @WslArgs 2>&1
        $code = $LASTEXITCODE
        $text = (($raw | ForEach-Object { ($_ -replace "`0", '') }) -join "`n")
        return [pscustomobject]@{ ExitCode = $code; Text = $text; LaunchFailed = $false }
    } catch {
        return [pscustomobject]@{
            ExitCode = 1
            Text = "wsl.exe 未能启动：$($_.Exception.Message)"
            LaunchFailed = $true
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

# 统一调用外部程序：**必须**用它，不能直接 `& exe ... 2>&1`。
# ⚠️ 2026-10-15 实测坑（import-distro.ps1 首轮实跑即被此坑截断报错信息）：
#    本脚本开头设了 `$ErrorActionPreference = 'Stop'`，而 PowerShell 5.1 在 Stop 模式下
#    **把原生程序写到 stderr 的每一行都升级为终止性错误**（NativeCommandError）。
#    后果：Python 抛 traceback 时，只输出第一行 `Traceback (most recent call last):`
#    就中断了，**真正的原因（后面几行）永远看不到** —— 极难排查。
#    ⇒ 故此处**临时降级为 Continue**，把 stdout+stderr 一并当数据收集起来，跑完再还原。
function Invoke-Native {
    param([string]$Exe, [string[]]$Argv)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Argv 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return [pscustomobject]@{
        ExitCode = $code
        Lines    = @($out | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    }
}

# ---------------------------------------------------------------- 0. 前置
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err '需要管理员权限（wsl --import 涉及系统级注册）。请以管理员身份重开 PowerShell。'
    exit $script:ExitNotAdmin
}
Write-Ok '管理员权限已具备'

# ---- 重启前置检查（必须在校验 TarPath 之前，否则占位符/错路径会先抛无关异常）----
# ⚠️ 2026-10-15 实测教训：组件启用后未重启时，`wsl --install` 会**静默失败**
#    （退出码 0、什么都没装）。若不先拦，用户只会看到一堆莫名其妙的报错，
#    而真正的原因是「还没重启」。故此处**优先**检查并给出明确指令。
Write-Step '0/3 前置检查：组件状态与重启'
$rebootPending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
                 (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime

$featState = @{}
foreach ($f in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
    $r = Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue
    $featState[$f] = if ($r) { [string]$r.State } else { 'Unknown' }
}
Write-Host "    上次启动 : $bootTime"
Write-Host "    WSL 组件: $($featState['Microsoft-Windows-Subsystem-Linux'])"
Write-Host "    虚拟机平台: $($featState['VirtualMachinePlatform'])"

$notEnabled = @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform') |
              Where-Object { $featState[$_] -ne 'Enabled' }
if ($notEnabled.Count -gt 0) {
    Write-Err "组件未启用：$($notEnabled -join ' , ')"
    Write-Host '    请先运行： powershell -ExecutionPolicy Bypass -File .\install-wsl2.ps1'
    exit $script:ExitFail
}
Write-Ok '两个必需组件均已启用'

if ($rebootPending) {
    Write-Err 'Windows 尚未重启，虚拟化平台未加载 —— wsl 现在无法真正启动。'
    Write-Host ''
    Write-Host '    ==> **请先重启 Windows**，然后重跑本脚本。'
    Write-Host '      [未重启即强行导入必然失败：wsl.exe 会返回错误文本但退出码仍为 0，'
    Write-Host '       即「假成功」（2026-10-15 首轮实跑即栽在此处）]'
    Write-Host ''
    Write-Host '    重启命令（保存工作后执行）： shutdown /r /t 0'
    Write-Host ''
    Write-Host '    若重启后仍失败，再走「手动下载 tar」路径：'
    Write-Host '      https://cloud-images.ubuntu.com/wsl/releases/'
    exit $script:ExitFail
}
Write-Ok '无待重启标记，系统状态就绪'

# ---- 参数解析（放在前置之后，避免占位符先抛「路径非法字符」）----
Write-Step '1/3 校验发行版包'

# ① 占位符拦截：文档里的示例被原样粘贴，是最常见的误操作（2026-10-15 实际发生）
if ($TarPath -match '[<>|:*?"]' -or $TarPath -match '路径$|请替换|例如|示例') {
    Write-Err '检测到占位符内容，未按文档示例原样执行。'
    Write-Host "    收到的参数：$TarPath"
    Write-Host ''
    Write-Host '    ==> 正确用法（两种，任选其一）：'
    Write-Host '       [A] 什么都不传 —— 自动扫描 E:\distros 下的镜像：'
    Write-Host '           powershell -ExecutionPolicy Bypass -File .\import-distro.ps1'
    Write-Host '       [B] 指定真实文件路径：'
    Write-Host '           powershell -ExecutionPolicy Bypass -File .\import-distro.ps1 -TarPath "E:\distros\<实际文件名>"'
    exit $script:ExitFail
}

# ② 未指定则自动扫描镜像目录（工程目录之外，见 E:\distros\README）
if ([string]::IsNullOrWhiteSpace($TarPath)) {
    $null = New-Item -ItemType Directory -Force -Path $MirrorDir
    $cands = @(Get-ChildItem $MirrorDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in '.tar', '.gz', '.wsl' } |
        Sort-Object Length -Descending)

    if ($cands.Count -eq 0) {
        # ---- 自动下载（2026-10-15 新增）----
        # ⚠️ 本机 GitHub HTTPS 走代理 127.0.0.1:7890 且**间歇性失败**
        #    （实测 `wsl --install` 报 `WININET_E_CONNECTION_RESET`；
        #      同一 URL 用 Invoke-WebRequest 复测 6/6 成功 ⇒ 抖动而非不通）。
        #    故此处**多源 + 逐源重试**，不把失败归因于单一站点。
        if ($NoDownload) {
            Write-Err "$MirrorDir 下无镜像，且已指定 -NoDownload"
            Write-Host "    请手工下载后放入 $MirrorDir ："
            Write-Host '      https://cloud-images.ubuntu.com/wsl/releases/'
            exit $script:ExitFail
        }
        Write-Step '1b/3 自动下载发行版镜像'
        $tarFile = Join-Path $MirrorDir "$Flavor-amd64.wsl"
        # ✅ 地址取自微软官方 WSL 发行版清单（`DistributionInfo.json`，2026-10-15 实测可达，
        #    HEAD 返回 200 / **371 MB**）。**Ubuntu 官方只提供 `.wsl` 形态**——
        #    实测 `cloud-images.ubuntu.com/wsl/releases/...rootfs.tar.gz` 等直链**全部 404**，
        #    不要凭猜测拼路径。脚本会自动把 `.wsl` 规整成 raw tar 再导入。
        $sources = @(
            'https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl',
            'https://cdimages.ubuntu.com/releases/24.04.5/release/ubuntu-24.04.5-wsl-amd64.wsl'
        )
        $got = $false
        foreach ($u in $sources) {
            for ($try = 1; $try -le 3; $try++) {
                # ⚠️⚠️ **PowerShell `-f` 的占位符是 0 基**（`{0}` 起），**不是** 1 基。
#    2026-10-15 实测踩坑：曾写成 `("源 {1} (第 {2}/3 次)" -f $file, $try)`（2 个参数却用了 {1}{2}）
#    ⇒ 运行时抛「在设置字符串格式时出错: 索引(从零开始)必须大于或等于零，且小于参数列表的大小」，
#    **且 PowerShell 解析器查不出语法错误**（静态校验全绿，只有运行时才炸）。
#    ⇒ 改后为 `("源 {0} (第 {1}/3 次)" -f $file, $try)`。
#    排查手法：用等价表达式单跑一行即可复现/确认，勿靠肉眼。
Write-Host ("    源 {0}  (第 {1}/3 次)" -f $u.Split('/')[-1], $try)
                $tmpFile = "$tarFile.part"
                try {
                    # ⚠️ 传输方式的两次排除（均为**实测**，不是偏好）：
                    #   ① `WebClient.DownloadFile` —— 被本机安全策略拦截
                    #      （「Download cradle using WebClient detected」）；
                    #   ② `Start-BitsTransfer` —— 亦被拦截
                    #      （「BITS transfer can download files silently in background」）。
                    #    故用 `Invoke-WebRequest`（实测同一 URL **6/6 成功**）。
                    # ⚠️ 代理抖动会抛「基础连接已经关闭」，故逐次 try/catch 后重试并退避。
                    Invoke-WebRequest -Uri $u -OutFile $tmpFile -TimeoutSec 900 -UseBasicParsing -ErrorAction Stop
                    Move-Item $tmpFile $tarFile -Force
                    $sz = [math]::Round((Get-Item $tarFile).Length / 1MB, 1)
                    Write-Ok "下载完成：$tarFile（$sz MB）"
                    $got = $true
                    break
                } catch {
                    $m = ($_.Exception.Message -replace "`r|`n", ' ')
                    if ($m.Length -gt 60) { $m = $m.Substring(0, 60) }
                    Write-Warn "失败：$m"
                    Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds (3 * $try)
                }
            }
            if ($got) { break }
        }
        if (-not $got) {
            Write-Err '全部镜像源均下载失败。'
            Write-Host '    可能原因与对策：'
            Write-Host '      ① **代理不稳定**（本机 WinINET 代理 127.0.0.1:7890 实测间歇失败）'
            Write-Host '         —— 请确认代理软件在运行且端口 7890 可连，然后重跑本脚本；'
            Write-Host '      ② 也可**用浏览器手工下载**后放入该目录，重跑本脚本即可（会自动识别）：'
            Write-Host "           $MirrorDir"
            Write-Host '         https://cloud-images.ubuntu.com/wsl/releases/'
            exit $script:ExitFail
        }
        Write-Step '1/3 校验发行版包'
        $TarPath = $tarFile
    } else {
        if ($cands.Count -gt 1) {
            Write-Warn "$MirrorDir 下有 $($cands.Count) 个候选包，取**最大**的一个："
            $cands | ForEach-Object {
                Write-Host ("      {0,8} MB  {1}" -f [math]::Round($_.Length / 1MB, 1), $_.Name)
            }
        }
        $TarPath = $cands[0].FullName
        Write-Ok "自动选中镜像：$TarPath"
    }
}

if (-not (Test-Path $TarPath)) {
    Write-Err "文件不存在：$TarPath"
    Write-Host '    下载地址（官方，无需登录）：'
    Write-Host '      https://cloud-images.ubuntu.com/wsl/releases/'
    Write-Host '      https://learn.microsoft.com/windows/wsl/install-manual#download-distributions'
    exit $script:ExitFail
}
$item = Get-Item $TarPath
$sizeMB = [math]::Round($item.Length / 1MB, 1)
Write-Host "    文件: $($item.FullName)"
Write-Host "    大小: $sizeMB MB"
if ($item.Length -lt 100MB) {
    Write-Err "文件仅 $sizeMB MB，明显过小 —— 多半下载的是错误页而非发行版包（Ubuntu 24.04 WSL 镜像约 **370 MB**）。"
    exit $script:ExitFail
}

# ---- 结构有效性校验 ----
# ⚠️⚠️ **`.wsl` 的真实格式与直觉相反**（2026-10-15 实测，勿按传闻改回 zip 写法）：
#    取自 `https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl` 的这个包，
#    虽然扩展名叫 `.wsl`，但**文件头是 `1f 8b 08`（gzip）**，`zipfile.is_zipfile()` 直接
#    返回 False —— 它其实就是**一个 gzip 压缩的 rootfs tar**（顶层即为 `bin/ etc/ dev/ usr/`），
#    **不是**微软规范里那种「zip 容器 + manifest.json + install.tar.gz」。
#    凡按「zip 容器」写的解包代码都会在此抛 `BadZipFile: File is not a zip file`。
#    ⇒ 本脚本对两种形态都兼容：**先判 zip，否则按 gzip / 裸 tar 处理**。
#
# ⚠️ 另：`wsl --import` 只吃 **raw tar**，不吃 gzip / zip
#    ⇒ 必须先在本地解成 raw tar 再导入。
#
# ⚠️ **Windows 自带 `tar.exe` 读不了 zip**（实测报「This does not look like a tar archive」，
#    尽管底层是 libarchive）；`Add-Type`＋`System.IO.Compression` 亦被本机安全策略拦截
#    ⇒ 压缩容器一律交给 **Python** 处理（已确认可用）。
$pyCmd = $null
foreach ($c in @('python', 'python3', 'py')) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $pyCmd = $c; break }
}
if (-not $pyCmd) {
    Write-Err '未找到 Python —— 展开 `.wsl` 容器与校验 raw tar **都需要它**。'
    Write-Host '    处置：安装 Python 并加入 PATH，或手工把 `.wsl` 展开后放 raw tar 进 E:\distros。'
    exit $script:ExitFail
}

if ($item.Extension -eq '.wsl') {
    $inner = Join-Path $MirrorDir "$Flavor-rootfs.tar"
    if (Test-Path $inner) {
        Write-Ok "已存在解包好的 tar，跳过解包：$inner"
    } else {
        Write-Host '    展开镜像容器（gzip / zip → raw tar，约 1.2 GB，需 1~2 分钟）...'
        $py = @'
import sys, os, gzip, zipfile, tarfile, shutil, tempfile

src, dst = sys.argv[1], sys.argv[2]


def to_raw_tar(path_in, path_out):
    """gzip 流 / 裸 tar -> raw tar"""
    with open(path_in, 'rb') as f:
        magic = f.read(2)
    if magic == b'\x1f\x8b':
        total = 0
        with gzip.open(path_in, 'rb') as fi, open(path_out, 'wb') as fo:
            while True:
                chunk = fi.read(8 * 1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
                total += len(chunk)
                if total % (128 * 1024 * 1024) == 0:
                    # ⚠️ 进度信息刻意用 **纯 ASCII**：它走 stderr，若掺中文会受
                    #    终端代码页（cp936 / UTF-8）影响而乱码。功能不受影响，
                    #    但没必要留这个观测隐患。
                    sys.stderr.write('      ... decompressed %d MB\n' % (total // 1048576))
        return
    shutil.copyfile(path_in, path_out)


def from_zip_container(path_in, path_out):
    """兼容真正 zip 容器形态的 .wsl（MS Store 通道多为这种）"""
    tmpdir = tempfile.mkdtemp(prefix='unwsl_', dir=os.path.dirname(os.path.abspath(path_out)))
    try:
        with zipfile.ZipFile(path_in) as z:
            z.extractall(tmpdir)
        pick = None
        for suffix in ('.tar', '.tar.gz', '.tgz'):
            hits = []
            for root, _dirs, files in os.walk(tmpdir):
                for name in files:
                    if name.lower().endswith(suffix):
                        hits.append(os.path.join(root, name))
            if hits:
                pick = max(hits, key=os.path.getsize)
                break
        if not pick:
            sys.exit('NO_TAR_IN_ZIP: zip container has no tar member')
        to_raw_tar(pick, path_out)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if zipfile.is_zipfile(src):
    from_zip_container(src, dst)
else:
    to_raw_tar(src, dst)

if not tarfile.is_tarfile(dst):
    sys.exit('NOT_A_TAR: unpacked result is not a valid tar archive')

# 用带前缀的标记行回传结果 —— 比「取最后一行」更稳：
# stdout 被管道接管时是块缓冲、stderr 是行缓冲，两者顺序不保证，靠行序会踩坑。
print('RESULT=' + dst)
sys.stdout.flush()
'@
        $pyFile = Join-Path $env:TEMP '_unpack_wsl.py'
        [IO.File]::WriteAllText($pyFile, $py, (New-Object Text.UTF8Encoding($false)))
        try {
            # ⚠️ 必须传 **两个** 参数！首轮实跑即栽在此处：只传了 $TarPath，
            #    Python 里 `sys.argv[2]` 越界 → IndexError → traceback。
            $r = Invoke-Native $pyCmd @($pyFile, $TarPath, $inner)
            if ($r.ExitCode -ne 0) {
                Write-Err "镜像展开失败（python 退出码 $($r.ExitCode)）："
                if ($r.Lines.Count -eq 0) { Write-Host '      （python 无输出）' }
                $r.Lines | ForEach-Object { Write-Host "      $_" }
                Write-Host '    NO_TAR_IN_ZIP / NOT_A_TAR ⇒ 下载不完整，或该文件不是发行版镜像。'
                exit $script:ExitFail
            }
            $found = $null
            foreach ($ln in $r.Lines) {
                if ($ln -like 'RESULT=*') { $found = $ln.Substring(7) }
                else { Write-Host "  $ln" }
            }
            if (-not $found -or -not (Test-Path $found)) {
                Write-Err "展开产物不可用：$found"
                exit $script:ExitFail
            }
            Write-Ok "展开完成：$found（$([math]::Round((Get-Item $found).Length/1MB,1)) MB）"
        } finally {
            Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $inner)) {
        Write-Err "未找到 raw tar：$inner"
        exit $script:ExitFail
    }
    $TarPath = $inner   # 后续校验与导入都用解出的 raw tar
    $item = Get-Item $TarPath
}

# ---- raw tar 校验：**以 Python 为准，`tar.exe` 仅作参考** ----
# ⚠️⚠️⚠️ 2026-10-15 实测纠错（**本次实跑栽在此处，属判据错误而非镜像问题**）：
#     **不能拿 `tar.exe` 的退出码当完整性判据。**
#     对 Ubuntu 官方镜像解出的这个 tar，`tar.exe -tf` **完整列出了 49188/49190 条**，
#     却仍返回**退出码 1**，stderr 只抱怨：
#         tar.exe: Archive entry has empty or unreadable filename ... skipping
#         tar.exe: Error exit delayed from previous errors
#     成因：归档里有 **2 个名字异常的条目**（Ubuntu 打包侧遗留，名字里含**字面 `\x2d`**
#     的 systemd unit）＋ 1 个含非 ASCII（`ő`）的证书软链。归档本身**结构完好**：
#     49190 成员、末尾 2048 字节全零（正确的 EOA）、总长是 10240 的整数倍。
#     ⇒ 把退出码当门禁，**好镜像会被判为「文件损坏」并被拒绝导入**。
#     ⇒ 改用 **Python（tarfile）** 做权威校验：能全量扫出 49190 成员，并**确认是 rootfs 布局**
#        （顶层必须有 `etc` / `usr`）——这才是校验真正该问的问题。
#     ⇒ `tar.exe` 降级为**参考列表**：退出码非 0 **只提示、不拦截**。
#        （另：也不能写 `tar.exe -tf ... | Select-Object -First 5` —— `-First` 会提前掐断管道，
#          tar.exe 收到 broken pipe 后**可能**返回非 0，又是一个假失败源。）
$pyCheck = @'
import sys, tarfile

src = sys.argv[1]
try:
    tf = tarfile.open(src)
except Exception as exc:
    sys.exit('NOT_A_TAR: %s' % exc)

count = 0
first = []
roots = set()
odd = 0
with tf:
    for m in tf:
        count += 1
        if len(first) < 5:
            first.append(m.name)
        name = m.name
        if name.startswith('./'):
            name = name[2:]
        roots.add(name.split('/')[0])
        if '\\x' in m.name:
            odd += 1

if count == 0:
    sys.exit('EMPTY_TAR: no members')

missing = [r for r in ('etc', 'usr') if r not in roots]
if missing:
    sys.exit('NOT_A_ROOTFS: missing top-level %s' % ','.join(missing))

print('members       = %d' % count)
print('first entries = %s' % ' / '.join(first))
print('odd names     = %d   (official-image quirk, harmless)' % odd)
print('RESULT=%d' % count)
'@
$pyCheckFile = Join-Path $env:TEMP '_check_tar.py'
[IO.File]::WriteAllText($pyCheckFile, $pyCheck, (New-Object Text.UTF8Encoding($false)))
try {
    $rc = Invoke-Native $pyCmd @($pyCheckFile, $TarPath)
    if ($rc.ExitCode -ne 0) {
        Write-Err "发行版 tar 结构校验未通过（python 退出码 $($rc.ExitCode)）：$TarPath"
        if ($rc.Lines.Count -eq 0) { Write-Host '      （python 无输出）' }
        $rc.Lines | ForEach-Object { Write-Host "      $_" }
        Write-Host '    NOT_A_ROOTFS ⇒ 顶层缺 `etc` / `usr`，多半下错了包（要的是 **rootfs** 镜像）。'
        exit $script:ExitFail
    }
    $rc.Lines | Where-Object { $_ -notlike 'RESULT=*' } | ForEach-Object { Write-Host "      $_" }
    Write-Ok 'tar 结构有效：Python 全量扫描通过，且为 rootfs 布局（含 etc/ usr/）'
} finally {
    Remove-Item $pyCheckFile -Force -ErrorAction SilentlyContinue
}

$tarCmd = Get-Command tar.exe -ErrorAction SilentlyContinue
if (-not $tarCmd) {
    Write-Warn '未找到 tar.exe（Windows 10 1803+ 自带），跳过参考列表'
} else {
    $t = Invoke-Native 'tar.exe' @('-tf', $TarPath)
    if ($t.ExitCode -eq 0) {
        Write-Ok "tar.exe 参考列表正常（$($t.Lines.Count) 条）"
    } else {
        Write-Warn "tar.exe 返回 $($t.ExitCode)（列表 $($t.Lines.Count) 条）—— 官方镜像的已知现象，**非损坏**，不拦截"
    }
}

# ---------------------------------------------------------------- 2. 导入
Write-Step "2/3 导入到 $InstallRoot"
$null = New-Item -ItemType Directory -Force -Path $InstallRoot
if ([string]::IsNullOrWhiteSpace($DistributionName)) {
    $DistributionName = ($item.BaseName -split '[-_.]')[0]
}
$target = Join-Path $InstallRoot $DistributionName
$vhdx = Join-Path $target 'ext4.vhdx'

if (Test-Path $target) {
    if (-not $Force) {
        Write-Err "目标已存在：$target"
        Write-Host '    确认要覆盖时加 -Force（**会先 unregister，不可回滚**）。'
        exit $script:ExitFail
    }
    Write-Warn "目标已存在，按 -Force 先注销 $DistributionName（**删除操作**）"
    $r = Invoke-Wsl --unregister $DistributionName
    Write-Host "    （exit=$($r.ExitCode)）"
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "    wsl --import $DistributionName `"$target`" `"$($item.FullName)`""
$r = Invoke-Wsl --import $DistributionName $target $item.FullName
if ($r.Text.Trim()) { $r.Text.Trim() -split "`n" | ForEach-Object { Write-Host "      [$($_.Trim())]" } }

# ---------------------------------------------------------------- 3. 终态校验
Write-Step '3/3 终态校验（**不靠退出码，靠产物**）'
if ($r.LaunchFailed) {
    Write-Err $r.Text
    exit $script:ExitFail
}
if (-not (Test-Path $vhdx)) {
    Write-Err "导入失败：未生成 $vhdx（exit=$($r.ExitCode)）"
    Write-Host '    常见原因：'
    Write-Host '      ① 组件启用后**尚未重启** → 请重启 Windows 再重跑本脚本；'
    Write-Host '      ② tar 不是 rootfs（缺 ./bin、./etc 等顶层目录）→ 请确认下载的是 **rootfs** 包；'
    Write-Host '      ③ 发行版不兼容（须为 x86_64）。'
    exit $script:ExitFail
}
$sizeGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
Write-Ok "虚拟磁盘已生成：$vhdx（$sizeGB GB）"

$rL = Invoke-Wsl -l -v
if ($rL.Text.Trim()) { $rL.Text.Trim() -split "`n" | ForEach-Object { Write-Host "    $($_.Trim())" } }
$pattern = '(?m)^\s*\*?\s*\S+\s+\S+\s+2\s*$'
if ($rL.Text -match $pattern) {
    Write-Ok '清单中确认存在 VERSION 2 实例'
} else {
    # 导入的实例默认 VERSION 1，需显式转 2
    Write-Warn '未检出 VERSION 2 —— 尝试 `wsl --set-version <name> 2` 转 WSL2'
    $r = Invoke-Wsl --set-version $DistributionName 2
    Write-Host "    （exit=$($r.ExitCode)；转换需数分钟）"
}

Write-Host ''
Write-Ok "导入完成：$DistributionName → $target"
Write-Host '下一步：'
Write-Host "  1) 初始化用户（首次进入需建账号）："
Write-Host "       wsl.exe -d $DistributionName"
Write-Host '  2) 进 Linux 后执行 provision-vllm.sh 安装 vLLM 并起服务'
exit $script:ExitOk
