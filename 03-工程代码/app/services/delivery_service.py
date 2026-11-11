"""交付包服务层 —— **SW-I04**（交付四件套：提示词集 ＋ 标识素材包 ＋ 合规声明 ＋ 清单）。

⚠️ **边界（`SYS-018`）**：本服务**不对接任何下游平台 API、不托管下游密钥与成片**——
只产出**交付包文件**（落盘到本地目录），由人工/外部流程取走。

⚠️ **本服务不生成合规结论**：`compliance.*` 的真值**只来自服务层**
（`pack_meta.build_pack_meta`）与**双闸实测留痕**；**不得**在此处臆造「已通过」。

---

## 与 `PRO-007`（`ISSUE-047`）的关系

`PRO-007` 已把根因拆成三条：

| 根因 | 内容 | 本服务的处置 |
| --- | --- | --- |
| **A** | `compliance.*` 的 enum 无「未取得」档 | **不擅自改契约**（属第二步、待项目方裁决）⇒ 继续写占位，**如实** |
| **B** | `pack_id` 的 pattern 不容纳占位形态 | 同上 ⇒ 继续写占位，**如实** |
| **C** | 判据用否定式，把「未取得」读成「未通过」 | 由 `PRO-007` 第一步处置（改 `validate_pack.py`），**不在本服务** |

⇒ **本服务产出的包在正式交付意义上是「预演包」**（根因 A／B 未决前必然如此），
必须保留 `meta.notes` 的「不得用于正式交付」留痕（`NT-02` 纪律）。

---

## 三件套的产出与留痕

| 件 | 载体 | 状态 |
| --- | --- | --- |
| ① 提示词集 | `<out>/<pack_id>/pack.json` | ✅ 产物本体 |
| ② AIGC 元数据块 | `<out>/<pack_id>/aigc_meta.json` | ✅ 服务层装配（`SW-013`）；**独立落盘**（§8.3 第 6 项「仅一份、可解析」） |
| ③ 标识素材包 | `<out>/<pack_id>/assets/`（8 个角标 PNG ＋ `AST-002` 规格 ＋ `AST-001` 说明） | ✅ 素材**已备**（`delivery/assets/`） |
| ④ 合规声明 | `<out>/<pack_id>/AST-004_compliance_statement.md` | ✅ 由服务层真值渲染（占位**原样保留**） |
| ＋ 质量门报告 | `<out>/<pack_id>/qa/audit_report.txt` | ✅ 随包留档（§8.3 第 13 项）；内容取**真实判定**，无镜头写「未执行」 |
| ⑤ 清单 | `<out>/<pack_id>/manifest.json` | ✅ **`CFG-005` v1.1.0**（`ISSUE-057` 候选① 重写；自检 18 项按实际判定填充） |

⚠️ **`manifest.json` 不是「文件列表」**：它是 `CFG-005` 契约件（`additionalProperties:false`），
字段集固定为 `manifest_version`／`pack_id`／`statement_id`／`created_at`／`artifacts`／
`exports`／`adapters`／`units`／`quality_gate`／`human_review`／`self_check`／`retention`／
`spec_version`／`provider`。**塞自拟字段会被 Schema 判 BLOCK**（旧实现即栽在这里）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.services import copyright_service
from app.services.export_service import build_exports
from app.services.pack_meta import (
    PLACEHOLDER_PROVIDER_CODE,
    PLACEHOLDER_PROVIDER_NAME,
    apply_service_truth,
    build_pack_meta,
)
from app.services.quality_gate import load_pack_validator

#: 交付包 schema（`CFG-006`）——顶层必填键（与 `artifact_contract` 的 pack 形态同源）
PACK_TOP_KEYS = (
    "schema_version", "meta", "style_bible", "units", "shots", "aigc_meta",
)

#: 合规声明模板（`AST-004`）相对路径（相对工程 `03-工程代码/`）
_COMPLIANCE_TEMPLATE = "delivery/templates/AST-004_compliance_statement_v1.md"

#: 标识素材目录（`AST-001`）相对路径
_ASSETS_DIR = "delivery/assets"

#: `meta.notes` 的预演包留痕（`NT-02` 纪律：根因 A／B 未决前**不得**用于正式交付）
PREVIEW_NOTE = (
    "本包为占位预演：企业码／内容编号／合规声明编号未取得，"
    "不得用于正式交付；正式交付前须回填并复检（PRO-007 根因 A／B）。"
)

#: **服务层形态**的内容编号：`<企业码>-PK-<YYYYMMDD>-<8位短码>`
#: （企业码可为 `{{PROVIDER_CODE}}` 占位；短码为 8 位大写十六进制）
_PACK_ID_RE = re.compile(r"^(?:\{\{[A-Z_]+\}\}|[A-Z0-9]{2,8})-PK-\d{8}-[0-9A-F]{8}$")

#: 清单 `spec_version` 的取值（依据的交付规范版本）。
#: ⚠️ 该常量**必须**与 `01-架构设计/SPEC-008_*.md` 正文版本一致 ——
#: 由 `tests/test_delivery.py::test_spec_version_matches_norm` **互锁对拍**（`PRO-012` 变更三件套）。
SPEC_VERSION = "NORM-DELIVERY-001 v2.4"


def _load_human_review(settings: Any, pack_id: str) -> list[dict[str, Any]]:
    """读**人工核对台账**中本包的记录（§8.3 第 18 项 / §8.4）。

    ⚠️ **只认人工录入的台账文件**，**绝不**从模型产物里取 `human_review`——
    那是「让模型自己证明自己被人工核对过」，属假合规。
    台账缺失／未配置 ⇒ 返回空 ⇒ 自检第 18 项 `fail`、清单判据 `human_review.missing` BLOCK
    （**如实拦住**，不静默放行）。

    台账形态（JSON）：`{"records": [{"pack_id": "...", "no": 18, "item": "...",
    "result": "pass|fail|warn", "checked_at": "ISO8601", "operator": "...", "detail": "..."}]}`
    """
    path = str(getattr(settings, "human_review_ledger", "") or "").strip()
    if not path:
        return []
    ledger = Path(path)
    if not ledger.is_file():
        return []
    try:
        data = json.loads(ledger.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = data.get("records") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("pack_id", "")) != pack_id:
            continue
        item = {k: row[k] for k in ("no", "item", "result", "checked_at", "operator", "detail")
                if k in row}
        out.append(item)
    return out


@dataclass
class DeliveryResult:
    """一次交付打包的结果（**服务层返回，不含 HTTP 语义**）。"""

    pack_id: str
    pack_dir: str
    files: list[str] = field(default_factory=list)
    #: ⚠️ **未回填的占位字段**（`_unfilled`）——如实暴露给调用方与留痕
    unfilled: list[str] = field(default_factory=list)
    #: ⚠️ **本包是否为「预演包」**（存在占位 ⇒ 是）。**不得用于正式交付**。
    is_preview: bool = True
    #: 交付包本体的字节数（供留痕）
    pack_bytes: int = 0
    #: **交付前自检结论**（`ISSUE-055` ①′）：`checked`／`blocked`／`blocks`／`warns`／
    #: `scope`／`report_path`。预演包只呈现不拒付；正式包 `blocked=true` ⇒ 抛 422。
    gate: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "pack_dir": self.pack_dir,
            "files": list(self.files),
            "unfilled": list(self.unfilled),
            "is_preview": self.is_preview,
            "pack_bytes": self.pack_bytes,
            "gate": dict(self.gate),
        }


#: `CFG-006` 的 `generation_trace.model.backend` 枚举（schema 真相源）
_MODEL_BACKENDS = ("vllm", "transformers", "llama_cpp", "remote_api", "other")


def _model_trace(art: dict[str, Any]) -> dict[str, Any]:
    """装配**合规**的 `generation_trace.model`（2026-11-03 真机实测修复）。

    ⚠️ **语义真相源＝官方样例** `CFG-004_demo_pack.json`：
    ```json
    "model": {"name": "Qwen2.5-7B-Instruct", "backend": "vllm", "revision": "main"}
    ```
    ⇒ **`name`＝模型名**／**`backend`＝后端枚举**／**`revision`＝模型 revision**。

    ⚠️ **此前的两处装配都反了**（实测 BLOCK：`backend` is a required property
    ＋ `version` was unexpected）：
    - 编排层留痕 `art["model"]` ＝ `{"name": backend.name, "version": backend.version}`
      —— 而 `backend.name` 是**后端标识**（`vllm`）、`backend.version` 是**模型名**
      （`inference/base.py`）⇒ **两者语义与 schema 正好相反**；
    - ⇒ 此处**从留痕派生**：`backend` ＝ 留痕 `name`（须落在枚举内），
      `name`／`revision` ＝ 留痕 `version`（模型名）。
    """
    m = art.get("model") if isinstance(art.get("model"), dict) else {}
    backend = str(m.get("name") or "").strip().lower()
    if backend not in _MODEL_BACKENDS:
        backend = "other"
    model_name = str(m.get("version") or "").strip() or "unknown"
    return {"name": model_name, "backend": backend, "revision": model_name}


#: `CFG-006` 的 `generation_trace.model.backend` 枚举（schema 真相源）
_MODEL_BACKENDS = ("vllm", "transformers", "llama_cpp", "remote_api", "other")


def _model_trace(art: dict[str, Any]) -> dict[str, Any]:
    """装配**合规**的 `generation_trace.model`（2026-11-03 真机实测修复）。

    ⚠️ **语义真相源＝官方样例** `CFG-004_demo_pack.json`：
    ```json
    "model": {"name": "Qwen2.5-7B-Instruct", "backend": "vllm", "revision": "main"}
    ```
    ⇒ **`name`＝模型名**／**`backend`＝后端枚举**／**`revision`＝模型 revision**。

    ⚠️ **此前的两处装配都反了**（实测 BLOCK：`backend` is a required property
    ＋ `version` was unexpected）：
    - 编排层留痕 `art["model"]` ＝ `{"name": backend.name, "version": backend.version}`
      —— 而 `backend.name` 是**后端标识**（`vllm`）、`backend.version` 是**模型名**
      （`inference/base.py`）⇒ **两者语义与 schema 正好相反**；
    - ⇒ 此处**从留痕派生**：`backend` ＝ 留痕 `name`（须落在枚举内），
      `name`／`revision` ＝ 留痕 `version`（模型名）。
    """
    m = art.get("model") if isinstance(art.get("model"), dict) else {}
    backend = str(m.get("name") or "").strip().lower()
    if backend not in _MODEL_BACKENDS:
        backend = "other"
    model_name = str(m.get("version") or "").strip() or "unknown"
    return {"name": model_name, "backend": backend, "revision": model_name}


def _load_pack_from_session(svc: Any, session_id: str) -> dict[str, Any]:
    """从会话取 `shot_prompt` 阶段的交付包产物。

    ⚠️ **服务层真值以本函数装配的 `meta` 为准**，不依赖产物自带：
    编排层的 `apply_service_truth` 遵守「**只覆盖、不新增**」（模型没输出的服务层域键
    **不补** —— 那是 `R27`／`R30` 的判据，替模型补洞等于掩盖缺键）。
    ⇒ 产物里 `meta` 为空（骨架／mock 形态）时，交付端点**自己装配** `meta`
    （服务层**确有**真值：`pack_id`／`compliance`／`generator`／`generation_trace`）。

    ⚠️ **不得**在此处臆造合规结论：`compliance.*` 一律取 `build_pack_meta`
    （双闸实测留痕取不到时写占位，如实）。
    """
    rec = svc._require(session_id)  # noqa: SLF001 —— 同包内服务，复用编排层的存在性校验
    art = rec.artifacts.get("shot_prompt")
    if art is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            f"会话 {session_id} 尚无 shot_prompt 产物，无法打包交付",
            details={"session_id": session_id, "have_stages": sorted(rec.artifacts)},
        )
    # ⚠️ 产物形态（`dialogue_service` 的 `artifact` 构造）：**只有 `text`**（模型输出的
    # JSON 文本），**没有 `json` 键** ⇒ 必须按文本解析。
    doc: Any = None
    if isinstance(art, dict):
        doc = art.get("json")
    if not isinstance(doc, dict):
        text = art.get("text") if isinstance(art, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "会话产物结构异常：无 JSON 本体也无文本",
                details={"session_id": session_id},
            )
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"会话产物不是合法 JSON：{exc}",
                details={"session_id": session_id},
            ) from exc
    missing = [k for k in PACK_TOP_KEYS if k not in doc]
    if missing:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"交付包缺顶层键：{'、'.join(missing)}（形态契约 `CFG-006`）",
            details={"missing": missing},
        )
    return doc


def _render_compliance_statement(pack: dict[str, Any]) -> str:
    """由服务层真值渲染合规声明（`AST-004` 模板）。

    ⚠️ **占位纪律**：模板中的 `{{...}}` 一律**原样保留**（不编造企业名／编号）。
    """
    tpl = _project_root() / _COMPLIANCE_TEMPLATE
    if not tpl.is_file():
        return (
            "# 交付合规声明\n\n"
            f"> ⚠️ 合规声明模板缺失（预期路径：{_COMPLIANCE_TEMPLATE}），"
            "本声明由服务层最小模板代偿，**须补齐**。\n\n"
            + _render_compliance_fallback(pack)
        )
    text = tpl.read_text(encoding="utf-8")
    meta = pack.get("meta") or {}
    comp = meta.get("compliance") or {}
    safety = comp.get("safety_check") or {}
    mapping = {
        "{{PACK_ID}}": str(meta.get("pack_id", "")),
        "{{PROVIDER_NAME}}": str((meta.get("generator") or {}).get("provider", "")),
        "{{PROVIDER_CODE}}": str((meta.get("generator") or {}).get("provider_code", "")),
        "{{STATEMENT_ID}}": str(comp.get("statement_id", "")),
        "{{CREATED_AT}}": str(meta.get("created_at", "")),
        "{{SAFETY_INPUT}}": str(safety.get("input", "")),
        "{{SAFETY_OUTPUT}}": str(safety.get("output", "")),
        "{{COPYRIGHT_STATUS}}": str((comp.get("copyright_check") or {}).get("status", "")),
        "{{MARKING_EXPLICIT}}": str((comp.get("marking_check") or {}).get("explicit", "")),
        "{{MARKING_IMPLICIT}}": str((comp.get("marking_check") or {}).get("implicit", "")),
    }
    for k, v in mapping.items():
        text = text.replace(k, v)

    # 附：**《版权与改编来源声明》指向**（`SW-015` ②「可导出」的可发现性）
    #    ⚠️ 该声明件是独立落盘文件，但清单（`CFG-005`）的 `artifacts` 是
    #    **固定五项**且 `additionalProperties: false` ⇒ **没有**它的登记位。
    #    为此改契约成本高、收益低 ⇒ 改由本合规声明**显式引用文件名**，
    #    确保下游拿到交付包时**能发现**它，而不是靠翻目录。
    _pid = str(meta.get("pack_id", ""))
    if _pid:
        text = text.rstrip("\n") + (
            f"\n\n> **附随文件**：本包另附 `{copyright_service.declaration_filename(_pid)}`"
            "（《版权与改编来源声明》），载明改编来源声明与相似度比对结论。\n"
        )
    return text


def _render_compliance_fallback(pack: dict[str, Any]) -> str:
    """合规声明的最小代偿模板（模板文件缺失时用）。"""
    meta = pack.get("meta") or {}
    comp = meta.get("compliance") or {}
    safety = comp.get("safety_check") or {}
    return (
        "| 项 | 值 |\n| --- | --- |\n"
        f"| 内容编号 `pack_id` | `{meta.get('pack_id', '')}` |\n"
        f"| 生成时间 | `{meta.get('created_at', '')}` |\n"
        f"| 内容安全（输入） | `{safety.get('input', '')}` |\n"
        f"| 内容安全（输出） | `{safety.get('output', '')}` |\n"
        f"| 版权校验 | `{comp.get('copyright_check', {}).get('status', '')}` |\n"
        f"| 显式标识 | `{comp.get('marking_check', {}).get('explicit', '')}` |\n"
        f"| 隐式标识 | `{comp.get('marking_check', {}).get('implicit', '')}` |\n"
        f"| 合规声明编号 | `{comp.get('statement_id', '')}` |\n"
    )


def _project_root() -> Path:
    """工程 `03-工程代码/` 根（`app/` 的上一级）。"""
    return Path(__file__).resolve().parents[2]


def _copy_assets(dst: Path) -> list[str]:
    """复制**标识素材包**（显式角标 PNG ＋ 素材说明）到交付目录。"""
    src = _project_root() / _ASSETS_DIR
    if not src.is_dir():
        return []
    out = dst / "assets"
    out.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for p in sorted(src.iterdir()):
        if p.is_file() and p.suffix.lower() in (".png", ".md", ".json"):
            shutil.copy2(p, out / p.name)
            copied.append(f"assets/{p.name}")
    return copied


# ──────────────────────────────────────────────────────────────────────────
# §8.3 十八项自检 ↔ 判据映射（`ISSUE-057` 候选①，2026-11-04）
# ──────────────────────────────────────────────────────────────────────────

#: ⚠️ **映射口径说明**：`SPEC-008` §8.3 的 18 项是**给人看的清单**，
#: 而工程判据粒度更细（一个自检项常对应多条判据码）⇒ 本表是**多对一**映射。
#: `detail` 里保留**原始判据码**，使「清单说 fail／warn」可**逐条回溯**到门禁条目。
#:
#: `from` 取值（判据来源）：
#: - `pack`        ⇒ 由包侧门禁（`delivery/validate_pack.py`）的条目推导
#: - `assets`      ⇒ 由清单装配时的**实际素材清点**推导（包侧无对应判据）
#: - `statement`   ⇒ 由 `statement_id` 实际值推导（占位 ⇒ 未取得）
#: - `adapters`    ⇒ 由适配条目 `verify_status` 推导（§8.3 第 12 项）
#: - `human_review`⇒ 由人工核对台账推导（§8.3 第 18 项）
#: - `out_of_scope`⇒ 交付包层面**不可机检**（如实标 `warn`，**绝不标 `pass`**）
#:
#: `requires` 取值：该项的判定对象；对象为空 ⇒ **没检**（标 `warn`，不标 `pass`）。
_SELF_CHECK_SPEC: tuple[dict[str, Any], ...] = (
    {"no": 1, "item": "输入内容安全检测通过", "from": "pack", "match": "输入侧",
     "codes": ("compliance.safety", "compliance.safety_pending")},
    {"no": 2, "item": "输出内容安全复检通过", "from": "pack", "match": "输出侧",
     "codes": ("compliance.safety", "compliance.safety_pending")},
    {"no": 3, "item": "版权/改编风险校验完成（有风险须提示并记录）", "from": "pack",
     # ⚠️ **2026-11-05 裁决**：`compliance.copyright`（版权未校验）由 BLOCK 降级为 WARN，
     #    码名改为 `compliance.copyright_pending`（见 `delivery/validate_pack.py` 同处注释）。
     #    ⇒ 本项由「BLOCK ⇒ fail」变为「WARN ⇒ warn」：**如实呈现「未校验」**，
     #      不再阻断交付（本工程无版权风险检测能力，占位是常态）。
     #    三项码并列覆盖：`_pending`（未接入/占位）／`copyright`（旧码，保留兼容）／`_risk`（检出风险）。
     "codes": ("compliance.copyright", "compliance.copyright_pending",
               "compliance.copyright_risk")},
    {"no": 4, "item": "提示词包通过 JSON Schema 校验",
     "from": "pack",
     # ⚠️ 除 Schema 外的「取值合规」判据（词表／风格锚点／任务类型／时间格式／
     #    单镜时长上下限）也归此项：它们同属「包的形态与取值是否合规」，
     #    在 18 项里没有更贴切的归属（多对一映射口径见上）。
     "codes": ("schema.pack", "schema.missing",
               "vocab.amplitude", "vocab.camera_alias", "vocab.camera_move", "vocab.height",
               "vocab.lighting", "vocab.lighting_default", "vocab.optics", "vocab.roll",
               "vocab.shot_size", "vocab.speed", "vocab.transition",
               "camera.amp_speed", "prompt.param", "prompt.quote",
               "style.anchors", "style.drift", "task.type", "task.unsupported",
               "provider.code", "time.format",
               "duration.integer", "duration.min", "duration.max")},
    {"no": 5, "item": "一致性校验（style_ref / character_refs / unit_id / 时长合计）",
     "from": "pack", "requires": "units",
     "codes": ("consistency.style_ref", "consistency.character_ref", "consistency.duration",
               "unit.ref", "unit.orphan", "unit.duplicate_id", "unit.missing",
               "unit.shot_missing")},
    {"no": 6, "item": "AIGC 元数据块存在、字段齐全、仅一份、可解析", "from": "pack",
     "codes": ("meta.aigc", "meta.field", "meta.duplicate", "meta.produce_id",
               "meta.propagate_id", "meta.propagator")},
    {"no": 7, "item": "显式标识存在于所有导出文件（按格式差异化注入）", "from": "pack",
     "codes": ("compliance.marking", "compliance.marking_pending")},
    {"no": 8, "item": "标识素材包完整（4 个 PNG）+ 规格文件存在", "from": "assets"},
    {"no": 9, "item": "合规声明已生成且 8 项要素齐全", "from": "statement",
     "codes": ("compliance.statement", "compliance.statement_pending")},
    {"no": 10, "item": "交付包内无密钥、无外部依赖、离线可用", "from": "pack",
     "codes": ("secret.leak", "offline.dependency")},
    {"no": 11, "item": "系统内不存在去标识功能入口（含管理控制台）", "from": "out_of_scope"},
    {"no": 12, "item": "适配输出与 verify_status 一致", "from": "adapters"},
    {"no": 13, "item": "镜头语言质量门 11 项全通过（逐单元 + 整片）", "from": "pack",
     "requires": "shots", "codes": ("gate.fail", "gate.empty", "gate.pass")},
    {"no": 14, "item": "台词—时长校验通过（每镜 ≤ 9 字/秒）", "from": "pack",
     "requires": "shots", "codes": ("dialogue.rate",)},
    {"no": 15, "item": "动作复杂度—时长预算校验完成", "from": "pack",
     "requires": "shots", "codes": ("action.incomplete",)},
    {"no": 16, "item": "不存在单镜生成单元；单元内运镜类型不重复；每单元 2–3 镜",
     "from": "pack", "requires": "units",
     "codes": ("unit.size", "unit.camera_dup", "camera.roll_dup",
               "unit.soundscape", "unit.music")},
    {"no": 17, "item": "目标模型不支持负向字段时，交付文本中无负向残留",
     "from": "pack", "requires": "shots",
     # ⚠️ `negative.residue` 的判据是**逐镜**遍历 `shots`（`validate_pack.py` ⑬）⇒
     #    镜头为空时判据根本没跑。「没跑」不等于「通过」，故必须声明 requires。
     "codes": ("negative.residue", "adapter.negative")},
    {"no": 18, "item": "角色一致性 / 跨镜连续性人工核对完成", "from": "human_review"},
)

#: 正向记录码（**不是问题**；仅作「检过了」的书面证据，如质量门全通过）
_POSITIVE_CODES = frozenset({"gate.pass"})

#: ⚠️ 清单侧判据码（由 `validate_manifest` 产出）——**不进**包侧自检映射，
#: 因为自检在清单**生成时**填充（此时清单侧判据尚未运行，属循环依赖）。
#: 它们各自的「真实来源」已在表内以 `from` 字段直接声明（assets/statement/
#: adapters/human_review）⇒ `test_self_check_map_covers_all_codes` 据此豁免。
_MANIFEST_SIDE_CODES = frozenset({
    "artifact.missing", "artifact.overlay", "artifact.quality_gate",
    "export.mark", "export.meta", "export.section",
    "manifest.pack_id", "manifest.statement_pending",
    "selfcheck.missing", "selfcheck.fail",
    "human_review.missing", "human_review.field",
    # ⚠️ 以下三条是**清单内部自洽性**检查（拿 self_check／adapters／quality_gate 相互印证），
    #    必须等清单写完之后才能判 ⇒ 属清单侧，不进生成期的自检映射。
    "adapter.status", "gate.status", "schema.manifest",
})


def _not_obtained(value: Any) -> bool:
    """判断合规字段是否**未取得**（与 `validate_pack._is_not_obtained` **同口径**）。

    ⚠️ 两处共用一套判据 ⇒ 由 `test_self_check_map` 的互锁测试对拍；
    任一侧改口径（例如只认占位不认 `not_available`）即当场报警。
    """
    if value is None:
        return True
    text = str(value).strip()
    if not text or text == "not_available" or "{{" in text or "占位" in text:
        return True
    return False


def _spec_hits(judgements: list[tuple[str, str, str]], spec: dict[str, Any],
               block_level: str) -> tuple[list[str], list[str]]:
    """把某自检项对应的门禁条目分成「阻断」与「问题」两栏（各带原始码）。"""
    codes = frozenset(spec.get("codes") or ())
    needle = spec.get("match")
    blocks: list[str] = []
    problems: list[str] = []
    for level, code, msg in judgements:
        if code not in codes:
            continue
        if needle and needle not in msg:
            continue
        if level == block_level:
            blocks.append(f"{code}: {msg}")
        elif code not in _POSITIVE_CODES:
            problems.append(f"{code}: {msg}")
    return blocks, problems


def build_self_check(
    judgements: list[tuple[str, str, str]],
    *,
    block_level: str,
    assets: list[str],
    statement_id: Any,
    adapters: list[dict[str, Any]],
    human_review: list[dict[str, Any]],
    has_shots: bool,
    has_units: bool,
    statement_file: str = "",
    exports: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按 §8.3 十八项**逐项实际判定**生成自检记录（`ISSUE-057` 候选①）。

    ⚠️ **铁律：不编造 `pass`**。三种「拿不到证据」的情形一律标 `warn`／`fail`：
    1. 判定对象为空（`shots`／`units` 没有）⇒ **没检** ⇒ `warn`；
    2. 交付包层面无判据（第 11 项系统级）⇒ `warn` ＋ 原因；
    3. 有判据但无机器可判内容（第 9 项「8 项要素齐全」）⇒ `warn`。
    """
    rows: list[dict[str, Any]] = []
    for spec in _SELF_CHECK_SPEC:
        src = spec["from"]
        result, detail = "pass", ""
        need = spec.get("requires")
        lacked = (need == "shots" and not has_shots) or (need == "units" and not has_units)

        # ⚠️ **第 7 项（显式标识存在于所有导出文件）自 2026-11-10 起按「导出物实测」判定**
        #    （`T-006` 接线）：`exports` 为 `None` ⇒ 沿用旧口径（只看
        #    `meta.compliance.marking_check` 字段，属「字段填了什么」）；
        #    给出 `exports`（含空列表）⇒ 只认**回读落盘文件取证**的结果，
        #    「一份导出物都没有」＝**没检**，如实判 `fail`（`§8.3` 该行为「阻断交付」）。
        if spec["no"] == 7 and exports is not None:
            missed = [str(e.get("file")) for e in exports if not e.get("explicit_mark")]
            one_section = [str(e.get("file")) for e in exports
                           if str(e.get("format")) == "txt" and not e.get("two_section")]
            if not exports:
                result, detail = "fail", "未产出任何导出物 ⇒ 该项**无判定对象**（§8.3 第 7 项：阻断交付）"
            elif missed:
                result, detail = "fail", f"{len(missed)} 份导出物缺显式标识：{', '.join(missed[:3])}"
            elif one_section:
                result = "warn"
                detail = f"{len(one_section)} 份适配 TXT 非两段式：{', '.join(one_section[:3])}"
            else:
                kinds = sorted({str(e.get("format")) for e in exports})
                detail = f"{len(exports)} 份导出物均含显式标识（{'/'.join(kinds)}）"
        elif src == "pack":
            blocks, problems = _spec_hits(judgements, spec, block_level)
            if lacked:
                result = "warn"
                detail = f"判定对象为空（{'shots' if need == 'shots' else 'units'} 无内容）⇒ 未检"
            elif blocks:
                result, detail = "fail", "｜".join(blocks[:3])
            elif problems:
                result, detail = "warn", "｜".join(problems[:3])
            else:
                positives = [msg for lv, code, msg in judgements
                             if code in _POSITIVE_CODES and lv != block_level]
                detail = "；".join(positives[:2]) or "对应判据全部通过（无异常条目）"

        elif src == "assets":
            pngs = [f for f in assets if str(f).lower().endswith(".png")]
            spec_ok = any("overlay_spec" in str(f) or "AST-002" in str(f) for f in assets)
            # ⚠️ 口径与清单判据 `artifact.overlay`（任意 .png ≥4 且含规格文件）**保持一致**，
            #    否则会出现「清单说 pass、判据说 fail」的自相矛盾。
            if len(pngs) >= 4 and spec_ok:
                detail = f"PNG {len(pngs)} 个 ＋ 规格文件 AST-002"
            else:
                result = "fail"
                detail = (f"PNG {len(pngs)}/4、规格文件{'存在' if spec_ok else '缺失'}"
                          "（§8.3 第 8 项要求 4 个 PNG + 规格文件）")

        elif src == "statement":
            blocks, _ = _spec_hits(judgements, spec, block_level)
            if blocks:
                result, detail = "fail", "｜".join(blocks[:3])
            elif _not_obtained(statement_id):
                result = "warn"
                detail = f"声明编号**结果未取得**（{statement_id!r}）⇒ 不得用于正式交付"
            elif not statement_file:
                result = "warn"
                detail = "声明编号已填，但**声明文件未落盘** ⇒ 未取得实物证据"
            else:
                # ⚠️ 「8 项要素齐全」是文字要素核对，**无机器判据** ⇒ 不得标 pass
                result = "warn"
                detail = (f"声明已生成（{statement_file}）、编号已填，"
                          "但「8 项要素齐全」无机检（人工核对承担，§8.3 第 9 项）")

        elif src == "out_of_scope":
            result = "warn"
            detail = ("交付包层面**不可机检**：属系统级审计范畴"
                      "（须核查控制台与路由表，见 `PRO-012` 覆盖矩阵第 11 项）")

        elif src == "adapters":
            if not adapters:
                result = "warn"
                detail = "本包无适配输出 ⇒ 该项**无判定对象**（未检）"
            else:
                pending = [a for a in adapters
                           if a.get("verify_status") in ("pending", "partial")]
                if pending:
                    result = "warn"
                    detail = (f"{len(pending)}/{len(adapters)} 个适配 pending/partial"
                              "⇒ 不得标为已验证（§8.3 第 12 项）")
                else:
                    detail = f"{len(adapters)} 个适配均 verified"

        elif src == "human_review":
            if not human_review:
                result = "fail"
                detail = "**无人工核对记录**（§8.3：无记录视为未做）"
            else:
                bad = [h for h in human_review
                       if any(not h.get(k) for k in ("result", "checked_at", "operator"))]
                fails = [h for h in human_review if h.get("result") == "fail"]
                warns = [h for h in human_review if h.get("result") == "warn"]
                if bad:
                    result = "fail"
                    detail = f"{len(bad)} 条记录缺「结果/时间/检查人」字段"
                elif fails:
                    result = "fail"
                    detail = f"{len(fails)} 条核对未通过"
                elif warns:
                    result = "warn"
                    detail = f"{len(warns)} 条核对标 warn"
                else:
                    detail = f"{len(human_review)} 条核对记录齐备"

        row = {"no": spec["no"], "item": spec["item"], "result": result}
        if detail:
            row["detail"] = detail
        rows.append(row)
    return rows


