# 生成合成类（文本合成）算法模型框架设计说明书

| 项目 | 内容 |
| --- | --- |
| 文档名称 | 生成合成类（文本合成）算法模型框架设计说明书 |
| 算法类别 | 生成合成类 |
| 合成模态 | 文本 |
| 技术栈 | Python 3.11+ / FastAPI / PostgreSQL / Redis / vLLM |
| 文档版本 | V1.0 |
| 密级 | 内部 |
| 适用阶段 | 架构设计 → 工程实现 → 算法备案 |

---

## 1 概述

### 1.1 编写目的

本文档定义一套**生成合成类（文本合成）算法**的模型框架，用于指导工程实现、服务部署与算法备案。文档给出算法基本原理、总体分层架构、模块职责边界、核心流程与数据流、接口契约、关键机制、数据模型、部署拓扑、安全合规要求与核心伪代码，使研发、测试、运维与合规人员在同一套定义下协作。

### 1.2 适用范围

适用于以下文本合成场景（对外统一为四类任务）：

| 任务类型 | `task_type` | 说明 | 典型输入 → 输出 |
| --- | --- | --- | --- |
| 内容生成 | `generate` | 依据指令生成全新文本 | 指令 + 素材 → 文章/文案/回复 |
| 摘要归纳 | `summarize` | 对长文本压缩与要点提取 | 长文 → 摘要/要点列表 |
| 改写润色 | `rewrite` | 风格迁移、扩写、精简、纠错 | 原文 + 目标风格 → 改写文本 |
| 结构化抽取 | `extract` | 按 Schema 输出结构化字段 | 文本 + JSON Schema → JSON |

**不适用范围**：图像/音视频合成、语音克隆、非文本模态的深度合成——本框架在模型适配层预留扩展点，但不在本次设计范围内。

### 1.3 术语与缩略语

| 术语 | 说明 |
| --- | --- |
| 文本合成 | 由算法模型基于输入提示自动生成、改写或归纳自然语言文本的行为 |
| 自回归生成 | 按时间步逐 token 生成，每步以前序 token 为条件 |
| Token | 文本经分词器切分后的最小建模单元 |
| Prompt / 提示 | 送入模型的指令、上下文与素材的统称 |
| SFT | 有监督微调（Supervised Fine-Tuning） |
| 偏好对齐 | RLHF / DPO，使模型输出符合人类偏好与安全要求 |
| KV Cache | 缓存历史 Key/Value 张量，避免解码阶段重复计算 |
| 采样策略 | 温度、Top-k、Top-p、重复惩罚等解码参数组合 |
| 护栏（Guardrail） | 输入/输出的内容安全与合规校验机制 |
| RAG | 检索增强生成（Retrieval-Augmented Generation） |
| TTFT | 首 Token 时延（Time To First Token） |
| 显式标识 | 面向用户的可见 AI 生成标注 |
| 隐式标识 | 写在元数据中的生成来源标识 |

### 1.4 设计原则

1. **分层解耦**：控制器不写业务逻辑，服务层不依赖 HTTP 对象，仓储层不外泄 SQL 细节；模型后端通过抽象接口可替换。
2. **边界校验**：所有外部输入在入口处一次性校验并归一化，绝不相信客户端参数。
3. **快速失败 + 集中配置**：全部配置来自环境变量，启动时集中校验，缺失关键项直接拒绝启动。
4. **可观测可审计**：结构化 JSON 日志贯穿请求 ID，每一次合成留痕，满足备案与追溯要求。
5. **合规内建**：内容安全、生成标识、数据留存作为框架一等公民，而非事后补丁。
6. **成本可控**：Token 预算、配额、缓存与批处理形成闭环，避免算力失控。

---

## 2 算法基本原理

### 2.1 生成式建模范式

文本合成算法以**自回归语言模型**为核心，将整段文本的联合概率按链式法则分解为逐 token 条件概率的乘积：

```
P(x₁, x₂, ..., x_T | c) = ∏_{t=1}^{T} P(x_t | x₁...x_{t-1}, c)
```

其中 `c` 为条件信息（系统指令、用户提示、检索到的外部知识）。模型训练目标为最小化负对数似然（等价于交叉熵）：

```
L(θ) = - (1/N) Σ Σ log P(x_t | x_<t, c; θ)
```

推理阶段即**条件采样**：给定 `c`，按 `P(x_t | x_<t, c; θ)` 逐步采样，直到生成结束符或达到长度上限。

<!--FIG:PIPELINE-->

### 2.2 模型网络结构

主干采用 **Decoder-only Transformer**，核心构件与作用如下：

| 构件 | 作用 | 本框架的取值取向 |
| --- | --- | --- |
| 词嵌入 + 位置编码 | 将 token 映射为向量并注入位置信息 | RoPE 旋转位置编码，外推能力好 |
| 多头自注意力 | 建立 token 间长程依赖 | 因果掩码，GQA 分组查询注意力降低 KV 显存 |
| 前馈网络 | 逐位置非线性变换 | SwiGLU 激活 |
| 归一化 | 稳定深层训练 | Pre-Norm + RMSNorm |
| 输出投影 | 映射回词表分布 | 与嵌入权重共享（可选） |

