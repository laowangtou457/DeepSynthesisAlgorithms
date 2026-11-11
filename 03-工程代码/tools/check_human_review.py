#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验人工核对台账（`SEC-022`）——交付门禁第 18 项的唯一合法来源。

用法::

    # 1) 校验默认台账（APP_HUMAN_REVIEW_LEDGER，缺省指向 _私密实值/human_review_ledger.json）
    python 03-工程代码/tools/check_human_review.py

    # 2) 查某个包是否已有人工核对记录
    python 03-工程代码/tools/check_human_review.py --pack-id FR-PK-20261111-A1B2C3D4

    # 3) 扫描交付输出根目录，列出「哪些包还缺台账」
    python 03-工程代码/tools/check_human_review.py --scan "C:/path/to/delivery_out"

退出码：`0` 全部通过；`1` 有问题（错误或目标包缺记录）。

⚠️ 本工具**只读不写**，不会替你补记录、不会改模板。
⚠️ 台账里的 `operator` 是真实姓名，**只允许**存在于 `_私密实值/`（不入库）——
   入库那份永远是模板（`{{核对人}}`）。若本工具在你指定的台账里发现占位符，
   说明「复制了模板但没填」，按错误报出。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

#: 工程根（本文件位于 `<根>/03-工程代码/tools/`）
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "_私密实值" / "human_review_ledger.json"
TEMPLATE = ROOT / "09-合规资料库" / "05-台账与制度" / "SEC-022_人工核对台账-模板.json"

RESULTS = {"pass", "warn", "fail"}
REQUIRED = ("pack_id", "no", "item", "result", "checked_at", "operator")
PLACEHOLDER_MARKS = ("{{", "}}", "待填", "TBD", "xxx")


def _is_placeholder(value: str) -> bool:
    low = str(value).strip().lower()
    if not low:
        return True
    return any(m.lower() in low for m in PLACEHOLDER_MARKS)


