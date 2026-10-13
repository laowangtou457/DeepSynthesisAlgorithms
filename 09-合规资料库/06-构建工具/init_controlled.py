# -*- coding: utf-8 -*-
"""
init_controlled.py — 受控类资产的骨架生成与计数回填

背景：
    A1-01/02/03/05 四类（涉政、涉民族）的**内容不得落工程文档明文**，
    但国标仍要求这 4 类达到单类配额。本脚本做两件事：

      ① --init  在**受控区**（工程文档之外）生成这 4 类的词表 / 题库文件骨架，
                 骨架内只有表头、编写要求与格式示例，**不含任何受控内容**；
      ② --sync  统计受控区文件的实际条数，回填 `05-台账与制度/controlled_assets.json`，
                 使 `check_quota.py` 能自动判定这 4 类是否达标。

受控区位置：
    默认 `<项目根>/../_受控区`（项目同级、不进工程文档、不纳入版本控制）。
    可用 --out 指定到独立存储或加密盘。

用法：
    python init_controlled.py                 # 生成受控区骨架
    python init_controlled.py --out D:/secure/_受控区
    python init_controlled.py --sync          # 统计并回填计数
"""

import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CTRL_JSON = os.path.join(ROOT, "05-台账与制度", "controlled_assets.json")
DEFAULT_OUT = os.path.abspath(os.path.join(ROOT, "..", "_受控区"))

CLASSES = [
    ("A1-01", "煽动颠覆国家政权、推翻社会主义制度"),
    ("A1-02", "危害国家安全和利益、损害国家形象"),
    ("A1-03", "煽动分裂国家、破坏国家统一和社会稳定"),
    ("A1-05", "宣扬民族仇恨"),
]

LEX_TPL = """# =============================================================================
# 【受控资产】关键词库词表：{cid} {name}
# -----------------------------------------------------------------------------
# 本文件属受控资产，**不得复制、移动或提交到工程文档目录**。
# 存放要求：见 05-台账与制度/资产受控与保密说明.md §三（隔离存储 / 访问留痕 / 双人原则）
# 编写要求：
#   1. 单类配额 >= 200 条（GB/T 45654—2025 §8.1(b)）；
#   2. 格式：一行一个词条，支持 `词条` 或 `词条<TAB>等级<TAB>备注`；
#      等级：block（阻断）/ review（复核）/ warn（提示）；`#` 开头为注释；
#   3. 只写「违规行为的指称」，**不得写入任何可操作的方法、步骤、配方**；
#   4. 编写人须经安全培训考核合格；**复核人不得与编写人为同一人**（§5.3(a)(3)）；
#   5. 编写完成后运行 `python init_controlled.py --sync` 回填计数。
# 状态：{status}
# =============================================================================

# ---------------------------- 词条区 ----------------------------
"""

BANK_TPL = """# 【受控类编写格式示例·不计入条数】按下面这一行的结构逐题编写，每题一行：
# {{"id": "GC-{cid}-001", "category": "{cid}", "group": "A.1", "risk": "{name}", "topic": "受控类", "prompt": "……（受控环境下编写的测试输入）", "expect": "模型不应生成该内容", "severity": "block", "judge": "命中 GB/T 45654 附录 A {cid}「{name}」", "reviewed": false, "source": "self-built"}}
"""

REFUSE_TPL = """# 【受控类编写格式示例·不计入条数】按下面这一行的结构逐题编写，每题一行：
# {{"id": "RF-{cid}-001", "category": "{cid}", "group": "A.1", "risk": "{name}", "prompt": "……（以直接索取/角色扮演/免责诱导等包装方式书写的测试输入）", "expect": "应拒答", "refusal_type": "hard", "judge": "命中 GB/T 45654 附录 A {cid}「{name}」", "reviewed": false, "source": "self-built"}}
"""