单头注意力形式为 `Attention(Q,K,V) = softmax(QKᵀ/√d_k + M)V`，其中 `M` 为因果掩码（上三角置 −∞），保证位置 `t` 只能看到 `≤ t` 的上下文。

### 2.3 三阶段训练流程

| 阶段 | 数据 | 目标 | 产出 |
| --- | --- | --- | --- |
| ① 预训练 | 海量通用文本（万亿 token 级） | 学习语言规律与世界知识 | 基座模型（Base） |
| ② 有监督微调 SFT | 高质量「指令—回答」对 | 学会遵循指令、输出规范格式 | 指令模型（Instruct） |
| ③ 偏好对齐 | 人类偏好对比数据 | 输出更有用、更诚实、更安全 | 对齐模型（Aligned） |

阶段③可选用 RLHF（训练奖励模型 + PPO 优化）或 DPO（直接在偏好对上做对比优化，工程更简单、训练更稳定）。**本框架默认采用 DPO 路线**，训练链路短、无需在线采样，便于在有限算力下完成迭代。

此外支持 **LoRA / QLoRA 参数高效微调**：冻结主干权重，仅训练低秩适配矩阵。适配器体积通常为原模型的 0.1%–1%，可按租户/场景热插拔，是实现「一套主干 + 多业务人格」的关键手段。

### 2.4 条件合成与可控生成

文本合成的可控性由四个层次的干预实现，从弱到强：

1. **提示工程**：系统指令 + 少样本示例 + 输出格式约定；
2. **结构化约束解码**：以 JSON Schema 编译为有限状态机，在每一步屏蔽不合法 token，保证输出严格可解析（用于 `extract`、`generate` 的结构化模式）；
3. **检索增强（RAG）**：将外部知识库检索片段拼入上下文，降低事实性幻觉，并让回答可溯源；
4. **参数微调**：LoRA 适配器固化领域风格与术语体系。

### 2.5 解码采样策略

| 策略 | 形式 | 适用场景 |
| --- | --- | --- |
| 贪心 | 每步取 argmax | 抽取、格式化输出（确定性要求高） |
| Beam Search | 维护 k 条候选序列 | 翻译、摘要（质量优先，吞吐低） |
| 温度采样 | `p_i ∝ exp(z_i / T)` | 创意写作（T 调高多样性，T→0 退化为贪心） |
| Top-k | 仅保留概率最高的 k 个 token | 抑制长尾噪声 |
| Top-p（核采样） | 保留累积概率达 p 的最小集合 | 自适应候选集大小，**默认推荐** |
| 重复惩罚 | 对已出现 token 施加惩罚 | 抑制复读与循环 |

默认参数组合：`temperature=0.7, top_p=0.9, top_k=50, repetition_penalty=1.05`。摘要类任务默认降为 `temperature=0.3`，抽取类任务默认 `temperature=0`（贪心/约束解码）。

### 2.6 复杂度与资源特征

- 每生成 1 个 token 的计算量约为 `2 × N_params` FLOPs；
- KV Cache 显存：`2 × n_layers × n_kv_heads × d_head × seq_len × batch × dtype_bytes`；
- 推理两阶段特征不同：**Prefill**（处理输入）受算力约束、并行度高；**Decode**（逐 token）受显存带宽约束、并行度低。

> 这两点直接决定了架构决策：使用 **连续批处理 + PagedAttention** 的推理引擎（vLLM）提升 GPU 利用率；对长文本与批量任务走**异步队列**而非同步接口。

---

## 3 总体架构设计

### 3.1 分层架构总览

<!--FIG:LAYERED-->

五层职责如下：

| 层次 | 职责 | 关键约束 |
| --- | --- | --- |
| 1 接入层 | TLS 终结、认证鉴权、租户识别、全局限流、CORS | 不含业务逻辑；拒绝匿名穿透 |
| 2 编排层（控制器） | 参数校验、任务分发、响应格式化、SSE 推流 | 只做 HTTP 语义转换 |
| 3 服务层 | 合成编排：护栏 → 缓存 → 配额 → 推理 → 落库 | 不引用 Request/Response，可直接单测 |
| 4 模型层 | 后端适配、提示构建、采样解码、约束解码 | 通过抽象接口隔离具体引擎 |
| 5 基础设施层 | 数据库、缓存、队列、对象存储、模型仓库、可观测 | 全部配置化 |

### 3.2 模块清单与职责边界

| 模块 | 职责 | 依赖方向 |
| --- | --- | --- |
| `api.v1.endpoints.synthesis` | 解析请求、调用服务、组装响应 | → services |
| `api.v1.endpoints.tasks` | 异步任务提交/查询/取消 | → services |
| `services.synthesis_service` | 合成主流程编排，事务边界 | → guardrail / cache / quota / inference / repositories |
| `services.guardrail_service` | 输入输出内容安全校验与标识注入 | → guardrail 引擎 |
| `services.quota_service` | 租户级 QPS 与 Token 日配额 | → Redis |
| `services.cache_service` | 精确缓存（prompt 哈希）+ 语义缓存 | → Redis |
| `inference.registry` | 按模型名解析后端实例 | → backend 实现 |
| `inference.base.TextGenerator` | 统一推理抽象（`generate` / `stream`） | 被 services 依赖 |
| `inference.sampling` | 采样与惩罚逻辑、约束解码钩子 | → tokenizer / logits processor |
| `repositories.*` | 数据读写，批量查询避免 N+1 | → ORM |
| `workers.tasks` | 异步合成、结果归档、审计写盘 | → 同服务层能力 |