def render_audit_report(
    judgements: list[tuple[str, str, str]], *, pack_id: str, block_level: str
) -> str:
    """生成镜头语言质量门报告 `qa/audit_report.txt`（§8.3 第 13 项留档件）。

    ⚠️ **内容只取真实判定**（`gate.*` 条目），**不编造阈值实测值**——
    报告缺失比谎称通过更安全。
    """
    gate_lines = [(lv, code, msg) for lv, code, msg in judgements
                  if code.startswith("gate.")]
    head = [
        "镜头语言质量门报告（SPEC-008 §4.2 / §8.3 第 13 项）",
        f"内容编号：{pack_id}",
        f"判定工具：delivery/validate_pack.py（11 阈值，逐单元 + 整片）",
    ]
    if not gate_lines:
        head.append("结论：**未执行**（本包无可判定的镜头 ⇒ 质量门未运行，不代表通过）")
        return "\n".join(head) + "\n"
    bad = [x for x in gate_lines if x[0] == block_level]
    head.append("结论：" + ("**未通过**" if bad else "全部通过"))
    head.append("")
    for level, code, msg in gate_lines:
        head.append(f"  [{level}] {msg}")
    return "\n".join(head) + "\n"


def _declaration_input(svc: Any, session_id: str, pack: dict[str, Any]) -> Any:
    """取「改编来源声明」的原始输入（`SW-015` ②：必填）。

    按优先级依次查三处，**任一路写入都能生效**（未来端点加入参时不必再改服务层）：

    1. 会话记录属性 `adaptation_declaration`（客户端在会话上提交的声明）；
    2. `shot_prompt` 产物里的 `adaptation_declaration`（编排层透传）；
    3. 交付包 `meta.adaptation_declaration`。

    ⚠️ 三处都没有 ⇒ 返回 `None` ⇒ 声明件里**明写「未提交」**。
    **绝不代填「原创」**：权属陈述只能由提交方作出。
    """
    try:
        rec = svc._require(session_id)  # noqa: SLF001
    except Exception:  # pragma: no cover - 会话取不到时按缺失处理，不臆造
        rec = None
    if rec is not None:
        raw = getattr(rec, "adaptation_declaration", None)
        if raw:
            return raw
        art = getattr(rec, "artifacts", None)
        if isinstance(art, dict):
            sp = art.get("shot_prompt")
            if isinstance(sp, dict) and sp.get("adaptation_declaration"):
                return sp.get("adaptation_declaration")
    meta = pack.get("meta")
    if isinstance(meta, dict) and meta.get("adaptation_declaration"):
        return meta.get("adaptation_declaration")
    return None


