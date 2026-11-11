"""版权校验与改编来源声明（`SW-015`）。

对应 `REQ-005` `SW-015` 的三条要求：

1. **相似度检测**：把生成内容与「可比对作品库」比对，相似度 ≥ 阈值（默认 **0.5**）
   即给出风险提示；
2. **改编来源声明**：客户提交的改编声明**必填、可留存、可导出**；
3. **风险不阻断但须告知**：高风险内容**不阻断交付**，但须在交付合规声明中**逐条列明**。

⚠️ **前置缺口如实登记（`REQ-005` `SW-015` 原文已载）**：相似度比对**依赖可比对的作品库**，
该库**当前未建立**（属 `T-011` 数据来源任务范围）。因此本模块的纪律是：

- 作品库**不存在或为空** ⇒ `status = "not_available"`，`note` 写明**真实原因**，
  **绝不可**折算成 `passed`（「没检」不等于「没风险」）；
- 作品库存在 ⇒ 才真正做比对，检出即 `risk`（不阻断），并**逐条列明**命中项；
- `threshold`／作品库路径**都可配置**（`app/core/config.py`），
  便于未来作品库到位后**无需改码**即可启用。

⚠️ **归因订正**：本模块新建前，`pack_meta.py` 把该字段的 `note` 硬编码为
「版权校验未接入（`T-008`）」——`T-008` 是**二期**任务（人工审核台），与本条无关；
真实卡点是**作品库未建立**。硬编码已随本模块改为**服务计算 + 真实归因**。

相似度算法：**字符 3-gram 集合 Jaccard**（确定性、零第三方依赖、可复现）。
选它而非 embedding 的理由：① 作品库尚不存在，任何算法都跑不出真实召回率；
② 判据要求「相似度 ≥0.5 即提示」，这是**字面相似**的语义，3-gram Jaccard 与之同构；
③ 确定性算法可被审阅复核——换 embedding 会引入模型版本漂移，反而不可举证。
未来若切换算法，`similarity()` 是唯一改动点，外部契约不变。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

#: 相似度默认阈值（`REQ-005` `SW-015`：默认 **0.5**，可配置）
DEFAULT_THRESHOLD = 0.5

#: 参与比对的文本最小长度（字符）。短于该值的是枚举／编号类取值，
#: 既无版权意义、又会把 Jaccard 分母拖成噪声 ⇒ 一律不参与比对。
MIN_TEXT_LEN = 20

#: 只取「像自然语言」的文本：含中文或空格分隔的连续字母数字
_CJK = re.compile(r"[\u4e00-\u9fff]")

#: 作品库识别的文本后缀
CORPUS_SUFFIXES = (".txt", ".md")


@dataclass
class Corpus:
    """可比对作品库。

    `available=False` 表示**库未建立**（目录不存在／为空／没有可用文本）——
    与「库存在但本次无命中」是**两种不同事实**，不可混同。
    """

    root: str = ""
    texts: dict[str, str] = field(default_factory=dict)  # 作品名 -> 正文
    reason: str = ""

    @property
    def available(self) -> bool:
        return bool(self.texts)

    @property
    def size(self) -> int:
        return len(self.texts)

    def describe(self) -> str:
        if self.available:
            return f"作品库已加载 {self.size} 篇（{self.root}）"
        return self.reason or "作品库未建立"


def load_corpus(root: str | os.PathLike[str] | None) -> Corpus:
    """加载可比对作品库。

    约定：目录下每个 `.txt`／`.md` 文件是一篇受保护作品，**文件名即作品名**。
    ⚠️ 库内容属外部数据，**不入版本控制**（由 `T-011` 数据来源任务投放）。
    """
    if not root:
        return Corpus(
            root="",
            reason="可比对作品库未建立（本算法尚未接入可比对的作品库）",
        )
    p = Path(str(root)).expanduser()
    if not p.is_dir():
        return Corpus(root=str(p), reason=f"可比对作品库路径不存在：{p}")

    texts: dict[str, str] = {}
    for f in sorted(p.iterdir()):
        if not f.is_file() or f.suffix.lower() not in CORPUS_SUFFIXES:
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(body.strip()) >= MIN_TEXT_LEN:
            texts[f.stem] = body
    if not texts:
        return Corpus(root=str(p), reason=f"可比对作品库为空（{p} 下无 ≥{MIN_TEXT_LEN} 字符的 .txt/.md）")
    return Corpus(root=str(p), texts=texts)


def _ngrams(text: str, n: int = 3) -> set[str]:
    """字符 n-gram 集合（保留空白归一化后的连续串）。"""
    s = re.sub(r"\s+", "", text)
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def similarity(a: str, b: str, *, n: int = 3) -> float:
    """两段文本的字符 n-gram Jaccard 相似度（0.0~1.0）。"""
    sa, sb = _ngrams(a, n), _ngrams(b, n)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return round(inter / union, 4) if union else 0.0


def collect_texts(pack: dict[str, Any]) -> list[tuple[str, str]]:
    """从交付包里抽取**参与版权比对**的自然语言文本。

    只取 `shots`／`units`／`style_bible` 下的字符串值，且长度 ≥ `MIN_TEXT_LEN`、
    含中文（或足够长的西文）。返回 `[(定位, 文本)]`，定位形如 `shots[S01-SH001].prompt`。

    ⚠️ 刻意**不扫 `meta`**：`meta` 里是服务层自填的编号／状态／时间，
    扫它只会产生假命中。
    """
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                # 编号／标识类键不参与（它们不是创作内容）
                if str(k) in {"shot_id", "unit_id", "id", "pack_id", "statement_id", "schema_version"}:
                    continue
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            s = node.strip()
            if len(s) < MIN_TEXT_LEN:
                return
            # 自然语言判据：含中文，或长西文（≥MIN_TEXT_LEN 且含空格）
            if _CJK.search(s) or " " in s:
                out.append((path, s))

    for key in ("shots", "units", "style_bible"):
        if key in pack:
            walk(pack[key], key)
    return out


def check(
    pack: dict[str, Any],
    *,
    corpus_root: str | os.PathLike[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """执行版权/改编风险校验（`SW-015` ①③）。

    返回结构**不直接等于** `compliance.copyright_check`：

    - `status`：`passed`（比对完成且全部低于阈值）／`risk`（检出）／`not_available`（库未建立）；
    - `note`：**人可读的真实结论**（含库状态与阈值，便于审核方复核）；
    - `max_similarity`／`hits`／`corpus`／`threshold`：机读证据，供声明件逐条列明。
    """
    corpus = load_corpus(corpus_root)
    texts = collect_texts(pack)

    if not corpus.available:
        # 库未建立 ⇒ 没检，不是通过。两个数字都不编：不报 max_similarity。
        return {
            "status": "not_available",
            "note": f"版权相似度比对未执行：{corpus.describe()}；本次交付按「未校验」如实标注（不阻断，见 SW-015 ③）",
            "threshold": threshold,
            "corpus": {"available": False, "size": 0, "reason": corpus.describe()},
            "max_similarity": None,
            "hits": [],
            "checked_texts": 0,
            "candidate_texts": len(texts),
        }

    if not texts:
        return {
            "status": "not_available",
            "note": "版权相似度比对未执行：交付包内无可比对的自然语言文本（`shots`/`units`/`style_bible` 均为空或全为短取值）",
            "threshold": threshold,
            "corpus": {"available": True, "size": corpus.size, "reason": corpus.describe()},
            "max_similarity": None,
            "hits": [],
            "checked_texts": 0,
            "candidate_texts": 0,
        }

    hits: list[dict[str, Any]] = []
    best = 0.0
    for where, text in texts:
        for name, body in corpus.texts.items():
            score = similarity(text, body)
            if score > best:
                best = score
            if score >= threshold:
                hits.append({"where": where, "work": name, "similarity": score})

    hits.sort(key=lambda h: h["similarity"], reverse=True)
    if hits:
        return {
            "status": "risk",
            "note": (
                f"检出 {len(hits)} 处疑似与受保护作品高度相似（阈值 {threshold}，"
                f"最高 {hits[0]['similarity']}）——**不阻断交付**，须在交付合规声明中逐条列明并提示客户"
                f"取得改编授权（`SW-015` ③）"
            ),
            "threshold": threshold,
            "corpus": {"available": True, "size": corpus.size, "reason": corpus.describe()},
            "max_similarity": best,
            "hits": hits,
            "checked_texts": len(texts),
            "candidate_texts": len(texts),
        }

    return {
        "status": "passed",
        "note": (
            f"已比对 {len(texts)} 段生成内容 × {corpus.size} 篇作品，"
            f"最高相似度 {best} < 阈值 {threshold}，未检出改编风险"
        ),
        "threshold": threshold,
        "corpus": {"available": True, "size": corpus.size, "reason": corpus.describe()},
        "max_similarity": best,
        "hits": [],
        "checked_texts": len(texts),
        "candidate_texts": len(texts),
    }


def normalize_declaration(raw: Any) -> dict[str, Any]:
    """校验并规整「改编来源声明」输入（`SW-015` ②：**必填**）。

    接受两种形态：

    - `str`：适配来源的一句话／一段话；
    - `dict`：`{"origin": "原创"|"改编", "source_work": "...", "license": "...", "declarant": "..."}`。

    ⚠️ **缺失即 `missing`，不代填**：声明的法律主体是客户，服务层不得替其编造
    「原创」——那构成为客户作出未经其确认的权属陈述。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {"present": False, "origin": "", "source_work": "", "license": "", "declarant": ""}
    if isinstance(raw, str):
        return {"present": True, "origin": raw.strip(), "source_work": "", "license": "", "declarant": ""}
    if isinstance(raw, dict):
        origin = str(raw.get("origin") or "").strip()
        if not origin:
            return {"present": False, "origin": "", "source_work": "", "license": "", "declarant": ""}
        return {
            "present": True,
            "origin": origin,
            "source_work": str(raw.get("source_work") or "").strip(),
            "license": str(raw.get("license") or "").strip(),
            "declarant": str(raw.get("declarant") or "").strip(),
        }
    return {"present": False, "origin": "", "source_work": "", "license": "", "declarant": ""}


