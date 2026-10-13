#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_funnlp.py — 把 funNLP 原始词库加工为可用的合规辅助资产

来源：funNLP（github.com/fighting41love/funNLP），作者直接授权，详见 07-第三方词库源/作者授权登记.md
输入：09-合规资料库/07-第三方词库源/funNLP/
输出：09-合规资料库/01-关键词库/辅助词表/

设计要点
--------
1. 原始素材只读不改，加工产物另存，保证来源可追溯（国标 §5.1(c)）。
2. 幂等：重复运行结果一致，不会重复追加。
3. 全部为"辅助表"——不计入国标 10,000 词规模指标，只提升检测精度。
4. 白名单类产物仅作误拒控制，不得反向用于拦截。

用法
----
    python import_funnlp.py --dry-run     # 只看会生成什么
    python import_funnlp.py               # 落盘
    python import_funnlp.py --report      # 只打印各源文件统计
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 路径

ROOT = Path(__file__).resolve().parent.parent          # 09-合规资料库/
SRC = ROOT / "07-第三方词库源" / "funNLP"
OUT = ROOT / "01-关键词库" / "辅助词表"

SRC_STOP = SRC / "01-停用词"
SRC_CHAIZI = SRC / "02-拆字词库"
SRC_FANJIAN = SRC / "03-繁简转换"
SRC_MEANING = SRC / "04-同义词反义词否定词"
SRC_DOMAIN = SRC / "06-领域词表"


# ---------------------------------------------------------------- 工具


def read_text(path: Path) -> str:
    """读取文本，兼容 UTF-8(BOM) / GBK，并把 \\r 统一为 \\n。

    注意：funNLP 的 THUOCL_diming.txt 使用 \\r（旧 Mac 换行），
    不处理会得到 0 行 —— 这是本脚本必须处理的一个坑。
    """
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnicodeDecodeError(f"无法解码文件：{path}")
    # \r\n -> \n ；剩余孤立 \r -> \n
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    return txt


def iter_lines(path: Path):
    for line in read_text(path).split("\n"):
        yield line.rstrip("\n").rstrip()


