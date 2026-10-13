# -*- coding: utf-8 -*-
"""
import_external.py — 从外部开源词库导入词条并归类到 GB/T 45654 附录 A 的 31 类

前置：
    1. 已按 04-开源资源索引/开源词库资源.md 获取词库到本地目录（本脚本不联网下载）
    2. 已确认该词库的许可证允许本项目使用，并留存 LICENSE

流程：
    读取外部 .txt 词库 → 清理 → 去重 → 启发式归类 → 写入各分类词表（追加）→ 生成导入报告

⚠️ 重要：
    归类为启发式规则，**仅作初筛**。导入后必须人工复核（每类抽 20 条），
    并逐条检查是否会造成误拒（国标限误拒率 <= 5%）。

用法：
    python import_external.py --src <外部词库目录> [--dry-run] [--tag <来源标识>]
    python import_external.py --src ./ext/Sensitive-lexicon/Vocabulary --tag Sensitive-lexicon
"""

import os
import re
import sys
import json
import glob
import argparse
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEX_DIR = os.path.join(ROOT, "01-关键词库")
VOCAB_DIR = os.path.join(LEX_DIR, "词表")
REPORT = os.path.join(LEX_DIR, "导入报告.json")

# ---------------------------------------------------------------- 归类规则
# 顺序敏感：先匹配到的生效。均为启发式，必须人工复核。
RULES = [
    # A.1
    (r"恐|极端|炸弹|炸药|袭击|圣战|暴恐|恐怖", "A1-04"),
    (r"谣|不实|伪造|假消息|假新闻|虚构事实", "A1-07"),
    (r"赌|毒|枪|违禁|走私|假证|代开|私彩|彩票|博彩", "A1-08"),
    (r"血|尸|杀|砍|斩|刺|割|虐|屠|斩首|开膛|断肢|剥皮|肉|暴|复仇|鞭尸",
     "A1-06"),
    (r"色情|淫|裸|情色|嫖|性行为|性器官|胸|臀|阴道|阴茎", "A1-06"),
    # A.2（须细分，顺序在 A.1 之后）
    (r"民族|族|种族|汉奸|韃", "A2-01"),
    (r"信仰|宗教|教派|邪教|迷信|神棍", "A2-02"),
    (r"外国|洋人|老外|国别|洋奴|境外", "A2-03"),
    (r"地域|省籍|某地|乡下|外地|土鳖|农民", "A2-04"),
    (r"女|男|性别|婊|娘|妇|性别歧视", "A2-05"),
    (r"老|幼|年龄|岁|小|年长", "A2-06"),
    (r"职业|工种|工作|打工|环卫|外卖|快递", "A2-07"),
    (r"残|废|病|疾|瘸|聋|哑|盲|精神病|智障", "A2-08"),
    # A.3
    (r"盗版|抄袭|洗稿|侵权|搬运|著作权|版权", "A3-01"),
    (r"虚假宣传|刷单|刷量|水军|差评", "A3-02"),
    (r"商业秘密|机密|内部资料|客户名单", "A3-03"),
    (r"垄断|不正当竞争|二选一|排他|恶意收购", "A3-04"),
    # A.4
    (r"自杀|自残|自伤|抑郁|减肥|节食|暴食|厌食|轻生", "A4-01"),
    (r"换脸|肖像|明星脸|deepfake|AI换脸", "A4-02"),
    (r"诽谤|名誉|中伤|抹黑|造谣中伤", "A4-03"),
    (r"英烈|烈士|英雄|荣誉|先烈", "A4-04"),
    (r"隐私|人肉|开盒|偷拍|跟踪|扒|定位", "A4-05"),
    (r"个人信息|手机号|身份证|银行卡|住址|数据爬取|倒卖", "A4-06"),
    (r"骚扰|恐吓|威胁|跟踪骚扰", "A4-07"),
]


def classify(word):
    """启发式归类，返回类别编号或 None。"""
    for pat, cid in RULES:
        if re.search(pat, word):
            return cid
    return None


def load_id_map():
    with open(os.path.join(LEX_DIR, "lexicon_manifest.json"), encoding="utf-8") as f:
        mf = json.load(f)
    return {c["id"]: c for c in mf["categories"]}


def read_words(src):
    """递归读取目录下所有 .txt（含无扩展名词库文件），返回词条集合。"""
    words = set()
    files = []
    for root, _dirs, names in os.walk(src):
        for n in names:
            if n.lower().endswith(".txt") or n.lower().endswith(".csv"):
                files.append(os.path.join(root, n))
    for fp in files:
        with open(fp, encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                # 兼容 `词,等级` 或 `词\t等级` 形式
                s = re.split(r"[,\t]", s)[0].strip()
                if s and len(s) <= 50:
                    words.add(s)
    return words, files


def main():
    ap = argparse.ArgumentParser(description="从外部开源词库导入词条并归类")
    ap.add_argument("--src", required=True, help="外部词库目录")
    ap.add_argument("--tag", default="external", help="来源标识，写入词条备注")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    ap.add_argument("--min-cert", type=int, default=2, help="纳入导入的最小词长（默认2）")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print("[错误] 目录不存在：%s" % args.src)
        return 2

    id_map = load_id_map()
    words, files = read_words(args.src)
    print("[import_external] 扫描 %d 个文件，读取 %d 个去重词条" % (len(files), len(words)))

    buckets = collections.defaultdict(list)
    unclassified = []
    for w in sorted(words):
        if len(w) < args.min_cert:
            continue
        cid = classify(w)
        if cid and cid in id_map:
            buckets[cid].append(w)
        else:
            unclassified.append(w)

    print("[import_external] 归类结果：")
    for cid in sorted(buckets):
        print("    %-8s %-30s %d 条" % (cid, id_map[cid]["name"][:28], len(buckets[cid])))
    print("[import_external] 未归类：%d 条（须人工处理）" % len(unclassified))

    report = dict(source=args.src, tag=args.tag, files=len(files),
                  total_words=len(words), buckets={k: len(v) for k, v in buckets.items()},
                  unclassified_count=len(unclassified),
                  unclassified_sample=unclassified[:200])

    if args.dry_run:
        print("[import_external] --dry-run，未写入文件")
        return 0

    # 写入各分类词表（追加，带来源与等级标注）
    appended = 0
    for cid, ws in buckets.items():
        cat = id_map[cid]
        path = os.path.join(VOCAB_DIR, cat["file"])
        if not os.path.exists(path):
            print("    [跳过] 找不到词表文件：%s" % path)
            continue
        with open(path, encoding="utf-8") as f:
            existing = f.read()
        new = [w for w in ws if ("\n%s\t" % w) not in ("\n" + existing) and w not in existing]
        if not new:
            continue
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n# ===== 导入自 %s（%s）=====\n" % (args.tag, args.src))
            for w in new:
                f.write("%s\treview\t来源:%s\n" % (w, args.tag))
        appended += len(new)

    with open(REPORT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[import_external] 追加写入 %d 条（全部标 review 级，须人工复核）" % appended)
    print("[import_external] 导入报告：%s" % REPORT)
    print("[import_external] 下一步：")
    print("    1) 人工复核归类质量（每类抽 20 条）")
    print("    2) 剔除误伤词（国标限误拒率 <= 5%）")
    print("    3) 运行 check_quota.py 与 report_coverage.py")
    print("    4) 在 05-台账与制度/词库更新台账.md 登记")
    return 0


if __name__ == "__main__":
    sys.exit(main())