def build_declaration(
    *,
    pack_id: str,
    session_id: str,
    verdict: dict[str, Any],
    declaration: dict[str, Any],
) -> str:
    """生成《版权与改编来源声明》交付件（`SW-015` ②：可留存、可导出）。

    ⚠️ 本文件是**交付包的一部分**（随包发给客户），因此：

    - 不写任何内部任务号／受控分类码；
    - 「未校验」必须**明写**，不得用「已校验」等含混表述；
    - 风险命中项**逐条列明**（`SW-015` ③），不许汇总成一句「存在风险」。
    """
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    status = str(verdict.get("status") or "not_available")
    label = {"passed": "已校验（未检出风险）", "risk": "已校验（检出风险，见下）",
             "not_available": "未校验"}.get(status, status)

    lines: list[str] = []
    lines.append("# 版权与改编来源声明")
    lines.append("")
    lines.append(f"- 交付包编号：`{pack_id}`")
    lines.append(f"- 会话编号：`{session_id}`")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 版权校验结论：**{label}**")
    lines.append("")

    lines.append("## 一、改编来源声明（提交方填写）")
    lines.append("")
    if declaration.get("present"):
        lines.append("| 项 | 内容 |")
        lines.append("| --- | --- |")
        lines.append(f"| 内容来源 | {declaration.get('origin') or '—'} |")
        lines.append(f"| 原作／来源作品 | {declaration.get('source_work') or '—'} |")
        lines.append(f"| 授权说明 | {declaration.get('license') or '—'} |")
        lines.append(f"| 声明人 | {declaration.get('declarant') or '—'} |")
    else:
        lines.append("> **⚠️ 本次交付未提交改编来源声明。**")
        lines.append(">")
        lines.append("> 声明缺失不影响本交付包的技术完整性，但**风险由提交方自负**：")
        lines.append("> 若生成内容改编自他人作品，提交方须自行取得授权并另行留存证明。")
    lines.append("")

    lines.append("## 二、相似度比对结论")
    lines.append("")
    corpus = verdict.get("corpus") or {}
    lines.append(f"- 比对状态：{corpus.get('reason') or '—'}")
    # ⚠️ **「待比对」与「实际比对」必须分开写**：库未建立时实际比对为 0，
    #    但包内确有若干段创作内容——只写「0 段」会让客户误读成「包内无内容」。
    _cand = verdict.get("candidate_texts", verdict.get("checked_texts", 0))
    lines.append(f"- 待比对内容段数：{_cand}；实际比对：{verdict.get('checked_texts', 0)}")
    lines.append(f"- 风险阈值：{verdict.get('threshold')}")
    if verdict.get("max_similarity") is not None:
        lines.append(f"- 本次最高相似度：{verdict.get('max_similarity')}")
    else:
        lines.append("- 本次最高相似度：**未计算**（作品库未建立，未做比对）")
    lines.append("")

    hits = verdict.get("hits") or []
    if hits:
        lines.append("### 检出项（逐条列明）")
        lines.append("")
        lines.append("| # | 位置 | 疑似来源作品 | 相似度 | 建议 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i, h in enumerate(hits, 1):
            lines.append(
                f"| {i} | `{h.get('where')}` | {h.get('work')} | {h.get('similarity')} | 核对改编授权，或改写以降低相似度 |"
            )
        lines.append("")
    else:
        lines.append("未检出高于阈值的相似内容。" if status == "passed" else "本次未做比对，故无检出项——**这不等于「无风险」**。")
        lines.append("")

    lines.append("## 三、责任边界")
    lines.append("")
    lines.append("1. 本算法仅依据提交方提供的素材与指令生成内容，**不主动检索、不复制**任何受保护作品；")
    lines.append("2. 相似度比对为**辅助提示手段**，不构成法律意义上的侵权判定；")
    lines.append("3. 内容是否可合法使用，由提交方依《著作权法》自行判断并承担责任。")
    lines.append("")
    return "\n".join(lines)


def declaration_filename(pack_id: str) -> str:
    """声明件文件名（稳定、可枚举、不含时间戳以免同包重复打包散落多份）。"""
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", pack_id or "pack")
    digest = hashlib.sha256((pack_id or "").encode("utf-8")).hexdigest()[:6]
    return f"copyright_declaration_{safe}_{digest}.md"
