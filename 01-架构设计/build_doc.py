# -*- coding: utf-8 -*-
"""把 Markdown 主稿渲染为带架构图的单文件 HTML 说明书。"""
import re
import pathlib
import markdown

BASE = pathlib.Path(__file__).resolve().parent
MD = BASE / "生成合成类文本合成算法模型框架设计说明书.md"
OUT = BASE / "生成合成类文本合成算法模型框架设计说明书.html"

INK1, INK2, INK3 = "#1b2230", "#5b6678", "#8b95a6"
LINE, PANEL, PANEL2 = "#d9e0ea", "#f7f9fc", "#eef2f8"
BLUE, BLUEBG = "#2563eb", "#eef4ff"
TEAL, TEALBG = "#0d9488", "#e9f7f5"
AMBER, AMBERBG = "#b45309", "#fdf3e7"
VIOLET, VIOLETBG = "#6d28d9", "#f3eeff"
ROSE, ROSEBG = "#be123c", "#fdeef1"
FONT = "'Segoe UI','Microsoft YaHei',system-ui,sans-serif"


def char_w(ch, size):
    """粗略字宽估算：CJK / 全角 / 特殊符号按满宽，其余按半宽。"""
    return size if ord(ch) > 0x2000 else size * 0.56


def text_w(s, size):
    return sum(char_w(c, size) for c in s)


def wrap(s, size, maxw, max_lines=2):
    """按估算宽度换行：优先空格，其次驼峰边界与 CJK 字符边界。"""
    if text_w(s, size) <= maxw:
        return [s]
    best = None
    for i in range(1, len(s)):
        if s[i] == " " or s[i - 1] == " " or (s[i].isupper() and s[i - 1].islower()) \
                or ord(s[i]) > 0x2000 or ord(s[i - 1]) > 0x2000:
            a, b = s[:i].strip(), s[i:].strip()
            if not a or not b:
                continue
            wa, wb = text_w(a, size), text_w(b, size)
            if wa <= maxw and wb <= maxw:
                score = abs(wa - wb) + (0 if s[i] == " " or s[i - 1] == " " else 6)
                if best is None or score < best[0]:
                    best = (score, [a, b])
    if best:
        return best[1]
    mid = max(1, len(s) // 2)
    return [s[:mid], s[mid:]]


def txt(x, y, lines, size=11, fill=INK1, weight="400", anchor="middle", lh=None,
        maxw=None):
    if isinstance(lines, str):
        lines = [lines]
    if maxw:
        fitted = []
        for ln in lines:
            fitted.extend(wrap(ln, size, maxw))
        lines = fitted[:4]
    lh = lh or size + 3
    out = [f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
           f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">']
    for i, ln in enumerate(lines):
        dy = 0 if i == 0 else lh
        out.append(f'<tspan x="{x}" dy="{dy}">{ln}</tspan>')
    out.append("</text>")
    return "".join(out)


def box(x, y, w, h, lines, fill=PANEL, stroke=LINE, color=INK1, size=11,
        weight="500", rx=9, lh=None, sw=1, pad=12):
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
         f'stroke="{stroke}" stroke-width="{sw}"/>')
    lines = lines if isinstance(lines, list) else [lines]
    if pad:
        fitted = []
        for ln in lines:
            fitted.extend(wrap(ln, size, w - pad * 2))
        lines = fitted[:4]
    lh = lh or size + 4
    total = (len(lines) - 1) * lh
    y0 = y + h / 2 - total / 2 + size * 0.36
    return s + txt(x + w / 2, y0, lines, size, color, weight, lh=lh)


def arrow(x1, y1, x2, y2, color=INK3, dash=None, sw=1.3, head=True):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#ah)"' if head else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{sw}"{d}{m}/>')


def poly(points, color=INK3, dash=None, sw=1.3, head=True):
    pts = " ".join(f"{p[0]},{p[1]}" for p in points)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#ah)"' if head else ""
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{sw}"{d}{m}/>'


def svg(w, h, body):
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" preserveAspectRatio="xMidYMid meet">'
        f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{INK3}"/></marker>'
        f'<marker id="ahb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker></defs>'
        f'{body}</svg>'
    )