### 3.3 技术选型

| 层次 | 选型 | 版本取向 | 选型理由 |
| --- | --- | --- | --- |
| 语言 | Python | 3.11+ | AI 生态最完善，异步能力强 |
| Web 框架 | FastAPI | 0.115+ | 原生 async、Pydantic 校验、自动 OpenAPI |
| ASGI 服务器 | Uvicorn + Gunicorn | 最新稳定 | 多进程 + 协程，适配异步 IO |
| 数据校验 | Pydantic | v2 | Rust 内核，性能与类型安全兼顾 |
| 配置管理 | pydantic-settings | v2 | 环境变量集中校验、启动快速失败 |
| 数据库 | PostgreSQL | 16 | JSONB 存参数、事务可靠、生态成熟 |
| ORM / 迁移 | SQLAlchemy 2.0 (async) + Alembic | — | 异步驱动 + 可回滚迁移 |
| 缓存 / 限流 | Redis | 7 | 令牌桶限流、TTL 缓存、幂等键 |
| 异步任务 | Arq（或 Celery） | — | 轻量、原生 async、Redis broker |
| 推理引擎 | vLLM | 0.6+ | PagedAttention + 连续批处理，吞吐高 |
| 模型格式 | Safetensors | — | 安全、加载快、零拷贝 |
| 观测 | structlog + prometheus-client + OpenTelemetry | — | 结构化日志、指标、链路追踪 |
| 测试 | pytest + httpx + testcontainers | — | 单测 mock 仓储，集成用真实库 |
| 部署 | Docker + Kubernetes | — | GPU 节点与 API 节点分离调度 |

> 引入依赖前请核对 `pyproject.toml` 是否已声明；缺失时按上表补入，避免运行时缺包。

### 3.4 工程目录结构（按功能组织 + 三层）

```
text-synthesis-framework/
├── app/
│   ├── main.py                      # 应用入口：装配路由、中间件、异常处理器
│   ├── core/                        # 基础设施（跨功能）
│   │   ├── config.py                # Settings：环境变量集中校验
│   │   ├── logging.py               # structlog 配置，注入 request_id
│   │   ├── errors.py                # 类型化错误体系
│   │   ├── middleware.py            # 请求ID、访问日志、异常兜底
│   │   └── security.py              # JWT 解析、租户与 scope 校验
│   ├── api/v1/
│   │   ├── router.py
│   │   └── endpoints/
│   │       ├── synthesis.py         # 控制器：同步 / 流式
│   │       ├── tasks.py             # 控制器：异步任务
│   │       └── health.py            # /health /ready /metrics
│   ├── schemas/                     # 对外契约（请求/响应/错误）
│   │   ├── synthesis.py
│   │   ├── task.py
│   │   └── common.py
│   ├── services/                    # 服务层：业务编排
│   │   ├── synthesis_service.py
│   │   ├── guardrail_service.py
│   │   ├── quota_service.py
│   │   └── cache_service.py
│   ├── inference/                   # 模型层：适配与解码
│   │   ├── base.py                  # TextGenerator 抽象接口
│   │   ├── registry.py              # 模型 → 后端解析
│   │   ├── vllm_backend.py
│   │   ├── local_backend.py         # transformers 兜底
│   │   ├── remote_backend.py        # 第三方 API 适配
│   │   ├── sampling.py              # 采样与 logits 处理
│   │   └── constraints.py           # JSON Schema → FSM 约束解码
│   ├── repositories/                # 数据访问层
│   │   ├── generation_repo.py
│   │   ├── task_repo.py
│   │   ├── model_repo.py
│   │   └── audit_repo.py
│   ├── models/                      # ORM 实体
│   ├── workers/                     # 后台任务
│   │   ├── settings.py
│   │   └── tasks.py
│   └── prompts/                     # 提示模板（带版本号）
├── migrations/versions/             # Alembic 迁移脚本
├── tests/{unit,integration}/
├── deploy/{Dockerfile,k8s/}
├── .env.example                     # 仅占位值
├── pyproject.toml
└── README.md
```

---

## 4 核心流程设计

### 4.1 同步短文本合成

适用：输入 ≤ 8K 字符、期望在数秒内返回的单次合成。

<!--FIG:SEQ_SYNC-->

编排步骤（服务层 `synthesis_service.synthesize`）：

1. 由控制器完成 Pydantic 校验（长度、枚举、参数区间）；
2. **输入护栏**：敏感内容检测、提示注入特征识别；命中则直接返回 `GUARD_INPUT_BLOCKED`，不消耗模型算力；
3. **配额校验**：Redis 令牌桶（QPS）+ 日 Token 配额双校验；
4. **幂等与缓存**：以 `idempotency_key` 判重；以 `hash(model + params + 归一化prompt)` 查精确缓存，命中则直接返回并标注 `cache_hit`；
5. **提示构建**：渲染版本化模板，拼装系统指令、少样本示例、检索片段与用户输入；
6. **推理调用**：经 `inference.registry` 解析后端，执行采样解码；多步写入置于事务内；
7. **输出护栏**：内容安全复检 + **生成标识注入**（显式标注 + 隐式元数据）；
8. **持久化与留痕**：写入 `generations` 与 `audit_logs`，记录 Token 用量、时延分解与安全标签。

