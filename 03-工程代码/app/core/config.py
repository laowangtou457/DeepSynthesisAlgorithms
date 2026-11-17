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

    # ---- 安全边界系统提示词（`T-015` 冻结资产 `CFG-010` 运行时注入，`DEV-20261110-012`）----
    #: 留空 ⇒ 按 `prompts_root` 相对定位默认资产
    #: `safety/CFG-010_safety_boundary_system_prompt.txt`（`prompts_root` 也为空 ⇒ 不注入）。
    #: 注入方式：`VllmBackend` 在 messages 层合并（边界提示词在前、模板 `<system>` 节在后）。
    safety_system_prompt_file: str = ""

    # ---- 语义闸（`T-108` ③：Qwen3Guard-Gen-4B，部署见 `DEV-20261110-012`）----
    #: 服务器 GPU7 `safety-guard.service`（127.0.0.1:8001），本机经 SSH 隧道 18002 访问。
    #: ⚠️ 失效语义 fail-open＋留痕：语义闸不可用 ⇒ 回落词闸判定（词闸＋输出复检＋人工抽检仍在线），
    #: 不得因语义闸故障拒绝正常请求；故障经 `_base_verdict_kwargs` 留痕，不静默旁路。
    guard_semantic_enabled: bool = True
    guard_semantic_base_url: str = "http://127.0.0.1:18002/v1"
    guard_semantic_model: str = "Qwen3Guard-Gen-4B"
    guard_semantic_timeout_seconds: float = 15.0

    # ---- 版权校验（`SW-015`）----
    #: 可比对作品库根目录：目录下每个 `.txt`/`.md` 是一篇受保护作品（文件名即作品名）。
    #: ⚠️ **当前为空＝库未建立**（属 `T-011` 数据来源任务范围，`REQ-005` `SW-015` 已登记该前置）。
    #: 留空时版权校验的结论**恒为 `not_available`**（「没检」，不是「通过」）——
    #: 这是**如实呈现**，不是缺陷；库投放到位后**无需改码**即可自动启用比对。
    #: 库内容属外部数据，**不入版本控制**。
    copyright_corpus_root: str = ""
    #: 相似度风险阈值（`REQ-005` `SW-015`：默认 **0.5**，可配置）。
    #: ≥ 该值即判 `risk`（**不阻断交付**，但须在版权声明中逐条列明，见 `SW-015` ③）。
    copyright_similarity_threshold: float = 0.5

    # ---- 提示词资产根目录（03-工程代码/prompts）----
    prompts_root: str = ""

    # ---- 输出契约 schema 目录（受约束解码用；`T-004`）----
    # 留空时按工程布局定位为 `<工程代码>/delivery/schemas`。
    # 该 schema 是**契约资产**，服务层读它做 FSM 约束采样（见 TPL-009 sampling 注释）。
    delivery_schemas_dir: str = ""

    # ---- 交付包输出目录（`SW-I04` / `T-006`）----
    #: `POST /delivery/pack` 的默认落盘目录。留空时端点要求请求体显式给 `out_dir`。
    #: ⚠️ **本目录只放交付包文件**（提示词集 ＋ 标识素材 ＋ 合规声明 ＋ 清单），
    #: **不托管下游平台密钥与成片**（`SYS-018`）。
    delivery_out_dir: str = ""
    #: **人工核对台账**（JSON）路径 —— `SPEC-008` §8.3 第 18 项 / §8.4 的**唯一合法来源**。
    #: ⚠️ 留空 ⇒ 视为「未做人工核对」：交付清单 `human_review` 为空、自检第 18 项 `fail`、
    #: 清单判据 `human_review.missing` **BLOCK**（**如实拦住**）。
    #: ⚠️ **绝不**从模型产物读 `human_review`（模型自证被人工核对 = 假合规）。
    human_review_ledger: str = ""

    # ---- 溯源留存日志（官方第 9 项 · `T-090`；`SW-016` 溯源五要素）----
    #: 日志落盘目录。**留空 ⇒ `<工程根>/.wb-e2e/logs`**（该目录在 `.gitignore` 内，不入库）。
    #: ⚠️ 官方要求「生成内容溯源留存相关日志**不少于六个月**，提供截图」⇒ 本目录必须位于
    #: **持久化磁盘**，不得指向临时目录；部署时可用 `APP_LOG_DIR` 指到大盘。
    log_dir: str = ""
    #: 日志留存天数。**默认 180（≥6 个月）**；调小即违反官方要求，属**受控变更**。
    log_retention_days: int = 180
    #: 是否落盘（`false` 仅用于单元测试/CI 隔离；生产**必须**为 `true`，否则官方第 9 项交不了）。
    log_to_file: bool = True

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

    #: **形态闸失败的重试开关**（`ISSUE-094`：形态闸前移 ＋ fail-fast ＋ 重试）。
    #:
    #: `true` ＝ 形态闸判出的失败**可重试**（该阶段自动重采样，见
    #: `shape_gate_max_attempts`）；`false` ＝ 维持改造前行为（判出即抛、零重试）。
    #:
    #: ⚠️ **为什么必须重试**（真机第 3 轮现场）：形态闸此前只判**顶层**形态，
    #: 而 `script` 段的 `max_attempts` 由**质量门禁**的 `gate_applies` 决定——
    #: `quality_gate_retry_enabled` 默认关 ⇒ `max_attempts=1` ⇒ 形态闸一旦判失败
    #: **一律直接抛错、零重试**。而形态缺陷（元素级结构、缺必需键、截断）恰恰是
    #: **单次采样的随机波动**（同一个模板同一天可产出合法产物）⇒ 「判出即抛」把
    #: 一次可自愈的采样波动升级成整链 502。
    #: ⇒ 形态闸与质量门禁**是两路驱动者**，额度取二者最大值（见 `_maybe_generate`）；
    #: 本开关只管「形态闸这一路要不要给额度」，与 `quality_gate_retry_enabled` 互不影响。
    #: ⚠️ 重试**不改判据**：形态判定的口径一字未动，只是「判失败后再采一次样」；
    #: 用尽额度仍失败则**如实抛出**（`GENERATION_FAILED` 原样、不改错误码、不改文案）。
    #: ⚠️ 与 `shape_gate_enforce` 的关系：后者为 `false`（受控旁路）时本项**不生效**
    #: （既不判阻断、自然也无需重试额度）。
    shape_gate_retry_enabled: bool = True

    #: **形态闸重试上限**（含首次；`2` ＝ 首次 ＋ 1 次重试）。
    #: ⚠️ **必须有上限**且**用尽即如实抛出**——否则本回路会退化为
    #: 「以重试掩盖结构性不可生成」，违反本层第一纪律。
    #: ⚠️ 与 `quality_gate_max_attempts` **不是两份额度、也不会相加**：实际
    #: `max_attempts = max(质量门禁额度, 形态闸额度)`，二者共用**同一串尝试序位**
    #: ⇒ 把本项调大**同时**抬高质量门禁的尝试上限（反之亦然）。
    #: 这条容易读错（独立 QA 复核时已指出一次），故写死：**只有判定阈值是两路各自的，
    #: 尝试次数是共享的**。`shape_gate_retry_enabled=false` 时本项完全不参与取值。
    #: 代价口径同 `quality_gate_max_attempts`：单段最坏墙钟 ≈ `max_attempts × 单次超时`。
    shape_gate_max_attempts: int = 2

    # ---- 生成后质量门禁 ＋ 不过即重试回路（`T-086`；`ISSUE-038` 的链路侧一半）----
    #: **总开关**：是否在「生成后、入库前」调用工程侧门禁判据。
    #: ⚠️ 判据的**唯一来源**是 `prompts/validate_output.py`（`R1`~`R40`）——
    #: 服务层**不得抄第二份**（抄一份就是两处口径，本工程已多次因「两处口径打架」返工）。
    quality_gate_enabled: bool = True

    #: **门禁适用的阶段**（逗号分隔；空串＝不适用任何阶段）。
    #:
    #: ⚠️ **2026-11-03 变更（`PRO-010` 批次 2 · 候选 A′）**：默认段由
    #: `"storyboard,shot_prompt"` 扩为 **`"script,storyboard,shot_prompt"`**（**加 `script`，不加 `synopsis`**）。
    #:
    #: **为什么加 `script`**（`PRO-010` §2.4 实测取证）——**旧注释给的理由经实测不成立**：
    #: 旧注释称「梗概／剧本段虽有 `R4` 同源问题，但那是**上游承继**、在分镜段会被**同一判据**再次抓到
    #: ⇒ 对上游段重复设闸只增加重试成本」。**实测反证**：`R4` 与 `R14` 是**两把不同的锁**——
    #: `R4` 判「Σ**场**秒 ＝ `total_est_seconds`」（剧本层），
    #: `R14` 判「Σ**镜**时长 ＝ `total_duration_ms`」（分镜层）；
    #: `R6`（恰为 3 幕）在分镜层**无对应判据**。
    #: ⇒ 剧本层的失败**不会被分镜层抓到**，只会被**算术继承**（实测：剧本层 `total=125` vs Σ场秒 `15`
    #: ⇒ 分镜层忠实承继成 `total=45000` vs Σ镜时长 `30000`）。
    #: ⇒ ⚠️ **成本论证仍有效**（上游段失败会整链重跑），但**前提是错的** ⇒ 本次是**在观测数据支持下**
    #: **扩大覆盖**，不是「修一个注释笔误」。
    #:
    #: **为什么不加 `synopsis`**：该层 `content_adequacy` 只判「`total_est_seconds` 存在且为正」，
    #: **无等效 `R` 判据**、价值最低，而风险（整链重跑）相同 ⇒ 先不加。
    #:
    #: ⚠️ **本段新增的判据已在离线验证存在且正确**（`PRO-010` §2.1 实测）：
    #: 绕过 `applies_to` 强行跑剧本层产物，`R4`／`R6`／`R5`／`R1`／`R20` **全部命中**
    #: 且**分类正确**（全为 `retryable`）⇒ **判据没坏，缺的只是调用**。
    #:
    #: ⚠️ **口径提醒**：`R6` 要求「`acts` **恰为 3 幕**」——这与 `TPL-008` v2.1.1 的模板条款
    #: （L85／L137／L242／L381「三幕剧本」「acts 必须为 3 幕」）**一致**，**不是判据与模板冲突**。
    quality_gate_stages: str = "script,storyboard,shot_prompt"

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

    #: **重试反馈注入**（**乙**，2026-11-17 裁决「先甲后乙」落地）。
    #: `true` ＝ 重采请求附带上一轮 retryable 明细（`_retry_feedback_text`，≤8 条×200 字符，
    #: 注入位置在**请求侧提示词尾**，不改模板、不改写产物），并启用「承继字段失败跳过
    #: 本段重试」（`_retry_targets_inherited_moves`：`shot_prompt` 段对 `R11`／`R19` 族
    #: 跳过——`camera.*` 出生于 `storyboard` 段且承继守恒，甲试点 `DEV-20261117-001`
    #: 实证盲重试救回 0/4、+40% 时长）。⚠️ `quality_gate_retry_enabled=false` 时本项无效果；
    #: ⚠️ 乙试点仍须量「反馈重试救回率」，不足再走丙（单元 ≥3 镜）／丁（运镜预算调度）。
    quality_gate_retry_feedback: bool = True

    #: 是否**同时**跑交付层门禁（`delivery/validate_pack.py` 的 `BLOCK` 判据）。
    #: ⚠️ `PRO-006` §7 的验收判据原文针对的**正是它**（「交付包经 `validate_pack.py` 门禁 0 BLOCK」）；
    #: 工程侧门禁（`validate_output.py`）判的是同一批产物的**另一层**，两者**都要**。
    quality_gate_pack_check: bool = True

    #: **分镜段派生量的确定性回填**（2026-11-04 项目方裁决；`ISSUE-038` 的 `R14` 一项）。
    #: `true` ＝ 生成后、门禁前，由服务层把 `total_duration_ms` **按 `Σ shots[].duration_ms` 重算并回填**；
    #: `false` ＝ 不动产物（只留原值，由门禁如实判失败）。
    #:
    #: ⚠️ **为什么必须换机制而不是继续改模板**：该项是**跨字段算术**，
    #: JSON Schema／受约束解码**在结构上表达不了**（只能约束单字段取值，无法约束「等于另一组字段之和」）；
    #: 而提示词路线已**四版四错**（v2.2.0 散文条款／v2.2.1 给自洽字面值 `18200`／v2.2.2 归零 ＋ 算式紧邻示例），
    #: 真机实测 `total_duration_ms` **恒为 `0`**（照抄骨架，2026-11-04 三种样本 3/3）。
    #:
    #: ⚠️ **这不是「改判据」**：`R14` 判据**一字未动**。回填后它判的是「回填结果是否守恒」，
    #: 恒等式成立属**工程保证**；模型原本那句自拟值被**完整留痕**（`artifact["derived_backfill"]`
    #: 记 `original`／`computed`），审计时可查「模型填了什么、服务层改成了什么」。
    #: 口径同 `service_truth`：**服务层只补自己算得出的量**，模型可影响字段一字不改。
    storyboard_derived_backfill: bool = True

    #: **剧本／梗概派生总量回填**（`PRO-011` 线 3 ＋ Q2 裁决「派生量服务层复算」；2026-11-04 授权落地）。
    #: `true` ＝ `script`／`synopsis` 段产物的 `total_est_seconds` 由服务层按
    #: **Σ 各场 `est_seconds`** 复算覆写（判据 `R4`；`script` 真基线 3/3 轮失败）。
    #: ⚠️ 口径与 `storyboard_derived_backfill`（`R14`）完全同构：**只改一个由各场时长
    #: 唯一决定的量**，场数／场内容／各场秒数一字不动；模型原值**完整留痕**
    #: （`artifact["derived_backfill"]`）；`R4` 判据一字未动（回填后判「守恒」）。
    #: ⚠️ 下发路线（Q2 原始候选）对**本层不可行**——生成前总量尚不存在（它是模型
    #: 各场决策的求和），只有「生成后复算」一种确定性实现；真值归属方案见 `PRO-011` 附 4。
    script_derived_backfill: bool = True

    #: **交付包派生总量回填**（`PRO-011` 线 3；2026-11-04 授权落地）。
    #: `true` ＝ `shot_prompt` 段（形态 `pack`）产物的 `meta.total_duration_ms` 由服务层按
    #: **Σ `shots[].duration_ms`** 复算覆写（判据 `R31` 双守恒之一 ＋ 交付侧
    #: `consistency.duration`；真基线 2/2 轮失败且第 2 轮还**放大**了上游偏差）。
    #: ⚠️ 逐镜与上游一致（`R31` 另一半）**不可回填**——镜时长是模型创作决策，
    #: 属「模型可影响字段一字不改」；本开关只补**纯算术派生量**。
    pack_derived_backfill: bool = True

    #: **英文运镜句机械补全**（**投影规则⑤**；项目方 2026-11-16 裁决批准）。
    #: `true` ＝ `shot_prompt` 段（形态 `pack`）产物在门禁判定**之前**，逐镜检查
    #: `prompt_en` 是否含**以 `The camera` 起句的独立句**（判据 `R34`，复用
    #: `prompts/validate_output.py` 的 `CAMERA_SENTENCE_RE`，不抄第二份）；缺失则由服务层
    #: 按本镜 `camera.*` **追加**一句英文运镜句，句式取自
    #: `delivery/config/CFG-002_shot_vocab.yaml` 的 `camera_move[].model_map.minimax_h3`
    #: （词表是**唯一句式真值源**，不在代码里硬编码句子）。
    #:
    #: ① **实证依据**（`r6` 复验批 12 轮，`DEV-20261112-012`）：`R34` **12/12 挂**、
    #:    重试自愈 **0/12**；`ab_t101_r6/on/run1` 更实证「越试越差」（attempt1 缺 1 镜 →
    #:    attempt2 缺 4 镜）。模板措辞路线已到顶（`TPL-009` 的 guards 已写「运镜句完整性」
    #:    逐镜自检、examples 已给正例，模型仍漏）⇒ 只能机制化处置。
    #: ② **性质：投影规则⑤，不是「改创作」**——`camera.*` 是**上游已定的导演决策**
    #:    （承继层「一字不得改」），本项只把该决策**投影为英文句子**（与投影规则①
    #:    lighting 拆分同族）；**只追加、不改原句**，且**只追加一句**、不重排不改写正文。
    #: ③ **回退**：`APP_PACK_EN_CAMERA_SENTENCE_FILL=false`（回退后 R34 恢复由模型自证）。
    #: ④ **与 `pack_conservation_fill` 的分工**：后者补的占位镜 `prompt_en` **明令留空**
    #:    「不伪造创作内容」（`_reconcile_pack_conservation`）⇒ 本项**跳过**
    #:    `prompt_en` 为空／缺失的镜，绝不替占位镜补句（否则会把 `R27P` 的洞洗白）。
    #:    ⇒ 本项必须在守恒兜底**之前**执行，占位镜那时尚不存在，天然免疫。
    pack_en_camera_sentence_fill: bool = True

    #: **正文外观复述机械清洗**（**投影规则⑥**；项目方 2026-11-16 裁决批准）。
    #: `true` ＝ `shot_prompt` 段（形态 `pack`）产物在门禁判定**之前**，逐镜比对
    #: `prompt_zh`／`prompt_en` 的**正文**与包内自带 `characters[].appearance_lock_zh|_en`，
    #: 命中外观锚（判据 `R28 PACK_APPEARANCE_ECHO` 口径：中文 **连续 3 字**、英文 **连续 3 实词**）
    #: 即**删除命中所在的完整子句**，并在删后**用判据自身的函数复算**是否归零。
    #:
    #: ① **为什么必须机制化**（真机实证 2026-11-16）：`R28` **6/6 挂**，命中片段集中在
    #:    `潜水服`×25／`orange rescue suit`×7／`深蓝色`×3 —— 全是 3 字／3 实词的**最小窗口**，
    #:    靠模型改措辞无法稳定规避；而模板 `TPL-009`（§641-643）已明令「外观只在此处定义一次，
    #:    正文命中即删」，同模板又要求「正文密度下界」（八维双落地）⇒ 模型唯一逃逸口就是
    #:    服装/体型词。**措辞路线已到顶**（与投影规则⑤ 同性质的结论）。
    #: ② **性质＝投影规则⑥**（项目方 2026-11-16 裁决口径；与 ⑤ 同族、方向相反——⑤ 补格式、
    #:    ⑥ 删冗余）。允许边界**三条**：**只删命中锚的完整子句**（不做逐词手术、不改写句子）；
    #:    删后**必须用判据自身的函数复算**，仍命中则**放弃并如实登记**（`skipped_unresolvable`，
    #:    不许硬凑、不许掩盖）；**只改** `prompt_zh`／`prompt_en` 两个字段（`camera`／`duration_ms`／
    #:    `shot_id` 一字不动）。
    #: ③ **不删空保护**（硬要求）：删到「中文去空白后 <10 字」或「英文 <6 实词」⇒ **整镜回滚**
    #:    （`skipped_would_empty`，原文不动）——否则本机制会把 `R27`（正文非空／可读）的洞
    #:    洗成**新缺陷**，即用一个判据的绿去换另一个判据的红。
    #: ④ **跳过占位镜**（`skipped_placeholder`）：识别锚是 `notes` 以「服务层构造占位」开头
    #:    （＝`_reconcile_pack_conservation` 自己写的锚，也是判据 `R27P PLACEHOLDER` 的同一锚），
    #:    **整镜**不参与清洗。⚠️ 不用「`prompt_en` 为空」当判据——那也可能是**模型漏写**的真实镜，
    #:    其 `prompt_zh` 是模型创作内容、该被清洗；占位镜的 `prompt_zh` 则是服务层由 `action`
    #:    机械派生的，替它清洗既不增信息、又抹掉追溯线索。
    #: ⑤ **不静默**：逐镜留痕（镜号／语言／命中 gram／删除长度）＋ `merge_warnings` 一条；
    #:    留痕**不落原文**（照 `camera_amp_speed_normalize` 的纪律）。
    #: ⑥ **判据零改动**：3 字／3 实词阈值与 `R28` 本身一字未动，本项只是「产物不许复述外观」
    #:    这条既有义务在服务层被**机械执行**（模型义务未减，见 `TPL-009` guards）。
    #: ⑦ **回退**：`APP_PACK_APPEARANCE_ECHO_CLEAN=false`（回退后 `R28` 恢复纯靠模型自证）。
    pack_appearance_echo_clean: bool = True

    #: **交付包镜集合守恒兜底**（`T-101` r3 收口呈报·**裁决甲**，2026-11-07 项目方裁决）。
    #: `true` ＝ `shot_prompt` 段（形态 `pack`）产物在门禁判定**之前**，由服务层校验
    #: 「`shots[]` ⊇ 上游分镜镜集合」：上游有而本层缺的镜，**按上游镜定义补占位条目**
    #: （`camera`／`duration_ms`／`action`／`shot_language` 等机械承继字段照抄上游；
    #: `prompt_zh` 由 `action` 派生；**`prompt_en` 留空**——不伪造创作内容，交 `R34` 等
    #: 判据如实判）；`notes` 明写「服务层构造占位」。
    #:
    #: ⚠️ **为什么必须程序保证**（r2／r3 两批实证）：`uniqueItems` 不入引擎允许面 ⇒
    #:    `minItems` 管个数管不住互异；事后闸（裁决丙的 dup 检出）只能拦「已生成的
    #:    退化解」，拦不住「首轮无凑数、次轮才掉镜」（r3 on#01／on#08）——**集合守恒类
    #:    硬约束只能由构造保证**（与 `T-100` 的场覆盖构造保证同源）。
    #: ⚠️ **本开关与 `pack_derived_backfill` 的分工**：那个补「算术派生量」
    #:    （`meta.total_duration_ms`＝Σ 镜时长），这个补「集合守恒」（缺镜本身）；
    #:    本开关必须先于派生回填执行，否则补进来的镜不参与 Σ。
    #: ⚠️ **只补「上游有、本层缺」的镜**；本层凭空多出的镜（幻觉镜号）不删——那是
    #:    另一类错误，交 `R31` 逐镜比对如实判。
    #: ⚠️ **留痕**：每次补镜产生 `merge.shot_conservation_fill｜…` 告警（进
    #:    `merge_warnings`／run 记录），可离线统计模型真实漏镜率——兜底不洗白。
    pack_conservation_fill: bool = True

    #: **分镜段场内镜号序列回填**（`T-087` 余项；2026-11-05 落地，判据 `R8`）。
    #: `true` ＝ storyboard 段产物生成后，`shots[].shot_no` 由服务层按**数组序的场内
    #: 位置**重编（第 k 个 ⇒ `shot_no=k`；`TPL-010` 数量要求 1「shots 的顺序即
    #: 全片镜序」⇒ `shot_no` 是位置投影、由结构唯一决定）。
    #: `false` ＝ 不动产物（由 `R8` 如实判失败）。
    #:
    #: ⚠️ **为什么是派生量**：真基线实测（2026-11-04 冒烟 storyboard 第 2 轮）模型按
    #: **单元内**编号产出 `[1,1,2,2]`，且 `shot_no` 是**排序键**（`segment.py` 镜序、
    #: 导出 `E4`）——单元内编号会让场景级排序出现平键、兜底成**错序**。回填把排序键
    #: 修回与镜序一致；`shots` 数组序（创作声明）一字不动，模型原值完整留痕
    #: （`artifact["derived_backfill"]["shots[].shot_no"]["original"]`，按 `shot_id` 键控）。
    #: ⚠️ 口径与 `storyboard_derived_backfill`（`R14`）同构；`R8` 判据一字未动。
    #: ⚠️ **非整数 `scene_no` 不兜底**（场内分组语义已破坏 ⇒ 留痕 skip、交判据判）。
    storyboard_shot_no_backfill: bool = True

    #: **分镜段道具覆盖回填**（`T-087` 余项后续；2026-11-05 落地，判据 `R24`）。
    #: `true` ＝ storyboard 段产物生成后，剧本某场 `props_present` 非空而该场
    #: **无一镜**把它标进 `prop_refs` 时，由服务层把缺失的 `prop_id` 补进该场
    #: **首镜**（数组序第一个）的 `prop_refs`。
    #: `false` ＝ 不动产物（由 `R24` 如实判失败）。
    #:
    #: ⚠️ **为什么可以做**：道具「在场」由**上游剧本声明**（`props_present`），
    #:   分镜层的义务只是把它落到镜（`BR-03`「有道具入画必标」）；整场漏标时
    #:   「补进哪一镜」才是创作决策，**「该场至少一镜」本身是上游数据的逻辑
    #:   后承**——与 `R8` 位置投影同类（结构＋上游唯一决定的量）。承载镜约定为
    #:   **场首镜**（建立镜惯例：该场出场面的第一镜最可能拍到在场景物）。
    #: ⚠️ **与 `R14`/`R8` 的差异（如实标注）**：`R14` 是纯算术、`R8` 是纯位置投影，
    #:   本项是「**上游声明 × 场首镜约定**」的投影——**语义层**的派生，承载镜选择
    #:   是约定而非唯一真值。原值完整留痕
    #:   （`artifact["derived_backfill"]["shots[].prop_refs"]["original"]`，按 `shot_id` 键控）。
    #: ⚠️ **场无镜头不兜底**（3 镜吸引子等 ⇒ 留痕 skip、交 `R24`/场覆盖判据判）。
    #: ⚠️ 语义镜像 `validate_output.py` 的 `_upstream_props_by_scene`（剧本场键＝
    #:   `acts[].scenes[].no`／`scenes_outline[].no`；分镜镜键＝`scene_no`）。
    storyboard_prop_coverage_backfill: bool = True

    #: **分镜段逐场编排**（`T-100`／`PRO-014`；2026-11-05 授权代决落地）。
    #: `true` ＝ 分镜段按上游剧本的**场号清单**逐场调用（`scene:<no>`，每场一次），
    #: 场覆盖由**构造**保证（模型看不到别的场，无从省略）；`false` ＝ 维持现状整片一次调用。
    #:
    #: ✅ **2026-11-09 裁决 4 执行：默认翻 `true`**（项目方「确认翻开关」，`DEV-20261109-002`）。
    #: 依据＝回炉后 r4 复验批按 `PRO-015` §3.2 约定通过线判定通过
    #: （`pack_shots_lt_upstream` off=0/on=0、守恒轴三批首次归零、成本轴三批方向一致）。
    #: ⚠️ 历史口径留痕：本项属**生成行为改变**，曾与派生回填默认 `true` 刻意区分、按
    #:    「先跑只判不拦、观测够再翻」长期保持 `false`；翻默认**不改变行为代码**，只把
    #:    A/B on 臂的生效配置变成生产默认。回退＝`APP_STORYBOARD_SCENE_ORCHESTRATION=false`。
    #: ⚠️ 与 `quality_gate_enforce` **是两套开关**：翻本项不触发 ENFORCE（准入见 `PRO-011` §5）。
    storyboard_scene_orchestration: bool = True

    #: **分镜标识归一化**（`R7`/`R9` 派生量；`T-100` 配套，2026-11-05 授权代决落地）。
    #: `true` ＝ 合并后按「场号＋数组序」重编 `shot_id`（`S<场号两位>-SH<镜号三位>`）与
    #: `unit_id`（`U01..Un`），并同步 `units[].shot_ids`／`shots[].unit_id`。
    #:
    #: ⚠️ **为什么是派生量**：`shot_id` 是 `scene_no` 与序位的**纯函数**（`R7` 格式即写明），
    #: 与 `R8` 的 `shot_no` 同族；不归一化时，跨场重号的 `shot_id` 会被 `merge_segments` 的
    #: `setdefault` **静默丢弃**（丢哪一场取决于遍历顺序）。
    #: ⚠️ **`unit_id` 重编的前置**：本场 `units[].shot_ids` 与 `shots[].unit_id` 双向一致（`R9`）；
    #: 不一致时**不重编**（否则会把 `R9` 的错误洗白），只留痕 `skipped_unit_renumber`。
    storyboard_identity_normalize: bool = True

    #: **`camera.amp_speed` 机械清洗**（`T-103` 结构性档；2026-11-12 项目方裁决允许）。
    #: `true` ＝ 引擎响应归一化层对 `camera.move ∈ CFG-002.no_amplitude_no_speed`（`static`／`pov`）
    #: 的镜头**删除** `camera.amplitude`／`camera.speed` 两个键。
    #:
    #: ⚠️ **为什么允许改模型产物**：这两字段是枚举档位（机械字段，非创作内容），`static`／`pov`
    #: 语义上本无运镜幅度/速度；`xgrammar` 不支持 if-then 条件约束 ⇒ 生成期拦不住，
    #: 两次 attempt 均报、重试不可自愈（`DEV-20261109-005` §3 六码分诊）。
    #: ⚠️ **不静默**（裁决口径三件之二）：每个被清镜头都进 artifact
    #: `camera_amp_speed_normalize.items`（镜号／删的键／删前值／前后正文摘要），
    #: 并追加一条 `merge_warnings`，门禁报告可见「N 镜经机械清洗后通过」。
    #: 回退＝`APP_CAMERA_AMP_SPEED_NORMALIZE=false`（回退后 `static` 带幅速仍按原样 BLOCK）。
    camera_amp_speed_normalize: bool = True

    #: **`shot_prompt` 段级输入裁剪**（`T-101`／`PRO-015`，2026-11-05）。
    #: `true` ＝ `package_head`／`unit:<id>` 段的 `storyboard_json` 注入**按段裁剪的副本**
    #: （头部段去 `shots[]`；单元段只留本单元与本单元的镜），`script_json` 不裁。
    #:
    #: ✅ **2026-11-09 裁决 4 执行：默认翻 `true`**（`DEV-20261109-002`）。依据＝r4 复验批
    #:    按 `PRO-015` §3.2 约定线通过（回退判据三项全 0）＋ 项目方明确「确认翻开关」。
    #: ⚠️ 历史口径留痕：本项属**行为改变类**（模型输入变了 ⇒ 产出分布会变），曾按
    #:    「须 A/B 验收后才翻默认」长期保持 `false`；回退＝`APP_SHOT_PROMPT_SEGMENT_SCOPE=false`。
    #: ⚠️ A/B 器具 `_ab_t101.py` 的 off 臂**显式设本项为 false** ⇒ 翻默认不破坏后续 A/B
    #:    可复现性（`run_arm` 每臂覆盖 env ＋ `get_settings.cache_clear()`）。
    #: ⚠️ 与 `quality_gate_enforce` **是两套开关**：翻本项不触发 ENFORCE（准入见 `PRO-011` §5）。
    #: ⚠️ 动机（实测，`PRO-015` §1）：885s 轮 completion 39,006 tokens 而合并产物仅
    #:    ≈6K tokens——每段都把整份上游重写一遍（膨胀 ≈6×）；裁掉「看得见的别人家」
    #:    ⇒ 越界重写失去素材。门禁跨层判据（`R23`/`R24`/`R31`）喂的是上游**原文**
    #:    （`gate_upstream`，裁剪前已另行保存），不受影响。
    #: ⚠️ 解析失败／uid 不中 ⇒ 原样整份注入＋留痕（不猜测、不静默）。
    shot_prompt_segment_scope: bool = True

    #: **分段最小镜数**（`丙`，2026-11-17；`DEV-20261117-003`／`-004` 的后续方案）。
    #: `auto` 分段时把**相邻单元攒成每段 ≥ 本值镜**的组（段名 `unit:U01+U02`），
    #: `0`／`1` ＝ 关（维持「每单元一段」旧行为，生产默认 ⇒ 行为零变化）。
    #: ⚠️ **要解决什么**：2 镜单元单独成段时，单元级运镜多样性门槛（`need=2`）要求
    #: **两镜全异**，而该段只有 2 镜可分配 ⇒ 实测最易失守（基线 10 轮人工复核率 44.4%、
    #: 甲试点盲重试救回 0/4 均集中在此）。组段让每次调用至少 3 镜可分配。
    #: ⚠️ **不改变单元级判据**：单元仍是 2–3 镜（`TPL-008` BR-11），判据一个字未动；
    #: 本项只改**调用粒度**。末组可能 < 本值（余数无处可并），如实保留并留痕。
    #: ⚠️ 上游 `units[]` 与镜数无法对齐（`unit_shot_counts_of` 返回空）时**退回逐单元**，
    #: 不猜测、不静默凑组。
    segment_plan_min_shots: int = 0


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
    #: ⚠️ 覆盖**只针对服务层域字段**；模型可影响的字段（`title`／`notes`／
    #: `shots`／`units`…）**一字不改**（本工程第一纪律：不改写模型输出）。
    #: ⚠️ `total_duration_ms` **不在本开关内**（2026-11-04 起）：它是**派生量**，
    #: 由 `storyboard_derived_backfill` 单独控制（见该开关的注释）。
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
