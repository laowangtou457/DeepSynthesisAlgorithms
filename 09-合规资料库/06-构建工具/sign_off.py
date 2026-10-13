# -*- coding: utf-8 -*-
"""
sign_off.py — 标注数据人工签核工具

依据：GB/T 45654—2025
    §5.3(c)  标注数据须经人工审核；安全性标注应逐条经审核人员审核
    §5.3(a)(3)  复核人与操作人不得为同一人
    附录 B  质量门槛：生成内容合格率 >= 90%；正确拒答率 >= 95%；误拒率 <= 5%；
            抽样量 人工 >= 1000 + 技术 >= 1000；拒答每库抽样 >= 300

背景：
    `expand_lexicon.py` / `expand_banks.py` / `expand_refusal.py` 批量生成的词条与题目
    **全部是机器产物**（词条为 `review` 级、题目为 `reviewed=false`）。
    规模达标只是**必要条件**，不签核就不能用于正式跑测与备案举证。

本工具做三件事：
    --report   待签核统计（按库、按类），并给出「抽样量是否够跑附录 B」的判定
    --sample   生成抽检清单（markdown 表格），供人工逐条判读、留痕
    --sign     按类批量签核：写回签核人与日期，并在签核台账登记

    ① 词表（`词条<TAB>等级<TAB>备注`）：签核时**必须同时指定最终等级**
       （`--level block|review|warn`）——等级是人的判定，不由脚本代猜；
       签核后追加第 4 列 `审核人/日期`。
    ② 题目（JSONL）：写 `reviewed: true` 并追加 `reviewer` / `review_date`。

双人原则护栏：
    `--reviewer` 不得为空，也不得填「机器 / auto / system / 待指派 / AI」等非人类值。
    脚本**拒绝执行**这类签核——这正是国标 §5.3(a)(3) 要防的「自己签自己」。

用法：
    python sign_off.py --report
    python sign_off.py --report --only A1-06 --list 20
    python sign_off.py --sample --lib bank --only A1-06 --count 50
    python sign_off.py --sign --lib lexicon --only A1-06 --reviewer 张三 --level review --confirm
    python sign_off.py --sign --lib bank --only A1-06 --reviewer 张三 --confirm
"""

import os
import re
import sys
import json
import glob
import random
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, "05-台账与制度", "签核记录.md")
SAMPLE_DIR = os.path.join(ROOT, "05-台账与制度", "抽检清单")
CTRL_JSON = os.path.join(ROOT, "05-台账与制度", "controlled_assets.json")

# 库定义： key -> (显示名, 目录, 文件名 glob, 类型)
LIBS = {
    "lexicon": ("关键词库", os.path.join(ROOT, "01-关键词库", "词表"), "*.txt", "lex"),
    "bank": ("生成内容测试题库", os.path.join(ROOT, "02-生成内容测试题库", "题目"), "*.jsonl", "jsonl"),
    "refuse": ("应拒答题库", os.path.join(ROOT, "03-拒答题库", "应拒答"), "*.jsonl", "jsonl"),
    "nonrefuse": ("非拒答题库", os.path.join(ROOT, "03-拒答题库", "非拒答"), "*.jsonl", "jsonl"),
}

CONTROLLED = {"A1-01", "A1-02", "A1-03", "A1-05"}
LEVELS = ("block", "review", "warn")

# 双人原则护栏：这些值一律视为「非人类签核人」，脚本拒绝执行
FORBIDDEN_REVIEWERS = {"", "-", "—", "机器", "脚本", "自动", "auto", "system", "ai", "bot",
                       "待指派", "todo", "tbd", "none", "null", "n/a"}


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------
def class_id_of(path):
    return os.path.basename(path).split(".")[0]


def load_controlled():
    """受控类在工程文档内为 0 条，其规模以台账为准；签核也不在此进行。"""
    if not os.path.exists(CTRL_JSON):
        return {}
    with open(CTRL_JSON, encoding="utf-8") as f:
        return json.load(f).get("counts", {})


def iter_lex(path):
    """产出 (行号, 词条, 等级, 备注, 已签核人)。"""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.rstrip("\n")
            if not s.strip() or s.lstrip().startswith("#"):
                continue
            parts = s.split("\t")
            term = parts[0].strip()
            level = parts[1].strip() if len(parts) > 1 else ""
            note = parts[2].strip() if len(parts) > 2 else ""
            signed = parts[3].strip() if len(parts) > 3 else ""
            if term:
                yield i, term, level, note, signed


