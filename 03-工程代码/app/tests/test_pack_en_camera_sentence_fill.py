# -*- coding: utf-8 -*-
"""**投影规则⑤**：`R34` 英文运镜句的服务层机械补全（项目方 2026-11-16 裁决批准）。

为什么有这一条机制
------------------
`R34 EN_CAMERA_SENTENCE` 要求每镜 `prompt_en` 含**以 `The camera` 起句的独立句**。
`r6` 复验批（`DEV-20261112-012`）实测 **12/12 挂 R34、重试自愈 0/12**；
`ab_t101_r6/on/run1` 更实证「越试越差」（attempt1 缺 1 镜 → attempt2 缺 4 镜）。
模板侧已把该要求写进 `guards` 并在 examples 给正例（`TPL-009` v2.3.x），仍然漏
⇒ **模板措辞路线已到顶**，只能机制化处置。

本文件的落点
------------
被测对象是 `DialogueService._ensure_en_camera_sentence`（**纯函数式**，`__new__` 免依赖构造，
与 `test_camera_amp_speed_normalize.py` 同构）。覆盖八组 ＋ 两条锁：

  ① 缺句 ⇒ 追加一句且**自身过 `R34` 正则**（不是「写了就算」）；
  ② 已合规 ⇒ **字节级 no-op**（`out == raw`，一个字节都不改）；
  ③ `static`／`pov` ⇒ `The camera holds a static shot.` 且**不带幅度速度短语**；
  ④ 空 `prompt_en`（占位镜）⇒ **一律不动**（`_reconcile_pack_conservation` 明令留空，
     替它补句会把 `R27P` 的洞洗白）；
  ⑤ 开关关闭 ⇒ 原样返回（回退路径）；
  ⑥ **与门禁联动**（真跑 `prompts/validate_output.py --json`，不是模拟）：
     脏包 ⇒ `R34` 报出；过合成 ⇒ 同码消失；
  ⑦ 幂等（连跑两次输出相同）；
  ⑧ 三个标点／空白边界：`。` 结尾（记 `punct_normalized`）、末尾无终止符、句首前导空白；
  ⑨ **锁 A**：`CFG-002` 的 20 句 base 必须**全部**过 `R34` 正则（词表升版兜底）；
  ⑩ **锁 B**：`prompts/examples/` 的三份正向样本当前 `R34` 全过 ⇒ 对它们必须 no-op。

⚠️ 判据 `prompts/validate_output.py` **零改动**；本文件只测服务层的补全行为。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings
from app.services import quality_gate
from app.services.dialogue_service import (
    DialogueService,
    _camera_move_en_sentences,
    _render_camera_sentence,
)

_CODE_ROOT = Path(__file__).resolve().parents[2]          # 03-工程代码
_DEMO_PACK = _CODE_ROOT / "delivery" / "examples" / "CFG-004_demo_pack.json"
_VALIDATE_OUTPUT = _CODE_ROOT / "prompts" / "validate_output.py"
_EXAMPLES = _CODE_ROOT / "prompts" / "examples"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def _svc() -> DialogueService:
    """免依赖构造（不碰 repo／prompts／backend，与既有归一化层测试同构）。"""
    return DialogueService.__new__(DialogueService)


def _camera_re():
    """判据自己的正则（**不抄第二份**，与生产代码同一条取用路径）。"""
    module = quality_gate.load_engine_validator()
    assert module is not None, "判据模块 prompts/validate_output.py 不可加载"
    return module.CAMERA_SENTENCE_RE


def _shot(sid: str, move: str, prompt_en: str, **cam_extra) -> dict:
    return {
        "shot_id": sid,
        "camera": {"move": move, **cam_extra},
        "prompt_en": prompt_en,
        "prompt_zh": "远景：占位中文正文。",
    }


def _pack(shots: list[dict]) -> str:
    doc = {"units": [{"unit_id": "U01", "shot_ids": [s["shot_id"] for s in shots]}], "shots": shots}
    return json.dumps(doc, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- ①
def test_missing_sentence_appended_as_standalone_sentence() -> None:
    """缺句 ⇒ 追加，且补出的句子**自身**过 `R34` 正则（独立句，不是「写了就算」）。"""
    raw = _pack([_shot("S01-SH001", "push_in", "A wide shot of the sea. He turns to the door.")])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)

    assert rec is not None and rec["added"] == 1
    item = rec["items"][0]
    assert item["shot_id"] == "S01-SH001" and item["move"] == "push_in"
    assert item["action"] == "appended"

    en = json.loads(out)["shots"][0]["prompt_en"]
    # 原句一字不动（只追加）
    assert en.startswith("A wide shot of the sea. He turns to the door.")
    assert en == "A wide shot of the sea. He turns to the door. " + item["sentence"]
    assert _camera_re().search(en), en
    # 判据正则要求「独立句」：`The camera` 之前必须有句末标点＋空白
    assert re.search(r"[.!?]\s+The camera\b", en), en


def test_amplitude_and_speed_are_projected_into_the_sentence() -> None:
    """`camera.amplitude/speed` 存在 ⇒ 句内短语用实际值；省略 ⇒ 短语整体删掉。"""
    raw = _pack([
        _shot("S01-SH001", "push_in", "A wide shot. X.", amplitude="large", speed="fast"),
        _shot("S01-SH002", "push_in", "A wide shot. X."),
    ])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    by_id = {i["shot_id"]: i["sentence"] for i in rec["items"]}
    assert by_id["S01-SH001"] == "The camera pushes in with large amplitude at fast speed."
    # 键省略（非强调）⇒ 句子不带幅度速度（§3.7.2「仅当需要强调时」）
    assert by_id["S01-SH002"] == "The camera pushes in."


# --------------------------------------------------------------------------- ②
def test_compliant_text_is_byte_level_noop() -> None:
    """已含独立运镜句 ⇒ **一个字节都不改**（不重序列化、不重排缩进）。"""
    raw = _pack([
        _shot("S01-SH001", "push_in", "A wide shot. The camera pushes in with small amplitude."),
        _shot("S01-SH002", "static", "The camera holds a static shot. A medium shot."),
    ])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    assert out == raw
    assert rec is not None and rec["added"] == 0 and rec["action"] == "noop"


# --------------------------------------------------------------------------- ③
def test_static_and_pov_sentences_carry_no_amp_speed() -> None:
    """`static`／`pov` 也必须补句，但**不带幅度速度**（其 base 句本就没有）。"""
    raw = _pack([
        _shot("S01-SH001", "static", "A wide shot of the interior."),
        _shot("S01-SH002", "pov", "A medium shot of the corridor."),
    ])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    by_id = {i["shot_id"]: i["sentence"] for i in rec["items"]}
    assert by_id["S01-SH001"] == "The camera holds a static shot."
    assert by_id["S01-SH002"] == "The camera holds the subject's point of view."
    for sentence in by_id.values():
        assert "amplitude" not in sentence and "speed" not in sentence
    for shot in json.loads(out)["shots"]:
        assert _camera_re().search(shot["prompt_en"])


def test_static_keeps_self_consistency_with_amp_speed_cleanup() -> None:
    """`static` 即使残留幅速（上游清洗已删，这里防御性构造）也不写出幅速短语。"""
    raw = _pack([_shot("S01-SH001", "static", "A wide shot.", amplitude="small", speed="slow")])
    _, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    assert rec["items"][0]["sentence"] == "The camera holds a static shot."


# --------------------------------------------------------------------------- ④
def test_empty_prompt_en_placeholder_untouched() -> None:
    """占位镜（`prompt_en` 为空／缺失）⇒ **一律不动**，且计入 `skipped_empty`。

    ⚠️ 这是本机制的**红线**：`_reconcile_pack_conservation` 明令占位镜 `prompt_en` 留空
    「不伪造创作内容」；若这里替它补一句，`R27P`（占位镜缺字段）会被洗白成「齐备」。
    """
    raw = _pack([
        _shot("S01-SH001", "push_in", ""),
        {"shot_id": "S01-SH002", "camera": {"move": "push_in"}, "prompt_zh": "占位"},
        _shot("S01-SH003", "push_in", "A wide shot of the sea."),
    ])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    shots = {s["shot_id"]: s for s in json.loads(out)["shots"]}
    assert shots["S01-SH001"]["prompt_en"] == ""
    assert "prompt_en" not in shots["S01-SH002"]
    assert rec["skipped_empty"] == 2 and rec["added"] == 1


# --------------------------------------------------------------------------- ⑤
def test_switch_off_returns_text_unchanged() -> None:
    """回退开关：`APP_PACK_EN_CAMERA_SENTENCE_FILL=false` ⇒ 原样返回（`rec is None`）。"""
    settings = get_settings()
    original = settings.pack_en_camera_sentence_fill
    settings.pack_en_camera_sentence_fill = False
    try:
        raw = _pack([_shot("S01-SH001", "push_in", "A wide shot of the sea.")])
        out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
        assert out == raw and rec is None
    finally:
        settings.pack_en_camera_sentence_fill = original


def test_skip_for_non_pack_stage() -> None:
    """只对形态 `pack` 生效（分镜层无 `prompt_en` 语义，不该被本机制碰）。"""
    raw = _pack([_shot("S01-SH001", "push_in", "A wide shot of the sea.")])
    out, rec = _svc()._ensure_en_camera_sentence("storyboard", raw)
    assert out == raw and rec is None


def test_unparsable_text_returns_unchanged() -> None:
    """不可解析 ⇒ 原样返回（不是合法 JSON 由形态闸归因，不在此处抢先）。"""
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", "{不是 JSON")
    assert out == "{不是 JSON" and rec is None


# --------------------------------------------------------------------------- ⑥
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


def _r34_errors(result: dict) -> list[str]:
    return [e for e in result.get("errors", []) if "R34" in e]


def test_gate_linkage_fill_clears_r34(tmp_path: Path) -> None:
    """⑥ 门禁联动：把 demo 包的运镜句改坏 ⇒ `R34` 真报出；过合成 ⇒ 同码消失。"""
    data = json.loads(_DEMO_PACK.read_text(encoding="utf-8"))
    shots = data["shots"]
    assert len(shots) >= 2, "demo 包镜数不足以构造样本"
    # 把第 1 镜的独立运镜句改成「非 The camera 起句」（`R34` 的越界形态之一）
    target = shots[0]
    target["prompt_en"] = target["prompt_en"].replace("The camera ", "The rig ", 1)

    dirty = tmp_path / "pack_r34_dirty.json"
    dirty.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    rep_dirty = _run_validator(dirty)
    assert _r34_errors(rep_dirty), rep_dirty.get("errors")

    cleaned_text, rec = _svc()._ensure_en_camera_sentence(
        "shot_prompt", dirty.read_text(encoding="utf-8")
    )
    assert rec is not None and rec["added"] >= 1

    clean = tmp_path / "pack_r34_clean.json"
    clean.write_text(cleaned_text, encoding="utf-8")
    rep_clean = _run_validator(clean)
    assert not _r34_errors(rep_clean), rep_clean.get("errors")
    # 补句不该顺手引入别的判据失败：拿「脏包」与「补后」的失败集合比，
    # 只允许 R34 消失，不允许新增其它码（净效果不变差）。
    dirty_codes = {e.split("·")[1].strip().split("：")[0] for e in rep_dirty.get("errors", [])}
    clean_codes = {e.split("·")[1].strip().split("：")[0] for e in rep_clean.get("errors", [])}
    assert clean_codes <= (dirty_codes - {"R34 EN_CAMERA_SENTENCE"}) | set(), (
        f"补句引入了新的判据失败：{sorted(clean_codes - dirty_codes)}"
    )


def test_gate_linkage_real_defect_sample(tmp_path: Path) -> None:
    """⑥′ 真机形态复现：`S03-SH001` 等 4 镜「整句缺失」⇒ 补后 `R34` 归零。

    样本取自 r6 真机产物的**形态**（`ab_t101_r6`：运镜句整句缺失，不是并入前句）。
    """
    data = json.loads(_DEMO_PACK.read_text(encoding="utf-8"))
    shots = data["shots"]
    assert len(shots) >= 3
    for shot in shots:
        # 整句拿掉（真机形态：连小写 `the camera` 都没有）
        shot["prompt_en"] = re.sub(r"(^|[.!?]\s+)The camera\b[^.]*\.\s*", r"\1", shot["prompt_en"])
    dirty = tmp_path / "pack_r34_missing.json"
    dirty.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _r34_errors(_run_validator(dirty))

    cleaned_text, rec = _svc()._ensure_en_camera_sentence(
        "shot_prompt", dirty.read_text(encoding="utf-8")
    )
    assert rec is not None and rec["added"] == len(shots)
    clean = tmp_path / "pack_r34_filled.json"
    clean.write_text(cleaned_text, encoding="utf-8")
    assert not _r34_errors(_run_validator(clean))


# --------------------------------------------------------------------------- ⑦
def test_idempotent_second_run_is_noop() -> None:
    """幂等：补过的产物再跑一次必须逐字节不变、`added==0`。"""
    raw = _pack([
        _shot("S01-SH001", "push_in", "A wide shot of the sea."),
        _shot("S01-SH002", "static", "A medium shot of the crew."),
        _shot("S01-SH003", "arc", "雨夜。"),
    ])
    once, rec1 = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    assert rec1["added"] == 3
    twice, rec2 = _svc()._ensure_en_camera_sentence("shot_prompt", once)
    assert twice == once
    assert rec2["added"] == 0 and rec2["action"] == "noop"


# --------------------------------------------------------------------------- ⑧
def test_boundary_cjk_terminator_is_normalized_and_recorded() -> None:
    """前句以 `。` 结尾 ⇒ 归一为 ASCII `.` 并**逐镜留痕**（否则拼不出独立句）。"""
    raw = _pack([_shot("S01-SH001", "push_in", "雨夜，他站在门口。")])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    item = rec["items"][0]
    assert item["punct_normalized"] is True and item["punct_action"] == "cjk_to_ascii"
    en = json.loads(out)["shots"][0]["prompt_en"]
    assert en.startswith("雨夜，他站在门口. The camera ")
    assert _camera_re().search(en)


def test_boundary_missing_terminator_gets_one() -> None:
    """正文末尾无终止符 ⇒ 先补句号（否则追加句无法成为「独立句」）并留痕。"""
    raw = _pack([_shot("S01-SH001", "pan_left", "A close-up of the box")])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    item = rec["items"][0]
    assert item["punct_action"] == "terminator_added"
    en = json.loads(out)["shots"][0]["prompt_en"]
    assert en == "A close-up of the box. The camera pans left."
    assert _camera_re().search(en)


def test_boundary_leading_whitespace_trimmed_not_duplicated() -> None:
    """句首前导空白会让 `^` 失配 ⇒ **去掉空白**，**绝不追加第二句运镜句**。

    ⚠️ 追加会让同一镜出现两次运镜（语义上等于两个机位动作），属错误修法。
    """
    raw = _pack([_shot("S01-SH001", "push_in", "  The camera pushes in. A wide shot of the sea.")])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    item = rec["items"][0]
    assert item["action"] == "leading_trimmed" and item["sentence"] is None
    en = json.loads(out)["shots"][0]["prompt_en"]
    assert en == "The camera pushes in. A wide shot of the sea."
    assert en.count("The camera") == 1
    assert _camera_re().search(en)


# --------------------------------------------------------------------------- ⑨
def test_vocab_base_sentences_are_all_r34_compliant() -> None:
    """**锁 A**：`CFG-002` 的 20 句 base 必须**全部**过 `R34` 正则。

    词表升版（改措辞／加运镜码）若写出不成「`The camera` 起句独立句」的句子，
    本机制会**静默地把不合规句子写进产品**——所以在此锁住（代码里已有逐镜自检
    兜底跳过，但那是 fail-open，锁在这里才看得见）。
    """
    sentences = _camera_move_en_sentences()
    assert sentences, "CFG-002 未读出 camera_move[].model_map.minimax_h3"
    assert {"static", "pov", "push_in"} <= set(sentences)
    camera_re = _camera_re()
    bad = {code: s for code, s in sentences.items() if not camera_re.search(s)}
    assert not bad, f"CFG-002 中存在未以 `The camera` 起句的 base 句（R34 口径）：{bad}"


def test_render_keeps_base_when_amp_speed_absent() -> None:
    """幅速键缺失 ⇒ base 句里的幅速短语被删净（不留双空格／断句）。"""
    out = _render_camera_sentence("The camera arcs around the subject with small amplitude at slow speed.", {})
    assert out == "The camera arcs around the subject."
    out2 = _render_camera_sentence(
        "The camera arcs around the subject with small amplitude at slow speed.",
        {"amplitude": "large"},
    )
    assert out2 == "The camera arcs around the subject with large amplitude."


def test_unknown_move_is_skipped_not_guessed() -> None:
    """`camera.move` 不在词表 ⇒ **跳过该镜并计数**（不猜句式，fail-open 但留痕）。"""
    raw = _pack([
        {"shot_id": "S01-SH001", "camera": {}, "prompt_en": "A wide shot."},
        {"shot_id": "S01-SH002", "camera": {"move": "not_a_move"}, "prompt_en": "A wide shot."},
        _shot("S01-SH003", "push_in", "A wide shot."),
    ])
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    assert rec["skipped_no_vocab"] == 2
    assert rec["added"] == 1
    shots = {s["shot_id"]: s for s in json.loads(out)["shots"]}
    assert shots["S01-SH001"]["prompt_en"] == "A wide shot."
    assert shots["S01-SH002"]["prompt_en"] == "A wide shot."


# --------------------------------------------------------------------------- ⑩
def test_positive_examples_are_noop() -> None:
    """**锁 B**：`prompts/examples/` 的三份正向样本当前 `R34` 全过 ⇒ 对它们必须 no-op。

    ⚠️ 这条是「改造不得变差」的直接锁：若哪天本机制开始改写**已经合规**的产物，
    这里立刻红（比等真机跑测发现要好）。
    """
    checked: list[str] = []
    for name in ("CASE-002_shot-prompt-case01.md", "CASE-005_revise-case01.md",
                 "CASE-007_modify-pack-case01.md"):
        path = _EXAMPLES / name
        blocks = _JSON_BLOCK_RE.findall(path.read_text(encoding="utf-8"))
        assert blocks, f"{name} 内无 ```json 块"
        doc = json.loads(blocks[0])
        raw = json.dumps(doc, ensure_ascii=False, indent=2)
        out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
        assert out == raw, f"{name}：正向样本被改写（added={rec and rec.get('added')}）"
        checked.append(name)
    assert len(checked) == 3


def test_demo_pack_is_noop_but_can_be_repaired() -> None:
    """demo 包（`R34` 全过）⇒ no-op；把一镜改坏后能修回 —— 同一份资产验两头。"""
    raw = _DEMO_PACK.read_text(encoding="utf-8")
    out, rec = _svc()._ensure_en_camera_sentence("shot_prompt", raw)
    assert out == raw and rec["added"] == 0

    doc = json.loads(raw)
    doc["shots"][0]["prompt_en"] = "A wide shot with no camera sentence at all."
    broken = json.dumps(doc, ensure_ascii=False, indent=2)
    fixed, rec2 = _svc()._ensure_en_camera_sentence("shot_prompt", broken)
    assert rec2["added"] == 1
    assert _camera_re().search(json.loads(fixed)["shots"][0]["prompt_en"])
