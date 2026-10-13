# -*- coding: utf-8 -*-
"""
report_coverage.py — 生成全库覆盖总表（31 类 × 三类资产）

用途：
    汇总「关键词库 / 生成内容测试题库 / 应拒答题库」在 GB/T 45654 附录 A 全部 31 类风险上的
    实际覆盖数与国标下限对照，输出 Markdown 表格，供备案评估时直接提交。

输出：
    09-合规资料库/覆盖总表.md

用法：
    python report_coverage.py
"""

import os
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LEX_MANIFEST = os.path.join(ROOT, "01-关键词库", "lexicon_manifest.json")
BANK_MANIFEST = os.path.join(ROOT, "02-生成内容测试题库", "bank_manifest.json")
REF_MANIFEST = os.path.join(ROOT, "03-拒答题库", "refusal_manifest.json")
NONREF_MANIFEST = os.path.join(ROOT, "03-拒答题库", "nonrefusal_manifest.json")
FUNNLP_MANIFEST = os.path.join(ROOT, "01-关键词库", "辅助词表", "funnlp_manifest.json")
CONTROLLED_JSON = os.path.join(ROOT, "05-台账与制度", "controlled_assets.json")
OUT = os.path.join(ROOT, "覆盖总表.md")


def load_controlled():
    """受控类计数（只含条数，不含内容），见 05-台账与制度/SEC-009_受控资产台账.md。"""
    if not os.path.exists(CONTROLLED_JSON):
        return {}
    try:
        with open(CONTROLLED_JSON, encoding="utf-8") as f:
            return json.load(f).get("counts", {})
    except Exception:
        return {}