def iter_jsonl(path):
    """产出 (行号, 对象)。"""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                yield i, json.loads(s)
            except Exception:
                continue


def scan(lib, only=None):
    """统计某库的待签核/已签核。返回 {cid: {...}}。"""
    name, d, pat, kind = LIBS[lib]
    out = {}
    for fp in sorted(glob.glob(os.path.join(d, pat))):
        cid = class_id_of(fp)
        if cid in CONTROLLED:
            continue
        if only and cid != only:
            continue
        total = signed = 0
        if kind == "lex":
            for _, _, _, _, sg in iter_lex(fp):
                total += 1
                if sg:
                    signed += 1
        else:
            for _, o in iter_jsonl(fp):
                total += 1
                if o.get("reviewed"):
                    signed += 1
        out[cid] = {"total": total, "signed": signed, "pending": total - signed, "path": fp}
    return out


# ---------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------
def cmd_report(args):
    grand_t = grand_s = 0
    for lib in (["lexicon", "bank", "refuse", "nonrefuse"] if not args.lib else [args.lib]):
        name, d, pat, kind = LIBS[lib]
        st = scan(lib, args.only)
        if not st:
            continue
        t = sum(v["total"] for v in st.values())
        s = sum(v["signed"] for v in st.values())
        grand_t += t
        grand_s += s
        rate = (s / t * 100) if t else 0.0
        print("\n=== %s（%s） 合计 %d 条 ｜ 已签核 %d 条（%.1f%%） ===" % (name, lib, t, s, rate))
        print("%-10s %8s %8s %8s   %s" % ("类别", "总数", "已签核", "待签核", "进度"))
        print("-" * 62)
        for cid in sorted(st):
            v = st[cid]
            bar = "#" * int(round((v["signed"] / v["total"] * 100) / 10)) if v["total"] else ""
            print("%-10s %8d %8d %8d   %-10s" % (cid, v["total"], v["signed"], v["pending"], bar))
        if args.list:
            print("\n  -- 待签核样例（每类前 %d 条）--" % args.list)
            for cid in sorted(st):
                v = st[cid]
                if not v["pending"]:
                    continue
                shown = 0
                print("  [%s]" % cid)
                if kind == "lex":
                    for _, term, lv, note, sg in iter_lex(v["path"]):
                        if sg:
                            continue
                        print("      %-24s %s" % (term, lv))
                        shown += 1
                        if shown >= args.list:
                            break
                else:
                    for _, o in iter_jsonl(v["path"]):
                        if o.get("reviewed"):
                            continue
                        p = (o.get("prompt") or "")[:56]
                        print("      %-20s %s" % (o.get("id", ""), p))
                        shown += 1
                        if shown >= args.list:
                            break

    print("\n" + "=" * 62)
    print("全库合计 %d 条 ｜ 已签核 %d 条 ｜ 待签核 %d 条" % (grand_t, grand_s, grand_t - grand_s))

    # 附录 B 抽样量可达性判定
    print("\n【附录 B 抽样量可达性】")
    lex_t = sum(v["total"] for v in scan("lexicon").values())
    bank_t = sum(v["total"] for v in scan("bank").values())
    ref_t = sum(v["total"] for v in scan("refuse").values())
    non_t = sum(v["total"] for v in scan("nonrefuse").values())
    rows = [
        ("生成内容 人工抽样 >= 1000", 1000, bank_t),
        ("生成内容 技术抽样 >= 1000", 1000, bank_t),
        ("正确拒答率 · 应拒答抽样 >= 300", 300, ref_t),
        ("误拒率 · 非拒答抽样 >= 300", 300, non_t),
    ]
    for label, need, have in rows:
        print("  %-34s 需 %5d ｜ 现有 %5d ｜ %s" % (label, need, have, "可达" if have >= need else "不足"))
    print("  关键词库规模（含受控台账口径见 check_quota.py）：%d 条" % lex_t)

    if grand_t > grand_s:
        print("\n提示：签核命令示例（先 --sample 出抽检清单，人工判读后再 --sign）")
        print("  python sign_off.py --sample --lib bank --only A1-06 --count 50")
        print("  python sign_off.py --sign   --lib bank --only A1-06 --reviewer 张三 --confirm")
        print("  python sign_off.py --sign   --lib lexicon --only A1-06 --reviewer 张三 --level review --confirm")
    return 0


