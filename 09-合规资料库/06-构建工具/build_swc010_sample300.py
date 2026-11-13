# -*- coding: utf-8 -*-
"""`T-109` 工具件①：SW-010 扩量 300 例「分层抽检输入清单」生成器（PRO-009/SEC-016 配套）。

定位与边界
----------
- 抽检对象是**实际生成的产物**（PRO-009 §2），产物池的前置是**题库全量/子集跑测**
  （尚未执行）⇒ 本清单先落**输入侧**：从题库（GB/T 45654—2025 §8.2，31 类）按层
  抽出 300 条测试输入，供跑测批次逐条送双闸，产物落盘后回填机器 action 再交人工判读。
- ⚠️ **判定主体必须是真人**（T-109 铁律：AI 代劳即伪造举证）——本工具只产清单与
  机器侧预跑占位列，**不产生任何人工结论**。
- ⚠️ 受控四类（A1-01/02/03/05）实体内容在受控区、工程内 jsonl 仅模板注释 ⇒
  这四类输出**占位行**（只记分类码，不涉任何明文），条目 ID 由受控环境补录。
- 分层：非受控类按工程内条数比例分配 260 例（每类下限 5），受控四类各 10 例占位。
- 随机种子固定（可复现可审计）；输出 md 清单（工具产物，非登记文档；
  正式台账仍以 SEC-016 为准）。

跑法
----
    python build_swc010_sample300.py                # 生成/覆盖清单
    python build_swc010_sample300.py --check        # 只校验不写盘
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
BANK = HERE.parent / "02-生成内容测试题库"
MANIFEST = BANK / "bank_manifest.json"
ITEMS = BANK / "题目"
OUT_MD = HERE / "SEC-016_sample300_工具产物.md"

TOTAL = 300
N_CONTROLLED_PER = 10          # 受控四类各占位例数
SEED = 20261113
MIN_PER_CATEGORY = 5          # 非受控类下限

CONTROLLED = {"A1-01", "A1-02", "A1-03", "A1-05"}


def load_categories():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return m["categories"]


def load_items(cat_id: str):
    """读工程内该类 jsonl 的题目（跳过模板注释行；受控类返回空）。"""
    rows = []
    p = ITEMS / f"{cat_id}.jsonl"
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def allocate(cats):
    """非受控按条数比例分 260，每类下限 MIN_PER_CATEGORY。"""
    pool = []
    for c in cats:
        if c["id"] in CONTROLLED:
            continue
        n = len(load_items(c["id"]))
        pool.append((c["id"], n))
    total = sum(n for _, n in pool)
    quota = {cid: max(MIN_PER_CATEGORY, round(TOTAL - N_CONTROLLED_PER * len(CONTROLLED)) * n // total)
             for cid, n in pool}
    # 收敛到恰好 260：按配额从大到小微调
    target = TOTAL - N_CONTROLLED_PER * len(CONTROLLED)
    diff = target - sum(quota.values())
    order = sorted(quota, key=lambda k: -quota[k])
    i = 0
    while diff != 0 and order:
        cid = order[i % len(order)]
        step = 1 if diff > 0 else -1
        if quota[cid] + step >= MIN_PER_CATEGORY:
            quota[cid] += step
            diff -= step
        i += 1
    return quota


def main(check_only: bool = False):
    cats = load_categories()
    quota = allocate(cats)
    rng = random.Random(SEED)
    rows = []
    no = 0
    # 非受控类：按 id 序逐类抽样
    for c in cats:
        cid = c["id"]
        if cid in CONTROLLED:
            continue
        items = load_items(cid)
        k = min(quota[cid], len(items))
        picked = rng.sample(items, k) if k else []
        for it in picked:
            no += 1
            rows.append((f"R-{no:03d}", cid, it.get("id", ""), it.get("severity", ""),
                         it.get("topic", ""), "待跑测回填", "", "", "", ""))
        if k < quota[cid]:
            print(f"WARN: {cid} 工程内仅 {len(items)} 条 < 配额 {quota[cid]}")
    # 受控类：占位行
    for cid in sorted(CONTROLLED):
        for _ in range(N_CONTROLLED_PER):
            no += 1
            rows.append((f"R-{no:03d}", cid, "（受控区条目，经受控环境补录 ID）", "",
                         "", "待受控环境跑测", "", "", "", ""))
    assert no == TOTAL, f"总例数 {no} != {TOTAL}"

    n_by_cat: dict[str, int] = {}
    for r in rows:
        n_by_cat[r[1]] = n_by_cat.get(r[1], 0) + 1

    lines = []
    lines.append("# SEC-016 扩量 300 例·抽检输入清单（工具产物）")
    lines.append("")
    lines.append("> ⚠️ **本文件是 `T-109` 工具件①（`build_swc010_sample300.py`）的输出，属工具产物、非登记文档**；")
    lines.append("> 正式人工抽检台账仍以 `SEC-016` 为准（判读结论回填处）。判定主体**必须是真人**（`T-109` 铁律）。")
    lines.append("")
    lines.append("| 项 | 内容 |")
    lines.append("|---|---|")
    lines.append(f"| 生成时间 | 2026-11-13（种子 {SEED}，可复现） |")
    lines.append(f"| 例数 | {TOTAL}（非受控 {TOTAL - N_CONTROLLED_PER * len(CONTROLLED)} ＋ 受控占位 {N_CONTROLLED_PER * len(CONTROLLED)}） |")
    lines.append("| 用途 | 跑测批次按本清单逐条送双闸 → 产物回填机器 action → 人工判读（抽检人≠复核人，复核 ≥10%） |")
    lines.append("| 前置 | 题库子集跑测未执行 ⇒ `机器 action` 列全部为占位，跑测完成后回填 |")
    lines.append("")
    lines.append("## 层次分布")
    lines.append("")
    lines.append("| 分类 | 例数 |")
    lines.append("|---|---|")
    for cid in sorted(n_by_cat):
        lines.append(f"| {cid} | {n_by_cat[cid]} |")
    lines.append("")
    lines.append("## 清单")
    lines.append("")
    lines.append("| 例号 | 分类 | 题目 ID | severity | topic | 机器 action | 抽检人 | 复核人 | 人工结论 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    content = "\n".join(lines) + "\n"

    if check_only:
        print(f"CHECK OK: {no} rows, categories={len(n_by_cat)}")
        return
    OUT_MD.write_bytes(content.encode("utf-8"))
    print(f"WROTE {OUT_MD} rows={no} bytes={len(content.encode('utf-8'))}")
    for cid in sorted(n_by_cat):
        print(f"  {cid}: {n_by_cat[cid]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    main(ap.parse_args().check)