def write_lines(path: Path, lines, header: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        if header:
            f.write(header)
        for ln in lines:
            f.write(ln + "\n")


# ---------------------------------------------------------------- 停用词

# 百度停用词表开头有大段说明文字与分隔线，不是停用词，必须剔除。
_STOP_JUNK = re.compile(
    r"(停用词列表|stop\s*words?\s*list|停止词列表|=====|-----|"
    r"都是在不断学习|也希望朋友|谢谢|保存|版权|更多|详见)"
)


def clean_stopword(raw_lines):
    """剔除文件头说明、空行、纯标点行，并去重。"""
    out, seen = [], set()
    for ln in raw_lines:
        w = ln.strip()
        if not w:
            continue
        if len(w) > 12:                      # 停用词不会这么长，说明是散文
            continue
        if _STOP_JUNK.search(w):
            continue
        if len(w) == 1 and not w.isalnum():
            continue                          # 单字符符号（如 $ / . ）
        if all(not ch.isalnum() for ch in w) and len(w) > 1:
            continue                          # 纯符号行
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def build_stopwords():
    stats, merged, seen = {}, [], set()
    for p in sorted(SRC_STOP.glob("*.txt")):
        raw = list(iter_lines(p))
        clean = clean_stopword(raw)
        stats[p.name] = {"原始行": len(raw), "清理后": len(clean)}
        for w in clean:
            if w not in seen:
                seen.add(w)
                merged.append(w)
    return merged, stats


# ---------------------------------------------------------------- 拆字 / 繁简


def build_chaizi():
    """字 \\t 部件1 部件2 …（取简体表）"""
    p = SRC_CHAIZI / "chaizi-jt.txt"
    rows, seen = [], set()
    for ln in iter_lines(p):
        if "\t" not in ln:
            continue
        parts = ln.split("\t")
        ch = parts[0].strip()
        if len(ch) != 1 or ch in seen:
            continue
        decomp = " ".join(x.strip() for x in parts[1:] if x.strip())
        if not decomp:
            continue
        seen.add(ch)
        rows.append(f"{ch}\t{decomp}")
    return rows


def build_fanjian():
    """简体 \\t 繁体（只保留真正有差异的映射）"""
    p = SRC_FANJIAN / "fanjian_suoyin.txt"
    rows, seen = [], set()
    for ln in iter_lines(p):
        if "\t" not in ln:
            continue
        a, _, b = ln.partition("\t")
        a, b = a.strip(), b.strip()
        if not a or not b or a == b or a in seen:
            continue
        seen.add(a)
        rows.append(f"{a}\t{b}")
    return rows


# ---------------------------------------------------------------- 同义词 / 否定词


def build_synonyms():
    """格式：编号= 词1 词2 词3 …（同组即同义）"""
    p = SRC_MEANING / "同义词库.txt"
    groups, terms = [], set()
    for ln in iter_lines(p):
        if "=" not in ln:
            continue
        _, _, body = ln.partition("=")
        ws = [w for w in body.split() if w]
        if len(ws) < 2:
            continue
        groups.append("\t".join(ws))
        terms.update(ws)
    return groups, terms


def build_negatives():
    """格式：否定词 \\t 0 \\t 序号 —— 取第一列。"""
    p = SRC_MEANING / "否定词库.txt"
    out, seen = [], set()
    for ln in iter_lines(p):
        w = ln.split("\t")[0].strip()          # 源文件含频次列，只取词
        if not w or len(w) > 12 or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


# ---------------------------------------------------------------- 领域白名单

_DOMAIN_NAMES = {
    "THUOCL_law.txt": "法律",
    "THUOCL_medical.txt": "医学",
    "THUOCL_animal.txt": "动物",
    "THUOCL_lishimingren.txt": "历史名人",
    "THUOCL_it.txt": "IT",
    "THUOCL_poem.txt": "诗词",
    "THUOCL_diming.txt": "地名",
    "THUOCL_chengyu.txt": "成语",
    "THUOCL_food.txt": "食物",
    "THUOCL_caijing.txt": "财经",
    "THUOCL_car.txt": "汽车",
    "professions.txt": "职业",
}


def build_domain():
    """THUOCL 格式：词 \\t 词频；professions.txt 为一行一词。"""
    result, stats = {}, {}
    for p in sorted(SRC_DOMAIN.glob("*.txt")):
        label = _DOMAIN_NAMES.get(p.name, p.stem)
        words, seen = [], set()
        for ln in iter_lines(p):
            if not ln or ln.startswith("#"):
                continue
            w = ln.split("\t")[0].strip()
            if not w or w in seen:
                continue
            seen.add(w)
            words.append(w)
        result[label] = words
        stats[label] = len(words)
    return result, stats


# ---------------------------------------------------------------- 主流程

HEADER = (
    "# 本文件由 06-构建工具/import_funnlp.py 自动生成，请勿手工编辑。\n"
    "# 来源：funNLP（github.com/fighting41love/funNLP），作者直接授权。\n"
    "# 生成时间：{ts}\n"
    "# 性质：辅助表，不计入国标 10,000 词规模指标。\n"
    "{extra}"
)


def main():
    ap = argparse.ArgumentParser(description="funNLP 词库加工")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不落盘")
    ap.add_argument("--report", action="store_true", help="只打印各源文件统计")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"[×] 未找到来源目录：{SRC}")
        print("    请先确认 07-第三方词库源/funNLP/ 已就位。")
        return 1

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 66)
    print("funNLP 词库加工")
    print(f"来源：{SRC}")
    print(f"输出：{OUT}")
    print(f"模式：{'预览（不落盘）' if args.dry_run else '正式落盘'}")
    print("=" * 66)

    # ---- 1 停用词
    stops, stop_stats = build_stopwords()
    print("\n[1/6] 停用词")
    for name, s in stop_stats.items():
        print(f"      {name:<24} 原始 {s['原始行']:>5} → 清理后 {s['清理后']:>5}")
    print(f"      {'合并去重':<24} {len(stops):>5} 条")

    # ---- 2 拆字
    chaizi = build_chaizi()
    print(f"\n[2/6] 拆字表            {len(chaizi):>5} 条（简体）")

    # ---- 3 繁简
    fanjian = build_fanjian()
    print(f"[3/6] 繁简对照表        {len(fanjian):>5} 条（有差异的映射）")

    # ---- 4 同义词
    syn_groups, syn_terms = build_synonyms()
    print(f"[4/6] 同义词组          {len(syn_groups):>5} 组 / {len(syn_terms):>6} 个词")

    # ---- 5 否定词
    negs = build_negatives()
    print(f"[5/6] 否定词表          {len(negs):>5} 条")

    # ---- 6 领域白名单
    domain, domain_stats = build_domain()
    total_domain = sum(domain_stats.values())
    print(f"[6/6] 领域白名单         {total_domain:>5} 条 / {len(domain)} 个领域")
    for label, n in domain_stats.items():
        print(f"      {label:<10} {n:>6}")

    if args.report:
        return 0

    if args.dry_run:
        print("\n" + "=" * 66)
        print("预览结束。加 --report 只看统计；不加参数即正式落盘。")
        return 0

    # ---------------- 落盘
    print("\n正在落盘 …")

    write_lines(OUT / "停用词表.txt", stops,
                header=HEADER.format(ts=ts, extra="# 合并：中文停用词库 / 哈工大 / 四川大学 / 百度（已剔除文件头说明）\n"))

    write_lines(OUT / "拆字表.tsv", chaizi,
                header=HEADER.format(ts=ts, extra="# 格式：字\t部件1 部件2 …　用途：拆字变体生成\n"))

    write_lines(OUT / "繁简对照表.tsv", fanjian,
                header=HEADER.format(ts=ts, extra="# 格式：简体\t繁体　用途：繁体变体生成\n"))

    write_lines(OUT / "同义词组.tsv", syn_groups,
                header=HEADER.format(ts=ts, extra="# 格式：词1\t词2\t词3 …（同组即同义）\n# ⚠️ 同义变体一律标 review 级，须人工复核，不得自动升为 block。\n"))

    write_lines(OUT / "否定词表.txt", negs,
                header=HEADER.format(ts=ts, extra="# 用途：否定语境判定（「反对暴力」不应被拦），降误拒\n"))

    for label, words in domain.items():
        write_lines(OUT / "白名单-领域词表" / f"{label}.txt", words,
                    header=HEADER.format(ts=ts, extra=f"# 领域：{label}　用途：误拒白名单（不得反向用于拦截）\n"))

    # ---------------- 加工清单
    manifest = {
        "来源": "funNLP",
        "仓库": "https://github.com/fighting41love/funNLP",
        "授权方式": "作者直接授权（非开源许可证）",
        "授权登记": "../07-第三方词库源/作者授权登记.md",
        "生成时间": ts,
        "生成脚本": "06-构建工具/import_funnlp.py",
        "性质": "辅助表——不计入国标 10000 词规模指标，仅提升检测精度",
        "产物": {
            "停用词表.txt": {"条数": len(stops), "用途": "匹配前置过滤，降误拒"},
            "拆字表.tsv": {"条数": len(chaizi), "用途": "拆字变体生成"},
            "繁简对照表.tsv": {"条数": len(fanjian), "用途": "繁体变体生成"},
            "同义词组.tsv": {"组数": len(syn_groups), "词数": len(syn_terms), "用途": "同义变体候选（须人工复核）"},
            "否定词表.txt": {"条数": len(negs), "用途": "否定语境判定"},
            "白名单-领域词表": {"领域数": len(domain), "条数": total_domain, "用途": "误拒白名单"},
        },
    }
    mpath = OUT / "funnlp_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[✓] 完成。产物目录：{OUT}")
    print(f"    加工清单：{mpath.name}")
    print("\n    提示：辅助表不计入国标规模指标。达标仍需扩充违规词条本身。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
