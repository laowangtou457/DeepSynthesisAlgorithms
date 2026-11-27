#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX 框架库 · Genre Profile 机械 gate  v2.0.0（零第三方依赖，Python 标准库 only）

用法：
    python check_profile_gate.py <profile.json> --baseline 90 [--registry style_refs.json]

定位：
    只做「可机械复算」的判据，不判断内容好坏。
    当前服务于 M1-01 金标准评审；F5 正式可生成性门另立（FX-060）。
    依据：FX-000 三条铁律、FX-030 §三注入点 / §五 R-S1~R-S7 / §七字段规范。

v2.0.0（2026-11-25，P0-1 重写）：
    依据 _评审报告_R1按标准执行_2026-11-25.md §2.2 的 15 组变体探针 + §6 P0-1，
    修复 8 类漏检/误杀。逐条对应关系见各判据的 [探针] 标注。
    本版判据正确性由 schema/tests/run_regression.py 的 A0~A17 回归用例固化。
    改动摘要：
      P01 双向白名单（A6）        P03 状态机枚举（A1）
      P07 --baseline 必填（A13）  P08 重写为命名空间隔离（A3/A4/A10）
      P09 >= 而非 ==（A2/L-09）   P10/P11 覆盖 hooks.extra（A14/A15）
      P13 校验 redlines.code（A11）P14 查 style_refs 注册表（A7）
      P15 铁律二/R-S6 改 FAIL 且按字段扫描（A8/A9）
      P17 无 U| 行按 K-03 判 FAIL（A12）

判据等级：
    PASS 通过 / FAIL 必打回 / WARN 需人判
    提交评审准入：FAIL == 0 且 WARN == 0（v2 起 WARN 也必须清零）

边界声明（重要，避免越权代判）：
    · 档案层 JSON 无 scenes[].hook_code 字段；R-S3/R-S4 要求的
      「hook_code ∈ hooks.open/close[].code」是剧本产物层（F2 门）的职责，
      本 gate 不越权代判。P08 只校验档案侧能判的：首拍 ≤3s、
      节拍码格式合法、节拍码与钩子码命名空间不相交。
      （旧 P08 查 beat_sheet.code 含 "OPEN"/"CLOSE" 字样，导致 A3 误杀、A4 放行。）
    · approved + unverified 组合的状态机语义属 L-03（P1），本 gate 不判。
    · STYLE_REGISTRY 是 fx_framework.yaml §六 style_refs 的镜像；骨架升版须同步，
      或用 --registry 传入派生 JSON {"CODE": "registered", ...} 覆盖。
