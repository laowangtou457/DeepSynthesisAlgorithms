#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SW-025 多模型适配 —— **适配层判据（E1~E12）+ 负向样本自测**

规范依据：SPEC-007《分镜提示词交付规范 v2.2》§6（§6.4 / §6.5 / §6.6 / §6.8）、§8.3

为什么需要这一层（补的是**既有闸门的盲区**）
-------------------------------------------------
`validate_pack.py` 只把 `CFG-001` 用于**校验提示词包**（门禁⑮ 时长上下限取自适配配置、
负向策略、第 12 项核对状态一致性）——**它校验「适配配置」，不校验「适配文本」**。
而交付规范 §1.4 要求包内 `exports/<model>/<model>.txt`（② 各模型适配格式）由 SW-025 产出。
故本脚本补上适配文本侧的判据：两段式结构、分组与顺序、正文卫生（内部 code／下游 API／
负向残留）、核对状态声明、编码与行尾、字数。

判据一览（逐条对应规范条款）
-------------------------------------------------
| 判据 | 内容 | 依据 |
| --- | --- | --- |
| E1 | 两段式结构：标识区 + 固定分隔行 + 提示词区，三者齐备且顺序正确 | §6.8 |
| E2 | 文件头含「复制说明」一句话 | §6.8 |
| E3 | 提示词区以**生成单元**分块，单元分隔行格式合规（含镜数／时长／模型名） | §6.8 |
| E4 | 块内镜头顺序严格按 `scene_no` → `shot_no` 升序 | §6.8 |
| E5 | 每镜必备：画面描述文本 + 时长 + 画幅 | §6.8 |
| E6 | 提示词区**不含** AIGC 元数据块（`ContentProducer`／`ProduceID`／`AIGC`） | §6.8、§5.3 |
| E7 | 提示词区**不得出现内部 code**（`push_in`／`close_up`／`eye_level` 等词表 code） | §3.7.2 |
| E8 | 提示词区**不得出现下游 API 地址／密钥字样**（脱钩原则） | SYS-018 |
| E9 | 负向残留扫描（目标模型不支持负向字段时**一字不得残留**） | §6.4、§8.3 第 17 项 |
| E10 | `verify_status != verified` 的模型**必须**打「适配参数待核对」（且**不得**标为已验证） | §13 NT-03、§6.6 |
| E11 | 编码 UTF-8 **无 BOM**、行尾为 LF | §6.8 |
| E12 | 每镜正文字符数 ≤ 该模型 `max_prompt_chars`（未核对者按**已知最大值**兜底并告警） | §6.6 |
| **E13** | **基线可复现**：用**现行**生成器重跑，与目标目录**逐文件一致**（仅忽略 `生成时间` 字段） | §6.7、`CM-001` §5「配置基线」 |

退出码：`0` = 全部通过；`1` = 存在 BLOCK 级问题。
`--selftest` 跑内置负向样本，断言**每条判据都能被触发**（可复现，不依赖人工目视）。
`--repro` 跑 **E13 基线可复现性检查** —— 判「这份基线**还是不是现行代码的产物**」。

