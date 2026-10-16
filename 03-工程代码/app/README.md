# 服务端工程骨架（交付物 `D-005` 一期）

> **AI 漫剧剧本与分镜提示词生成系统** 的服务端骨架。
> 对应任务 **`T-003`**（见 `12-项目管理/PM-001_任务清单.md` §1 关键路径）。
>
> 本目录下全部 `*.py`／`pyproject.toml`／`.env.example`／本文件均属
> `13-项目配置管理/CM-002_文件取号表.md` §3 **豁免命名**（代码由版本控制与目录结构管理），
> **不取号、不改名**。

---

## 一、这一层解决什么

提示词资产（`../prompts/`）回答「模型该收到什么指令」，交付契约（`../delivery/`）回答
「产物该长什么样」；**本层回答「这两者如何被编排起来对外服务」**——即
`REQ-005` §1 的「任务对话编排引擎」与 §3 的接口需求。

本批（`T-003` 一期）交付一个**可运行的最小闭环**：

| 能力 | 需求编号 | 状态 |
| --- | --- | --- |
| 任务对话状态机（七阶段流转 + 回退 + 确认门控） | SW-001 / SW-003 | ✅ 已实现 |
| 对话式修改入口 | SW-002 | ✅ 已实现（对接 `modify_v1`） |
| `SW-I01` 任务对话接口 | SW-I01 | ✅ 已实现 |
| `SW-I02` 生成任务接口 | SW-I02 | ✅ 已实现（**mock 后端**） |
| `SW-I06` 统一错误信封 | SW-I06 | ✅ 已实现（全接口共用） |
| 提示词模板加载器（读取 `../prompts/`） | — | ✅ 已实现 |
| `pack_meta` 服务层注入 | SW-012 前置 | ✅ 已实现 |
| `SW-I03` 内容安全双闸（输入／输出／注入／拒答） | SW-009 / SW-010 / SW-011 / SW-017 | ✅ **已实现并挂上生成链路**（`T-005`） |
| `SW-I04` 交付包 / `SW-I05` 认证 / `SW-I08` 导出 | — | ⏳ **占位**（显式 501） |

> ⚠️ **占位接口返回 501，不静默放行**——「宁可显式报未接入，也不给一个看起来通过、
> 实则未经检测的结论」。这是本工程的一贯口径。

---

## 二、目录结构

```
app/
├── main.py                    # 应用装配：配置 → 资产 → 服务 → 中间件 → 路由
├── core/
│   ├── config.py              # Settings：环境变量集中校验、启动快速失败
│   ├── errors.py              # 类型化错误体系 + 统一错误信封（SW-I06）
│   ├── logging.py             # JSON 结构化日志 + request_id 上下文
│   └── middleware.py          # 请求 ID 贯穿 + 访问日志
├── api/
│   ├── deps.py                # 依赖注入（从 app.state 取服务）
│   └── v1/
│       ├── router.py          # v1 路由汇总（含「端点 ↔ 需求编号」索引）
│       └── endpoints/
│           ├── dialogue.py    # SW-I01 任务对话
│           ├── tasks.py       # SW-I02 生成任务
│           ├── safety.py      # SW-I03（双闸端点，判定在 services/safety_service.py）
│           ├── delivery.py    # SW-I04（占位）
│           ├── auth.py        # SW-I05（占位）
│           ├── export.py      # SW-I08（占位）
│           └── health.py      # /health /ready
├── schemas/                   # 对外契约（请求／响应／错误）
├── services/
│   ├── state_machine.py       # 七阶段状态机（纯函数，可脱网单测）
│   ├── dialogue_service.py    # 会话编排（分段调用 / 安全双闸 / 形态闸 / 内容足量探测）
│   ├── artifact_contract.py   # **链路产物形态契约（运行期唯一真值）** ← `ISSUE-042` 根治
│   ├── output_schema.py       # 输出契约 schema 的来源（契约文件型 + 派生型，同一入口）
│   ├── segment.py             # 分段计划、分段产物解析与结构合并
│   ├── safety_service.py      # 内容安全双闸判定（SW-009/010/011/017）
│   ├── content_adequacy.py    # 产物**内容足量性**探测（**只判不拦**）← `ISSUE-045`
│   └── pack_meta.py           # 交付包元数据装配（服务层注入）
├── repositories/
│   └── session_repo.py        # 会话存储（本批：内存）
├── inference/
│   ├── base.py                # TextGenerator 抽象（可替换是架构底线）
│   ├── registry.py            # 按名解析后端
│   ├── vllm_backend.py        # vLLM OpenAI 兼容后端（受约束解码形态收敛于此）
│   └── mock_backend.py        # 确定性 mock 后端（**回包形态须合规**，见 artifact_contract）
├── prompts/
│   └── loader.py              # 提示词模板加载器（只读）
└── tests/                     # 216 项自动化测试
```

⚠️ **产物契约的「结构」与「内容」两层（分字段留痕，不得合并）**：链路四段既有**结构**判据、
也有**内容**判据，二者**运行位置相同、执行后果不同**——

