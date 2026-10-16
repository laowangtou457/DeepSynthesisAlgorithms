"""应用配置：环境变量集中校验、启动快速失败。

对应《模型框架设计说明书》ARCH-003 §3.4 `app/core/config.py`。
纪律：配置只从环境变量／`.env` 读取，**不得在业务代码中内联硬编码**。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务配置。字段名与 `.env.example` 中的 `APP_*` 一一对应。"""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_name: str = "AI 漫剧剧本与分镜提示词生成系统"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # ---- 备案主体标识（**脱敏版留空，由部署环境注入**）----
    # provider_name / provider_code 为空时，`pack_meta` 一律写占位符并登记，
    # **绝不自拟假值**（见 app/services/pack_meta.py）。
    provider_name: str = ""
    provider_code: str = ""

    # ---- 推理后端（ARCH-003 §6.1「可替换是架构底线」）----
    # 取值：mock | vllm | local | remote；切换只改本项，业务代码零改动。
    inference_backend: str = "mock"

    # ---- vLLM 后端（`T-004` 生成链路接入 / `T-012` 部署手册）----
    # 平台前提：vLLM 官方仅支持 Linux / WSL2，故服务进程跑在 WSL2 内、
    # 监听回环端口；Windows 侧应用经 localhost 转发访问（见 `04-部署运维/OPS-002`）。
    # 纪律：地址与模型名一律来自配置，**不得在业务代码中硬编码**。
    vllm_base_url: str = "http://127.0.0.1:8001/v1"
    vllm_model: str = "Qwen2.5-7B-Instruct"
    vllm_api_key: str = ""  # 本机部署无鉴权；仅占位，**任何真实密钥不得写入文件**
    #: **单次后端调用的超时秒数**（`httpx.AsyncClient(timeout=…)`，**按每次 HTTP 请求**计）。
    #: ⚠️ **`180` 是与实测耗时重叠的错值，本批上修为 `600`**（`ISSUE-048`）：
    #: 实测四段中 `shot_prompt` 单次调用 **167～304 s**（`DEV-20261016-003` 一轮 167.3 s；
    #: `DEV-20261016-007` 另记约 304 s）⇒ 原值 **180** 落在分布**中部**，
    #: 该段成败取决于**当次输出长度** ⇒ **间歇性 502**（真跑现场：`latency_ms=180050`、
    #: `vllm_timeout`、应用如实转 502 且 `retryable=true`）。
    #: ⚠️ **为什么不是随便调大**：超时是「fail fast」与「容忍长产出」的取舍——过小会把
    #: **正常的长生成**判成故障（本次即如此）；过大则真故障要等很久才暴露。
    #: 取 **600** 的依据＝**实测最大值（304 s）上取整到整百后的约 2 倍档**，
    #: 给模型输出长度波动留一档余量，同时**远小于**「十并发压测」（`T-013`）所需的总时限。
    #: ⚠️ **与重试回路的关系**：本超时**按调用计**，而重试会**多次调用** ⇒
    #: 单段最坏墙钟时间 ≈ `quality_gate_max_attempts × 本值`，部署侧须据此评估用户等待时间。
    vllm_timeout_seconds: float = 600.0
    #: 受约束解码策略（**版本敏感，切换前须核对目标 vLLM 版本**）：
    #: - `structured_outputs` = vLLM **>= 0.12.0** 官方形态（`{"json": …}`）；
    #: - `guided_json` = vLLM **< 0.12.0** 原生参数（旧字段发给新版会被**静默忽略**
    #:   → 无约束解码，故不作默认）；
    #: - `response_format` = OpenAI 标准 `json_schema` 形态（跨引擎最通用）；
    #: - `off` = 不约束（**仅调试用**，产物合法性须自行校验）。
    #: ⚠️ 不得把版本不匹配当作「约束已生效」—— 详见 `inference/vllm_backend.py`。
    vllm_guided_decoding_mode: Literal[
        "structured_outputs", "guided_json", "response_format", "off"
    ] = "structured_outputs"
    #: 单卡并发上限（`SYS-015` 待实测校准，此处只登记目标值）。
    vllm_max_concurrency: int = 10

    # ---- 提示词资产根目录（03-工程代码/prompts）----
    prompts_root: str = ""

    # ---- 输出契约 schema 目录（受约束解码用；`T-004`）----
    # 留空时按工程布局定位为 `<工程代码>/delivery/schemas`。
    # 该 schema 是**契约资产**，服务层读它做 FSM 约束采样（见 TPL-009 sampling 注释）。
    delivery_schemas_dir: str = ""

    # ---- 提示词输入体积（`ISSUE-037` 方案 D 的**服务层**一半）----
    #: 注入上游产物变量（`*_json`）前，对其 JSON 文本做**无损紧凑化**（只去空白，语义零改动）。
    #: 背景：`TPL-009` 原先把上游全文插入 **5 次**（渲染器 `loader._interpolate` 对**每一处**
    #: `{name}` 一律全量替换），`shot_prompt` 段真实输入达 **50,358 tokens**，加输出 8,192 后
    #: **58,550** ⇒ 超 Qwen2.5-7B 原生上限 **32768**，该段在**引擎入口**被拒（`502`）。
    #: 模板侧已改为「每个上游各只注入一次」（`TPL-009` v2.1.1）；本项再削掉 JSON 的缩进与换行。
    #: ⚠️ **默认 `true`**，且**不建议改为 `false`**：该变换**只去空白**——键序、键值、数值精度
    #: 一律不变（`ensure_ascii=False` 保持中文可读），解析失败时**原样返回** ⇒ 它是**体积优化**，
    #: 不是语义变换。置 `false` 仅用于「原文即所见」的**对照量测**。
    prompt_compact_upstream: bool = True

    #: **紧凑化的适用阶段**（逗号分隔的阶段名，`ISSUE-044`；空串＝不适用任何阶段）。
    #: ⚠️ **为什么需要这一项**：紧凑化的**唯一动机**是「某段的渲染输入超窗」，而实测
    #: 只有 `shot_prompt` 段会超（未紧凑 50,358 ＋ 8,192 ＝ 58,550 ❌）；`storyboard` 段的
    #: 输入仅 **12,214 tokens**（未紧凑亦仅 14,534，＋8,192 ＝ 22,726 ≪ 32,768 ✅）——
    #: **对它施加紧凑化没有收益**。
    #: ⚠️ **背景（实测对照，n＝6/格）**：分镜段存在一个「**只覆盖第 1 场的 3 镜 / 1 单元**」
    #: 吸引子 —— **不带受约束解码时 6/6 稳定落入**；带受约束解码时 12 次中 5 次逃出
    #: （镜数 9~15）。紧凑化在带约束时表现为**疑似劣化**（越阈值 **4/6 → 1/6**），
    #: ⚠️ 但 **Fisher 单侧 p≈0.24、不显著**，故本项**只按「谁需要谁才用」收窄**，
    #: **不宣称**已证明因果（对照脚本见 `03-工程代码/.wb-e2e/ab_storyboard*.py`）。
    #: ⇒ 默认**只对 `shot_prompt` 段**启用；**方案 D 的目的（救第 4 段超窗）不受影响**。
    prompt_compact_stages: str = "shot_prompt"

    # ---- 产物形态闸（`ISSUE-042` 根治）----
    #: **阻断执行开关**：`true` ＝ 形态判定生效并在生成链路上阻断；
    #: `false` ＝ **只判定、只留痕、不阻断**（受控旁路）。
    #: ⚠️ **背景**：实测（第 3 轮真跑）分镜段产出**被截断的 JSON**
    #: （13,252 字符，`finish_reason=stop`），却**照常入库并推进状态机**，
    #: 下游拿到不可解析的上游继续生成、自行编造 `units`／`shots` ⇒
    #: 本层第一纪律「承继守恒」**在源头已不可验证**。
    #: 根因是「产物形态契约」在运行期**无落点**（中间三段的形态真值此前只在
    #: 人读文档与离线门禁脚本里）⇒ 三道闸（受约束解码／生成后自检／下游准入）
    #: 全部建不起来。现由 `app/services/artifact_contract.py` 补上落点。
    #: ⚠️ **默认为 `true`**；置 `false` 时判定**照常执行并留痕**、仅在留痕中
    #: 标注 `enforced=false`——**不得静默**（与内容安全双闸同一纪律）。
    shape_gate_enforce: bool = True

    # ---- 生成后质量门禁 ＋ 不过即重试回路（`T-086`；`ISSUE-038` 的链路侧一半）----
    #: **总开关**：是否在「生成后、入库前」调用工程侧门禁判据。
    #: ⚠️ 判据的**唯一来源**是 `prompts/validate_output.py`（`R1`~`R40`）——
    #: 服务层**不得抄第二份**（抄一份就是两处口径，本工程已多次因「两处口径打架」返工）。
    quality_gate_enabled: bool = True

    #: **门禁适用的阶段**（逗号分隔；空串＝不适用任何阶段）。
    #: ⚠️ 默认只对 `storyboard`（分镜）与 `shot_prompt`（交付包）两段启用：
    #: `ISSUE-038` 的实测失败**全部**落在分镜段及其下游；梗概／剧本段虽有 `R4` 同源问题，
    #: 但那是**上游承继**、在分镜段会被同一判据再次抓到 ⇒ 对上游段重复设闸只增加重试成本。
    quality_gate_stages: str = "storyboard,shot_prompt"

    #: **阻断执行开关**（项目方 2026-10-16 裁决「**分阶段上线**」）：
    #: `true` ＝ 门禁结论生效，用尽重试仍不过则**如实拒绝**（不写产物槽、不推进状态机）；
    #: `false` ＝ **只判定、只留痕、不阻断**（受控旁路）——**当前默认**。
    #: ⚠️ **为什么默认关**：实测**产物级直出率 `passed=true` ＝ 0/3**（`ISSUE-038`），
    #: 若此刻就拦，四段生成会**大概率全部被拒** ⇒ 链路直接不可用。
    #: 故本批**先把回路建成并用真实数据检验**，待 `T-087`（资产侧提质）把直出率抬到可用后
    #: 再翻为 `true`。⚠️ 置 `false` 时判定**照常执行并留痕**（`enforced=false`），**不得静默**。
    quality_gate_enforce: bool = False

    #: **重试回路开关**（与 `quality_gate_enforce` **分开**）。
    #: `true` ＝ 门禁不过时**按 `quality_gate_max_attempts` 重试**；
    #: `false` ＝ **只判一次、不重试**（判定与留痕照常）。
    #: ⚠️ **为什么默认关**（本批实测结论，2026-10-16）：置 `true` 会**成倍拉长单次生成耗时** ——
    #: 实测直出率 `passed=true` ＝ **0/3**，即**几乎每次都会走到重试**；而 `shot_prompt` 段
    #: 单段实测约 **304 s**、`storyboard` 段约 **130 s** ⇒ 开着重试意味着这两段各跑两遍。
    #: 在 `quality_gate_enforce=false`（分阶段上线）期间，重试**不改变「是否入库」**、
    #: 只改变「入库的是哪一版」⇒ 收益与成倍耗时不成比例。
    #: ⇒ 建议与 `quality_gate_enforce` **同时**在 `T-087`（资产侧提质）完成后打开；
    #: 或先打开本项做**收敛性实测**（`T-086` 的待办项之一），量出「重试后通过率」再决定。
    quality_gate_retry_enabled: bool = False

    #: **重试上限**（含首次；`2` ＝ 首次 ＋ 1 次重试）。项目方 2026-10-16 裁决取 `2`。
    #: ⚠️ **必须有上限**且**用尽即如实拒绝**（`quality_gate_enforce=true` 时）——
    #: 否则本回路会退化为「**以重试掩盖不合格产物**」，违反本层第一纪律。
    quality_gate_max_attempts: int = 2

    #: **重试粒度**：`segment` ＝ 只重跑定位到的失败段（`T-086` 默认）；`stage` ＝ 整阶段重跑。
    #: ⚠️ 按段的**定位**依赖「门禁报错消息 → 段」的映射（`unit:Uxx`／`package_head`）；
    #: **映射不到一律回退为全部段**（宁可多跑，不得漏跑），并在留痕里记 `scope_fallback`。
    quality_gate_retry_scope: Literal["segment", "stage"] = "segment"

    #: 是否**同时**跑交付层门禁（`delivery/validate_pack.py` 的 `BLOCK` 判据）。
    #: ⚠️ `PRO-006` §7 的验收判据原文针对的**正是它**（「交付包经 `validate_pack.py` 门禁 0 BLOCK」）；
    #: 工程侧门禁（`validate_output.py`）判的是同一批产物的**另一层**，两者**都要**。
    quality_gate_pack_check: bool = True

    #: **服务层元数据真值覆盖**（`T-086` 配套；2026-10-16 项目方裁决「服务层强制覆盖」）。
    #: `true` ＝ 交付包产物生成后，由服务层以**自己算出来的** `pack_meta` 覆盖模型自述的
    #: `meta`（`pack_id`／`created_at`／`task_type`／`unsupported_task_types`／`generator`／
    #: `generation_trace`／`compliance`）与 `aigc_meta.AIGC`（标识块），模型自拟值**一律丢弃**。
    #: ⚠️ **为什么必须做**（实测发现，合规级）：服务层刻意留的占位（`safety_check:"占位（内容安全
    #: 双闸未接入）"`、`marking_check:"占位"`、`statement_id:"{{STATEMENT_ID}}"`）在真实产物里
    #: **被模型替换成了看起来已通过的假值** —— `safety_check:"passed"`（还带时间戳）、
    #: `copyright_check:"passed"`、`marking_check.explicit:"present"`、`statement_id:"ST-001"`。
    #: ⇒ 客户拿到的产物**看起来已过内容安全与标识校验，而平台根本没做**。这比「缺失」更危险
    #: （缺失会被门禁拦下，假值会**通过**门禁）。⇒ 合规字段的**写入权必须归服务层**。
    #: ⚠️ 覆盖**只针对服务层域字段**；模型可影响的字段（`title`／`total_duration_ms`／
    #: `notes`／`shots`／`units`…）**一字不改**（本工程第一纪律：不改写模型输出）。
    service_truth_override: bool = True

    #: **对外能力声明**（逗号分隔的任务类型码，写入交付包 `meta.unsupported_task_types`）。
    #: 语义＝「本期不支持的任务类型」，`CFG-006` 要求**非空**（「留空会让客户以为支持」）。
    #: ⚠️ **默认空**＝服务层**不声明**（不替项目方做产品口径声明）：
    #: 此时 `build_pack_meta` 产出空列表，而 `apply_service_truth` ②′ **保留模型已声明的值**
    #: （模型若写了合法内容，交付 schema 的 `minItems: 1` 即满足）。
    #: ⇒ **要稳定满足 schema，应由部署侧显式配置**（如
    #: `APP_UNSUPPORTED_TASK_TYPES=keyframe_completion,reference_generation,...`），
    #: 具体内容属**产品口径**，须项目方确认后回填（见 `ISSUE-047`）。
    unsupported_task_types: str = ""

    # ---- 会话（SW-001「会话超时恢复」）----
    session_ttl_seconds: int = 3600

    # ---- 身份与租户（T-008 二期接入，本批只保留配置位）----
    auth_enabled: bool = False

    # ---- 内容安全双闸（`T-005`；SW-009 / SW-010 / SW-011 / SW-017）----
    #: 关键词库根目录（`09-合规资料库/01-关键词库`）。留空时按工程布局定位。
    lexicon_root: str = ""
    #: 输出闸命中处置策略：`block` 拦截 ／ `replace` 标记待处置 ／ `flag` 放行并打标。
    #: 需求 `SW-010` 原文「命中策略可配（拦截/替换/标记）」，默认取最严的 `block`。
    guard_output_action: Literal["block", "flag"] = "block"
    #: **fail-closed**：检测不可用（词库零词条/ 加载失败）时拒绝放行。
    #: ⚠️ **默认 `true` 且不建议改为 `false`**——改为 fail-open 等于「检测失效即放行」，
    #: 与 `SW-009` 异常列「检测服务不可用熔断」相悖。该开关仅供**本地调试**临时关闭。
    guard_fail_closed: bool = True
    #: **阻断执行开关**（项目方 2026-10-15 决策「保持 fail-closed ＋ 加受控的旁路开关」）：
    #: `true` ＝ verdict 生效、生成链路据其阻断；`false` ＝ **只判定不阻断**，
    #: 用于「受控词库尚未就绪」期间的工程联调。
    #: ⚠️ **默认为 `true`**；置 `false` 时检测**照常执行并留痕**，但放行判定不做阻断——
    #: 该状态会体现在 `/safety/policy` 的 `fail_closed` 与启动日志中，**不得静默**。
    guard_enforce: bool = True
    #: **受控词库目录**（项目方 2026-10-15 决策：「受控内容**不入库**，
    #: 双闸**运行时读受控区**」）。留空时按工程布局取 `E:\_受控区\lexicon_controlled`。
    #: ⚠️ 该目录**不受版本控制**（`.gitignore` 已排除 `_受控区/`）；
    #: ⚠️ **其路径不得出现在任何 API 响应中**（`Lexicon.controlled_loaded` 只给布尔）。
    controlled_lexicon_root: str = ""
    #: 单次检测最多返回的命中类别数（避免响应体过大）。
    guard_max_hits: int = 20
    # ---- `SW-017` 兜底话术（2026-10-16 项目方裁决 `ISSUE-035` ② 取方案 B）----
    #: 需求原文：「拒答话术**可配置、可审计**；兜底话术由 `TPL-005`／`TPL-004` 产出」。
    #: 落实为「**配置承载话术 ＋ 执行期确定性取用**」：
    #:   · 话术值在此配置 ⇒ **改话术不改代码**（可配置、可审计，需求原文达标）；
    #:   · 执行期**不调推理后端** ⇒ 安全兜底在后端不可用时仍能工作
    #:     （若话术依赖模型，模型被注入时兜底同时失效——这是 `DEV-20261015-009`
    #:     的设计初衷，**方案 B 予以保留**）。
    #: ⚠️ 留空 ＝ 回落服务层内置默认（行为与改动前逐字一致，零回归是硬要求）。
    #: ⚠️ `TPL-004/005` 的 `sections.output` 给出的是**模型生成**的话术规格，
    #:   属后续增强（`DEV-009` 已声明不作为本轮验收依据），本轮**不接**。
    guard_refusal_talk: str = ""
    #: 澄清话术（修改意见含糊时使用），同上。
    guard_clarify_talk: str = ""

    @property
    def prompts_dir(self) -> Path:
        """提示词资产根目录：显式配置优先，否则按包位置上溯定位。"""
        if self.prompts_root:
            return Path(self.prompts_root).expanduser().resolve()
        # 本文件位于 <工程代码>/app/core/config.py → 上溯三级得 <工程代码>/prompts
        return Path(__file__).resolve().parents[2] / "prompts"

    @property
    def compact_stages(self) -> frozenset[str]:
        """紧凑化适用的**阶段集合**（由 `prompt_compact_stages` 按逗号切分）。

        ⚠️ 空串表示**不适用任何阶段**（紧凑化整体不生效）；未登记的阶段**原样注入**。
        用裸字符串 + 本属性而非 `tuple` 型字段：pydantic-settings 对环境变量里的
        复杂类型走 **JSON 解析**，运维侧输入 `APP_PROMPT_COMPACT_STAGES=shot_prompt`
        会被判非法；逗号分隔对操作者更稳（同 `PATH` 一类习惯）。
        """
        return frozenset(s.strip() for s in self.prompt_compact_stages.split(",") if s.strip())

    @property
    def quality_gate_stage_set(self) -> frozenset[str]:
        """门禁适用的**阶段集合**（由 `quality_gate_stages` 按逗号切分）。

        同 `compact_stages`：用逗号分隔的裸字符串而非 `tuple` 型字段 —— pydantic-settings
        对环境变量里的复杂类型走 JSON 解析，运维侧写 `APP_QUALITY_GATE_STAGES=a,b` 会被判非法。
        空串表示**不适用任何阶段**（门禁整体不生效）。
        """
        return frozenset(s.strip() for s in self.quality_gate_stages.split(",") if s.strip())

    @property
    def lexicon_dir(self) -> Path:
        """关键词库根目录：显式配置优先，否则按工程布局定位。

        定位规则：`<工程代码>/app/core/config.py` → 上溯三级得 `<工程代码>` →
        再上溯一级得**工程根**，取 `<工程根>/09-合规资料库/01-关键词库`。
        """
        if self.lexicon_root:
            return Path(self.lexicon_root).expanduser().resolve()
        project_code_dir = Path(__file__).resolve().parents[2]  # <工程代码>
        project_root = project_code_dir.parent                   # <工程根>
        return project_root / "09-合规资料库" / "01-关键词库"

    @property
    def controlled_lexicon_dir(self) -> Path:
        """受控词库目录：显式配置优先，否则取受控区默认位置。

        ⚠️ **受控区在工程根之外、不受版本控制**（项目方 2026-10-15 决策）。
        目录不存在时**不报错**，由 `load_lexicon` 记入 `warnings` 并按
        「受控类别检测能力不可用」处理——**绝不静默当作无受控风险**。
        """
        if self.controlled_lexicon_root:
            return Path(self.controlled_lexicon_root).expanduser().resolve()
        return Path(r"E:\_受控区\lexicon_controlled")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()
