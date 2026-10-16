#!/usr/bin/env bash
# =============================================================================
# provision-vllm.sh —— WSL2 侧 vLLM 供给与启动（对应任务 T-012 / OPS-002 §4~§6）
#
# 职责边界：只做「装依赖 → 校验权重 → 起服务」。
#   * 不装 WSL（那是 Windows 侧 install-wsl2.ps1 的职责）；
#   * 不下载模型权重（本机权重在 /mnt/e/models，**零拷贝复用**，避免重下 15.2 GB）；
#   * 不做业务判断（参数是否合规由 validate_pack.py 等门禁判，本脚本只管起得来）。
#
# 设计纪律：
#   1. **凡未实测的数值一律标注 <待实测>**，不编造显存/吞吐数字；
#   2. 幂等：重复执行不报错，已装即跳过；
#   3. 失败即退出（set -euo pipefail），绝不「装不上就跳过继续」；
#   4. 引擎版本**显式打印**——受约束解码字段与版本强相关（见 OPS-002 §4.3）。
#
# 用法：
#   bash provision-vllm.sh              # 安装 + 用默认参数起服务
#   bash provision-vllm.sh --serve-only # 跳过安装，仅按现参数起服务
#   bash provision-vllm.sh --speedtest  # 实测各 pip 源吞吐（快测 + 持续测两列，选源用；不装不启动）
#
# 常用环境变量：
#   PIP_INDEX=cn|ustc|huawei|aliyun|<完整URL>   指定 pip 源（见下方 PIP_INDEX 注释）
#   PIP_PROXY=http://<宿主IP>:7890              pip 走代理（WSL 内用宿主代理，见 OPS-002 §3.7.1）
#   PY_BIN=~/vllm-venv/bin/python              指定解释器。**可省略**（2026-10-16 起）：
#                                              未指定时自动探测 ~/vllm-venv，探不到才回落系统
#                                              python3；显式传参永远优先（可强制覆盖）
#   PIP_RESUME_RETRIES=5                       大轮子断流后**续传**次数（pip>=23.1，强烈建议保留）
#   ALLOW_NO_TOOLCHAIN=1                       缺 ninja/g++ 时**不中断**，改用 PyTorch 原生采样
#                                              （默认缺工具链直接失败：vLLM 会崩在 flashinfer JIT 且日志为空）
#   REQUIRE_FLASHINFER_SAMPLER=1                CUDA 编译器/头文件版本不一致时**不再响亮降级**，
#                                              改为直接失败（默认行为见下方「CUDA 版本一致性」段）
#
# ⚠️ 选源只看 `--speedtest` 的**持续**列，不要看「快测」列 —— 短窗读数会系统性高估（见下方注释）。
# =============================================================================
set -euo pipefail

# ------------------------------------------------------------------ 可调参数
MODEL_PATH="${MODEL_PATH:-/mnt/e/models/Qwen2.5-7B-Instruct}"
MODEL_NAME="${MODEL_NAME:-Qwen2.5-7B-Instruct}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
#: max-model-len 须 ≥「最长分段提示词 + 8192 输出」。
#: ★ **已实测（2026-10-15，DEV-20261015-014 / `ISSUE-032`）**：最长分段＝`storyboard` 段，
#:   其完整渲染 prompt ＝ **14473 tokens**（30252 字符；模板正文 24438 ＋ 上游 `script_json` 5814，
#:   经引擎自身 `/tokenize` 精确计数）⇒ 所需窗口 ≥ 14473 + 8192 = **22665**。
#:   **原值 16384 不够**（只剩 1911 输出预算，storyboard 段被引擎入口 400 拒收）。
#:   取 **32768**：Qwen2.5-7B-Instruct **原生支持**该长度（无需 YaRN）。
#: ⚠️ **提窗不额外占显存**——KV 池容量由 `gpu_memory_utilization` 决定（实测 88,032 tokens），
#:   与 max_model_len 无关；代价是**满长度并发**由 5.37x（@16384）降至约 **2.68x**（@32768）。
#: ⚠️ 沿用 16384 前请先确认 storyboard 段能过（否则主链第 3 段必挂）。
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"     # 并发目标 10（SYS-015）留 1.6 倍余量 <待实测校准>
DTYPE="${DTYPE:-bfloat16}"             # T-010「不走量化」：BF16 全量
ENFORCE_EAGER="${ENFORCE_EAGER:-0}"    # 1 = 不用 CUDA Graph（显存紧张/OOM 排查时开）
#: pip 索引源。留空 = pip 官方默认（pypi.org）。
#: 也可用简写（由 resolve_pip_index 展开）：cn / tencent / ustc / huawei / aliyun / tuna。
#: ⚠️ vLLM ＋ torch ＋ CUDA 运行库轮子合计约 **6~8 GB** ⇒ **源选错就是「2 分钟」和「4 小时」的差别**。
#: 本机 2026-10-15 实测（单位 MB/s）。
#: ⚠️⚠️ **同一源在同一天内可差 50 倍以上**（阿里云 0.38 ↔ 21.92；腾讯云 12.33 ↔ 4.43）
#:    ⇒ 「哪个源快」**不是源的固定属性，而是测量时点**，任何写死的排名都会过期。
#:    16:50 一轮短窗取样（仅作参考，不可据此下结论）：
#:      repo.huaweicloud.com 23.05 ／ mirrors.aliyun.com 21.92
#:      pypi.org 15.60 ／ mirrors.cloud.tencent.com 4.43
#: ⚠️ **短窗测速会系统性高估**：10 s 单流取样常只吃到 CDN 的突发额度（令牌桶）。
#:    同一次 pip 安装（阿里云源、累计 2.5 GB / 224 个对象）实测**持续速率仅 0.31 MB/s**
#:    （按缓存文件完成时间逐文件反算，区间 0.20~0.37，**极稳定** ⇒ 更像被限速而非拥塞），
#:    仅为短窗读数的 **1/70**。⇒ 这正是「测速 22 MB/s、实下 0.3 MB/s」的原因。
#: ⇒ 选源只看 `--speedtest` 的**持续**列；两列差距大 = 该源在限速，不要选。
PIP_INDEX="${PIP_INDEX:-}"
#: pip 显式代理（HTTP，形如 http://172.30.224.1:7890 —— 地址必须是**宿主侧 WSL 网卡地址**，
#: 不是 127.0.0.1；见 OPS-002 §3.7.1）。留空则 pip 自动读 http_proxy / https_proxy 环境变量。
PIP_PROXY="${PIP_PROXY:-}"
#: 单包重试次数与超时秒数。轮子很大（torch 单文件约 800 MB），默认值在弱网下容易中途断。
PIP_RETRIES="${PIP_RETRIES:-5}"
PIP_TIMEOUT="${PIP_TIMEOUT:-60}"
#: 大轮子断流后的**续传**次数（pip >= 23.1 才支持 `--resume-retries`）。
#: 值 >0 时，torch/cudnn 这类几百 MB 的轮子在 90% 处断线会**接着下**，而不是从 0 重来 ——
#: 在 0.3 MB/s 量级的链路上这是省下几十分钟的关键开关。
PIP_RESUME_RETRIES="${PIP_RESUME_RETRIES:-5}"
#: --speedtest 取样窗口（秒）：快测（短窗，吃突发额度）＋ 持续测（长窗，看稳态）。
SPEEDTEST_WINDOW="${SPEEDTEST_WINDOW:-8}"
SPEEDTEST_SUSTAIN="${SPEEDTEST_SUSTAIN:-30}"
#: 持续测只对快测前 N 名做（省时间）；设 0 = 全部做。
SPEEDTEST_TOP="${SPEEDTEST_TOP:-2}"
SPEEDTEST=0
SERVE_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --serve-only) SERVE_ONLY=1; shift ;;
    --speedtest) SPEEDTEST=1; shift ;;
    --pip-index) PIP_INDEX="$2"; shift 2 ;;
    --model-path) MODEL_PATH="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --max-model-len) MAX_MODEL_LEN="$2"; shift 2 ;;
    # 用法头部改为按「注释块结束」截取（不写死行号，避免头部增删导致打印错位）
    -h|--help) awk 'NR>1 && /^set -euo/{exit} NR>1{print}' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 64 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    [OK] %s\n' "$*"; }