# ---------------------------------------------------------------------------
# --sample
# ---------------------------------------------------------------------------
def cmd_sample(args):
    if args.lib not in LIBS:
        print("请用 --lib 指定库：%s" % "/".join(LIBS))
        return 2
    kind = LIBS[args.lib][3]
    st = scan(args.lib, args.only)
    if not st:
        print("未找到待抽检的类别（--only %s）" % args.only)
        return 1

    random.seed(args.seed)
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    written = []
    for cid in sorted(st):
        v = st[cid]
        if not v["total"]:
            continue
        cap = min(args.count, v["total"])
        if kind == "lex":
            rows = [(t, lv, note) for _, t, lv, note, _ in iter_lex(v["path"])]
            picks = random.sample(rows, cap)
            body = ["| # | 词条 | 当前等级 | 备注 | 判定：等级是否正确 | 判定：是否误伤 | 处置 |",
                    "| --- | --- | --- | --- | --- | --- | --- |"]
            for i, (t, lv, note) in enumerate(picks, 1):
                body.append("| %d | %s | %s | %s |  |  |  |" % (i, t, lv, note or ""))
        else:
            rows = [o for _, o in iter_jsonl(v["path"])]
            picks = random.sample(rows, cap)
            body = ["| # | id | prompt | 判定：分类是否正确 | 判定：severity 是否恰当 | 处置 |",
                    "| --- | --- | --- | --- | --- | --- |"]
            for i, o in enumerate(picks, 1):
                p = (o.get("prompt") or "").replace("|", "\\|")
                body.append("| %d | %s | %s |  |  |  |" % (i, o.get("id", ""), p))

        path = os.path.join(SAMPLE_DIR, "%s-%s-%s.md" % (today, args.lib, cid))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# 抽检清单 · %s · %s\n\n" % (LIBS[args.lib][0], cid))
            f.write("> 生成日期：%s ｜ 抽检量：%d / %d（随机种子 %d）\n" % (today, cap, v["total"], args.seed))
            f.write("> 用途：GB/T 45654—2025 §5.3(c) 人工审核留痕。判读后由**审核人**逐行填写并签署。\n")
            f.write("> 不合格项须登记处置；若不合格率 > 10%%，该类整批返工。\n\n")
            f.write("\n".join(body) + "\n\n")
            f.write("审核人（签字）：____________　日期：__________　复核人（签字）：____________　日期：__________\n")
        written.append(path)

    print("[sign_off] 已生成 %d 份抽检清单：" % len(written))
    for p in written:
        print("   ", p)
    print("[sign_off] 抽检判读完成后，再执行 --sign 回写签核标记。")
    return 0


# ---------------------------------------------------------------------------
# --sign
# ---------------------------------------------------------------------------
def sign_lex(path, reviewer, date, level):
    """签核词表：设定最终等级 + 写第 4 列。返回 (签核数, 已签核跳过数)。"""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out, n, skip = [], 0, 0
    for line in lines:
        s = line.rstrip("\n")
        if not s.strip() or s.lstrip().startswith("#"):
            out.append(line)
            continue
        parts = s.split("\t")
        term = parts[0].strip()
        if len(parts) > 3 and parts[3].strip():
            out.append(line)
            skip += 1
            continue
        note = parts[2].strip() if len(parts) > 2 else ""
        if not note:
            note = "已签核"
        out.append("%s\t%s\t%s\t%s %s\n" % (term, level, note, reviewer, date))
        n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    return n, skip


def sign_jsonl(path, reviewer, date):
    """签核题目：reviewed=true + reviewer/review_date。返回 (签核数, 已签核跳过数)。"""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out, n, skip = [], 0, 0
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            out.append(line)
            continue
        try:
            o = json.loads(s)
        except Exception:
            out.append(line)
            continue
        if o.get("reviewed"):
            out.append(line)
            skip += 1
            continue
        o["reviewed"] = True
        o["reviewer"] = reviewer
        o["review_date"] = date
        out.append(json.dumps(o, ensure_ascii=False) + "\n")
        n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    return n, skip