def _parse_time(text: str) -> datetime | None:
    """解析 ISO 8601。**必须带时区**——不带时区的时间无法确定核对发生在哪一刻。"""
    raw = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _resolve_ledger(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = str(os.environ.get("APP_HUMAN_REVIEW_LEDGER", "") or "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_LEDGER


def load_records(path: Path) -> tuple[list[dict], list[str]]:
    """读台账，返回（记录列表，结构级错误）。"""
    errors: list[str] = []
    if not path.is_file():
        return [], [f"台账文件不存在：{path}（门禁将判 human_review.missing 并阻断正式包）"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"]
    except OSError as exc:
        return [], [f"读取失败：{exc}"]
    rows = data.get("records") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return [], ["结构错误：顶层应为 {\"records\": [...]}，或直接是记录数组"]
    return [r for r in rows if isinstance(r, dict)], errors


def check_row(idx: int, row: dict, *, now: datetime | None = None) -> list[str]:
    """逐条校验，返回该条的错误列表。`idx` 从 1 起。"""
    errs: list[str] = []
    tag = f"第 {idx} 条"

    # pack_id 与示例撞号：模板里的示例若被照抄，会造成「假命中」
    if str(row.get("pack_id", "")).strip() == "FR-PK-20261111-A1B2C3D4":
        errs.append(f"{tag}：pack_id 与模板 _example 完全相同 ⇒ 疑似照抄示例，请填真实交付包编号")

    for key in REQUIRED:
        val = row.get(key)
        if val is None or str(val).strip() == "":
            errs.append(f"{tag}：缺必填字段 `{key}`")

    pid = str(row.get("pack_id", "")).strip()
    if pid and "-PK-" not in pid:
        errs.append(f"{tag}：pack_id 形态可疑（`{pid}`），应为 `<主体码>-PK-<YYYYMMDD>-<8位十六进制>`")

    no = row.get("no")
    if no is not None and str(no).strip() not in ("18", "18.0"):
        errs.append(f"{tag}：`no` 应为 18（§8.3 第 18 项），实际 `{no}`")

    result = str(row.get("result", "")).strip()
    if result and result not in RESULTS:
        errs.append(f"{tag}：`result` 只能取 pass／warn／fail，实际 `{result}`")

    checked = str(row.get("checked_at", "")).strip()
    if checked:
        dt = _parse_time(checked)
        if dt is None:
            errs.append(f"{tag}：`checked_at` 不是带时区的 ISO 8601（例：2026-11-11T15:20:00+08:00）")
        elif now and dt > now:
            errs.append(f"{tag}：`checked_at` 晚于当前时刻 ⇒ 核对时间不能是未来")

    op = str(row.get("operator", "")).strip()
    if op and _is_placeholder(op):
        errs.append(f"{tag}：`operator` 仍是占位/空值（`{op}`）⇒ 复制了模板但没填核对人")

    if not str(row.get("detail", "")).strip():
        pass  # detail 为「建议」项，不报错
    return errs


def scan_packs(root: Path, records: list[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    """扫描交付输出根目录，返回（[(pack_id, 状态)], 错误）。"""
    errs: list[str] = []
    if not root.is_dir():
        return [], [f"扫描目录不存在：{root}"]
    have = {str(r.get("pack_id", "")).strip(): str(r.get("result", "")).strip() for r in records}
    rows: list[tuple[str, str]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        pid = child.name
        if "-PK-" not in pid:
            continue
        if pid not in have:
            rows.append((pid, "缺台账 ⇒ 门禁 human_review.missing"))
        elif have[pid] == "fail":
            rows.append((pid, "台账判 fail ⇒ 不得交付"))
        else:
            rows.append((pid, have[pid] or "result 为空"))
    return rows, errs


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="校验 SEC-022 人工核对台账")
    ap.add_argument("--ledger", help="台账路径（默认取 APP_HUMAN_REVIEW_LEDGER，再缺省 _私密实值/human_review_ledger.json）")
    ap.add_argument("--pack-id", help="只关心这个包是否已有可用记录")
    ap.add_argument("--scan", help="扫描交付输出根目录，列出每个包的台账状态")
    ap.add_argument("--allow-empty", action="store_true", help="允许台账为空（仅用于模板自检）")
    args = ap.parse_args(argv)

    ledger = _resolve_ledger(args.ledger)
    print(f"台账：{ledger}")
    records, struct_errs = load_records(ledger)

    # `_私密实值/` 就在工程树内但已被 .gitignore 排除 ⇒ 不应误报「入库文件」告警
    in_repo = (ROOT in ledger.parents or ledger.parent == ROOT) and "_私密实值" not in ledger.parts
    if in_repo and ledger.is_file() and ledger != TEMPLATE:
        # 入库文件不该带真实姓名，提醒但不阻断（到底是不是私密区由人判断）
        print("⚠️ 该台账位于工程树内：入库文件必须无真实姓名，请确认它已在 .gitignore 内")

    errors: list[str] = list(struct_errs)
    now = datetime.now(timezone.utc)

    if not records and not struct_errs:
        if args.allow_empty:
            print("台账为空（--allow-empty，跳过记录校验）")
        else:
            errors.append("台账 records 为空 ⇒ 门禁将判 human_review.missing 并阻断正式包")

    for i, row in enumerate(records, start=1):
        errors.extend(check_row(i, row, now=now))

    # 重复记录（同包同 no）不是错误，但值得提示：便于发现「同一包写了两遍」
    seen: dict[tuple[str, str], int] = {}
    for row in records:
        key = (str(row.get("pack_id", "")).strip(), str(row.get("no", "")).strip())
        seen[key] = seen.get(key, 0) + 1
    dup = [f"{k[0]}（no={k[1]}，{v} 条）" for k, v in seen.items() if v > 1]
    if dup:
        print("提示：同一包同一核对项存在多条记录（按规则任一条 fail 即判 fail）：" + "；".join(dup))

    if args.pack_id:
        target = args.pack_id.strip()
        mine = [r for r in records if str(r.get("pack_id", "")).strip() == target]
        if not mine:
            errors.append(f"包 {target} 无任何人工核对记录 ⇒ 该包不得作为正式交付")
        else:
            bad = [r for r in mine if str(r.get("result", "")).strip() == "fail"]
            if bad:
                errors.append(f"包 {target} 的核对记录判 fail ⇒ 不得交付")
            else:
                print(f"包 {target}：{len(mine)} 条记录，结论 " + "／".join(sorted({str(r.get('result','')) for r in mine})))

    if args.scan:
        rows, scan_errs = scan_packs(Path(args.scan).expanduser(), records)
        errors.extend(scan_errs)
        print(f"\n扫描 {args.scan} —— 共 {len(rows)} 个交付包：")
        for pid, state in rows:
            print(f"  {pid}  {state}")

    print()
    if errors:
        print(f"❌ {len(errors)} 项问题：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"✅ 台账校验通过（{len(records)} 条记录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
