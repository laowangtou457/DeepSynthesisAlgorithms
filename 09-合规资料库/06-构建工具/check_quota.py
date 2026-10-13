# -*- coding: utf-8 -*-
"""
check_quota.py — 合规资料库达标自检

对照 GB/T 45654—2025 §8.1 / §8.2 / §8.3 的量化门槛，统计本库三大资产的实际规模，
输出达标状态表与差距清单。

用法：
    python check_quota.py             # 打印达标状态表
    python check_quota.py --json      # 输出机读 JSON（供台账 / CI 使用）
    python check_quota.py --strict    # 未达标时返回非 0 退出码（供 CI 卡点）

依据：
    §8.1 关键词库      总规模 >= 10000；覆盖 A.1+A.2 共 17 类；A.1 >= 200/类，A.2 >= 100/类
    §8.2 生成内容题库  总规模 >= 2000；覆盖全部 31 类；A.1/A.2 >= 50/类，其他 >= 20/类
    §8.3 拒答题库      应拒答 >= 500（覆盖 A.1/A.2 共 17 类，>= 20/类）
                       非拒答 >= 500（覆盖制度/信仰/形象/文化/习俗/民族/地理/历史/英烈
                                     以及性别/年龄/职业/健康等，>= 20/项）
"""

import os
import re
import sys
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LEX_DIR = os.path.join(ROOT, "01-关键词库")
LEX_MANIFEST = os.path.join(LEX_DIR, "lexicon_manifest.json")
LEX_VOCAB = os.path.join(LEX_DIR, "词表")

BANK_DIR = os.path.join(ROOT, "02-生成内容测试题库", "题目")
REFUSE_DIR = os.path.join(ROOT, "03-拒答题库", "应拒答")
NONREFUSE_DIR = os.path.join(ROOT, "03-拒答题库", "非拒答")

# 受控类机读计数（只含条数，不含内容）——见 05-台账与制度/SEC-009_受控资产台账.md
CONTROLLED_JSON = os.path.join(ROOT, "05-台账与制度", "controlled_assets.json")

# ---------------------------------------------------------------- 阈值
TH = dict(
    lex_total=10000, lex_a1=200, lex_a2=100,
    gc_total=2000, gc_a12=50, gc_other=20,
    refuse_total=500, refuse_per=20,
    nonrefuse_total=500, nonrefuse_per=20,
)

OK = "达标"
NG = "未达标"


def count_lexicon_words(path):
    """统计词表文件中的有效词条数（排除空行与 # 注释）。"""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            n += 1
    return n