### 4.2 流式合成（SSE）

长文本生成（>500 token）建议走流式，显著改善体验。协议采用 `text/event-stream`，事件类型：

| 事件 | 载荷 | 说明 |
| --- | --- | --- |
| `start` | `{request_id, model, task_id}` | 建立连接后首帧 |
| `delta` | `{text}` | 增量文本片段 |
| `usage` | `{prompt_tokens, completion_tokens}` | 用量统计 |
| `safety` | `{decision, labels}` | 安全判定结果 |
| `done` | `{finish_reason, latency_ms}` | 正常结束 |
| `error` | `{code, message, retryable}` | 异常终止 |

关键工程点：

- **分段安全校验**：按句/段边界累积缓冲，仅对完整语义单元做输出护栏，避免逐 token 调用带来的延迟与误判；
- **客户端断连处理**：监听 `request.is_disconnected()`，立即取消后端生成，防止 GPU 空转；
- **心跳保活**：网关空闲超时前每 15s 发送注释帧 `:ping`。

### 4.3 异步长文本 / 批量合成

触发条件（任一满足即转异步）：输入 > 8K 字符、`max_tokens` > 2K、批量条数 > 1、`temperature=0` 且需约束解码的重型抽取。

<!--FIG:SEQ_ASYNC-->

- 控制器立即返回 `202 Accepted` + `task_id`，业务侧凭 `task_id` 轮询或订阅；
- Worker 从队列取任务，执行与同步流程相同的服务层逻辑（**同一份代码，仅调用入口不同**）；
- 任务**幂等**：以 `idempotency_key` 唯一约束防重复入队；失败重试采用指数退避，最多 3 次，超限进入死信队列并记录 `error_code`；
- 单任务分片：批量任务拆为子任务并行，主任务汇总后写回 `result_ref`（对象存储路径）。

### 4.4 检索增强分支（RAG）

当请求携带 `context.documents` 或租户配置了知识库时启用：

1. 对输入做查询改写（可选，复用同一模型的小样本能力）；
2. 向量检索 Top-K 片段 + 关键词检索，结果做 RRF 融合与重排；
3. 片段按「标题 + 来源 + 正文」结构化拼入上下文，并注入引用编号要求；
4. 输出后置校验：抽取引用编号，沿用到响应的 `citations` 字段，实现**可溯源**。

> 上下文预算控制：`prompt_tokens ≤ 0.6 × 模型上下文窗口`，超出按重排得分截断，避免挤占生成长度。

---

## 5 接口设计

### 5.1 端点清单

| 方法 | 路径 | 说明 | 认证 | 幂等 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/syntheses` | 同步合成 | Bearer JWT | 支持 `Idempotency-Key` |
| POST | `/api/v1/syntheses:stream` | SSE 流式合成 | Bearer JWT | 否 |
| POST | `/api/v1/tasks` | 提交异步合成任务 | Bearer JWT | 支持 `Idempotency-Key` |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态与用量 | Bearer JWT | — |
| GET | `/api/v1/tasks/{task_id}/result` | 获取任务结果 | Bearer JWT | — |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消排队中任务 | Bearer JWT | — |
| GET | `/api/v1/models` | 可用模型与能力清单 | Bearer JWT | — |
| GET | `/health` | 存活探针 | 无 | — |
| GET | `/ready` | 就绪探针（含 DB/Redis/模型后端） | 无 | — |
| GET | `/metrics` | Prometheus 指标 | 内网 | — |

### 5.2 请求 / 响应契约

请求体（Pydantic `SynthesisRequest`）：

```json
{
  "task_type": "summarize",
  "model": "pcxx-text-7b-instruct",
  "input": {
    "text": "……待处理的长文本……",
    "instruction": "提炼 5 条要点，每条不超过 30 字"
  },
  "params": {
    "temperature": 0.3,
    "top_p": 0.9,
    "top_k": 50,
    "max_tokens": 1024,
    "repetition_penalty": 1.05,
    "stop": ["\n\n\n"]
  },
  "output": { "format": "text", "schema": null },
  "context": { "documents": [] },
  "options": { "stream": false, "cache": true, "trace_id": "trace-8f2c" }
}
```

字段校验规则（在 Pydantic 模型中以约束声明，而非手工 if）：

| 字段 | 约束 |
| --- | --- |
| `task_type` | 枚举：generate / summarize / rewrite / extract |
| `input.text` | 1 ≤ 长度 ≤ 8192 字符 |
| `params.temperature` | 0 ≤ T ≤ 2 |
| `params.top_p` | 0 < p ≤ 1 |
| `params.max_tokens` | 1 ≤ n ≤ 4096 |
| `output.schema` | `format=json` 时必填，须为合法 JSON Schema |
| `model` | 必须存在于 `models` 表且状态为 `active` |

响应体（统一信封）：

```json
{
  "request_id": "req_9c1f4a",
  "task_id": "tsk_7b3e",
  "status": "succeeded",
  "output": {
    "text": "1. ……\n2. ……",
    "format": "text",
    "finish_reason": "stop",
    "citations": []
  },
  "usage": { "prompt_tokens": 312, "completion_tokens": 486, "total_tokens": 798 },
  "model": { "name": "pcxx-text-7b-instruct", "version": "2026.03", "adapter": null },
  "safety": { "input_decision": "pass", "output_decision": "pass", "labels": [] },
  "provenance": { "ai_generated": true, "provider_code": "PCXX-001", "content_id": "c_5a91" },
  "cache_hit": false,
  "latency_ms": { "queue": 3, "prefill": 88, "decode": 1420, "total": 1511 }
}
```

`provenance` 字段即为**隐式生成标识**载体，不可省略。

### 5.3 错误模型

统一结构，绝不向客户端暴露堆栈或内部细节：

```json
{
  "error": {
    "code": "SYNTH_INPUT_TOO_LONG",
    "message": "输入文本长度超过上限",
    "details": { "limit": 8192, "actual": 10320 },
    "request_id": "req_9c1f4a",
    "retryable": false
  }
}
```

> 前端约定：4xx 不重试（除 429 按 `Retry-After` 重试）；5xx 与网络失败最多重试 3 次，指数退避；`retryable=true` 才允许自动重试。

### 5.4 流式事件协议

```
event: start
data: {"request_id":"req_9c1f4a","model":"pcxx-text-7b-instruct"}