**（一）结构层 —— 可阻断**（`ISSUE-042` 根治，`services/artifact_contract.py`）：
链路四段的产物形态真值集中在 `artifact_contract.py`（来源登记为 `prompts/validate_output.py`
的 `detect_shape` 与 **R5**，`pack` 复用 `segment.REQUIRED_TOP_KEYS`）。**三条通路共用同一份真值**：
① **受约束解码**（`output_schema.load_engine_schema` 对 `synopsis`/`script`/`storyboard`
返回派生 schema，此前这三段无任何约束 ⇒ 模型可产出截断 JSON）；
② **生成后形态闸**（`dialogue_service._guard_artifact_shape`，单段/多段同一条路径）；
③ **上游准入闸**（`_admit_upstream`，禁止「拿不可解析的上游继续生成」）。
受控旁路开关 `APP_SHAPE_GATE_ENFORCE`（默认 `true`；置 `false` 时照样判定与留痕、仅不阻断）。

**（二）内容层 —— 只判不拦**（`ISSUE-045`，`services/content_adequacy.py`）：
形态闸判的是「能不能解析、顶层键齐不齐」，**判不出「算得对不对、覆盖全不全」**——
实测「合法 JSON ＋ 严重欠生成」（剧本 1 幕 1 场 15 秒却自报 108 秒；分镜 3 镜只覆盖第 1 场、
第 2~5 场全漏拍且 `unspecified` 无记）能整整齐齐穿过全部三道闸。故另设本模块判
**算术自洽**（剧本 `Σ场秒` vs `total_est_seconds`；分镜 `Σ镜头时长` vs `total_duration_ms`）
与**场覆盖度**，结论只进日志与产物留痕的 `content_adequacy` 字段
（`checked`/`ok`/`findings`/`metrics`）——⚠️ **永不阻断**：真实模型产物普遍不自洽
（四轮真跑中凡产出分镜者时长**无一轮守恒**），设阻断会让整条链路不可用。

⚠️ **上游紧凑化按段适用**（`ISSUE-044`，`APP_PROMPT_COMPACT_UPSTREAM` ＋ `APP_PROMPT_COMPACT_STAGES`）：
`ISSUE-037` 方案 D 引入的**无损紧凑化**（只去 JSON 空白）此后**只对配置里登记的阶段**生效，
默认 `shot_prompt`。依据是实测：该变换的**唯一动机**是「渲染输入超窗」，而只有 `shot_prompt`
段会超（未紧凑 58,550 > 32,768）；`storyboard` 段输入仅 12,214 tokens、**不需要**它。

**（三）质量层 —— 可阻断，当前「分阶段上线」**（`T-086`／`ISSUE-038` 的链路侧一半，
`services/quality_gate.py` ＋ `services/pack_meta.py`）：
在**生成后、入库前**调用**工程侧门禁**（判据唯一来源 `prompts/validate_output.py` 的 `R1~R40`，
服务层**不抄第二份**）与**交付侧门禁**（`delivery/validate_pack.py` 的 `BLOCK`）——
形态闸管**结构**，本层管**质量**，两层都要。配套三件事：