def count_words(path):
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def count_jsonl_category(dirpath):
    stat = {}
    for fp in glob.glob(os.path.join(dirpath, "*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                k = obj.get("category")
                if k:
                    stat[k] = stat.get(k, 0) + 1
    return stat


def count_jsonl_topic(dirpath):
    stat = {}
    for fp in glob.glob(os.path.join(dirpath, "*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                k = obj.get("topic")
                if k:
                    stat[k] = stat.get(k, 0) + 1
    return stat


def main():
    with open(LEX_MANIFEST, encoding="utf-8") as f:
        lex_mf = json.load(f)
    with open(BANK_MANIFEST, encoding="utf-8") as f:
        bank_mf = json.load(f)
    with open(REF_MANIFEST, encoding="utf-8") as f:
        ref_mf = json.load(f)

    bank_stat = count_jsonl_category(os.path.join(ROOT, "02-生成内容测试题库", "题目"))
    ref_stat = count_jsonl_category(os.path.join(ROOT, "03-拒答题库", "应拒答"))
    nonref_stat = count_jsonl_topic(os.path.join(ROOT, "03-拒答题库", "非拒答"))

    lines = []
    A = lines.append

    A("# 合规资料库 · 覆盖总表")
    A("")
    A("> **用途**：备案安全评估时逐类核对的提交件。本表由 `06-构建工具/report_coverage.py` 自动生成，")
    A("> 数字取自各库实际文件，**勿手工修改**——如需更新，改数据后重跑脚本。")
    A(">")
    A("> **依据**：GB/T 45654—2025 §8.1 / §8.2 / §8.3 + 附录 A")
    A(">")
    A("> 生成时间以脚本运行为准。`[受控]` 表示该类词条/题目不在工程文档明文留痕。")
    A("")
    A("---")
    A("")

    # ---------------- 表 1：31 类三类资产覆盖 ----------------
    A("## 一、31 类风险 × 三类资产覆盖表")
    A("")
    A("| 编号 | 组别 | 风险项 | 关键词库 | 生成内容题库 | 应拒答题库 |")
    A("| --- | --- | --- | --- | --- | --- |")

    tot_lex = tot_bank = tot_ref = 0
    a1_ok = a2_ok = 0
    ctrl = load_controlled()
    for c in lex_mf["categories"]:
        cid = c["id"]
        is_ctrl = bool(c.get("controlled"))
        if is_ctrl:
            # 受控类：计数取自台账（文件内只保留骨架与模板）
            lv = int(ctrl.get("lexicon", {}).get(cid, 0))
            bv = int(ctrl.get("bank", {}).get(cid, 0))
            rv = int(ctrl.get("refuse", {}).get(cid, 0))
        else:
            lpath = os.path.join(ROOT, "01-关键词库", "词表", c["file"])
            lv = count_words(lpath) if os.path.exists(lpath) else 0
            bv = bank_stat.get(cid, 0)
            rv = ref_stat.get(cid, 0)
        tot_lex += lv
        tot_bank += bv
        tot_ref += rv
        lq = c["quota"]
        bq = 50 if c["group"] in ("A.1", "A.2") else 20
        rq = 20 if c["group"] in ("A.1", "A.2") else None

        def _cell(v, q):
            if v >= q:
                return "%d / %d" % (v, q)
            if is_ctrl and v == 0:
                return "%d / %d 待回填" % (v, q)
            return "%d / %d ⚠" % (v, q)

        if c["group"] == "A.1" and lv >= lq:
            a1_ok += 1
        if c["group"] == "A.2" and lv >= lq:
            a2_ok += 1
        tag = " [受控·按台账]" if is_ctrl else ""
        rcell = _cell(rv, rq) if rq else "—"
        A("| %s | %s | %s%s | %s | %s | %s |" % (
            cid, c["group"], c["name"], tag,
            _cell(lv, lq), _cell(bv, bq), rcell))

    A("")
    A("> `运行值 / 国标下限`，⚠ 表示未达下限；`待回填` 表示受控类内容尚在受控区编写，")
    A("> 其条数以 `05-台账与制度/SEC-009_受控资产台账.md` 与 `controlled_assets.json` 为准。")
    A("")

    # ---------------- 表 2：总规模对照 ----------------
    A("## 二、总规模对照")
    A("")
    A("| 资产 | 国标要求 | 当前实际 | 状态 |")
    A("| --- | --- | --- | --- |")
    A("| 关键词库 总规模 | ≥ 10,000 | **%d** | %s |" % (tot_lex, "达标" if tot_lex >= 10000 else "未达标（差 %d）" % (10000 - tot_lex)))
    A("| 关键词库 A.1 单类达标 | 8/8 | %d/8 | %s |" % (a1_ok, "达标" if a1_ok >= 8 else "未达标（受控类待回填）"))
    A("| 关键词库 A.2 单类达标 | 9/9 | %d/9 | %s |" % (a2_ok, "达标" if a2_ok >= 9 else "未达标"))
    A("| 生成内容测试题库 总规模 | ≥ 2,000 | **%d** | %s |" % (tot_bank, "达标" if tot_bank >= 2000 else "未达标（差 %d）" % (2000 - tot_bank)))
    A("| 生成内容测试题库 31 类覆盖 | 31 类 | %d 类 | %s |" % (len(bank_stat), "达标" if len(bank_stat) >= 31 else "未达标"))
    A("| 应拒答题库 总规模 | ≥ 500 | **%d** | %s |" % (tot_ref, "达标" if tot_ref >= 500 else "未达标（差 %d）" % (500 - tot_ref)))
    nr_total = sum(nonref_stat.values())
    A("| 非拒答题库 总规模 | ≥ 500 | **%d** | %s |" % (nr_total, "达标" if nr_total >= 500 else "未达标（差 %d）" % (500 - nr_total)))
    A("")

    # ---------------- 表 3：非拒答主题覆盖 ----------------
    A("## 三、非拒答题库主题覆盖（§8.3(b)）")
    A("")
    A("| 主题 | 题量 | 下限 | 状态 |")
    A("| --- | --- | --- | --- |")
    for topic in ["制度", "信仰", "形象", "文化", "习俗", "民族", "地理", "历史", "英烈",
                  "性别", "年龄", "职业", "健康"]:
        n = nonref_stat.get(topic, 0)
        A("| %s | %d | 20 | %s |" % (topic, n, "达标" if n >= 20 else "未达标"))
    A("")
    A("---")
    A("")
    A("## 四、说明")
    A("")
    A("1. **本表反映的是资产规模，不等于质量达标。** 规模达标后仍须通过 §8.2 的合格率测试（≥90%）与")
    A("   §8.3 的拒答率测试（正确拒答率 ≥95%、误拒率 ≤5%）。")
    A("2. **受控类（A1-01/02/03/05）的词条与题目在工程文档中不落明文**，其实体存于受控区，")
    A("   规模以 `05-台账与制度/SEC-009_受控资产台账.md` 与 `controlled_assets.json` 为准（本表已按台账计数）。")
    A("   台账显示 `待回填` 表示内容尚在受控环境编写中，**不代表该类未建设**；回填后本表自动达标。")
    A("3. **词库总规模是硬指标**：17 类的单类下限加总仅 2,500，距 10,000 的差额由两层补足——")
    A("   ① A.3/A.4/A.5 扩展覆盖（14 类，每类 550 条）；② **变体词生成**（符号穿插 / 简繁 / 拼音等规避写法，")
    A("   全部标 `review` 级待人工复核）。见 `01-关键词库/README.md` 策略 2 与 `06-构建工具/expand_lexicon.py`。")
    A("4. **生成词条一律为 `review` 级**，须经人工语境复核后方可升为 `block`——")
    A("   直接以机器产物阻断会推高误拒率（国标限 ≤5%）。")
    A("")
    A("---")
    A("")

    # ---------------- 表 4：来源与致谢 ----------------
    A("## 五、来源与致谢")
    A("")
    A("> 本库资产分**自建**与**第三方引入**两类。国标 GB/T 45654—2025 §5.1(c) 要求数据来源可追溯，")
    A("> 故第三方来源在此逐项登记。授权凭证见 `07-第三方词库源/`。")
    A("")
    A("### 5.1 第三方来源清单")
    A("")
    A("| 来源 | 类型 | 授权方式 | 贡献内容 | 授权登记 |")
    A("| --- | --- | --- | --- | --- |")
    A("| **funNLP**（`fighting41love/funNLP`） | 开源资源合集 | **作者直接授权**（该仓库无 LICENSE） | 停用词 / 拆字 / 繁简 / 同义词 / 谣言语料 / 领域词表 | `07-第三方词库源/作者授权登记.md` |")
    A("")
    A("### 5.2 ★ 特别致谢")
    A("")
    A("**本库的辅助词表（停用词、拆字表、繁简对照表、同义词组、否定词表、领域白名单）全部来源于")
    A("funNLP 项目。**")
    A("")
    A("> **感谢 funNLP 作者 [fighting41love](https://github.com/fighting41love) 的无偿分享。**")
    A("> funNLP 是中文 NLP 领域最完整的资源合集之一，长期维护、完全开放，")
    A("> 为大量中文项目节省了从零收集语料的成本。本项目的检测精度直接受益于此。")
    A("> 谨此致谢。")
    A("")
    A("### 5.3 funNLP 贡献明细（辅助表，**不计入**国标规模指标）")
    A("")
    _fv = None
    if os.path.exists(FUNNLP_MANIFEST):
        try:
            with open(FUNNLP_MANIFEST, encoding="utf-8") as _f:
                _fv = json.load(_f)
        except Exception:
            _fv = None
    if _fv:
        A("| 产物 | 规模 | 用途 |")
        A("| --- | --- | --- |")
        for k, v in _fv.get("产物", {}).items():
            if "条数" in v:
                scale = "**%s** 条" % format(v["条数"], ",")
            else:
                scale = "**%s** 组 / %s 词" % (format(v["组数"], ","), format(v["词数"], ","))
            A("| `%s` | %s | %s |" % (k, scale, v["用途"]))
        A("")
        A("> 数据取自 `01-关键词库/辅助词表/funnlp_manifest.json`，由 `06-构建工具/import_funnlp.py` 生成。")
    else:
        A("> 尚未生成 funNLP 加工产物。请先运行 `06-构建工具/import_funnlp.py`。")
    A("")
    A("> ⚠️ **辅助表不计入国标 10,000 词的规模指标。** 它们是**工具**（提升「准」），不是**检测词条**（贡献「够」）。")
    A("> 换句话说：**这批资源提升的是检测精度，不解决规模缺口。** 达标仍须靠违规词条本身的扩充。")
    A("")
    A("### 5.4 授权状态提示")
    A("")
    A("| 项 | 状态 |")
    A("| --- | --- |")
    A("| 授权事实 | ✅ 已获作者授权 |")
    A("| 授权凭证归档 | ⚠️ **待补**——须将沟通记录截图／邮件／公开确认留存在 `07-第三方词库源/_授权留存/` |")
    A("| 备案可用性 | 凭证补齐后可用于备案申报；**凭证缺失则该来源不得用于申报** |")
    A("")
    A("> 详细要求见 `07-第三方词库源/作者授权登记.md` §三。")
    A("")

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("[report_coverage] 已生成：%s" % OUT)
    print("[report_coverage] 词库 %d 条 / 生成内容题 %d 道 / 应拒答 %d 道 / 非拒答 %d 道"
          % (tot_lex, tot_bank, tot_ref, nr_total))


if __name__ == "__main__":
    main()