def _artifact_entry(hit: list[str], expect: list[str], note: str = "") -> dict[str, Any]:
    """装配 `CFG-005` 的 `artifact` 条目（`files` 须非空，故 present=False 时登记预期路径）。"""
    entry: dict[str, Any] = {"present": bool(hit), "files": hit or expect}
    if not hit:
        entry["note"] = note or "文件未生成（如实登记预期路径，present=false）"
    return entry


def build_manifest(
    pack: dict[str, Any],
    files: list[str],
    service_truth: dict[str, Any] | None = None,
    *,
    self_check: list[dict[str, Any]] | None = None,
    human_review: list[dict[str, Any]] | None = None,
    quality_gate: dict[str, Any] | None = None,
    exports: list[dict[str, Any]] | None = None,
    retention_months: int = 6,
    spec_version: str = "",
) -> dict[str, Any]:
    """构造交付清单（**对齐 `CFG-005` v1.1.0**，`ISSUE-057` 候选①）。

    ⚠️ **与旧实现的差别（本函数是重写，非增量）**：
    | 维度 | 旧（`manifest_version` 1.0.0） | 新（`1.1.0`） |
    | --- | --- | --- |
    | 形态 | 自拟字段（`files`／`counts`／`compliance`／`is_preview`） | `CFG-005` 契约字段（`additionalProperties:false`） |
    | 四件套 | 无 | `artifacts` 五项（四件套 + 质量门报告） |
    | 自检 | 无 | `self_check` **18 项实际判定** |
    | 人工核对 | 无 | `human_review`（无记录即空，**不编造**） |

    ⚠️ **清单只登记文件与真值**，**不含下游平台地址与密钥**（`SYS-018`）。
    ⚠️ `artifacts` **一律由实际落盘文件推导**（不按「应该有哪些」写死）——
    文件没生成就 `present=false`，让门禁如实拦。
    """
    meta = pack.get("meta") or {}
    comp = meta.get("compliance") or {}
    gen = meta.get("generator") or {}
    statement_id = comp.get("statement_id", "")

    pack_files = [f for f in files if f == "pack.json"]
    aigc_files = [f for f in files if f == "aigc_meta.json"]
    overlay_files = [f for f in files
                     if f.startswith("assets/") and f.lower().endswith((".png", ".json"))]
    stmt_files = [f for f in files if "compliance_statement" in f]
    qa_files = [f for f in files if f.startswith("qa/")]

    provider = ""
    if gen.get("provider") or gen.get("provider_code"):
        provider = f"{gen.get('provider', '')}/{gen.get('provider_code', '')}".strip("/")

    manifest: dict[str, Any] = {
        "manifest_version": "1.1.0",
        "pack_id": str(meta.get("pack_id", "")),
        "statement_id": str(statement_id),
        "created_at": str(meta.get("created_at", "")),
        "artifacts": {
            "shot_prompt_pack": _artifact_entry(pack_files, ["pack.json"]),
            "aigc_meta": _artifact_entry(
                aigc_files, ["aigc_meta.json"],
                "AIGC 元数据块未单独落盘（§8.3 第 6 项要求「仅一份、可解析」）",
            ),
            "overlay_assets": _artifact_entry(
                overlay_files, ["assets/AST-002_overlay_spec.json"],
                "标识素材包未生成（§8.3 第 8 项：4 个 PNG + 规格文件）",
            ),
            "compliance_statement": _artifact_entry(
                stmt_files, ["AST-004_compliance_statement.md"],
                "合规声明未生成（§8.3 第 9 项）",
            ),
            "quality_gate_report": _artifact_entry(
                qa_files, ["qa/audit_report.txt"],
                "镜头语言质量门报告未生成（§8.3 第 13 项：缺即阻断）",
            ),
        },
        "adapters": [],
        "units": [],
        # ⚠️ 导出物记录（`SW-022`／`SPEC-008 §9.2` 差异化标识注入的**机读证据**）：
        #    由 `export_service.build_exports` **回读落盘文件**取证后给出，
        #    非空才能让清单侧判据 `export.mark` 真正被执行（此前该判据恒空跑）。
        "exports": list(exports or []),
        "human_review": list(human_review or []),
        "self_check": list(self_check or []),
        "retention": {
            "months": int(retention_months),
            "note": "交付合规声明／自检记录／质量门报告／人工核对记录／清单与校验和 "
                    "均留存 ≥6 个月（SPEC-008 §8.4）",
        },
    }
    if spec_version:
        manifest["spec_version"] = spec_version
    if provider:
        manifest["provider"] = provider
    if quality_gate:
        manifest["quality_gate"] = quality_gate

    # 生成单元摘要（§3.5 / §4.3；**只登记真实字段**，不补造）
    for u in pack.get("units") or []:
        if not isinstance(u, dict):
            continue
        row: dict[str, Any] = {}
        if u.get("unit_id"):
            row["unit_id"] = str(u["unit_id"])
        shot_ids = u.get("shot_ids") or []
        if shot_ids:
            row["shot_count"] = len(shot_ids)
        if isinstance(u.get("duration_ms"), int):
            row["duration_ms"] = u["duration_ms"]
        shots_by_id = {s.get("shot_id"): s for s in (pack.get("shots") or [])
                       if isinstance(s, dict)}
        types = [((shots_by_id.get(sid) or {}).get("camera") or {}).get("move")
                 for sid in shot_ids]
        types = [t for t in types if t]
        if types:
            row["camera_types"] = types
            row["camera_types_unique"] = len(set(types)) == len(types)
        if row:
            manifest["units"].append(row)

    # 服务层真值覆盖清单（举证用；`CFG-005` 无此字段 ⇒ 只在有内容时以 provider 附带信息出现）
    # ⚠️ 契约 `additionalProperties:false` ⇒ **不得**塞进清单；
    #    真值来源已完整记录在原 `manifest` 之外的 `gate_report.json` 与 `pack.json` 中。
    _ = service_truth  # 保留形参以兼容调用方；不写入清单（契约不允许）
    return manifest


