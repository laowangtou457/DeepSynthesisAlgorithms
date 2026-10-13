#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交付包校验工具（delivery pack validator）

规范依据：NORM-DELIVERY-001《分镜提示词交付规范 v1.3》（现行版；V1.1→V1.3 技术内容逐字未变、章节结构未变动，故 §8.3 门禁 18 项判据不变）
          §3.8 校验 / §4.2 质量门 / §4.3 单元划分 / §4.5 语速 / §4.6 动作预算
          §6.4 负向归位 / §6.6 时长上下限 / §8.3 交付前自检（18 项）
对应需求：SW-007、SW-013、SW-014、SW-022、SW-025、SW-026

作用：作为交付前的强制门禁，对提示词包与交付清单做结构、内容质量、一致性与合规校验。
      任一 BLOCK 级问题不通过，则不允许生成交付包。

★ v1.1 新增校验（依导演视角评审 D-02/04/05/06/11/22）：
    ⑪ 生成单元划分（每单元 2–3 镜、单元内运镜类型不重复、无单镜单元）
    ⑫ 镜头语言质量门（11 阈值，逐单元 + 整片；容差算法与 audit_shots.py 一致）
    ⑬ 台词—时长语速（≤ 9 字/秒）
    ⑭ 动作三段状态（action.start/change/end）
    ⑮ 时长上下限与整秒（上下限取自 config/model_adapters.yaml，不在本脚本硬编码）
    ⑯ 运镜幅度/速度与 static/pov 的互斥、camera.roll 与 camera.move 重复计
    ⑰ 负向残留（目标模型不支持负向字段时，文本中不得残留负向写法）
    ⑱ 风格锚点封闭（prompt 中不得出现锚点清单之外的已知风格词）

用法：
    python validate_pack.py                          # 校验 examples/ 下全部示例
    python validate_pack.py path/to/pack.json        # 校验指定提示词包
    python validate_pack.py --no-quality-gate <p>    # 跳过质量门（不推荐）

退出码：0 = 全部通过；1 = 存在 BLOCK 级问题
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    jsonschema = None
    Draft202012Validator = None

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE / "schemas"
CONFIG = HERE / "config"
EXAMPLES = HERE / "examples"

BLOCK = "BLOCK"
WARN = "WARN"

# 提示词中不得出现的参数指令（规范 §3.7.6）
PARAM_PATTERN = re.compile(r"(^|\s)--(ar|v|style|stylize|chaos|no)\b", re.I)
# 显式标识必须含「AI」或「人工智能」+「生成」或「合成」（GB 45438 §5.4）
MARK_PATTERN = re.compile(r"(AI|人工智能).*(生成|合成)", re.I)
# 中文引号（H3 画面可见文字必须用英文双引号）（规范 §3.7.6）
CJK_QUOTE_RE = re.compile(r"[\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f]")

# ── 镜头语言质量门（规范 §4.2；阈值与 audit_shots.py 的 GATE 一致）────────────
GATE = {
    "运镜覆盖": 1.00,
    "景别覆盖": 1.00,
    "静止镜占比": 0.40,      # 上限
    "运镜类型数": 5,          # 下限（实际阈值按镜数缩放）
    "单一运镜占比": 0.35,     # 上限
    "角度覆盖": 0.40,
    "光学覆盖": 0.30,
    "构图覆盖": 0.50,
    "轴线覆盖": 0.30,
    "光线覆盖": 0.40,
    "画面结果覆盖": 0.60,
}

# 中文语速可行阈值（规范 §4.5）
MAX_CHARS_PER_SECOND = 9.0


class Report:
    def __init__(self, name: str) -> None:
        self.name = name
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, code: str, msg: str) -> None:
        self.items.append((level, code, msg))

    @property
    def blocked(self) -> bool:
        return any(lv == BLOCK for lv, _, _ in self.items)

    def render(self) -> str:
        status = "未通过" if self.blocked else "通过"
        lines = [f"\n{'=' * 74}", f"校验对象：{self.name}  →  {status}", "=" * 74]
        if not self.items:
            lines.append("  无问题")
        for lv, code, msg in self.items:
            icon = "X" if lv == BLOCK else "!"
            lines.append(f"  [{icon}] {lv:<5} {code:<26} {msg}")
        return "\n".join(lines)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path):
    if yaml is None:
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ceil(x: float) -> int:
    return int(math.ceil(x))


