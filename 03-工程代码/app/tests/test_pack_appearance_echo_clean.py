# -*- coding: utf-8 -*-
"""**投影规则⑥**：`R28` 正文外观复述的服务层机械清洗（项目方 2026-11-16 裁决批准）。

为什么有这一条机制
------------------
`R28 PACK_APPEARANCE_ECHO`（`prompts/validate_output.py` 的 `rule_pack_appearance_echo`）
要求交付包 `shots[].prompt_zh`／`prompt_en` 的**正文不得复述** `characters[].appearance_lock_*`。
真机 **6 轮跑测 6/6 挂 `R28`**，命中片段集中在 `潜水服`×25／`orange rescue suit`×7／
`深蓝色`×3——**全是 3 字／3 实词的最小窗口**。模板 `TPL-009:641-643` 已明令「外观命中即删」，
同模板又要求「正文密度下界」（八维双落地）⇒ 模型唯一逃逸口就是服装／体型词。
**措辞路线已到顶**（与投影规则⑤ 同性质的结论），只能服务层机制化。

本文件的落点
------------
被测对象是 `DialogueService._clean_pack_appearance_echo`（**纯函数式**，`__new__` 免依赖构造，
与 `test_pack_en_camera_sentence_fill.py`／`test_camera_amp_speed_normalize.py` 同构）。
共 **17 个用例**，覆盖十三组：

  ① 中文单锚 ⇒ 子句整删、`R28` 复算归零、其他字段一字不动；
  ② 同子句含两锚 ⇒ **一次删整句**即归零（证明不是逐词手术）；
  ③ 两锚分属**不同子句** ⇒ 同轮全删、一轮收敛；跨子句伪 gram（英文）⇒ **如实登记
     `skipped_unresolvable`、原文不动**（不硬凑，交判据判）；
  ④ 英文 3 实词命中 ⇒ 删子句、归零；
  ⑤ 命中只落在 `The camera …` 句内 ⇒ **该句不删**（保护投影规则⑤ 补的句子）；
  ⑤′ **占位镜整镜跳过**（`notes` 以「服务层构造占位」开头）⇒ `prompt_zh` 逐字不变、
     记 `skipped_placeholder`；同包内的**真实镜**（`notes` 无前缀）照常清洗
     （⇒ 既证明「不是把开关关掉」，也证明「识别锚不是 `prompt_en` 为空」）；
  ⑥ **不删空保护**：删到低于阈值 ⇒ 整镜回滚、字段值完全不变；
  ⑦ 无外观锚 ⇒ **字节级 no-op**；
  ⑧ 开关关闭 ⇒ 原样返回（回退路径）；
  ⑨ 幂等：连跑两次，第二次 `changed is False` 且字节相同；
  ⑩ **与门禁联动**（真跑 `prompts/validate_output.py --json`，不是模拟）：
     demo 包（只读）自带 1 条 `R28`（`S01-SH002`「眼神平」）⇒ 清洗后同码消失、不新增任何码；
  ⑪ 非 `pack` 形态（`storyboard`）⇒ 原文不变；
  ⑫ **canary 锁**：`prompts/examples/` 三份正向样本 `R28` 当前全过 ⇒ 必须**字节级 no-op**。

⚠️ 判据 `prompts/validate_output.py` **零改动**；命中口径（中文 3 字／英文 3 实词、
`CJK_RUN_RE`、`ANCHOR_NGRAM`）**一律取判据模块自己的**，本文件不抄第二份。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services import quality_gate
from app.services.dialogue_service import (
    DialogueService,
    _PLACEHOLDER_NOTES_PREFIX,
    _scrub_appearance_echo_field,
)

_CODE_ROOT = Path(__file__).resolve().parents[2]          # 03-工程代码
_DEMO_PACK = _CODE_ROOT / "delivery" / "examples" / "CFG-004_demo_pack.json"
_VALIDATE_OUTPUT = _CODE_ROOT / "prompts" / "validate_output.py"
_EXAMPLES = _CODE_ROOT / "prompts" / "examples"


def _svc() -> DialogueService:
    """免依赖构造（不碰 repo／prompts／backend，与既有归一化层测试同构）。"""
    return DialogueService.__new__(DialogueService)


def _pack(shots: list[dict], characters: list[dict] | None = None) -> str:
    doc = {
        "units": [{"unit_id": "U01", "shot_ids": [s["shot_id"] for s in shots]}],
        "characters": characters or [],
        "shots": shots,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _char(lock_zh: str | None = None, lock_en: str | None = None) -> dict:
    out: dict[str, Any] = {"character_id": "CHR-01"}
    if lock_zh is not None:
        out["appearance_lock_zh"] = lock_zh
    if lock_en is not None:
        out["appearance_lock_en"] = lock_en
    return out


def _r28_errors(doc: dict) -> list[str]:
    """**跑判据自己的 `R28`**（进程内，`QUIET` 免刷屏）——不是模拟，也不抄第二份算法。"""
    module = quality_gate.load_engine_validator()
    assert module is not None, "判据模块 prompts/validate_output.py 不可加载"
    saved_errors = list(module.RESULT.get("errors") or [])
    saved_quiet = module.QUIET
    module.QUIET = True
    module.RESULT["errors"] = []
    try:
        module.rule_pack_appearance_echo(doc, "test")
        return [e for e in module.RESULT["errors"] if "R28" in e]
    finally:
        module.RESULT["errors"] = saved_errors
        module.QUIET = saved_quiet


# --------------------------------------------------------------------------- ①
def test_zh_hit_removes_clause_and_clears_r28() -> None:
    """中文单锚 ⇒ **整子句删除**、`R28` 复算归零、`R28` 之外的字段一字不动。"""
    orig_zh = "近景：他站在甲板上，海风吹动衣角，穿着深蓝色潜水服，目光望向远处。"
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "camera": {"move": "push_in", "height": "eye_level"},
                "duration_ms": 5000,
                "prompt_zh": orig_zh,
                "prompt_en": "Close-up of him on the deck. The camera pushes in.",
            }
        ],
        [_char(lock_zh="深蓝色潜水服，短寸头")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec is not None
    assert rec["changed"] is True and rec["action"] == "scrubbed"
    assert rec["scrubbed"] == 1 and rec["skipped_unresolvable"] == 0
    item = rec["items"][0]
    assert item["shot_id"] == "S01-SH001" and item["lang"] == "zh"
    assert item["hit_gram"] == "深蓝色"
    # 子句（9 字）＋ 删后被折叠掉的那个逗号（1 字）＝ 10；留痕记的是**实际删除长度**
    assert item["removed_chars"] == len(orig_zh) - len(
        "近景：他站在甲板上，海风吹动衣角，目光望向远处。"
    )
    assert item["removed_chars"] >= len("穿着深蓝色潜水服")

    doc = json.loads(out)
    assert "深蓝色潜水服" not in doc["shots"][0]["prompt_zh"]
    assert doc["shots"][0]["prompt_zh"] == "近景：他站在甲板上，海风吹动衣角，目光望向远处。"
    # 只改正文两个字段：`camera`／`duration_ms`／`shot_id`／`prompt_en` 一字不动
    assert doc["shots"][0]["camera"] == {"move": "push_in", "height": "eye_level"}
    assert doc["shots"][0]["duration_ms"] == 5000
    assert doc["shots"][0]["prompt_en"] == "Close-up of him on the deck. The camera pushes in."
    # 判据复算归零（**用判据自己跑**，不是看 rec 的自述）
    assert _r28_errors(doc) == []
    # 留痕不落原文（只留 gram 与长度）
    assert "prompt_zh" not in json.dumps(rec["items"], ensure_ascii=False)


# --------------------------------------------------------------------------- ②
def test_multi_anchor_same_clause_single_pass() -> None:
    """同子句含 `深蓝色` 与 `救生衣` 两锚 ⇒ **一次删整子句**即归零（不是逐词手术）。"""
    clause = "穿着深蓝色潜水服和橙色救生衣"
    orig_zh = f"近景：他站在甲板上，海风吹动衣角，{clause}，目光望向远处。"
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "prompt_zh": orig_zh,
            }
        ],
        [_char(lock_zh="深蓝色潜水服，橙色救生衣")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec["scrubbed"] == 1
    item = rec["items"][0]
    # **整句长度**一次删掉（＋折叠掉的那个逗号）⇒ 若做逐词手术，删除长度会明显小于子句长度
    assert item["removed_chars"] == len(clause) + 1
    assert item["rounds"] == 1
    doc = json.loads(out)
    # 子句整体消失（两个锚都不可能残留半截）
    assert "深蓝色" not in doc["shots"][0]["prompt_zh"]
    assert "救生衣" not in doc["shots"][0]["prompt_zh"]
    assert doc["shots"][0]["prompt_zh"] == "近景：他站在甲板上，海风吹动衣角，目光望向远处。"
    assert _r28_errors(doc) == []


# --------------------------------------------------------------------------- ③
def test_iterates_to_fixed_point_across_clauses() -> None:
    """两锚分属**不同子句** ⇒ 同轮全删、**一轮收敛到不动点**（不留半截）。

    ⚠️ 为什么 `rounds == 1`：删子句时**保留分隔符**（`_split_clauses`／`_join_clauses`），
       中文的汉字连续段因此不会跨子句重新连成新的 3 字窗口 ⇒ 「一轮删完所有命中子句」
       就是本算法的不动点。真正的跨子句伪 gram 只会出现在**英文**侧
       （`_en_content_ngrams` 只取实词、不认标点），见下一个用例的**诚实放弃**。
    """
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "prompt_zh": (
                    "远景：海面很平静，"
                    "他穿着深蓝色潜水服站在船头，"
                    "风把旗帜吹得笔直，"
                    "目光平静，"
                    "远处的灯塔亮着。"
                ),
            }
        ],
        [_char(lock_zh="深蓝色潜水服，目光平静")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec["scrubbed"] == 1
    assert rec["items"][0]["rounds"] == 1
    doc = json.loads(out)
    assert _r28_errors(doc) == []
    zh = doc["shots"][0]["prompt_zh"]
    # 两个命中子句都走干净了，非命中子句一字不动
    assert "深蓝色" not in zh and "目光平" not in zh
    assert zh.startswith("远景：海面很平静，")
    assert zh.endswith("远处的灯塔亮着。")


def test_cross_clause_pseudo_gram_is_registered_not_faked() -> None:
    """英文跨子句伪 gram ⇒ **如实登记 `skipped_unresolvable`、原文不动**（不硬凑）。

    构造：`bright blue helmet` 独立成句（可删）＋ `orange`／`rescue suit` 分处两句，
    删掉第一句后实词序列才拼出锚 gram `orange rescue suit` ⇒ 第 2 轮起**任何单个子句
    都不含命中**，无法再按「完整子句」粒度删除。此时本机制的义务是**承认删不动**
    （3 字／3 实词阈值属判据口径，改它需另案裁决），而不是逐词抠掉 `orange`。
    """
    lock_en = "bright blue helmet, orange rescue suit"
    text = "He wears a bright blue helmet, orange, rescue suit in the rain."
    status_text, gram, status, rounds = _scrub_appearance_echo_field(
        text,
        lang="en",
        hit=lambda t: _en_hit(t, lock_en),
        is_too_short=lambda t: False,
    )
    assert gram is not None and status == "unresolvable"
    assert rounds == 2, "伪 gram 只在第 2 轮才出现 ⇒ 证明迭代真的在复算"

    raw = _pack([{"shot_id": "S01-SH001", "prompt_en": text}], [_char(lock_en=lock_en)])
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    # 字段**一字不动**（删半截既不归零、又把正文弄坏，属「越改越差」）
    assert out == raw
    assert rec["changed"] is False and rec["action"] == "noop"
    assert rec["skipped_unresolvable"] == 1


def _en_hit(text: str, lock_en: str) -> str | None:
    """测试侧的命中判定：**只调判据模块自己的函数**（不抄 3 实词规则）。"""
    module = quality_gate.load_engine_validator()
    assert module is not None
    inter = module._en_content_ngrams(text) & module._en_content_ngrams(lock_en)
    return sorted(inter)[0] if inter else None


# --------------------------------------------------------------------------- ④
def test_en_three_content_words() -> None:
    """英文 3 实词（`dark blue wetsuit`）命中 ⇒ 删子句、`R28` 归零。"""
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "prompt_en": (
                    "Close-up of him in a dark blue wetsuit, "
                    "rain streaks the deck behind him, "
                    "the lantern flickers once."
                ),
            }
        ],
        [_char(lock_en="dark blue wetsuit, short hair")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec["scrubbed"] == 1
    item = rec["items"][0]
    assert item["lang"] == "en" and item["hit_gram"] == "dark blue wetsuit"
    doc = json.loads(out)
    en = doc["shots"][0]["prompt_en"]
    assert "dark blue wetsuit" not in en
    # 原句其余部分一字不动（只删整子句，不重写）
    assert en == "rain streaks the deck behind him, the lantern flickers once."
    assert _r28_errors(doc) == []


# --------------------------------------------------------------------------- ⑤
def test_camera_sentence_clause_is_protected() -> None:
    """命中只落在 `The camera …` 句内 ⇒ **该句不删**（保护投影规则⑤ 补的句子）。

    ⚠️ 顺序纪律的可见后果：本机制排在 `_ensure_en_camera_sentence` **之前**，
       所以正常情况下「清洗时还没有合成句」；但模型**自己写对**的运镜句同样受保护，
       否则本机制会亲手打开 `R34` 的洞（用一个判据的绿换另一个判据的红）。
    """
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "prompt_zh": "近景：他站在甲板上，海风吹动衣角，目光望向远处。",
                "prompt_en": (
                    "A wide shot of the deck. "
                    "The camera pushes in over an orange rescue suit. "
                    "Rain falls hard."
                ),
            }
        ],
        [_char(lock_en="orange rescue suit, short hair")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec is not None
    assert rec["changed"] is False and rec["action"] == "noop"
    assert rec["skipped_unresolvable"] == 1
    assert rec["scrubbed"] == 0
    # 原文**一字不动**（既没删运镜句，也没删别的句子去凑「归零」）
    assert out == raw
    doc = json.loads(out)
    assert "The camera pushes in over an orange rescue suit." in doc["shots"][0]["prompt_en"]
    # 承认删不动：判据侧仍会报（本机制不掩盖）
    assert _r28_errors(doc)


# --------------------------------------------------------------------------- ⑤′
def test_placeholder_shot_fully_skipped_but_real_shot_scrubbed() -> None:
    """**占位镜整镜跳过**、非占位镜照常清洗（SPEC-008 V2.6 §3.7.2 边界⑤ 的实现对齐）。

    ⚠️ 为什么这条必须存在（`7006072` 的真实缺陷）：首版只对「空字段」做 continue，
       占位镜（`prompt_en` 为空、`notes` 明写「服务层构造占位…」）的 **`prompt_zh` 仍被清洗**——
       而 `prompt_zh` 是服务层由 `action` 机械派生的自有产物，清洗它＝服务层改写自己刚生成的东西
       （既不增信息，又抹掉追溯线索），且与规范／开关注释／docstring 三处承诺冲突。

    ⚠️ 识别锚**只认 `notes` 前缀**，**不认**「`prompt_en` 为空」：后者也可能是**模型漏写**的
       真实镜，其 `prompt_zh` 是模型创作内容，**该被清洗**（本用例的镜 B 就是这种形态下的对照）。

    ⚠️ 判据侧的归零断言只能**按镜**做：占位镜的正文仍含外观锚，`R28` 会继续如实报它
       （本机制**不掩盖**服务层占位镜的洞），故断言「只剩占位镜那一处、镜 B 已消失」。
    """
    # 生产侧常量与 `_reconcile_pack_conservation` 写入的文案同源（防两处字面量分叉）
    assert _PLACEHOLDER_NOTES_PREFIX == "服务层构造占位"
    placeholder_notes = (
        "服务层构造占位（2026-11-07 裁决甲）：模型漏生成本镜；"
        "机械承继字段引用上游分镜镜定义，prompt_zh 由 action 派生，"
        "prompt_en 留空待补——占位本身不构成创作合格，交判据如实判。"
    )
    placeholder_zh = "角色穿着深蓝色潜水服登场，随后下潜，光线渐暗。"
    real_zh = "近景：他站在甲板上，海风吹动衣角，穿着深蓝色潜水服，目光望向远处。"
    raw = _pack(
        [
            {   # 镜 A：**服务层占位镜**
                "shot_id": "S01-SH001",
                "notes": placeholder_notes,
                "prompt_zh": placeholder_zh,
                "prompt_en": "",
            },
            {   # 镜 B：真实镜（`notes` 无前缀）
                "shot_id": "S01-SH002",
                "notes": "本层正文由模型创作。",
                "prompt_zh": real_zh,
                "prompt_en": "Close-up of him on the deck. The camera pushes in.",
            },
        ],
        [_char(lock_zh="深蓝色潜水服")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec is not None
    assert rec["skipped_placeholder"] == 1, "占位镜未被识别（notes 前缀锚失效）"
    assert rec["scrubbed"] == 1, "本机制被整体关掉或被占位镜拖累"
    assert rec["items"][0]["shot_id"] == "S01-SH002"

    doc = json.loads(out)
    by_id = {s["shot_id"]: s for s in doc["shots"]}
    # 镜 A：**逐字不变**（整镜跳过，不止跳过 `prompt_en`）
    assert by_id["S01-SH001"]["prompt_zh"] == placeholder_zh
    assert by_id["S01-SH001"]["prompt_en"] == ""
    # 镜 B：照常清洗
    assert "深蓝色" not in by_id["S01-SH002"]["prompt_zh"]
    assert by_id["S01-SH002"]["prompt_zh"] == "近景：他站在甲板上，海风吹动衣角，目光望向远处。"

    # 判据复算：只剩**占位镜**那一处如实报出，镜 B 已消失（不掩盖、也不敢掩盖）
    hits = _r28_errors(doc)
    assert len(hits) == 1, hits
    assert "S01-SH001" in hits[0] and "S01-SH002" not in hits[0]


def test_placeholder_only_package_is_noop() -> None:
    """整包只有占位镜 ⇒ **字节级 noop**（不因「只跳过占位镜」就写 artifact／重序列化）。"""
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "notes": "服务层构造占位（2026-11-07 裁决甲）：模型漏生成本镜；",
                "prompt_zh": "角色穿着深蓝色潜水服登场，随后下潜，光线渐暗。",
                "prompt_en": "",
            }
        ],
        [_char(lock_zh="深蓝色潜水服")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    assert out == raw
    assert rec["changed"] is False and rec["action"] == "noop"
    assert rec["skipped_placeholder"] == 1 and rec["scrubbed"] == 0


# --------------------------------------------------------------------------- ⑥
def test_would_empty_is_rolled_back() -> None:
    """中文正文过短且全命中 ⇒ `skipped_would_empty=1`、字段值**完全不变**。

    ⚠️ 这是**不删空保护**的核心：`R28` 绿了但正文被删空 ⇒ 换来 `R27`（正文非空/可读）
       的红，净效果变差。宁可留 `R28` 的洞如实登记，也不许把一个洞洗成另一个洞。
    """
    raw = _pack(
        [
            {
                "shot_id": "S01-SH001",
                "prompt_zh": "深蓝色潜水服。",
                "prompt_en": "A wide shot of the deck.",
            }
        ],
        [_char(lock_zh="深蓝色潜水服")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)

    assert rec["changed"] is False and rec["action"] == "noop"
    assert rec["skipped_would_empty"] == 1
    assert rec["scrubbed"] == 0
    assert out == raw
    assert json.loads(out)["shots"][0]["prompt_zh"] == "深蓝色潜水服。"


def test_would_empty_en_fewer_than_six_content_words() -> None:
    """英文删后实词 < 6 ⇒ 同样整镜回滚（两种语言的保护阈值各自生效）。"""
    raw = _pack(
        [{"shot_id": "S01-SH001", "prompt_en": "He wears an orange rescue suit."}],
        [_char(lock_en="orange rescue suit")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    assert rec["skipped_would_empty"] == 1
    assert out == raw


# --------------------------------------------------------------------------- ⑦
def test_no_anchor_is_noop_bytes_same() -> None:
    """`characters` 无 `appearance_lock` ⇒ **字节级 no-op**、`rec is None`。"""
    raw = _pack([{"shot_id": "S01-SH001", "prompt_zh": "近景：他站在甲板上。"}], [_char()])
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    assert out == raw and rec is None


def test_unparsable_text_returns_unchanged() -> None:
    """不可解析 ⇒ 原样返回（形态由形态闸归因，不在此处抢先）。"""
    out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", "{不是 JSON")
    assert out == "{不是 JSON" and rec is None


# --------------------------------------------------------------------------- ⑧
def test_switch_off_is_noop() -> None:
    """回退开关：`APP_PACK_APPEARANCE_ECHO_CLEAN=false` ⇒ 原样返回（`rec is None`）。"""
    settings = get_settings()
    original = settings.pack_appearance_echo_clean
    settings.pack_appearance_echo_clean = False
    try:
        raw = _pack(
            [{"shot_id": "S01-SH001", "prompt_zh": "近景：他穿着深蓝色潜水服站在甲板上。"}],
            [_char(lock_zh="深蓝色潜水服")],
        )
        out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
        assert out == raw and rec is None
    finally:
        settings.pack_appearance_echo_clean = original


# --------------------------------------------------------------------------- ⑨
def test_idempotent_second_run_noop() -> None:
    """幂等：清洗过的产物再跑一次 ⇒ `changed is False` 且**逐字节相同**。"""
    raw = _pack(
        [{"shot_id": "S01-SH001",
          "prompt_zh": "近景：他穿着深蓝色潜水服站在甲板上，海风吹动他的衣角，远处的灯塔亮着。"}],
        [_char(lock_zh="深蓝色潜水服")],
    )
    once, rec1 = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    assert rec1["scrubbed"] == 1
    twice, rec2 = _svc()._clean_pack_appearance_echo("shot_prompt", once)
    assert twice == once
    assert rec2["changed"] is False and rec2["action"] == "noop"


# --------------------------------------------------------------------------- ⑩
def _run_validator(path: Path) -> dict:
    """真跑判据脚本（`--json`），返回其机器可读结果（**不是模拟**）。"""
    proc = subprocess.run(  # noqa: S603 - 固定脚本 + 固定解释器
        [sys.executable, str(_VALIDATE_OUTPUT), "--file", str(path), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(_CODE_ROOT),
    )
    assert proc.stdout.strip(), proc.stderr
    return json.loads(proc.stdout)


def _codes(result: dict) -> set[str]:
    """失败码集合（`前缀 · Rnn NAME：…` → `Rnn NAME`）。"""
    out: set[str] = set()
    for entry in result.get("errors", []):
        parts = entry.split("·", 1)
        if len(parts) < 2:
            continue
        out.add(parts[1].strip().split("：")[0])
    return out


def test_gate_linkage_cleaning_removes_r28(tmp_path: Path) -> None:
    """⑩ 门禁联动：demo 包自带 1 条 `R28`（`S01-SH002`「眼神平」）⇒ 清洗后同码消失。

    ⚠️ 断言两头：① `R28` 真的消失；② **不新增任何码**（净效果不变差）。
    """
    raw = _DEMO_PACK.read_text(encoding="utf-8")  # **只读**：示例资产不得被测试改写
    dirty_path = tmp_path / "pack_r28_dirty.json"
    dirty_path.write_bytes(raw.encode("utf-8"))
    rep_dirty = _run_validator(dirty_path)
    codes_dirty = _codes(rep_dirty)
    assert "R28 PACK_APPEARANCE_ECHO" in codes_dirty, rep_dirty.get("errors")

    cleaned_text, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
    assert rec is not None and rec["scrubbed"] >= 1
    assert all(item["shot_id"] for item in rec["items"])

    clean_path = tmp_path / "pack_r28_clean.json"
    clean_path.write_bytes(cleaned_text.encode("utf-8"))
    rep_clean = _run_validator(clean_path)
    codes_clean = _codes(rep_clean)

    assert "R28 PACK_APPEARANCE_ECHO" not in codes_clean, rep_clean.get("errors")
    assert codes_clean <= (codes_dirty - {"R28 PACK_APPEARANCE_ECHO"}), (
        f"清洗引入了新的判据失败：{sorted(codes_clean - codes_dirty)}"
    )
    # 示例资产未被测试改动（只读纪律）
    assert _DEMO_PACK.read_text(encoding="utf-8") == raw


# --------------------------------------------------------------------------- ⑪
def test_non_pack_stage_unaffected() -> None:
    """只对形态 `pack` 生效（分镜层无 `prompt_zh`／`prompt_en` 语义，不该被本机制碰）。"""
    raw = _pack(
        [{"shot_id": "S01-SH001", "prompt_zh": "近景：他穿着深蓝色潜水服站在甲板上，海风很大。"}],
        [_char(lock_zh="深蓝色潜水服")],
    )
    out, rec = _svc()._clean_pack_appearance_echo("storyboard", raw)
    assert out == raw and rec is None


# --------------------------------------------------------------------------- ⑫
def test_examples_canary_bytes_noop() -> None:
    """**canary 锁**：`prompts/examples/` 三份正向样本 `R28` 全过 ⇒ 必须字节级 no-op。

    这条是「改造不得变差」的直接锁：一旦本机制开始改写**已经合规**的产物，这里立刻红。
    """
    block_re = re.compile(r"```json\s*\n(.*?)\n```", re.S)
    checked: list[str] = []
    for name in (
        "CASE-002_shot-prompt-case01.md",
        "CASE-005_revise-case01.md",
        "CASE-007_modify-pack-case01.md",
    ):
        path = _EXAMPLES / name
        blocks = block_re.findall(path.read_text(encoding="utf-8"))
        assert blocks, f"{name} 内无 ```json 块"
        doc = json.loads(blocks[0])
        assert _r28_errors(doc) == [], f"{name} 的样本本身含 R28 命中，不适宜作 canary"
        raw = json.dumps(doc, ensure_ascii=False, indent=2)
        out, rec = _svc()._clean_pack_appearance_echo("shot_prompt", raw)
        assert out == raw, f"{name}：正向样本被改写（scrubbed={rec and rec.get('scrubbed')}）"
        checked.append(name)
    assert len(checked) == 3
