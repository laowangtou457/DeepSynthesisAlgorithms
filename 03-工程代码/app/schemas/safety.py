"""内容安全接口契约 —— **SW-I03**（承载 `SW-009` / `SW-010` / `SW-011` / `SW-017`）。

字段纪律：

- `degraded` 与 `empty_categories` **必须如实回传**——调用方据此判断结论可信度；
- **不回传任何命中词原文**（`SW-019` 数据最小化），只回类别编号与名称；
- 「通过」只在 `degraded=false` 且未命中时成立。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["input", "output"]
Action = Literal["pass", "block", "flag", "notice"]
#: ⚠️ **`notice` = 命中仅提示**（2026-11-03 增补）：
#: 词表 `warn` 级词条命中时使用 —— **放行、记录留痕，但不进人工复核队列**。
#: 依据 `SEC-007` §4.3「`warn` = 命中仅提示，正常语境常见、仅特定语境违规」。
#: ⚠️ 此前实现把 `review` 与 `warn` **同义处理**（都 `flag`）⇒ 12,035 条
#: `review` 级词条全部进人工队列 ⇒ 实测误拒率 6.7% > 国标 ≤5%。
#: ⚠️ **「替换（replace）」已从取值域移除**（2026-10-16）：该策略**无实际替换实现**——
#: 命中后既不替换文本也不放行，等于「静默放过」，与 `SW-010` 的可配置语义不符。
#: 输出闸现为 **`block`（拦截）／`flag`（放行并标记待人工复核）** 两态。


class InspectRequest(BaseModel):
    """输入／输出内容检测请求。"""

    text: str = Field(min_length=1, description="待检文本；不得为空")
    channel: Channel = Field(description="检测通道：input=SW-009 输入闸；output=SW-010 输出闸")
    stage: str | None = Field(default=None, description="业务阶段（可选，仅用于留痕）")


class Hit(BaseModel):
    """一次命中。**不含命中词原文**——只给类别，供客户端提示与留痕。"""

    category_id: str = Field(description="类别编号，如 A1-07")
    category_name: str = Field(description="类别名称")
    group: str = Field(default="", description="组别，如 A.1")
    #: ⚠️ **词条等级**（来自词表第 2 段）：`block`（命中即按策略拦截）／
    #: `review`（**记录待人工复核、不阻断**）／`warn`（**仅提示、不进复核队列**）。
    #: ⚠️ 2026-11-03 修正：`warn` 与 `review` 的**处置已区分** —— `warn` ⇒
    #: `action=notice`（放行且留痕，不占人工复核工作量）。
    #: ⚠️ 2026-11-03 抽检实测发现：运行时此前**丢弃等级** ⇒ 96% 的 `review` 级词条
    #: 被当 `block` ⇒ 正常剧本段 100% 误拒。**本字段为向后兼容的增量**
    #: （默认值 `review`），旧客户端不受影响。
    level: str = Field(default="review", description="词条等级：block/review/warn")


class InspectVerdict(BaseModel):
    """检测结论。

    ⚠️ `passed=true` 的**充分条件**是：未命中 **且** `degraded=false`。
    `degraded=true` 时结论**不可用于放行决策**。
    """

    passed: bool
    channel: Channel
    action: Action = Field(description="处置动作：pass/block/replace/flag")
    hits: list[Hit] = Field(default_factory=list)
    hit_count: int = 0
    #: ⚠️ **`warn` 级命中数**（2026-11-03 增补）：仅提示、不进人工复核队列，
    #: 不计入 `hit_count`（`hit_count` 是「需处置的命中数」）。
    #: 用途：证明「提示级已检出」而不虚增人工工作量。
    warn_count: int = 0
    degraded: bool = Field(
        default=False,
        description="检测能力降级（词库不可用/加载失败/熔断）——true 时结论不可用于放行",
    )
    degraded_reason: str = Field(default="", description="降级原因（degraded=true 时非空）")
    lexicon_standard: str = Field(default="", description="词库依据标准，如 GB/T 45654—2025")
    empty_categories: list[str] = Field(
        default_factory=list, description="词条数为 0 的类别（待编写，≠ 无风险）"
    )
    unreadable_categories: list[str] = Field(default_factory=list, description="不可读的类别")
    message: str = Field(default="", description="面向用户的处置说明")
    refusal_talk: str | None = Field(
        default=None, description="`SW-017` 拒答话术；仅 action=block 时给出"
    )


class InjectionRequest(BaseModel):
    """提示注入检测请求 —— `SW-011`。"""

    text: str = Field(min_length=1)
    context_fields: list[str] = Field(
        default_factory=list,
        description="参与检查的上下文字段名（如素材、参考资料）——结构隔离范围",
    )


class InjectionVerdict(BaseModel):
    """注入检测结论。`blocked=false` 时 `passed=true`。"""

    passed: bool
    blocked: bool
    patterns: list[str] = Field(default_factory=list, description="命中的注入模式标识")
    isolated_fields: list[str] = Field(default_factory=list, description="已被结构隔离的字段")
    message: str = Field(default="")
    degraded: bool = False
    degraded_reason: str = Field(default="")


class PolicyView(BaseModel):
    """安全策略与检测能力现状 —— 供监督与举证查阅，不参与放行决策。"""

    lexicon_standard: str = ""
    lexicon_root: str = ""
    category_count: int = 0
    total_words: int = 0
    quota_covered: int = 0
    empty_categories: list[str] = Field(default_factory=list)
    unreadable_categories: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    circuit_open: bool = Field(default=False, description="熔断是否打开（打开即拒绝放行）")
    circuit_reason: str = Field(default="")
    fail_closed: bool = Field(default=True, description="检测不可用时是否拒绝放行（fail-closed）")
    enforced: bool = Field(
        default=True,
        description="**阻断是否生效**。false ＝ 只判定不阻断（词库未就绪期的联调旁路，"
        "项目方 2026-10-15 决策）。⚠️ 此状态**不得静默**——false 时检测照常执行并留痕",
    )
    controlled_loaded: bool = Field(
        default=False,
        description="受控词库是否已加载（**只给布尔，不含路径**——受控区路径不外泄）",
    )
    input_channel: str = Field(default="SW-009")
    output_channel: str = Field(default="SW-010")
    injection_channel: str = Field(default="SW-011")
    refusal_channel: str = Field(default="SW-017")