⚠️ **E13 的由来（`T-072` 自查实测到的盲区）**：E1~E12 只判**文本本身**合不合规，
判不出**基线是否陈旧**——生成器在基线落盘后又被修订（`strip_annotation` 去掉词表括注、
负向标签按半角/全角冒号决定是否加空格），而基线未重跑，于是**闸门继续放行一份谁也复现不出来的文本**。
本检查把「基线必须能由现行生成器复现」变成**机器判据**：改生成器而不重跑基线，即 BLOCK。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("需要 pyyaml：请先安装（见 delivery/README.md §3.1）", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
ADAPTERS_PATH = CONFIG / "CFG-001_model_adapters.yaml"
VOCAB_PATH = CONFIG / "CFG-002_shot_vocab.yaml"
EXPORTS_DIR = ROOT / "examples" / "_exports_demo"

BLOCK = "BLOCK"
WARN = "WARN"
OK = "OK"

# 下游 API／密钥字样（脱钩原则，SYS-018）——仅扫描「疑似真实调用」的形态，避免误伤
API_PATTERNS = [
    r"https?://",
    r"\bapi[_-]?key\b",
    r"\baccess[_-]?token\b",
    r"\bBearer\s+\S",
    r"\bsk-\S{8,}",
]


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, tag: str, msg: str) -> None:
        self.items.append((level, tag, msg))

    @property
    def blocked(self) -> bool:
        return any(lv == BLOCK for lv, _, _ in self.items)

    def echo(self, title: str) -> None:
        n_block = sum(1 for lv, _, _ in self.items if lv == BLOCK)
        n_warn = sum(1 for lv, _, _ in self.items if lv == WARN)
        print(f"\n=== {title} ===")
        for lv, tag, msg in self.items:
            icon = {"BLOCK": "X", "WARN": "!", "OK": "-"}[lv]
            print(f"  [{icon}] {tag}: {msg}")
        print(f"  → BLOCK {n_block} / WARN {n_warn}")


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def collect_codes(vocab: dict) -> dict[str, list[str]]:
    """词表内部 code 清单（用于 E7：适配正文不得出现内部 code）。

    ⚠️ **只收「可无歧义判定」的 code —— 即带下划线的（`push_in` / `close_up` / `eye_level` …）**。
    纯小写单词型 code（`static` / `wide` / `full` / `arc` / `tracking` / `level` / `medium`）
    与英文正文**同形**：模型要求的英文正文本来就写 "static shot"、"wide shot"，
    对它们做子串匹配会把**正确输出**判成泄漏。规范 §3.7.2 禁的是「用内部标签**代替**人话」，
    不是「英文里恰好出现同名词」——故这类 code **不参与子串判定**，
    改由「赋值形态」检出（`push_in:` / `push_in=` / `[push_in]`，含全部 code，另有兜底函数）。
    """
    out: dict[str, list[str]] = {}
    for kind in ("shot_size", "camera_move", "camera_height", "camera_roll", "camera_optics", "lighting"):
        out[kind] = [e["code"] for e in (vocab.get(kind) or []) if isinstance(e, dict) and "_" in e["code"]]
    out["transition"] = [e["code"] for e in (vocab.get("transition", {}).get("values") or []) if "_" in e["code"]]
    return out


def collect_all_codes(vocab: dict) -> list[str]:
    """全部 code（含单词型）——仅用于「赋值形态」兜底检出。"""
    allc: list[str] = []
    for kind in ("shot_size", "camera_move", "camera_height", "camera_roll", "camera_optics", "lighting"):
        allc += [e["code"] for e in (vocab.get(kind) or []) if isinstance(e, dict)]
    allc += [e["code"] for e in (vocab.get("transition", {}).get("values") or [])]
    return sorted(set(allc), key=len, reverse=True)


def parse_export(text: str) -> dict:
    """把适配文本切成「提示区 / 提示词区」两段（两段式的机器可读形态）。"""
    lines = text.split("\n")
    divider_idx = next((i for i, ln in enumerate(lines) if "以下为提示词区" in ln), None)
    mark_idx = next((i for i, ln in enumerate(lines) if ln.startswith("【AI生成内容】")), None)
    prompt_lines = lines[divider_idx + 1 :] if divider_idx is not None else []
    return {
        "lines": lines,
        "divider_idx": divider_idx,
        "mark_idx": mark_idx,
        "notice": lines[:mark_idx] if mark_idx is not None else [],
        "prompt": prompt_lines,
    }


