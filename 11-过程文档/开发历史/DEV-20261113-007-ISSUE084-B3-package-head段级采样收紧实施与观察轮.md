# 开发历史 · ISSUE-084 B3 实施：package_head 段级采样收紧（BugFix）

| 项目 | 内容 |
| --- | --- |
| 记录编号 | DEV-20261113-007 |
| 记录时间 | 2026-11-13 15:55 |
| 动作类型 | 代码（`app/` 两文件：服务层 +42/−1 ＋ 新增单测） |
| 触发来源 | 项目方 2026-11-13 裁决「**B3 先行（半天级）＋观察一轮跑测；B1 留作 B3 无效时的正选**」 |
| 涉及目录 | `03-工程代码/app/services/`（收紧）、`app/tests/`（单测）、`12-项目管理/PM-001`（V1.91） |
| 状态 | 已完成（实施＋QA 回归全过＋**观察轮判定 B3 有效**：package_head 1075 tokens 零截断、码族不劣化） |

---

## 1 背景与裁决承接

`DEV-20261113-006` 定界实测改判后，r6 截断真因＝`package_head` 段偶发**真跑满 12288 tokens**（正常产出仅 ≈5.3K，呈退化 ramble）。项目方在三案复呈后裁决：**B3 先行＋观察一轮；B1（细分 package_head 分段）留作 B3 无效时的正选**。用户同轮确认 **B3 无需 Docker**（链路全程裸机：8010 FastAPI 直起、模板为 YAML、推理在 GPU 机经 SSH 隧道）。

## 2 B3 设计（只收紧采样，不动编排/模板/判据）

对 `package_head` 段（且仅该段）两条采样收紧：

1. **降温 0.7→0.4**：该段产出 meta／style_bible／characters 等**元数据**而非镜头创意正文，需要稳定复述而非发散；`SW-007` 的 0.7 只约束 shot 正文，**不受波及**。
2. **`max_tokens` 封顶 8192（快速失败）**：正常产出 ≈5.3K 不受影响；真退化轮从「12288 tokens／≈28 分钟」压到 8192 级，`T-086` 按段重试代价同步下降——把「整轮作废」压成「单段重试」。

两者均取 `min` 语义（模板日后更保守时不放大）；常量内联、不新建设置项（可调性＝删掉几行）。

## 3 实施明细（工程师寇豆码）

- `app/services/dialogue_service.py`（+42/−1，纯 LF 守恒）：① `from dataclasses import replace`（`GenParams` 为 **frozen dataclass**，`replace` 生成新对象，防收紧泄漏到 `unit:*` 段）；② 分段循环内 `seg_params = _params_of(template.sampling)`，`seg == "package_head"` 时经新纯函数 `_package_head_sampling()` 收紧后传入 `backend.generate`；③ 新增模块级纯函数 `_package_head_sampling`（docstring 载明两条收紧依据与 min 语义）。
- `app/tests/test_package_head_sampling.py`（新增 247 行，8 例）：基线收紧、正常产出 5319 < 8192 < 12288 三点断言、其余字段原样、**入参不可变**、min 不放大（含恰等阈值恒等＋幂等）、端到端（RecordingBackend：`calls[0]=0.4/8192`，`unit` 段逐字段等于模板原值 0.7/12288）。

## 4 QA 独立回归（严过关，5 项全 PASS、路由 NoOne）

- 改动面：`app/` 内仅两文件，`dialogue_service.py` 恰 +42/−1、3 hunk，判据/编排/模板/trace 零改动；
- 语义：frozen 不改入参（`FrozenInstanceError` 实证）、min 语义 runtime 验证、QA 自写端到端脚本（非复用工程师用例）验证段隔离——`calls[0]=0.4/8192`、`unit` 段＝基线；脚本已删无残留；
- 回归：专项 **8 passed**、关键词子集 **74 passed**、**全量 515 passed, 6 warnings**（QA 独立重跑）；
- 编码：两文件纯 LF、无 BOM、py_compile 通过；
- 边界：`segment_plan==["all"]` 整包轮 runtime 实测收 0.7/12288 原值（**B3 不覆盖整包轮**）；`trace` 8 键未变。

## 5 边界与已知定义域（如实登记）

