"""生成后质量门禁 ＋ 「不过即重试」的判定层（`T-086`；`ISSUE-038` 的**链路侧**一半）。

## 定位

`ISSUE-042` 补的是**结构层**的落点（`app/services/artifact_contract.py`：产物形态对不对）；
本模块补的是**质量层**的落点 —— 把工程侧既有的两套门禁判据在**生成后、入库前**调用：

| 层 | 判据来源 | 判什么 | 严重档 |
| --- | --- | --- | --- |
| 工程侧 | `prompts/validate_output.py`（`R1`~`R40`） | 产物**内容**是否符合契约（枚举／成员／时长守恒／质量门／自检属实） | `errors` / `warnings` |
| 交付侧 | `delivery/validate_pack.py` | 交付包（`SW-007`）能否**交给客户**（`BLOCK` / `WARN`） | `BLOCK` / `WARN` |

⚠️ **判据口径的唯一真值是上述两个脚本**，本模块**只做调用与折算，不得抄第二份**。
抄一份＝两处口径，本工程已多次因「两处口径打架」返工（最近一例见 `ISSUE-047`）。

## 为什么必须有这一层（依据）

`OPS-002` §4.3.1（d）确立的链路形态是：
> prompt 承载质量门要求（**不可依赖**）→ 引擎受约束解码（保证**结构**合法）
> → 门禁（**必须保留**）→ 不通过则**携带诊断信息重试**

`OPS-002` §7.3 第 2 项的判据**已订正**：原文「产物**直出即合规**（无需重试）」
**只在结构层成立**，「**门禁 ＋ 重试环节不可省**」。本模块即该判据的落地。

## 两条纪律

1. **重试只针对「模型产出内容」引起的失败**。合规资产缺口（`compliance.*`）、
   必备素材缺失（`artifact.*`）、服务层域占位（`pack_id`／`provider`／`task_id`）
   **重试一次也照样失败** ⇒ 由 `retryable` 与 `non_retryable` 分开列出，
   重试回路**只在 `retryable` 非空时才重试**（否则白烧 2×300 s）。
2. **「判过且通过」与「根本没判」必须可分**（`ISSUE-042` 的教训）⇒
   判定结果恒带 `checked`，判据脚本自身抛错时 `checked=False` ＋ `ok=None`，**不得**沉默放行。

## 并发

⚠️ `validate_output.py` 用**模块级全局** `RESULT`／`UPSTREAM`／`QUIET` 累积判定结果，
且 `vllm_max_concurrency` 默认为 **10** ⇒ 本模块对工程侧判定加 `asyncio.Lock` **串行化**。
（交付侧 `validate_pack.py` 的 `Report` 是**局部对象**，天然可重入，但仍随工程侧一起串行，
以避免「两套判据在同一份产物上得出互相矛盾的结论」这类难查的问题。）
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import threading
from pathlib import Path
from typing import Any, NamedTuple

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 门禁判据脚本相对**工程代码目录**的位置（`T-086`：沿用既有脚本，不新建判据）。
_ENGINE_VALIDATOR_REL = Path("prompts") / "validate_output.py"
_PACK_VALIDATOR_REL = Path("delivery") / "validate_pack.py"

#: **重试无法解决**的失败特征（子串匹配，作用于交付侧 `BLOCK` 的 **code** 与工程侧 `errors` 的文本）。
#:
#: ⚠️ 判据是「**该失败的原因是否在服务层域／合规资产侧**」，而不是「这条规则严不严」：
#: - `compliance.*` —— 内容安全／版权／标识／声明编号的结果由**服务层与合规资产**决定，
#:   模型无从影响（且服务层已强制覆盖，见 `pack_meta.apply_service_truth`）；
#: - `artifact.*` —— 标识素材包／合规声明等**必备文件**缺失（`SW-014`）；
#: - `meta.aigc` / `meta.field` / `meta.duplicate` —— 标识块的**存在性与唯一性**；
#: - `pack_id` / `generator.provider` / `task_id` —— 服务层域字段的占位形态
#:   （未配置企业码／任务号时报出，属**配置未齐**，重试无用）。
#:
#: 其余（`unit.*`／`consistency.*`／`gate.*`／`R9`~`R25` 一类）**都算可重试** ——
#: 它们描述的是模型这次**怎么写的**，重采样有机会改变。
_NON_RETRYABLE_MARKERS: tuple[str, ...] = (
    "compliance",
    "artifact.",
    "meta.aigc",
    "meta.field",
    "meta.duplicate",
    "manifest.",
    "pack_id",
    "generator.provider",
    "task_id",
    "unsupported_task_types",
)

#: 工程侧 `errors` 里同样存在「服务层域」的失败（如 `R30 AIGC_META` 的字段与编号一致性）。
_NON_RETRYABLE_ENGINE_MARKERS: tuple[str, ...] = (
    "R30",
    "AIGC_META",
)


class QualityVerdict(NamedTuple):
    """一次门禁判定的结果。字段与日志留痕**一一对应**，便于「判过没有」可核查。"""

    stage: str
    shape: str | None
    checked: bool
    ok: bool | None
    engine_checks: int
    engine_errors: list[str]
    engine_warnings: list[str]
    pack_blocks: list[str]
    pack_warnings: list[str]
    retryable: list[str]
    non_retryable: list[str]
    enforced: bool
    reason: str | None = None

    def as_record(self) -> dict[str, Any]:
        """转成可 JSON 化／可入日志的扁平留痕（⚠️ 布尔与计数分开，不合并成一个结论）。"""
        return {
            "stage": self.stage,
            "shape": self.shape,
            "checked": self.checked,
            "ok": self.ok,
            # 「判了几项」与「过了没有」分开：`ok=True, checks=0` 说明**判据空转**
            "engine_checks": self.engine_checks,
            "engine_errors": len(self.engine_errors),
            "engine_warnings": len(self.engine_warnings),
            "pack_blocks": len(self.pack_blocks),
            "pack_warnings": len(self.pack_warnings),
            "retryable": len(self.retryable),
            "non_retryable": len(self.non_retryable),
            # ⚠️ **计数与明细都要**：计数只看得出「失败了几项」，而 `T-086` 的
            #    「如实登记／如实拒绝」要求能举证**具体哪条判据**失败 —— 尤其
            #    `unit.shot_missing`（引用断链）这类需人工判断成因的项，
            #    没有明细就无法核查「重试到底有没有把它消掉」。
            "engine_error_codes": list(self.engine_errors),
            "pack_block_codes": list(self.pack_blocks),
            "retryable_codes": self.retryable[:12],
            "non_retryable_codes": self.non_retryable[:12],
            "enforced": self.enforced,
            "reason": self.reason,
        }


#: 工程代码目录（`app/services/quality_gate.py` → 上溯两级）。
_CODE_DIR = Path(__file__).resolve().parents[2]

_module_lock = threading.Lock()
_engine_module: Any | None = None
_pack_module: Any | None = None
#: 工程侧判据的**串行化闸**（它用模块级全局累积结果，见模块 docstring「并发」）。
_engine_serial = asyncio.Lock()


def _load_module(path: Path, name: str) -> Any | None:
    """按路径加载判据脚本（`prompts/` 与 `delivery/` 都不是包，不能 `import`）。"""
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 路径存在即应可加载
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine_validator() -> Any | None:
    global _engine_module
    with _module_lock:
        if _engine_module is None:
            _engine_module = _load_module(_CODE_DIR / _ENGINE_VALIDATOR_REL, "_t086_validate_output")
            if _engine_module is None:
                logger.warning(
                    "quality_gate_engine_missing",
                    extra={"extra_fields": {"path": str(_CODE_DIR / _ENGINE_VALIDATOR_REL)}},
                )
        return _engine_module


def _pack_validator() -> Any | None:
    global _pack_module
    with _module_lock:
        if _pack_module is None:
            _pack_module = _load_module(_CODE_DIR / _PACK_VALIDATOR_REL, "_t086_validate_pack")
            if _pack_module is None:
                logger.warning(
                    "quality_gate_pack_missing",
                    extra={"extra_fields": {"path": str(_CODE_DIR / _PACK_VALIDATOR_REL)}},
                )
        return _pack_module


def applies_to(stage: str) -> bool:
    """本阶段是否适用门禁（配置位 `quality_gate_stages`）。"""
    settings = get_settings()
    return bool(settings.quality_gate_enabled) and stage in settings.quality_gate_stage_set


def _classify(items: list[str], markers: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """按 `markers` 子串把失败项分成（可重试，重试无用）。"""
    retryable: list[str] = []
    non_retryable: list[str] = []
    for item in items:
        low = item.lower()
        if any(m.lower() in low for m in markers):
            non_retryable.append(item)
        else:
            retryable.append(item)
    return retryable, non_retryable


def _engine_errors(module: Any, doc: Any, where: str, upstream: dict[str, str]) -> dict[str, Any]:
    """**同步**调用工程侧判据（调用方负责持有 `_engine_serial`）。"""
    import tempfile as _tf

    module.QUIET = True
    module.RESULT = {"checks": 0, "errors": [], "warnings": []}
    module.UPSTREAM = {"doc": None, "src": None, "sb_doc": None, "sb_src": None}
    tmp = _tf.TemporaryDirectory()
    try:
        for shape, text in (upstream or {}).items():
            p = Path(tmp.name) / f"upstream_{shape}.json"
            p.write_text(text, encoding="utf-8")
            up = module._load_doc_by_shape(str(p))  # noqa: SLF001 - 判据脚本的官方入口
            if up is None:
                continue
            if shape == "storyboard":
                module.UPSTREAM["sb_doc"], module.UPSTREAM["sb_src"] = up, p.name
            else:
                module.UPSTREAM["doc"], module.UPSTREAM["src"] = up, p.name
        module.validate_doc(doc, where, fname=f"{where}.json")
        return {
            "checks": module.RESULT["checks"],
            "errors": list(module.RESULT["errors"]),
            "warnings": list(module.RESULT["warnings"]),
        }
    finally:
        module.UPSTREAM = {"doc": None, "src": None, "sb_doc": None, "sb_src": None}
        tmp.cleanup()


def _pack_report(module: Any, text: str) -> dict[str, Any]:
    """**同步**调用交付侧门禁（写临时文件：该脚本的入口就是「按路径校验」）。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "pack.json"
        p.write_text(text, encoding="utf-8")
        rep = module.validate_pack(p)
    blocks = [f"{code}｜{msg}" for lv, code, msg in rep.items if lv == module.BLOCK]
    warns = [f"{code}" for lv, code, _ in rep.items if lv == module.WARN]
    return {"blocks": blocks, "warnings": warns}