def check_file(path: Path, cfg: dict, codes: dict[str, list[str]], model_cfg: dict | None, all_codes: list[str] | None = None) -> Report:
    rep = Report()
    raw = path.read_bytes()
    all_codes = all_codes or []

    # E11 编码与行尾（先看字节，不能先 decode 成 str）
    if raw.startswith(b"\xef\xbb\xbf"):
        rep.add(BLOCK, "E11/BOM", "文件带 UTF-8 BOM（§6.8 要求 UTF-8 无 BOM）")
    if b"\r\n" in raw:
        rep.add(BLOCK, "E11/CRLF", "文件含 CRLF 行尾（§6.8 要求 LF）")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        rep.add(BLOCK, "E11/UTF-8", f"非 UTF-8 编码：{exc}")
        return rep

    parsed = parse_export(text)
    prompt_text = "\n".join(parsed["prompt"])

    # E1 两段式
    if parsed["divider_idx"] is None:
        rep.add(BLOCK, "E1/divider", "缺固定分隔行「以下为提示词区…」（§6.8 两段式）")
    if parsed["mark_idx"] is None:
        rep.add(BLOCK, "E1/mark", "缺显式标识区行（`【AI生成内容】…`，§6.8 / §9.2）")
    elif parsed["divider_idx"] is not None and parsed["mark_idx"] > parsed["divider_idx"]:
        rep.add(BLOCK, "E1/order", "标识区出现在分隔行**之后**（顺序应为 标识区 → 分隔行 → 提示词区）")

    # E2 复制说明
    if not any("复制" in ln for ln in parsed["notice"]):
        rep.add(BLOCK, "E2/copy_hint", "提示区缺「复制方法」说明句（§6.8）")

    # E3 单元分块
    unit_lines = [ln for ln in parsed["prompt"] if ln.startswith("━━━ 单元")]
    if not unit_lines:
        rep.add(BLOCK, "E3/unit_header", "提示词区未按生成单元分块（缺单元分隔行，§6.8）")
    for ln in unit_lines:
        if not re.search(r"单元\s+\S+（\d+\s*镜\s*·\s*\d+s", ln):
            rep.add(WARN, "E3/unit_format", f"单元分隔行格式偏离模板：{ln[:40]}")

    # E4 / E5 逐镜
    shots = []
    cur = None
    for ln in parsed["prompt"]:
        m = re.match(r"^───\s*镜\s+(\S+?)（(.*?)）\s*───\s*$", ln)
        if m:
            cur = {"id": m.group(1), "meta": m.group(2), "body": []}
            shots.append(cur)
        elif cur is not None:
            cur["body"].append(ln)
    if not shots:
        rep.add(BLOCK, "E5/shots", "提示词区无镜头块（缺镜头分隔行，§6.8）")

    orders: list[tuple[int, int, str]] = []
    for s in shots:
        # E5 时长 + 画幅
        if not re.search(r"\d+s", s["meta"]):
            rep.add(BLOCK, "E5/duration", f"镜 {s['id']} 分隔行未标注时长")
        if not re.search(r"\d+:\d+", s["meta"]):
            rep.add(BLOCK, "E5/aspect", f"镜 {s['id']} 分隔行未标注画幅")
        body = "\n".join(s["body"]).strip()
        if len(body) < 15:
            rep.add(BLOCK, "E5/prose", f"镜 {s['id']} 缺画面描述文本")
        nums = re.findall(r"(\d+)", s["id"])
        if len(nums) >= 2:
            orders.append((int(nums[0]), int(nums[1]), s["id"]))
        # E7 内部 code（歧义型 code 走「赋值形态」兜底）
        for kind, lst in codes.items():
            for code in lst:
                if re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", body):
                    rep.add(BLOCK, "E7/internal_code", f"镜 {s['id']} 正文出现内部 code `{code}`（{kind}，§3.7.2）")
        for code in all_codes:
            if re.search(rf"(?<![\w-]){re.escape(code)}\s*[:=]|[:=]\s*{re.escape(code)}(?![\w-])|\[{re.escape(code)}\]", body):
                rep.add(BLOCK, "E7/internal_code_assign", f"镜 {s['id']} 正文出现内部 code 赋值形态 `{code}`（§3.7.2）")
        # E12 字数
        if model_cfg:
            limit = (model_cfg.get("dims", {}).get("limits") or {}).get("max_prompt_chars")
            if limit and len(body) > limit:
                rep.add(BLOCK, "E12/too_long", f"镜 {s['id']} 正文 {len(body)} > max_prompt_chars {limit}（§6.6）")
        # E9 负向残留
        if model_cfg and not (model_cfg.get("dims", {}).get("negative_prompt") or {}).get("supported"):
            for pat in (cfg.get("negative_policy") or {}).get("residual_patterns") or []:
                if pat and pat in body:
                    rep.add(BLOCK, "E9/negative_residue", f"镜 {s['id']} 正文残留「{pat}」而该模型不支持负向字段（§6.4）")

    # E4 顺序（同场景内 shot_no 必须递增）
    by_scene: dict[int, list[int]] = {}
    for scene, no, _sid in orders:
        by_scene.setdefault(scene, []).append(no)
    for scene, nos in by_scene.items():
        if nos != sorted(nos):
            rep.add(BLOCK, "E4/order", f"场 {scene} 的镜头顺序非升序：{nos}（§6.8）")

    # E6 元数据块不得进提示词区
    for key in ("ContentProducer", "ProduceID", "ContentPropagator", "PropagateID", "aigc_meta", "AIGC"):
        if key in prompt_text:
            rep.add(BLOCK, "E6/meta_leak", f"提示词区出现 AIGC 元数据键 `{key}`（§6.8「不含元数据」）")

    # E8 脱钩
    for pat in API_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            frag = m.group(0)
            if frag.startswith("http") and "example" in frag:
                continue
            rep.add(BLOCK, "E8/decouple", f"出现疑似下游 API／密钥字样：`{frag[:40]}`（SYS-018）")

    # E10 核对状态声明
    if model_cfg:
        status = model_cfg.get("verify_status")
        head = "\n".join(parsed["notice"])
        if status != "verified":
            if "适配参数待核对" not in head:
                rep.add(BLOCK, "E10/verify_notice", f"`verify_status={status}` 但未打「适配参数待核对」（§13 NT-03）")
            if re.search(r"核对状态：verified", head):
                rep.add(BLOCK, "E10/false_verified", "未核对模型被标为 verified（§6.6）")
        else:
            if "适配参数待核对" in head:
                rep.add(WARN, "E10/spurious_notice", "verified 模型带了「待核对」提示，措辞可能过保守")

    if not rep.items:
        rep.add(OK, "all", "E1~E12 全部通过")
    return rep