1. 收紧仅 `package_head`：**小包整包轮（`all`）不覆盖**——若观察期内整包轮也现 ramble，须另立改判；
2. 按段重试（`T-086`）同样带收紧参数（重试代价下降与预期一致）；
3. `trace` 未新增采样留痕字段（「不改判据/留痕面」纪律）——观察轮从产物侧反查采样值不可行，采样生效性以单测＋QA runtime 验证为证。

## 6 验证数字汇总

工程师：新单测 8 passed；`-k "dialogue or sampling or segment or params"` 74 passed；`test_vllm_backend.py` 22 passed；全量 **515 passed, 0 failed**。QA 独立重跑：同数字全绿。行尾族：两文件 CR=0。

## 7 观察轮（在跑）

- 命令：`AB101_RUNS=1 AB101_ARMS=on AB101_OUT=ab_t101_b3_obs`，cwd=`03-工程代码`，真实 14B（18001 隧道），夹具 v2（15 镜 ⇒ 必触发 package_head 分段）；
- 启动前 T-111 预检通过（`guided_mode=response_format` 自证＋配置一致）；
- **判读口径**：① package_head 段 `completion_tokens` 收敛 ≈5.3K 量级；② 若 ramble 复发应在 8192 触顶快速失败并按段重试（单段代价 ≈8192 tokens 级而非整轮 28 分钟）；③ 全链三判据（R27/R28/R29/R34 族、15 镜守恒）不劣化。结论待轮次落盘后回填 §8。

## 8 观察轮结论（2026-11-13 16:15 回填，轮次产物 `.wb-e2e/ab_t101_b3_obs/` 不入库）

单轮实测（15:34→16:15，2421.3s，attempts=2）：**B3 判定有效**。

| 判读口径 | 实测 | 结论 |
| --- | --- | --- |
| ① package_head 收敛 | **`completion_tokens=1075`、`finish=stop`**（历史正常 ≈5.3K，r6 退化轮跑满 12288） | 比历史正常值还降 80%，远离 8192 封顶——**ramble 未复发** |
| ② 快速失败兜底 | 全部 10 段（attempt1 6 段＋attempt2 重试 4 段）**全 `finish=stop`、零截断** | 兜底未被触发即收敛，退化若复发也只损失 ≤8192 级单段 |
| ③ 判据不劣化 | 守恒 15 镜/5 单元 100%；失败码族 **{R28,R34} ⊆ r5 基线族**；R7/R9/R14 回退行全 0 | 不劣化 |

- attempt1 判 R34（6 镜）＋R28（2 处）→ 按段重试 4 段（U01/U02/U03/U05，retry_calls=4 吻合）；attempt2 后残留 R34（5 镜）＋R28（1 处）⇒ `ok=False`——**预期内**（全门禁下自由内容难零瑕疵，与 r6 十二轮同为 ok=False 基线形态，且码族未扩）。
- 附带收益：package_head 在 0.4 温度下输出更精炼（1075 vs ≈5.3K tokens），头部段 token 成本同步下降。
- 注：attempt1 ct=12742 与 r6 正常轮（≈12.7K）同量级——B3 只影响 package_head 段，unit 段行为不变（单测与 QA runtime 已证）。

**处置**：B1（细分 package_head 分段）**无需启动**；T-110 按「B3 落地＋单轮观察有效」推进——轮次统计意义有限（n=1），是否再累计轮次由项目方定（建议：后续跑测天然覆盖，不需专门烧 GPU）。

## 9 遗留与下一步

1. 生产 `.env` 超时 600s 未动；整包轮（`all`）采样未动（B3 不覆盖，若小包轮现 ramble 另立改判）；
2. 观察轮证据文件在 `.wb-e2e/ab_t101_b3_obs/`（不入库，换机须重建）；
3. 常驻监控面板 `_run_monitor.py`（8021 聚合首页＋按跑测详情页）已按项目方「每次跑测必须可在界面查看」要求上线，本观察轮即首用。

## 10 未改动声明

分段编排、`TPL-009` 模板正文、判据（R1~R43）、`trace` 留痕面、生产 `.env` 均零改动；`app/` 改动仅 §3 两文件。
