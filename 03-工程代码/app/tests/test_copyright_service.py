"""版权校验与改编来源声明（`SW-015`）单测。

覆盖三条要求的**可实施部分**：

- ① 相似度检测：库未建立 ⇒ `not_available`（**不是** `passed`）；库存在 ⇒ 真比对，
  ≥ 阈值判 `risk` 并**逐条列明**；
- ② 改编来源声明：缺失如实标「未提交」，**不代填「原创」**；
- ③ 风险不阻断：`risk` 不进阻断码集合（由 `pack_meta`／门禁侧保证，本文件只验服务输出）。

⚠️ 另断言**交付可见文案不含内部任务号**（声明件随包发给客户／监管）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import copyright_service as cs

# 一段「含中文、长度达标」的示例创作内容
SAMPLE = "雨夜的街道上，少年撑着黑伞独自行走，路灯把影子拉得很长，远处传来电车的声音。"
SAMPLE_B = "清晨的码头上，老渔夫修补渔网，海鸥在头顶盘旋，潮水一遍遍拍打石阶。"


def _pack(text: str = SAMPLE) -> dict:
    return {
        "shots": [{"shot_id": "S01-SH001", "prompt": text, "action": text}],
        "meta": {"pack_id": "FX-PK-20261111-abcdef12"},
    }


# ---------- ① 相似度检测 ----------


def test_corpus_missing_is_not_available_not_passed() -> None:
    """库未建立 ⇒ `not_available`。**绝不可**折算为 `passed`（「没检」≠「没风险」）。"""
    v = cs.check(_pack(), corpus_root="")
    assert v["status"] == "not_available"
    assert v["max_similarity"] is None, "未做比对时不得给出相似度数字"
    assert v["hits"] == []
    assert v["corpus"]["available"] is False
    assert "未建立" in v["corpus"]["reason"]


def test_corpus_missing_reports_candidate_texts() -> None:
    """库未建立时仍须如实报告「本来有多少段待比对」，不得显示 0 段。"""
    v = cs.check(_pack(), corpus_root="")
    assert v["checked_texts"] == 0
    assert v["candidate_texts"] > 0


def test_corpus_missing_note_has_no_internal_task_id() -> None:
    """交付可见文案不得出现内部任务号（`T-0xx`）。"""
    v = cs.check(_pack(), corpus_root="")
    assert not re.search(r"\bT-\d{3}\b", v["note"])
    assert not re.search(r"\bT-\d{3}\b", v["corpus"]["reason"])


def test_corpus_path_not_exist(tmp_path: Path) -> None:
    v = cs.check(_pack(), corpus_root=tmp_path / "nope")
    assert v["status"] == "not_available"
    assert "不存在" in v["corpus"]["reason"]


def test_corpus_empty_dir(tmp_path: Path) -> None:
    v = cs.check(_pack(), corpus_root=tmp_path)
    assert v["status"] == "not_available"
    assert "为空" in v["corpus"]["reason"]


def test_identical_text_is_risk(tmp_path: Path) -> None:
    """与作品库正文完全相同 ⇒ 相似度 1.0 ≥ 阈值 ⇒ `risk`，且命中项可定位。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    v = cs.check(_pack(SAMPLE), corpus_root=tmp_path, threshold=0.5)
    assert v["status"] == "risk"
    assert v["max_similarity"] == pytest.approx(1.0)
    assert v["hits"], "检出风险必须逐条列出"
    hit = v["hits"][0]
    assert hit["work"] == "某受保护作品"
    assert hit["where"].startswith("shots[")
    assert hit["similarity"] >= 0.5


def test_different_text_passes(tmp_path: Path) -> None:
    """完全无关的两段文本 ⇒ `passed`，且给出实际相似度（不是 None）。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    v = cs.check(_pack(SAMPLE_B), corpus_root=tmp_path, threshold=0.5)
    assert v["status"] == "passed"
    assert v["max_similarity"] is not None
    assert v["max_similarity"] < 0.5
    assert v["hits"] == []


def test_threshold_is_configurable(tmp_path: Path) -> None:
    """阈值可配置，且**只影响判定、不影响测量**（同一对文本的相似度不随阈值漂移）。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    # 构造「部分相似」文本：首段与作品相同、后半不同 ⇒ 相似度严格落在 (0, 1)
    partial = SAMPLE[:20] + "然而海风突然转向，沙尘遮住了整片天空，行人纷纷躲避。"
    lo = cs.check(_pack(partial), corpus_root=tmp_path, threshold=0.01)
    hi = cs.check(_pack(partial), corpus_root=tmp_path, threshold=0.99)
    assert lo["status"] == "risk", "低阈值下部分相似须判 risk"
    assert hi["status"] == "passed", "高阈值下同一文本不得判 risk"
    assert lo["max_similarity"] == hi["max_similarity"] == pytest.approx(
        cs.similarity(partial, SAMPLE)
    ), "阈值只决定判定结果，不得改变测量值"


def test_similarity_is_symmetric_and_bounded() -> None:
    assert cs.similarity(SAMPLE, SAMPLE) == pytest.approx(1.0)
    assert cs.similarity(SAMPLE, SAMPLE_B) == cs.similarity(SAMPLE_B, SAMPLE)
    assert 0.0 <= cs.similarity(SAMPLE, SAMPLE_B) <= 1.0
    assert cs.similarity("", SAMPLE) == 0.0