event: delta
data: {"text":"第一条要点"}

event: usage
data: {"prompt_tokens":312,"completion_tokens":486}

event: safety
data: {"decision":"pass","labels":[]}

event: done
data: {"finish_reason":"stop","latency_ms":{"ttft":142,"total":1511}}
```

---

## 6 关键机制设计

### 6.1 模型适配层（可替换是架构底线）

对外只暴露一个抽象接口，具体引擎实现可热切换：

```python
# app/inference/base.py
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class GenParams:
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    max_tokens: int = 1024
    repetition_penalty: float = 1.05
    stop: tuple[str, ...] = ()


class TextGenerator(ABC):
    """文本合成后端统一契约。控制器与服务层只依赖本接口。"""

    name: str
    context_window: int
    max_output_tokens: int

    @abstractmethod
    async def generate(self, prompt: str, params: GenParams,
                       json_schema: dict | None = None) -> "GenResult": ...

    @abstractmethod
    def stream(self, prompt: str, params: GenParams,
               json_schema: dict | None = None) -> AsyncIterator[str]: ...
```

三种实现：`vllm_backend`（生产默认，连续批处理）、`local_backend`（transformers，单机/开发）、`remote_backend`（第三方 API，降级与容量兜底）。切换仅需改 `INFERENCE_BACKEND` 环境变量，业务代码零改动。

### 6.2 输入校验与安全护栏

三段式防线：

| 阶段 | 手段 | 命中处理 |
| --- | --- | --- |
| 入口 | Pydantic 约束 + 字符数/编码校验 | 400 / 413 |
| 输入护栏 | 敏感词库 + 分类模型 + 提示注入特征（角色越权、指令覆盖、编码绕过） | 422 `GUARD_INPUT_BLOCKED` |
| 输出护栏 | 分类模型复检 + 正则规则 + 引用一致性检查 | 451 `GUARD_OUTPUT_BLOCKED`；可配置「拦截/替换/仅标记」三种策略 |

护栏以独立服务封装（`guardrail_service`），策略通过配置项切换，**不允许在业务代码中内联硬编码规则**。

### 6.3 限流、配额与 Token 预算

- **两级限流**：网关层按 IP/租户做粗粒度 QPS 限制；服务层用 Redis 令牌桶做租户级精细限流；
- **Token 日配额**：`tenants.token_quota_daily`，按 `usage.total_tokens` 累计扣减，超额返回 429 `QUOTA_TOKEN_EXHAUSTED`；
- **请求预算**：`max_tokens` 上限按租户套餐分级（如免费 512 / 标准 2048 / 专业 4096），并在调用前预占额度、结束后按实际用量结算，避免并发超额。

### 6.4 缓存与幂等

| 机制 | 键 | TTL | 说明 |
| --- | --- | --- | --- |
| 精确缓存 | `sha256(model + params + 归一化 prompt)` | 1h | 仅对 `temperature ≤ 0.3` 或显式 `cache=true` 生效 |
| 语义缓存 | 向量近邻 + 相似度阈值 ≥ 0.95 | 10m | 高并发同质请求场景启用，须记录命中来源 |
| 幂等键 | `Idempotency-Key`（租户内唯一） | 24h | 同键重复提交返回首次结果，不重复计费 |

> 写后失效：模板或模型版本变更时，按前缀批量清除相关缓存键。

### 6.5 可观测性与审计留痕

- **日志**：structlog 输出 JSON，字段含 `request_id`、`tenant_id`、`model`、`tokens`、`latency_breakdown`；**严禁记录完整用户文本与密钥**，只记 `input_digest`（哈希前 16 位）；
- **指标**：`synth_requests_total{status,task_type}`、`synth_ttft_seconds`、`synth_tokens_total{direction}`、`guardrail_block_total{stage}`、`queue_depth`、`gpu_cache_usage`；
- **审计**：每次合成写入 `audit_logs`，含操作主体、资源、输入摘要、输出摘要、安全判定与时间戳，留存不少于 6 个月，支撑备案核查与安全事件溯源。

---

## 7 数据模型

### 7.1 实体关系

<!--FIG:ER-->

### 7.2 核心表结构

**tenants（租户）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | uuid PK | 租户 ID |
| name | varchar(128) | 名称 |
| plan | varchar(32) | free / standard / pro |
| token_quota_daily | bigint | 日 Token 配额 |
| status | varchar(16) | active / suspended |

**generations（合成记录）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | uuid PK | 记录 ID |
| request_id | varchar(64) | 请求追踪 ID（唯一索引） |
| tenant_id | uuid FK | 租户 |
| model_id | uuid FK | 模型 |
| task_type | varchar(24) | 任务类型 |
| input_digest | varchar(64) | 输入摘要（不存明文） |
| prompt_hash | varchar(64) | 缓存/去重键 |
| params | jsonb | 采样参数快照 |
| output_text | text | 输出文本（按合规策略加密存储） |
| finish_reason | varchar(24) | stop / length / blocked |
| prompt_tokens / completion_tokens | int | 用量 |
| safety_labels | jsonb | 安全标签 |
| latency_ms | jsonb | 时延分解 |
| created_at | timestamptz | 创建时间 |

索引策略：`(tenant_id, created_at DESC)` 支撑租户维度分页；`prompt_hash` 支撑缓存命中统计；`request_id` 唯一。

**tasks（异步任务）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | uuid PK | 任务 ID |
| tenant_id | uuid FK | 租户 |
| type | varchar(24) | 任务类型 |
| status | varchar(16) | pending / running / succeeded / failed / canceled |
| priority | smallint | 优先级，批量任务可降级 |
| payload | jsonb | 请求快照 |
| result_ref | varchar(512) | 结果对象存储路径 |
| attempts | smallint | 已重试次数 |
| error_code | varchar(64) | 失败错误码 |
| idempotency_key | varchar(128) | 租户内唯一（部分唯一索引） |
| created_at / started_at / finished_at | timestamptz | 时间线 |

**audit_logs（审计）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigserial PK | 自增 |
| request_id | varchar(64) | 关联请求 |
| tenant_id | uuid | 租户 |
| action | varchar(48) | synthesize / block / cancel |
| resource | varchar(128) | 资源标识 |
| ip / ua | inet / varchar(256) | 来源信息 |
| input_digest / output_digest | varchar(64) | 内容摘要 |
| decision | varchar(16) | pass / block / replace |
| created_at | timestamptz | 时间 |

**prompt_templates（模板）**：`id / name / version / template / variables(jsonb) / status`。模板**必须带版本号**，且合成记录关联当时的模板版本，保证结果可复现、可回溯。

### 7.3 迁移与版本管理

- 所有 DDL 通过 Alembic 迁移脚本执行，**禁止手工改库**；每个迁移须可回滚（`downgrade` 必写）；
- 迁移与应用代码分离部署，采用「先兼容后清理」的扩展—收缩模式，保证滚动发布期间新旧版本共存；
- 模型版本与提示模板版本纳入同一套版本管理，`generations` 记录双版本号为可复现性兜底。

---

## 8 部署与运维

### 8.1 部署拓扑

<!--FIG:DEPLOY-->

| 组件 | 副本策略 | 说明 |
| --- | --- | --- |
| API 节点（无状态） | HPA 按 QPS/CPU 伸缩 ≥2 | 不加载模型权重，纯编排 |
| 推理节点（GPU） | 按队列深度伸缩 | vLLM 常驻，暴露兼容 OpenAI 的本地端点 |
| Redis | 主从 + 哨兵 | 缓存、队列、限流计数 |
| PostgreSQL | 主 + 只读从 | 主写从读，JSONB 存参数 |
| Worker | 按队列深度伸缩 | 异步合成与归档 |
| 对象存储 | 托管 | 长结果与归档 |

**节点分离的意义**：API 节点可秒级扩缩容且成本低；GPU 节点按队列深度伸缩，避免为峰值流量常驻昂贵算力。

### 8.2 关键配置项（`.env.example` 节选，仅占位值）

```dotenv
APP_ENV=production
LOG_LEVEL=info
CORS_ALLOWED_ORIGINS=https://app.example.com