def _allow(ratio: float, n: int) -> int:
    """占比型门槛 → 绝对个数（至少 1 个）。与 audit_shots.py 的 _allow 同算法。"""
    return max(1, _ceil(ratio * n))


def check_schema(data, schema_path: Path, rep: Report, tag: str) -> None:
    if Draft202012Validator is None:
        rep.add(WARN, "schema.missing", "未安装 jsonschema，跳过 Schema 校验（pip install jsonschema）")
        return
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    for e in errors:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        rep.add(BLOCK, f"schema.{tag}", f"{loc}: {e.message}")


# ──────────────────────────────────────────────────────────────────────────
# 镜头语言质量门（结构化口径）
# ──────────────────────────────────────────────────────────────────────────
def quality_gate_for(shots: list[dict]) -> tuple[dict, list[str]]:
    """按结构化字段计算 11 项指标并给出未达标项。

    说明：规范 §4.2 要求对「适配投喂文本」跑 audit_shots.py；本函数是对
    **结构化字段**的等价口径，用于在打包前做第一道拦截。两者都通过才算数。
    """
    n = len(shots)
    if not n:
        return {}, ["无镜头"]

    def has(s, path):
        cur = s
        for k in path.split("."):
            if not isinstance(cur, dict) or not cur.get(k):
                return False
            cur = cur[k]
        return True

    cam_types = [s.get("camera", {}).get("move") for s in shots if s.get("camera", {}).get("move")]
    static_cnt = sum(1 for t in cam_types if t == "static")
    from collections import Counter
    top_type, top_cnt = (Counter(cam_types).most_common(1) or [("—", 0)])[0]

    metrics = {
        "景别覆盖": sum(1 for s in shots if s.get("shot_size")) / n,
        "运镜覆盖": sum(1 for s in shots if s.get("camera", {}).get("move")) / n,
        "角度覆盖": sum(1 for s in shots if s.get("camera", {}).get("height")) / n,
        "光学覆盖": sum(1 for s in shots if s.get("camera", {}).get("optics")) / n,
        "构图覆盖": sum(1 for s in shots if has(s, "shot_language.composition")) / n,
        "轴线覆盖": sum(1 for s in shots if has(s, "shot_language.axis")) / n,
        "光线覆盖": sum(1 for s in shots if s.get("lighting")) / n,
        "画面结果覆盖": sum(1 for s in shots if has(s, "shot_language.result")) / n,
        "静止镜占比": static_cnt / n,
        "单一运镜占比": top_cnt / n,
        "运镜类型数": float(len(set(cam_types))),
        "_top_camera_type": top_type,
        "_top_camera_count": top_cnt,
        "_static_count": static_cnt,
        "_shots": n,
    }

    bad: list[str] = []
    for label in ("运镜覆盖", "景别覆盖", "角度覆盖", "光学覆盖",
                  "构图覆盖", "轴线覆盖", "光线覆盖", "画面结果覆盖"):
        if metrics[label] < GATE[label]:
            bad.append(f"{label} {metrics[label]:.0%} < 门槛 {GATE[label]:.0%}")
    # ⚠️ 占比型门槛必须按 **_allow() 的「允许绝对个数」** 比较，**不得**用比例直接比阈值。
    #    原因（2026-10-13 随 SW-007 自查发现并修正）：小样本下比例会被离散化放大——
    #    n=2 时「1 个静止镜」的比例是 50%，直接比 40% 必判 FAIL，而容差算法的本意正是
    #    `max(1, ceil(ratio*n))`：2 镜单元**允许 1 个**静止镜。参照实现 `audit_shots.py`
    #    与本工程 `prompts/validate_output.py`（R19）用的都是计数比较，唯本处曾用比例 →
    #    同一产物出现「本脚本 BLOCK、另两个通过」的矛盾结论（实测：U04 2 镜 1 static）。
    #    本函数 docstring 早已声明「容差算法与 audit_shots.py 一致」，此处为**实现笔误**。
    st_allow = _allow(GATE["静止镜占比"], n)
    if static_cnt > st_allow:
        bad.append(f"静止镜 {static_cnt}/{n} 个 > 允许 {st_allow} 个"
                   f"（上限 {GATE['静止镜占比']:.0%}）")
    top_allow = _allow(GATE["单一运镜占比"], n)
    if top_cnt > top_allow:
        bad.append(f"单一运镜（{top_type}）{top_cnt}/{n} 个 > 允许 {top_allow} 个"
                   f"（上限 {GATE['单一运镜占比']:.0%}）")
    need = min(GATE["运镜类型数"], max(2, _ceil(n / 4)))
    if metrics["运镜类型数"] < need:
        bad.append(f"运镜类型数 {int(metrics['运镜类型数'])} < 门槛 {need}（{n} 镜）")
    return metrics, bad


