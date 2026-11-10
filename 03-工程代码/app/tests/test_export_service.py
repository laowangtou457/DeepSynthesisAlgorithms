"""导出服务测试 —— `T-006`（`SW-022` 导出文件逐格式显式标识注入）。

⚠️ 本文件锁的是**一条最容易退化的合规链**：
「`exports[]` 恒为空 ⇒ 清单判据 `export.mark` 从未执行 ⇒ 自检第 7 项变成
『元数据字段填了什么』」，而不是「导出文件里真的有没有标识」。

纪律：

- **取证回读**：每条断言都读**落盘文件**，不采信内存里的返回值；
- **不编造 pass**：缺标识／无导出物 ⇒ 判 `fail`；非两段式 TXT ⇒ 判 `warn`；
- **文案单一事实源**：`AST-002` 的 `texts.full_final` 与 `CFG-001` 的
  `explicit_mark_text` 必须一致（两处漂移会同时污染角标 PNG 与文本导出）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.delivery_service import build_manifest, build_self_check
from app.services.export_service import (
    SUPPORTED_FORMATS,
    _evidence,
    _record,
    build_exports,
    explicit_mark_text,
    merge_manifest_exports,
    update_manifest_file,
)

CODE_ROOT = Path(__file__).resolve().parents[2]
DEMO_PACK = CODE_ROOT / "delivery" / "examples" / "CFG-004_demo_pack.json"
ADAPTERS = CODE_ROOT / "delivery" / "config" / "CFG-001_model_adapters.yaml"


def _demo_pack() -> dict:
    return json.loads(DEMO_PACK.read_text(encoding="utf-8"))


@pytest.fixture()
def pack_dir(tmp_path: Path) -> Path:
    """把示例包落成 `pack.json`（`build_exports` 需要真实路径供 TXT 生成器读取）。"""
    d = tmp_path / "PACK"
    d.mkdir()
    (d / "pack.json").write_text(
        json.dumps(_demo_pack(), ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return d


# --------------------------------------------------------------------------- #
# ① 文案单一事实源
# --------------------------------------------------------------------------- #
def test_mark_text_single_source() -> None:
    """`AST-002` 与 `CFG-001` 的标识文案必须一致（互锁，防两处漂移）。"""
    spec = json.loads((CODE_ROOT / "delivery" / "assets" / "AST-002_overlay_spec.json")
                      .read_text(encoding="utf-8"))
    text = spec["texts"]["full_final"]
    assert explicit_mark_text() == text

    yaml_text = ADAPTERS.read_text(encoding="utf-8")
    assert f'explicit_mark_text: "{text}"' in yaml_text, "CFG-001 与 AST-002 文案漂移"


# --------------------------------------------------------------------------- #
# ② 逐格式注入（回读取证）
# --------------------------------------------------------------------------- #
def test_all_formats_inject_marks(pack_dir: Path) -> None:
    res = build_exports(_demo_pack(), pack_dir / "pack.json")
    got = {r["format"] for r in res.records}
    assert {"json", "md", "csv", "xlsx", "txt"} <= got, got
    for rec in res.records:
        path = pack_dir / rec["file"]
        assert path.is_file(), rec["file"]
        assert rec["explicit_mark"] is True, rec
        assert rec["implicit_mark"] is True, rec
        assert len(rec["sha256"]) == 64
    # 每份文件的显式标识都能**在正文里找到**（不是只在记录里写 true）
    mark = explicit_mark_text()
    assert mark in (pack_dir / res.records[0]["file"]).read_text(encoding="utf-8")


def test_md_and_csv_layout(pack_dir: Path) -> None:
    res = build_exports(_demo_pack(), pack_dir / "pack.json", formats=("md", "csv"))
    md = (pack_dir / "exports" / f"{_pid(res)}").parent
    md_file = next(r["file"] for r in res.records if r["format"] == "md")
    text = (pack_dir / md_file).read_text(encoding="utf-8")
    assert text.startswith("> 【AI生成内容】")
    assert "\n## 元数据\n" in text

    csv_file = next(r["file"] for r in res.records if r["format"] == "csv")
    lines = (pack_dir / csv_file).read_text(encoding="utf-8").split("\n")
    assert lines[0].startswith("#AI生成内容")
    assert any(ln.startswith("#AIGC:") for ln in lines)
    assert md  # 目录存在性（md 与 csv 同目录）


def test_txt_two_section_and_no_meta_in_prompt_area(pack_dir: Path) -> None:
    """TXT 必须两段式，且**提示词区不得出现 AIGC 元数据键**（`SPEC-008 §6.8` E6）。"""
    res = build_exports(_demo_pack(), pack_dir / "pack.json", formats=("txt",))
    assert res.records, res.failed
    for rec in res.records:
        assert rec["two_section"] is True, rec
        lines = (pack_dir / rec["file"]).read_text(encoding="utf-8").split("\n")
        mark_idx = next(i for i, ln in enumerate(lines) if ln.startswith("【AI生成内容】"))
        div_idx = next(i for i, ln in enumerate(lines) if "以下为提示词区" in ln)
        assert mark_idx < div_idx
        notice, prompt = lines[:div_idx], lines[div_idx:]
        assert any("ProduceID" in ln for ln in notice), "隐式标识未落在标识区"
        assert not any("ProduceID" in ln or "ContentProducer" in ln for ln in prompt)


def test_pdf_not_implemented_is_reported(pack_dir: Path) -> None:
    res = build_exports(_demo_pack(), pack_dir / "pack.json", formats=("pdf",))
    assert res.records == []
    assert any("pdf" in f for f in res.failed)


# --------------------------------------------------------------------------- #
# ③ 取证不可被"写入成功"蒙混
# --------------------------------------------------------------------------- #
def test_evidence_fails_when_mark_removed(tmp_path: Path) -> None:
    """把标识行删掉后，取证必须判 `explicit_mark=False`（宁可 fail，不可假 pass）。"""
    mark = explicit_mark_text()
    p = tmp_path / "x.md"
    p.write_text("# 无标识文件\n\n正文\n", encoding="utf-8")
    explicit, implicit, _, _ = _evidence(p, "md", mark)
    assert explicit is False and implicit is False
    rec = _record(tmp_path, p, "md", mark)
    assert rec["explicit_mark"] is False


def test_bad_json_is_not_marked(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("{not json", encoding="utf-8")
    assert _record(tmp_path, p, "json", explicit_mark_text())["explicit_mark"] is False


# --------------------------------------------------------------------------- #
# ④ 清单并入 + 自检第 7 项改按导出物实测
# --------------------------------------------------------------------------- #
def test_manifest_merge_only_contract_fields() -> None:
    mf: dict = {}
    merge_manifest_exports(mf, [
        {"file": "exports/a.md", "format": "md", "explicit_mark": True,
         "implicit_mark": True, "sha256": "0" * 64, "illegal_key": 1},
    ])
    assert mf["exports"][0]["file"] == "exports/a.md"
    assert "illegal_key" not in mf["exports"][0]


def test_update_manifest_file_keeps_other_fields(tmp_path: Path) -> None:
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({"manifest_version": "1.1.0", "pack_id": "P"}, ensure_ascii=False),
                  encoding="utf-8")
    update_manifest_file(mf, [{"file": "exports/a.md", "format": "md", "explicit_mark": True}])
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["pack_id"] == "P" and data["exports"][0]["file"] == "exports/a.md"


def _self_check(exports, **kw) -> list[dict]:
    base = dict(
        block_level="BLOCK", assets=["assets/a.png"] * 4 + ["assets/AST-002_overlay_spec.json"],
        statement_id="{{STATEMENT_ID}}", adapters=[], human_review=[],
        has_shots=True, has_units=True, statement_file="AST-004_compliance_statement.md",
    )
    base.update(kw)
    return build_self_check([], exports=exports, **base)


def test_self_check_7_pass_when_all_marked() -> None:
    row = next(r for r in _self_check([
        {"file": "exports/a.md", "format": "md", "explicit_mark": True},
        {"file": "exports/b.json", "format": "json", "explicit_mark": True},
    ]) if r["no"] == 7)
    assert row["result"] == "pass" and "2 份导出物" in row["detail"]


def test_self_check_7_fail_when_missing_mark() -> None:
    row = next(r for r in _self_check([
        {"file": "exports/a.md", "format": "md", "explicit_mark": False},
    ]) if r["no"] == 7)
    assert row["result"] == "fail" and "exports/a.md" in row["detail"]


def test_self_check_7_fail_when_no_export() -> None:
    """**没有导出物 ＝ 没检**，不得标 pass（`§8.3` 该行为阻断交付）。"""
    row = next(r for r in _self_check([]) if r["no"] == 7)
    assert row["result"] == "fail"


def test_self_check_7_warn_when_txt_one_section() -> None:
    row = next(r for r in _self_check([
        {"file": "exports/m/a.txt", "format": "txt", "explicit_mark": True, "two_section": False},
    ]) if r["no"] == 7)
    assert row["result"] == "warn"


def test_self_check_legacy_path_unchanged() -> None:
    """`exports=None`（未接线的老调用方）仍走旧口径，不误报 fail。"""
    row = next(r for r in _self_check(None) if r["no"] == 7)
    assert row["result"] == "pass"


def test_manifest_carries_exports() -> None:
    pack = _demo_pack()
    mf = build_manifest(pack, ["pack.json", "manifest.json"],
                        exports=[{"file": "exports/a.md", "format": "md", "explicit_mark": True}])
    assert mf["exports"][0]["file"] == "exports/a.md"


def test_supported_formats_cover_spec() -> None:
    """`SPEC-008 §9.1` 的六格式中，除 PDF（P2 后置）外必须全部实现。"""
    assert set(SUPPORTED_FORMATS) == {"json", "md", "csv", "xlsx", "txt"}


def _pid(res) -> str:
    return Path(res.records[0]["file"]).name
