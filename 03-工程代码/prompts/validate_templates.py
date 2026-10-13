#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词资产校验器 · validate_templates.py

校验对象：
  1. manifest.yaml      —— 主清单结构与登记完整性
  2. templates/*.yaml   —— 各模板五节结构与变量引用一致性
  3. examples/*.md      —— 样例内 JSON 块的可解析性与必备字段

用法：
  python validate_templates.py            # 校验全部，人类可读输出
  python validate_templates.py --json     # 机器可读（供交付测试与备案留档）

退出码：
  0 = 全部通过 ｜ 1 = 存在失败项 ｜ 2 = 环境缺失依赖

依赖：pyyaml
"""
import sys
import os
import re
import json
import argparse

try:
    import yaml
except ImportError:
    print("[FATAL] 缺少 pyyaml，请先安装：pip install pyyaml", file=sys.stderr)
    sys.exit(2)

BASE = os.path.dirname(os.path.abspath(__file__))
SECTIONS = ["system", "task", "context", "output", "examples"]
TPL_REQUIRED = ["id", "name", "task_type", "file", "version", "status"]
VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)[?}]")
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

_result = {"checks": 0, "errors": [], "warnings": []}


def _out(msg=""):
    if not _QUIET:
        print(msg)


_QUIET = False


def ok(msg):
    _result["checks"] += 1
    _out(f"  [OK]   {msg}")


def err(msg):
    _result["errors"].append(msg)
    _out(f"  [FAIL] {msg}")


def warn(msg):
    _result["warnings"].append(msg)
    _out(f"  [WARN] {msg}")


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_manifest():
    _out("\n=== 1. 主清单 manifest.yaml ===")
    path = os.path.join(BASE, "manifest.yaml")
    if not os.path.exists(path):
        err("manifest.yaml 不存在")
        return []
    try:
        mf = load_yaml(path)
    except Exception as e:
        err(f"manifest.yaml 解析失败：{e}")
        return []

    tpls = mf.get("templates") or []
    ok(f"解析成功，登记模板 {len(tpls)} 个")

    ids = [t.get("id") for t in tpls]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        err(f"id 重复：{sorted(dup)}")
    else:
        ok("id 唯一性通过")

    summary = mf.get("summary") or {}
    if summary.get("total") == len(tpls):
        ok(f"summary.total 与实际一致（{len(tpls)}）")
    else:
        err(f"summary.total={summary.get('total')} 与实际条数 {len(tpls)} 不符")

    for t in tpls:
        miss = [k for k in TPL_REQUIRED if not t.get(k)]
        if miss:
            err(f"模板 {t.get('id')} 缺必备字段：{miss}")
        fp = os.path.join(BASE, t.get("file", ""))
        if t.get("file") and not os.path.exists(fp):
            err(f"模板 {t.get('id')} 的 file 路径不存在：{t['file']}")
    if not _result["errors"] or all("缺必备字段" not in e and "路径不存在" not in e for e in _result["errors"]):
        ok("各条目必备字段与 file 指向均存在")
    return tpls


def check_template(t):
    tid = t.get("id")
    path = os.path.join(BASE, t.get("file", ""))
    _out(f"\n=== 2.{tid} ===")
    if not os.path.exists(path):
        err(f"{tid}: 文件不存在")
        return
    try:
        doc = load_yaml(path)
    except Exception as e:
        err(f"{tid}: YAML 解析失败：{e}")
        return
    ok(f"YAML 解析成功 v{doc.get('version')}")

    for k in ("id", "version", "task_type"):
        if doc.get(k) != t.get(k) and k != "version":
            if k == "id" and doc.get("id") != tid:
                err(f"{tid}: 文件内 id 与清单不一致（{doc.get('id')}）")
        elif k == "version" and doc.get("version") != t.get("version"):
            warn(f"{tid}: 文件内 version {doc.get('version')} 与清单 {t.get('version')} 不一致")

    secs = doc.get("sections") or {}
    missing = [k for k in SECTIONS if not (secs.get(k) or "").strip()]
    if missing:
        err(f"{tid}: 分节缺失或为空：{missing}")
    else:
        ok("五节结构齐备（system/task/context/output/examples）")

    variables = doc.get("variables") or []
    declared = {v.get("name") for v in variables if isinstance(v, dict)}
    if not declared:
        err(f"{tid}: variables 未声明")
    else:
        body = json.dumps(secs, ensure_ascii=False)
        used = set(VAR_RE.findall(body))
        undeclared = sorted(used - declared)
        unused = sorted(declared - used)
        if undeclared:
            err(f"{tid}: 正文引用了未声明变量：{undeclared}")
        else:
            ok(f"变量引用一致性通过（声明 {len(declared)} 个，正文引用 {len(used)} 个）")
        if unused:
            warn(f"{tid}: 声明但正文未使用：{unused}")

    req_vars = [v.get("name") for v in variables if isinstance(v, dict) and v.get("required")]
    if not req_vars:
        err(f"{tid}: 无任何 required 变量")
    else:
        ok(f"必填变量：{req_vars}")

    if not doc.get("guards"):
        warn(f"{tid}: 未定义 guards")
    if not doc.get("fallback"):
        warn(f"{tid}: 未定义 fallback")
    if doc.get("stage"):
        ok(f"业务链路阶段 stage={doc['stage']}")


def check_examples():
    _out("\n=== 3. 样例 examples/*.md ===")
    exp_dir = os.path.join(BASE, "examples")
    if not os.path.isdir(exp_dir):
        warn("examples/ 目录不存在，跳过")
        return
    files = [f for f in sorted(os.listdir(exp_dir)) if f.endswith(".md") and f != "README.md"]
    if not files:
        warn("examples/ 下无可校验样例")
        return
    for fn in files:
        fp = os.path.join(exp_dir, fn)
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        blocks = JSON_BLOCK_RE.findall(text)
        if not blocks:
            warn(f"{fn}: 未找到 ```json 代码块")
            continue
        for i, b in enumerate(blocks, 1):
            try:
                data = json.loads(b)
                ok(f"{fn}（第 {i} 个 JSON 块）：解析成功，顶层字段 {len(data)} 个")
            except Exception as e:
                err(f"{fn}（第 {i} 个 JSON 块）：解析失败 {e}")
        if "未验证" not in text and "已实测" not in text:
            warn(f"{fn}: 未标注验证状态")


def main():
    global _QUIET
    ap = argparse.ArgumentParser(description="提示词资产校验器")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args()
    _QUIET = args.json

    if not _QUIET:
        print("提示词资产校验 · validate_templates.py")
        print(f"根目录：{BASE}")

    tpls = check_manifest()
    for t in tpls:
        check_template(t)
    check_examples()

    passed = not _result["errors"]
    if args.json:
        print(json.dumps({
            "passed": passed,
            "checks": _result["checks"],
            "errors": _result["errors"],
            "warnings": _result["warnings"],
            "exit_code": 0 if passed else 1,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 52)
        print(f"通过检查项：{_result['checks']}")
        print(f"失败：{len(_result['errors'])} ｜ 警告：{len(_result['warnings'])}")
        print("结论：" + ("✅ 全部通过" if passed else "❌ 存在失败项，不得交付"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