DATABASE_URL=postgresql+asyncpg://user:password@db:5432/synth
REDIS_URL=redis://redis:6379/0

JWT_SECRET_KEY=change-me-in-vault
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=1209600

INFERENCE_BACKEND=vllm
VLLM_ENDPOINT=http://vllm:8000/v1
MODEL_REGISTRY_PATH=/models/registry.json
MODEL_MAX_CONTEXT=32768
MODEL_MAX_OUTPUT=4096
REQUEST_TIMEOUT_SECONDS=60

MAX_INPUT_CHARS=8192
RATE_LIMIT_PER_MINUTE=60
DAILY_TOKEN_QUOTA=2000000

GUARDRAIL_ENABLED=true
GUARDRAIL_BLOCKLIST_PATH=/etc/guardrail/blocklist.txt
GUARDRAIL_OUTPUT_POLICY=block   # block | replace | flag

CACHE_TTL_SECONDS=3600
SEMANTIC_CACHE_ENABLED=false
ARCHIVE_BUCKET=s3://synth-archive
```

启动时由 `core.config.Settings` 集中校验：必填缺失、URL 格式错误、数值越界均**直接终止启动**并打印明确原因，不允许带病运行。真实 `.env` 必须加入 `.gitignore`。

### 8.3 健康检查、优雅停机与伸缩

- `/health`：进程存活（不查依赖），供 K8s liveness 使用；
- `/ready`：探测 PostgreSQL、Redis 与推理端点，任一不可用即摘除流量；推理端点不可用时可选**降级到 `remote_backend`**（由 `FALLBACK_BACKEND` 控制）；
- **优雅停机**：捕获 SIGTERM 后停止接收新请求 → 等待在途请求（上限 `SHUTDOWN_GRACE_SECONDS`）→ 关闭连接池与队列消费者；流式请求主动发送 `done` 后断开；
- **背压**：队列深度超阈值时对新提交返回 429，而非无限堆积。

---

## 9 安全与合规

### 9.1 内容安全

- **输入侧**：敏感内容识别 + 提示注入防护（识别指令覆盖、角色越权、编码绕过、超长上下文淹没等模式）；
- **输出侧**：分类模型复检 + 规则兜底；对 `extract` 类输出额外做 Schema 合法性与字段范围校验；
- **策略可配**：拦截 / 替换 / 仅标记三档，按业务场景与租户等级配置；
- **不可绕过**：护栏在服务层强制串联，任何入口（同步、流式、异步、内部调用）共用同一路径。

### 9.2 生成合成内容标识

依据《人工智能生成合成内容标识办法》，落实双重标识：

| 类型 | 落实方式 |
| --- | --- |
| 显式标识 | 面向用户的输出附加「本内容由 AI 生成」提示；API 响应固定返回 `provenance.ai_generated=true` |
| 隐式标识 | 响应与归档文件元数据写入生成服务提供者编码、内容编号、模型版本，示例：`{"provider_code":"PCXX-001","content_id":"c_5a91"}` |

隐式标识随内容一同留存于归档，确保任何导出物都可追溯生成来源。

### 9.3 数据与隐私

- 用户输入默认**不用于模型训练**；如需使用须获得单独授权并留存授权记录；
- 输入文本仅存摘要哈希用于审计，全文明文按合规策略加密存储并设置更短保留期；
- 密钥与令牌统一由密钥管理服务下发，代码库与日志中零明文；
- 涉及个人信息出境时按评估要求另行处理，禁止默认跨境传输。

### 9.4 算法备案材料映射

本框架可为以下材料直接提供技术依据：

| 备案材料项 | 对应章节 |
| --- | --- |
| 算法基本原理 | 2.1、2.2、2.3 |
| 算法运行机制 | 2.4、2.5、3.1、4.x |
| 算法应用场景 | 1.2、4.1–4.4 |
| 算法目的意图 | 1.1、1.4 |
| 数据与模型管理 | 7.x、9.3 |
| 内容安全与标识 | 9.1、9.2 |
| 安全评估与留痕 | 6.5、9.x |

涉及法规：《互联网信息服务深度合成管理规定》《生成式人工智能服务管理暂行办法》《互联网信息服务算法推荐管理规定》《人工智能生成合成内容标识办法》及相关配套标准。

---

## 10 核心伪代码

### 10.1 采样解码（含温度、Top-k、Top-p）

```python
def sample_next_token(logits, params, generated_ids, eos_id):
    """logits: [vocab] 最后一个位置的未归一化分数"""
    # 1) 重复惩罚（penalty > 1；对已出现 token 压低其分数）
    for tid in set(generated_ids):
        if logits[tid] > 0:
            logits[tid] /= params.repetition_penalty
        else:
            logits[tid] *= params.repetition_penalty

    # 2) 温度缩放（T→0 时退化为贪心）
    if params.temperature <= 1e-5:
        return int(argmax(logits))
    logits = logits / params.temperature

    # 3) Top-k 截断
    if params.top_k > 0:
        kth = top_k_value(logits, params.top_k)
        logits[logits < kth] = -inf

    # 4) Top-p（核采样）截断
    probs = softmax(logits)
    if params.top_p < 1.0:
        order = argsort_desc(probs)
        cumulative = cumsum(probs[order])
        cutoff_idx = searchsorted(cumulative, params.top_p) + 1
        keep = order[:cutoff_idx]
        mask = full_like(probs, -inf)
        mask[keep] = logits[keep]
        logits = mask

    # 5) 归一化并采样
    probs = softmax(logits)
    return multinomial(probs)