def load_controlled():
    """读取受控类计数（A1-01/02/03/05）。

    受控内容不在工程文档明文留痕，规模以《受控资产台账》与其机读文件为准。
    返回 {'lexicon': {...}, 'bank': {...}, 'refuse': {...}}；文件缺失时返回空 dict。
    """
    if not os.path.exists(CONTROLLED_JSON):
        return {}
    try:
        with open(CONTROLLED_JSON, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    return d.get("counts", {})


def scan_lexicon():
    if not os.path.exists(LEX_MANIFEST):
        return None
    with open(LEX_MANIFEST, encoding="utf-8") as f:
        mf = json.load(f)
    ctrl = load_controlled().get("lexicon", {})
    rows = []
    total = 0
    for cat in mf["categories"]:
        if cat.get("controlled"):
            # 受控类：计数取自台账（文件内只保留骨架与模板，不计入明文规模）
            n = int(ctrl.get(cat["id"], 0))
            src = "台账"
        else:
            path = os.path.join(LEX_VOCAB, cat["file"])
            n = count_lexicon_words(path) if os.path.exists(path) else 0
            src = "文件"
        total += n
        rows.append(dict(id=cat["id"], group=cat["group"], name=cat["name"],
                         quota=cat["quota"], actual=n, source=src,
                         ok=(n >= cat["quota"]), controlled=cat["controlled"]))
    return dict(rows=rows, total=total, manifest=mf)


def scan_jsonl_dir(dirpath, pattern="*.jsonl"):
    """扫描目录下所有 jsonl，按 category / topic 字段统计行数。"""
    stat = {}
    bad = 0
    for fp in glob.glob(os.path.join(dirpath, pattern)):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    bad += 1
                    continue
                key = obj.get("category") or obj.get("topic") or "_unknown"
                stat[key] = stat.get(key, 0) + 1
    return stat, sum(stat.values()), bad


def fmt_row(cols, widths):
    return "  ".join(str(c).ljust(w) if not _is_cjk_heavy(str(c)) else str(c).ljust(w + _cjk_pad(str(c), w)) for c, w in zip(cols, widths))


def _is_cjk_heavy(s):
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _cjk_pad(s, w):
    """中文字符占 2 列宽，计算需要额外补的空格数。"""
    visual = 0
    for ch in s:
        visual += 2 if ("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef") else 1
    return max(0, w - visual)


def pad(s, w):
    s = str(s)
    visual = 0
    for ch in s:
        visual += 2 if ("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef") else 1
    return s + " " * max(0, w - visual)


def main():
    want_json = "--json" in sys.argv
    strict = "--strict" in sys.argv
    report = dict(standard="GB/T 45654—2025", checks=[], overall=True)

    # ---------------- 1. 关键词库 ----------------
    lex = scan_lexicon()
    if lex:
        a1 = [r for r in lex["rows"] if r["group"] == "A.1"]
        a2 = [r for r in lex["rows"] if r["group"] == "A.2"]
        a1_ok = sum(1 for r in a1 if r["ok"])
        a2_ok = sum(1 for r in a2 if r["ok"])
        total_ok = lex["total"] >= TH["lex_total"]
        overall = total_ok and a1_ok == 8 and a2_ok == 9
        report["checks"].append(dict(
            资产="关键词库", 指标="总规模", 要求=">= %d" % TH["lex_total"],
            实际=lex["total"], 状态=OK if total_ok else NG, 项数=overall))
        report["checks"].append(dict(
            资产="关键词库", 指标="A.1 单类达标数", 要求="8/8", 实际="%d/8" % a1_ok,
            状态=OK if a1_ok == 8 else NG, 项数=overall))
        report["checks"].append(dict(
            资产="关键词库", 指标="A.2 单类达标数", 要求="9/9", 实际="%d/9" % a2_ok,
            状态=OK if a2_ok == 9 else NG, 项数=overall))
        ctrl_rows = [r for r in lex["rows"] if r["controlled"]]
        ctrl_ok = sum(1 for r in ctrl_rows if r["ok"])
        report["checks"].append(dict(
            资产="关键词库", 指标="受控类（按台账计数）", 要求="4/4",
            实际="%d/4" % ctrl_ok, 状态=OK if ctrl_ok == 4 else NG,
            项数=(ctrl_ok != 4)))
        report["lexicon_detail"] = lex["rows"]
        report["overall"] = report["overall"] and overall

    # ---------------- 2. 生成内容测试题库 ----------------
    gc_stat, gc_total, gc_bad = scan_jsonl_dir(BANK_DIR)
    # 受控类以台账计数为准（覆盖文件内的模板占位计数）
    for cid, n in load_controlled().get("bank", {}).items():
        gc_stat[cid] = int(n)
    gc_total = sum(gc_stat.values())
    gc_total_ok = gc_total >= TH["gc_total"]
    a12_keys = [k for k in gc_stat if k.startswith("A1-") or k.startswith("A2-")]
    a12_ok = sum(1 for k in a12_keys if gc_stat[k] >= TH["gc_a12"])
    report["checks"].append(dict(
        资产="生成内容测试题库", 指标="总规模", 要求=">= %d" % TH["gc_total"],
        实际=gc_total, 状态=OK if gc_total_ok else NG, 项数=False))
    report["checks"].append(dict(
        资产="生成内容测试题库", 指标="31 类覆盖", 要求="31", 实际=len(gc_stat),
        状态=OK if len(gc_stat) >= 31 else NG, 项数=False))
    report["checks"].append(dict(
        资产="生成内容测试题库", 指标="A.1/A.2 单类 >=50", 要求="17/17",
        实际="%d/17" % a12_ok, 状态=OK if a12_ok == 17 else NG, 项数=False))
    report["gc_stat"] = gc_stat
    report["gc_bad_lines"] = gc_bad
    report["overall"] = report["overall"] and gc_total_ok and len(gc_stat) >= 31 and a12_ok == 17

    # ---------------- 3. 拒答题库 ----------------
    rf_stat, rf_total, rf_bad = scan_jsonl_dir(REFUSE_DIR)
    for cid, n in load_controlled().get("refuse", {}).items():
        rf_stat[cid] = int(n)
    rf_total = sum(rf_stat.values())
    nr_stat, nr_total, nr_bad = scan_jsonl_dir(NONREFUSE_DIR)
    rf_ok = rf_total >= TH["refuse_total"]
    nr_ok = nr_total >= TH["nonrefuse_total"]
    report["checks"].append(dict(
        资产="应拒答题库", 指标="总规模", 要求=">= %d" % TH["refuse_total"],
        实际=rf_total, 状态=OK if rf_ok else NG, 项数=False))
    report["checks"].append(dict(
        资产="非拒答题库", 指标="总规模", 要求=">= %d" % TH["nonrefuse_total"],
        实际=nr_total, 状态=OK if nr_ok else NG, 项数=False))
    report["refuse_stat"] = rf_stat
    report["nonrefuse_stat"] = nr_stat
    report["overall"] = report["overall"] and rf_ok and nr_ok

    # ---------------- 输出 ----------------
    if want_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["overall"] else (1 if strict else 0)

    print("=" * 100)
    print("合规资料库 · 达标自检报告   （依据 GB/T 45654—2025）")
    print("=" * 100)
    print(pad("资产", 22) + pad("指标", 24) + pad("要求", 14) + pad("实际", 12) + "状态")
    print("-" * 100)
    for c in report["checks"]:
        print(pad(c["资产"], 22) + pad(c["指标"], 24) + pad(c["要求"], 14) +
              pad(c["实际"], 12) + c["状态"])
    print("-" * 100)

    if lex:
        print("\n【关键词库 · 分类明细】")
        print(pad("编号", 10) + pad("组别", 8) + pad("风险项", 44) + pad("配额", 8) + pad("实际", 8) + "状态")
        print("-" * 100)
        for r in report["lexicon_detail"]:
            name = r["name"]
            if len(name) > 20:
                name = name[:19] + "…"
            tag = "  [受控·按台账]" if r["controlled"] else ""
            print(pad(r["id"], 10) + pad(r["group"], 8) + pad(name, 44) +
                  pad(r["quota"], 8) + pad(r["actual"], 8) +
                  ("达标" if r["ok"] else "未达标") + tag)

        ctrl_pending = [r["id"] for r in report["lexicon_detail"]
                        if r["controlled"] and not r["ok"]]
        if ctrl_pending:
            print("\n⚠ 受控类待回填：%s" % "、".join(ctrl_pending))
            print("  受控内容不在工程文档明文留痕，规模以 05-台账与制度/SEC-009_受控资产台账.md 与")
            print("  05-台账与制度/controlled_assets.json 为准；回填后本项自动判定（见 06-构建工具/README.md）。")

    print("\n" + "=" * 100)
    print("总体结论：%s" % ("全部达标" if report["overall"] else "尚未达标（公开部分见上表；受控类见台账）"))
    print("=" * 100)

    if gc_bad or rf_bad or nr_bad:
        print("提示：题库存在 JSON 解析失败行 —— 生成内容 %d 行，应拒答 %d 行，非拒答 %d 行"
              % (gc_bad, rf_bad, nr_bad))

    return 0 if report["overall"] else (1 if strict else 0)


if __name__ == "__main__":
    sys.exit(main())
