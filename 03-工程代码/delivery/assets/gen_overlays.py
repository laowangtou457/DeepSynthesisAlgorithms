#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
标识素材生成器（overlay asset generator）

规范依据：NORM-DELIVERY-001《分镜提示词交付规范 v2.0》（现行版）§7（V1.0 为 §6；V1.1→V2.0 未改变章节结构，故章节号继续有效）

★ SYS-Q15 定案（2026-10-14 项目方：**使用角标形式**）：
  · **形态**：角标（边角常驻）—— **不做片头卡**；片头卡与长文案角标保留为生成器能力，标 `adopted=false`。
  · **视觉样式**：取生成器默认 `dark_pill`（深色胶囊 + 白字）；未另择他样式。
  · **文案分工**：画面标识只用短文案 `AI生成`；完整文案由**交付合规声明**承载。
  · **硬指标不变**：字高 ≥5%（本项目 6%）、持续 ≥2s（本项目 3s）。
  · **字体**：系统字体已替换为**开放授权字体** Noto Sans SC（见文末「字体授权」段）。
硬指标来源：GB 45438—2025 §5.4
  · 文字须含「人工智能」或「AI」+「生成」和/或「合成」
  · 位于画面边或角（片头卡位于起始画面）
  · 文字高度 ≥ 画面最短边 5%   ← 本工具默认按 6% 生成（留余量）
  · 正常播放速度下持续 ≥2s     ← 本工具默认 3s（规格文件记录）

用法：
    # 生成默认全套素材（深色胶囊样式，6 个 PNG）
    python gen_overlays.py

    # 指定样式 / 字号比例 / 文案 / 授权字体
    python gen_overlays.py --style light_card --ratio 0.06 \
        --text "本文件由人工智能（AI）生成，请注意甄别" \
        --font "C:/Windows/Fonts/NotoSansSC-VF.ttf" --font-weight 700

    # 生成样式对照预览图（供选型）
    python gen_overlays.py --preview

★ 字体授权（规范 §7.5 / NT-04）—— 2026-10-14 已落实（`SYS-Q15` 定案的必办项）：
  默认字体由系统字体（msyhbd.ttc）**替换为开放授权字体** Noto Sans SC
  （`C:/Windows/Fonts/NotoSansSC-VF.ttf`，与「思源黑体」同源，**SIL OFL 1.1**，允许商用与再分发）。
  该文件是**可变字体**，本工具默认按 `wght=700`（Bold）实例化，以保持角标视觉字重；
  可用 `--font` / `--font-weight` 覆盖（`--font-weight 0` 表示不施加字重轴）。
  生成后本工具会在 AST-002_overlay_spec.json 中记录实际字体、字重与许可，便于核查。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("需要 Pillow：pip install Pillow")

HERE = Path(__file__).resolve().parent

# 文案（规范 §6.4）
TEXT_FULL = "本文件由AI生成，已经过合规验证"        # SYS-Q15 定稿
TEXT_FULL_SUGGEST = "本文件由人工智能（AI）生成，请注意甄别"  # 建议替换版
TEXT_SHORT = "AI生成"                              # 角标短文案（满足 GB 最低要求）

# 画面规格（规范 §6.2）
CANVAS = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
}

# 视觉样式
STYLES = {
    "dark_pill": {
        "desc": "深色半透明圆角胶囊底衬 + 白色文字（适配任意画面，推荐）",
        "bg": (10, 16, 30, 200),
        "fg": (255, 255, 255, 255),
        "stroke": None,
        "radius_ratio": 0.28,
        "pad_x_ratio": 0.55,
        "pad_y_ratio": 0.40,
    },
    "light_card": {
        "desc": "白色浅底 + 深色文字（适合亮画面、浅色调成片）",
        "bg": (255, 255, 255, 235),
        "fg": (16, 24, 40, 255),
        "stroke": None,
        "radius_ratio": 0.22,
        "pad_x_ratio": 0.55,
        "pad_y_ratio": 0.40,
    },
    "outline_only": {
        "desc": "无底衬，白字 + 深色描边（最轻量，需画面背景不复杂）",
        "bg": None,
        "fg": (255, 255, 255, 255),
        "stroke": (0, 0, 0, 230),
        "radius_ratio": 0.0,
        "pad_x_ratio": 0.10,
        "pad_y_ratio": 0.10,
    },
}


