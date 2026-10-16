# -*- coding: utf-8 -*-
"""md2xlsx —— 把「表格密集型」Markdown 文档转换为同名 Excel 工作簿。

设计目标
--------
Markdown 文档体量变大后（数千行、数十至上百个表格），编辑器渲染与检索都会明显卡顿，
且表格列宽参差、跨表比对困难。本工具把 md 中的**表格**抽取为结构化工作簿，便于筛选、
排序、比对与长期维护；md 原文保持不动，两者互补。

工作簿结构
----------
* 首个工作表 `00-索引`：源文档路径、生成时间、表格数与工作表数，以及逐表清单
  （序号 / 表名 / 章节路径 / 数据行数 / 列数 / 所在工作表）。
* 其余工作表：按原文档的**二级标题**（无二级标题时退化到一级标题）分表，章节内的
  多个表格自上而下顺序堆叠，每个表格前置一行表名分隔（浅橙底加粗），表格之间空一行。

用法
----
    python md2xlsx.py                # 转换内置目标清单
    python md2xlsx.py <文件或目录> …  # 转换指定文件/目录（递归）

判定规则
--------
* 表格 = 连续的以 `|` 开头的行（代码块 ``` / ~~~ 内的 `|` 行不计）。
* 第二行若为分隔行（`---` / `:---:` / `-`），则第一行视为表头；否则整体视为无表头数据。
* 单表数据行数 < 3 的文件跳过（表格过少，转 Excel 无收益）。

依赖：openpyxl
"""
from __future__ import annotations

import datetime as _dt
import io
import os
import re
import sys
import time
from collections import OrderedDict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------- 目标范围配置

ROOT = r"E:\深度合成算法工程材料"

# 目标目录（需求类 / 清单类 / 规范类 / 台账类）
TARGET_DIRS = [
    "00-需求",
    "01-架构设计",
    "02-备案申报",
    "04-部署运维",
    "07-提示词工程",
    "09-合规资料库",
    "12-项目管理",
    "13-项目配置管理",
]

# 单独指定的文件（所在目录整体不纳入转换）
TARGET_FILES = [
    "03-工程代码/delivery/assets/AST-001_ASSETS.md",
]

# 永久排除路径片段（第三方词库源：无 LICENSE 且含真实 PII）
EXCLUDE_PARTS = ("funNLP",)

# 单文件表格数据行总数低于该值则跳过
MIN_DATA_ROWS = 3

# 转出目录（None 表示与源文件同目录同名）
OUT_DIR = None

# ---------------------------------------------------------------- 样式

_THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

NAME_FILL = PatternFill("solid", fgColor="FCE4D6")
NAME_FONT = Font(bold=True, size=11, color="833C00")

HDR_FILL = PatternFill("solid", fgColor="DDEBF7")
HDR_FONT = Font(bold=True, size=10, color="1F3864")

BODY_FONT = Font(size=10)
META_FONT = Font(size=10, color="595959")
TITLE_FONT = Font(bold=True, size=13, color="1F3864")

WRAP = Alignment(wrap_text=True, vertical="top")
WRAP_HDR = Alignment(wrap_text=True, vertical="center", horizontal="center")

MAX_COL_WIDTH = 45
MIN_COL_WIDTH = 9

# ---------------------------------------------------------------- Markdown 解析

_SEP_CELL = re.compile(r"^:?-+:?$")


def _clean_cell(txt: str) -> str:
    """清洗单元格文本：剥离 Markdown/HTML 标记，保留语义内容。"""
    s = txt.strip()
    s = s.replace("\\|", "\x00")                       # 保护转义竖线
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)      # 换行标签 → 换行
    s = re.sub(r"<[^>]+>", "", s)                      # 其余 HTML 标签剔除
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)         # 图片
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)     # 链接保留文字
    s = s.replace("**", "").replace("__", "").replace("`", "").replace("\x00", "|")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [_clean_cell(part) for part in re.split(r"(?<!\\)\|", s)]


def _is_sep_row(cells: list[str]) -> bool:
    if not cells:
        return False
    hit = False
    for c in cells:
        c = c.strip()
        if c == "":
            continue
        if _SEP_CELL.match(c):
            hit = True
        else:
            return False
    return hit


def _build_table(buf: list[str]) -> dict | None:
    rows = [_split_row(line) for line in buf]
    if len(rows) < 2:
        return None

    has_header = _is_sep_row(rows[1])
    header = rows[0] if has_header else None
    data = rows[2:] if has_header else rows

    if not data:
        return None

    ncol = max([len(r) for r in ([header] if header else []) + data])
    if ncol == 0:
        return None

    def norm(r: list[str]) -> list[str]:
        return r + [""] * (ncol - len(r))

    return {
        "header": norm(header) if header else None,
        "data": [norm(r) for r in data],
        "ncol": ncol,
    }