# ---------------------------------------------------------------- FIG: PIPELINE
def fig_pipeline():
    b = []
    names = [
        (["输入提示 + 上下文", "c：指令 / 素材 / 检索片段"], BLUEBG, BLUE),
        (["分词 · 嵌入", "Token → 向量 + RoPE 位置编码"], TEALBG, TEAL),
        (["N × 解码块", "因果自注意力 + SwiGLU FFN"], VIOLETBG, VIOLET),
        (["采样器", "温度 / Top-k / Top-p / 惩罚"], AMBERBG, AMBER),
        (["后处理与输出", "反分词 · 护栏 · 生成标识"], ROSEBG, ROSE),
    ]
    x, w, gap = 18, 112, 21
    for i, (lines, bg, fg) in enumerate(names):
        cx = x + i * (w + gap)
        b.append(box(cx, 74, w, 62, lines, fill=bg, stroke=fg, color=INK1, size=10.5, lh=14))
        if i < 4:
            b.append(arrow(cx + w, 105, cx + w + gap - 3, 105, color=INK3, sw=1.4))
    # 自回归回路
    b.append(poly([(18 + 2 * (w + gap) + w / 2, 136), (18 + 2 * (w + gap) + w / 2, 168),
                   (18 + 3 * (w + gap) + w / 2, 168), (18 + 3 * (w + gap) + w / 2, 140)],
                  color=TEAL, dash="4 3", sw=1.3))
    b.append(txt(18 + 2.5 * (w + gap) + w / 2, 184,
                 "自回归：新 token 回灌上下文，KV Cache 复用历史状态（Prefill 一次 / Decode 逐 token）",
                 size=10, fill=TEAL))
    # 条件控制层
    b.append(box(18, 200, 118, 40, ["条件控制层"], fill="#ffffff", stroke=LINE, size=10.5, color=INK2))
    b.append(txt(146, 214, ["系统指令 · 少样本示例 · RAG 检索片段 · LoRA 适配器"], size=10, fill=INK2, anchor="start"))
    b.append(txt(146, 230, ["↑ 通过提示工程 / 结构化约束解码 / 参数微调实现可控合成"], size=10, fill=INK3, anchor="start"))
    b.append(poly([(136, 220), (200, 220), (200, 140)], color=INK3, dash="4 3", sw=1.1))
    b.append(txt(340, 34, "文本合成算法运行流水线", size=13, fill=INK1, weight="600"))
    b.append(txt(340, 52, "给定条件 c，逐 token 采样：P(x) = ∏ P(x_t | x_<t , c)", size=10.5, fill=INK2))
    return svg(680, 258, "".join(b))