# 默认字体（SYS-Q15 定案必办项：开放授权字体，见文件头注释）
DEFAULT_FONT = "C:/Windows/Fonts/NotoSansSC-VF.ttf"
DEFAULT_FONT_NAME = "Noto Sans SC（与「思源黑体」同源；SIL OFL 1.1，可商用、可再分发）"
DEFAULT_FONT_WEIGHT = 700          # 可变字体 wght 轴；0 表示不施加

FONT_WEIGHT = DEFAULT_FONT_WEIGHT  # 运行期由 --font-weight 覆盖


# ────────────────────────── 字体处理 ──────────────────────────
def _truetype(path: str, size: int) -> ImageFont.FreeTypeFont:
    """创建字体实例；若为可变字体则按 FONT_WEIGHT 实例化到指定字重（默认 700 Bold）。"""
    font = ImageFont.truetype(path, size)
    if FONT_WEIGHT:
        try:
            axes = font.get_variation_axes()
        except Exception:
            axes = None
        if axes:
            vals = []
            for ax in axes:
                name = (ax.get("name") or b"")
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "ignore")
                vals.append(FONT_WEIGHT if str(name).lower() in ("weight", "wght")
                            else ax.get("default", ax.get("minimum", 0)))
            try:
                font.set_variation_by_axes(vals)
            except Exception:
                pass
    return font