async def check(
    stage: str,
    *,
    text: str,
    upstream: dict[str, str] | None = None,
) -> QualityVerdict:
    """对**生成后的产物文本**跑门禁，返回判定（永不抛错 —— 判据自身失败记为 `checked=False`）。

    `upstream` 形如 `{"script": <文本>, "storyboard": <文本>}`，键为**形态名**
    （与判据脚本 `--script`／`--storyboard` 的语义一致）；缺上游时跨层规则会跳过并告警。
    """
    settings = get_settings()
    enforced = bool(settings.quality_gate_enforce)
    where = f"{stage}"

    doc: Any = None
    reason: str | None = None
    try:
        doc = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - 解析不了＝**没通过**，不是判据失败
        return QualityVerdict(
            stage=stage, shape=None, checked=True, ok=False,
            engine_checks=0, engine_errors=[f"产物不是合法 JSON：{type(exc).__name__}"],
            engine_warnings=[], pack_blocks=[], pack_warnings=[],
            retryable=["产物不是合法 JSON"], non_retryable=[],
            enforced=enforced, reason="unparsable",
        )

    shape = None
    engine = _engine_validator()
    engine_out = {"checks": 0, "errors": [], "warnings": []}
    if engine is None:
        reason = "engine_validator_missing"
    else:
        try:
            shape = engine.detect_shape(doc)
        except Exception:  # noqa: BLE001 - 形态识别失败不阻断「判过没有」的可核查性
            shape = None
        try:
            async with _engine_serial:
                engine_out = await asyncio.to_thread(_engine_errors, engine, doc, where, upstream or {})
        except Exception as exc:  # noqa: BLE001
            reason = f"engine_validator_error:{type(exc).__name__}"

    pack_out = {"blocks": [], "warnings": []}
    if settings.quality_gate_pack_check and shape == "pack":
        pack = _pack_validator()
        if pack is None:
            reason = (reason or "") + ";pack_validator_missing"
        else:
            try:
                pack_out = await asyncio.to_thread(_pack_report, pack, text)
            except Exception as exc:  # noqa: BLE001
                reason = (reason or "") + f";pack_validator_error:{type(exc).__name__}"

    failures = list(engine_out["errors"]) + list(pack_out["blocks"])
    retryable, non_retryable = _classify(
        failures, _NON_RETRYABLE_MARKERS + _NON_RETRYABLE_ENGINE_MARKERS
    )

    # ---- 「判过且通过」与「根本没判」必须可分（`ISSUE-042` 的教训，本函数**自己**也要守）----
    # ⚠️ 实测踩到（本批探针）：产物是**API 信封**（`{"request_id":…,"data":…}`）而非裸产物时，
    #    `detect_shape` 返回 `None` ⇒ 判据脚本走「无法识别形态 → 告警并跳过」⇒
    #    **`checks=0`、`errors=0`**，若直接按「无失败即通过」折算就会得到 **`ok=true`** ——
    #    一个「什么都没判」的产物被报成「通过」。这正是 `ISSUE-042` 的同形缺陷，
    #    故在此**显式堵住**：`ok` 恒为三态（`True`／`False`／`None`），`None` ＝ **无法判定**。
    #    判定顺序不可换：**有失败 → False**（失败是硬事实）；**判据缺失/自爆 → None**（不猜）。
    if failures:
        ok: bool | None = False
    elif reason:
        ok = None
    elif shape is None:
        ok, reason = None, "shape_undetected"
    elif engine_out["checks"] == 0 and not pack_out["warnings"]:
        ok, reason = None, "nothing_checked"
    else:
        ok = True
    return QualityVerdict(
        stage=stage, shape=shape, checked=True, ok=ok,
        engine_checks=engine_out["checks"],
        engine_errors=list(engine_out["errors"]),
        engine_warnings=list(engine_out["warnings"]),
        pack_blocks=list(pack_out["blocks"]),
        pack_warnings=list(pack_out["warnings"]),
        retryable=retryable, non_retryable=non_retryable,
        enforced=enforced, reason=reason,
    )


def should_retry(verdict: QualityVerdict) -> bool:
    """**是否值得重试** —— 唯一判据是「是否存在模型可影响的失败」。

    ⚠️ 这一条是本模块最要紧的产出：若把「合规资产未接入」当成的失败也拿去重试，
    回路会**每轮白烧数百秒**、最后还是拒绝，且日志上看起来像「模型不行」——
    归因方向完全错（本工程反复踩过的同族问题）。
    """
    return bool(verdict.retryable)
