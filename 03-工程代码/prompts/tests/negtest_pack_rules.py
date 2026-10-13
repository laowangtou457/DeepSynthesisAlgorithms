#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付包规则负向验证 · negtest_pack_rules.py

定位：`validate_output.py` 只对 examples/ 的**通过样本**跑正向校验——正向全绿仅证明
      「规则不误报」，**不证明规则有效**（把判据写反、条件永不成立、字段名拼错，
      都会让正向照样全绿）。本脚本**逐条构造越界样本**，断言对应规则真的触发（EXIT=1）。

覆盖：交付包层 R26~R32（2026-10-13 随 SW-007 `shot_prompt_v1` 建立）。

用法：
    python tests/negtest_pack_rules.py            # 跑全部样本
    python tests/negtest_pack_rules.py --json     # 机器可读结果

退出码：0 = 全部符合预期；1 = 存在不符（规则没触发，或盲区意外触发）

⚠️ 纪律：新增交付包规则时，**必须**在此处补一个越界样本——没有越界样本的新规则
   等于一条未经验证的声明。（与 SCHEMA.md「负向验证纪律」条目配套。）

依赖：仅标准库。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # prompts/
VAL = os.path.join(BASE, "validate_output.py")
EX = os.path.join(BASE, "examples")
JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)
UP_CASE = "shot-prompt-case01.md"
UP_SB = "storyboard-case01.md"


# --------------------------------------------------------------------------
# 样本定义
# --------------------------------------------------------------------------
CASES = []          # (名称, 期望命中的规则码, 变异函数, 是否需上游分镜)
BLINDSPOTS = []     # (名称, 变异函数, 为何不触发)
_SB = {}


def _load_base():
    t = open(os.path.join(EX, UP_CASE), encoding="utf-8").read()
    for b in JSON_BLOCK.findall(t):
        j = json.loads(b)
        if "aigc_meta" in j and "schema_version" in j:
            return j
    raise SystemExit(f"[FATAL] {UP_CASE} 中未找到交付包 JSON 块（含 aigc_meta + schema_version）")


def case(name, rule, need_sb=False):
    def deco(fn):
        CASES.append((name, rule, fn, need_sb))
        return fn
    return deco


def blindspot(name, fn, why):
    BLINDSPOTS.append((name, fn, why))
    return fn


def setp(obj, path, val):
    """按 a.b.c 路径设置值（末段可为 list 索引）。"""
    put(obj, path, val)


def _resolve(obj, path):
    """返回 (容器, 末段键)；末段若为数字则键为 int。"""
    cur, parts = obj, path.split(".")
    for p in parts[:-1]:
        cur = cur[int(p)] if p.isdigit() else cur[p]
    last = parts[-1]
    return cur, (int(last) if last.isdigit() else last)


def put(obj, path, val):
    cont, key = _resolve(obj, path)
    cont[key] = val


def drop(obj, path):
    cont, key = _resolve(obj, path)
    if isinstance(cont, dict):
        cont.pop(key, None)
    else:
        cont.pop(key)


def add(obj, path, delta):
    cont, key = _resolve(obj, path)
    cont[key] += delta


# ---- R26 运镜幅度／速度的省略规则 ----------------------------------------
@case("R26 幅度用了默认值 medium", "R26")
def _(d):
    put(d, "shots.0.camera.amplitude", "medium")


@case("R26 速度用了默认值 normal", "R26")
def _(d):
    put(d, "shots.1.camera.speed", "normal")


# ---- R27 交付包必备结构 --------------------------------------------------
@case("R27 某镜缺 prompt_en", "R27")
def _(d):
    drop(d, "shots.3.prompt_en")


@case("R27 style_ref 未命中 style_id（§3.8 阻断项）", "R27")
def _(d):
    put(d, "shots.5.style_ref", "STYLE-99")


@case("R27 character_refs 引用未定义角色", "R27")
def _(d):
    put(d, "shots.6.character_refs", ["CHR-99"])


# ---- R28 正文不得复述外观锚 ----------------------------------------------
@case("R28 中文正文复述外观锚", "R28")
def _(d):
    put(d, "shots.0.prompt_zh", d["shots"][0]["prompt_zh"] + "他穿着深蓝色外卖冲锋衣。")


@case("R28 英文正文复述外观锚", "R28")
def _(d):
    put(d, "shots.0.prompt_en",
        d["shots"][0]["prompt_en"] + " A dark blue delivery jacket with reflective strips.")


# ---- R29 提示词正文卫生 --------------------------------------------------
@case("R29 正文含模型参数指令", "R29")
def _(d):
    put(d, "shots.2.prompt_zh", d["shots"][2]["prompt_zh"] + " --ar 16:9 --style raw")


@case("R29 正文含负向残留", "R29")
def _(d):
    put(d, "shots.2.prompt_en", d["shots"][2]["prompt_en"] + " (negative: no rain)")


