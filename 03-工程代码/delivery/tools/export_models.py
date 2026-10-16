#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SW-025 多模型提示词适配 —— 适配文本生成器（**配置驱动**）

规范依据：SPEC-007《分镜提示词交付规范 v2.2》§6（尤其 §6.1 / §6.5 / §6.6 / §6.7 / §6.8）

设计纪律（与 SW-025 验收标准逐条对应）
-------------------------------------------------
1. **配置驱动，新增模型不改代码**（§6.7「必须」）——逐模型差异全部读
   `config/CFG-001_model_adapters.yaml` 的 `export_rules`，本脚本只做「按声明执行」。
2. **基准唯一 + 单向投影**（§6.1）——正文来源是交付包内的 `prompt_zh` / `prompt_en`
   （§4.1「八维双落地」已保证八维写进正文），本脚本**不改写、不重组、不润色**；
   适配层只做三件事：① 字段 code → 目标模型字面（`model_map` 投影）；
   ② 按 `export_rules` 追加模型专属行（镜头语言 / 负向字段 / 音轨）；
   ③ 按 §6.6 做**可见的**降级处置与告警。
3. **不悄悄改数字**——`duration_ms` 一律原样承继；低于下限 / 高于上限 / 非整秒
   只**登记告警**，不擅自拆分或延长（那属导演决策，须回上游处置）。
4. **不装点合规**——`verified` 之外的模型一律在提示词区之外打「适配参数待核对」，
   不得标为已验证（§13 NT-03）。
5. **脱钩**（SYS-018）——本脚本不出现任何下游 API 地址、密钥字段或调用逻辑。

