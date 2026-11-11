"""导出服务层 —— **SW-022**（内容导出，含导出文件显式标识）。

⚠️ **本模块补的是「最后一公里」**：`SW-I04` 交付包此前只落 `pack.json`／
`aigc_meta.json`／`assets/`／`AST-004`／`qa/`，**从不产出 `exports/`** ⇒
`CFG-005` 的 `exports[]` 恒为空 ⇒ `validate_manifest` 的 `export.mark` 判据
**从未被执行过**，自检第 7 项「显式标识存在于所有导出文件」只反映了
`meta.compliance.marking_check` 这个**字段填了什么**，而非「导出文件里真的有没有」。

本模块按 `SPEC-008 §9.2`（`SPEC-002` 同名章节）**逐格式差异化注入**：

| 格式 | 显式标识 | 隐式标识 |
| --- | --- | --- |
| JSON | 顶层 `explicit_mark`（文案 ＋ 位置说明） | 顶层 `AIGC` 键 |
| MD | 文首引用块 ＋ 文末标注 | 文末 `## 元数据` 小节 |
| CSV | 首行 `#AI生成内容…` ＋ 末行重复 | 末行 `#AIGC:` 前缀 JSON |
| XLSX | 首行合并单元格标识行（醒目填充） | 工作簿文档属性（见下「已知偏差」）|
| TXT（适配） | 标识区 `【AI生成内容】…` ＋ 固定分隔行（两段式） | 标识区内的 `ProduceID` 行 |

**铁律**（`SPEC-008 §9.2` 末段）：任一格式注入失败 ⇒ **该记录 `explicit_mark=false`**
（由清单判据 `export.mark` 阻断导出），**绝不出现「导出成功但无标识」**。
本模块**不吞异常后写 `true`** —— 判定一律回读落盘文件取证。

### 已知偏差（如实登记，不静默）

- ~~**XLSX 隐式标识**：`openpyxl` 只支持**核心**文档属性~~ → **已补齐**（2026-11-11，
  `DEV-20261111-014`，`ISSUE-073` 闭环）：`openpyxl` ≥3.1 原生支持自定义文档属性
  （`wb.custom_doc_props`），`AIGC_*` 逐键写入 `docProps/custom.xml`（规范 §9.2
  要求的载体），`keywords`／`description` 承载**保留**为冗余兼容（旧客户端只认
  核心属性；双载体内容同源，`_evidence` 双路取证）。
- **TXT 隐式标识**：不写「文件末尾元数据块」，而写**标识区**（分隔行之前）。
  依据是 `SPEC-008 §6.8` 的 E6 判据——**提示词区不得出现 AIGC 元数据键**
  （否则客户全选复制会把元数据粘进模型）。两处规范冲突时取 §6.8（更具体的适配格式约束）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CN_TZ = timezone(timedelta(hours=8))

#: 工程根（`03-工程代码/`）——`app/services/` 上溯两级。
APP_ROOT = Path(__file__).resolve().parents[2]

#: 标识规格文件（**文案的唯一事实源**：`AST-002` 的 `texts.full_final`）。
OVERLAY_SPEC_PATH = APP_ROOT / "delivery" / "assets" / "AST-002_overlay_spec.json"

#: `AST-002` 读不到时的**兜底文案**（与 `SYS-Q15` 定稿一致）。
_FALLBACK_MARK_TEXT = "本文件由AI生成，已经过合规验证"

#: 导出格式全集（`CFG-005.fileEntry.format` 枚举的子集；`pdf` 未实现 —— `SPEC-008 §12 T-06` 后置）
SUPPORTED_FORMATS: tuple[str, ...] = ("json", "md", "csv", "xlsx", "txt")

#: 文件名非法字符（`SPEC-008 §9.3`）。
_ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')


def explicit_mark_text() -> str:
    """取**集中配置**的显式标识文案（不硬编码在多个位置）。

    ⚠️ 事实源＝`delivery/assets/AST-002_overlay_spec.json` 的 `texts.full_final`
    —— 该文件同时驱动角标 PNG 的绘制（`gen_overlays.py`），故文案改一处即
    「角标与文本导出同步」；`test_export_service` 另有**互锁断言**对拍
    `CFG-001_model_adapters.yaml` 的 `explicit_mark_text`，防两处漂移。
    """
    try:
        spec = json.loads(OVERLAY_SPEC_PATH.read_text(encoding="utf-8"))
        text = str(((spec.get("texts") or {}).get("full_final") or "")).strip()
        if text:
            return text
    except (OSError, ValueError):
        pass
    return _FALLBACK_MARK_TEXT


def _safe(name: str) -> str:
    """净化文件名字段（`{{PROVIDER_CODE}}` 这类占位符含非法字符）。"""
    cleaned = _ILLEGAL.sub("_", str(name or "")).replace("{", "").replace("}", "")
    return cleaned.strip("_")[:80] or "PACK-UNKNOWN"


def _version(pack: dict[str, Any]) -> str:
    """版本号取自包 `schema_version`（无则 `1`）——`SPEC-008 §9.3` 命名要求的 `<v>`。"""
    raw = str(pack.get("schema_version") or "1").strip()
    return _safe(raw) or "1"


@dataclass
class ExportResult:
    """一次导出的结果（`records` 直接进 `manifest.exports[]`）。"""

    records: list[dict[str, Any]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"records": self.records, "files": self.files, "failed": self.failed}


# --------------------------------------------------------------------------- #
# 各格式渲染器（**返回值即"标识是否注入成功"的证据**，不靠调用方假设）
# --------------------------------------------------------------------------- #
def _aigc_block(pack: dict[str, Any]) -> dict[str, Any]:
    am = pack.get("aigc_meta")
    if isinstance(am, dict) and isinstance(am.get("AIGC"), dict):
        return dict(am["AIGC"])
    return {}


def _render_json(pack: dict[str, Any], mark: str) -> str:
    """JSON：顶层 `explicit_mark`（文案＋位置说明）＋ 顶层 `AIGC` 键。"""
    doc = dict(pack)
    doc["explicit_mark"] = {
        "text": mark,
        "position": "顶层 explicit_mark 字段（SPEC-008 §9.2：JSON 差异化注入位）",
        "injected_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
    }
    doc["AIGC"] = _aigc_block(pack) or doc.get("AIGC") or {}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _shots_rows(pack: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """分镜表（CSV／XLSX 共用）——**只取真实字段**，缺值为空串，不补造。"""
    header = ["场次", "镜号", "单元", "时长(s)", "画幅", "景别", "运镜", "画面描述", "台词"]
    shots = [s for s in (pack.get("shots") or []) if isinstance(s, dict)]
    shots.sort(key=lambda s: (s.get("scene_no") or 0, s.get("shot_no") or 0))
    rows: list[list[str]] = []
    for s in shots:
        cam = s.get("camera") if isinstance(s.get("camera"), dict) else {}
        ms = s.get("duration_ms")
        rows.append([
            str(s.get("scene_no") if s.get("scene_no") is not None else ""),
            str(s.get("shot_no") if s.get("shot_no") is not None else ""),
            str(s.get("unit_id") or ""),
            f"{ms / 1000:g}" if isinstance(ms, int) else "",
            str(cam.get("aspect_ratio") or s.get("aspect_ratio") or ""),
            str(cam.get("shot_size") or ""),
            str(cam.get("move") or ""),
            str(s.get("description") or s.get("prose") or s.get("visual") or "").replace("\n", " "),
            str(s.get("dialogue") or "").replace("\n", " "),
        ])
    return header, rows


def _render_csv(pack: dict[str, Any], mark: str) -> str:
    """CSV：首行 `#AI生成内容…` 注释行 ＋ 末行 `#AIGC:` 前缀 JSON。"""
    header, rows = _shots_rows(pack)
    buf = io.StringIO()
    buf.write(f"#AI生成内容 {mark}\n")
    buf.write("#标识方法：首行与末行注释行（SPEC-008 §9.2：CSV 差异化注入位）\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    aigc = _aigc_block(pack)
    buf.write("#AIGC:" + json.dumps(aigc, ensure_ascii=False, sort_keys=True) + "\n")
    buf.write(f"#AI生成内容 {mark}\n")
    return buf.getvalue()


def _render_md(pack: dict[str, Any], mark: str) -> str:
    """MD：文首引用块 ＋ 文末标注；隐式标识落文末 `## 元数据` 小节。"""
    meta = pack.get("meta") or {}
    header, rows = _shots_rows(pack)
    lines = [
        f"> 【AI生成内容】{mark}",
        "> ",
        "> 标识位置：文首引用块 ＋ 文末标注（SPEC-008 §9.2：MD 差异化注入位）。",
        "",
        f"# 分镜提示词集 · {meta.get('title') or '(未命名)'}",
        "",
        f"- 交付包编号：`{meta.get('pack_id') or ''}`",
        f"- 生成时间：`{meta.get('created_at') or ''}`",
        f"- 生成单元 / 镜头数：{len(pack.get('units') or [])} / {len(pack.get('shots') or [])}",
        "",
        "## 分镜表",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(c.replace("|", "／") for c in row) + " |")
    lines += [
        "",
        "## 元数据",
        "",
        "```json",
        json.dumps(_aigc_block(pack), ensure_ascii=False, indent=2),
        "```",
        "",
        "---",
        "",
        f"> 【AI生成内容】{mark}",
        "",
    ]
    return "\n".join(lines)


def _render_xlsx(pack: dict[str, Any], mark: str, target: Path) -> None:
    """XLSX：首行合并单元格标识行（醒目填充）＋ 工作簿文档属性。

    隐式标识**双载体**（`ISSUE-073` 闭环，2026-11-11）：
    ① **规范载体** —— `docProps/custom.xml` 自定义属性（§9.2 要求），`AIGC_*`
       逐键写入（`openpyxl` ≥3.1 `wb.custom_doc_props` 原生支持，写盘自动完成
       `[Content_Types].xml` 与 `_rels/.rels` 注册）；
    ② **冗余兼容** —— 核心属性 `keywords`／`description` 照旧承载（旧客户端只认
       核心属性；内容与 ① 同源）。
    """
    from openpyxl import Workbook
    from openpyxl.packaging.custom import StringProperty
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    header, rows = _shots_rows(pack)
    aigc = _aigc_block(pack)
    wb = Workbook()
    ws = wb.active
    ws.title = "分镜表"

    ws.append([f"【AI生成内容】{mark}"])
    last_col = get_column_letter(len(header))
    ws.merge_cells(f"A1:{last_col}1")
    cell = ws["A1"]
    cell.font = Font(bold=True, color="FFFFFF", size=12)
    cell.fill = PatternFill("solid", start_color="C00000", end_color="C00000")
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    ws.append(header)
    for row in rows:
        ws.append(row)
    for idx, width in enumerate([6, 6, 10, 8, 8, 10, 10, 46, 24], start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A3"

    props = wb.properties
    props.title = f"分镜表 · {mark}"
    props.subject = "AI 生成内容（含显式标识）"
    props.creator = str((pack.get("meta") or {}).get("generator", {}).get("system", "")) or "AIGC"
    props.keywords = ";".join(f"{k}={v}" for k, v in sorted(aigc.items()) if v != "")
    props.description = (
        f"【AI生成内容】{mark}｜标识方法：首行标识行 ＋ 工作簿文档属性（keywords 承载 AIGC_*）"
    )
    props.category = "AIGC"
    # 规范载体：AIGC_* 逐键落 docProps/custom.xml（字符串型，键值均为审计面明文）
    for k, v in sorted(aigc.items()):
        if v != "":
            wb.custom_doc_props.props.append(StringProperty(name=f"AIGC_{k}", value=str(v)))
    wb.save(target)


# --------------------------------------------------------------------------- #
# TXT：复用 §6.8 两段式适配生成器（`delivery/tools/export_models.py`）
# --------------------------------------------------------------------------- #
def _render_txt(pack_path: Path, out_root: Path) -> tuple[list[str], list[str]]:
    """调用 `SW-025` 适配生成器产出 `exports/<code>/*.txt`（两段式）。

    返回 `(落盘相对路径列表, 失败说明列表)`。导入失败／无适配配置时**如实返回失败**，
    由调用方把该格式记入 `failed`，**不伪造标识成功**。
    """
    tools_dir = APP_ROOT / "delivery" / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        import export_models as em  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - 依赖缺失即如实降级
        return [], [f"txt 适配生成器不可用：{exc}"]

    cfg_path = APP_ROOT / "delivery" / "config" / "CFG-001_model_adapters.yaml"
    vocab_path = APP_ROOT / "delivery" / "config" / "CFG-002_shot_vocab.yaml"
    cfg = em.load_yaml(cfg_path)
    defaults = cfg.get("defaults") or {}
    vocab = em.Vocab(em.load_yaml(vocab_path), defaults.get("literal_reject_patterns"))

    summary = em.run(pack_path, out_root, None, cfg, defaults, vocab)
    files: list[str] = []
    failed: list[str] = []
    for m in summary.get("models") or []:
        rel = str(m.get("file") or "")
        if not rel:
            failed.append(f"txt 适配 {m.get('code')} 未产出文件")
            continue
        files.append(rel)
        if m.get("verify_status") != "verified":
            failed.append(
                f"txt 适配 {m.get('code')} 的 verify_status={m.get('verify_status')}"
                "（标识已注入，但适配参数待核对 —— 不影响标识判定，见 §13 NT-03）"
            )
    return files, failed


# --------------------------------------------------------------------------- #
# 取证（回读落盘文件判定标识是否真的存在）
# --------------------------------------------------------------------------- #
def _evidence(path: Path, fmt: str, mark: str) -> tuple[bool, bool, bool, str]:
    """回读文件取证：`(explicit, implicit, two_section, note)`。

    ⚠️ **判定一律以文件内容为准**，不采信「我刚写过」的假设 ——
    这正是 `ISSUE-070`（自述≠证据）家族的纪律。
    """
    try:
        if fmt == "xlsx":
            from openpyxl import load_workbook

            wb = load_workbook(path)
            ws = wb.active
            first = str(ws["A1"].value or "")
            kw = str(wb.properties.keywords or "")
            # 双载体取证（ISSUE-073）：规范载体 custom.xml ＋ 冗余载体 keywords
            custom_names = {str(p.name) for p in wb.custom_doc_props.props}
            explicit = mark in first
            implicit = (
                "ProduceID=" in kw
                or "ContentProducer=" in kw
                or "AIGC_ProduceID" in custom_names
            )
            n_custom = len(custom_names)
            return (
                explicit,
                implicit,
                False,
                f"首行标识行{'已注入' if explicit else '缺失'}；"
                f"自定义属性 docProps/custom.xml AIGC_* × {n_custom}；"
                f"核心属性 keywords {len(kw)} 字符",
            )

        raw = path.read_bytes()
        text = raw.decode("utf-8")
        if fmt == "json":
            doc = json.loads(text)
            explicit = isinstance(doc.get("explicit_mark"), dict) and mark in str(
                doc["explicit_mark"].get("text", "")
            )
            implicit = bool(doc.get("AIGC"))
            return explicit, implicit, False, "顶层 explicit_mark ＋ AIGC 键"
        if fmt == "csv":
            lines = text.split("\n")
            explicit = lines[0].startswith("#AI生成内容") and mark in lines[0]
            implicit = any(ln.startswith("#AIGC:") for ln in lines)
            return explicit, implicit, False, f"首行注释行{'在' if explicit else '缺'}；末行 AIGC {len(lines)} 行"
        if fmt == "md":
            explicit = text.startswith(f"> 【AI生成内容】{mark}") and text.rstrip().endswith(mark)
            implicit = "\n## 元数据\n" in text
            return explicit, implicit, False, "文首引用块＋文末标注；元数据小节"
        if fmt == "txt":
            lines = text.split("\n")
            mark_idx = next((i for i, ln in enumerate(lines) if ln.startswith("【AI生成内容】")), None)
            div_idx = next((i for i, ln in enumerate(lines) if "以下为提示词区" in ln), None)
            explicit = mark_idx is not None and mark in lines[mark_idx]
            two_section = div_idx is not None and mark_idx is not None and mark_idx < div_idx
            implicit = any("ProduceID" in ln for ln in (lines[:div_idx] if div_idx else lines))
            return explicit, implicit, two_section, f"标识区行 {mark_idx}／分隔行 {div_idx}"
    except Exception as exc:  # noqa: BLE001 - 取证失败即判「无标识」
        return False, False, False, f"取证失败：{type(exc).__name__}: {exc}"
    return False, False, False, f"未知格式 {fmt}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _record(root: Path, path: Path, fmt: str, mark: str, note: str = "") -> dict[str, Any]:
    explicit, implicit, two_section, ev = _evidence(path, fmt, mark)
    row: dict[str, Any] = {
        "file": path.relative_to(root).as_posix(),
        "format": fmt,
        "explicit_mark": explicit,
        "implicit_mark": implicit,
        "sha256": _sha256(path),
    }
    if fmt == "txt":
        row["two_section"] = two_section
    text = note or ev
    if text:
        row["note"] = text
    return row


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def build_exports(
    pack: dict[str, Any],
    pack_path: Path,
    *,
    formats: tuple[str, ...] = SUPPORTED_FORMATS,
    out_dir: Path | None = None,
) -> ExportResult:
    """按格式差异化注入标识并落盘，返回**可进 `manifest.exports[]`** 的记录。

    `pack_path`：已落盘的 `pack.json`（TXT 适配生成器按路径读包）。
    `out_dir`：导出根目录，默认 `<pack.json 所在目录>/exports`。
    """
    root = Path(pack_path).resolve().parent
    out = Path(out_dir).resolve() if out_dir else root / "exports"
    out.mkdir(parents=True, exist_ok=True)

    mark = explicit_mark_text()
    pid = _safe(str((pack.get("meta") or {}).get("pack_id") or "PACK-UNKNOWN"))
    ver = _version(pack)
    res = ExportResult()

    for fmt in formats:
        try:
            if fmt == "json":
                target = out / f"{pid}_分镜提示词集_v{ver}.json"
                target.write_text(_render_json(pack, mark), encoding="utf-8", newline="\n")
                res.records.append(_record(root, target, "json", mark))
            elif fmt == "md":
                target = out / f"{pid}_分镜提示词集_v{ver}.md"
                target.write_text(_render_md(pack, mark), encoding="utf-8", newline="\n")
                res.records.append(_record(root, target, "md", mark))
            elif fmt == "csv":
                target = out / f"{pid}_分镜表_v{ver}.csv"
                target.write_text(_render_csv(pack, mark), encoding="utf-8", newline="\n")
                res.records.append(_record(root, target, "csv", mark))
            elif fmt == "xlsx":
                target = out / f"{pid}_分镜表_v{ver}.xlsx"
                _render_xlsx(pack, mark, target)
                res.records.append(_record(
                    root, target, "xlsx", mark,
                    "隐式标识：自定义属性 docProps/custom.xml（AIGC_*，规范 §9.2 载体）"
                    "＋ 核心属性 keywords（冗余兼容）",
                ))
            elif fmt == "txt":
                files, failed = _render_txt(Path(pack_path), out)
                res.failed.extend(failed)
                txt_root = Path(pack_path).resolve().parent
                for rel in files:
                    target = (txt_root / rel).resolve()
                    if not target.exists():
                        res.failed.append(f"txt 记录指向不存在的文件：{rel}")
                        continue
                    # 隐式标识：在标识区（分隔行之前）插入 `ProduceID` 行（§6.8 E6 禁元数据入提示词区）
                    _inject_txt_implicit(target, pack)
                    res.records.append(_record(root, target, "txt", mark))
            elif fmt == "pdf":
                res.failed.append("pdf 导出未实现（SPEC-008 §12 T-06 待决，P2 后置）")
            else:
                res.failed.append(f"不支持的格式 {fmt!r}")
        except Exception as exc:  # noqa: BLE001 - 单格式失败不拖垮整包，但**如实记失败**
            res.failed.append(f"{fmt} 导出失败：{type(exc).__name__}: {exc}")

    res.files = [r["file"] for r in res.records]
    return res


def _inject_txt_implicit(path: Path, pack: dict[str, Any]) -> None:
    """在 TXT 的**标识区**补一行 `ProduceID`（隐式标识）；已存在则不动。"""
    aigc = _aigc_block(pack)
    produce = str(aigc.get("ProduceID") or "").strip()
    producer = str(aigc.get("ContentProducer") or "").strip()
    if not produce and not producer:
        return
    text = path.read_text(encoding="utf-8")
    if "ProduceID" in text.split("════════════ 以下为提示词区")[0]:
        return
    lines = text.split("\n")
    div = next((i for i, ln in enumerate(lines) if "以下为提示词区" in ln), None)
    if div is None:
        return
    mark = next((i for i, ln in enumerate(lines) if ln.startswith("【AI生成内容】")), div)
    line = (
        f"[隐式标识] ContentProducer={producer}；ProduceID={produce}；Label=1"
        "（本行属标识区，请勿复制进模型）"
    )
    lines.insert(mark, line)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def merge_manifest_exports(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """把导出记录并入清单（`CFG-005.exports[]`，`additionalProperties:false` ⇒ 只放契约字段）。"""
    allowed = {"file", "format", "explicit_mark", "implicit_mark", "two_section", "note", "sha256"}
    manifest["exports"] = [
        {k: v for k, v in r.items() if k in allowed} for r in records if isinstance(r, dict)
    ]
    return manifest


def update_manifest_file(manifest_path: Path, records: list[dict[str, Any]]) -> None:
    """重出导出物后刷新**已有** `manifest.json` 的 `exports[]`（不动其它字段）。"""
    path = Path(manifest_path)
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    merge_manifest_exports(data, records)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