#: 交付前自检报告文件名（**随包落盘、不进 `manifest.files`** —— `ISSUE-055` 裁决③）
GATE_REPORT_NAME = "gate_report.json"

#: ⚠️ 清单侧的校验说明（`ISSUE-057` 候选① 落地后：**清单已纳入门禁**）
GATE_MANIFEST_NOTE = (
    "清单侧判据已纳入：`manifest.json` 按 `CFG-005` v1.1.0 契约校验"
    "（四件套＋质量门报告、自检 18 项、人工核对记录、密钥/外部依赖）。"
)


def pack_judgements(pack_path: Path) -> tuple[list[tuple[str, str, str]], str]:
    """取**包侧**门禁条目（`(level, code, message)` 列表 ＋ BLOCK 档位名）。

    ⚠️ 为什么单独暴露：清单的 `self_check` **18 项要按实际判定填充**，
    而判定来自包侧门禁 ⇒ 必须在清单生成**之前**拿到结论。此函数与
    `evaluate_gate` 用**同一** `validate_pack`，不另立口径。
    """
    module = load_pack_validator()
    if module is None:
        return [], "BLOCK"
    rep = module.validate_pack(pack_path)
    return list(rep.items), module.BLOCK


def quality_gate_block(
    judgements: list[tuple[str, str, str]], block_level: str
) -> dict[str, Any] | None:
    """由 `gate.*` 条目装配清单的 `quality_gate` 结论（§4.2／§4.8）。

    ⚠️ **无 `gate.*` 条目 ⇒ 返回 `None`**（质量门没跑，例如无镜头）——
    **不写 `passed=false` 也不写 `true`**：前者是谎称不合格，后者是谎称通过。
    """
    gate_items = [x for x in judgements if x[1].startswith("gate.")]
    if not gate_items:
        return None
    return {
        "tool": "delivery/validate_pack.py",
        "command": "python delivery/validate_pack.py <pack.json>",
        "scope": "pack（11 阈值，逐单元 + 整片）",
        "passed": not any(lv == block_level for lv, _, _ in gate_items),
        "report_file": "qa/audit_report.txt",
    }