def test_collect_texts_skips_meta_and_short_values() -> None:
    """`meta` 不参与比对（全是编号／状态，扫了只会假命中）；短取值同样跳过。"""
    pack = {
        "meta": {"pack_id": "FX-PK-20261111-abcdef12", "note": "这是一段很长很长的元数据说明文字不该被扫到"},
        "shots": [
            {"shot_id": "S01-SH001", "prompt": SAMPLE, "amplitude": "中"},
            {"shot_id": "S01-SH002", "prompt": "短"},
        ],
    }
    got = cs.collect_texts(pack)
    paths = [p for p, _ in got]
    assert all(not p.startswith("meta") for p in paths), "meta 不得参与版权比对"
    assert any(p.endswith(".prompt") for p in paths)
    assert all(len(t) >= cs.MIN_TEXT_LEN for _, t in got)


def test_pack_without_text_is_not_available(tmp_path: Path) -> None:
    """库存在但包内无可比对文本 ⇒ 仍是 `not_available`（没比对），不是 passed。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    v = cs.check({"shots": []}, corpus_root=tmp_path)
    assert v["status"] == "not_available"
    assert v["checked_texts"] == 0


# ---------- ② 改编来源声明 ----------


def test_declaration_missing_is_not_filled() -> None:
    """声明缺失 ⇒ `present=False`。**绝不代填「原创」**（权属陈述只能由提交方作出）。"""
    for raw in (None, "", "   ", {}, {"source_work": "某作品"}):
        d = cs.normalize_declaration(raw)
        assert d["present"] is False
        assert d["origin"] == ""


def test_declaration_str_form() -> None:
    d = cs.normalize_declaration("改编自公有领域小说")
    assert d["present"] is True
    assert d["origin"] == "改编自公有领域小说"


def test_declaration_dict_form() -> None:
    d = cs.normalize_declaration(
        {"origin": "改编", "source_work": "某小说", "license": "已获授权", "declarant": "客户 A"}
    )
    assert d["present"] is True
    assert d["source_work"] == "某小说"
    assert d["license"] == "已获授权"
    assert d["declarant"] == "客户 A"


# ---------- ③ 声明件（可留存、可导出） ----------


def test_declaration_doc_states_checked_when_corpus_missing() -> None:
    """库未建立时，声明件必须**明写「未校验」**，不得用「已校验」含混表述。"""
    v = cs.check(_pack(), corpus_root="")
    doc = cs.build_declaration(
        pack_id="FX-PK-20261111-abcdef12",
        session_id="sess_x",
        verdict=v,
        declaration=cs.normalize_declaration(None),
    )
    assert "未校验" in doc
    assert "**未校验**" in doc, "结论须加粗醒目，避免读者误读为已通过"
    assert "本次最高相似度：**未计算**" in doc
    assert "待比对内容段数" in doc, "须区分「待比对」与「实际比对」，否则客户误读成「包内无内容」"
    assert "实际比对：0" in doc
    assert "未提交改编来源声明" in doc
    assert "风险由提交方自负" in doc


def test_declaration_doc_lists_hits_one_by_one(tmp_path: Path) -> None:
    """`SW-015` ③：风险命中项须**逐条列明**，不许汇总成一句「存在风险」。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "另一部作品.txt").write_text(SAMPLE, encoding="utf-8")
    v = cs.check(_pack(SAMPLE), corpus_root=tmp_path, threshold=0.5)
    assert v["status"] == "risk"
    doc = cs.build_declaration(
        pack_id="FX-PK-20261111-abcdef12",
        session_id="sess_x",
        verdict=v,
        declaration=cs.normalize_declaration("原创"),
    )
    assert "检出项（逐条列明）" in doc
    for h in v["hits"]:
        assert h["work"] in doc
    assert doc.count("核对改编授权") >= len(v["hits"])


def test_declaration_doc_has_no_internal_task_id(tmp_path: Path) -> None:
    """声明件随包交给客户／监管 ⇒ 不得出现内部任务号与受控分类码。"""
    (tmp_path / "某受保护作品.txt").write_text(SAMPLE, encoding="utf-8")
    for v in (cs.check(_pack(), corpus_root=""), cs.check(_pack(SAMPLE), corpus_root=tmp_path)):
        doc = cs.build_declaration(
            pack_id="FX-PK-20261111-abcdef12",
            session_id="sess_x",
            verdict=v,
            declaration=cs.normalize_declaration("原创"),
        )
        assert not re.search(r"\bT-\d{3}\b", doc), doc[:400]
        assert not re.search(r"\bA[1-5]-\d{2}\b", doc), "受控分类码不得出现在交付件"


def test_declaration_filename_is_stable_and_safe() -> None:
    a = cs.declaration_filename("FX-PK-20261111-abcdef12")
    b = cs.declaration_filename("FX-PK-20261111-abcdef12")
    assert a == b, "同包重复打包不得散落成多份声明"
    assert a.endswith(".md")
    assert "{{" not in a, "占位 pack_id 须净化，避免非法路径字符"
    assert cs.declaration_filename("{{PROVIDER}}-PK-x").count("/") == 0
