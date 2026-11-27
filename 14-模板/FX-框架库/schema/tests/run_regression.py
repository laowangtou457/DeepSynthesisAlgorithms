#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX 框架库 · check_profile_gate.py 判据回归用例（零第三方依赖）

来源：_评审报告_R1按标准执行_2026-11-25.md §2.2「15 组变体探针」→ 固化为 A0~A15。
补充：A16 / A17 为主理人新增的反证探针，用于锁住 P15 的扫描范围边界
      （A16 证明「禁用词元描述」不被误杀；A17 证明「hooks.name」被覆盖）。
另含 C1：gate 内置 STYLE_REGISTRY 与 fx_framework.yaml §六 注册表一致性检查。

用法：
    python schema/tests/run_regression.py
退出码：
    0 = 全部通过（A0 仍 FAIL=0 WARN=0，且每个探针产出预期结果）
    1 = 有探针未达预期（gate 判据回归失败，不得用于 R1 判档）

纪律：本脚本是「判据自身的回归」，不是「档案合规检查」。
      FAIL=0 只证明字段齐全 + 算术自洽；必须先跑通本脚本，gate 结论才可信。
"""
import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "schema" / "check_profile_gate.py"
BASE = ROOT / "profiles" / "fx_profile_M1-01.json"
FRAMEWORK = ROOT / "schema" / "fx_framework.yaml"


# ------------------------------------------------------------
# 变体定义：(名称, 变体函数, 是否传 --baseline, 预期, 按骨架应判)
# 预期 pass = FAIL=0 且 WARN=0；预期 fail = FAIL>=1
# ------------------------------------------------------------
def build_variants():
    V = []

    def mk(name, fn, baseline, expect, should):
        V.append((name, fn, baseline, expect, should))

    mk("A0", lambda d: None, True, "pass", "原状对照组 → PASS")

    # --- 评审报告 §2.2 的 15 组 ---
    mk("A1", lambda d: d.update(status="approved"), True, "pass",
       "合法（状态机终态，R1『通过』后的状态）")
    mk("A2", lambda d: d["beat_sheet"][4].update(is_payoff=True), True, "pass",
       "合法（标 2 处兑现、min_per_ep=1，R-S1 是 >=）")

    def a3(d):
        d["beat_sheet"][7]["code"] = "BEAT_FINALE"
    mk("A3", a3, True, "pass", "合法（合法节拍码，不含 CLOSE 也应放行）")

    def a4(d):
        d["beat_sheet"][7]["code"] = "CLOSE_CRISIS"
    mk("A4", a4, True, "fail", "应挡（钩子码当节拍码，R-S3 禁止混用）")

    def a5(d):
        d["hooks"]["close"] = []
    mk("A5", a5, True, "fail", "应挡（close 钩子库清空）")

    def a6(d):
        d["EXTRA_FIELD"] = 1
    mk("A6", a6, True, "fail", "应挡（新增第 15 个顶层字段，铁律一）")

    def a7(d):
        d["style_bible_ref"] = "STY-NOT-REGISTERED"
    mk("A7", a7, True, "fail", "应挡（未注册画风锚）")

    def a8(d):
        d["hooks"]["open"][0]["formula"] = "氛围压抑"
    mk("A8", a8, True, "fail", "应挡（formula 含不可校验表述，铁律二）")

    def a9(d):
        d["redlines"][0]["fallback"] = "他心里一惊"
    mk("A9", a9, True, "fail", "应挡（fallback 含心理动词，R-S6）")

    def a10(d):
        d["beat_sheet"][0]["code"] = "beat_open_hook"
    mk("A10", a10, True, "fail", "应挡（beat_sheet.code 小写）")

    def a11(d):
        d["redlines"][0]["code"] = "rl_01"
    mk("A11", a11, True, "fail", "应挡（redlines.code 小写）")

    def a12(d):
        lines = [l for l in d["evidence"].splitlines()
                 if not re.match(r"^U-\d+\|", l.strip())]
        d["evidence"] = "\n".join(lines)
    mk("A12", a12, True, "fail", "应挡（删光 U| 行，K-03）")

    mk("A13", lambda d: None, False, "fail", "应挡（不传 --baseline，基准是硬条件）")

    def a14(d):
        d["hooks"]["extra"] = [
            {"code": "OPEN_HUMILIATE", "name": "重复码",
             "formula": "x", "sample_line": "x"}
        ]
    mk("A14", a14, True, "fail", "应挡（hooks.extra 注入与 open 重复 code）")

    def a15(d):
        d["hooks"]["open"][0]["code"] = "CLOSE_CRISIS"
    mk("A15", a15, True, "fail", "应挡（open 与 close 重复 code，对照组）")

    # --- 主理人补充反证探针（锁住 P15 扫描范围）---
    def a16(d):
        d["redlines"][0]["rule"] = "禁止出现：想/觉得/心里"
    mk("A16", a16, True, "pass",
       "合法（rule 是禁用词元描述，含词面属正常，不得误杀）")

    def a17(d):
        d["hooks"]["open"][0]["name"] = "氛围压抑"
    mk("A17", a17, True, "fail", "应挡（hooks.name 也须纳入铁律二扫描）")

    return V


def run_gate(profile_path, baseline):
    cmd = [sys.executable, str(GATE), str(profile_path)]
    if baseline:
        cmd += ["--baseline", "90"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"FAIL=(\d+)\s+WARN=(\d+)", r.stdout or "")
    if not m:
        return None, None, (r.stdout or "") + (r.stderr or "")
    return int(m.group(1)), int(m.group(2)), r.stdout


def check_registry_consistency():
    """C1：gate 内置 STYLE_REGISTRY 必须与 fx_framework.yaml §六 一致。"""
    spec = importlib.util.spec_from_file_location("fxgate", GATE)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    text = FRAMEWORK.read_text(encoding="utf-8")
    found = dict(re.findall(
        r"\{\s*code:\s*(STY-[A-Z-]+),\s*name:[^,]*,\s*status:\s*(\w+)\s*\}", text))
    return g.STYLE_REGISTRY, found


def main():
    if not BASE.exists():
        print("基线不存在: %s" % BASE)
        return 1
    base = json.loads(BASE.read_text(encoding="utf-8"))
    variants = build_variants()

    print("=" * 96)
    print("check_profile_gate.py v2.0.0 · 判据回归（15 组评审探针 + 2 组主理人反证）")
    print("=" * 96)
    print("%-5s %-4s %-6s %-10s %-8s %s" %
          ("探针", "传基准", "预期", "gate 实际", "结论", "按骨架应判"))
    print("-" * 96)

    failures = []
    with tempfile.TemporaryDirectory(prefix="fx_gate_", dir=str(ROOT / "schema")) as td:
        td = Path(td)
        for name, fn, baseline, expect, should in variants:
            d = copy.deepcopy(base)
            fn(d)
            p = td / (name + ".json")
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            nf, nw, out = run_gate(p, baseline)
            if nf is None:
                ok = False
                actual = "解析失败"
                print("%-5s %-4s %-6s %-10s %-8s %s" %
                      (name, "Y" if baseline else "N", expect, actual, "✗", should))
                failures.append((name, "gate 输出无法解析：" + out[:200]))
                continue
            actual = "F=%d W=%d" % (nf, nw)
            ok = (nf == 0 and nw == 0) if expect == "pass" else (nf >= 1)
            print("%-5s %-4s %-6s %-10s %-8s %s" %
                  (name, "Y" if baseline else "N", expect, actual,
                   "✓" if ok else "✗", should))
            if not ok:
                failures.append((name, "预期 %s，实际 %s" % (expect, actual)))
                print("      ---- gate 输出 ----")
                for line in (out or "").splitlines():
                    if line.startswith("[FAIL]") or line.startswith("[WARN]"):
                        print("      " + line)

    print("-" * 96)
    reg_builtin, reg_yaml = check_registry_consistency()
    c1 = reg_builtin == reg_yaml
    print("C1  注册表一致性 gate.STYLE_REGISTRY == fx_framework.yaml style_refs: %s" %
          ("✓" if c1 else "✗"))
    if not c1:
        print("     gate 内置: %s" % reg_builtin)
        print("     yaml 解析: %s" % reg_yaml)
        failures.append(("C1", "注册表镜像与骨架不一致"))

    print("=" * 96)
    total = len(variants) + 1
    print("用例 %d 组，未达预期 %d 组 → %s" %
          (total, len(failures), "全部通过" if not failures else "回归失败"))
    if failures:
        for n, why in failures:
            print("  ✗ %s: %s" % (n, why))
        print("=" * 96)
        return 1
    print("A0 仍 FAIL=0 WARN=0；gate 判据回归通过，可用于 R1 判档。")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