用法
-------------------------------------------------
    python tools/export_models.py examples/CFG-004_demo_pack.json
    python tools/export_models.py <pack.json> --out <dir> --models minimax_h3,kling
    python tools/export_models.py <pack.json> --json          # 机器可读摘要
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("需要 pyyaml：请先安装（jsonschema / pyyaml 见 delivery/README.md §3.1）", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
ADAPTERS_PATH = CONFIG / "CFG-001_model_adapters.yaml"
VOCAB_PATH = CONFIG / "CFG-002_shot_vocab.yaml"
DEFAULT_OUT = ROOT / "examples" / "_exports_demo"

CN_TZ = timezone(timedelta(hours=8))

# 受保护句的识别词：含这些词元的句子在裁剪时不得删除（§6.6「禁止删除主体动作与镜头语言」）
PROTECT_TERMS = ["机位", "镜头", "运镜", "the camera", "The camera", "camera"]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def strip_annotation(text: str) -> str:
    """去掉词表里给人工看的括注：`the shot transitions to（降级）` → `the shot transitions to`。"""
    if not isinstance(text, str):
        return text
    return re.sub(r"[（(][^（()）]*[)）]\s*$", "", text).strip()


class Vocab:
    """CFG-002 镜头词表索引 —— 「内部 code → 各模型字面」的唯一投影源。

    `literal_reject_patterns`（来自 `CFG-001.defaults`）用于剔除词表里**给人看的参数注解**：
    例 · 可灵 `pan_left` 的「六轴水平摇负值」是注解（该怎么设参数），不是措辞（该怎么说）；
    命中注解者退到该条的 `model_map.fallback`，无 fallback 再退到中文字面。
    —— 这条规则写在 `CFG-001` 里，不在代码里，故新增模型仍只改配置。
    """

    KINDS = ("shot_size", "camera_move", "camera_height", "camera_roll", "camera_optics")

    def __init__(self, vocab: dict, reject_patterns: list[str] | None = None):
        self.raw = vocab
        self.reject = [re.compile(p) for p in (reject_patterns or [])]
        self.index: dict[str, dict[str, dict]] = {}
        for kind in self.KINDS:
            self.index[kind] = {e["code"]: e for e in (vocab.get(kind) or []) if isinstance(e, dict)}
        self.lighting = {e["code"]: e for e in (vocab.get("lighting") or []) if isinstance(e, dict)}
        self.transition = {e["code"]: e for e in (vocab.get("transition", {}).get("values") or [])}

    def _usable(self, lit: str | None) -> bool:
        if not lit:
            return False
        return not any(r.search(lit) for r in self.reject)

    def literal(self, kind: str, code: str | None, model_code: str, lang: str) -> str | None:
        if not code:
            return None
        if kind == "lighting":
            entry = self.lighting.get(code)
            if not entry:
                return None
            return entry.get("en") if lang == "en" else entry.get("zh")
        if kind == "transition":
            entry = self.transition.get(code)
            if not entry:
                return None
            mm = entry.get("model_map") or {}
            for cand in (mm.get(model_code), mm.get("fallback")):
                if self._usable(cand):
                    return strip_annotation(cand)
            return entry.get("zh")
        entry = self.index.get(kind, {}).get(code)
        if not entry:
            return None
        mm = entry.get("model_map") or {}
        for cand in (mm.get(model_code), mm.get("fallback")):
            if self._usable(cand):
                return strip_annotation(cand)
        return strip_annotation(entry.get("en") if lang == "en" else entry.get("zh"))

    def zh(self, kind: str, code: str | None) -> str:
        """供**分隔行**使用的中文字面（分隔行是给人看的，不按模型投影）。"""
        if not code:
            return ""
        if kind == "transition":
            entry = self.transition.get(code)
        elif kind == "lighting":
            entry = self.lighting.get(code)
        else:
            entry = self.index.get(kind, {}).get(code)
        return strip_annotation((entry or {}).get("zh", ""))


def seconds(ms: int | None) -> float | None:
    if ms is None:
        return None
    return round(ms / 1000.0, 3)


def fmt_seconds(ms: int | None) -> str:
    """模型侧不接受毫秒精度（§6.6）——展示层一律整秒。"""
    if ms is None:
        return "?"
    return f"{int(round(ms / 1000.0))}"


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[。！？；.!?;])\s*", text.strip())
    return [p for p in (s.strip() for s in parts) if p]


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def trim_by_priority(text: str, limit: int, drop_terms: list[str]) -> tuple[str, list[str]]:
    """§6.6 长度超限的裁剪优先级：缩短风格串 → 删修饰性形容词 → 精简环境描述。

    **禁止**删除主体动作与镜头语言句（`PROTECT_TERMS` 命中即受保护）。
    返回 (裁剪后文本, 处置记录)。裁到保护句为止仍超限则原文返回并如实登记。
    """
    if not text or limit is None or len(text) <= limit:
        return text, []
    sentences = split_sentences(text)
    protected = [any(t in s for t in PROTECT_TERMS) for s in sentences]
    actions: list[str] = []

    # 第 1 优先级：缩短风格串（含 style_anchors 的句子整体删除）
    for i in range(len(sentences) - 1, -1, -1):
        if len(text) <= limit:
            break
        if protected[i] or i == 0:
            continue
        if any(t and t in sentences[i] for t in drop_terms):
            actions.append(f"缩短风格串：删除「{sentences[i][:18]}…」")
            text = text.replace(sentences[i], "")
            sentences[i] = ""

    # 第 2 优先级：删除修饰性形容词从句（「，」后带形容词性修饰的短从句）
    if len(text) > limit:
        text2 = re.sub(r"[，,](?:极其|非常|十分|格外|略显|轻微地|缓缓地|静静地)[^，。；]{0,12}(?=[，。；])", "", text)
        if len(text2) < len(text):
            actions.append("删修饰性形容词")
            text = text2

    # 第 3 优先级：精简环境描述（从尾部删除非保护句）
    if len(text) > limit:
        sentences = split_sentences(text)
        protected = [any(t in s for t in PROTECT_TERMS) for s in sentences]
        for i in range(len(sentences) - 1, 0, -1):
            if len(text) <= limit:
                break
            if protected[i]:
                continue
            actions.append(f"精简环境描述：删除「{sentences[i][:18]}…」")
            text = text.replace(sentences[i], "")

    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > limit:
        actions.append(f"⚠️ 已按优先级裁尽仍超限（{len(text)} > {limit}），保留原文交人工处置")
    return text, actions


