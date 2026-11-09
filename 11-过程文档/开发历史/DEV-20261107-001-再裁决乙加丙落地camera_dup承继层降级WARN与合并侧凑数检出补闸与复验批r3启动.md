# DEV-20261107-001 项目方再裁决（乙＋丙）落地：`camera_dup` 承继层降级 WARN ＋ 合并侧凑数检出补闸 ＋ 复验批 r3 启动

- **日期**：2026-11-07　**批次类型**：代码落地（再裁决执行）＋ 复验批启动
- **裁决依据**：`DEV-20261106-007` §4 三选项呈报 ⇒ 项目方 2026-11-07 裁定 **乙＋丙**
- **前置**：裁决 3 复验批（`ab_t101_r2`）未通过——`R26` 根治、`pack_shots_lt_upstream` on=2（同在 `unit:U01`）触发回退；根因＝`uniqueItems` 不入引擎允许面（重复凑数）＋ U01「承继守恒 × `camera_dup`」不可满足约束对

---

## 1 裁决乙：`unit.camera_dup` 承继层 BLOCK → WARN

- **落点**：`03-工程代码/delivery/validate_pack.py`（⑩ 生成单元划分段）。
- **口径**：`unit.camera_dup` 是分镜层的**生成期**约束（§4.3）；shot_prompt 层是**承继层**（`TPL-009` 承继列：`camera.*` 一字不得改）。承继层把它当 BLOCK（且可重试）＝制造「照抄必违本条、改 camera 必违承继守恒」的不可满足约束对——复验批 run6/run10 实证模型在此冲突下退化为重复条目凑 `minItems`、重试同因复现。⇒ 本层降级 **WARN** 并留痕「交分镜层处置」；若重复**非**承继自上游，由 `R31`／承继守恒判据兜底。
- **影响面**：WARN 不进 `pack_blocks` ⇒ 不再触发针对该码的定向重试（此前重试反馈把「运镜重复」塞给无权改 camera 的模型，是退化解的直接压力源）。交付侧终验同口径（WARN 仍入报告、留痕义务不取消）。
- **测试**：`test_validate_pack.py` 新增 `test_unit_camera_dup_is_warn_after_demotion`（人为制造单元内运镜重复 ⇒ 有 `unit.camera_dup`、无 `BLOCK unit.camera_dup`）。

## 2 裁决丙：合并侧「段内重复凑数」检出 → 可重试失败

- **检出点**：`app/services/segment.py` `merge_segments()`——新增**段内** `shot_id` 重复检出（`uniqueItems` 被引擎剥离 ⇒ `shots_floor` 管得住个数、管不住互异；段内重复**从来不是合法产物**）。命中即告警并带机器可读码：
  `merge.shot_dup_in_segment｜分镜「<sid>」在第 <idx> 段内重复出现 <n> 次（同一 shot_id 单段内重复＝凑数形态）——已保留先到者，重试时必须为每个 shot_id 写不同镜头`
  （全同重复——旧静默——与内容不同重复均检出；**跨段**首到先得不误报。）
- **升级点**：`app/services/dialogue_service.py` 新增 `_inject_merge_dup_verdict()`，在门禁判定后把该码注入 `QualityVerdict`（`ok=False` ＋ `retryable` 追加，原文保留既有 retryable）。报错含 `shot_id` ⇒ `_retry_segments` 的包含定位精确命中属主段；重试反馈明写「不得重复条目凑 `minItems` 下限」⇒ **打破确定性退化解的反馈回路**（r2 批两轮两次尝试同解复现，缺的就是这句反馈）。
- **测试**：`test_segment.py` ＋3（全同重复检出／内容不同重复检出／跨段不误报）；`test_generation_segments.py` ＋2（注入后 `ok=False` 且码入 `retryable`、既有 retryable 保留）。
- **全量**：**406 passed**（基线 400 ＋ 新增 6）。

## 3 复验批 r3（裁决 2 再裁决点的验收动作）

- **器具与口径**：同 `_ab_t101.py`、同一固定上游 `ab101_fixed_storyboard.json`（15 镜／5 单元），两臂（off 基线／on 段级裁剪＋schema 收窄）各 12 轮，产物原文归档 `ab_t101_r3/`。
- **验收口径**（承 `PRO-015` §3.2／§9）：回退判据不变——`pack_shots_lt_upstream` on ≥2 即未通过；重点观察——① U01 段是否仍现凑数（`merge.shot_dup_in_segment` 出现即被丙转成定向重试）；② `camera_dup` 不再进 retryable 后 U01 的解除冲突效果；③ `R26` 保持 0；④ `R29` 臂间差异是否随冲突消解回落。
- **进度**：干跑 1×2 通过后启动全量（预计约 7h），跑完另件收口并同步台账；**两开关维持 `false`**，复验通过前不翻。

## 4 台账同步

- `PM-001` `T-101` 行：再裁决落地状态追记；
- `PRO-016`：§6① 再裁决点已裁定（乙＋丙）、§7 V1.2；
- `PRO-015`：§9 尾部追记再裁决落地；
- `CM-002`：§2 `DEV` 计数刷新、§7 V1.48；
- 开发历史 `README.md`：序号 127 补登本件。

## 5 遗留

1. 复验批 r3 跑完后的**收口件**（判定与台账）；未过则回到 `PRO-016` 再裁决。
2. `R29` 臂间差异的处置（若 r3 仍显著）。
3. `ISSUE-058` 段截断未消除；裁决 6（`ISSUE-063` 留痕级探测）仍挂。
