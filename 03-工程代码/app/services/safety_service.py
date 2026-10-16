"""内容安全双闸 —— **`SW-009` / `SW-010` / `SW-011` / `SW-017`**（任务 `T-005`）。

分层纪律（`SW-104`：控制器不含业务逻辑；服务层不依赖 HTTP 类型）：

    端点 → SafetyService（只**判定**并返回 verdict，不阻断）
        → 编排层（DialogueService）据 verdict **决定阻断或放行**

⚠️ 三条硬纪律：

1. **fail-closed**（默认开启）—— 词库不可用 / 加载失败 / 熔断打开时，**一律拒绝放行**，
   绝不「查不到词 ⇒ 判定安全」。这是 `SW-009` 异常列「检测服务不可用熔断」的实现。
2. **降级结论不可用于放行** —— `degraded=true` 时 `passed` 恒为 `false`。
3. **拒答话术不依赖模型** —— 双闸必须在推理后端不可用时仍能工作，故话术为**服务层内置兜底**，
   模型生成的个性化拒答属后续增强（不作为本轮验收依据）。

⚠️ **受控类四类（`A1-01`／`A1-02`／`A1-03`／`A1-05`）当前为空壳**（项目方手工编写中，`T-020`），
本服务据实登记为 `empty_categories` 并在熔断判定中计入「检测覆盖不完整」——
**不因空类别而输出「安全」结论**。
"""

from __future__ import annotations

import re
from typing import Literal

from app.repositories.lexicon import Lexicon
from app.schemas.safety import (
    Hit,
    InjectionVerdict,
    InspectRequest,
    InspectVerdict,
    PolicyView,
)

OutputAction = Literal["block", "flag"]

#: `SW-011` 提示注入模式。**只做结构化模式识别，不做语义判断**——
#: 宁可漏判也不误判（误判会把正常创作指令当注入拦掉）。
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous", re.compile(r"(忽略|无视|忘记)\s*.{0,12}(之前|上面|以上|前面)")),
    ("ignore_instruction", re.compile(r"(忽略|无视|忘记)\s*.{0,8}(指令|要求|命令|规则|设定)")),
    ("role_override", re.compile(r"(你现在是|从现在起你是|你不再是|扮演)\s*\S")),
    ("developer_mode", re.compile(r"(developer\s*mode|开发者模式|dan\s*模式)", re.I)),
    ("leak_system_prompt", re.compile(r"(输出|复述|重复|告诉我)\s*.{0,10}(系统提示|系统指令|system\s*prompt|初始指令)", re.I)),
    ("bypass_refusal", re.compile(r"(不要拒绝|不许拒绝|必须回答|不得拒绝|绕过(限制|检测|审核))")),
    ("reveal_guard", re.compile(r"(你的)(系统提示|安全策略|审核规则|拒答规则)")),
)

# ---- `SW-017` 兜底话术（**配置承载、可审计、执行不依赖模型**）----
#
# ⚠️ **口径变更（2026-10-16 项目方裁决 `ISSUE-035` ②取方案 B）**：
#   需求原文要求「兜底话术由 `TPL-005`／`TPL-004` **产出**」，而
#   `DEV-20261015-009` 的设计是「**不依赖模型的确定性兜底**」——二者不矛盾，
#   实为同一事实的两层：模板（`task_type: guard`）＝给**模型**看的生成规格；
#   本处＝给**执行期**用的**确定性话术**，不调模型
#   （安全兜底必须在推理后端不可用时仍能工作，否则模型被注入时兜底同时失效）。
#   ⇒ 落实为「**话术值由配置注入（改话术不改代码、可审计），执行期确定性取用，
#      取不到回落内置默认**」。`TPL-004/005` 的 `sections.output` 给出的是
#   **模型生成**的话术规格，属后续增强（`DEV-009` 已声明不作为本轮验收依据）。
_DEFAULT_REFUSAL_TALK = "很抱歉，本次请求涉及超出服务范围的内容，我无法据此生成。"
_DEFAULT_CLARIFY_TALK = (
    "为准确理解您的修改要求，请补充说明：您希望调整的是哪一部分、期望的调整方向是什么？"
)