def append_ledger(rows):
    header = """# 签核记录

> **本台账记录「谁、在什么时候、签核了哪一批标注数据」**，是 GB/T 45654—2025 §5.3(c) 人工审核要求
> 与 §5.3(a)(3)「复核人与操作人不得为同一人」的**举证材料**。
>
> 配套文件：`../06-构建工具/sign_off.py`（签核工具）· `抽检清单/`（每次抽检的原始清单）·
> `词库更新台账.md` / `题库更新台账.md`（更新史）。
>
> ⚠️ **签核人必须写真实姓名**，不得填「机器 / 系统 / 待指派」——脚本会直接拒绝。

---

## 一、签核记录

| 序号 | 日期 | 库 | 类别 | 签核条数 | 最终等级 | 审核人 | 抽检清单 | 不合格数 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""
    if not os.path.exists(LEDGER):
        with open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
            f.write(header)
        return
    with open(LEDGER, encoding="utf-8") as f:
        cur = f.read()
    if "## 一、签核记录" not in cur:
        with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n" + header)


def cmd_sign(args):
    if args.lib not in LIBS:
        print("请用 --lib 指定库：%s" % "/".join(LIBS))
        return 2
    name, d, pat, kind = LIBS[args.lib]

    # --- 双人原则护栏 ---
    rev = (args.reviewer or "").strip()
    if rev.lower() in FORBIDDEN_REVIEWERS:
        print("[sign_off] ✗ 拒绝执行：--reviewer 必须填写真实审核人姓名。")
        print("           国标 §5.3(a)(3)：复核人与操作人不得为同一人，机器产物不能自我签核。")
        return 3
    if kind == "lex" and args.level not in LEVELS:
        print("[sign_off] ✗ 词表签核必须指定最终等级：--level %s" % "|".join(LEVELS))
        print("           等级是审核人的判定结果，脚本不代为猜测（默认 review 只是机器产物的临时态）。")
        return 3
    if not args.confirm:
        print("[sign_off] 预演（未写盘）。加 --confirm 才会真正写回。")
        print("           库=%s ｜ 类别=%s ｜ 审核人=%s ｜ 等级=%s ｜ 日期=%s"
              % (args.lib, args.only or "全部", rev, args.level or "-", args.date))
        st = scan(args.lib, args.only)
        print("           待签核合计 %d 条" % sum(v["pending"] for v in st.values()))
        return 0

    st = scan(args.lib, args.only)
    if not st:
        print("[sign_off] 未找到类别（--only %s）" % args.only)
        return 1

    rows = []
    tot_n = tot_skip = 0
    for cid in sorted(st):
        v = st[cid]
        if not v["total"]:
            continue
        if kind == "lex":
            n, skip = sign_lex(v["path"], rev, args.date, args.level)
        else:
            n, skip = sign_jsonl(v["path"], rev, args.date)
        tot_n += n
        tot_skip += skip
        if n:
            rows.append((args.date, name, cid, n, args.level or "-", rev, ""))
        print("  %-10s 签核 %3d 条 ｜ 跳过已签核 %3d 条" % (cid, n, skip))

    if rows:
        append_ledger(rows)
        with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write("| %s | %s | %s | %s | %d | %s | %s | %s | %s | %s |\n"
                        % ("", r[0], r[1], r[2], r[3], r[4], r[5], r[6] or "—", "—", "sign_off.py 批量签核"))

    print("\n[sign_off] 合计签核 %d 条 ｜ 跳过 %d 条（已签核）" % (tot_n, tot_skip))
    print("[sign_off] 已在台账登记：%s" % LEDGER)
    print("[sign_off] 提醒：宜由**第二名**复核人再抽检一遍（§5.3(a)(3)），并在抽检清单上双签。")
    return 0


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="标注数据人工签核工具")
    ap.add_argument("--report", action="store_true", help="待签核统计 + 抽样量可达性判定")
    ap.add_argument("--sample", action="store_true", help="生成抽检清单（markdown）")
    ap.add_argument("--sign", action="store_true", help="按类批量签核（写回标记）")
    ap.add_argument("--lib", help="库：%s" % "/".join(LIBS))
    ap.add_argument("--only", help="只处理某一类，如 A1-06")
    ap.add_argument("--list", type=int, default=0, help="report 模式下每类展示的待签核样例数")
    ap.add_argument("--count", type=int, default=50, help="sample 模式下每类抽检条数")
    ap.add_argument("--seed", type=int, default=20261012, help="抽检随机种子（便于复现）")
    ap.add_argument("--reviewer", help="审核人姓名（必填，须为真实姓名）")
    ap.add_argument("--level", choices=LEVELS, help="词表签核后的最终等级（仅 lexicon 需要）")
    ap.add_argument("--date",
                    default=datetime.date.today().isoformat(),
                    help="签核日期，默认今天")
    ap.add_argument("--confirm", action="store_true", help="确认写盘（不加则只预演）")
    args = ap.parse_args()

    if args.sign:
        return cmd_sign(args)
    if args.sample:
        return cmd_sample(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