# ---------------------------------------------------------------- FIG: LAYERED
def fig_layered():
    b = []
    layers = [
        ("L1", "接入层", ["网关 / WAF", "认证鉴权 JWT", "租户识别", "全局限流", "CORS 白名单"], BLUE, BLUEBG),
        ("L2", "编排层", ["POST /syntheses", "SSE 流式端点", "异步任务端点", "Pydantic 校验", "响应信封 / 错误规范化"], TEAL, TEALBG),
        ("L3", "服务层", ["SynthesisService", "GuardrailService", "QuotaService", "CacheService", "TaskService"], VIOLET, VIOLETBG),
        ("L4", "模型层", ["Registry 路由", "TextGenerator 抽象", "vLLM / 本地 / 远程", "Sampling 采样", "约束解码 FSM"], AMBER, AMBERBG),
        ("L5", "基础设施", ["PostgreSQL", "Redis", "任务队列", "对象存储", "可观测 / 模型仓库"], ROSE, ROSEBG),
    ]
    y0, rh, gap = 46, 66, 14
    for i, (code, name, chips, fg, bg) in enumerate(layers):
        y = y0 + i * (rh + gap)
        b.append(f'<rect x="18" y="{y}" width="644" height="{rh}" rx="11" fill="{PANEL2}" '
                 f'stroke="{LINE}" stroke-width="1"/>')
        b.append(f'<rect x="18" y="{y}" width="96" height="{rh}" rx="11" fill="{bg}" stroke="{fg}" '
                 f'stroke-width="1"/>')
        b.append(f'<rect x="96" y="{y}" width="18" height="{rh}" fill="{bg}"/>')
        b.append(txt(66, y + 27, name, size=11.5, fill=fg, weight="700"))
        b.append(txt(66, y + 45, code, size=9.5, fill=fg))
        cx, cw, cg = 126, 100, 8
        for j, c in enumerate(chips):
            x = cx + j * (cw + cg)
            w = cw if j < 4 else 660 - x
            b.append(f'<rect x="{x}" y="{y + 16}" width="{w}" height="34" rx="7" fill="#ffffff" '
                     f'stroke="{LINE}" stroke-width="1"/>')
            words = wrap(c, 9.5, w - 8)
            b.append(txt(x + w / 2, y + 36 - (len(words) - 1) * 6, words,
                         size=9.5, fill=INK1, lh=12))
    b.append(txt(340, 26, "文本合成算法框架 · 分层架构", size=13, fill=INK1, weight="600"))
    b.append(txt(340, 470, "依赖方向自上而下单向；控制器不含业务逻辑，服务层不依赖 HTTP 对象，模型后端可替换",
                 size=10, fill=INK3))
    return svg(680, 492, "".join(b))


# ---------------------------------------------------------------- 时序图工具
def lifelines(centers, labels, top=20, head_h=44, bottom=0):
    b = []
    for cx, lab in zip(centers, labels):
        b.append(f'<rect x="{cx - 48}" y="{top}" width="96" height="{head_h}" rx="8" fill="{PANEL2}" '
                 f'stroke="{LINE}" stroke-width="1"/>')
        parts = lab.split("\n")
        b.append(txt(cx, top + (20 if len(parts) == 1 else 14), parts, size=10, fill=INK1, weight="600", lh=12))
        b.append(f'<line x1="{cx}" y1="{top + head_h}" x2="{cx}" y2="{bottom}" stroke="#cbd5e1" '
                 f'stroke-width="1" stroke-dasharray="3 4"/>')
    return "".join(b)


def msg(y, x1, x2, label, ret=False, sub=None):
    b = []
    color = INK3 if ret else BLUE
    dash = "5 4" if ret else None
    b.append(arrow(x1, y, x2, y, color=color, dash=dash, sw=1.3))
    mid = (x1 + x2) / 2
    b.append(txt(mid, y - 6, label, size=9.5, fill=INK2))
    if sub:
        b.append(txt(mid, y + 11, sub, size=8.5, fill=INK3))
    return "".join(b)