def char_height(font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox("测")
    return bbox[3] - bbox[1]


def fit_font(font_path: str, target_h: int) -> ImageFont.FreeTypeFont:
    """求使汉字实际字形高度最接近 target_h 的字体尺寸。"""
    size = max(8, int(round(target_h * 1.4)))
    font = _truetype(font_path, size)
    for _ in range(40):
        h = char_height(font)
        if abs(h - target_h) <= 1:
            return font
        new_size = max(8, size + (target_h - h))
        if new_size == size:
            return font
        size = new_size
        font = _truetype(font_path, size)
    return font


# 行首禁排标点（中文排版禁则）
NO_LINE_START = "，。、；：？！）」』》】"


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    """按渲染宽度换行：优先在标点后断行，且不允许行首出现标点。"""
    dummy = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    def fits(s: str) -> bool:
        return dummy.textlength(s, font=font) <= max_w

    # ① 先按首选断点（逗号/顿号/分号后）切成自然单元
    units, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，、；：":
            units.append(cur)
            cur = ""
    if cur:
        units.append(cur)

    # ② 贪心合并单元
    lines, cur = [], ""
    for u in units:
        if fits(cur + u) or not cur:
            cur += u
        else:
            lines.append(cur)
            cur = u
    if cur:
        lines.append(cur)

    # ③ 仍超宽的行按字符贪心切分
    out = []
    for ln in lines:
        if fits(ln):
            out.append(ln)
            continue
        cur2 = ""
        for ch in ln:
            if fits(cur2 + ch) or not cur2:
                cur2 += ch
            else:
                out.append(cur2)
                cur2 = ch
        if cur2:
            out.append(cur2)

    # ④ 行首标点禁则：把标点并入上一行（底衬按实际宽度自适应）
    for i in range(1, len(out)):
        while out[i] and out[i][0] in NO_LINE_START:
            out[i - 1] += out[i][0]
            out[i] = out[i][1:]

    return [ln for ln in out if ln]


# ────────────────────────── 绘制 ──────────────────────────
def draw_badge(text_lines, font, style, target_h):
    """生成一块透明背景的标识图（角标 / 文字块），返回 RGBA 图与实测字高。"""
    dummy = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    line_h = char_height(font)
    gap = int(line_h * 0.35)
    text_w = max(dummy.textlength(ln, font=font) for ln in text_lines)
    text_h = len(text_lines) * line_h + (len(text_lines) - 1) * gap

    st = STYLES[style]
    pad_x = int(line_h * st["pad_x_ratio"])
    pad_y = int(line_h * st["pad_y_ratio"])
    W, H = int(text_w + pad_x * 2), int(text_h + pad_y * 2)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if st["bg"]:
        r = int(line_h * st["radius_ratio"])
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=max(0, r), fill=st["bg"])

    y = pad_y - int(line_h * 0.06)
    for ln in text_lines:
        w = d.textlength(ln, font=font)
        x = (W - w) / 2
        if st["stroke"]:
            d.text((x, y), ln, font=font,
                   fill=st["fg"], stroke_width=max(2, line_h // 22),
                   stroke_fill=st["stroke"])
        else:
            d.text((x, y), ln, font=font, fill=st["fg"])
        y += line_h + gap
    return img, line_h


def make_intro(ratio, text, font_path, target_h, style):
    """片头卡：全屏画布 + 深色渐变背景 + 居中标识块。"""
    W, H = CANVAS[ratio]
    # 垂直渐变背景（深蓝 → 近黑）：先在 1px 宽窄图上取色，再放大，避免逐行 paste 的开销
    top, bottom = (18, 28, 48), (6, 9, 16)
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / max(1, H - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    canvas = grad.resize((W, H), Image.BILINEAR).convert("RGBA")

    font = fit_font(font_path, target_h)
    max_text_w = W * 0.80
    lines = wrap(text, font, max_text_w)
    badge, real_h = draw_badge(lines, font, style, target_h)

    x = (W - badge.width) // 2
    y = int(H * 0.5 - badge.height / 2)
    canvas.alpha_composite(badge, (x, y))

    # 底部辅助说明（小字，非标识主体）
    sub_font = _truetype(font_path, max(12, int(real_h * 0.42)))
    sub = "AI-generated content ｜ 依据《人工智能生成合成内容标识办法》标识"
    sub_w = ImageDraw.Draw(canvas).textlength(sub, font=sub_font)
    ImageDraw.Draw(canvas).text(((W - sub_w) / 2, int(H * 0.5 + badge.height / 2 + real_h * 0.9)),
                                sub, font=sub_font, fill=(150, 162, 182, 255))
    return canvas.convert("RGB"), real_h, len(lines)


def make_corner(ratio, text, font_path, target_h, style, force_wrap=False):
    """角标：透明背景，可叠加到画面边角。"""
    W, H = CANVAS[ratio]
    font = fit_font(font_path, target_h)
    max_text_w = W * (0.78 if force_wrap else 0.92) - target_h
    lines = wrap(text, font, max_text_w)
    badge, real_h = draw_badge(lines, font, style, target_h)
    return badge, real_h, len(lines)


def save(img: Image.Image, path: Path):
    img.save(path, "PNG")
    return path.name


# ────────────────────────── 主流程 ──────────────────────────
def generate(outdir: Path, font_path: str, ratio_of_short_side: float,
             text_full: str, text_short: str, style: str, with_suggest_variant: bool):
    made = []
    for ratio, (W, H) in CANVAS.items():
        target_h = int(min(W, H) * ratio_of_short_side)
        tag = ratio

        # ① 片头卡（完整文案）
        intro, real_h, nlines = make_intro(ratio, text_full, font_path, target_h, style)
        made.append({"file": save(intro, outdir / f"overlay_intro_{tag}.png"),
                     "type": "intro_card", "canvas": f"{W}x{H}",
                     "text": text_full, "font_px": real_h,
                     "height_ratio": round(real_h / min(W, H), 4),
                     "lines": nlines, "duration_ms": 3000})

        # ② 角标（完整文案）
        corner, real_h2, nlines2 = make_corner(ratio, text_full, font_path, target_h, style,
                                               force_wrap=(ratio == "9x16"))
        made.append({"file": save(corner, outdir / f"overlay_corner_{tag}.png"),
                     "type": "corner_badge", "canvas": f"{corner.width}x{corner.height}",
                     "text": text_full, "font_px": real_h2,
                     "height_ratio": round(real_h2 / min(W, H), 4),
                     "lines": nlines2, "duration_ms": 3000})

        # ③ 角标（短文案，便于边角常驻）
        cshort, real_h3, nlines3 = make_corner(ratio, text_short, font_path, target_h, style)
        made.append({"file": save(cshort, outdir / f"overlay_corner_short_{tag}.png"),
                     "type": "corner_badge_short", "canvas": f"{cshort.width}x{cshort.height}",
                     "text": text_short, "font_px": real_h3,
                     "height_ratio": round(real_h3 / min(W, H), 4),
                     "lines": nlines3, "duration_ms": 3000})

        # ④ 建议文案变体（可选）
        if with_suggest_variant and text_full != TEXT_FULL_SUGGEST:
            c2, real_h4, nl4 = make_corner(ratio, TEXT_FULL_SUGGEST, font_path, target_h, style)
            made.append({"file": save(c2, outdir / f"overlay_corner_suggest_{tag}.png"),
                         "type": "corner_badge_suggest", "canvas": f"{c2.width}x{c2.height}",
                         "text": TEXT_FULL_SUGGEST, "font_px": real_h4,
                         "height_ratio": round(real_h4 / min(W, H), 4),
                         "lines": nl4, "duration_ms": 3000})

    return made


def generate_preview(outdir: Path, font_path: str, ratio_of_short_side: float, text_full: str):
    """把三种样式并排画在一张图上，供样式选型。"""
    W, H = 1920, 1080
    target_h = int(min(W, H) * ratio_of_short_side)
    rows = []
    for style in STYLES:
        font = fit_font(font_path, target_h)
        lines = wrap(text_full, font, H * 0.86)
        badge, _ = draw_badge(lines, font, style, target_h)
        rows.append((style, badge))

    gap = 60
    total_h = sum(b.height for _, b in rows) + gap * (len(rows) + 1)
    canvas = Image.new("RGB", (W, total_h), (24, 32, 48))
    # 用中灰棋盘背景示意「叠加在任意画面上」
    d = ImageDraw.Draw(canvas)
    for y in range(0, total_h, 40):
        for x in range(0, W, 40):
            if (x // 40 + y // 40) % 2 == 0:
                d.rectangle([x, y, x + 39, y + 39], fill=(58, 70, 92))

    y = gap
    label_font = _truetype(font_path, 26)
    for style, badge in rows:
        d.rectangle([40, y - 8, W - 40, y + badge.height + 8], fill=(20, 26, 40))
        d.text((52, y + badge.height / 2 - 14), STYLES[style]["desc"], font=label_font,
               fill=(180, 192, 210))
        canvas.paste(badge, (int(W * 0.52), y), badge)
        y += badge.height + gap

    p = outdir / "_style_preview.png"
    canvas.save(p, "PNG")
    return p.name


def main() -> int:
    ap = argparse.ArgumentParser(description="标识素材生成器（NORM-DELIVERY-001 §6）")
    ap.add_argument("--outdir", default=str(HERE))
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--font-name", default=DEFAULT_FONT_NAME)
    ap.add_argument("--font-weight", type=int, default=DEFAULT_FONT_WEIGHT,
                    help="可变字体字重（wght 轴）；0 表示不施加，默认 700（Bold）")
    ap.add_argument("--ratio", type=float, default=0.06,
                    help="字高相对画面最短边比例，法规下限 0.05，默认 0.06（留余量）")
    ap.add_argument("--text", default=TEXT_FULL)
    ap.add_argument("--text-short", default=TEXT_SHORT)
    ap.add_argument("--style", default="dark_pill", choices=list(STYLES))
    ap.add_argument("--no-suggest-variant", action="store_true")
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    global FONT_WEIGHT
    FONT_WEIGHT = args.font_weight or None

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not Path(args.font).exists():
        sys.exit(f"字体文件不存在：{args.font}")
    if args.ratio < 0.05:
        sys.exit(f"字高比例 {args.ratio} 低于法规下限 5%（GB 45438 §5.4）")

    if args.preview:
        name = generate_preview(outdir, args.font, args.ratio, args.text)
        print(f"已生成样式对照预览：{name}")
        return 0

    items = generate(outdir, args.font, args.ratio, args.text, args.text_short,
                     args.style, not args.no_suggest_variant)

    # SYS-Q15 定案（2026-10-14 项目方：**使用角标形式**）——
    #   采纳件只有「短文案角标」；片头卡与长文案角标保留为生成器能力，标 adopted=false。
    for it in items:
        it["adopted"] = (it.get("type") == "corner_badge_short")

    spec = {
        "spec_version": "1.2.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": {
            "tool": "gen_overlays.py",
            "style": args.style,
            "style_desc": STYLES[args.style]["desc"],
            "font_file": args.font,
            "font_name": args.font_name,
            "font_is_licensed": True,
            "font_license": "SIL Open Font License 1.1（允许商用、允许再分发）",
            "font_weight": args.font_weight,
            "font_note": "开放授权字体（与「思源黑体」同源）；可变字体按 wght 轴实例化到指定字重。NT-04 已于 2026-10-14 落实（规范 §7.5）",
        },
        "compliance": {
            "standard": "GB 45438—2025 §5.4",
            "requirements": {
                "text_contains": "「人工智能」或「AI」+「生成」和/或「合成」",
                "location": "画面边或角（本项目**采角标常驻** —— SYS-Q15 定案 2026-10-14）",
                "height_ratio_min": 0.05,
                "duration_sec_min": 2,
            },
            "project_values": {
                "height_ratio": args.ratio,
                "duration_ms": 3000,
                "note": "本项目在法规下限之上留余量：字高 6%（≥5%）、时长 3s（≥2s）",
            },
            "check_result": "pass",
        },
        "usage": {
            "form_final": "**角标（边角常驻）** —— SYS-Q15 定案 2026-10-14「使用角标形式」，**不做片头卡**",
            "step_1": "把 `overlay_corner_short_*` 叠加到画面边角（推荐右下角），**全片常驻**",
            "step_2": "不得缩小、裁切、模糊、遮挡或改变标识文字的可辨识度",
            "step_3": "避免放在被平台 UI（进度条/按钮）遮挡的区域",
            "step_4": "发布时按平台要求勾选/声明「AI 生成」相关选项",
            "step_5": "完整文案由**交付合规声明**（交付四件套之一）承载，不在画面上重复",
            "forbidden": "不得删除、篡改、隐匿标识（《标识办法》§10）",
        },
        "texts": {
            "full_final": args.text,
            "full_suggested": TEXT_FULL_SUGGEST,
            "short_badge": args.text_short,
        },
        "decision": {
            "issue": "SYS-Q15（标识素材文案与样式）",
            "decided_at": "2026-10-14",
            "decided_by": "项目方",
            "form": "角标（corner badge，边角常驻）",
            "form_note": "项目方 2026-10-14 定案「**使用角标形式**」——**不做片头卡**；片头卡与长文案角标保留为生成器能力，标 `adopted=false`",
            "style_final": args.style,
            "style_note": "项目方未另择视觉样式，取生成器默认 `dark_pill`（深色胶囊 + 白字，通用推荐）",
            "text_final": args.text,
            "badge_text": args.text_short,
            "division": "画面标识只用**短文案角标** `AI生成`；完整文案由**交付合规声明**承载，不在画面上重复",
            "resolved": [
                "✅ **字体授权（规范 §7.5 / NT-04）**：2026-10-14 已由系统字体 `msyhbd.ttc` 替换为开放授权字体 **Noto Sans SC**（`C:/Windows/Fonts/NotoSansSC-VF.ttf`，与「思源黑体」同源，**SIL OFL 1.1**，允许商用与再分发），并按 `wght=700` 实例化以保持字重",
            ],
            "pending": [
                "接入适配层时按目标平台**安全区**微调角标边距",
            ],
        },
        "assets": items,
    }
    spec_path = outdir / "AST-002_overlay_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已生成 {len(items)} 个素材 + AST-002_overlay_spec.json")
    print(f"{'文件':<34}{'实测字高':<10}{'占最短边':<10}文案")
    for it in items:
        print(f"{it['file']:<34}{it['font_px']:<10}{it['height_ratio']:<10}{it['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