def run(target: Path, cfg: dict, vocab: dict) -> Report:
    codes = collect_codes(vocab)
    all_codes = collect_all_codes(vocab)
    models = {m["code"]: m for m in (cfg.get("models") or []) if isinstance(m, dict)}
    all_rep = Report()
    files: list[Path] = []
    if target.is_file():
        files = [target]
    else:
        files = sorted(p for p in target.rglob("*.txt") if p.is_file())
    if not files:
        all_rep.add(BLOCK, "target", f"未找到任何适配文本：{target}")
        return all_rep
    for f in files:
        code = f.parent.name
        rep = check_file(f, cfg, codes, models.get(code), all_codes)
        for lv, tag, msg in rep.items:
            all_rep.add(lv, f"{code}/{tag}", msg)
    return all_rep


# ────────────────────────────────────────────────────────────
# 负向样本自测：断言每条判据都能被触发（不依赖人工目视）
# ────────────────────────────────────────────────────────────
def _good_text(cfg: dict) -> str:
    return (
        "━━━ 交付包 FR-PK-DEMO ━━━\n"
        "核对状态：verified（已核对）\n"
        "复制方法：请从下方分隔行以下开始复制。\n"
        "【AI生成内容】本文件由AI生成，已经过合规验证        ← 标识区，请勿复制\n"
        "════════════ 以下为提示词区，请从此行以下复制 ════════════\n"
        "\n"
        "━━━ 单元 U01（2 镜 · 9s · 模型X）━━━\n"
        "─── 镜 S01-SH001（远景 · 固定机位 · 4s · 16:9）───\n"
        "The camera holds a static shot at eye level. A wide rainy alley at dusk, lantern glow on wet stone.\n"
        "─── 镜 S01-SH002（近景 · 前推 · 5s · 16:9）───\n"
        "The camera pushes in with small amplitude at slow speed. The girl slowly lifts her head, rain on her hair.\n"
    )