# ------------------------------------------------------------- FIG: SEQ_SYNC
def fig_seq_sync():
    c = [50, 150, 250, 350, 450, 550, 650]
    labels = ["客户端", "控制器", "服务编排", "安全护栏", "配额 / 缓存", "推理后端\n(vLLM)", "存储 / 审计"]
    b = [lifelines(c, labels, top=14, head_h=46, bottom=448)]
    rows = [
        (0, 1, "POST /api/v1/syntheses", False, "鉴权 · 参数校验 · 输入长度"),
        (1, 2, "synthesize(request, tenant)", False, None),
        (2, 3, "check_input(text)", False, "敏感内容 · 提示注入"),
        (3, 2, "verdict: pass / block", True, "命中则 422，零算力返回"),
        (2, 4, "reserve(max_tokens) + cache.get()", False, "令牌桶 QPS + Token 配额"),
        (4, 2, "cache miss", True, None),
        (2, 5, "generate(prompt, params)", False, "约束解码按需开启"),
        (5, 2, "text + usage", True, "TTFT / prefill / decode 时延"),
        (2, 3, "check_output(text)", False, "复检 + 生成标识注入"),
        (2, 6, "BEGIN → save + audit → COMMIT", False, "记录用量·安全标签·留痕"),
        (2, 1, "SynthesisResult(provenance)", True, None),
        (1, 0, "200 OK · 统一 JSON 信封", True, "usage + safety + provenance"),
    ]
    y = 92
    for a, bx, lab, ret, sub in rows:
        b.append(msg(y, c[a], c[bx], lab, ret=ret, sub=sub))
        y += 30
    b.append(f'<rect x="18" y="452" width="644" height="34" rx="8" fill="{BLUEBG}" stroke="{BLUE}" stroke-width="1"/>')
    b.append(txt(340, 473, "配额「先预占 → 按实际用量结算」，避免并发超额；护栏失败不计费、不落模型调用",
                 size=10, fill=BLUE))
    b.append(txt(340, 8, "同步短文本合成 · 时序流程", size=12, fill=INK1, weight="600"))
    return svg(700, 498, "".join(b))


def fig_seq_async():
    c = [70, 210, 350, 490, 630]
    labels = ["客户端", "控制器", "任务队列\n(Redis)", "Worker", "推理后端 / 存储"]
    b = [lifelines(c, labels, top=14, head_h=46, bottom=380)]
    rows = [
        (0, 1, "POST /api/v1/tasks + Idempotency-Key", False, None),
        (1, 2, "enqueue(task)", False, "幂等键唯一约束防重复入队"),
        (1, 0, "202 Accepted + task_id", True, "立即返回，不阻塞连接"),
        (2, 3, "dequeue", False, "按优先级出队 · 背压控制"),
        (3, 4, "generate(...) 分片执行", False, "批量任务拆子任务并行"),
        (4, 3, "text + usage", True, None),
        (3, 4, "save result_ref + audit", False, "长结果落对象存储"),
        (0, 1, "GET /api/v1/tasks/{id}", False, "轮询或订阅回调"),
        (1, 0, "status + result_ref", True, "succeeded / failed"),
    ]
    y = 92
    for a, bx, lab, ret, sub in rows:
        b.append(msg(y, c[a], c[bx], lab, ret=ret, sub=sub))
        y += 30
    b.append(f'<rect x="18" y="384" width="644" height="34" rx="8" fill="{AMBERBG}" stroke="{AMBER}" stroke-width="1"/>')
    b.append(txt(340, 405, "失败重试：指数退避 ≤ 3 次；超限进入死信队列并记录 error_code，任务全程幂等",
                 size=10, fill=AMBER))
    b.append(txt(350, 8, "异步长文本 / 批量合成 · 时序流程", size=12, fill=INK1, weight="600"))
    return svg(700, 430, "".join(b))


