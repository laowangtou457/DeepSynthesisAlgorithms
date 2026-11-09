# -*- coding: utf-8 -*-
"""`T-102`（2026-11-08）：`init_controlled.py --sync` 的 `history` 追加义务。

⚠️ 被测脚本位于 `09-合规资料库/06-构建工具/`，不在 `app/` 包内 ⇒ 按路径用
`importlib` 加载（与 `quality_gate._engine_validator()` 的既有做法同族）。
测试**只读数字**：临时受控区里写的是中性占位词条，绝不触碰 `E:/_受控区`
实体，也绝不改写工程内真实的 `controlled_assets.json`。
"""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]  # 03-工程代码/app/tests → 工程根
_SCRIPT = _ROOT / "09-合规资料库" / "06-构建工具" / "init_controlled.py"

_EXISTING_ROW = {
    "date": "2026-10-12",
    "action": "建立受控类达标机制与机读计数文件",
    "lexicon_added": 0,
    "bank_added": 0,
    "refuse_added": 0,
    "operator": "—",
    "reviewer": "—",
    "note": "机制就绪；受控内容须由安全负责人按受控流程在隔离环境编写后回填计数",
}


@pytest.fixture(scope="module")
def mod():
    if not _SCRIPT.exists():
        pytest.skip(f"受控回填脚本不在预期路径：{_SCRIPT}")
    spec = importlib.util.spec_from_file_location("init_controlled_under_test", _SCRIPT)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_zone(root: Path, mod, lex: int = 205, bank: int = 60, refuse: int = 25) -> None:
    """造一个中性占位受控区（只有条数有意义，无任何受控内容）。"""
    for sub in ("lexicon_controlled", "bank_controlled", "refuse_controlled"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for cid, _ in mod.CLASSES:
        (root / "lexicon_controlled" / f"{cid}.txt").write_text(
            "# 注释行不计入条数\n" + "\n".join(f"占位词条{i}" for i in range(lex)) + "\n",
            encoding="utf-8",
        )
        for sub, n in (("bank_controlled", bank), ("refuse_controlled", refuse)):
            (root / sub / f"{cid}.jsonl").write_text(
                "# 格式示例不计入条数\n"
                + "\n".join(json.dumps({"id": f"{cid}-{i}"}) for i in range(n))
                + "\n",
                encoding="utf-8",
            )


def _zero_counts() -> dict:
    return {k: {c: 0 for c in ("A1-01", "A1-02", "A1-03", "A1-05")}
            for k in ("lexicon", "bank", "refuse")}


def _write_ledger(path: Path, *, counts=None, status="pending_controlled_authoring",
                  history=None) -> dict:
    d = {
        "purpose": "受控类资产规模机读计数——只记条数，不含任何受控内容。",
        "last_updated": "2026-11-07",
        "status": status,
        "counts": counts if counts is not None else _zero_counts(),
    }
    if history is not None:
        d["history"] = history
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return d


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sync_appends_history_on_count_change(tmp_path, mod) -> None:
    zone, ledger = tmp_path / "zone", tmp_path / "ledger.json"
    _make_zone(zone, mod=mod)
    _write_ledger(ledger, history=[dict(_EXISTING_ROW)])

    assert mod.sync(str(zone), ctrl_json=str(ledger)) == 0
    d = _read(ledger)
    assert d["counts"]["lexicon"]["A1-01"] == 205
    assert d["counts"]["bank"]["A1-01"] == 60
    assert d["counts"]["refuse"]["A1-01"] == 25
    assert d["status"] == "ok"
    assert len(d["history"]) == 2
    e = d["history"][-1]
    # 与既有行同构（不新增字段）
    assert set(e) == set(_EXISTING_ROW)
    # 四类合计增量
    assert e["lexicon_added"] == 205 * 4
    assert e["bank_added"] == 60 * 4
    assert e["refuse_added"] == 25 * 4
    assert e["date"] == datetime.date.today().isoformat()
    assert e["operator"] == "—" and e["reviewer"] == "—"
    assert "T-102" in e["note"] and "不含任何受控内容" in e["note"]
    assert d["last_updated"] == e["date"]
    assert d["history"][0] == _EXISTING_ROW  # 既有行零改动


def test_sync_is_idempotent_when_nothing_changed(tmp_path, mod) -> None:
    zone, ledger = tmp_path / "zone", tmp_path / "ledger.json"
    _make_zone(zone, mod=mod)
    _write_ledger(ledger, history=[dict(_EXISTING_ROW)])
    assert mod.sync(str(zone), ctrl_json=str(ledger)) == 0
    first = _read(ledger)

    assert mod.sync(str(zone), ctrl_json=str(ledger)) == 0
    second = _read(ledger)
    assert second["history"] == first["history"]  # 幂等：不追加、不改写
    assert len(second["history"]) == 2


def test_sync_appends_when_only_status_changes(tmp_path, mod) -> None:
    """counts 已一致但 status 滞后（如人工改过）⇒ 仍须留痕。"""
    zone, ledger = tmp_path / "zone", tmp_path / "ledger.json"
    _make_zone(zone, mod=mod)
    # 直接造出「counts 与实测一致、status 却是 pending」的滞后态
    ids = ("A1-01", "A1-02", "A1-03", "A1-05")
    measured = {k: {c: v for c in ids}
                for k, v in (("lexicon", 205), ("bank", 60), ("refuse", 25))}
    _write_ledger(ledger, counts=measured, status="pending_controlled_authoring",
                  history=[dict(_EXISTING_ROW)])

    assert mod.sync(str(zone), ctrl_json=str(ledger)) == 0
    out = _read(ledger)
    assert len(out["history"]) == 2 and out["status"] == "ok"
    assert out["history"][-1]["lexicon_added"] == 0  # 计数无变化，增量为 0
    assert out["history"][0] == _EXISTING_ROW


def test_sync_initializes_missing_or_broken_history(tmp_path, mod) -> None:
    zone = tmp_path / "zone"
    _make_zone(zone, mod=mod)
    for broken in (None, "非列表"):
        ledger = tmp_path / f"ledger_{'missing' if broken is None else 'wrong'}.json"
        _write_ledger(ledger, history=broken)
        assert mod.sync(str(zone), ctrl_json=str(ledger)) == 0
        d = _read(ledger)
        assert isinstance(d["history"], list) and len(d["history"]) == 1


def test_append_sync_history_keeps_existing_rows_untouched(mod) -> None:
    """纯函数：既有 2 行逐字不变，新增行结构与既有一致。"""
    import copy
    hist = [dict(_EXISTING_ROW), dict(_EXISTING_ROW, date="2026-11-07", action="核验")]
    d = {"counts": copy.deepcopy(_zero_counts()), "status": "ok", "history": hist}
    before = copy.deepcopy(hist)
    new_counts = copy.deepcopy(d["counts"])
    new_counts["refuse"]["A1-05"] = 20

    assert mod.append_sync_history(d, new_counts, "2026-11-08", "ok") is True
    assert d["history"][:2] == before
    assert len(d["history"]) == 3
    assert set(d["history"][-1]) == set(before[0])
    assert d["history"][-1]["refuse_added"] == 20
    # 无变化 ⇒ 不追加
    assert mod.append_sync_history(d, d["counts"], "2026-11-08", "ok") is False
    assert len(d["history"]) == 3