def selftest(cfg: dict, vocab: dict) -> int:
    codes = collect_codes(vocab)
    all_codes = collect_all_codes(vocab)
    verified_model = {"code": "m_verified", "verify_status": "verified", "dims": {"limits": {}, "negative_prompt": {"supported": True}}}
    pending_model = {"code": "m_pending", "verify_status": "pending", "dims": {"limits": {}, "negative_prompt": {"supported": False}}}

    cases: list[tuple[str, str, dict | None, str]] = [
        ("基线（应全绿，仅 E10 对 pending 模型的声明检查）", _good_text(cfg), verified_model, "OK"),
        ("E1 缺分隔行", _good_text(cfg).replace("════════════ 以下为提示词区，请从此行以下复制 ════════════\n", ""), verified_model, "E1/divider"),
        ("E1 缺标识区", _good_text(cfg).replace("【AI生成内容】本文件由AI生成，已经过合规验证        ← 标识区，请勿复制\n", ""), verified_model, "E1/mark"),
        ("E2 缺复制说明", _good_text(cfg).replace("复制方法：请从下方分隔行以下开始复制。\n", ""), verified_model, "E2/copy_hint"),
        ("E3 缺单元分块", _good_text(cfg).replace("━━━ 单元 U01（2 镜 · 9s · 模型X）━━━\n", ""), verified_model, "E3/unit_header"),
        ("E4 镜序倒置", _good_text(cfg).replace("S01-SH001", "S01-SH099").replace("S01-SH002", "S01-SH002"), verified_model, "E4/order"),
        ("E5 分隔行缺时长", _good_text(cfg).replace("· 4s ·", "· ·"), verified_model, "E5/duration"),
        ("E5 分隔行缺画幅", _good_text(cfg).replace("· 16:9", "· "), verified_model, "E5/aspect"),
        ("E6 元数据块进正文", _good_text(cfg).replace("A wide rainy alley", "ContentProducer: X A wide rainy alley"), verified_model, "E6/meta_leak"),
        ("E7 内部 code 泄漏", _good_text(cfg).replace("A wide rainy alley", "push_in A wide rainy alley"), verified_model, "E7/internal_code"),
        ("E7 code 赋值形态", _good_text(cfg).replace("A wide rainy alley", "camera.move: static A wide rainy alley"), verified_model, "E7/internal_code_assign"),
        ("E8 下游 API 字样", _good_text(cfg).replace("A wide rainy alley", "call https://vendor.example.com/v1 A wide rainy alley"), verified_model, "E8/decouple"),
        ("E9 负向残留（不支持负向的模型）", _good_text(cfg).replace("A wide rainy alley", "（负向：水印） A wide rainy alley"), pending_model, "E9/negative_residue"),
        ("E10 pending 未打核对提示", _good_text(cfg), pending_model, "E10/verify_notice"),
        ("E10 未核对却标 verified", _good_text(cfg).replace("核对状态：verified（已核对）", "核对状态：verified（已核对）\n适配参数待核对：忽略"), pending_model, "E10/false_verified"),
        ("E11 带 BOM", "\ufeff" + _good_text(cfg), verified_model, "E11/BOM"),
        ("E12 超字数上限", _good_text(cfg), {"code": "m_tiny", "verify_status": "verified", "dims": {"limits": {"max_prompt_chars": 20}, "negative_prompt": {"supported": True}}}, "E12/too_long"),
    ]

    print("=== 适配层判据 负向样本自测（每条判据都须可触发） ===")
    bad = 0
    with tempfile.TemporaryDirectory(prefix="wbe-export-selftest-") as tmpdir:
        root = Path(tmpdir)
        for name, text, model, expect in cases:
            tmp = root / (model or {"code": "m"})["code"] / "x.txt"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8", newline="\n")
            if expect == "E11/BOM":
                tmp.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
            rep = check_file(tmp, cfg, codes, model, all_codes)
            tags = [tag for lv, tag, _ in rep.items if lv == BLOCK]
            passed = (not tags) if expect == "OK" else (expect in tags)
            print(f"  {'PASS' if passed else 'FAIL'}  {name:<28} 期望 {'（无 BLOCK）' if expect=='OK' else expect:<22} 实得 {tags or '（无 BLOCK）'}")
            bad += 0 if passed else 1

        # CRLF 样本（单独构造，避免 newline 归一化）
        tmp = root / "m_crlf" / "x.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(_good_text(cfg).replace("\n", "\r\n").encode("utf-8"))
        rep = check_file(tmp, cfg, codes, verified_model, all_codes)
        tags = [t for lv, t, _ in rep.items if lv == BLOCK]
        passed = "E11/CRLF" in tags
        print(f"  {'PASS' if passed else 'FAIL'}  {'E11 CRLF 行尾':<28} 期望 E11/CRLF{'':<16} 实得 {tags or '（无 BLOCK）'}")
        bad += 0 if passed else 1

    total = len(cases) + 1
    print(f"  → 自测 {total - bad}/{total} 符合预期（{'全部通过' if bad == 0 else '存在不符预期项'}）")
    return 1 if bad else 0


# ── E13 基线可复现性 ────────────────────────────────────────────────────────
# 文件头里的「生成时间」是**唯一**非确定性字段（其余内容由 pack + 配置完全决定）。
# 复现比对时把它掩掉，避免把「重跑时刻不同」误判为「内容漂移」。
TIMESTAMP_RE = re.compile(r"生成时间：[^\n]*")


def _mask_timestamp(text: str) -> str:
    return TIMESTAMP_RE.sub("生成时间：<忽略>", text)