"""
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- 骨架字段（FX-030 §七 + fx_framework.yaml profile_template） ---
TOP_FIELDS = [
    "genre_id", "name", "status", "verification", "beat_sheet",
    "hooks", "payoff", "cast", "line", "style_bible_ref",
    "asset_bias", "redlines", "adapt", "evidence",
]
NESTED = {
    "hooks": ["open", "close", "extra"],
    "payoff": ["min_per_ep", "escalate_every_s"],
    "cast": ["max_speaking", "max_on_screen"],
    "line": ["max_chars", "char_per_sec", "tone_codes", "banned"],
    "asset_bias": ["prop_focus", "scene_pool"],
    "adapt": ["chars_per_ep", "keep", "merge", "rewrite"],
}
REDLINE_KEYS = ["code", "rule", "fallback"]
HOOK_KEYS = ["code", "name", "formula", "sample_line"]
BEAT_KEYS = ["at_s", "dur_s", "code", "purpose", "is_payoff"]
STATUS_ENUM = {"skeleton", "draft", "approved"}
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# 画风锚注册表：fx_framework.yaml §六 style_refs 的镜像（见文件头边界声明）
STYLE_REGISTRY = {
    "STY-KR-WEBTOON": "registered",
    "STY-FINE-FEMALE": "registered",
    "STY-SHINKAI": "registered",
    "STY-DARK-REAL": "registered",
    "STY-GUOCHAO": "registered",
    "STY-RETRO": "registered",
}

# 不可校验表述（FX-000 铁律二）
ADJECTIVE_RE = re.compile(
    r"节奏明快|节奏紧凑|氛围压抑|情绪饱满|画风高级|高级感|震撼|"
    r"张力十足|行云流水|扣人心弦|淋漓尽致|细腻动人|极具|富有张力"
)
# 心理动词（FX-030 R-S6）
MENTAL_RE = re.compile(r"想|觉得|心里|心中|暗自|不禁|仿佛|意识到|感到|明白过来")

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def rec(level, code, msg):
    results.append((level, code, msg))


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def content_strings(d):
    """会流进剧本产物画面/台词的「参数取值」字段 → [(路径, 文本)]。

    刻意排除以下三类（含禁用词字面属正常，扫了会误杀）：
      redlines[].rule  —— 禁用词清单的元描述（如 RL_04 明写「禁止出现：想/觉得/心里」）
      line.banned      —— 禁用词清单本身
      evidence         —— 参数依据说明，不是参数取值
    覆盖：beat_sheet / hooks.* 全键 / redlines.code+fallback / asset_bias /
          line.tone_codes / adapt.keep|merge|rewrite。
    """
    out = []

    def add(p, v):
        if isinstance(v, str):
            out.append((p, v))

    bs = d.get("beat_sheet") or []
    if isinstance(bs, list):
        for i, b in enumerate(bs):
            if isinstance(b, dict):
                add("beat_sheet[%d].code" % i, b.get("code"))
                add("beat_sheet[%d].purpose" % i, b.get("purpose"))

    hooks = d.get("hooks") or {}
    if isinstance(hooks, dict):
        for grp in ("open", "close", "extra"):
            items = hooks.get(grp) or []
            if isinstance(items, list):
                for i, h in enumerate(items):
                    if isinstance(h, dict):
                        for k in HOOK_KEYS:
                            add("hooks.%s[%d].%s" % (grp, i, k), h.get(k))

    rl = d.get("redlines") or []
    if isinstance(rl, list):
        for i, r in enumerate(rl):
            if isinstance(r, dict):
                add("redlines[%d].code" % i, r.get("code"))
                add("redlines[%d].fallback" % i, r.get("fallback"))

    ab = d.get("asset_bias") or {}
    if isinstance(ab, dict):
        for k in ("prop_focus", "scene_pool"):
            items = ab.get(k) or []
            if isinstance(items, list):
                for i, v in enumerate(items):
                    add("asset_bias.%s[%d]" % (k, i), v)

    ln = d.get("line") or {}
    if isinstance(ln, dict):
        items = ln.get("tone_codes") or []
        if isinstance(items, list):
            for i, v in enumerate(items):
                add("line.tone_codes[%d]" % i, v)

    ad = d.get("adapt") or {}
    if isinstance(ad, dict):
        for k in ("keep", "merge", "rewrite"):
            items = ad.get(k) or []
            if isinstance(items, list):
                for i, v in enumerate(items):
                    add("adapt.%s[%d]" % (k, i), v)

    return out


def hook_codes_of(hooks):
    """收集 open/close/extra 全部钩子 code，作为「钩子码命名空间」。"""
    s = set()
    if not isinstance(hooks, dict):
        return s
    for grp in ("open", "close", "extra"):
        items = hooks.get(grp) or []
        if isinstance(items, list):
            for h in items:
                if isinstance(h, dict) and "code" in h:
                    s.add(str(h.get("code")))
    return s


def summarize(path):
    nf = sum(1 for l, _, _ in results if l == FAIL)
    nw = sum(1 for l, _, _ in results if l == WARN)
    print("=" * 64)
    print("Genre Profile gate v2.0.0 · %s" % path)
    print("=" * 64)
    for l, code, msg in results:
        print("[%-4s] %-22s %s" % (l, code, msg))
    print("-" * 64)
    verdict = "可提交人工评审" if (nf == 0 and nw == 0) else "打回重生成"
    print("FAIL=%d  WARN=%d  → %s" % (nf, nw, verdict))
    print("=" * 64)
    return nf


def main(path, baseline, registry):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    if not isinstance(d, dict):
        rec(FAIL, "P00 顶层结构", "JSON 顶层不是对象: %s" % type(d).__name__)
        return summarize(path)

    # P01 顶层字段双向白名单 [探针 A6：新增第 15 个字段必须挡]
    missing = [k for k in TOP_FIELDS if k not in d]
    extra = [k for k in d if k not in TOP_FIELDS]
    rec(FAIL if (missing or extra) else PASS, "P01 顶层字段双向白名单",
        "齐全 14/14 且无多余" if not (missing or extra)
        else "缺失 %s / 多余 %s（铁律一：骨架唯一）" % (missing, extra))

    # P02 嵌套字段齐全
    nmiss = []
    for parent, keys in NESTED.items():
        node = d.get(parent)
        if not isinstance(node, dict):
            nmiss.append(parent + "(非对象)")
            continue
        for k in keys:
            if k not in node:
                nmiss.append(parent + "." + k)
    rec(FAIL if nmiss else PASS, "P02 嵌套字段",
        "齐全" if not nmiss else "缺失: " + ", ".join(nmiss))

    # P03 status 状态机枚举 [探针 A1：approved 是合法终态，不得误杀]
    st = d.get("status")
    rec(PASS if st in STATUS_ENUM else FAIL, "P03 status 状态机",
        "%s ∈ {skeleton,draft,approved}" % st if st in STATUS_ENUM
        else "非法状态 %r；应为状态机枚举之一" % st)

    # P04 verification
    ver = str(d.get("verification", ""))
    rec(PASS if ver else FAIL, "P04 verification",
        "已标注: %s" % ver if ver else "为空——K-03 要求标注核验状态")

    # P05 beat_sheet 结构 + 数值类型
    bs = d.get("beat_sheet")
    if not isinstance(bs, list) or not bs:
        rec(FAIL, "P05 beat_sheet", "非列表或为空")
        bs = []
    else:
        bad = [i for i, b in enumerate(bs)
               if not isinstance(b, dict) or any(k not in b for k in BEAT_KEYS)
               or not is_num(b.get("at_s")) or not is_num(b.get("dur_s"))]
        rec(FAIL if bad else PASS, "P05 beat_sheet",
            "%d 拍，结构/数值类型全对" % len(bs) if not bad
            else "第 %s 拍字段缺失或数值写成字符串" % bad)

    # P06 at_s 从 0 起、严格递增、首尾相接、无重叠无空隙
    if bs:
        cursor, gaps, ok = 0, [], True
        for i, b in enumerate(bs):
            a, dur = b.get("at_s"), b.get("dur_s")
            if not is_num(a) or not is_num(dur) or dur <= 0:
                gaps.append("#%d 非正时长/非数值" % (i + 1)); ok = False; continue
            if a != cursor:
                gaps.append("#%d at_s=%s 应接 %s" % (i + 1, a, cursor)); ok = False
            cursor = a + dur
        rec(PASS if ok else FAIL, "P06 节拍连续性",
            "0→%s 首尾相接、无重叠无空隙" % cursor if ok else "; ".join(gaps))
        total = cursor
    else:
        total = None

    # P07 时长守恒 [探针 A13：不传 --baseline 必须 FAIL，不得退化 WARN]
    if total is None:
        rec(FAIL, "P07 时长守恒", "beat_sheet 为空，无法复算")
    elif baseline is None:
        rec(FAIL, "P07 时长守恒",
            "未传 --baseline —— 基准秒数是硬条件，缺省不放行（v2）")
    else:
        rec(PASS if total == baseline else FAIL, "P07 时长守恒",
            "Σdur_s=%s == 基准 %s" % (total, baseline) if total == baseline
            else "Σdur_s=%s != 基准 %s（差 %+d）" % (total, baseline, total - baseline))

    # P08 钩子/节拍命名空间（重写）[探针 A3 / A4 / A10]
    # 契约见文件头「边界声明」：hook_code 枚举校验属 F2 门，本 gate 不代判。
    hooks = d.get("hooks") or {}
    if bs:
        first = bs[0] if isinstance(bs[0], dict) else {}
        fdur = first.get("dur_s")
        ok_dur = is_num(fdur) and fdur <= 3
        beat_codes = [str(b.get("code", "")) for b in bs if isinstance(b, dict)]
        bad_fmt = [c for c in beat_codes if not CODE_RE.match(c)]
        mixed = sorted(set(beat_codes) & hook_codes_of(hooks))
        det = []
        if not ok_dur:
            det.append("首拍 dur_s=%r >3（R-S4 黄金 3 秒）" % fdur)
        if bad_fmt:
            det.append("节拍码格式不合法 %s（须大写下划线）" % bad_fmt)
        if mixed:
            det.append("钩子码被当节拍码混用 %s（R-S3 禁止）" % mixed)
        rec(PASS if not det else FAIL, "P08 钩子/节拍命名空间",
            "首拍 %ss、%d 个节拍码格式合法、与钩子码零相交（hook_code 枚举属 F2 门）"
            % (fdur, len(beat_codes)) if not det else "; ".join(det))

    # P09 爽点守恒 [探针 A2 / L-09：R-S1 是 >= 下限，不是 ==]
    marked = sum(1 for b in bs if isinstance(b, dict) and b.get("is_payoff") is True)
    mpe = (d.get("payoff") or {}).get("min_per_ep")
    if is_num(mpe) and mpe >= 1:
        rec(PASS if marked >= mpe else FAIL, "P09 爽点守恒",
            "标记 %d 处 ≥ min_per_ep %d（R-S1 下限）" % (marked, mpe)
            if marked >= mpe else "标记 %d 处 < min_per_ep %d" % (marked, mpe))
    else:
        rec(FAIL, "P09 爽点守恒", "min_per_ep 非数值或 <1: %r" % mpe)

    # P10 钩子库条数 + 结构（覆盖 extra）[探针 A5 / A14]
    for grp, minimum in (("open", 3), ("close", 3), ("extra", 0)):
        items = hooks.get(grp) if isinstance(hooks, dict) else None
        if not isinstance(items, list):
            rec(FAIL, "P10 hooks.%s" % grp, "非列表")
            continue
        bad = [i for i, h in enumerate(items)
               if not isinstance(h, dict) or any(k not in h for k in HOOK_KEYS)]
        good = len(items) >= minimum and not bad
        rec(PASS if good else FAIL, "P10 hooks.%s" % grp,
            "%d 条、结构齐全" % len(items) if good
            else "%d 条（需 ≥%d），结构缺失 %s" % (len(items), minimum, bad))

    # P11 钩子 code 唯一 + 格式（收集 open/close/extra）[探针 A14 / A15]
    allcodes = []
    if isinstance(hooks, dict):
        for grp in ("open", "close", "extra"):
            items = hooks.get(grp) or []
            if isinstance(items, list):
                for h in items:
                    if isinstance(h, dict) and "code" in h:
                        allcodes.append(str(h.get("code")))
    dup = sorted({c for c in allcodes if allcodes.count(c) > 1})
    badfmt = [c for c in allcodes if not CODE_RE.match(c)]
    rec(PASS if not (dup or badfmt) else FAIL, "P11 钩子 code",
        "%d 个 code（含 extra）全唯一且格式合法" % len(allcodes)
        if not (dup or badfmt) else "重复 %s / 格式不合法 %s" % (dup, badfmt))

    # P12 钩子台词 ≤15 字（词表扫描统一由 P15 承担）
    violations = []
    for grp in ("open", "close", "extra"):
        for h in (hooks.get(grp) or []) if isinstance(hooks, dict) else []:
            if not isinstance(h, dict):
                continue
            s = str(h.get("sample_line", ""))
            if len(s) > 15:
                violations.append("%s:%s 共%d字" % (grp, h.get("code"), len(s)))
    rec(PASS if not violations else FAIL, "P12 钩子台词字数",
        "全部 ≤15 字" if not violations else "; ".join(violations))

    # P13 红线三件套 + code 格式 [探针 A11]
    rl = d.get("redlines")
    if not isinstance(rl, list) or not rl:
        rec(FAIL, "P13 红线", "非列表或为空")
    else:
        bad = [i for i, r in enumerate(rl)
               if not isinstance(r, dict) or any(not r.get(k) for k in REDLINE_KEYS)]
        badcode = [str(r.get("code")) for r in rl
                   if isinstance(r, dict) and not CODE_RE.match(str(r.get("code", "")))]
        rec(FAIL if (bad or badcode) else PASS, "P13 红线",
            "%d 条均含 code/rule/fallback 且 code 格式合法" % len(rl)
            if not (bad or badcode)
            else "缺三件套 %s / code 格式不合法 %s" % (bad, badcode))

    # P14 画风锚命中注册表 [探针 A7]
    ref = str(d.get("style_bible_ref", ""))
    stt = registry.get(ref)
    rec(PASS if stt == "registered" else FAIL, "P14 画风锚注册表",
        "%s 命中 style_refs · status=%s" % (ref, stt) if stt == "registered"
        else "%s 未注册/格式非法（注册表 %d 项）" % (ref, len(registry)))

    # P15 铁律二（形容词）+ R-S6（心理动词），按字段扫描，命中即 FAIL
    # [探针 A8 formula / A9 fallback；A16 反证 rule 不误杀 / A17 覆盖 name]
    pairs = content_strings(d)
    adj = sorted({w for _, s in pairs for w in ADJECTIVE_RE.findall(s)})
    men = sorted({w for _, s in pairs for w in MENTAL_RE.findall(s)})
    rec(PASS if not (adj or men) else FAIL, "P15 参数封闭/R-S6",
        "%d 个参数字段已扫，未命中不可校验表述与心理动词" % len(pairs)
        if not (adj or men)
        else "不可校验表述 %s / 心理动词 %s（命中字段见 gate 明细）" % (adj, men))

    # P16 evidence
    ev = d.get("evidence")
    rec(PASS if isinstance(ev, str) and ev.strip() else FAIL, "P16 evidence",
        "已填" if isinstance(ev, str) and ev.strip() else "为空——K-03 要求逐参数给依据")

    # P17 unverified 单列 [探针 A12：删光 U| 行必须 FAIL]
    u_lines = []
    if isinstance(ev, str):
        u_lines = [l.strip() for l in ev.splitlines()
                   if re.match(r"^U-\d+\|", l.strip())]
    if ver == "unverified":
        rec(PASS if u_lines else FAIL, "P17 unverified 单列",
            "evidence 内 U| 行 %d 项（逐项需人工评审确认）" % len(u_lines)
            if u_lines else "verification=unverified 却无 U| 行——违反 K-03")
    else:
        rec(PASS, "P17 unverified 单列",
            "verification=%s，U| 行 %d 项" % (ver, len(u_lines)))

    return summarize(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    base = None
    if "--baseline" in sys.argv:
        i = sys.argv.index("--baseline")
        try:
            base = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            print("--baseline 需给整数")
            sys.exit(2)
    reg = STYLE_REGISTRY
    if "--registry" in sys.argv:
        i = sys.argv.index("--registry")
        try:
            with open(sys.argv[i + 1], encoding="utf-8") as f:
                reg = json.load(f)
        except (IndexError, OSError, ValueError) as e:
            print("--registry 读取失败: %s" % e)
            sys.exit(2)
    sys.exit(1 if main(sys.argv[1], base, reg) else 0)