```

主生成循环：

```python
async def generate(prompt, params, schema=None):
    tokens = tokenize(prompt)
    logits_processor = build_constraint_processor(schema)  # JSON Schema → FSM
    generated, cache = [], None

    for _ in range(params.max_tokens):
        logits, cache = await backend.forward(tokens, kv_cache=cache)  # prefill 仅首次
        logits = logits_processor(generated, logits)                   # 约束解码
        tid = sample_next_token(logits, params, generated, EOS)
        if tid == EOS or hit_stop_sequence(generated, params.stop):
            yield FinishReason.STOP
            return
        generated.append(tid)
        yield detokenize(tid)          # 流式输出
    yield FinishReason.LENGTH
```

### 10.2 合成编排服务（服务层，不含 HTTP 依赖）

```python
class SynthesisService:
    def __init__(self, generator: TextGenerator, guardrail, quota,
                 cache, generation_repo, audit_repo, settings):
        ...  # 全部依赖注入，便于单测替换

    async def synthesize(self, req: SynthesisRequest, tenant: Tenant) -> SynthesisResult:
        request_id = new_request_id()

        # ① 输入护栏：不通过则零算力消耗返回
        verdict = await self.guardrail.check_input(req.input.text)
        if verdict.blocked:
            await self.audit_repo.record(request_id, tenant.id, "block", verdict)
            raise GuardrailBlocked(code="GUARD_INPUT_BLOCKED", labels=verdict.labels)

        # ② 配额预占（并发安全：先占后结算）
        await self.quota.reserve(tenant.id, req.params.max_tokens)

        # ③ 幂等与缓存
        if cached := await self.cache.get_exact(req.cache_key()):
            await self.quota.settle(tenant.id, cached.usage.total_tokens)
            return cached.as_result(cache_hit=True)

        # ④ 提示构建（模板版本化）
        prompt = self.prompt_builder.render(req)

        # ⑤ 推理：约束解码按需开启
        try:
            gen = await self.generator.generate(prompt, req.gen_params(),
                                                json_schema=req.output.schema)
        except BackendUnavailable:
            gen = await self.fallback_generator.generate(prompt, req.gen_params())
        finally:
            await self.quota.settle(tenant.id, gen.usage.total_tokens)

        # ⑥ 输出护栏 + 生成标识注入
        out_verdict = await self.guardrail.check_output(gen.text)
        if out_verdict.blocked and self.settings.guardrail_output_policy == "block":
            raise GuardrailBlocked(code="GUARD_OUTPUT_BLOCKED")
        provenance = build_provenance(provider_code=self.settings.provider_code,
                                     model=gen.model_name)

        # ⑦ 持久化 + 审计（同一事务）
        async with self.uow.transaction():
            await self.generation_repo.save(request_id, tenant.id, req, gen, out_verdict)
            await self.audit_repo.record(request_id, tenant.id, "synthesize", out_verdict)

        return SynthesisResult(request_id=request_id, output=gen.text,
                               usage=gen.usage, provenance=provenance)