def pick_prose(shot: dict, lang: str) -> tuple[str, str]:
    """按模型语言倾向取正文来源；返回 (正文, 所用字段名)。**不改写**。"""
    zh = (shot.get("prompt_zh") or "").strip()
    en = (shot.get("prompt_en") or "").strip()
    if lang == "en":
        return (en or zh), ("prompt_en" if en else "prompt_zh")
    return (zh or en), ("prompt_zh" if zh else "prompt_en")


class Adapter:
    """一个模型的适配渲染器 —— 逐模型差异全部来自 CFG-001 的声明。"""

    def __init__(self, cfg: dict, defaults: dict, vocab: Vocab, model: dict):
        self.cfg = cfg
        self.defaults = defaults
        self.vocab = vocab
        self.model = model
        self.code = model["code"]
        self.dims = model.get("dims") or {}
        self.rules = model.get("export_rules") or {}
        self.limits = self.dims.get("limits") or {}
        self.notices: list[str] = []
        self.actions: list[str] = []
        lang_pref = self.dims.get("language_preference") or "zh_primary"
        self.lang = "en" if lang_pref == "en_primary" else "zh"

    # ── 渲染 ────────────────────────────────────────────────
    def camera_line(self, shot: dict) -> str | None:
        cam = shot.get("camera") or {}
        parts: list[str] = []
        size = self.vocab.literal("shot_size", shot.get("shot_size"), self.code, self.lang)
        if size:
            parts.append(size)
        move = self.vocab.literal("camera_move", cam.get("move"), self.code, self.lang)
        if move:
            parts.append(move)
        for kind, key in (("camera_height", "height"), ("camera_roll", "roll"), ("camera_optics", "optics")):
            lit = self.vocab.literal(kind, cam.get(key), self.code, self.lang)
            if lit:
                parts.append(lit)
        # 转场仅在**非默认切**时单独成行（`cut` 是默认衔接，写出来没有信息量；
        # 且各平台对 `cut` 的 model_map 多为「平台行为说明」而非措辞——见 §6.5 映射表）
        trans_code = shot.get("transition_in")
        if self.rules.get("transition_line") and trans_code and trans_code != "cut":
            trans = self.vocab.literal("transition", trans_code, self.code, self.lang)
            if trans:
                parts.append(trans)
        return "，".join(parts) if parts else None

    def dialogue_line(self, dialogue: str) -> str:
        """台词行 —— 逐模型语言铁律由 `export_rules.dialogue_format` 声明（§6.4）。"""
        fmt = self.rules.get("dialogue_format")
        if fmt == "d_tag_chinese":
            return f"<d>[Chinese]{dialogue}</d>"        # H3：中文只允许出现在 <d>[Chinese]…</d>
        return f"对白：{dialogue}" if self.lang == "zh" else f'Dialogue: "{dialogue}"'

    def negative_line(self, shot: dict, unit: dict) -> str | None:
        """负向归位（§6.4）——**支持独立负向字段的模型才装配**；不支持的模型一字不加。

        来源优先级：`shots[].negative_prompt` → `style_bible.negative_global`。
        """
        np_cfg = self.dims.get("negative_prompt") or {}
        label = self.rules.get("negative_label")
        if not label or not np_cfg.get("supported"):
            return None
        words = shot.get("negative_prompt") or (self.pack.get("style_bible") or {}).get("negative_global") or []
        if not words:
            return None
        sep = " " if label.endswith(":") else ""
        joiner = ", " if self.lang == "en" else "，"
        return f"{label}{sep}{joiner.join(words)}"

    def shot_block(self, shot: dict, unit: dict) -> str:
        sep_tpl = self.defaults.get("shot_separator", "─── 镜 {shot_id} ───")
        cam = shot.get("camera") or {}
        head = (
            sep_tpl.replace("{shot_id}", str(shot.get("shot_id", "")))
            .replace("{shot_size_zh}", self.vocab.zh("shot_size", shot.get("shot_size")))
            .replace("{camera_move_zh}", self.vocab.zh("camera_move", cam.get("move")))
            .replace("{duration_s}", fmt_seconds(shot.get("duration_ms")))
            .replace("{aspect_ratio}", str(shot.get("aspect_ratio") or self.pack.get("meta", {}).get("aspect_ratio_default") or ""))
        )

        prose, field = pick_prose(shot, self.lang)
        prose, acts = trim_by_priority(prose, self.limits.get("max_prompt_chars"), self._drop_terms())
        for a in acts:
            self.actions.append(f"{shot.get('shot_id')}：{a}（{field}）")

        lines = [head, prose]
        if self.rules.get("camera_line") == "appended":
            cam_line = self.camera_line(shot)
            if cam_line:
                prefix = "镜头" if self.lang == "zh" else "Camera"
                lines.append(f"{prefix}：{cam_line}" if self.lang == "zh" else f"{prefix}: {cam_line}.")
        elif self.rules.get("camera_line") == "embedded":
            # H3：运镜必须是正文内的**独立句**（§6.4）——只核不补，避免重复
            if not re.search(r"(^|[.。!！?？]\s*)The camera\b", prose):
                self.notices.append(f"⚠️ 镜 {shot.get('shot_id')}：正文未以独立句出现 `The camera`（§6.4），属上游缺陷须回退")

        dialogue = (shot.get("dialogue") or "").strip()
        if dialogue and dialogue not in ("", "（无）"):
            lines.append(self.dialogue_line(dialogue))
        sfx = (shot.get("sfx") or "").strip()
        if sfx:
            lines.append(f"音效：{sfx}" if self.lang == "zh" else f"SFX: {sfx}")
        neg = self.negative_line(shot, unit)
        if neg:
            lines.append(neg)

        self._check_duration(shot)
        if self.rules.get("camera_line") == "embedded":
            self._check_residue(shot, prose)
        return "\n".join(lines)

    def unit_block(self, unit: dict, shots: list[dict]) -> str:
        sep_tpl = self.defaults.get("unit_separator", "━━━ 单元 {unit_id} ━━━")
        total = sum(int(s.get("duration_ms") or 0) for s in shots)
        head = (
            sep_tpl.replace("{unit_id}", str(unit.get("unit_id", "")))
            .replace("{shot_count}", str(len(shots)))
            .replace("{unit_duration_s}", fmt_seconds(total))
            .replace("{model_display}", self.model.get("display_name", self.code))
        )
        body = [head]
        sound = self.dims.get("sound") or {}
        if sound.get("fields"):
            sc = (unit.get("soundscape") or "").strip()
            mu = (unit.get("music") or "").strip()
            if sc:
                body.append(f"[单元音轨] 环境声：{sc}" if self.lang == "zh" else f"[Unit audio] Soundscape: {sc}")
                if self.dims.get("language_hard_constraint") and self.lang == "en" and has_cjk(sc):
                    self.notices.append(
                        f"⚠️ 单元 {unit.get('unit_id')}：环境声为中文，而本模型要求英文基底且**语言倾向不得覆盖硬约束**（§6.3 第 1 维）"
                        " —— 属**上游字段缺英文**，须回上游补写，本脚本不代译"
                    )
            if mu:
                body.append(f"[单元音轨] 配乐：{mu}" if self.lang == "zh" else f"[Unit audio] Music: {mu}")
        for shot in shots:
            body.append(self.shot_block(shot, unit))
        return "\n".join(body)

    # ── 告警 ────────────────────────────────────────────────
    def _check_duration(self, shot: dict) -> None:
        ms = shot.get("duration_ms")
        if ms is None:
            return
        lo, hi = self.limits.get("min_duration_ms"), self.limits.get("max_duration_ms")
        sid = shot.get("shot_id")
        if lo and ms < lo:
            self.notices.append(f"⚠️ 镜 {sid} 时长 {ms}ms < 本模型下限 {lo}ms —— 按 §6.6 应延长至下限或与相邻镜合并（**本脚本不擅自改时长**，请回上游处置）")
        if hi and ms > hi:
            self.notices.append(f"⚠️ 镜 {sid} 时长 {ms}ms > 本模型上限 {hi}ms —— 按 §6.6 应按语义边界拆分（`shot_id` 加 `-a`/`-b`，**本脚本不擅自拆分**）")
        if self.limits.get("integer_seconds_only") and ms % 1000 != 0:
            self.notices.append(f"⚠️ 镜 {sid} 时长 {ms}ms 非整秒 —— 展示层已取整为 {fmt_seconds(ms)}s，源头数值未改（§6.6）")

    def _check_residue(self, shot: dict, prose: str) -> None:
        pats = (self.cfg.get("negative_policy") or {}).get("residual_patterns") or []
        for p in pats:
            if p and p in prose:
                self.notices.append(f"⚠️ 镜 {shot.get('shot_id')}：正文命中负向残留模式「{p}」，而本模型不支持负向字段（§6.4）")

    def _drop_terms(self) -> list[str]:
        anchors = (self.pack.get("style_bible") or {}).get("style_anchors") or []
        return [a for a in anchors if isinstance(a, str)]

    # ── 组装整文件 ──────────────────────────────────────────
    def render(self, pack: dict) -> str:
        self.pack = pack
        meta = pack.get("meta") or {}
        shots = pack.get("shots") or []
        units = pack.get("units") or []

        # ⚠️ 顺序敏感：必须**先渲染正文区**（渲染期才产生时长／残留／语言告警），再组装提示区。
        blocks: list[str] = []
        for unit in units:
            uid = unit.get("unit_id")
            u_shots = [s for s in shots if s.get("unit_id") == uid]
            u_shots.sort(key=lambda s: (s.get("scene_no") or 0, s.get("shot_no") or 0))
            if u_shots:
                blocks.append(self.unit_block(unit, u_shots))
        leftovers = [s for s in shots if not any(s.get("unit_id") == u.get("unit_id") for u in units)]
        if leftovers:
            self.notices.append(
                f"⚠️ {len(leftovers)} 个镜头的 `unit_id` 未被任何单元收录，已按 `scene_no`/`shot_no` 追加在末尾（**不丢弃**）"
            )
            blocks.append(
                self.unit_block(
                    {"unit_id": "UNASSIGNED"},
                    sorted(leftovers, key=lambda s: (s.get("scene_no") or 0, s.get("shot_no") or 0)),
                )
            )

        hdr_tpl = self.defaults.get("file_header", "━━━ 交付包 {pack_id} ━━━\n")
        created = datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        header = (
            hdr_tpl.replace("{pack_id}", str(meta.get("pack_id", "")))
            .replace("{model_display}", str(self.model.get("display_name", self.code)))
            .replace("{unit_count}", str(len(units)))
            .replace("{shot_count}", str(len(shots)))
            .replace("{total_duration_s}", fmt_seconds(meta.get("total_duration_ms")))
            .replace("{created_at}", created)
        ).rstrip("\n")

        status = self.model.get("verify_status", "pending")
        status_line = {
            "verified": "核对状态：verified（已按官方文档／本项目实测核对，可直接交付）",
            "partial": "核对状态：partial（结构写法已核对，**部分数值待官方核对**）",
            "pending": "核对状态：pending（**待核对**）",
        }.get(status, f"核对状态：{status}")

        notice_zone: list[str] = [header, status_line]
        if status != "verified":
            pend = self.model.get("verify_pending")
            pend_txt = f"：{' / '.join(map(str, pend))}" if pend else ""
            notice_zone.append(
                f"[适配参数待核对] {self.model.get('display_name', self.code)} 的数值项{pend_txt} 待按官方文档核对 —— "
                "**本文件不得作为「照做就行」的样板**（规范 §13 NT-03）"
            )
        for extra in self.rules.get("extra_notices") or []:
            notice_zone.append(f"[适配说明] {extra}")
        notice_zone.append(self._adapt_summary(meta))
        notice_zone.extend(self.notices)
        if self.actions:
            notice_zone.append("[长度裁剪执行记录] " + "；".join(self.actions))
        notice_zone.append(self.defaults.get("copy_hint", "复制方法：请从下方分隔行以下开始复制。"))

        explicit = self.rules.get("explicit_mark_text") or self.defaults.get("explicit_mark_text", "本文件由AI生成，已经过合规验证")
        mark = self.defaults.get("mark_section", "【AI生成内容】{explicit_text}").replace("{explicit_text}", explicit)
        divider = self.defaults.get("mark_divider", "════════════ 以下为提示词区 ════════════")

        return "\n".join(notice_zone) + "\n" + mark + "\n" + divider + "\n\n" + "\n\n".join(blocks) + "\n"

    def _adapt_summary(self, meta: dict) -> str:
        unsupported = meta.get("unsupported_task_types") or []
        ref_note = "；Ref2VA 六段式合并（参考生成／续写／编辑／音频复用）本期不作适配" if unsupported else ""
        two = self.defaults.get("two_section_output", True)
        return (
            "[适配说明] 组织粒度＝**逐镜一条提示词**（每镜可独立成片投喂）；"
            f"两段式输出＝{'开启' if two else '关闭'}（标识区 + 分隔行 + 提示词区）；"
            f"本模型不含 AIGC 元数据块（避免污染提示词）{ref_note}。"
        )