def render_gate(rep: Report, metrics: dict, bad: list[str], scope: str, level: str) -> None:
    if not metrics:
        rep.add(BLOCK, "gate.empty", f"{scope}：无镜头")
        return
    line = (f"{scope} {int(metrics['_shots'])}镜｜"
            f"景别{metrics['景别覆盖']:.0%} 运镜{metrics['运镜覆盖']:.0%} "
            f"角度{metrics['角度覆盖']:.0%} 光学{metrics['光学覆盖']:.0%} "
            f"构图{metrics['构图覆盖']:.0%} 轴线{metrics['轴线覆盖']:.0%} "
            f"光线{metrics['光线覆盖']:.0%} 结果{metrics['画面结果覆盖']:.0%}｜"
            f"静止{metrics['静止镜占比']:.0%} 类型数{int(metrics['运镜类型数'])}")
    if bad:
        rep.add(level, "gate.fail", f"{line} → 未达标：" + "；".join(bad))
    else:
        rep.add(WARN, "gate.pass", f"{line} → 全部质量门通过")


# ──────────────────────────────────────────────────────────────────────────
# 主校验
# ──────────────────────────────────────────────────────────────────────────
def validate_pack(pack_path: Path, run_gate: bool = True) -> Report:
    rep = Report(str(pack_path.relative_to(HERE)) if HERE in pack_path.parents else pack_path.name)
    data = load_json(pack_path)

    vocab = load_yaml(CONFIG / "shot_vocab.yaml") or {}
    adapters = load_yaml(CONFIG / "model_adapters.yaml") or {}

    # ① Schema 校验
    check_schema(data, SCHEMAS / "shot_prompt_pack.v1.schema.json", rep, "pack")

    meta = data.get("meta", {}) or {}
    shots = data.get("shots", []) or []
    units = data.get("units", []) or []
    chars = data.get("characters", []) or []
    style = data.get("style_bible", {}) or {}
    aigc = (data.get("aigc_meta", {}) or {}).get("AIGC", {})

    shot_by_id = {s.get("shot_id"): s for s in shots}

    # ② 一致性校验：锚点引用必须命中（规范 §3.8）
    style_ids = {style.get("style_id")}
    char_ids = {c.get("character_id") for c in chars}
    for s in shots:
        if s.get("style_ref") not in style_ids:
            rep.add(BLOCK, "consistency.style_ref",
                    f"镜头 {s.get('shot_id')} 的 style_ref={s.get('style_ref')!r} 未命中 style_bible.style_id")
        for cr in s.get("character_refs", []) or []:
            if cr not in char_ids:
                rep.add(BLOCK, "consistency.character_ref",
                        f"镜头 {s.get('shot_id')} 引用不存在的 character_id={cr!r}")

    # ③ 时长合计一致（规范 §3.8）
    total = meta.get("total_duration_ms")
    if isinstance(total, int) and shots:
        ssum = sum(int(s.get("duration_ms", 0)) for s in shots)
        if ssum != total:
            rep.add(BLOCK, "consistency.duration",
                    f"meta.total_duration_ms={total} 与镜头时长合计 {ssum} 不一致")

    # ④ 元数据块：存在、字段齐全、唯一（规范 §5.3 / §5.4）
    if not aigc:
        rep.add(BLOCK, "meta.aigc", "缺少 aigc_meta.AIGC 元数据块（违反隐式标识义务，《标识办法》§5）")
    else:
        required = ["Label", "ContentProducer", "ProduceID", "ReservedCode1",
                    "ContentPropagator", "PropagateID", "ReservedCode2"]
        for k in required:
            if k not in aigc:
                rep.add(BLOCK, "meta.field", f"元数据块缺字段 {k}")
        if aigc.get("ProduceID") and meta.get("pack_id") and aigc["ProduceID"] != meta["pack_id"]:
            rep.add(BLOCK, "meta.produce_id",
                    f"ProduceID={aigc.get('ProduceID')!r} 与 meta.pack_id={meta.get('pack_id')!r} 不一致")
        if aigc.get("ContentPropagator") != aigc.get("ContentProducer"):
            rep.add(WARN, "meta.propagator",
                    "首次写入时 ContentPropagator 应等于 ContentProducer（规范 §5.1）")
        if aigc.get("PropagateID") != aigc.get("ProduceID"):
            rep.add(WARN, "meta.propagate_id",
                    "首次写入时 PropagateID 应等于 ProduceID（规范 §5.1）")
        raw = pack_path.read_text(encoding="utf-8")
        if raw.count('"AIGC"') > 1:
            rep.add(BLOCK, "meta.duplicate",
                    f'文件中出现 {raw.count(chr(34) + "AIGC" + chr(34))} 次 "AIGC" 块；GB 45438 要求仅保留一份')

    # ⑤ 提供者编码占位检查（规范 §13 NT-02）
    provider_code = (meta.get("generator", {}) or {}).get("provider_code", "")
    if "{{" in str(provider_code) or not provider_code:
        rep.add(WARN, "provider.code",
                "provider_code 仍为占位（{{PROVIDER_CODE}}）→ 不得用于正式交付，须回填（NT-02）")

    # ⑥ 任务类型声明（规范 §3.2 / D-21）
    if not meta.get("task_type"):
        rep.add(BLOCK, "task.type", "缺少 meta.task_type（规范 §3.2）")
    if not meta.get("unsupported_task_types"):
        rep.add(WARN, "task.unsupported",
                "缺少 meta.unsupported_task_types：留空会让客户以为支持本期未覆盖的生成形态")

    # ⑦ 提示词不得含参数指令 / 中文引号（规范 §3.7.6）
    for s in shots:
        for f in ("prompt_zh", "prompt_en"):
            v = s.get(f) or ""
            if PARAM_PATTERN.search(v):
                rep.add(WARN, "prompt.param",
                        f"镜头 {s.get('shot_id')} 的 {f} 含参数指令，应移入结构化字段")
        if CJK_QUOTE_RE.search(s.get("prompt_en") or ""):
            rep.add(WARN, "prompt.quote",
                    f"镜头 {s.get('shot_id')} 的 prompt_en 含中文引号；画面可见文字必须用英文双引号（§3.7.6）")

    # ⑧ 合规状态（规范 §8.3 第 1/2/7/9 项）
    comp = meta.get("compliance", {}) or {}
    sc = comp.get("safety_check", {}) or {}
    if sc.get("input") != "passed" or sc.get("output") != "passed":
        rep.add(BLOCK, "compliance.safety", "输入/输出内容安全检测未通过 → 阻断交付（SW-009/010）")
    mk = comp.get("marking_check", {}) or {}
    if mk.get("explicit") != "present" or mk.get("implicit") != "present":
        rep.add(BLOCK, "compliance.marking", "标识完整性校验未通过 → 阻断交付（SW-014）")
    if not comp.get("statement_id"):
        rep.add(BLOCK, "compliance.statement", "缺少合规声明编号 → 阻断交付（SW-026）")

    # ⑨ 词表取值校验（规范 §3.7）
    if vocab:
        sizes = {v["code"] for v in vocab.get("shot_size", [])}
        moves = {v["code"] for v in vocab.get("camera_move", []) if isinstance(v, dict) and v.get("code")}
        lights = {v.get("code") for v in vocab.get("lighting", []) if isinstance(v, dict)}
        heights = {v.get("code") for v in vocab.get("camera_height", []) if isinstance(v, dict)}
        rolls = {v.get("code") for v in vocab.get("camera_roll", []) if isinstance(v, dict)}
        optics = {v.get("code") for v in vocab.get("camera_optics", []) if isinstance(v, dict)}
        amps = set((vocab.get("camera_amplitude", {}) or {}).get("values", []) or [])
        speeds = set((vocab.get("camera_speed", {}) or {}).get("values", []) or [])
        deprecated = vocab.get("deprecated_alias", {}) or {}
        trans = {v.get("code") for v in (vocab.get("transition", {}) or {}).get("values", []) if isinstance(v, dict)}

        for s in shots:
            sid = s.get("shot_id")
            if s.get("shot_size") not in sizes:
                rep.add(BLOCK, "vocab.shot_size", f"镜头 {sid} 的 shot_size 不在词表：{s.get('shot_size')!r}")
            cam = s.get("camera", {}) or {}
            mv = cam.get("move")
            if mv not in moves:
                if mv in deprecated:
                    rep.add(BLOCK, "vocab.camera_alias",
                            f"镜头 {sid} 使用了已弃用别名 camera.move={mv!r} → 应迁移为 {deprecated[mv]!r}（§3.7.2）")
                else:
                    rep.add(BLOCK, "vocab.camera_move", f"镜头 {sid} 的 camera.move 不在词表：{mv!r}")

            # ⑯ 幅度/速度与 static/pov 互斥、roll 重复计
            no_amp = {c["code"] for c in vocab.get("camera_move", [])
                      if isinstance(c, dict) and c.get("no_amplitude_no_speed")}
            if mv in no_amp and (cam.get("amplitude") or cam.get("speed")):
                rep.add(BLOCK, "camera.amp_speed",
                        f"镜头 {sid} 的 camera.move={mv} 不得携带幅度/速度（§3.7.2）")
            if cam.get("amplitude") and cam["amplitude"] not in amps:
                rep.add(WARN, "vocab.amplitude", f"镜头 {sid} 的 camera.amplitude 不在词表：{cam['amplitude']!r}")
            if cam.get("speed") and cam["speed"] not in speeds:
                rep.add(WARN, "vocab.speed", f"镜头 {sid} 的 camera.speed 不在词表：{cam['speed']!r}")
            if cam.get("height") and cam["height"] not in heights:
                rep.add(BLOCK, "vocab.height", f"镜头 {sid} 的 camera.height 不在词表：{cam['height']!r}")
            if cam.get("roll") and cam["roll"] not in rolls:
                rep.add(BLOCK, "vocab.roll", f"镜头 {sid} 的 camera.roll 不在词表：{cam['roll']!r}")
            if cam.get("optics") and cam["optics"] not in optics:
                rep.add(BLOCK, "vocab.optics", f"镜头 {sid} 的 camera.optics 不在词表：{cam['optics']!r}")
            if cam.get("move") in ("roll_cw", "roll_ccw") and cam.get("roll") == cam.get("move"):
                rep.add(BLOCK, "camera.roll_dup",
                        f"镜头 {sid} 把 roll 同时写进 camera.move 与 camera.roll → 会被重复计为两种运镜（§3.7.3）")

            lt = s.get("lighting")
            if lt and lt not in lights:
                rep.add(WARN, "vocab.lighting", f"镜头 {sid} 的 lighting 不在词表：{lt!r}")
            for f in ("transition_in", "transition_out"):
                tv = s.get(f)
                if tv and trans and tv not in trans:
                    rep.add(BLOCK, "vocab.transition", f"镜头 {sid} 的 {f} 不在词表：{tv!r}")
        if style.get("lighting_default") and style["lighting_default"] not in lights:
            rep.add(WARN, "vocab.lighting_default",
                    f"style_bible.lighting_default 不在词表：{style.get('lighting_default')!r}")

    # ⑩ 生成单元划分（规范 §4.3 / 评审 D-05）
    unit_ids = [u.get("unit_id") for u in units]
    if not units:
        rep.add(BLOCK, "unit.missing", "缺少 units[] 生成单元（规范 §3.5）——单镜粒度交付结构上不达标")
    if len(set(unit_ids)) != len(unit_ids):
        rep.add(BLOCK, "unit.duplicate_id", f"units[].unit_id 存在重复：{unit_ids}")
    covered: list[str] = []
    for u in units:
        uid = u.get("unit_id")
        sids = u.get("shot_ids", []) or []
        if not (2 <= len(sids) <= 3):
            rep.add(BLOCK, "unit.size",
                    f"单元 {uid} 含 {len(sids)} 镜；必须 ∈ [2, 3]（1 镜单元结构性不达标，§4.3）")
        for sid in sids:
            if sid not in shot_by_id:
                rep.add(BLOCK, "unit.shot_missing", f"单元 {uid} 引用了不存在的 shot_id={sid!r}")
            covered.append(sid)
        types = [shot_by_id[s].get("camera", {}).get("move") for s in sids if s in shot_by_id]
        dup = {t for t in types if types.count(t) > 1}
        if dup:
            rep.add(BLOCK, "unit.camera_dup",
                    f"单元 {uid} 内运镜类型重复：{sorted(dup)} → 单元内运镜类型不得重复（§4.3）")
        if not u.get("soundscape"):
            rep.add(BLOCK, "unit.soundscape", f"单元 {uid} 缺少 soundscape（H3 overall_soundscape 投影源）")
        if not u.get("music"):
            rep.add(WARN, "unit.music", f"单元 {uid} 缺少 music（无配乐应填 N/A）")

    for s in shots:
        if s.get("shot_id") not in covered:
            rep.add(BLOCK, "unit.orphan", f"镜头 {s.get('shot_id')} 不属于任何生成单元（§3.5）")
        uid = s.get("unit_id")
        if uid and uid not in set(unit_ids):
            rep.add(BLOCK, "unit.ref", f"镜头 {s.get('shot_id')} 的 unit_id={uid!r} 未命中 units[]")

    # ⑪ 镜头语言质量门（规范 §4.2 / 评审 D-06）
    if run_gate and shots:
        metrics, bad = quality_gate_for(shots)
        render_gate(rep, metrics, bad, "整片", BLOCK)
        for u in units:
            uid = u.get("unit_id")
            us = [shot_by_id[s] for s in (u.get("shot_ids") or []) if s in shot_by_id]
            if us:
                um, ubad = quality_gate_for(us)
                render_gate(rep, um, ubad, f"单元 {uid}", BLOCK)

    # ⑫ 台词—时长语速（规范 §4.5 / 评审 D-11）
    for s in shots:
        dlg = (s.get("dialogue") or "").strip()
        if not dlg:
            continue
        # 去掉括号提示（如「（旁白）」）与标点后再计数
        core = re.sub(r"[（(][^）)]*[）)]", "", dlg)
        core = re.sub(r"[，。！？、；：,.!?;:\s\"'「」『』]", "", core)
        n_chars = len(core)
        if not n_chars:
            continue
        secs = int(s.get("duration_ms", 0)) / 1000
        if secs <= 0:
            continue
        rate = n_chars / secs
        if rate > MAX_CHARS_PER_SECOND:
            need_ms = int(math.ceil(n_chars / MAX_CHARS_PER_SECOND)) * 1000
            rep.add(BLOCK, "dialogue.rate",
                    f"镜头 {s.get('shot_id')} 台词 {n_chars} 字 / {secs:g}s = {rate:.1f} 字/秒 "
                    f"> {MAX_CHARS_PER_SECOND:g} → 须延长时长至 ≥ {need_ms}ms（只延时不改画面，§4.5）")

    # ⑬ 动作三段状态（规范 §4.6 / 评审 D-10）
    for s in shots:
        act = s.get("action")
        if not isinstance(act, dict) or not all(act.get(k) for k in ("start", "change", "end")):
            rep.add(WARN, "action.incomplete",
                    f"镜头 {s.get('shot_id')} 的 action 缺少 start/change/end 之一（§4.6）")

    # ⑭ 时长上下限与整秒（规范 §6.6 / 评审 D-04）
    window = None
    if adapters:
        mins, maxes = [], []
        for m in adapters.get("models", []) or []:
            if m.get("priority") == "P3" or not m.get("export_filename"):
                continue
            lim = (m.get("dims", {}) or {}).get("limits", {}) or {}
            if lim.get("min_duration_ms"):
                mins.append(lim["min_duration_ms"])
            if lim.get("max_duration_ms"):
                maxes.append(lim["max_duration_ms"])
        if mins and maxes:
            window = (max(mins), min(maxes))
    for s in shots:
        d = s.get("duration_ms")
        if not isinstance(d, int):
            continue
        if d % 1000 != 0:
            rep.add(BLOCK, "duration.integer",
                    f"镜头 {s.get('shot_id')} 时长 {d}ms 非整秒——模型侧不接受毫秒精度（§6.6）")
        if window:
            lo, hi = window
            if d < lo:
                rep.add(BLOCK, "duration.min",
                        f"镜头 {s.get('shot_id')} 时长 {d}ms < 适配模型下发下限 {lo}ms → "
                        f"合并相邻镜头或延长至下限，只延时不改画面（§6.6）")
            if d > hi:
                rep.add(WARN, "duration.max",
                        f"镜头 {s.get('shot_id')} 时长 {d}ms > 适配模型最小上限 {hi}ms → 需按 §6.6 拆分")

    # ⑮ 负向残留（规范 §6.4 / 评审 D-02）
    if adapters:
        np_policy = adapters.get("negative_policy", {}) or {}
        patterns = np_policy.get("residual_patterns", []) or []
        unsupported = [m.get("display_name") for m in (adapters.get("models", []) or [])
                       if (m.get("dims", {}) or {}).get("negative_prompt", {}).get("supported") is False]
        if unsupported and patterns:
            for s in shots:
                for f in ("prompt_zh", "prompt_en"):
                    v = s.get(f) or ""
                    for p in patterns:
                        if p and p in v:
                            rep.add(BLOCK, "negative.residue",
                                    f"镜头 {s.get('shot_id')} 的 {f} 含负向残留 {p!r}；"
                                    f"{'/'.join(unsupported)} 不支持负向字段，须转写为正向约束句（§6.4）")
                            break

    # ⑯ 风格锚点封闭（规范 §3.3 / 评审 D-17）
    anchors = style.get("style_anchors") or []
    if style and not anchors:
        rep.add(BLOCK, "style.anchors", "缺少 style_bible.style_anchors（固定 3–5 条，§3.3）")
    elif vocab:
        known = set((vocab.get("style_tags", {}) or {}).get("items", []) or [])
        outside = known - set(anchors)
        for s in shots:
            for f in ("prompt_zh", "prompt_en"):
                v = s.get(f) or ""
                hit = {w for w in outside if w in v}
                if hit:
                    rep.add(WARN, "style.drift",
                            f"镜头 {s.get('shot_id')} 的 {f} 出现锚点清单之外的风格词 {sorted(hit)}（§3.3）")

    # ⑰ 时间格式（规范 §3.2）
    for field, val in (("meta.created_at", meta.get("created_at")),
                       ("compliance.safety_check.checked_at", sc.get("checked_at"))):
        if val:
            try:
                datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except ValueError:
                rep.add(BLOCK, "time.format", f"{field} 不是合法 ISO 8601 时间：{val!r}")

    return rep