def parse_markdown(text: str) -> tuple[str | None, list[tuple[list[str], dict]]]:
    """返回 (文档标题, [(章节路径, 表格)…])。"""
    lines = text.splitlines()
    stack: dict[int, str] = {}
    tables: list[tuple[list[str], dict]] = []
    doc_title: str | None = None

    in_code = False
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            i += 1
            continue

        if in_code:
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", raw)
        if m:
            lvl = len(m.group(1))
            title = _clean_cell(m.group(2))
            if lvl == 1 and doc_title is None:
                doc_title = title
            stack[lvl] = title
            for k in [k for k in stack if k > lvl]:
                del stack[k]
            i += 1
            continue

        if stripped.startswith("|"):
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i])
                i += 1
            tbl = _build_table(buf)
            if tbl:
                path = [stack[k] for k in sorted(stack)]
                tables.append((path, tbl))
            continue

        i += 1

    return doc_title, tables


# ---------------------------------------------------------------- Excel 输出

def _disp_len(value: str) -> int:
    longest = 0
    for seg in str(value).split("\n"):
        w = sum(2 if ord(ch) > 0x2E7F else 1 for ch in seg)
        longest = max(longest, w)
    return longest


def _section_key(path: list[str]) -> tuple[str, str]:
    """由章节路径推导 (工作表名, 章节全路径文本)。"""
    if not path:
        return "前言", "（无标题）"
    if len(path) >= 2:
        return path[1], " > ".join(path)
    return path[0], path[0]


_ILLEGAL = re.compile(r"[\[\]\*\?/\\:]")


def _set(ws, row: int, col: int, value):
    """安全写入：强制字符串单元格为文本类型。

    形如 `= 0%（绝对红线）` 的内容会被 openpyxl 推断为公式，Excel 打开时显示
    `#NAME?`；此处统一回退为文本，避免误算与公式注入。
    """
    cell = ws.cell(row, col)
    cell.value = value
    if isinstance(value, str) and cell.data_type == "f":
        cell.data_type = "s"
    return cell


def _sheet_name(raw: str, used: set[str]) -> str:
    name = _ILLEGAL.sub("-", raw).strip() or "表格"
    name = name[:31]
    if name not in used:
        used.add(name)
        return name
    k = 2
    while True:
        cand = f"{name[:28]}_{k}"
        if cand not in used:
            used.add(cand)
            return cand
        k += 1


