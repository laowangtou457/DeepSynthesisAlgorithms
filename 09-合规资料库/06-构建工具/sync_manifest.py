# -*- coding: utf-8 -*-
"""
sync_manifest.py —— 把四份 manifest 的计数与实体文件对齐

背景
----
`init_lexicon.py` / `init_banks.py` / `init_nonrefuse.py` 写入的 `seed_count`
只反映**初始化（种子）阶段**的条数。此后 `expand_lexicon.py` /
`expand_banks.py` / `expand_refusal.py` / 人工编写都不会回头改 manifest，
于是 manifest 里的数字会与实体文件长期不一致——评估方一比对就穿帮。

本脚本做两件事（**不修改 `seed_count`，保留其历史含义**）：
  1. 为每个类别补/更新 `current_count` = 实体文件当前条数；
  2. 写入顶层 `counts_snapshot` = {as_of, totals, note}。

受控类（A1-01 / A1-02 / A1-03 / A1-05）
---------------------------------------
工程文档内只留**不计数的编写模板占位**，其真实规模以
`05-台账与制度/controlled_assets.json` 为准。
故本脚本对受控类把 `current_count` 记为 0，并附 `counted_via` 说明。

用法
----
    python sync_manifest.py --dry-run     # 只打印将要写入的内容
    python sync_manifest.py               # 落盘
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

LEX_DIR = os.path.join(ROOT, "01-关键词库", "词表")
BANK_DIR = os.path.join(ROOT, "02-生成内容测试题库", "题目")
REFUSE_DIR = os.path.join(ROOT, "03-拒答题库", "应拒答")
NONREFUSE_DIR = os.path.join(ROOT, "03-拒答题库", "非拒答")

CONTROLLED_JSON = os.path.join(ROOT, "05-台账与制度", "controlled_assets.json")

TARGETS = [
    # (manifest 路径, 实体目录, 计数函数名, 受控口径键)
    (os.path.join(ROOT, "01-关键词库", "lexicon_manifest.json"), LEX_DIR, "lex", "lexicon"),
    (os.path.join(ROOT, "02-生成内容测试题库", "bank_manifest.json"), BANK_DIR, "jsonl", "bank"),
    (os.path.join(ROOT, "03-拒答题库", "refusal_manifest.json"), REFUSE_DIR, "jsonl", "refuse"),
    (os.path.join(ROOT, "03-拒答题库", "nonrefusal_manifest.json"), NONREFUSE_DIR, "jsonl", None),
]


def count_lex(path):
    """词表：跳过注释行与空行。"""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            n += 1
    return n


def count_jsonl(path):
    """题库：跳过空行与以 # 开头的注释行，必须可解析为 JSON。"""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                json.loads(s)
            except Exception:
                continue
            n += 1
    return n


COUNT_FN = {"lex": count_lex, "jsonl": count_jsonl}


def load_controlled():
    if not os.path.exists(CONTROLLED_JSON):
        return {}
    try:
        with open(CONTROLLED_JSON, encoding="utf-8") as f:
            return json.load(f).get("counts", {})
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="把 manifest 计数与实体文件对齐")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写盘")
    args = ap.parse_args()

    ctrl = load_controlled()
    as_of = datetime.date.today().isoformat()
    grand = 0

    for mpath, data_dir, kind, ctrl_key in TARGETS:
        if not os.path.exists(mpath):
            print("[跳过] 找不到 %s" % mpath)
            continue

        with open(mpath, encoding="utf-8") as f:
            mf = json.load(f)

        fn = COUNT_FN[kind]
        cats = mf.get("categories", [])
        subtotal = 0
        rows = []

        for c in cats:
            cid = c.get("id", "")
            fname = c.get("file", "")
            fpath = os.path.join(data_dir, fname)

            if cid in ("A1-01", "A1-02", "A1-03", "A1-05") and ctrl_key:
                real = 0
                c["counted_via"] = "05-台账与制度/controlled_assets.json（受控类，工程文档内不计入）"
                ledger = int(ctrl.get(ctrl_key, {}).get(cid, 0))
                c["ledger_count"] = ledger
            else:
                c.pop("counted_via", None)
                c.pop("ledger_count", None)
                real = fn(fpath) if os.path.exists(fpath) else 0

            c["current_count"] = real
            subtotal += real
            rows.append((cid, fname, c.get("seed_count"), real))

        mf["counts_snapshot"] = {
            "as_of": as_of,
            "total": subtotal,
            "signature": "06-构建工具/sync_manifest.py",
            "note": "current_count 为实体文件当前条数；seed_count 为初始化阶段条数，保留作历史对照；受控类不计入，其规模见 05-台账与制度/controlled_assets.json",
        }
        grand += subtotal

        print("=" * 78)
        print("%s   小计 = %d" % (os.path.basename(mpath), subtotal))
        print("-" * 78)
        print("%-10s %-42s %10s %10s" % ("类别", "文件", "seed", "current"))
        for cid, fname, seed, real in rows:
            flag = ""
            if seed is not None and int(seed) != real:
                flag = "  <-- 已变化"
            print("%-10s %-42s %10s %10s%s" % (cid, fname[:42], seed, real, flag))

        if not args.dry_run:
            with open(mpath, "w", encoding="utf-8") as f:
                json.dump(mf, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print("[写入] %s" % mpath)

    print("=" * 78)
    print("四份 manifest 实体合计 = %d" % grand)
    if args.dry_run:
        print("（--dry-run：未写盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