warn() { printf '    [WARN] %s\n' "$*"; }
die()  { printf '\n\033[31m    [ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- pip 源工具
# 简写 → 完整 simple 索引 URL。留空 = pip 官方默认（不下发 -i）。
resolve_pip_index() {
  case "${1:-}" in
    ''|official|pypi)   printf '' ;;
    cn|tencent)         printf '%s' 'https://mirrors.cloud.tencent.com/pypi/simple/' ;;
    ustc)               printf '%s' 'https://mirrors.ustc.edu.cn/pypi/simple/' ;;
    huawei)             printf '%s' 'https://repo.huaweicloud.com/repository/pypi/simple/' ;;
    aliyun)             printf '%s' 'https://mirrors.aliyun.com/pypi/simple/' ;;
    tuna|tsinghua)      printf '%s' 'https://pypi.tuna.tsinghua.edu.cn/simple/' ;;
    http://*|https://*) printf '%s' "$1" ;;
    *) die "无法识别的 PIP_INDEX：$1
    可用简写：cn(腾讯云) / ustc / huawei / aliyun / tuna / pypi，或直接给完整 simple 索引 URL。" ;;
  esac
}

# 解析源上要取样的对象：torch 索引里任一 manylinux x86_64 轮子。
# 输出：成功 = 绝对 URL；失败 = `-<原因>`（调用方据此区分，不必解析中文）。
# 只用 curl / grep / sed / awk，不依赖 Python。
speedtest_pick_url() {
  local simple="$1" proxy="${2:-}"
  local idx raw idxcode html rel root url curlopts=()
  idx="${simple%/}/torch/"
  # 空数组在 `set -u` 下需用 "${arr[@]+…}" 形式展开，直接写 "${curlopts[@]}" 在旧 bash 会报未绑定
  if [[ -n "$proxy" ]]; then curlopts=(-x "$proxy"); fi
  # 索引页正文 + HTTP 状态码：用哨兵串把状态码从末尾切出来，免建临时文件
  raw=$(curl -sL -A 'curl/8' ${curlopts[@]+"${curlopts[@]}"} --max-time 25 --max-redirs 3 \
        -w '__HTTP__%{http_code}' "$idx" 2>/dev/null || true)
  idxcode="${raw##*__HTTP__}"
  html="${raw%__HTTP__*}"
  if [[ "$idxcode" != "200" ]]; then printf '%s' "-（索引 http=${idxcode:-无响应}）"; return 0; fi
  # ⚠️ 匹配式**不能**写成 `…x86_64\.whl"` —— 真实 href 是 `…x86_64.whl#sha256=…`，
  #    `.whl` 后面还有 `#` 片段；要求紧跟引号会**一条都匹配不到**（实测 0 命中），
  #    于是好源被误报成「索引不可达」。故只匹配到 `.whl` 为止。
  rel=$(printf '%s' "$html" \
        | grep -o 'href="[^"]*manylinux[^"#]*x86_64\.whl' | tail -1 \
        | sed 's/^href="//')
  if [[ -z "$rel" ]]; then printf '%s' '-（索引可读，但未找到 x86_64 轮子）'; return 0; fi
  if [[ "$rel" == http* ]]; then
    url="$rel"
  else
    # 索引里是相对路径（多为 ../../packages/…）⇒ 以 <root> 为基准还原为绝对地址
    root="${simple%/simple/}"
    rel="${rel#../../}"; rel="${rel#../}"
    url="$root/$rel"
  fi
  printf '%s' "$url"
}