# ------------------------------------------------------------- FIG: DEPLOY
def fig_deploy():
    b = []
    b.append(txt(20, 44, "① 接入与编排（CPU 节点 · 可秒级扩缩容）", size=10.5, fill=BLUE, weight="600", anchor="start"))
    b.append(txt(670, 44, "② 模型推理（GPU 节点 · 按队列深度伸缩）", size=10.5, fill=VIOLET, weight="600", anchor="end"))
    rowA = [
        (20, 118, ["客户端", "业务系统 / APP"], PANEL, LINE, INK1),
        (163, 157, ["WAF · CDN · 网关", "认证 · 限流 · CORS"], BLUEBG, BLUE, INK1),
        (345, 145, ["API 节点池", "无状态 ×N（HPA）"], TEALBG, TEAL, INK1),
        (515, 165, ["推理节点池 GPU ×M", "vLLM 连续批处理"], VIOLETBG, VIOLET, INK1),
    ]
    for x, w, lines, bg, st, co in rowA:
        b.append(box(x, 58, w, 66, lines, fill=bg, stroke=st, color=co, size=10.5, lh=15))
    for i in range(3):
        x1 = rowA[i][0] + rowA[i][1]
        x2 = rowA[i + 1][0]
        b.append(arrow(x1, 91, x2 - 3, 91, color=INK3, sw=1.4))
    b.append(txt((rowA[2][0] + rowA[2][1] + rowA[3][0]) / 2, 82, "任务队列 / HTTP", size=9, fill=INK2))
    b.append(txt((rowA[2][0] + rowA[2][1] + rowA[3][0]) / 2, 105, "OpenAI 兼容", size=8.5, fill=INK3))

    b.append(txt(20, 158, "③ 共享基础设施", size=10.5, fill=ROSE, weight="600", anchor="start"))
    rowB = [
        (24, 148, ["Redis", "缓存 · 队列 · 限流"], ROSE, ROSEBG),
        (190, 148, ["PostgreSQL 主 + 只读从", "generations / tasks"], ROSE, ROSEBG),
        (356, 148, ["对象存储", "长结果 · 归档"], ROSE, ROSEBG),
        (522, 148, ["可观测", "Prometheus / 日志 / 链路"], ROSE, ROSEBG),
    ]
    for x, w, lines, st, bg in rowB:
        b.append(box(x, 172, w, 64, lines, fill=bg, stroke=st, color=INK1, size=10.5, lh=15))
    b.append(poly([(400, 124), (400, 150), (98, 150), (98, 168)], color=INK3, dash="4 3", sw=1.1))
    b.append(poly([(598, 124), (598, 150), (596, 150), (596, 168)], color=INK3, dash="4 3", sw=1.1))
    b.append(box(24, 262, 646, 54,
                 ["关键设计：API 节点不加载模型权重，可低成本横向扩容；GPU 节点常驻 vLLM 并按队列深度伸缩，",
                  "推理不可用时可降级到远程后端（FALLBACK_BACKEND），避免全站不可用。"],
                 fill="#ffffff", stroke=LINE, color=INK2, size=10, lh=15, weight="400"))
    b.append(txt(347, 24, "部署拓扑", size=13, fill=INK1, weight="600"))
    return svg(694, 332, "".join(b))


