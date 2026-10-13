# -*- coding: utf-8 -*-
"""
check_upstream.py — 上游词库导入前核实工具

用途
    在导入任何 GitHub 开源词库之前，核实两件事：
      ① **许可证是否允许商用**（MIT / Apache-2.0 / BSD 可以；AGPL / GPL / 无许可证不可以）
      ② **词库实际规模**（文件清单 + 逐文件行数）

    这是 `04-开源资源索引/SEC-006_开源词库资源.md` 中「导入前须重新核实」条款的落地工具。
    开源仓库的许可证与规模随时可能变化，**不要相信文档里的旧数字**。

用法
    python check_upstream.py konsheng/Sensitive-lexicon
    python check_upstream.py konsheng/Sensitive-lexicon --dir Vocabulary
    python check_upstream.py fwwdn/sensitive-stop-words --branch master
    python check_upstream.py houbb/sensitive-word

输出
    许可证判定 + 仓库概况 + 逐文件行数。
    需要网络（走 api.github.com）；raw.githubusercontent.com 在本环境不可达，故改用 contents API。

依赖
    仅标准库。外部命令 curl 非必需。
"""

import base64
import json
import sys
import time
import urllib.parse
import urllib.request

HDR = {"Accept": "application/vnd.github+json", "User-Agent": "wb-research"}

# 许可证判定表
OK_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "Unlicense"}
BLOCK_LICENSES = {"AGPL-3.0", "GPL-3.0", "GPL-2.0", "LGPL-3.0", "MPL-2.0", "CC-BY-SA-4.0"}

SKIP_NAMES = {"LICENSE", "README.md", "README", "README.MD", "CHANGELOG.md",
              ".gitignore", ".gitattributes", "CODE_OF_CONDUCT.md",
              "CONTRIBUTING.md", "SECURITY.md"}


def api(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def judge(spdx):
    if not spdx or spdx == "NOASSERTION":
        return "禁止", "无许可证或未声明 —— 默认保留所有权利，不可商用"
    if spdx in OK_LICENSES:
        return "可用", "允许商用"
    if spdx in BLOCK_LICENSES:
        return "禁用", "传染性许可证 —— 商用需开源自身代码，本项目不可接受"
    return "待人工判断", "许可证为 %s，需人工确认商用条款" % spdx


def count_lines(d):
    content = d.get("content")
    if not content:
        return None
    txt = base64.b64decode(content).decode("utf-8", "ignore")
    return len([l for l in txt.split("\n") if l.strip()])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    repo = args[0]
    sub = ""
    if "--dir" in sys.argv:
        sub = sys.argv[sys.argv.index("--dir") + 1].strip("/") + "/"

    print("=" * 78)
    print("上游核实：%s" % repo)
    print("=" * 78)

    try:
        meta = api("https://api.github.com/repos/" + repo)
    except Exception as e:
        print("[错误] 无法获取仓库信息：%s" % e)
        return 1

    spdx = (meta.get("license") or {}).get("spdx_id")
    br = meta.get("default_branch", "main")
    if "--branch" in sys.argv:
        br = sys.argv[sys.argv.index("--branch") + 1]

    verdict, why = judge(spdx)
    print("  许可证    : %s" % (spdx or "无"))
    print("  判定      : 【%s】%s" % (verdict, why))
    print("  star      : %s" % meta.get("stargazers_count"))
    print("  仓库体积  : %s KB" % meta.get("size"))
    print("  最后推送  : %s" % (meta.get("pushed_at") or "")[:10])
    print("  默认分支  : %s" % br)

    if verdict != "可用":
        print("\n  ⚠️ 本仓库不建议导入。如确需使用，请先走法务与合规确认流程。")

    print("\n" + "-" * 78)
    print("文件清单与规模（目录：%s）" % (sub or "根目录"))
    print("-" * 78)
    try:
        listing = api("https://api.github.com/repos/%s/contents/%s?ref=%s"
                      % (repo, urllib.parse.quote(sub.rstrip("/")), br))
    except Exception as e:
        print("[错误] 无法列出目录：%s" % e)
        return 1

    total = 0
    stats = []
    for it in listing:
        if it["type"] != "file":
            print("  %-40s <目录>" % it["name"])
            continue
        if it["name"] in SKIP_NAMES:
            continue
        size = it.get("size", 0)
        if size > 2_000_000:
            print("  %-40s %9d B   (过大，跳过统计)" % (it["name"], size))
            continue
        try:
            d = api("https://api.github.com/repos/%s/contents/%s?ref=%s"
                    % (repo, urllib.parse.quote(sub + it["name"]), br))
            n = count_lines(d)
        except Exception:
            n = None
        if n is None:
            print("  %-40s %9d B   (无法统计)" % (it["name"], size))
        else:
            total += n
            stats.append((it["name"], n))
            print("  %-40s %9d B  → %8d 条" % (it["name"], size, n))
        time.sleep(0.6)

    print("-" * 78)
    print("  已统计文件 %d 个，合计约 %d 条（含重复与变体，未去重）" % (len(stats), total))
    print("\n  提示：导入前还须做四项加工——去重 / 归类重映射 / 剔除误伤词 / 补处置等级。")
    print("        详见 04-开源资源索引/SEC-006_开源词库资源.md §七。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