@case("R29 正文用了锚点清单外的风格词", "R29")
def _(d):
    put(d, "shots.4.prompt_zh", d["shots"][4]["prompt_zh"] + "厚涂质感。")


# ---- R30 AIGC 元数据块 ---------------------------------------------------
@case("R30 Label 不是 \"1\"", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.Label", "0")


@case("R30 ProduceID 与 pack_id 不一致", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.ProduceID", "FR-PK-99999999-XXXXXXXX")


@case("R30 传播方与生产者取值不同", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.ContentPropagator", "别的主体/OTHER")


# ---- R31 时长守恒与「不改导演决策」不变量 ---------------------------------
@case("R31 只改 meta.total_duration_ms", "R31")
def _(d):
    add(d, "meta.total_duration_ms", 1000)


@case("R31 只改单镜时长、未改总时长", "R31")
def _(d):
    add(d, "shots.9.duration_ms", 1000)


@case("R31 与上游分镜的逐镜时长不一致", "R31", need_sb=True)
def _(d):
    add(d, "shots.11.duration_ms", 1000)
    add(d, "meta.total_duration_ms", 1000)


@case("R31 镜数与上游不一致（少一镜）", "R31", need_sb=True)
def _(d):
    drop_shot = d["shots"].pop()
    add(d, "meta.total_duration_ms", -drop_shot["duration_ms"])


# ---- R32 光照字段的词表纯度 ----------------------------------------------
@case("R32 lighting 写成「词表值——说明」", "R32")
def _(d):
    put(d, "shots.0.lighting", "逐光—侧面硬光打在下半张脸")


@case("R32 lighting_default 非纯词表值", "R32")
def _(d):
    put(d, "style_bible.lighting_default", "实景光（楼道感应灯为主）")


# ---- 已知盲区（预期**不**触发；登记在案，防止日后误以为规则更强）---------
def _bs_selfconsistent(d):
    add(d, "shots.7.duration_ms", 1000)
    add(d, "meta.total_duration_ms", 1000)      # 逐镜与总量同步改 → 自洽


blindspot("未提供上游时，同时改单镜时长与总时长（自洽）", _bs_selfconsistent,
          "总时长与逐镜仍自洽，无外部真值可比 → 校验交付包须始终带 --storyboard")


def _bs_no_total(d):
    drop(d, "meta.total_duration_ms")


blindspot("meta.total_duration_ms 缺失", _bs_no_total,
          "该字段在 schema 的 meta.required 里是可选的（规范亦未列为必须）→ 本层无从守恒")


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------
def _run(doc, need_sb, tmpdir):
    fp = os.path.join(tmpdir, "_tmp_pack.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    cmd = [sys.executable, VAL, "--file", fp]
    if need_sb:
        cmd += ["--storyboard", os.path.join(EX, UP_SB)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    ap = argparse.ArgumentParser(description="交付包规则 R26~R32 负向验证")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--keep", action="store_true", help="保留临时样本目录（排查用）")
    args = ap.parse_args()

    base = _load_base()
    tmpdir = tempfile.mkdtemp(prefix="negtest-pack-")
    rows, bad = [], 0
    try:
        for name, rule, mutate, need_sb in CASES:
            d = copy.deepcopy(base)
            mutate(d)
            code, out = _run(d, need_sb, tmpdir)
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            exact = any(rule in ln for ln in fails)
            good = (code == 1 and exact)
            bad += 0 if good else 1
            rows.append({"case": name, "rule": rule, "expect": "EXIT=1 命中 " + rule,
                         "exit": code, "hit": exact, "ok": good,
                         "fails": fails[:3]})
        for name, mutate, why in BLINDSPOTS:
            d = copy.deepcopy(base)
            mutate(d)
            code, out = _run(d, False, tmpdir)
            good = (code == 0)
            bad += 0 if good else 1
            rows.append({"case": name, "rule": "（已知盲区）", "expect": "EXIT=0",
                         "exit": code, "hit": None, "ok": good, "why": why})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=not args.keep)

    if args.json:
        print(json.dumps({"passed": bad == 0, "total": len(rows), "failed": bad,
                          "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"交付包规则负向验证 · R26~R32 · {len(CASES)} 个越界样本 + {len(BLINDSPOTS)} 个已知盲区")
        print("=" * 66)
        for r in rows:
            print(f"[{'OK ' if r['ok'] else 'BAD'}] exit={r['exit']} {r['expect']} · {r['case']}")
            if not r["ok"]:
                print("      → 实际 FAIL 行：" + (" | ".join(r["fails"]) if r.get("fails") else "（无）"))
            if r.get("why"):
                print(f"      理由：{r['why']}")
        print("=" * 66)
        print(f"合计 {len(rows)} 项：{len(rows) - bad} 项符合预期，{bad} 项不符")
        print("结论：" + ("✅ 规则有效（每条均能被越界样本触发）" if bad == 0 else "❌ 存在未触发/意外触发项"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