def _write_index(ws, src_md: str, ws_count: int, entries: list[tuple[int, str, str, dict, str]]):
    ws.cell(1, 1, "Markdown → Excel 表格索引").font = TITLE_FONT
    meta = [
        ("源文档", src_md),
        ("生成时间", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("表格总数", str(len(entries))),
        ("章节工作表数", str(ws_count)),
    ]
    r = 3
    for k, v in meta:
        _set(ws, r, 1, k).font = Font(bold=True, size=10)
        _set(ws, r, 2, v).font = META_FONT
        r += 1

    r += 1
    heads = ["序号", "表名", "章节路径", "数据行数", "列数", "所在工作表"]
    for j, h in enumerate(heads, start=1):
        c = _set(ws, r, j, h)
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.border = BORDER
        c.alignment = WRAP_HDR
    r += 1
    for seq, name, path_txt, tbl, sheet in entries:
        vals = [seq, name, path_txt, len(tbl["data"]), tbl["ncol"], sheet]
        for j, v in enumerate(vals, start=1):
            c = _set(ws, r, j, v)
            c.font = BODY_FONT
            c.border = BORDER
            c.alignment = WRAP
        r += 1

    widths = [6, 34, 44, 10, 7, 22]
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(9, 1)


def _write_section(ws, doc_title: str, items: list[tuple[str, dict]]):
    ws.cell(1, 1, f"来源文档：{doc_title}").font = Font(bold=True, size=12, color="1F3864")
    r = 3
    widths: dict[int, int] = {}

    for disp, tbl in items:
        ncol = tbl["ncol"]
        # 表名分隔行（整行同底色，避免视觉断裂）
        for j in range(1, ncol + 1):
            c = ws.cell(r, j)
            c.fill = NAME_FILL
            c.border = BORDER
        c = _set(ws, r, 1, disp)
        c.font = NAME_FONT
        c.alignment = Alignment(vertical="center")
        widths[1] = max(widths.get(1, 0), _disp_len(disp))
        r += 1

        if tbl["header"]:
            for j, v in enumerate(tbl["header"], start=1):
                c = _set(ws, r, j, v)
                c.font = HDR_FONT
                c.fill = HDR_FILL
                c.border = BORDER
                c.alignment = WRAP_HDR
                widths[j] = max(widths.get(j, 0), _disp_len(v))
            r += 1

        for row in tbl["data"]:
            for j in range(ncol):
                v = row[j] if j < len(row) else ""
                c = _set(ws, r, j + 1, v)
                c.font = BODY_FONT
                c.border = BORDER
                c.alignment = WRAP
                widths[j + 1] = max(widths.get(j + 1, 0), _disp_len(v))
            r += 1

        r += 1  # 表格之间空一行

    for j, w in widths.items():
        ws.column_dimensions[get_column_letter(j)].width = max(
            MIN_COL_WIDTH, min(MAX_COL_WIDTH, w + 2)
        )


def _save_workbook(wb, out_path: str) -> None:
    """落盘工作簿。

    优先「临时文件 + 原子替换」；若目标被 Excel / WPS / 预览面板持有句柄，
    Windows 会拒绝重命名（WinError 5），此时回退为**原地覆盖写**（这类句柄通常
    允许写入只是不允许改名）。任一路径失败都会重试并最终抛错，由调用方记录。
    """
    tmp_path = out_path + ".writing.tmp"
    wb.save(tmp_path)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            os.replace(tmp_path, out_path)
            last_err = None
            break
        except OSError as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))

    if last_err is not None:
        for attempt in range(3):
            try:
                with io.open(tmp_path, "rb") as src, io.open(out_path, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                last_err = None
                break
            except OSError as exc:
                last_err = exc
                time.sleep(0.5 * (attempt + 1))

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass

    if last_err is not None:
        raise last_err


def convert(md_path: str) -> dict | None:
    with io.open(md_path, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()

    doc_title, tables = parse_markdown(text)
    total_rows = sum(len(t["data"]) for _, t in tables)
    if not tables or total_rows < MIN_DATA_ROWS:
        return {"skipped": True, "md": md_path, "tables": len(tables), "rows": total_rows}

    doc_title = doc_title or os.path.splitext(os.path.basename(md_path))[0]

    wb = Workbook()
    idx_ws = wb.active
    idx_ws.title = "00-索引"

    used = {"00-索引"}
    groups: "OrderedDict[str, list]" = OrderedDict()
    order: list[str] = []

    for path, tbl in tables:
        key, path_txt = _section_key(path)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((path_txt, tbl))

    sheet_of_group: dict[str, str] = {}
    for gname in order:
        sheet_of_group[gname] = _sheet_name(gname, used)

    entries = []
    seq = 0
    for gname in order:
        sheet = wb.create_sheet(sheet_of_group[gname])
        items = []
        for path_txt, tbl in groups[gname]:
            seq += 1
            leaf = path_txt.split(" > ")[-1]
            disp = f"表 {seq}｜{leaf}"
            items.append((disp, tbl))
            entries.append((seq, disp, path_txt, tbl, sheet_of_group[gname]))
        _write_section(sheet, doc_title, items)

    _write_index(idx_ws, os.path.relpath(md_path, ROOT), len(wb.sheetnames) - 1, entries)

    out_path = os.path.join(os.path.dirname(md_path), os.path.basename(md_path)[:-3] + ".xlsx")
    if OUT_DIR:
        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, os.path.basename(out_path))

    # 原子落盘：先写临时文件再替换；目标被 Excel/WPS/预览占用时自动回退为原地覆盖。
    _save_workbook(wb, out_path)

    return {
        "skipped": False,
        "md": md_path,
        "xlsx": out_path,
        "tables": len(entries),
        "rows": total_rows,
        "sheets": len(wb.sheetnames),
    }


# ---------------------------------------------------------------- 主流程

def collect(targets: list[str]) -> list[str]:
    files: list[str] = []
    for t in targets:
        if os.path.isfile(t):
            if t.lower().endswith(".md"):
                files.append(t)
            continue
        for dp, dns, fns in os.walk(t):
            dns[:] = [d for d in dns if d not in (".git", ".workbuddy", "__pycache__")]
            for fn in fns:
                if fn.lower().endswith(".md"):
                    files.append(os.path.join(dp, fn))
    return files


def main(argv: list[str]) -> int:
    if argv:
        targets = [os.path.abspath(a) for a in argv]
    else:
        targets = [os.path.join(ROOT, d) for d in TARGET_DIRS]
        targets += [os.path.join(ROOT, f) for f in TARGET_FILES]

    files = collect(targets)
    files = [f for f in files if not any(p in f for p in EXCLUDE_PARTS)]
    files.sort()

    ok, skipped, failed = [], [], []
    for f in files:
        try:
            res = convert(f)
        except Exception as exc:  # 单文件失败不阻断整批
            failed.append((f, exc))
            print(f"[失败] {type(exc).__name__}: {exc}  →  {os.path.relpath(f, ROOT)}")
            continue
        if res is None:
            continue
        if res["skipped"]:
            skipped.append(res)
            print(f"[跳过] 表格过少（表 {res['tables']} / 行 {res['rows']}）  {os.path.relpath(res['md'], ROOT)}")
        else:
            ok.append(res)
            print(
                f"[完成] 表 {res['tables']:>3} / 行 {res['rows']:>4} / 工作表 {res['sheets']:>2}  "
                f"{os.path.relpath(res['xlsx'], ROOT)}"
            )

    print(f"\n合计：转换 {len(ok)} 份，跳过 {len(skipped)} 份，失败 {len(failed)} 份，候选 {len(files)} 份")
    if ok:
        print(f"表格总计 {sum(r['tables'] for r in ok)} 个 / 数据行 {sum(r['rows'] for r in ok)} 行")
    if failed:
        print("失败清单（多为文件被 Excel/WPS 占用，关闭后重跑即可）：")
        for f, e in failed:
            print(f"  - {os.path.relpath(f, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main(sys.argv[1:]))