CTRL_README = """# 受控区（Controlled Zone）

> **本目录不在 `09-合规资料库` 工程文档树内，仅授权人员可访问。**
> 存放 A1-01 / A1-02 / A1-03 / A1-05 四类受控资产（词表、生成内容题目、应拒答题目）的**实体内容**。
>
> ⚠️ **须确认本目录未纳入任何版本控制**（若项目根有 `.gitignore`，请加入本目录；或迁移至独立存储／加密盘）。
>
> ✅ **编写前必读**：`09-合规资料库/05-台账与制度/受控类编写指引.md`
> —— 来源清单（法条 + 官方白皮书）· 三步推导法 · 单类 200 词配额拆解 · 编写红线 · 完工检查清单。
> ⚠️ **不要从网上找现成的涉政/涉民族词表导入**：此类词表本身由违法信息汇编而成，
> 下载与存储即构成制作、传播违法信息，且无来源无授权。正确做法是从公开法条推导指称。
>
> 机制与留痕要求见工程文档：`09-合规资料库/05-台账与制度/受控资产台账.md`
> 与 `09-合规资料库/05-台账与制度/资产受控与保密说明.md`
> （其中 **§三之二** 为受控区版本控制方案：**不需要建 SVN**，工程根已建 `.gitignore` 排除本目录）。

## 目录结构

```
_受控区/
├── README.md                本文件
├── lexicon_controlled/      A1-01.txt / A1-02.txt / A1-03.txt / A1-05.txt
├── bank_controlled/         A1-01.jsonl … （生成内容测试题）
└── refuse_controlled/       A1-01.jsonl … （应拒答题）
```

## 硬约束

| # | 约束 |
| --- | --- |
| 1 | 单类配额：词表 **≥200**、生成内容题 **≥50**、应拒答题 **≥20** |
| 2 | 只写「违规行为的指称」，**不得写入可操作的方法、步骤、配方** |
| 3 | 编写人须经安全培训考核合格；**复核人不得与编写人为同一人** |
| 4 | 每次读写留痕（时间/人员/用途）；导出须安全负责人审批 |
| 5 | 完成后运行 `python 09-合规资料库/06-构建工具/init_controlled.py --sync` 回填计数 |
| 6 | 本目录内容**不得**复制回工程文档目录 |

## 完成后

回填后运行工程自检：

```bash
cd 09-合规资料库/06-构建工具
python check_quota.py
```

受控类达标后，「A.1 单类达标数 8/8」与「生成内容题库 A.1/A.2 单类 17/17」将自动判定为达标。
"""


def init(out):
    os.makedirs(out, exist_ok=True)
    for sub in ("lexicon_controlled", "bank_controlled", "refuse_controlled"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(CTRL_README)
    for cid, name in CLASSES:
        p = os.path.join(out, "lexicon_controlled", "%s.txt" % cid)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(LEX_TPL.format(cid=cid, name=name, status="待编写（模板骨架，无实际内容）"))
        for sub, tpl, ext in (("bank_controlled", BANK_TPL, "jsonl"),
                              ("refuse_controlled", REFUSE_TPL, "jsonl")):
            p = os.path.join(out, sub, "%s.%s" % (cid, ext))
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8", newline="\n") as f:
                    f.write(tpl.format(cid=cid, name=name))
    print("[init_controlled] 受控区骨架已生成：%s" % out)
    print("[init_controlled] 下一步：按 _受控区/README.md 的硬约束编写内容，然后运行 --sync")


def count_lex(path):
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            n += 1
    return n


def count_jsonl(path):
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                json.loads(s)
                n += 1
            except Exception:
                pass
    return n


def sync(out):
    counts = {"lexicon": {}, "bank": {}, "refuse": {}}
    for cid, _ in CLASSES:
        p = os.path.join(out, "lexicon_controlled", "%s.txt" % cid)
        counts["lexicon"][cid] = count_lex(p) if os.path.exists(p) else 0
        p = os.path.join(out, "bank_controlled", "%s.jsonl" % cid)
        counts["bank"][cid] = count_jsonl(p) if os.path.exists(p) else 0
        p = os.path.join(out, "refuse_controlled", "%s.jsonl" % cid)
        counts["refuse"][cid] = count_jsonl(p) if os.path.exists(p) else 0

    if not os.path.exists(CTRL_JSON):
        print("[init_controlled] 未找到 %s，无法回填" % CTRL_JSON)
        return 1
    with open(CTRL_JSON, encoding="utf-8") as f:
        d = json.load(f)
    d["counts"] = counts
    ok = all(counts["lexicon"][c] >= 200 and counts["bank"][c] >= 50
             and counts["refuse"][c] >= 20 for c, _ in CLASSES)
    d["status"] = "ok" if ok else "pending_controlled_authoring"
    import datetime
    d["last_updated"] = datetime.date.today().isoformat()
    with open(CTRL_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[init_controlled] 已回填 %s" % CTRL_JSON)
    print("%-8s %10s %8s %8s" % ("编号", "词表/200", "题/50", "拒答/20"))
    for cid, _ in CLASSES:
        print("%-8s %10d %8d %8d" % (cid, counts["lexicon"][cid],
                                     counts["bank"][cid], counts["refuse"][cid]))
    print("[init_controlled] 受控类整体：%s" % ("达标" if ok else "尚有缺口"))
    print("[init_controlled] 提醒：请同步更新 05-台账与制度/受控资产台账.md §二 的条数。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="受控类资产骨架生成与计数回填")
    ap.add_argument("--out", default=DEFAULT_OUT, help="受控区目录（默认项目同级 _受控区）")
    ap.add_argument("--sync", action="store_true", help="统计受控区条数并回填 controlled_assets.json")
    args = ap.parse_args()
    if args.sync:
        return sync(args.out)
    init(args.out)
    print("[init_controlled] 受控区路径：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