def evaluate_gate(
    pack_path: Path,
    manifest_path: Path | None = None,
    *,
    pack_items: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """跑交付门禁（`delivery/validate_pack.py`）并返回**结构化结论**。

    ⚠️ 只读产物、无副作用；判据**一字不改**（`ISSUE-055`：接线不改进判据）。
    ⚠️ `ISSUE-057` 候选① 起：传入 `manifest_path` 即**同时校验清单侧**
    （`validate_manifest`，与 CLI `main()` 同一函数）⇒ `manifest_checked=True`。
    """
    module = load_pack_validator()
    if module is None:
        return {
            "checked": False,
            "blocked": None,
            "reason": "validator_unavailable",
            "blocks": [],
            "warns": [],
            "scope": "pack",
            "manifest_checked": False,
            "manifest_note": GATE_MANIFEST_NOTE,
        }
    if pack_items is None:
        items: list[tuple[str, str, str]] = list(module.validate_pack(pack_path).items)
    else:
        items = list(pack_items)

    scope = "pack"
    manifest_checked = False
    if manifest_path is not None and manifest_path.is_file():
        pack_rep = module.Report(str(pack_path.name))
        pack_rep.items = list(items)
        mrep = module.validate_manifest(manifest_path, pack_rep)
        items = items + list(mrep.items)
        scope = "pack+manifest"
        manifest_checked = True

    blocks = [{"code": code, "message": msg}
              for lv, code, msg in items if lv == module.BLOCK]
    warns = [{"code": code, "message": msg}
             for lv, code, msg in items if lv == module.WARN]
    return {
        "checked": True,
        "blocked": bool(blocks),
        "blocks": blocks,
        "warns": warns,
        "block_count": len(blocks),
        "warn_count": len(warns),
        "scope": scope,
        "manifest_checked": manifest_checked,
        "manifest_note": GATE_MANIFEST_NOTE,
    }


def pack_delivery(
    *,
    svc: Any,
    session_id: str,
    out_dir: str | os.PathLike[str],
    settings: Any,
) -> DeliveryResult:
    """打包一次交付（`SW-I04` 端点的服务层实现）。

    纪律：

    - **不臆造合规结论**——`compliance.*` 全部来自 `build_pack_meta`
      （双闸实测留痕取不到时写占位，如实）；
    - **`meta` 由服务层装配**——编排层的 `apply_service_truth` 遵守「只覆盖、不新增」，
      产物里 `meta` 为空时**不补**（那会掩盖缺键）⇒ **交付端点自己装配**服务层域
      （`pack_id`／`compliance`／`generator`／`generation_trace`），
      **模型可影响字段（`title`／`shots`／`units`／`characters`／`props`／
      `style_bible`／`forbidden_items`）一字不改**；
    - **占位如实保留**——`provider_code`／`pack_id`／`statement_id` 是占位时
      **照原样写出**，`is_preview=True`；
    - **不托管下游密钥与成片**——只落本地文件。
    """
    pack = _load_pack_from_session(svc, session_id)

    # ---- ① 服务层装配 `meta`（模型产物里没有就装配；有了就以服务层为准覆盖）----
    art = svc._require(session_id).artifacts.get("shot_prompt") or {}  # noqa: SLF001
    safety = art.get("safety") if isinstance(art, dict) else None
    # ---- ①′ 版权校验（`SW-015`）----
    #    ⚠️ **在装配 `meta` 之前跑**：`compliance.copyright_check` 是 `meta` 的一部分，
    #    装配后再算就只能得到「没检」的结论 —— 那正是本字段此前长期硬编码
    #    `not_available`（且归因错写成 `T-008`）的成因。
    #    ⚠️ **作品库未建立时本步返回 `not_available`，不是异常**：`SW-015` 原文
    #    已登记「库未建立前本条不得判达标」⇒ 如实标注、不阻断交付、不伪造 `passed`。
    copyright_verdict = copyright_service.check(
        pack,
        corpus_root=getattr(settings, "copyright_corpus_root", "") or "",
        threshold=float(getattr(settings, "copyright_similarity_threshold", 0.5) or 0.5),
    )
    # ⚠️ **编号写入权单点化**（2026-11-11 结构性收敛，`ISSUE-074`）：
    #    `ISSUE-074` 的缺陷形态是「**两处都想写、后写者赢**」——打包入口按「沿用既有编号」
    #    写 A，随后 `apply_service_truth` 又把 `meta.pack_id` 覆盖回 `truth` 里的
    #    当次随机新编号 B ⇒ 目录／清单是 A、`pack.json` 与 `ProduceID` 是 B。
    #    此前的修法是「覆盖之后再纠偏」——**修补得了结果，防不住复发**（下一处覆盖者仍会赢）。
    #    ⇒ 结构解：编号在**装配 truth 之前**一次性确定，并作为 `truth["pack_id"]`
    #    的**唯一取值**；`build_pack_meta(pack_id=…)` 之后，`apply_service_truth`
    #    只是把这个值写进 `meta`，**不存在第二个写入者**。
    meta_in = pack.get("meta")
    meta = dict(meta_in) if isinstance(meta_in, dict) else {}
    # ⚠️ **已存在的 `pack_id` 沿用**（服务层 `build_pack_meta` 每次会生成新的随机短码
    #    ⇒ 若无条件覆盖，同一产物重复打包会**散落成多个编号目录**）。
    #    「补齐占位后重出同一编号的包」是交付侧的常规动作 ⇒ 编号必须可沿用。
    existing_pack_id = str(meta_in.get("pack_id") or "").strip() if isinstance(meta_in, dict) else ""
    # ⚠️ **沿用前须验形态**：模型自拟的 `pack_id` **不可信**（`SW-013` 要求
    #    内容编号不可被删除篡改隐匿）⇒ 只接受**服务层形态**
    #    `<企业码>-PK-<YYYYMMDD>-<8位短码>`（企业码可为占位）。
    inherit_id = existing_pack_id if existing_pack_id and _PACK_ID_RE.match(existing_pack_id) else None
    form_rejected = bool(existing_pack_id) and inherit_id is None

    truth = build_pack_meta(
        session_id=session_id,
        stage="shot_prompt",
        templates=[{"id": str(art.get("template_id", "")), "version": str(art.get("template_version", ""))}],
        model=_model_trace(art),
        settings=settings,
        artifacts={},
        title=None,
        # ⚠️ 单点写入：沿用值在此固化进 truth（None ⇒ 由 `build_pack_meta` 生成新编号）
        pack_id=inherit_id,
        safety=safety if isinstance(safety, dict) else None,
        copyright_verdict=copyright_verdict,
    )
    # ⚠️ **模型可影响字段保留**（`title` 等）；服务层域用真值覆盖
    for key in ("pack_id", "created_at", "task_type", "generator", "generation_trace", "compliance"):
        if key in truth:
            meta[key] = truth[key]
    if form_rejected:
        # 形态不合 ⇒ 用服务层生成的真值，并**如实留痕**（不静默）
        meta.setdefault("notes", "")
        meta["notes"] = (
            f"{meta.get('notes', '')}｜原产物 `meta.pack_id` 形态不合服务层规范，"
            "已改用服务层生成的编号。"
        ).strip("｜")
    # `unsupported_task_types`：服务层**有配置**才覆盖（无配置保留模型值 —— `pack_meta` 注记）
    if truth.get("unsupported_task_types"):
        meta["unsupported_task_types"] = truth["unsupported_task_types"]
    pack["meta"] = meta

    pack_id = str(meta.get("pack_id") or "").strip()
    if not pack_id:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "交付包缺 `meta.pack_id`，无法确定交付目录",
            details={"session_id": session_id},
        )

    # ---- ② 标识块（`aigc_meta.AIGC`）：**服务层装配**（`SW-013` 隐式标识的核心交付物）----
    # ⚠️ 编排层的 `apply_service_truth` 遵守「只覆盖、不新增」⇒ 产物里 `aigc_meta`
    #    是空骨架时它**什么都不覆盖**。但标识块是**服务层的确凿责任**
    #    （`SW-013`：元数据含提供者编码、内容编号，标识不可被删除篡改隐匿）
    #    ⇒ **此处必须装配**，且 `ProduceID` 与 `meta.pack_id` **同源**（`R30`）。
    provider_name = getattr(settings, "provider_name", "") or ""
    provider_code = getattr(settings, "provider_code", "") or ""
    producer = f"{provider_name or PLACEHOLDER_PROVIDER_NAME}/{provider_code or PLACEHOLDER_PROVIDER_CODE}"
    am = pack.get("aigc_meta")
    aigc = am.get("AIGC") if isinstance(am, dict) else None
    if not isinstance(aigc, dict):
        aigc = {}
    # ⚠️ `ReservedCode1/2` 属预留位，服务层无真值 ⇒ 写空串（`CFG-006` 要求存在）
    for key, value in (
        ("Label", "1"),
        ("ContentProducer", producer),
        ("ProduceID", pack_id),
        ("ContentPropagator", producer),
        ("PropagateID", pack_id),
        ("ReservedCode1", ""),
        ("ReservedCode2", ""),
    ):
        aigc[key] = value
    pack["aigc_meta"] = {"AIGC": aigc}
    # 覆盖清单留痕（哪些字段是服务层写的）
    truth_overrides = apply_service_truth(
        pack,
        truth,
        provider_name=provider_name,
        provider_code=provider_code,
    )

    # ---- ①‴ **编号同源不变量校验**（2026-11-11 结构性收敛，`ISSUE-074`）----
    # ⚠️ **缺陷沿革**：`apply_service_truth` 的 `META_SERVICE_KEYS` 含 `pack_id`，
    #    它曾把上文「沿用既有编号」的结果**覆盖回** `truth["pack_id"]`
    #    （服务层当次新生成的随机短码）⇒ 目录／清单是 A、`pack.json` 与
    #    `aigc_meta.AIGC.ProduceID` 变成 B，违反 `SW-013`／`R30`。
    #    上一版修法是「覆盖之后重新钉一遍」（能修结果、防不住复发）。
    #    **本版改为结构性收敛**：编号在装配 `truth` 之前一次性确定并作为
    #    `truth["pack_id"]`（见 ① 前的说明），`apply_service_truth` 只是执行者，
    #    **不存在第二个写入者**。此处因此**只校验、不修补**——一旦将来有人引入
    #    第二写入者，立即 fail-closed 出声，而不是把矛盾留在交付包里。
    _meta_now = pack.get("meta")
    _pid_now = str(_meta_now.get("pack_id") or "") if isinstance(_meta_now, dict) else ""
    if _pid_now != pack_id:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "交付包编号在装配过程中被改写（违反 SW-013／R30 同源要求）",
            details={"expected": pack_id, "actual": _pid_now, "where": "meta.pack_id"},
        )
    _am_chk = pack.get("aigc_meta")
    _aigc_chk = _am_chk.get("AIGC") if isinstance(_am_chk, dict) else None
    if isinstance(_aigc_chk, dict):
        for _k in ("ProduceID", "PropagateID"):
            _now = str(_aigc_chk.get(_k) or "")
            if _now != pack_id:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "隐式标识编号与 pack_id 不同源（违反 R30）",
                    details={"expected": pack_id, "actual": _now,
                             "where": f"aigc_meta.AIGC.{_k}"},
                )

    service_truth: dict[str, Any] = {}
    if truth_overrides:
        service_truth = {
            "checked": sorted(truth_overrides.keys()),
            "overrides": truth_overrides,
        }

    # ⚠️ `_unfilled` 是**服务层内部留痕字段**（`CFG-006` 的 `meta` 是
    #    `additionalProperties: false` ⇒ **不得**进交付包）⇒ 单独取出、只用于判预演态。
    unfilled = list(truth.get("_unfilled") or [])

    root = Path(out_dir).resolve()
    # ⚠️ 目录名取 pack_id 的**安全子串**（占位含 `{{}}` 需净化，避免非法路径字符）
    safe_id = "".join(ch for ch in pack_id if ch.isalnum() or ch in "-_")[:64] or "PACK-UNKNOWN"
    dst = root / safe_id
    dst.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    pack_path = dst / "pack.json"
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append("pack.json")

    # ② 标识素材包
    files.extend(_copy_assets(dst))

    # ③ 合规声明
    stmt = _render_compliance_statement(pack)
    stmt_path = dst / "AST-004_compliance_statement.md"
    stmt_path.write_text(stmt, encoding="utf-8")
    files.append("AST-004_compliance_statement.md")

    # ③‴ **版权与改编来源声明**（`SW-015` ②③）—— 必填、可留存、可导出
    #    ⚠️ 独立成件而非塞进 `compliance.note`：`CFG-006` 的 `copyright_check`
    #       是 `additionalProperties: false`（只有 `status`/`note`），而声明需要
    #       **逐条列明命中项 + 提交方声明 + 责任边界** ⇒ 结构化承载只能靠独立件。
    #       本件随包交付、由清单 `files` 登记 ⇒ 满足「可留存、可导出」。
    _decl = copyright_service.normalize_declaration(_declaration_input(svc, session_id, pack))
    _decl_name = copyright_service.declaration_filename(pack_id)
    (dst / _decl_name).write_text(
        copyright_service.build_declaration(
            pack_id=pack_id,
            session_id=session_id,
            verdict=copyright_verdict,
            declaration=_decl,
        ),
        encoding="utf-8",
        newline="\n",
    )
    files.append(_decl_name)

    # ③′ AIGC 元数据块**单独落盘**（§8.3 第 6 项「存在、字段齐全、仅一份、可解析」）
    #    ⚠️ 旧实现只在 `pack.json` 内嵌 ⇒ 四件套之②没有独立交付物，清单无法登记。
    aigc_path = dst / "aigc_meta.json"
    aigc_path.write_text(
        json.dumps(pack.get("aigc_meta") or {}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files.append("aigc_meta.json")

    # ③″ **导出物（含逐格式显式标识）** —— `SW-022` ＋ `SPEC-008 §9.2`
    #    ⚠️ **本块是 `T-006` 的实质缺口**：此前交付包**从不产出 `exports/`** ⇒
    #    清单的 `exports[]` 恒空 ⇒ 清单判据 `export.mark`／`export.meta`／
    #    `export.section` **从未被执行**，自检第 7 项只反映「元数据字段填了什么」。
    #    现按 JSON／MD／CSV／XLSX／TXT（适配两段式）逐格式注入，且**回读落盘文件取证**。
    export_res = build_exports(pack, pack_path)
    files.extend(export_res.files)
    if export_res.failed:
        # 失败不静默：写进包侧留痕（`gate_report.json` 里另有导出物判定）
        (dst / "exports" / "EXPORT_NOTES.txt").write_text(
            "\n".join(export_res.failed) + "\n", encoding="utf-8", newline="\n"
        )
        files.append("exports/EXPORT_NOTES.txt")

    # ⚠️ 预演态判定**必须在门禁之前**：它是「呈现 vs 拒付」的分档依据（`ISSUE-055` ①′）
    is_preview = bool(unfilled) or "{{" in pack_id

    # ---- ④ 包侧判定（清单 `self_check` 18 项的真实来源，`ISSUE-057` 候选①）----
    judgements, block_level = pack_judgements(pack_path)

    # ④′ 镜头语言质量门报告 `qa/audit_report.txt`（§8.3 第 13 项留档件）
    #    ⚠️ 内容只取真实 `gate.*` 条目；无镜头时写「未执行」，不写「通过」。
    (dst / "qa").mkdir(parents=True, exist_ok=True)
    (dst / "qa" / "audit_report.txt").write_text(
        render_audit_report(judgements, pack_id=pack_id, block_level=block_level),
        encoding="utf-8",
    )
    files.append("qa/audit_report.txt")

    # ④″ 人工核对记录（§8.3 第 18 项）——**只从人工录入的台账读**，服务层不代填
    human_review = _load_human_review(settings, pack_id)

    # ---- ⑤ 清单（`CFG-005` v1.1.0；自检 18 项按实际判定填充）----
    self_check = build_self_check(
        judgements,
        block_level=block_level,
        assets=[f for f in files if f.startswith("assets/")],
        statement_id=(pack.get("meta") or {}).get("compliance", {}).get("statement_id", ""),
        statement_file="AST-004_compliance_statement.md",
        adapters=[a for a in (pack.get("adapters") or []) if isinstance(a, dict)],
        human_review=human_review,
        has_shots=bool(pack.get("shots")),
        has_units=bool(pack.get("units")),
        exports=export_res.records,
    )
    manifest = build_manifest(
        pack,
        files + ["manifest.json"],
        service_truth,
        self_check=self_check,
        human_review=human_review,
        quality_gate=quality_gate_block(judgements, block_level),
        exports=export_res.records,
        retention_months=max(1, int(getattr(settings, "log_retention_days", 180)) // 30),
        spec_version=SPEC_VERSION,
    )
    mf_path = dst / "manifest.json"
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append("manifest.json")

    # ---- ⑥ 交付前自检（官方第 9 项「自检记录留档」＋`SW-026`「未通过→阻断」）----
    # ⚠️ **分档**：预演包 ⇒ 只呈现（`compliance.*` 占位必然 BLOCK，拒付会让端点长期不可用）；
    #    正式包 ⇒ `blocked` 即拒付（422），并**保留已落盘目录**（自检记录须留档 ≥6 个月，不能删）。
    # ⚠️ `ISSUE-057` 候选① 起：**清单侧一并校验**（`manifest_checked=True`）。
    gate = evaluate_gate(pack_path, mf_path, pack_items=judgements)
    gate["is_preview"] = is_preview
    gate["evaluated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    gate_path = dst / GATE_REPORT_NAME
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    gate["report_path"] = str(gate_path)

    if not is_preview and gate.get("blocked"):
        codes = [b["code"] for b in gate.get("blocks") or []]
        raise AppError(
            # ⚠️ 裁决要求 422：本工程 `VALIDATION_ERROR` 映射 **400**，
            #    而 `DELIVERY_PACK_INVALID` 才是既有 422 专用码 ⇒ 取后者（语义也更准）。
            ErrorCode.DELIVERY_PACK_INVALID,
            f"交付前自检未通过（BLOCK {len(codes)} 项）：{', '.join(codes[:5])}",
            details={
                "pack_id": pack_id,
                "pack_dir": str(dst),
                "gate_blocks": codes,
                "blocks": gate.get("blocks") or [],
                "gate_report": str(gate_path),
                "scope": gate.get("scope"),
                "manifest_checked": gate.get("manifest_checked"),
            },
        )

    return DeliveryResult(
        pack_id=pack_id,
        pack_dir=str(dst),
        files=sorted(set(files)),
        unfilled=unfilled,
        is_preview=is_preview,
        pack_bytes=pack_path.stat().st_size,
        gate=gate,
    )