① **不过即重试**：按段定位失败段后重跑（`APP_QUALITY_GATE_RETRY_SCOPE=segment`），
上限 `APP_QUALITY_GATE_MAX_ATTEMPTS`。⚠️ **重试不得使结果变差** —— 次轮结构非法时
**回退**到首轮合法产物，留痕 `retry_degraded_fallback`；用尽重试仍不过则**如实拒绝**
（`enforce=true`）或**如实留痕**（`enforce=false`），**绝不以放行或后处理修补兜底**。
② **服务层真值覆盖**（`APP_SERVICE_TRUTH_OVERRIDE`）：交付包的 `meta` 与 `aigc_meta.AIGC`
由服务层以自己算出的值**强制覆盖**，模型自拟值一律丢弃。动因是实测发现的**假合规**——
服务层留的占位（`safety_check:"占位（…）"`）被模型换成了看起来已通过的 `"passed"`（还带时间戳）：
**假值会通过门禁，比缺失更危险**。
③ **三态判定**：门禁结论的 `ok` 是 `True`/`False`/**`None`（无法判定）** 三态，
「判过且通过」与「根本没判」在留痕里**必须可分**（`checked` 与 `ok` 分列）。

⚠️ 两个开关默认**关**（`APP_QUALITY_GATE_ENFORCE=false`、`APP_QUALITY_GATE_RETRY_ENABLED=false`）：
实测产物级直出率 `passed=true` ＝ **0/3**，此刻就拦会让四段生成大概率全部被拒、链路不可用；
开着重试则每段跑两遍（`shot_prompt` 单段约 304 s）。⇒ **先把回路建成并用真实数据检验**，
待 `T-087`（资产侧提质）把直出率抬起来再打开。⚠️ 关着时**判定照常执行并留痕**，**不得静默**。

分层参照 `01-架构设计/ARCH-003_…模型框架设计说明书.md` §3.4；
**服务层不引用 Request/Response**，可直接单测。

---

## 三、运行与测试

```bash
# 依赖（见 pyproject.toml；AGENTS 环境下的解释器路径）
pip install -e ".[dev]"

# ⚠️ 在 03-工程代码/ 下启动（**包根是 app/ 的上一级**）：
#    app/ 目录本身即 app 包（含 __init__.py）；在 app/ 下执行会 import 不到而报
#    ModuleNotFoundError: No module named 'app'（pytest 因 pyproject 里 pythonpath=[".."] 不受影响）。
cd 03-工程代码
uvicorn app.main:app --reload --port 8000

# 运行测试（在 03-工程代码/app 下）
cd app && pytest
```

配置项全部来自环境变量（`APP_*`），样例见 `.env.example`。
**密钥与真实企业标识一律不落文件**；未提供时 `pack_meta` 写占位符并登记，**绝不自拟假值**。

---

## 四、状态机（本层的核心）

```
待梗概 ──生成──> 梗概修改 ──确认──> 梗概确认 ──> 待剧本 ──> 待分镜 ──> 待提示词 ──> 已完成
                  ↑                    │
                  └────── 回退 ────────┴──── 可回退到任意前置阶段
```

两点设计说明：

1. **门控是数据结构，不是 if 判断**。`TRANSITIONS` 把每一对相邻阶段映射到一个动作
   （`generate` / `confirm` / `advance`）。从「梗概修改」出发的唯一合法转移是 `confirm`，
   因此「未经确认就进入剧本阶段」在**结构上不可能**发生——不依赖开发者记得写判断。
2. **回退不是重置**。回退只改当前阶段，**已确认的梗概快照保留**，供下游重新生成时对照。

驱动它的接口是 `SW-I01`：

| 端点 | 语义 |
| --- | --- |
| `POST /api/v1/sessions` | 建会话，落「待梗概」 |
| `POST /api/v1/sessions/{id}/advance` | 推进一步（可能触发一次生成）；需确认时返回 `409 CONFIRMATION_REQUIRED` |
| `POST /api/v1/sessions/{id}/confirm` | 执行确认并固化快照 |
| `POST /api/v1/sessions/{id}/rollback` | 回退到前置阶段 |
| `POST /api/v1/sessions/{id}/revise` | 对话式修改（改产物、不改阶段） |

---

## 五、已知边界（如实登记，不作掩饰）

- **推理后端是 mock**：输出为确定性占位 JSON，带 `_mock: true` 标记，
  **不可能被误当作真实产物**。接入 vLLM 见 `T-012` / `T-004`，切换只改
  `APP_INFERENCE_BACKEND`，**业务代码零改动**。
- **会话存内存**：进程重启即丢；替换为 PostgreSQL + Redis 见 `T-004` 及二期，
  仓储接口保持不变。
- **无认证**：`SW-I05` 未接入（二期），当前接口无鉴权，**不得直接对外暴露**。
- **内容安全双闸已接入，且挂在生成链路上**（`T-005`）：输入前置检测（`SW-009`）＋ 提示注入防护（`SW-011`）
  在**调用推理后端之前**执行；输出复检（`SW-010`）在**产物落槽之前**执行；命中时编排层抛
  `GUARD_INPUT_BLOCKED`（422）／`GUARD_OUTPUT_BLOCKED`（451）；拒答话术（`SW-017`）由服务层内置、**不依赖模型**。
  判定只记**分类码与计数**，**不落命中词明文**。⚠️ **仍有两条上线前必须确认**：① **受控词库须真实到位**
  （`T-020` / `T-058`）——未到位时检测覆盖不完整 ⇒ `degraded=true` ⇒ **fail-closed 拒绝放行**；
  ② `APP_GUARD_ENFORCE`（默认 `true`）控制**是否阻断**，联调期可置 `false`——此时**检测与留痕照常，仅不阻断**。
  **在①②都确认前，本服务仍不具备上线合规条件。**
- **`pack_meta` 的备案关联字段为占位符**（`{{PROVIDER_CODE}}` / `{{STATEMENT_ID}}`）：
  部署环境须注入真实值，否则交付包与生成记录的反查链**显式中断**。

---

## 六、下一步

| 任务 | 内容 |
| --- | --- |
| `T-004` | 把 `../prompts/` 的五个业务模板真正接入（替换 mock），打通五段生成闭环 —— 🟦 **收尾中**：主链前两段已真跑通过，第 3／4 段待引擎提窗后重跑（`ISSUE-032`） |
| `T-005` | 内容安全双闸接入（`SW-I03`）—— ✅ **已落地**（端点 ＋ **生成链路挂闸**），见 §五「已知边界」 |
| `T-006` | 生成标识与交付四件套（`SW-I04`），复用 `../delivery/` 既有 Schema 与素材 |

台账见 `12-项目管理/PM-001_任务清单.md`；本批留痕见
`11-过程文档/开发历史/DEV-20261014-017-*.md`。