# ------------------------------------------------------------- FIG: ER
def fig_er():
    b = []
    ents = {
        "api_keys": dict(x=20, y=40, w=160, h=96, c=TEAL, bg=TEALBG,
                         fields=["id  PK", "tenant_id  FK → tenants", "key_hash", "scopes jsonb", "revoked_at"]),
        "tenants": dict(x=260, y=40, w=170, h=96, c=BLUE, bg=BLUEBG,
                        fields=["id  PK", "name", "plan", "token_quota_daily", "status"]),
        "models": dict(x=510, y=40, w=160, h=96, c=VIOLET, bg=VIOLETBG,
                       fields=["id  PK", "name / provider", "version", "context_window", "status"]),
        "tasks": dict(x=20, y=190, w=170, h=110, c=AMBER, bg=AMBERBG,
                      fields=["id  PK", "tenant_id  FK", "status / priority", "idempotency_key  UQ",
                              "attempts / error_code", "result_ref"]),
        "generations": dict(x=250, y=190, w=200, h=124, c=ROSE, bg=ROSEBG,
                            fields=["id  PK  ·  request_id  UQ", "tenant_id  FK  ·  model_id  FK",
                                    "template_version", "prompt_hash / params jsonb",
                                    "usage / safety_labels", "latency_ms jsonb", "created_at"]),
        "audit_logs": dict(x=510, y=190, w=160, h=110, c="#475569", bg="#eef1f5",
                           fields=["id  PK", "request_id", "tenant_id", "action / decision",
                                   "input_digest", "created_at"]),
        "prompt_templates": dict(x=250, y=350, w=200, h=86, c="#475569", bg="#eef1f5",
                                 fields=["id  PK", "name / version", "template", "status"]),
    }
    for name, e in ents.items():
        b.append(f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["w"]}" height="{e["h"]}" rx="9" '
                 f'fill="#ffffff" stroke="{e["c"]}" stroke-width="1.3"/>')
        b.append(f'<path d="M{e["x"]},{e["y"] + 9} a9,9 0 0 1 9,-9 h{e["w"] - 18} a9,9 0 0 1 9,9 '
                 f'v13 h-{e["w"]} z" fill="{e["bg"]}"/>')
        b.append(txt(e["x"] + 10, e["y"] + 16, name, size=10.5, fill=e["c"], weight="700", anchor="start"))
        b.append(f'<line x1="{e["x"]}" y1="{e["y"] + 22}" x2="{e["x"] + e["w"]}" y2="{e["y"] + 22}" '
                 f'stroke="{e["c"]}" stroke-width="1" opacity="0.5"/>')
        for i, f in enumerate(e["fields"]):
            b.append(txt(e["x"] + 10, e["y"] + 36 + i * 13, f, size=9, fill=INK2, anchor="start"))

    def rel(pts, lx, ly, lab="1:N"):
        out = poly(pts, color=INK3, sw=1.1)
        out += f'<rect x="{lx - 13}" y="{ly - 9}" width="26" height="14" rx="4" fill="#ffffff"/>'
        out += txt(lx, ly + 2, lab, size=8.5, fill=INK2)
        return out

    b.append(rel([(260, 88), (184, 88)], 222, 88))
    b.append(rel([(350, 136), (350, 186)], 350, 166))
    b.append(rel([(590, 136), (590, 162), (432, 162), (432, 186)], 470, 162))
    b.append(rel([(260, 108), (206, 108), (206, 160), (105, 160), (105, 186)], 234, 106))
    b.append(rel([(430, 76), (690, 76), (690, 220), (674, 220)], 610, 76))
    b.append(rel([(350, 350), (350, 318)], 350, 334))
    b.append(txt(347, 24, "核心数据模型 · 实体关系", size=13, fill=INK1, weight="600"))
    b.append(txt(347, 452, "输入文本仅存摘要哈希（input_digest）用于审计，明文本按合规策略加密并设置更短保留期",
                 size=10, fill=INK3))
    return svg(700, 468, "".join(b))


FIGS = {
    "PIPELINE": fig_pipeline,
    "LAYERED": fig_layered,
    "SEQ_SYNC": fig_seq_sync,
    "SEQ_ASYNC": fig_seq_async,
    "DEPLOY": fig_deploy,
    "ER": fig_er,
}