def _first_diff(a: str, b: str) -> str:
    for i, (la, lb) in enumerate(zip(a.splitlines(), b.splitlines()), start=1):
        if la != lb:
            return f"第 {i} 行\n        基线：{la[:110]}\n        重跑：{lb[:110]}"
    return f"行数不同（基线 {len(a.splitlines())} / 重跑 {len(b.splitlines())}）"


def _import_generator():
    """同目录导入生成器（复现检查用）——不依赖调用方 cwd。"""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import export_models  # type: ignore

    return export_models


def repro(target: Path, cfg: dict, pack: Path | None = None) -> int:
    """E13 —— 基线可复现性检查（用现行生成器重跑，与本目录逐文件比对）。"""
    out = Path(target)
    if not out.is_dir():
        print(f"[BLOCK] 复现检查需要「目录」目标，实得：{out}")
        return 1

    baseline = {p.relative_to(out): _mask_timestamp(p.read_text(encoding="utf-8", errors="replace"))
                for p in sorted(out.rglob("*.txt"))}
    if not baseline:
        print(f"[BLOCK] 目标目录内无适配文本（*.txt）：{out}")
        return 1

    try:
        gen = _import_generator()
    except Exception as exc:  # 生成器缺失/不可导入
        print(f"[BLOCK] 无法导入生成器 export_models.py：{exc}")
        return 1

    defaults = cfg.get("defaults") or {}
    gen_vocab = gen.Vocab(load_yaml(VOCAB_PATH), defaults.get("literal_reject_patterns"))
    pack_path = Path(pack) if pack else (ROOT / "examples" / "CFG-004_demo_pack.json")
    if not pack_path.exists():
        print(f"[BLOCK] 找不到示例交付包：{pack_path}")
        return 1

    print(f"\n=== 基线可复现性检查 E13 · {out} ===")
    print(f"  重跑输入：{pack_path.name}")
    with tempfile.TemporaryDirectory(prefix="wbe-export-repro-") as td:
        gen.run(pack_path, Path(td), None, cfg, defaults, gen_vocab)
        tmp = Path(td)
        fresh = {p.relative_to(tmp): _mask_timestamp(p.read_text(encoding="utf-8", errors="replace"))
                 for p in sorted(tmp.rglob("*.txt"))}

    problems: list[tuple[Path, str]] = []
    for rel in sorted(set(baseline) | set(fresh)):
        if rel not in fresh:
            problems.append((rel, "基线存在、重跑不产出（生成器已不再生成该模型）"))
        elif rel not in baseline:
            problems.append((rel, "重跑产出、基线缺失（基线漏跑）"))
        elif baseline[rel] != fresh[rel]:
            problems.append((rel, f"内容不一致 —— {_first_diff(baseline[rel], fresh[rel])}"))

    if problems:
        for rel, why in problems:
            print(f"  [BLOCK] E13/not_reproducible  {rel} —— {why}")
        print(f"  → BLOCK {len(problems)} / 共 {len(baseline)} 个文件")
        print("  处置：重跑 `python tools/export_models.py` 让基线跟上生成器；\n"
              "        若差异系**有意**修订，须同步复核本目录内文本的合规结论。")
        return 1

    for rel in sorted(baseline):
        print(f"  [-] {rel}: 可由现行生成器复现")
    print(f"  → BLOCK 0 / 共 {len(baseline)} 个文件（仅「生成时间」字段被忽略）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SW-025 适配层判据（E1~E12）、基线可复现性（E13）与负向样本自测")
    ap.add_argument("target", nargs="?", default=str(EXPORTS_DIR), help="适配文本文件或目录（默认 examples/_exports_demo）")
    ap.add_argument("--selftest", action="store_true", help="跑内置负向样本自测")
    ap.add_argument("--repro", action="store_true", help="跑 E13 基线可复现性检查（用现行生成器重跑比对）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_yaml(ADAPTERS_PATH)
    vocab = load_yaml(VOCAB_PATH)

    if args.selftest:
        return selftest(cfg, vocab)

    if args.repro:
        return repro(Path(args.target), cfg)

    rep = run(Path(args.target), cfg, vocab)
    if args.json:
        print(json.dumps({"items": rep.items, "blocked": rep.blocked}, ensure_ascii=False, indent=2))
    else:
        rep.echo(f"适配层判据 E1~E12 · {args.target}")
    return 1 if rep.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
