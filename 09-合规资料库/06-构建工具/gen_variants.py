# -*- coding: utf-8 -*-
"""
gen_variants.py — 为词库生成规避变体（词库规模扩充的主力手段）

原理：
    违规内容常以变体形态规避关键词匹配，例如「血腥」写作「xuexing」「血惺」「血*腥」。
    为每个基础词生成其常见变体，可显著提升词库的召回能力。

生成的变体类型：
    1. 拼音全拼 / 首字母        （需安装 pypinyin，未安装时自动降级跳过）
    2. 符号穿插                 （血*腥 / 血-腥 / 血 腥）
    3. 空格分隔                 （血 腥）
    4. 简繁转换                 （需 opencc，未安装时跳过）

⚠️ 重要：
    变体词**全部标记为 review 级**，不得标 block。
    原因：变体匹配误伤率高，必须经人工语境判断，否则会推高误拒率（国标限 <= 5%）。

用法：
    python gen_variants.py                    # 处理全部词表
    python gen_variants.py --only A1-06       # 只处理指定类别
    python gen_variants.py --dry-run          # 只统计不写入
"""

import os
import re
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VOCAB_DIR = os.path.join(ROOT, "01-关键词库", "词表")

try:
    from pypinyin import lazy_pinyin, Style  # type: ignore
    HAS_PINYIN = True
except Exception:
    HAS_PINYIN = False

try:
    from opencc import OpenCC  # type: ignore
    HAS_OPENCC = True
    _cc = OpenCC("s2t")
except Exception:
    HAS_OPENCC = False
    _cc = None

INSERT_CHARS = ["*", "-", ".", "·", " ", "/", "+"]


def variants(word):
    """生成单个词的变体集合。"""
    out = set()
    w = word.strip()
    if len(w) < 2 or not re.search(r"[\u4e00-\u9fff]", w):
        return out
    if len(w) > 6:      # 长词不生成变体，避免爆炸式增长
        return out

    # 1. 拼音
    if HAS_PINYIN:
        full = "".join(lazy_pinyin(w))
        first = "".join(lazy_pinyin(w, style=Style.FIRST_LETTER))
        if len(full) > 1:
            out.add(full)
        if len(first) > 1:
            out.add(first)

    # 2. 符号穿插
    for ch in INSERT_CHARS:
        out.add(ch.join(list(w)))

    # 3. 单点插入（中间加一个符号）
    for ch in ["*", "-", "."]:
        mid = len(w) // 2
        out.add(w[:mid] + ch + w[mid:])

    # 4. 简繁
    if HAS_OPENCC:
        t = _cc.convert(w)
        if t != w:
            out.add(t)

    # 去掉与自身相同、以及纯符号
    out.discard(w)
    return {x for x in out if x.strip() and x != w}


def read_words(path):
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            w = re.split(r"[\t,]", s)[0].strip()
            if w:
                words.append(w)
    return words


def main():
    ap = argparse.ArgumentParser(description="生成词库规避变体")
    ap.add_argument("--only", help="只处理指定类别编号，如 A1-06")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("[gen_variants] pypinyin: %s ｜ opencc: %s" % (
        "可用" if HAS_PINYIN else "未安装（跳过拼音变体）",
        "可用" if HAS_OPENCC else "未安装（跳过简繁变体）"))

    total_new = 0
    for name in sorted(os.listdir(VOCAB_DIR)):
        if not name.endswith(".txt"):
            continue
        cid = name.split("-")[0] + "-" + name.split("-")[1]
        if args.only and cid != args.only:
            continue
        path = os.path.join(VOCAB_DIR, name)

        with open(path, encoding="utf-8") as f:
            content = f.read()
        existing = set(read_words(path))

        new = set()
        for w in existing:
            new |= variants(w)
        new -= existing

        # 只保留在库中尚不存在的
        new = {x for x in new if ("\t%s\t" % x) not in content and x not in existing}

        if not new:
            continue
        total_new += len(new)
        print("    %-60s +%d 条" % (name[:58], len(new)))

        if args.dry_run:
            continue
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n# ===== 自动生成变体（全部 review 级，须人工复核语境）=====\n")
            for x in sorted(new):
                f.write("%s\treview\t变体词\n" % x)

    print("[gen_variants] 共生成 %d 条变体%s" % (total_new, "（未写入）" if args.dry_run else ""))
    if total_new and not args.dry_run:
        print("[gen_variants] 下一步：人工复核变体质量，剔除误伤词，再运行 check_quota.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