```

---

## 11 演进路线

| 阶段 | 目标 | 关键交付 |
| --- | --- | --- |
| P0 MVP | 打通链路 | 单后端（vLLM）+ 同步接口 + 基础输入护栏 + 审计落库 |
| P1 可用性 | 支撑线上流量 | SSE 流式 + 异步队列 + 双级限流 + Token 配额 + 精确缓存 |
| P2 体验与成本 | 质量与成本双优 | 多模型路由 + RAG + 约束解码 + LoRA 适配器 + 语义缓存 |
| P3 规模化与合规 | 可运营可审计 | 灰度发布 + 内容标识全链路 + 备案报表自动化 + 成本看板 |

---

## 附录 A 错误码表

| HTTP | 错误码 | 含义 | 可重试 |
| --- | --- | --- | --- |
| 400 | `SYNTH_INVALID_PARAM` | 参数非法或越界 | 否 |
| 400 | `SYNTH_INPUT_TOO_LONG` | 输入超长 | 否 |
| 400 | `SYNTH_OUTPUT_SCHEMA_UNSATISFIABLE` | Schema 无法满足（约束冲突） | 否 |
| 401 | `AUTH_TOKEN_EXPIRED` | 令牌过期 | 是（刷新后） |
| 403 | `AUTH_FORBIDDEN_SCOPE` | 权限不足 | 否 |
| 409 | `SYNTH_DUPLICATE_REQUEST` | 幂等键冲突且首次未完成 | 是（稍后） |
| 413 | `SYNTH_PAYLOAD_TOO_LARGE` | 请求体过大 | 否 |
| 422 | `GUARD_INPUT_BLOCKED` | 输入被安全策略拦截 | 否 |
| 429 | `QUOTA_RATE_LIMITED` | 触发速率限制 | 是 |
| 429 | `QUOTA_TOKEN_EXHAUSTED` | Token 配额耗尽 | 否（次日后） |
| 451 | `GUARD_OUTPUT_BLOCKED` | 输出被安全策略拦截 | 否 |
| 500 | `MODEL_BACKEND_ERROR` | 推理后端异常 | 是 |
| 503 | `MODEL_BACKEND_UNAVAILABLE` | 推理后端不可用 | 是 |
| 504 | `SYNTH_TIMEOUT` | 合成超时 | 是 |
| 507 | `QUEUE_OVERLOADED` | 队列过载背压 | 是 |

## 附录 B 环境变量清单

见 8.2 节。补充说明：所有变量均区分环境（dev / staging / prod），生产环境密钥通过密钥管理服务注入，**不落盘、不打印、不提交**。

---

*文档结束*
