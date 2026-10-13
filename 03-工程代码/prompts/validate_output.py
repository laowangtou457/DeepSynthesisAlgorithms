#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出契约校验器 · validate_output.py

定位：
  validate_templates.py 校验「模板写了什么」（结构／变量一致性）；
  本脚本校验「产物长什么样」——即模板输出 JSON 是否满足链路已定案的**封闭枚举与接缝约定**。

  ⚠️ 本脚本**不联网、不调用模型**，只对「已产出的 JSON」做静态核对。
     因此它既能用于当前的**人工构造用例**（examples/*.md 内的 JSON 块），
     也能在模型就绪后直接对**真实输出**执行（用法见下）。

首批校验规则（依 2026-10-13 导演视角两轮评审定案）：
  R1 PURPOSE_ENUM          scenes_outline[].purpose / acts[].scenes[].purpose
                           仅限五值：建立／升级／转折／反转／收束
                           —— 本脚本的**首要规则**（对应 R-05：枚举未闭合导致用例越界）
  R2 FILL_STAGE_ENUM       unspecified[].fill_stage 仅限：
                           synopsis／script／storyboard／shot_prompt
  R3 SCENE_NO_CONTINUITY   场号须从 1 起连续、不重复（R-06：区间与档位口径）
  R4 EST_SECONDS_SUM       total_est_seconds 须等于各场 est_seconds 之和
  R5 REQUIRED_KEYS         按产物形态（synopsis／script）核对必备顶层字段
  R6 ACT_STRUCTURE         （仅 script）acts 恰为 3 幕，且每场 act_no 与所属幕一致

用法：
  python validate_output.py                     # 扫描 examples/*.md 内全部 JSON 块
  python validate_output.py --file out.json     # 校验单个 JSON 文件（真实模型输出）
  python validate_output.py --json              # 机器可读结果

退出码：
  0 = 全部通过 ｜ 1 = 存在失败项 ｜ 2 = 环境缺失依赖或用法错误

依赖：仅标准库（无 pyyaml 依赖）
"""
import sys
import os
import re
import json
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))

# ---------------- 封闭枚举（唯一真值来源，改动须同步模板与 SCHEMA.md） ----------------
PURPOSE_ENUM = ["建立", "升级", "转折", "反转", "收束"]
FILL_STAGE_ENUM = ["synopsis", "script", "storyboard", "shot_prompt"]

JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

RESULT = {"checks": 0, "errors": [], "warnings": []}
QUIET = False


def out(msg=""):
    if not QUIET:
        print(msg)


def ok(msg):
    RESULT["checks"] += 1
    out(f"  [OK]   {msg}")


def err(msg):
    RESULT["errors"].append(msg)
    out(f"  [FAIL] {msg}")


def warn(msg):
    RESULT["warnings"].append(msg)
    out(f"  [WARN] {msg}")


# ---------------- 形态识别与字段抽取 ----------------
def detect_shape(doc):
    """按产物顶层字段识别形态。"""
    if not isinstance(doc, dict):
        return None
    if "acts" in doc:
        return "script"
    if "scenes_outline" in doc:
        return "synopsis"
    return None


def iter_scenes(doc, shape):
    """产出 (场号, purpose, est_seconds, 定位串) 四元组，屏蔽两种形态差异。"""
    if shape == "script":
        for ai, act in enumerate(doc.get("acts") or []):
            for si, sc in enumerate(act.get("scenes") or []):
                yield (sc, f"acts[{ai}].scenes[{si}]")
    else:
        for si, sc in enumerate(doc.get("scenes_outline") or []):
            yield (sc, f"scenes_outline[{si}]")


# ---------------- 规则实现 ----------------
def rule_purpose_enum(doc, shape, where):
    """R1：purpose 封闭枚举（本脚本首要规则）。"""
    seen = 0
    bad = []
    for sc, loc in iter_scenes(doc, shape):
        if not isinstance(sc, dict):
            continue
        seen += 1
        val = sc.get("purpose")
        if val is None:
            bad.append(f"{loc}.purpose 缺失")
        elif val not in PURPOSE_ENUM:
            bad.append(f"{loc}.purpose = 『{val}』")
    if bad:
        err(f"{where} · R1 PURPOSE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    elif seen:
        ok(f"{where} · R1 PURPOSE_ENUM：{seen} 处 purpose 全部落在五值枚举内")
    else:
        warn(f"{where} · R1 PURPOSE_ENUM：未找到任何场次（跳过）")


def rule_fill_stage_enum(doc, where):
    """R2：unspecified[].fill_stage 封闭枚举。"""
    items = doc.get("unspecified") or []
    if not isinstance(items, list) or not items:
        warn(f"{where} · R2 FILL_STAGE_ENUM：无 unspecified 条目（跳过）")
        return
    bad = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            bad.append(f"unspecified[{i}] 非对象")
            continue
        val = it.get("fill_stage")
        if val not in FILL_STAGE_ENUM:
            bad.append(f"unspecified[{i}].fill_stage = 『{val}』")
    if bad:
        err(f"{where} · R2 FILL_STAGE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R2 FILL_STAGE_ENUM：{len(items)} 条 fill_stage 全部落在四值枚举内")


def rule_scene_no_continuity(doc, shape, where):
    """R3：场号从 1 起连续、不重复。"""
    nos = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            nos.append(sc.get("no"))
    if not nos:
        warn(f"{where} · R3 SCENE_NO_CONTINUITY：无场号可校（跳过）")
        return
    if any(not isinstance(n, int) for n in nos):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：存在非整数场号 → {nos}")
        return
    if sorted(nos) != list(range(1, len(nos) + 1)):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：场号应为 1..{len(nos)}，实际 {nos}")
    else:
        ok(f"{where} · R3 SCENE_NO_CONTINUITY：场号 1..{len(nos)} 连续且唯一")


def rule_est_seconds_sum(doc, shape, where):
    """R4：total_est_seconds == Σ est_seconds。"""
    total = doc.get("total_est_seconds")
    vals = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            vals.append(sc.get("est_seconds"))
    if total is None:
        err(f"{where} · R4 EST_SECONDS_SUM：缺 total_est_seconds")
        return
    if any(not isinstance(v, (int, float)) for v in vals):
        err(f"{where} · R4 EST_SECONDS_SUM：存在非数值 est_seconds → {vals}")
        return
    s = sum(vals)
    if s != total:
        err(f"{where} · R4 EST_SECONDS_SUM：Σest_seconds={s} ≠ total_est_seconds={total}")
    else:
        ok(f"{where} · R4 EST_SECONDS_SUM：Σ{len(vals)} 场 = {s} = total_est_seconds")


def rule_required_keys(doc, shape, where):
    """R5：按形态核对必备顶层字段。"""
    need = {
        "synopsis": ["title", "logline", "protagonist", "supporting", "world",
                     "conflict", "scenes_outline", "ending", "forbidden_items",
                     "total_est_seconds", "unspecified"],
        "script": ["title", "logline", "genre", "style_bible", "characters", "acts",
                   "forbidden_items", "total_est_seconds", "unspecified"],
    }[shape]
    miss = [k for k in need if k not in doc]
    if miss:
        err(f"{where} · R5 REQUIRED_KEYS（{shape}）：缺 {miss}")
    else:
        ok(f"{where} · R5 REQUIRED_KEYS（{shape}）：{len(need)} 个必备顶层字段齐备")


def rule_act_structure(doc, where):
    """R6（仅 script）：恰为 3 幕，且每场 act_no 与所属幕一致。"""
    acts = doc.get("acts")
    if not isinstance(acts, list) or not acts:
        err(f"{where} · R6 ACT_STRUCTURE：acts 缺失或为空")
        return
    if len(acts) != 3:
        err(f"{where} · R6 ACT_STRUCTURE：幕数应为 3，实际 {len(acts)}")
        return
    bad = []
    for ai, act in enumerate(acts):
        if not isinstance(act, dict):
            bad.append(f"acts[{ai}] 非对象")
            continue
        expect = act.get("act_no")
        for si, sc in enumerate(act.get("scenes") or []):
            if isinstance(sc, dict) and sc.get("act_no") != expect:
                bad.append(f"acts[{ai}].scenes[{si}].act_no={sc.get('act_no')} 与幕 act_no={expect} 不一致")
    if bad:
        err(f"{where} · R6 ACT_STRUCTURE：{len(bad)} 处不一致 → " + "；".join(bad[:5]))
    else:
        ok(f"{where} · R6 ACT_STRUCTURE：3 幕齐备，各场 act_no 归属一致")


# ---------------- 调度 ----------------
def validate_doc(doc, where):
    shape = detect_shape(doc)
    if shape is None:
        warn(f"{where}：无法识别产物形态（既无 acts 也无 scenes_outline），跳过")
        return
    out(f"\n--- {where}（形态：{shape}）---")
    rule_required_keys(doc, shape, where)
    rule_purpose_enum(doc, shape, where)
    rule_fill_stage_enum(doc, where)
    rule_scene_no_continuity(doc, shape, where)
    rule_est_seconds_sum(doc, shape, where)
    if shape == "script":
        rule_act_structure(doc, where)


def scan_examples():
    exp_dir = os.path.join(BASE, "examples")
    if not os.path.isdir(exp_dir):
        warn("examples/ 目录不存在，跳过")
        return
    files = [f for f in sorted(os.listdir(exp_dir)) if f.endswith(".md") and f != "README.md"]
    if not files:
        warn("examples/ 下无可校验样例")
        return
    for fn in files:
        with open(os.path.join(exp_dir, fn), encoding="utf-8") as f:
            text = f.read()
        blocks = JSON_BLOCK_RE.findall(text)
        if not blocks:
            warn(f"{fn}：未找到 ```json 代码块")
            continue
        for i, b in enumerate(blocks, 1):
            try:
                doc = json.loads(b)
            except Exception as e:
                err(f"{fn}（第 {i} 个 JSON 块）：解析失败 {e}")
                continue
            validate_doc(doc, f"{fn}#{i}")


def validate_file(path):
    if not os.path.exists(path):
        err(f"文件不存在：{path}")
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 允许传入「裸 JSON」或「含 ```json 块的 md」
    blocks = JSON_BLOCK_RE.findall(text)
    if not blocks:
        blocks = [text]
    for i, b in enumerate(blocks, 1):
        try:
            doc = json.loads(b)
        except Exception as e:
            err(f"{os.path.basename(path)}（第 {i} 个 JSON）：解析失败 {e}")
            continue
        validate_doc(doc, f"{os.path.basename(path)}#{i}")


def main():
    global QUIET
    ap = argparse.ArgumentParser(description="输出契约校验器（首批：purpose 封闭枚举）")
    ap.add_argument("--file", help="校验单个 JSON（或含 ```json 块的 .md）文件")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args()
    QUIET = args.json

    if not QUIET:
        print("输出契约校验 · validate_output.py")
        print(f"根目录：{BASE}")
        print(f"purpose 枚举：{'／'.join(PURPOSE_ENUM)}")
        print(f"fill_stage 枚举：{'／'.join(FILL_STAGE_ENUM)}")

    if args.file:
        validate_file(args.file)
    else:
        scan_examples()

    passed = not RESULT["errors"]
    if args.json:
        print(json.dumps({
            "passed": passed,
            "checks": RESULT["checks"],
            "errors": RESULT["errors"],
            "warnings": RESULT["warnings"],
            "purpose_enum": PURPOSE_ENUM,
            "fill_stage_enum": FILL_STAGE_ENUM,
            "exit_code": 0 if passed else 1,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 52)
        print(f"通过检查项：{RESULT['checks']}")
        print(f"失败：{len(RESULT['errors'])} ｜ 警告：{len(RESULT['warnings'])}")
        print("结论：" + ("✅ 全部通过" if passed else "❌ 存在失败项"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