def validate_manifest(path: Path, pack_rep: Report | None) -> Report:
    rep = Report(f"{path.name}（交付清单）")
    data = load_json(path)
    check_schema(data, SCHEMAS / "manifest.v1.schema.json", rep, "manifest")

    # 四件套齐备（规范 §1.1）
    for key, label in (("shot_prompt_pack", "① 提示词集"), ("aigc_meta", "② AIGC 元数据块"),
                       ("overlay_assets", "③ 标识素材包"), ("compliance_statement", "④ 合规声明")):
        art = (data.get("artifacts", {}) or {}).get(key, {}) or {}
        if not art.get("present"):
            rep.add(BLOCK, "artifact.missing", f"{label} 缺失 → 阻断交付（SW-014）")

    # 质量门报告（规范 §8.3 第 13 项）
    qg = (data.get("artifacts", {}) or {}).get("quality_gate_report", {}) or {}
    if not qg.get("present"):
        rep.add(BLOCK, "artifact.quality_gate",
                "缺少 qa/audit_report.txt 镜头语言质量门报告 → 阻断交付（§8.3 第 13 项）")

    # 导出文件必须含显式标识（《标识办法》§4 末段 / SW-022）
    for e in data.get("exports", []) or []:
        if not e.get("explicit_mark"):
            rep.add(BLOCK, "export.mark", f"{e.get('file')} 未注入显式标识 → 阻断导出（SW-022）")
        if not e.get("implicit_mark"):
            rep.add(WARN, "export.meta", f"{e.get('file')} 未注入隐式标识")
        if str(e.get("format")).lower() == "txt" and not e.get("two_section"):
            rep.add(WARN, "export.section",
                    f"{e.get('file')} 未标注两段式（标识区 + 提示词区）——全选复制会把标识粘进模型（§6.8）")

    # 交付前自检 18 项（规范 §8.3）
    checks = {c.get("no"): c for c in data.get("self_check", []) or []}
    for i in range(1, 19):
        if i not in checks:
            rep.add(BLOCK, "selfcheck.missing", f"自检第 {i} 项缺失（规范 §8.3 共 18 项）")
        elif checks[i].get("result") == "fail":
            rep.add(BLOCK, "selfcheck.fail", f"自检第 {i} 项未通过：{checks[i].get('item')}")

    # 第 12 项与适配核对状态一致（规范 §8.3）
    pending = [a for a in data.get("adapters", []) or []
               if a.get("verify_status") in ("pending", "partial")]
    if pending and checks.get(12, {}).get("result") == "pass":
        rep.add(WARN, "adapter.status",
                f"{len(pending)} 个适配为 pending/partial，但自检第 12 项标为 pass（应标 warn）")

    # 第 13 项与质量门结论一致
    gate = data.get("quality_gate", {}) or {}
    if gate.get("passed") is True and checks.get(13, {}).get("result") != "pass":
        rep.add(WARN, "gate.status", "quality_gate.passed=true 但自检第 13 项非 pass，请核对")

    # 第 18 项须有记录（规范 §8.3 / D-23）
    hr = data.get("human_review", []) or []
    if not hr:
        rep.add(BLOCK, "human_review.missing",
                "缺少人工核对记录（角色一致性 / 跨镜连续性，§8.3 第 18 项）——无记录视为未做")
    else:
        for h in hr:
            missing = [k for k in ("result", "checked_at", "operator") if not h.get(k)]
            if missing:
                rep.add(BLOCK, "human_review.field",
                        f"人工核对记录缺字段 {missing}（须记结果 + 时间 + 检查人）")

    # 负向支持状态与残留结论一致（规范 §6.4）
    for a in data.get("adapters", []) or []:
        if a.get("negative_prompt_supported") is False and a.get("negative_residue_check") != "pass":
            rep.add(BLOCK, "adapter.negative",
                    f"{a.get('model_display')} 不支持负向字段，但未标记 negative_residue_check=pass（§8.3 第 17 项）")

    if pack_rep is not None:
        pids = {data.get("pack_id")}
        if None in pids or "" in pids:
            rep.add(WARN, "manifest.pack_id", "交付清单未填写 pack_id")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="交付包校验工具（NORM-DELIVERY-001 v1.3 §8.3 门禁）")
    ap.add_argument("targets", nargs="*", help="提示词包 JSON 路径；缺省校验 examples/ 下全部")
    ap.add_argument("--no-quality-gate", action="store_true",
                    help="跳过镜头语言质量门（不推荐；仅用于中间态调试）")
    args = ap.parse_args()

    targets = [Path(t) for t in args.targets] if args.targets else sorted(EXAMPLES.glob("*pack*.json"))
    reports: list[Report] = []

    for t in targets:
        if not t.exists():
            r = Report(t.name)
            r.add(BLOCK, "file", "文件不存在")
            reports.append(r)
            continue
        r = validate_pack(t, run_gate=not args.no_quality_gate)
        reports.append(r)
        mf = t.parent / "demo_manifest.json"
        if mf.exists():
            reports.append(validate_manifest(mf, r))

    out = "\n".join(r.render() for r in reports)
    blocked = sum(1 for r in reports if r.blocked)
    warns = sum(1 for r in reports for lv, _, _ in r.items if lv == WARN)
    print(out)
    print(f"\n{'=' * 74}")
    print(f"汇总：{len(reports)} 个对象 ｜ BLOCK 不通过 {blocked} 个 ｜ WARN {warns} 条")
    print("门禁结论：" + ("X 不允许生成交付包" if blocked else "OK 允许生成交付包（WARN 项需人工确认）"))
    print("=" * 74)
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
