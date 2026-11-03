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
| ② 标识素材包 | `<out>/<pack_id>/assets/`（显式角标 PNG ＋ `AST-004` 合规声明） | ✅ 素材**已备**（`delivery/assets/`） |
| ③ 合规声明 | `<out>/<pack_id>/AST-004_compliance_statement.md` | ✅ 由 `apply_service_truth` 的真值渲染 |
| ④ 清单（manifest） | `<out>/<pack_id>/manifest.json` | ✅ 对齐 `CFG-005` 形态 |
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.services.pack_meta import (
    PLACEHOLDER_PROVIDER_CODE,
    PLACEHOLDER_PROVIDER_NAME,
    apply_service_truth,
    build_pack_meta,
)

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "pack_dir": self.pack_dir,
            "files": list(self.files),
            "unfilled": list(self.unfilled),
            "is_preview": self.is_preview,
            "pack_bytes": self.pack_bytes,
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


def build_manifest(pack: dict[str, Any], files: list[str],
                   service_truth: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造交付清单（`CFG-005` 形态）。

    ⚠️ 清单**只登记文件与真值**，**不含下游平台地址与密钥**（`SYS-018`）。
    """
    meta = pack.get("meta") or {}
    comp = meta.get("compliance") or {}
    return {
        "manifest_version": "1.0.0",
        "pack_id": meta.get("pack_id", ""),
        "created_at": meta.get("created_at", ""),
        "title": meta.get("title", ""),
        "schema_version": pack.get("schema_version", ""),
        "files": list(files),
        "counts": {
            "shots": len(pack.get("shots") or []),
            "units": len(pack.get("units") or []),
            "characters": len(pack.get("characters") or []),
            "props": len(pack.get("props") or []),
            "forbidden_items": len(pack.get("forbidden_items") or []),
        },
        "compliance": {
            "safety_check": comp.get("safety_check", {}),
            "copyright_check": comp.get("copyright_check", {}),
            "marking_check": comp.get("marking_check", {}),
            "statement_id": comp.get("statement_id", ""),
        },
        "is_preview": True,
        "preview_note": PREVIEW_NOTE,
        # ⚠️ 服务层真值覆盖清单（哪些字段由服务层写入）——举证用
        "service_truth": service_truth or {},
        "provider": (meta.get("generator") or {}),
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
    truth = build_pack_meta(
        session_id=session_id,
        stage="shot_prompt",
        templates=[{"id": str(art.get("template_id", "")), "version": str(art.get("template_version", ""))}],
        model=_model_trace(art),
        settings=settings,
        artifacts={},
        title=None,
        safety=safety if isinstance(safety, dict) else None,
    )
    meta_in = pack.get("meta")
    meta = dict(meta_in) if isinstance(meta_in, dict) else {}
    # ⚠️ **已存在的 `pack_id` 沿用**（服务层 `build_pack_meta` 每次会生成新的随机短码
    #    ⇒ 若无条件覆盖，同一产物重复打包会**散落成多个编号目录**）。
    #    「补齐占位后重出同一编号的包」是交付侧的常规动作 ⇒ 编号必须可沿用。
    existing_pack_id = str(meta_in.get("pack_id") or "").strip() if isinstance(meta_in, dict) else ""
    # ⚠️ **模型可影响字段保留**（`title` 等）；服务层域用真值覆盖
    for key in ("pack_id", "created_at", "task_type", "generator", "generation_trace", "compliance"):
        if key in truth:
            meta[key] = truth[key]
    if existing_pack_id:
        # ⚠️ **沿用前须验形态**：模型自拟的 `pack_id` **不可信**（`SW-013` 要求
        #    内容编号不可被删除篡改隐匿）⇒ 只接受**服务层形态**
        #    `<企业码>-PK-<YYYYMMDD>-<8位短码>`（企业码可为占位）。
        if _PACK_ID_RE.match(existing_pack_id):
            meta["pack_id"] = existing_pack_id
        else:
            # 形态不合 ⇒ 用服务层生成的真值，并**如实留痕**（不静默）
            meta["pack_id"] = truth["pack_id"]
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

    # ④ 清单
    manifest = build_manifest(pack, files + ["manifest.json"], service_truth)
    mf_path = dst / "manifest.json"
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append("manifest.json")

    is_preview = bool(unfilled) or "{{" in pack_id

    return DeliveryResult(
        pack_id=pack_id,
        pack_dir=str(dst),
        files=sorted(set(files)),
        unfilled=unfilled,
        is_preview=is_preview,
        pack_bytes=pack_path.stat().st_size,
    )