def run(pack_path: Path, out_dir: Path, only: list[str] | None, cfg: dict, defaults: dict, vocab: Vocab) -> dict:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    models = [m for m in (cfg.get("models") or []) if m.get("export_filename")]
    if only:
        models = [m for m in models if m.get("code") in only]
    summary: dict = {"pack": str(pack_path), "generated_at": datetime.now(CN_TZ).isoformat(), "models": []}
    for model in models:
        adapter = Adapter(cfg, defaults, vocab, model)
        text = adapter.render(pack)
        target = out_dir / model["code"] / model["export_filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        summary["models"].append(
            {
                "code": model["code"],
                "display_name": model.get("display_name"),
                "priority": model.get("priority"),
                "verify_status": model.get("verify_status"),
                "file": str(target.relative_to(out_dir.parent)),
                "chars": len(text),
                "lines": text.count("\n") + 1,
                "notices": len(adapter.notices),
                "trims": len(adapter.actions),
            }
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SW-025 多模型安全适配文本生成器（配置驱动）")
    ap.add_argument("pack", nargs="?", default=str(ROOT / "examples" / "CFG-004_demo_pack.json"))
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出根目录（默认 examples/_exports_demo）")
    ap.add_argument("--models", default="", help="逗号分隔的模型 code，缺省＝全部有 export_filename 的模型")
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    args = ap.parse_args(argv)

    cfg = load_yaml(ADAPTERS_PATH)
    defaults = cfg.get("defaults") or {}
    vocab = Vocab(load_yaml(VOCAB_PATH), defaults.get("literal_reject_patterns"))
    only = [c for c in (args.models.split(",") if args.models else []) if c]

    summary = run(Path(args.pack), Path(args.out), only, cfg, defaults, vocab)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"pack: {summary['pack']}")
        print(f"out : {args.out}")
        for m in summary["models"]:
            flag = "OK " if m["verify_status"] == "verified" else "WARN"
            print(
                f"  [{flag}] {m['code']:<16} {m['priority']:<3} {m['verify_status']:<9} "
                f"{m['file']}  ({m['chars']} 字符 / {m['lines']} 行"
                + (f"，{m['notices']} 条告警" if m["notices"] else "")
                + (f"，{m['trims']} 处裁剪" if m["trims"] else "")
                + ")"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