# 单次取样：对给定 URL 单流下载 <window> 秒后掐断，返回**该窗口的平均**吞吐。
# ⚠️ 这是**短窗快照**：CDN 的突发额度（令牌桶）会让它显著高于持续速率 —— 不可单独用作选源依据。
# 输出：成功 = 纯数字（MB/s）；失败 = `-<原因>`。
speedtest_fetch() {
  local url="$1" proxy="${2:-}" window="${3:-10}"
  local out code spd curlopts=()
  if [[ -n "$proxy" ]]; then curlopts=(-x "$proxy"); fi
  out=$(curl -sL -A 'curl/8' ${curlopts[@]+"${curlopts[@]}"} --max-time "$window" --max-redirs 3 \
        -o /dev/null -w '%{http_code} %{speed_download}' "$url" 2>/dev/null || true)
  code="${out%% *}"; spd="${out##* }"
  if [[ "$code" != "200" ]]; then printf '%s' "-（http=${code:-无响应}）"; return 0; fi
  awk -v s="$spd" 'BEGIN{printf "%.2f", s/1048576}'
}

# --speedtest：快测（短窗、全部候选源）＋ 持续测（长窗、仅快测前 N 名）。
# 设计意图：10 s 单流会吃到 CDN 突发额度而**系统性高估** —— 2026-10-15 实测曾出现
# 「快测 21.92 MB/s、实际持续 0.31 MB/s」的 **70 倍**落差 ⇒ 只看快测列会选错源。
run_speedtest() {
  local wq="${SPEEDTEST_WINDOW:-8}" ws="${SPEEDTEST_SUSTAIN:-30}" top="${SPEEDTEST_TOP:-2}"
  local -a quick_rows=() sorted=()
  local host key simple url q s line rank penv recs=""
  step "pip 源实测：快测 ${wq}s（全源）＋ 持续测 ${ws}s（快测前 ${top} 名）；不装、不启动、不落盘"
  # 代理会改变结论（同一源走/不走代理可差数十倍）⇒ 下面两行必须如实打印，否则排序看着没道理
  [[ -n "${PIP_PROXY:-}" ]] && echo "  显式代理：$PIP_PROXY"
  # 大小写 4 个变量通常指向同一地址 ⇒ 去重后一行显示
  penv=$(env | grep -i '^https\?_proxy=' | sed 's/^[^=]*=//' | sort -u | tr '\n' ' ' || true)
  [[ -n "$penv" ]] && echo "  环境代理（去重后）：$penv"

  # 三列：主机名|PIP_INDEX 简写|simple 索引 URL。
  # **刻意只用 ASCII 做表格字段** —— printf 的 %-Ns 按字符数（非显示宽度）补齐，
  # 中文全角括号会把整张表挤歪，故中文说明一律放到表外。
  while IFS='|' read -r host key simple; do
    [[ -z "$host" ]] && continue
    url=$(speedtest_pick_url "$simple" "${PIP_PROXY:-}")
    if [[ "$url" == -* ]]; then
      printf '  %-30s %-7s 取材失败 %s\n' "$host" "$key" "${url#-}"; continue
    fi
    q=$(speedtest_fetch "$url" "${PIP_PROXY:-}" "$wq")
    if [[ "$q" == -* ]]; then
      printf '  %-30s %-7s 快测失败 %s\n' "$host" "$key" "${q#-}"; continue
    fi
    quick_rows+=("$q|$host|$key|$url")
  done <<'SOURCES'
pypi.org|pypi|https://pypi.org/simple/
mirrors.cloud.tencent.com|cn|https://mirrors.cloud.tencent.com/pypi/simple/
mirrors.ustc.edu.cn|ustc|https://mirrors.ustc.edu.cn/pypi/simple/
repo.huaweicloud.com|huawei|https://repo.huaweicloud.com/repository/pypi/simple/
mirrors.aliyun.com|aliyun|https://mirrors.aliyun.com/pypi/simple/
pypi.tuna.tsinghua.edu.cn|tuna|https://pypi.tuna.tsinghua.edu.cn/simple/
SOURCES

  if [[ ${#quick_rows[@]} -eq 0 ]]; then
    echo
    warn "所有源均探测失败 —— 先确认 WSL 内出网正常（curl -sI https://pypi.org/simple/）"
    return 0
  fi
  while IFS= read -r line; do sorted+=("$line"); done \
    < <(printf '%s\n' "${quick_rows[@]}" | sort -t'|' -k1 -rn)

  # 持续测：只对快测前 N 名做（`SPEEDTEST_TOP=0` = 全部），省时间
  rank=0
  for line in "${sorted[@]}"; do
    rank=$((rank+1))
    [[ "$top" -gt 0 && "$rank" -gt "$top" ]] && break
    IFS='|' read -r q host key url <<<"$line"
    printf '  … 持续测 %s（%s s）\n' "$host" "$ws"
    s=$(speedtest_fetch "$url" "${PIP_PROXY:-}" "$ws")
    recs="${recs}${host}|${s}"$'\n'
  done

  echo
  echo "  单位 MB/s。衰减 = 1 - 持续/快测；衰减越大说明短窗读数越不可信。"
  printf '  %-30s %-7s %9s %9s %7s  %s\n' "源主机" "PIP_INDEX" "快测${wq}s" "持续${ws}s" "衰减" "判定"
  for line in "${sorted[@]}"; do
    IFS='|' read -r q host key url <<<"$line"
    s=$(printf '%s' "$recs" | awk -F'|' -v L="$host" '$1==L{print $2; exit}')
    if [[ -z "$s" ]]; then
      printf '  %-30s %-7s %9s %9s %7s  %s\n' "$host" "$key" "$q" "—" "—" "（未做持续测）"
    elif [[ "$s" == -* ]]; then
      printf '  %-30s %-7s %9s %9s %7s  %s\n' "$host" "$key" "$q" "失败" "—" "${s#-}"
    else
      printf '  %-30s %-7s %9s %9s %7s  %s\n' "$host" "$key" "$q" "$s" \
        "$(awk -v a="$q" -v b="$s" 'BEGIN{d=(a-b)/a*100; if(d<0)d=0; printf "%.0f%%", d}')" \
        "$(awk -v a="$q" -v b="$s" 'BEGIN{if(a<=0)print "—"; else if(b/a<0.4)print "明显衰减，勿选"; else print "较稳定"}')"
    fi
  done
  echo
  echo "  选源：看【持续】列最高者 —— **测速快 ≠ 下得下来**（短窗会吃掉突发额度）。"
  echo "  用法：PIP_INDEX=<上表 PIP_INDEX 列> bash $0    （也可直接填完整 simple 索引 URL）"
  echo "  提示：换源会让 pip 缓存**按 URL 整体作废**（缓存以完整 URL 为键）——"
  echo "        已下几 GB 时，先比较「重下总量 / 新源持续速率」与「剩余量 / 旧源持续速率」再换。"
  echo "  代理：PIP_PROXY=http://<宿主WSL网卡IP>:7890 bash $0    （见 OPS-002 §3.7.1）"
}

if [[ "$SPEEDTEST" -eq 1 ]]; then
  run_speedtest
  exit 0
fi

# ------------------------------------------------------------------ 0. 环境体检
step "0/5 环境体检"
# ⚠️ /etc/os-release 在精简镜像 / 非 Linux 宿主下可能不存在 —— 故用 if 保护，
#    不可写成 `. /etc/os-release && …`（set -e 下会因缺文件直接中断体检）。
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  echo "    发行版: $(. /etc/os-release && echo "${PRETTY_NAME:-未知}")"
else
  echo "    发行版: 未知（/etc/os-release 不可读）"
fi
echo "    内核  : $(uname -r)"
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  ok "运行于 WSL 发行版 ${WSL_DISTRO_NAME}"
else
  warn "未检测到 WSL 环境变量（WSL_DISTRO_NAME 为空）—— 若非在 WSL2 内运行请确认"
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  die "未找到 nvidia-smi —— WSL2 未直通 GPU。请先按 OPS-002 §3.5 配置 NVIDIA 驱动（Windows 侧须 >= 560.94 / 生产分支）。"
fi
echo "    GPU 探测："
nvidia-smi --query-gpu=name,compute_cap,memory.total,driver_version \
  --format=csv,noheader 2>/dev/null | sed 's/^/      /' || warn "nvidia-smi 查询失败"

# ---------------------------------------------------- 解释器选择（venv 自动优先）
# ⚠️ 现场教训（2026-10-16 实测）：此前的默认值写死为 `python3`，而 venv 方案要求人工
#    **每次**带上 `PY_BIN=~/vllm-venv/bin/python` 前缀。一旦漏写，后果**不是**「提示 venv 未找到」，
#    而是**静默降级成系统解释器**，且**最该做的前置检查整段被跳过**：
#      · 「运行环境归位」整段不成立（PY_ROOT=/usr 下无 pyvenv.cfg）⇒ <venv>/bin 与 CUDA_HOME
#        都不会被归位 ⇒ nvcc 探测不到；
#      · 紧随其后的「CUDA 编译器／头文件版本一致性自检」因取不到 CUDART_VERSION 而**静默跳过**
#        （该段只 warn 不 die）⇒ 恰恰是 2026-10-15 最费时定位出来的那层真因被无声绕过。
#    以上两条只留下极易被忽略的 warning，属于本项目明令禁止的「静默降级」形态 ⇒ 必须从默认值根治。
# 处置：`PY_BIN` 未显式给出时**自动探测**常规 venv 位置；显式传参**永远优先**（可强制覆盖，
#      如 `PY_BIN=/usr/bin/python3 bash $0`）。探测失败才回落 python3，并**响亮提示**。
if [[ -z "${PY_BIN:-}" ]]; then
  PY_BIN=""
  for cand in "${HOME:-/root}/vllm-venv" /root/vllm-venv; do
    [[ -x "$cand/bin/python" ]] || continue
    PY_BIN="$cand/bin/python"
    ok "解释器：未显式指定 PY_BIN，自动探测到 venv ⇒ $PY_BIN"
    break
  done
  if [[ -z "$PY_BIN" ]]; then
    PY_BIN="python3"
    warn "未探测到 ~/vllm-venv —— 回落系统解释器 python3。"
    warn "  若系统侧未装 vllm，第 3 步会失败；请显式指定：PY_BIN=<venv>/bin/python bash \$0"
  fi
fi
command -v "$PY_BIN" >/dev/null 2>&1 || die "未找到 $PY_BIN"
ok "Python: $($PY_BIN --version 2>&1)"

# ---------------------------------------------------- 运行环境归位（venv 方案必做）
# ⚠️ 为什么必须显式做：本脚本用 `exec "$PY_BIN" -m vllm...` 以**绝对路径**调用解释器，
#    这**不会**顺带把 venv 的 bin 目录放进 PATH。而 PATH 是 vLLM 运行期的隐性前置 ——
#    它会 fork 子进程去调外部可执行文件：
#      · flashinfer 的 JIT 编译需要 `ninja`（flashinfer 把 ninja 列为**硬依赖**，
#        pip 会把它装到 <venv>/bin/ninja；系统 /usr/bin 下**没有** ninja）
#      · torch inductor 的 cpp_wrapper / C++ 扩展需要 `g++`
#    PATH 里没有 <venv>/bin ⇒ ninja 找不到 ⇒ JIT 在**产生任何编译输出之前**就失败。
#    现场特征（2026-10-15 本机踩坑）：~/.cache/flashinfer/<ver>/<arch>/flashinfer_jit.log
#    为 **0 字节**、cached_ops/<op>/ 是**空目录**、lock 文件残留 —— 报错信息离真因很远。
# 取解释器的**真实目录**：用 `command -v` + `cd/pwd` 归一化，而不用 readlink。
# 原因：readlink -f 在 MSYS/Git Bash 下可能返回 `C:/...` 这种含冒号的路径，而 PATH 里的
# 冒号是**分隔符** ⇒ 这个条目会被截成两段、静默失效（Linux 侧无此问题，但同一脚本要在
# 两类环境里都可靠）。`cd` + `pwd` 输出的始终是当前 shell 的原生形式。
PY_REAL="$(command -v "$PY_BIN" 2>/dev/null || true)"
PY_DIR=""
case "$PY_REAL" in
  */*) PY_DIR="$(cd "$(dirname "$PY_REAL")" 2>/dev/null && pwd || true)" ;;
esac
PY_ROOT="$(cd "$PY_DIR/.." 2>/dev/null && pwd || true)"
PY_IN_VENV=""
if [[ -n "$PY_ROOT" && -f "$PY_ROOT/pyvenv.cfg" ]]; then
  PY_IN_VENV=1
  export VIRTUAL_ENV="$PY_ROOT"
  case ":$PATH:" in
    *":$PY_DIR:"*) : ;;
    *) export PATH="$PY_DIR:$PATH" ;;
  esac
  ok "venv 归位：VIRTUAL_ENV=$PY_ROOT（$PY_DIR 已加入 PATH）"
  # pip 版 CUDA 工具链也要归位：本机系统里**既无** /usr/local/cuda **也无** /usr/bin/nvcc，
  # 而 JIT 编译需要 nvcc/ptxas；pip 包已把整套 toolkit 铺在 site-packages/nvidia 下
  # （bin/include/lib/nvvm 齐备 ⇒ 就是一个标准 CUDA_HOME）。
  for cand in "$PY_ROOT"/lib/python*/site-packages/nvidia/cu13 \
              "$PY_ROOT"/lib/python*/site-packages/nvidia/cuda_nvcc; do
    [[ -d "$cand/bin" ]] || continue
    case ":$PATH:" in *":$cand/bin:"*) : ;; *) export PATH="$cand/bin:$PATH" ;; esac
    # 只在**未设置**且目录结构完整时兜底设 CUDA_HOME，避免覆盖用户显式配置
    if [[ -z "${CUDA_HOME:-}" && -d "$cand/include" && -d "$cand/lib" ]]; then
      CUDA_HOME="$cand"; export CUDA_HOME
    fi
    ok "CUDA 工具链归位：${CUDA_HOME:-（CUDA_HOME 未设置）}（$cand/bin 已加入 PATH）"
    break
  done
fi

# ---------------------------------------------------- 编译工具链自检
# vLLM 运行期会**真实调用**这些外部程序，缺了会在启动后期才炸（那时报错离真因很远）。
# 缺工具链时**不静默降级**：要么按提示补装，要么显式令 ALLOW_NO_TOOLCHAIN=1 关掉
# flashinfer 采样内核（退化为 PyTorch 原生采样，可用但略慢）。
MISSING_TOOLS=()
command -v ninja >/dev/null 2>&1 || MISSING_TOOLS+=(ninja)
{ command -v g++ >/dev/null 2>&1 || command -v c++ >/dev/null 2>&1; } || MISSING_TOOLS+=(g++)
if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
  if [[ "${ALLOW_NO_TOOLCHAIN:-0}" == "1" ]]; then
    export VLLM_USE_FLASHINFER_SAMPLER=0
    warn "缺编译工具链：${MISSING_TOOLS[*]} —— 按 ALLOW_NO_TOOLCHAIN=1 继续，"
    warn "  已设 VLLM_USE_FLASHINFER_SAMPLER=0（改用 PyTorch 原生采样，可用但略慢）"
  elif [[ "${DRY_RUN:-0}" == "1" ]]; then
    # ⚠️ 干跑**绝不阻断** —— 否则「干跑能不能走到打印启动参数」这件事就验不了（前车之鉴）。
    warn "缺编译工具链：${MISSING_TOOLS[*]}（干跑不阻断，正式跑前必须补）"
    echo "      补装：apt-get update && apt-get install -y ninja-build build-essential"
    echo "      或  ：ALLOW_NO_TOOLCHAIN=1 bash $0   # 退化为 PyTorch 原生采样"
  else
    die "缺编译工具链：${MISSING_TOOLS[*]} —— vLLM 会在启动后期崩在 flashinfer JIT（且日志为空，极难定位）。
    处置（二选一）：
      ① 补装（推荐）：apt-get update && apt-get install -y ninja-build build-essential
      ② 显式降级   ：ALLOW_NO_TOOLCHAIN=1 bash $0   # 关掉 flashinfer 采样内核"
  fi
else
  ok "工具链: ninja=$(command -v ninja)  g++=$(command -v g++ 2>/dev/null || command -v c++)"
fi

# ------------------------------------------- CUDA 编译器 / 头文件 版本一致性自检
# ⚠️ 这是 2026-10-15 实测定位到的**第二层**真因（第一层是 ninja 不在 PATH，见上一段）。
#    flashinfer 捆绑的 CCCL（libcudacxx）里有一条**硬性**校验，编译任何 .cu 都会走到：
#      libcudacxx/include/cuda/std/__cccl/cuda_toolkit.h:41
#      #if !_CCCL_CUDACC_EQUAL((CUDART_VERSION / 1000), (CUDART_VERSION % 1000) / 10)
#        #error "CUDA compiler and CUDA toolkit headers are incompatible, please check your include paths"
#    即 **nvcc 的 major.minor 必须与 CUDA 头文件的 major.minor 严格相等** ——
#    注意是「严格相等」，差一个 minor 也直接 #error。
#    而 pip 的 nvidia-* 轮子**会被解析成不同 minor**。本机实测（venv 内）：
#      nvidia-cuda-nvcc / nvidia-cuda-crt = 13.4.92  ⇒ nvcc 13.4
#      nvidia-cuda-runtime                = 13.0.96  ⇒ cuda_runtime_api.h 的 CUDART_VERSION=13000 ⇒ 13.0
#    成因：元包 cuda-toolkit 13.0.3.0 声明的**自洽组合**本是
#      nvcc/crt ==13.0.88.* ＋ runtime ==13.0.96.*
#    但 tilelang（nvidia-cuda-nvcc>=13.0.48）与 humming-kernels（未钉版）都会把 nvcc 拉到最新 ⇒ 版本漂移。
#    症状（极易误判成别的问题）：vLLM 只报
#      RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
#    而 **`Failed core proc(s): {}` 是空的** —— 真因被打印在它**上方**，必须先 tee 日志才能看到
#    （漏了 tee 就会像本工程 17:36 那次一样「现场无任何日志」，只能靠文件写入痕迹反推）。
# 处置策略**刻意与上面「缺工具链即 die」不同**，理由写在此处以免日后被当成疏漏：
#    flashinfer 采样只是**加速路径**；vLLM 源码 docstring 明写其与原生采样
#    「statistically equivalent」，且**不参与受约束解码**（后者是 logits 处理阶段）。
#    ⇒ 版本不一致时**响亮降级**（把两边版本、后果、根治命令都打印出来），而不是让服务直接起不来。
#    要恢复「严格」：REQUIRE_FLASHINFER_SAMPLER=1
#    要根治（恢复上游声明的自洽组合，推荐）：
#      ~/vllm-venv/bin/pip install "nvidia-cuda-nvcc==13.0.88.*" "nvidia-cuda-crt==13.0.88.*"
#      rm -rf ~/.cache/flashinfer   # 换编译器后必须清掉旧 JIT 缓存，否则可能复用失败产物
CTK_VER=""
CTK_HDR="${CUDA_HOME:-}/include/cuda_runtime_api.h"
if [[ -n "${CUDA_HOME:-}" && -f "$CTK_HDR" ]]; then
  CTK_VER=$(grep -m1 -E '^[[:space:]]*#define[[:space:]]+CUDART_VERSION' "$CTK_HDR" 2>/dev/null \
            | awk '{print $3}' || true)
fi
NVCC_VER=""
if command -v nvcc >/dev/null 2>&1; then
  # nvcc --version 里形如 `Cuda compilation tools, release 13.4, V13.4.92`
  NVCC_VER=$(nvcc --version 2>/dev/null | grep -oE 'release [0-9]+\.[0-9]+' | head -1 \
             | awk '{print $2}' || true)
fi
CTK_MM=""
if [[ -n "$CTK_VER" && "$CTK_VER" =~ ^[0-9]+$ ]]; then
  CTK_MM="$((CTK_VER / 1000)).$(( (CTK_VER % 1000) / 10 ))"
fi
if [[ -n "$NVCC_VER" ]]; then
  ok "nvcc: ${NVCC_VER}（$(command -v nvcc)）"
else
  warn "nvcc: 未探测到 —— flashinfer JIT 无法编译（pip 版工具链缺失或 CUDA_HOME 未指向）"
fi
if [[ -n "$CTK_MM" && -n "$NVCC_VER" ]]; then
  if [[ "$CTK_MM" == "$NVCC_VER" ]]; then
    ok "CUDA 工具链一致：nvcc ${NVCC_VER} == 头文件 CUDART_VERSION ${CTK_VER}（${CTK_MM}）"
  else
    if [[ "${REQUIRE_FLASHINFER_SAMPLER:-0}" == "1" ]]; then
      die "CUDA 编译器与头文件版本不一致（CCCL 硬性校验，差一个 minor 也拒绝）：
    nvcc      = ${NVCC_VER}
    CUDART    = ${CTK_VER}  ⇒ ${CTK_MM}   （来自 $CTK_HDR）
    ⇒ flashinfer 的采样内核 JIT 必然编译失败，vLLM 会报
      「Engine core initialization failed. See root cause above. Failed core proc(s): {}」
    处置（二选一）：
      ① 根治（推荐）：~/vllm-venv/bin/pip install \"nvidia-cuda-nvcc==13.0.88.*\" \"nvidia-cuda-crt==13.0.88.*\"
                       rm -rf ~/.cache/flashinfer   # 换编译器必须清 JIT 缓存
      ② 不再要求严格：去掉 REQUIRE_FLASHINFER_SAMPLER=1（将自动改用 PyTorch 原生采样）"
    fi
    export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
    warn "CUDA 编译器与头文件版本不一致：nvcc ${NVCC_VER} ／ CUDART ${CTK_MM}（来自 ${CTK_VER}）"
    warn "  ⇒ flashinfer 采样内核 JIT 必然编译失败（CCCL 要求 major.minor 严格相等）。"
    warn "  已设 VLLM_USE_FLASHINFER_SAMPLER=${VLLM_USE_FLASHINFER_SAMPLER}（改用 PyTorch 原生采样，"
    warn "  与 flashinfer 路径『statistically equivalent』，且不参与受约束解码 ⇒ 不改变产物口径）。"
    echo "      根治（恢复上游 cuda-toolkit 声明的组合，之后可删掉本降级）："
    echo "        ~/vllm-venv/bin/pip install \"nvidia-cuda-nvcc==13.0.88.*\" \"nvidia-cuda-crt==13.0.88.*\""
    echo "        rm -rf ~/.cache/flashinfer"
    echo "      强制严格（不一致就直接失败）：REQUIRE_FLASHINFER_SAMPLER=1 bash $0"
  fi
elif [[ -z "$CTK_MM" ]]; then
  warn "未取到 CUDART_VERSION（预期路径 $CTK_HDR）—— 跳过版本一致性检查"
fi
SAMPLER_MODE="flashinfer（默认，需编译工具链与版本一致）"
if [[ "${VLLM_USE_FLASHINFER_SAMPLER:-}" == "0" ]]; then
  SAMPLER_MODE="PyTorch 原生（VLLM_USE_FLASHINFER_SAMPLER=0）"
fi

# ------------------------------------------------------------------ 1. 权重校验
step "1/5 校验模型权重（不下载）"
[[ -d "$MODEL_PATH" ]] || die "权重目录不存在：$MODEL_PATH
    本脚本**刻意不下载权重**（15.2 GB）。请确认路径，或用 --model-path 指定。"
if [[ ! -f "$MODEL_PATH/config.json" ]]; then
  die "权重目录缺 config.json，不是完整模型目录：$MODEL_PATH"
fi
SHARD_COUNT=$(find "$MODEL_PATH" -maxdepth 1 -name '*.safetensors' | wc -l | tr -d ' ')
WEIGHT_GB=$(du -sm "$MODEL_PATH" 2>/dev/null | cut -f1)
ok "权重就位：$MODEL_PATH（${SHARD_COUNT} 个 safetensors 分片，${WEIGHT_GB} MiB）"
[[ "$SHARD_COUNT" -ge 1 ]] || die "未找到任何 .safetensors 分片"
ok "权重来源：Windows E 盘经 /mnt/e 挂载（**零拷贝**，未在 Linux 侧落第二份）"

# ------------------------------------------------------------------ 2. 安装 vLLM
if [[ "$SERVE_ONLY" -eq 1 ]]; then
  step "2/5 --serve-only：跳过安装"
else
  step "2/5 安装 vLLM（pip）"
  # ⚠️ 版本钉住：受约束解码字段在 v0.12.0 有破坏性变更（guided_json → structured_outputs）。
  #    这里不钉死具体版本（由离线/镜像源决定），但**装完必须打印版本**供人工核对。
  # ⚠️ Ubuntu 24.04 起 pip 默认拒绝写入系统环境（PEP 668 externally-managed-environment），
  #    `--break-system-packages` 是**本发行版内的既定选择**（该实例专供 vLLM，无其他系统级
  #    Python 依赖会因此受损）。若要隔离，请自行改用 venv 并设 PY_BIN 指向它。
  # —— pip 参数决策 ——
  # 是否运行在 venv / virtualenv 内：venv 里**没有** EXTERNALLY-MANAGED 标记，
  # 不需要 --break-system-packages（传了无害，但会让人误以为必须）。
  # 前半段（运行环境归位）已用 pyvenv.cfg 判过 ⇒ 这里只作兜底（覆盖 conda 等其它形态）。
  PY_IN_VENV="${PY_IN_VENV:-$("$PY_BIN" -c 'import sys; print(int(sys.prefix != sys.base_prefix))' 2>/dev/null || echo 0)}"
  if [[ -n "${PIP_ARGS:-}" ]]; then
    :                                     # 用户显式指定，原样尊重
  elif [[ "$PY_IN_VENV" == "1" ]]; then
    PIP_ARGS=""                           # venv 内自动摘掉
  else
    PIP_ARGS="--break-system-packages"    # 系统 python：Ubuntu 24.04 的 PEP 668 既定选择
  fi
  # 重试与超时：轮子大（torch 单文件约 800 MB），弱网下用 pip 默认值容易中途断掉重来
  PIP_ARGS="${PIP_ARGS:+$PIP_ARGS }--retries $PIP_RETRIES --timeout $PIP_TIMEOUT"
  # 断点续传：`--resume-retries` 是 pip >= 23.1 才有的选项，低版本传了会**直接以
  # unknown option 退出**（比慢更糟）⇒ 必须先探测 pip 版本再决定是否下发。
  # 意义：torch/cudnn 这类几百 MB 的轮子下到 90% 断线时**接着下**，而不是从 0 重来。
  PIP_VER=$("$PY_BIN" -m pip --version 2>/dev/null | awk '{print $2}' || true)
  if [[ -n "$PIP_VER" && "$PIP_RESUME_RETRIES" -gt 0 ]] \
     && printf '%s\n%s\n' '23.1' "$PIP_VER" | sort -V -C 2>/dev/null; then
    PIP_ARGS="$PIP_ARGS --resume-retries $PIP_RESUME_RETRIES"
    RESUME_STATE="开（$PIP_RESUME_RETRIES 次，pip $PIP_VER）"
  elif [[ -n "$PIP_VER" ]]; then
    RESUME_STATE="关（pip $PIP_VER 不支持或已置 0）"
  else
    RESUME_STATE="未知（当前解释器查不到 pip 版本）"
  fi
  PIP_INDEX_URL=$(resolve_pip_index "$PIP_INDEX")
  if [[ -n "$PIP_INDEX_URL" ]]; then
    PIP_ARGS="$PIP_ARGS -i $PIP_INDEX_URL"
  fi
  # 代理：显式 PIP_PROXY 优先；未指定时 pip 会自己读 http_proxy/https_proxy —— 故这里只如实打印
  if [[ -n "$PIP_PROXY" ]]; then
    PIP_ARGS="$PIP_ARGS --proxy $PIP_PROXY"
  fi
  # 环境里大小写共 4 个 *_proxy 变量，逐行打印会把下面的标签挤糊 —— 故缩进分行显示
  PROXY_ENV=$(env | grep -i '_proxy=' | sed 's/^/      /' || true)
  echo "    pip 源  : ${PIP_INDEX_URL:-（pip 官方默认 pypi.org）}"
  echo "    pip 代理: ${PIP_PROXY:-（未显式指定 —— pip 将自动读取环境变量）}"
  echo "    环境代理:"
  printf '%s\n' "${PROXY_ENV:-      （无）}"
  echo "    重试/超时: ${PIP_RETRIES} 次 / ${PIP_TIMEOUT} s"
  echo "    断点续传: ${RESUME_STATE}"
  echo "    pip 参数: ${PIP_ARGS}"
  echo "    解释器  : $(command -v "$PY_BIN")$([[ "$PY_IN_VENV" == "1" ]] && echo '  (venv)')"

  if ! "$PY_BIN" -m pip --version >/dev/null 2>&1; then
    warn "pip 不可用"
    # ⚠️ Debian / Ubuntu 的**系统 python 会显式禁用 ensurepip**（报
    #    `ensurepip is disabled in Debian/Ubuntu for the system python`），
    #    故这一步失败属**预期策略**，**不代表环境损坏** —— 不要在这里下「环境有问题」的结论。
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
      echo "      干跑模式**不阻断** —— 正式跑前请先补 pip（二选一）："
      echo "        ① 装系统 pip：apt-get update && apt-get install -y python3-pip"
      echo "        ② 用 venv   ：apt-get install -y python3-venv && python3 -m venv ~/vllm-venv"
      echo "                      然后：PY_BIN=~/vllm-venv/bin/python bash $0"
    elif ! "$PY_BIN" -m ensurepip --upgrade >/dev/null 2>&1; then
      # ⚠️ 两行写成 `&& \` 是一条命令 —— 这样用户**即使粘成一行也能跑**。
      die "解释器 $(command -v "$PY_BIN") 无 pip，且 Debian/Ubuntu 已禁用 ensurepip（正常策略，非故障）。
    处置（二选一，装完重跑本脚本）：
      ① 装系统 pip      ：apt-get update && apt-get install -y python3-pip
      ② 用 venv 隔离（推荐）：
           apt-get install -y python3-venv && python3 -m venv ~/vllm-venv && \\
             PY_BIN=~/vllm-venv/bin/python bash $0"
    fi
  fi

  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    ok "DRY_RUN=1：跳过安装。将执行：$PY_BIN -m pip install --upgrade vllm $PIP_ARGS"
  else
    echo "    安装 vllm（可能耗时数分钟至数十分钟，下载 CUDA 轮子较大）..."
    # shellcheck disable=SC2086
    "$PY_BIN" -m pip install --upgrade vllm $PIP_ARGS
    ok "vLLM 安装完成"
  fi
fi

# ------------------------------------------------------------------ 3. 版本与能力核对
step "3/5 引擎版本与受约束解码能力"
VLLM_VER=$("$PY_BIN" -c 'import vllm; print(vllm.__version__)' 2>/dev/null || echo "未取到")
echo "    vLLM 版本: $VLLM_VER"
echo "    torch CUDA: $("$PY_BIN" -c 'import torch;print(torch.__version__, "cuda:", torch.cuda.is_available())' 2>/dev/null || echo '未取到')"

if [[ "$VLLM_VER" == "未取到" ]]; then
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    warn "DRY_RUN=1：当前解释器尚未装 vLLM，跳过版本核对（正式跑时会强制校验）"
  else
    die "无法导入 vllm —— 安装未成功，或当前 python 不是运行 vllm 的那个解释器。"
  fi
fi

# 与 Windows 侧 APP_VLLM_GUIDED_DECODING_MODE 的口径对齐（OPS-002 §4.3）
# ⚠️ 必须包在「已取到版本」分支里：`[[ 未取到 -gt 0 ]]` 会让 bash 报
#    `integer expression expected` 并以非 0 退出（set -e 下直接中止脚本）。
if [[ "$VLLM_VER" != "未取到" ]]; then
  MAJOR="${VLLM_VER%%.*}"; MINOR="${VLLM_VER#*.}"; MINOR="${MINOR%%.*}"
  if [[ "$MAJOR" -gt 0 || "$MINOR" -ge 12 ]]; then
    ok "引擎 >= 0.12.0 → Windows 侧应设 APP_VLLM_GUIDED_DECODING_MODE=structured_outputs"
  else
    warn "引擎 < 0.12.0 → Windows 侧应设 APP_VLLM_GUIDED_DECODING_MODE=guided_json"
    warn "  ⚠️ 配错会被引擎**静默忽略**，导致无约束解码（看似成功、实则无约束）"
  fi
fi

# ------------------------------------------------------------------ 4. 端口占用
step "4/5 端口检查"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  warn "端口 ${PORT} 已被占用："
  ss -ltnp 2>/dev/null | grep ":${PORT} " | sed 's/^/      /'
  die "请先停掉占用进程，或用 --port 换端口"
fi
ok "端口 ${PORT} 空闲"

# ------------------------------------------------------------------ 5. 启动服务
step "5/5 启动 vLLM 服务"
EAGER_FLAG=""
[[ "$ENFORCE_EAGER" == "1" ]] && EAGER_FLAG="--enforce-eager"

cat <<EOF
    启动参数（与 OPS-002 §5 基线一致）：
      --model                 $MODEL_PATH
      --served-model-name     $MODEL_NAME
      --dtype                 $DTYPE
      --max-model-len         $MAX_MODEL_LEN
      --gpu-memory-utilization $GPU_MEM_UTIL
      --max-num-seqs          $MAX_NUM_SEQS
      --host / --port         $HOST:$PORT
      --enable-prefix-caching  (Qwen 前缀复用，schema 段落可命中缓存 <待实测收益>)
      采样后端                 $SAMPLER_MODE
      $EAGER_FLAG

    ⚠️ 下列数值**均未实测**，须在上机后回填实测值并登记：
       · 实际显存占用与 KV Cache 可用块数（--kv-cache-memory-bytes 或日志）
       · 单卡 10 并发下的 TTFT / TPOT（SYS-015 校准依据，见 T-013）
       · max-model-len 是否足够容纳最长分段提示词
         → **已实测（DEV-20261015-014）**：最长＝storyboard 段 **14473 tokens** ⇒ 窗口需 ≥ 22665，
           故默认值取 32768；原 16384 不足（storyboard 段被入口 400 拒收，见 ISSUE-032）
EOF

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  ok "DRY_RUN=1，仅打印参数，不启动"
  exit 0
fi

echo
echo "    启动后自检（在另一终端执行）："
echo "      curl -s http://127.0.0.1:${PORT}/v1/models | head -c 400"
echo
exec "$PY_BIN" -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" \
  --served-model-name "$MODEL_NAME" \
  --dtype "$DTYPE" \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --enable-prefix-caching \
  $EAGER_FLAG \
  --host "$HOST" \
  --port "$PORT"