class SafetyService:
    """内容安全判定服务。无状态（词库快照在构造时注入），可安全复用。"""

    def __init__(
        self,
        lexicon: Lexicon,
        *,
        output_action: OutputAction = "block",
        fail_closed: bool = True,
        max_hits: int = 20,
        enforce: bool = True,
        refusal_talk: str | None = None,
        clarify_talk: str | None = None,
    ) -> None:
        self._lex = lexicon
        self._output_action: OutputAction = output_action
        self._fail_closed = fail_closed
        self._max_hits = max_hits
        self._enforce = enforce
        # `SW-017` 话术注入（方案 B）：**配置优先、回落内置默认**，
        # 保证「无配置时行为与改动前逐字一致」——零回归是硬要求。
        self._refusal_talk = refusal_talk or _DEFAULT_REFUSAL_TALK
        self._clarify_talk = clarify_talk or _DEFAULT_CLARIFY_TALK

    @property
    def enforce(self) -> bool:
        """**阻断是否生效**（项目方 2026-10-15 决策：加受控的旁路开关）。

        ⚠️ 本服务层**只判定、不阻断**——阻断由编排层（`DialogueService`）据本标志
        决定是否抛 `GUARD_*` 错误。`false` 时检测**照常执行、verdict 照常产出并留痕**，
        仅**放行判定不做阻断**，用于受控词库未就绪期的工程联调。
        """
        return self._enforce

    # ------------------------------------------------------------------
    # 熔断
    # ------------------------------------------------------------------
    @property
    def circuit_open(self) -> bool:
        """熔断是否打开。

        打开条件：① 词库**完全不可用**（零词条）；② fail-closed 关闭且存在不可读类别。
        「存在空类别」**不单独触发熔断**，但会置 `degraded=true`——
        因为空类别意味着**覆盖不完整**，而非检测失效。
        """
        if not self._lex.usable:
            return True
        return not self._fail_closed and bool(self._lex.unreadable)

    def _degradation(self) -> tuple[bool, str]:
        """返回 `(degraded, reason)`。reason 为空串表示未降级。"""
        reasons: list[str] = []
        if not self._lex.usable:
            reasons.append("词库零词条：检测能力不可用")
        if self._lex.unreadable:
            reasons.append(f"类别不可读：{'/'.join(self._lex.unreadable)}")
        if self._lex.warnings:
            reasons.extend(self._lex.warnings)
        if self._lex.empty_categories:
            # 空类别 ⇒ 覆盖不完整（受控类四类编写中，T-020），结论不得用于放行
            return True, "；".join(
                reasons
                + [f"类别词条为空（覆盖不完整，待编写）：{'/'.join(self._lex.empty_categories)}"]
            )
        if reasons:
            return True, "；".join(reasons)
        return False, ""

    # ------------------------------------------------------------------
    # SW-009 输入闸 / SW-010 输出闸
    # ------------------------------------------------------------------
    def inspect(self, req: InspectRequest) -> InspectVerdict:
        """按 `req.channel` 执行对应闸门，**只判定不阻断**。"""
        if req.channel == "input":
            return self.inspect_input(req.text, stage=req.stage)
        return self.inspect_output(req.text, stage=req.stage)

    def _base_verdict_kwargs(self) -> dict:
        degraded, reason = self._degradation()
        return {
            "degraded": degraded,
            "degraded_reason": reason,
            "lexicon_standard": self._lex.standard,
            "empty_categories": list(self._lex.empty_categories),
            "unreadable_categories": list(self._lex.unreadable),
        }

    def inspect_input(self, text: str, *, stage: str | None = None) -> InspectVerdict:
        """`SW-009` 输入内容安全检测：命中即拦截（`GUARD_INPUT_BLOCKED` 由编排层抛）。"""
        common = self._base_verdict_kwargs()
        if self.circuit_open:
            return InspectVerdict(
                passed=False,
                channel="input",
                action="block",
                hits=[],
                hit_count=0,
                message=f"输入检测能力不可用，已按 fail-closed 拒绝（{common['degraded_reason'] or '熔断'}）",
                refusal_talk=self._refusal_talk,
                **common,
            )

        raw = self._lex.scan(text, limit=self._max_hits)
        hits = [Hit(category_id=cid, category_name=name, group="") for cid, name, _ in raw]

        if hits:
            return InspectVerdict(
                passed=False,
                channel="input",
                action="block",
                hits=hits,
                hit_count=len(hits),
                message=f"输入命中 {len(hits)} 类禁止内容，已拦截",
                refusal_talk=self._refusal_talk,
                **common,
            )
        if common["degraded"]:
            return InspectVerdict(
                passed=False,
                channel="input",
                action="block",
                hits=[],
                hit_count=0,
                message=f"未命中，但检测覆盖不完整，按 fail-closed 拒绝（{common['degraded_reason']}）",
                refusal_talk=self._refusal_talk,
                **common,
            )
        return InspectVerdict(
            passed=True,
            channel="input",
            action="pass",
            hits=[],
            hit_count=0,
            message="通过",
            **common,
        )

    def inspect_output(self, text: str, *, stage: str | None = None) -> InspectVerdict:
        """`SW-010` 输出内容安全复检：命中策略可配（拦截／替换／标记）。"""
        common = self._base_verdict_kwargs()
        if self.circuit_open:
            return InspectVerdict(
                passed=False,
                channel="output",
                action="block",
                hits=[],
                hit_count=0,
                message=f"输出检测能力不可用，已按 fail-closed 拒绝（{common['degraded_reason'] or '熔断'}）",
                refusal_talk=self._refusal_talk,
                **common,
            )

        raw = self._lex.scan(text, limit=self._max_hits)
        hits = [Hit(category_id=cid, category_name=name, group="") for cid, name, _ in raw]

        if hits:
            action = self._output_action
            msg = {
                "block": f"输出命中 {len(hits)} 类禁止内容，已拦截",
                "flag": f"输出命中 {len(hits)} 类禁止内容，已标记待人工复核",
            }[action]
            return InspectVerdict(
                passed=(action == "flag"),
                channel="output",
                action=action,
                hits=hits,
                hit_count=len(hits),
                message=msg,
                refusal_talk=self._refusal_talk if action == "block" else None,
                **common,
            )
        if common["degraded"]:
            return InspectVerdict(
                passed=False,
                channel="output",
                action="block",
                hits=[],
                hit_count=0,
                message=f"未命中，但检测覆盖不完整，按 fail-closed 拒绝（{common['degraded_reason']}）",
                refusal_talk=self._refusal_talk,
                **common,
            )
        return InspectVerdict(
            passed=True,
            channel="output",
            action="pass",
            hits=[],
            hit_count=0,
            message="通过",
            **common,
        )

    # ------------------------------------------------------------------
    # SW-011 提示注入防护
    # ------------------------------------------------------------------
    def check_injection(self, text: str, context_fields: list[str] | None = None) -> InjectionVerdict:
        """`SW-011`：结构隔离 ＋ 注入模式识别。

        结构隔离 = 上下文类字段**只作为素材注入、不作为指令执行**；本方法对传入的
        `context_fields` 一律登记为「已隔离」，并对 `text` 做模式识别。
        """
        degraded, reason = self._degradation()
        isolated = list(context_fields or [])
        patterns = [name for name, rx in _INJECTION_PATTERNS if rx.search(text or "")]

        if patterns:
            return InjectionVerdict(
                passed=False,
                blocked=True,
                patterns=patterns,
                isolated_fields=isolated,
                message=f"识别到提示注入模式：{'/'.join(patterns)}，已拒绝执行",
                degraded=degraded,
                degraded_reason=reason,
            )
        if degraded:
            # 注入检测不依赖词库，但「覆盖不完整」仍须如实告知；不因此误判为注入
            return InjectionVerdict(
                passed=True,
                blocked=False,
                patterns=[],
                isolated_fields=isolated,
                message="未识别到注入模式（检测覆盖不完整，见 degraded_reason）",
                degraded=True,
                degraded_reason=reason,
            )
        return InjectionVerdict(
            passed=True,
            blocked=False,
            patterns=[],
            isolated_fields=isolated,
            message="未识别到注入模式",
            degraded=False,
            degraded_reason="",
        )

    # ------------------------------------------------------------------
    # SW-017 拒答与兜底
    # ------------------------------------------------------------------
    def refusal_talk(self) -> str:
        """`SW-017` 拒答话术。

        **配置优先、回落内置默认**（方案 B）：值由 `main.py` 自 `settings` 注入，
        改话术**不必改代码**（可配置、可审计）；未配置时回落 `_DEFAULT_REFUSAL_TALK`。
        ⚠️ **执行期不调推理后端** —— 安全兜底必须在后端不可用时仍能工作。
        """
        return self._refusal_talk

    def clarify_talk(self) -> str:
        """`SW-017` 澄清话术（修改意见含糊时触发）。同 `refusal_talk`：配置优先。"""
        return self._clarify_talk

    # ------------------------------------------------------------------
    # SW-017 澄清判定（口径 A：必填项缺失即含糊）
    # ------------------------------------------------------------------
    #: `revise` 修改意见的**必填信息项**（口径 A 的判定依据）：
    #: 缺任一项即视为「意图不唯一」⇒ 不猜、不择优，转澄清。
    #: ⚠️ **口径 A 只覆盖「缺项」**，覆盖不了「表述歧义」——
    #:   按项目方 2026-10-16 裁决「覆盖率不足再叠加 B（模型判定）」，
    #:   故本方法预留 `_ambiguity_hook` 钩子（默认无钩子 ＝ 未启用）。
    _CLARIFY_REQUIRED_ITEMS: tuple[str, ...] = (
        "target_stage",
        "modification_request",
    )

    def detect_ambiguity(self, request: dict[str, Any]) -> list[str]:
        """判定修改意见是否**含糊**（`CFG-008`「含糊时澄清」契约的实现）。

        返回**缺失项列表**（空 ＝ 不含糊）；契约要求「意图不唯一时**不猜、不择优**，
        转 `guard_clarify_v1` 追问」。

        ⚠️ 口径 A（确定性规则）：只认**必填项缺失**，不猜意图；
        叠加 B（模型判定）时经 `_ambiguity_hook` 调用并取**并集**。
        """
        missing = [
            k
            for k in self._CLARIFY_REQUIRED_ITEMS
            if not str(request.get(k) or "").strip()
        ]
        hook = getattr(self, "_ambiguity_hook", None)
        if callable(hook):
            for extra in hook(request) or []:
                if extra not in missing:
                    missing.append(extra)
        return missing

    # ------------------------------------------------------------------
    # 策略视图
    # ------------------------------------------------------------------
    def policy(self) -> PolicyView:
        return PolicyView(
            lexicon_standard=self._lex.standard,
            lexicon_root=self._lex.source_root,
            category_count=self._lex.category_count,
            total_words=self._lex.total_words,
            quota_covered=self._lex.quota_covered,
            empty_categories=list(self._lex.empty_categories),
            unreadable_categories=list(self._lex.unreadable),
            warnings=list(self._lex.warnings),
            circuit_open=self.circuit_open,
            circuit_reason=self._degradation()[1],
            fail_closed=self._fail_closed,
            enforced=self._enforce,
            controlled_loaded=self._lex.controlled_loaded,
        )