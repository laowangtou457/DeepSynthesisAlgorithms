"""`SW-I04` 交付包端点测试 —— `T-006`。

⚠️ 纪律：

- **不依赖真实会话产物**——用 `tmp_path` 造确定性交付包（与 `test_safety.py` 同纪律）；
- **占位如实**——`pack_id`／`statement_id` 是占位时，响应**必须**标 `is_preview=true`
  且 `unfilled` 非空（`PRO-007` 根因 A／B 未决前的诚实边界）；
- **不臆造合规结论**——`compliance.*` 一律取服务层真值，端点**不二次生成**。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError
from app.services.delivery_service import (
    PACK_TOP_KEYS,
    PREVIEW_NOTE,
    build_manifest,
    pack_delivery,
)


def _fake_pack(*, pack_id: str = "{{PROVIDER_CODE}}-PK-20261103-ABCD1234",
               statement_id: str = "{{STATEMENT_ID}}",
               provider_code: str = "{{PROVIDER_CODE}}") -> dict:
    """构造一个**形态合法**的交付包（顶层键齐、含占位）。"""
    return {
        "schema_version": "2.2.0",
        "meta": {
            "pack_id": pack_id,
            "title": "测试作品",
            "created_at": "2026-11-03T15:00:00+08:00",
            "task_type": "text_to_video",
            "unsupported_task_types": ["keyframe_completion：本期不作适配"],
            "generator": {
                "system": "测试系统",
                "version": "0.1.0",
                "provider": "{{PROVIDER_NAME}}",
                "provider_code": provider_code,
            },
            "generation_trace": {
                "session_id": "SESS-TEST-0001",
                "task_id": "TASK-TEST-0001",
                "stage_chain": ["synopsis", "script", "storyboard", "shot_prompt"],
                "templates": [{"id": "shot_prompt_v1", "version": "2.2.0"}],
                "model": {"name": "mock", "backend": "mock", "revision": "0"},
            },
            "compliance": {
                "safety_check": {"input": "passed", "output": "passed"},
                "copyright_check": {"status": "占位（版权校验未接入，见任务 T-008）", "note": ""},
                "marking_check": {"explicit": "占位", "implicit": "占位"},
                "statement_id": statement_id,
            },
            "_unfilled": ["generator.provider_code", "compliance.statement_id"],
        },
        "style_bible": {"visual_style": "写实", "color_tone": "冷调"},
        "characters": [],
        "props": [],
        "units": [{"unit_id": "U01", "title": "单元一"}],
        "shots": [{"shot_id": "SH001", "prompt_zh": "废弃采矿站", "prompt_en": "an abandoned mine"}],
        "forbidden_items": [],
        "aigc_meta": {
            "AIGC": {
                "Label": "1",
                "ContentProducer": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
                "ProduceID": pack_id,
                "ReservedCode1": "",
                "ContentPropagator": "{{PROVIDER_NAME}}/{{PROVIDER_CODE}}",
                "PropagateID": pack_id,
                "ReservedCode2": "",
            }
        },
    }


class _FakeRec:
    def __init__(self, artifacts: dict) -> None:
        self.artifacts = artifacts
        self.session_id = "SESS-TEST-0001"


class _FakeSvc:
    def __init__(self, artifacts: dict) -> None:
        self._rec = _FakeRec(artifacts)

    def _require(self, session_id: str) -> _FakeRec:
        return self._rec


def _svc_with(pack: dict | None) -> _FakeSvc:
    if pack is None:
        return _FakeSvc({})
    return _FakeSvc({"shot_prompt": {"text": json.dumps(pack, ensure_ascii=False)}})


# ---------------------------------------------------------------- 打包


def test_pack_writes_four_pieces(tmp_path: Path) -> None:
    """交付四件套齐备：提示词集 ＋ 标识素材 ＋ 合规声明 ＋ 清单。"""
    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    d = Path(r.pack_dir)
    assert (d / "pack.json").is_file()
    assert (d / "manifest.json").is_file()
    assert (d / "AST-004_compliance_statement.md").is_file()
    # ② 标识素材包（AST-001 目录存在时至少复制说明文件）
    assert "pack.json" in r.files
    assert "manifest.json" in r.files
    assert "AST-004_compliance_statement.md" in r.files
    assert r.pack_bytes > 0


def test_pack_preserves_placeholders_and_marks_preview(tmp_path: Path) -> None:
    """⚠️ **占位如实**：占位不被编造替换，且 `is_preview=true`、`unfilled` 非空。"""
    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    assert r.is_preview is True
    assert "compliance.statement_id" in r.unfilled
    assert "generator.provider_code" in r.unfilled
    # 落盘的包内占位**原样保留**（不得被编造值替换）
    saved = json.loads((Path(r.pack_dir) / "pack.json").read_text(encoding="utf-8"))
    assert saved["meta"]["compliance"]["statement_id"] == "{{STATEMENT_ID}}"
    assert saved["meta"]["generator"]["provider_code"] == "{{PROVIDER_CODE}}"
    # 预演包留痕说明须在
    assert PREVIEW_NOTE


def test_pack_rejects_missing_artifact(tmp_path: Path) -> None:
    """无 `shot_prompt` 产物 ⇒ 报 NOT_FOUND（**不得**静默产出空包）。"""
    try:
        pack_delivery(svc=_svc_with(None), session_id="SESS-X",
                      out_dir=str(tmp_path), settings=Settings())
    except AppError as e:
        assert e.code == "NOT_FOUND"
    else:
        raise AssertionError("应当抛 NOT_FOUND")


def test_pack_rejects_incomplete_top_keys(tmp_path: Path) -> None:
    """缺顶层键 ⇒ 报 VALIDATION_ERROR（形态契约 `CFG-006`）。"""
    bad = _fake_pack()
    del bad["aigc_meta"]
    try:
        pack_delivery(svc=_svc_with(bad), session_id="SESS-X",
                      out_dir=str(tmp_path), settings=Settings())
    except AppError as e:
        assert e.code == "VALIDATION_ERROR"
        assert "aigc_meta" in str(e.details or "") or "aigc_meta" in str(e)
    else:
        raise AssertionError("应当抛 VALIDATION_ERROR")


def test_pack_is_idempotent_by_pack_id(tmp_path: Path) -> None:
    """同一 `pack_id` 重复打包 ⇒ 落到**同一目录**（不产生散落副本）。

    ⚠️ `pack_id` 的短码是**随机**的（`uuid4().hex[:8]`）⇒ 幂等性只在
    **同一个 `pack_id`** 的前提下成立；不同 `pack_id` 落不同目录是**正确**的。
    ⚠️ 沿用已有 `pack_id` 前**须验服务层形态**（`_<企业码>-PK-<日期>-<8位大写十六进制>`）
    —— 模型自拟的编号**不可信**（`SW-013`）。
    """
    pack = _fake_pack(pack_id="FR-PK-20261103-A1B2C3D4")
    out = tmp_path / "delivery"
    a = pack_delivery(svc=_svc_with(pack), session_id="S", out_dir=str(out), settings=Settings())
    b = pack_delivery(svc=_svc_with(pack), session_id="S", out_dir=str(out), settings=Settings())
    assert a.pack_dir == b.pack_dir
    assert Path(a.pack_dir).name == "FR-PK-20261103-A1B2C3D4"
    # 不同 pack_id ⇒ 不同目录
    other = _fake_pack(pack_id="FR-PK-20261103-0F1E2D3C")
    c = pack_delivery(svc=_svc_with(other), session_id="S", out_dir=str(out), settings=Settings())
    assert c.pack_dir != a.pack_dir


def test_pack_replaces_malformed_pack_id_from_model(tmp_path: Path) -> None:
    """⚠️ **模型自拟的不合规 `pack_id` 不得被沿用** ⇒ 改用服务层生成的编号并留痕。

    依据 `SW-013`（内容编号不可被删除篡改隐匿）＋ 服务层真值纪律。
    """
    pack = _fake_pack(pack_id="模型自己编的编号")
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="S", out_dir=str(out), settings=Settings())
    assert r.pack_id != "模型自己编的编号"
    assert "-PK-" in r.pack_id
    # 留痕：须在 `meta.notes` 里说明改过
    saved = json.loads((Path(r.pack_dir) / "pack.json").read_text(encoding="utf-8"))
    assert "pack_id" in (saved["meta"].get("notes") or "")


# ---------------------------------------------------------------- 清单


def test_manifest_counts_and_compliance_are_carried() -> None:
    """清单须带**镜头/单元计数**与**合规状态**（供交 reviewer 与备案举证）。"""
    pack = _fake_pack()
    mf = build_manifest(pack, ["pack.json"])
    assert mf["counts"]["shots"] == 1
    assert mf["counts"]["units"] == 1
    assert mf["compliance"]["safety_check"]["input"] == "passed"
    assert mf["compliance"]["statement_id"] == "{{STATEMENT_ID}}"
    assert mf["is_preview"] is True
    assert mf["preview_note"] == PREVIEW_NOTE
    # 顶层键齐备
    for k in PACK_TOP_KEYS:
        assert k in pack


# ================================================================ ISSUE-055 ①′ 分档门禁（2026-11-04）

def test_preview_pack_reports_gate_but_still_delivers(tmp_path: Path) -> None:
    """★ **预演包**：门禁照跑、结论如实呈现，但**不拒付**（占位是常态，拒付＝端点长期不可用）。

    断言要点：
    - `gate.checked=True` 且 `blocked=True`（`compliance.copyright` 未校验 ⇒ BLOCK 档）；
    - 四件套照常落盘，响应可读；
    - **`gate_report.json` 随包留档**（`SW-026` 要求自检记录可调取）且**不进** `manifest.files`。
    """
    from app.services.delivery_service import GATE_REPORT_NAME

    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    d = Path(r.pack_dir)

    assert r.is_preview is True
    assert r.gate["checked"] is True, "预演包也必须跑门禁（只呈现不拒付，≠ 不检查）"
    assert r.gate["blocked"] is True
    codes = [b["code"] for b in r.gate["blocks"]]
    assert "compliance.copyright" in codes, f"版权未校验未报 BLOCK：{codes}"
    assert r.gate["scope"] == "pack"
    assert r.gate["manifest_checked"] is False, "清单侧未校验须如实标记（不得假覆盖）"

    report = d / GATE_REPORT_NAME
    assert report.is_file(), "自检报告必须随包留档"
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["blocked"] is True and saved["is_preview"] is True

    # ⚠️ 裁决③：报告**不进**交付清单 files（审计附随件，不是交付载荷）
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert GATE_REPORT_NAME not in (mf.get("files") or [])
    assert GATE_REPORT_NAME not in (r.files or [])


def _patch_formal(monkeypatch, *, blocked: bool):
    """把「正式包 + 指定门禁结论」注入（当前 `statement_id` 恒为占位 ⇒ 正式态不可由 API 达成）。"""
    from app.services import delivery_service as ds

    def _truth(**kwargs):  # noqa: ANN003
        return {
            "pack_id": "FR-PK-20261104-ABCD1234",
            "created_at": "2026-11-04T12:00:00+08:00",
            "task_type": "text_to_video",
            "generator": {"system": "S", "version": "0.1.0",
                          "provider": "FR", "provider_code": "FR"},
            "generation_trace": {"session_id": "SESS-TEST-0001", "task_id": "T-1",
                                 "stage_chain": ["synopsis"], "templates": [],
                                 "model": {"name": "mock", "backend": "mock", "revision": "0"}},
            "compliance": {
                "safety_check": {"input": "passed", "output": "passed"},
                "copyright_check": {"status": "passed", "note": ""},
                "marking_check": {"explicit": "present", "implicit": "present"},
                "statement_id": "ST-001",
            },
            "_unfilled": [],  # ⚠️ 无未回填项 ⇒ 正式包
        }

    monkeypatch.setattr(ds, "build_pack_meta", _truth, raising=True)
    monkeypatch.setattr(ds, "evaluate_gate", lambda p: {
        "checked": True, "blocked": blocked,
        "blocks": ([{"code": "compliance.copyright", "message": "版权未校验"}] if blocked else []),
        "warns": [], "block_count": 1 if blocked else 0, "warn_count": 0,
        "scope": "pack", "manifest_checked": False, "manifest_note": "test",
    }, raising=True)


def test_formal_pack_blocked_raises_422_and_keeps_report(tmp_path: Path, monkeypatch) -> None:
    """★ **正式包 + BLOCK ⇒ 拒付 422**（`SW-026`「自检未通过→阻断交付并告警」）。

    ⚠️ 拒付时**不得删除已落盘目录**：自检记录须留档 ≥6 个月、可随时调取。
    """
    _patch_formal(monkeypatch, blocked=True)
    pack = _fake_pack(pack_id="FR-PK-20261104-ABCD1234", statement_id="ST-001", provider_code="FR")
    out = tmp_path / "delivery"
    try:
        pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    except AppError as e:
        assert e.code == "DELIVERY_PACK_INVALID", f"422 专用码不对：{e.code}"
        assert e.details.get("gate_blocks") == ["compliance.copyright"], e.details
        report = Path(e.details["gate_report"])
        assert report.is_file(), "拒付也必须留下自检报告（留档要求）"
        assert json.loads(report.read_text(encoding="utf-8"))["blocked"] is True
        assert Path(e.details["pack_dir"]).is_dir(), "拒付不得删除目录"
    else:
        raise AssertionError("正式包 BLOCK 必须拒付")


def test_formal_pack_passed_returns_gate_ok(tmp_path: Path, monkeypatch) -> None:
    """正式包 + 无 BLOCK ⇒ 正常交付，`gate.blocked=False`、无预演说明。"""
    _patch_formal(monkeypatch, blocked=False)
    pack = _fake_pack(pack_id="FR-PK-20261104-ABCD1234", statement_id="ST-001", provider_code="FR")
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    assert r.is_preview is False
    assert r.gate["blocked"] is False
    assert r.gate["checked"] is True
    assert (Path(r.pack_dir) / "gate_report.json").is_file()


# ================================================================ ISSUE-055 ①′ 分档门禁（2026-11-04）

def test_preview_pack_reports_gate_but_still_delivers(tmp_path: Path) -> None:
    """★ **预演包**：门禁照跑、结论如实呈现，但**不拒付**（占位是常态，拒付＝端点长期不可用）。

    断言要点：
    - `gate.checked=True` 且 `blocked=True`（`compliance.copyright` 未校验 ⇒ BLOCK 档）；
    - 四件套照常落盘，响应可读；
    - **`gate_report.json` 随包留档**（`SW-026` 要求自检记录可调取）且**不进** `manifest.files`。
    """
    from app.services.delivery_service import GATE_REPORT_NAME

    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    d = Path(r.pack_dir)

    assert r.is_preview is True
    assert r.gate["checked"] is True, "预演包也必须跑门禁（只呈现不拒付，≠ 不检查）"
    assert r.gate["blocked"] is True
    codes = [b["code"] for b in r.gate["blocks"]]
    assert "compliance.copyright" in codes, f"版权未校验未报 BLOCK：{codes}"
    assert r.gate["scope"] == "pack"
    assert r.gate["manifest_checked"] is False, "清单侧未校验须如实标记（不得假覆盖）"

    report = d / GATE_REPORT_NAME
    assert report.is_file(), "自检报告必须随包留档"
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["blocked"] is True and saved["is_preview"] is True

    # ⚠️ 裁决③：报告**不进**交付清单 files（审计附随件，不是交付载荷）
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert GATE_REPORT_NAME not in (mf.get("files") or [])
    assert GATE_REPORT_NAME not in (r.files or [])


def _patch_formal(monkeypatch, *, blocked: bool):
    """把「正式包 + 指定门禁结论」注入（当前 `statement_id` 恒为占位 ⇒ 正式态不可由 API 达成）。"""
    from app.services import delivery_service as ds

    def _truth(**kwargs):  # noqa: ANN003
        return {
            "pack_id": "FR-PK-20261104-ABCD1234",
            "created_at": "2026-11-04T12:00:00+08:00",
            "task_type": "text_to_video",
            "generator": {"system": "S", "version": "0.1.0",
                          "provider": "FR", "provider_code": "FR"},
            "generation_trace": {"session_id": "SESS-TEST-0001", "task_id": "T-1",
                                 "stage_chain": ["synopsis"], "templates": [],
                                 "model": {"name": "mock", "backend": "mock", "revision": "0"}},
            "compliance": {
                "safety_check": {"input": "passed", "output": "passed"},
                "copyright_check": {"status": "passed", "note": ""},
                "marking_check": {"explicit": "present", "implicit": "present"},
                "statement_id": "ST-001",
            },
            "_unfilled": [],  # ⚠️ 无未回填项 ⇒ 正式包
        }

    monkeypatch.setattr(ds, "build_pack_meta", _truth, raising=True)
    monkeypatch.setattr(ds, "evaluate_gate", lambda p: {
        "checked": True, "blocked": blocked,
        "blocks": ([{"code": "compliance.copyright", "message": "版权未校验"}] if blocked else []),
        "warns": [], "block_count": 1 if blocked else 0, "warn_count": 0,
        "scope": "pack", "manifest_checked": False, "manifest_note": "test",
    }, raising=True)


def test_formal_pack_blocked_raises_422_and_keeps_report(tmp_path: Path, monkeypatch) -> None:
    """★ **正式包 + BLOCK ⇒ 拒付 422**（`SW-026`「自检未通过→阻断交付并告警」）。

    ⚠️ 拒付时**不得删除已落盘目录**：自检记录须留档 ≥6 个月、可随时调取。
    """
    _patch_formal(monkeypatch, blocked=True)
    pack = _fake_pack(pack_id="FR-PK-20261104-ABCD1234", statement_id="ST-001", provider_code="FR")
    out = tmp_path / "delivery"
    try:
        pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    except AppError as e:
        assert e.code == "DELIVERY_PACK_INVALID", f"422 专用码不对：{e.code}"
        assert e.details.get("gate_blocks") == ["compliance.copyright"], e.details
        report = Path(e.details["gate_report"])
        assert report.is_file(), "拒付也必须留下自检报告（留档要求）"
        assert json.loads(report.read_text(encoding="utf-8"))["blocked"] is True
        assert Path(e.details["pack_dir"]).is_dir(), "拒付不得删除目录"
    else:
        raise AssertionError("正式包 BLOCK 必须拒付")


def test_formal_pack_passed_returns_gate_ok(tmp_path: Path, monkeypatch) -> None:
    """正式包 + 无 BLOCK ⇒ 正常交付，`gate.blocked=False`、无预演说明。"""
    _patch_formal(monkeypatch, blocked=False)
    pack = _fake_pack(pack_id="FR-PK-20261104-ABCD1234", statement_id="ST-001", provider_code="FR")
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    assert r.is_preview is False
    assert r.gate["blocked"] is False
    assert r.gate["checked"] is True
    assert (Path(r.pack_dir) / "gate_report.json").is_file()