CSS = """
:root{--ink1:#1b2230;--ink2:#5b6678;--ink3:#8b95a6;--line:#e4e9f0;--bg:#ffffff;
--accent:#2563eb;--teal:#0d9488;--panel:#f8fafc;--code:#f5f7fa;}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f2f5f9;color:#1b2230;
font-family:'Segoe UI','Microsoft YaHei',system-ui,-apple-system,sans-serif;
font-size:14.5px;line-height:1.78;}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px;display:grid;
grid-template-columns:238px minmax(0,1fr);gap:34px;align-items:start;}
nav.toc{position:sticky;top:28px;background:#fff;border:1px solid var(--line);
border-radius:14px;padding:18px 16px;max-height:calc(100vh - 60px);overflow:auto;
font-size:12.5px;box-shadow:0 1px 3px rgba(27,34,48,.05)}
nav.toc h4{margin:0 0 10px;font-size:12px;letter-spacing:.08em;color:var(--ink3);
text-transform:uppercase;font-weight:700}
nav.toc ul{list-style:none;margin:0;padding:0}
nav.toc li{margin:0}
nav.toc a{display:block;color:var(--ink2);text-decoration:none;padding:3px 8px;
border-radius:6px;border-left:2px solid transparent}
nav.toc a:hover{background:var(--panel);color:var(--accent)}
nav.toc ul ul{padding-left:10px}
nav.toc ul ul a{font-size:11.5px;color:var(--ink3)}
main{background:#fff;border:1px solid var(--line);border-radius:16px;
padding:46px 54px 60px;box-shadow:0 1px 3px rgba(27,34,48,.06);min-width:0}
h1{font-size:26px;line-height:1.4;margin:0 0 6px;letter-spacing:-.2px;font-weight:700}
h1+table{margin-top:26px}
h2{font-size:19px;margin:44px 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line);font-weight:700}
h3{font-size:15.5px;margin:28px 0 10px;font-weight:700;color:#232b3a}
h4{font-size:14px;margin:20px 0 8px;font-weight:700;color:var(--ink2)}
p{margin:10px 0;color:#28303f}
a{color:var(--accent)}
strong{font-weight:700;color:#151b26}
hr{border:0;border-top:1px solid var(--line);margin:38px 0}
table{width:100%;border-collapse:collapse;margin:16px 0;font-size:12.8px;
display:table;overflow:hidden;border-radius:10px}
th,td{border:1px solid var(--line);padding:8px 11px;text-align:left;vertical-align:top}
th{background:var(--panel);font-weight:700;color:#232b3a;white-space:nowrap}
tbody tr:nth-child(even){background:#fcfdfe}
td code,p code,li code{font-size:12px}
code{font-family:'Cascadia Mono',Consolas,'Courier New',monospace;
background:var(--code);padding:1.5px 5px;border-radius:4px;color:#1f2937;font-size:12.4px}
pre{background:#f7f9fc;border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:10px;padding:16px 18px;overflow:auto;margin:16px 0}
pre code{background:none;padding:0;font-size:12.4px;line-height:1.7;color:#1e2733;
display:block;white-space:pre}
blockquote{margin:16px 0;padding:11px 18px;background:#f8fbff;border-left:3px solid var(--accent);
border-radius:0 8px 8px 0;color:#2f4055}
blockquote p{margin:0}
ul,ol{padding-left:24px;margin:10px 0}
li{margin:5px 0;color:#28303f}
figure.fig{margin:22px 0;padding:16px 14px;background:#fbfcfe;border:1px solid var(--line);
border-radius:12px;overflow:hidden}
figure.fig svg{width:100%;height:auto;display:block}
em{color:var(--ink2)}
@media print{
 body{background:#fff} .wrap{display:block;max-width:none;padding:0}
 nav.toc{display:none} main{border:0;box-shadow:none;padding:0;border-radius:0}
 figure.fig{break-inside:avoid} table{break-inside:avoid} h2{break-after:avoid}
}
@media(max-width:980px){.wrap{grid-template-columns:1fr}nav.toc{position:static;max-height:none}
 main{padding:28px 20px 40px}}
"""

TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>生成合成类（文本合成）算法模型框架设计说明书</title>
<style>{css}</style></head>
<body><div class="wrap">
<nav class="toc"><h4>目录</h4>{toc}</nav>
<main>{body}</main>
</div></body></html>
"""


def main():
    raw = MD.read_text(encoding="utf-8")

    def repl(m):
        key = m.group(1)
        return "\n<figure class=\"fig\">%s</figure>\n" % FIGS[key]()

    raw = re.sub(r"<!--FIG:([A-Z_]+)-->", repl, raw)

    md = markdown.Markdown(extensions=["extra", "toc", "sane_lists", "md_in_html"],
                           extension_configs={"toc": {"title": "目录"}})
    body = md.convert(raw)
    toc = md.toc
    # 目录层级收敛：只保留到三级
    toc = re.sub(r'<div class="toc">|</div>', "", toc).strip()
    OUT.write_text(TPL.format(css=CSS, toc=toc, body=body), encoding="utf-8")
    print("written:", OUT)
    print("size:", OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
