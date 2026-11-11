"""`SW-I04` 交付包端点测试 —— `T-006`；清单契约对齐 —— `ISSUE-057` 候选①。

⚠️ 纪律：

- **不依赖真实会话产物**——用 `tmp_path` 造确定性交付包（与 `test_safety.py` 同纪律）；
- **占位如实**——`pack_id`／`statement_id` 是占位时，响应**必须**标 `is_preview=true`
  且 `unfilled` 非空（`PRO-007` 根因 A／B 未决前的诚实边界）；
- **不臆造合规结论**——`compliance.*` 一律取服务层真值，端点**不二次生成**；
- **清单不得编造 `pass`**——`self_check` 十八项由实际判定填充，无证据即 `warn`／`fail`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError
from app.services.delivery_service import (
    GATE_REPORT_NAME,
    PACK_TOP_KEYS,
    PREVIEW_NOTE,
    SPEC_VERSION,
    _MANIFEST_SIDE_CODES,
    _SELF_CHECK_SPEC,
    build_manifest,
    build_self_check,
    pack_delivery,
)

#: `03-工程代码/`（测试文件位于 `03-工程代码/app/tests/`）
CODE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = CODE_ROOT.parent


def _fake_pack(*, pack_id: str = "{{PROVIDER_CODE}}-PK-20261103-ABCD1234",
               statement_id: str = "{{STATEMENT_ID}}",
               provider_code: str = "{{PROVIDER_CODE}}") -> dict:
    """构造一个**形态合法**的交付包（顶层键齐、含占位）。"""
    return {
        "schema_version": "2.3.0",
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
                "templates": [{"id": "shot_prompt_v1", "version": "2.3.1"}],
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
    """交付四件套齐备：提示词集 ＋ AIGC 元数据块 ＋ 标识素材 ＋ 合规声明（＋清单）。"""
    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    d = Path(r.pack_dir)
    assert (d / "pack.json").is_file()
    assert (d / "aigc_meta.json").is_file(), "AIGC 元数据块须单独落盘（§8.3 第 6 项）"
    assert (d / "manifest.json").is_file()
    assert (d / "AST-004_compliance_statement.md").is_file()
    assert (d / "qa" / "audit_report.txt").is_file(), "质量门报告须随包（§8.3 第 13 项）"
    for name in ("pack.json", "aigc_meta.json", "manifest.json",
                 "AST-004_compliance_statement.md", "qa/audit_report.txt"):
        assert name in r.files, f"{name} 未登记进交付文件列表"
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


def test_pack_writes_exports_with_explicit_marks(tmp_path: Path) -> None:
    """`SW-022` 接线（2026-11-10）：交付包里**必须有 `exports/`**，且清单 `exports[]` 非空。

    ⚠️ 此前该列表**恒为空** ⇒ 清单判据 `export.mark` 从未执行、自检第 7 项退化成
    「元数据字段填了什么」。本用例锁的是「导出物真的落盘且带标识」。
    """
    pack = _fake_pack()
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(tmp_path / "delivery"), settings=Settings())
    d = Path(r.pack_dir)
    assert (d / "exports").is_dir(), "未产出 exports/ 目录（SW-022 未接线）"
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert mf.get("exports"), "清单 exports[] 为空 ⇒ export.mark 判据空跑"
    for e in mf["exports"]:
        assert e["explicit_mark"] is True, e
    row = next(c for c in mf["self_check"] if c["no"] == 7)
    assert row["result"] == "pass" and "份导出物" in row["detail"], row


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


# ================================================================ 版权校验接线（SW-015）


#: 一段长度达标的示例创作内容（`copyright_service.MIN_TEXT_LEN` 为 20）
_LONG_PROMPT = (
    "雨夜的街道上，少年撑着黑伞独自行走，路灯把影子拉得很长，远处传来电车的声音，"
    "潮湿的空气里混着梧桐叶与铁锈的气味，整座城市像一张被浸湿的旧照片。"
)


def _pack_with_long_prompt(**kw: object) -> dict:
    """`_fake_pack` 的默认 `prompt_zh` 只有 5 字（`废弃采矿站`）⇒ 版权比对会跳过它。
    本组测试需要**可比对的长文本**，故就地加长。"""
    p = _fake_pack(**kw)  # type: ignore[arg-type]
    p["shots"][0]["prompt_zh"] = _LONG_PROMPT
    return p


def _saved_pack(pack_dir: str) -> dict:
    return json.loads((Path(pack_dir) / "pack.json").read_text(encoding="utf-8"))


def test_copyright_check_corpus_missing_is_not_available(tmp_path: Path) -> None:
    """★ 作品库未建立 ⇒ `copyright_check=not_available`，且**归因必须是真实原因**。

    ⚠️ 本条是接线前的**实质缺陷**：该字段被硬编码为
    `{"status":"not_available","note":"版权校验未接入（T-008）"}`，
    而 `T-008` 是**二期人工审核台**、与本条无关；真实卡点是
    「可比对作品库未建立」（`REQ-005` `SW-015` 原文已登记该前置）。
    """
    r = pack_delivery(
        svc=_svc_with(_pack_with_long_prompt(pack_id="FR-PK-20261111-A1B2C3D4")),
        session_id="S",
        out_dir=str(tmp_path / "delivery"),
        settings=Settings(),  # 默认 copyright_corpus_root="" ⇒ 库未建立
    )
    cp = _saved_pack(r.pack_dir)["meta"]["compliance"]["copyright_check"]
    assert cp["status"] == "not_available", "库未建立不得折算为 passed（没检 ≠ 没风险）"
    assert "T-008" not in cp["note"], f"旧归因 T-008 必须已订正：{cp['note']}"
    assert "作品库" in cp["note"], f"须给出真实归因：{cp['note']}"


def test_copyright_declaration_written_and_listed(tmp_path: Path) -> None:
    """`SW-015` ②：改编来源声明须**可留存、可导出**。

    ⚠️ **「可导出」靠两件事共同保证**，缺一不可：

    1. 声明件**独立落盘**在交付包目录（物理可导出）；
    2. 合规声明（`AST-004`）**显式引用**其文件名（可发现）。

    第 2 条是必须的：清单（`CFG-005`）的 `artifacts` 是**固定五项**且
    `additionalProperties: false` ⇒ 声明件**没有**清单登记位，若再不引用，
    下游只能靠翻目录才能发现它。
    """
    r = pack_delivery(
        svc=_svc_with(_pack_with_long_prompt(pack_id="FR-PK-20261111-A1B2C3D4")),
        session_id="S",
        out_dir=str(tmp_path / "delivery"),
        settings=Settings(),
    )
    decls = sorted(Path(r.pack_dir).glob("copyright_declaration_*.md"))
    assert len(decls) == 1, "声明件须恰好一份（同包重复打包不得散落多份）"
    text = decls[0].read_text(encoding="utf-8")
    assert "未校验" in text, "库未建立时声明件必须明写「未校验」"
    assert "未提交改编来源声明" in text, "缺失声明须如实标注，绝不代填「原创」"
    assert "风险由提交方自负" in text

    stmt = (Path(r.pack_dir) / "AST-004_compliance_statement.md").read_text(encoding="utf-8")
    assert decls[0].name in stmt, "合规声明须引用声明件文件名，否则下游不可发现"


def test_copyright_risk_does_not_block_delivery(tmp_path: Path) -> None:
    """`SW-015` ③：检出风险**不阻断交付**，但须在声明中逐条列明。

    作品库投放到位后（配置 `copyright_corpus_root`）**无需改码**即自动启用比对 ——
    本条同时验证该配置路径。
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "某受保护作品.txt").write_text(_LONG_PROMPT, encoding="utf-8")

    r = pack_delivery(
        svc=_svc_with(_pack_with_long_prompt(pack_id="FR-PK-20261111-A1B2C3D4")),
        session_id="S",
        out_dir=str(tmp_path / "delivery"),
        settings=Settings(copyright_corpus_root=str(corpus)),
    )
    cp = _saved_pack(r.pack_dir)["meta"]["compliance"]["copyright_check"]
    assert cp["status"] == "risk", f"与作品库正文雷同须判 risk：{cp}"

    manifest = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))
    item3 = next(i for i in manifest["self_check"] if i["no"] == 3)
    assert item3["result"] != "fail", f"SW-015 ③ 明确不阻断交付，但自检判了 fail：{item3}"

    decl = sorted(Path(r.pack_dir).glob("copyright_declaration_*.md"))[0].read_text(encoding="utf-8")
    assert "检出项（逐条列明）" in decl
    assert "某受保护作品" in decl, "命中项须逐条列明来源作品"
    assert "核对改编授权" in decl


def test_copyright_similarity_threshold_is_configurable(tmp_path: Path) -> None:
    """阈值可配置（`REQ-005` `SW-015`：默认 0.5）——设 1.01 后同一雷同内容不再判 risk。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "某受保护作品.txt").write_text(_LONG_PROMPT, encoding="utf-8")
    r = pack_delivery(
        svc=_svc_with(_pack_with_long_prompt(pack_id="FR-PK-20261111-A1B2C3D4")),
        session_id="S",
        out_dir=str(tmp_path / "delivery"),
        settings=Settings(copyright_corpus_root=str(corpus), copyright_similarity_threshold=1.01),
    )
    cp = _saved_pack(r.pack_dir)["meta"]["compliance"]["copyright_check"]
    assert cp["status"] == "passed", f"阈值调高后不应再判 risk：{cp}"


def test_pack_id_is_identical_across_all_artifacts(tmp_path: Path) -> None:
    """★ **同一次交付只能有一个编号**（`SW-013` ＋ `R30`，2026-11-11 实测缺陷的回归锁）。

    ⚠️ **本条锁的是已发生的真实缺陷**：`apply_service_truth` 的 `META_SERVICE_KEYS`
    含 `pack_id`，它把「沿用既有编号」的结果**覆盖回**服务层当次新生成的随机短码，
    而目录名／清单编号用的是沿用值 ⇒ 同一交付里出现了**两个编号**：

    | 位置 | 缺陷时的取值 |
    | --- | --- |
    | 交付目录名 ／ `DeliveryResult.pack_id` ／ 清单 `pack_id` | `FR-PK-20261111-A1B2C3D4`（沿用值） |
    | `pack.json` 的 `meta.pack_id` ／ `aigc_meta.AIGC.ProduceID` | `{{PROVIDER_CODE}}-PK-20261111-<随机>`（新生成） |

    `SW-013`（内容编号不可被删除篡改隐匿）与 `R30`（`ProduceID` 与 `pack_id` 同源）
    都要求一致 —— 审核方只要比对目录名与 `ProduceID` 就能发现矛盾。
    **本测试跨五处比对**，任何一处漂移都会失败。
    """
    r = pack_delivery(
        svc=_svc_with(_pack_with_long_prompt(pack_id="FR-PK-20261111-A1B2C3D4")),
        session_id="S",
        out_dir=str(tmp_path / "delivery"),
        settings=Settings(),
    )
    saved = _saved_pack(r.pack_dir)
    manifest = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))
    produce_id = (saved.get("aigc_meta") or {}).get("AIGC", {}).get("ProduceID")
    prop_id = (saved.get("aigc_meta") or {}).get("AIGC", {}).get("PropagateID")

    actual = {
        "目录名": Path(r.pack_dir).name,
        "DeliveryResult.pack_id": r.pack_id,
        "清单 pack_id": manifest["pack_id"],
        "pack.json meta.pack_id": saved["meta"]["pack_id"],
        "隐式标识 ProduceID": produce_id,
        "隐式标识 PropagateID": prop_id,
    }
    assert len(set(actual.values())) == 1, f"编号不同源：{actual}"
    assert actual["目录名"] == "FR-PK-20261111-A1B2C3D4", "沿用既有编号失败"


def test_pack_id_has_single_writer_and_guard_fires(tmp_path: Path, monkeypatch) -> None:
    """★ **编号写入权单点**（`ISSUE-074` 结构性收敛的锁）。

    ⚠️ 上一版修法是「`apply_service_truth` 覆盖之后再纠偏」——**能修结果、防不住复发**：
    只要还有第二个写入者，它就能再赢一次。本版结构解是「编号在装配 `truth` 之前
    一次性确定，`truth` 是唯一载体，之后只写一次」，并用**同源不变量校验**兜底。

    本条即验证兜底**有牙齿**：人为在 `apply_service_truth` 之后再改一次 `meta.pack_id`
    （模拟将来有人重新引入第二写入者）⇒ `pack_delivery` 必须 **fail-closed 抛错**，
    而不是把矛盾编号写进交付包。
    """
    import pytest

    import app.services.delivery_service as ds
    from app.services.pack_meta import apply_service_truth as real_apply

    def _second_writer(doc, truth, **kwargs):  # noqa: ANN001, ANN003
        out = real_apply(doc, truth, **kwargs)
        if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
            doc["meta"]["pack_id"] = "FR-PK-20261111-BADBAD00"  # ← 第二个写入者
        return out

    monkeypatch.setattr(ds, "apply_service_truth", _second_writer)
    with pytest.raises(AppError) as ei:
        pack_delivery(
            svc=_svc_with(_fake_pack(pack_id="FR-PK-20261111-A1B2C3D4")),
            session_id="S",
            out_dir=str(tmp_path / "delivery"),
            settings=Settings(),
        )
    assert "SW-013" in str(ei.value) or "编号" in str(ei.value)


def test_build_pack_meta_honours_explicit_pack_id() -> None:
    """`build_pack_meta(pack_id=…)`：**显式编号即最终编号**（`truth` 是编号唯一载体）。

    ⚠️ 这是单点写入的前提：沿用值必须先固化进 `truth`，下游才不需要第二个写入者。
    """
    from app.services.pack_meta import build_pack_meta

    truth = build_pack_meta(
        session_id="S", stage="shot_prompt", templates=[],
        model={"name": "m", "backend": "vllm", "revision": "r"},
        settings=Settings(), pack_id="FR-PK-20261111-A1B2C3D4",
    )
    assert truth["pack_id"] == "FR-PK-20261111-A1B2C3D4"
    # 不传 ⇒ 服务层生成（形态仍须合规）
    gen = build_pack_meta(
        session_id="S", stage="shot_prompt", templates=[],
        model={"name": "m", "backend": "vllm", "revision": "r"}, settings=Settings(),
    )
    assert "-PK-" in gen["pack_id"] and gen["pack_id"] != truth["pack_id"]


# ================================================================ 清单契约对齐（ISSUE-057 候选①）


def test_manifest_matches_cfg005_schema(tmp_path: Path) -> None:
    """★ **清单必须通过 `CFG-005` 契约**（旧实现是 `manifest_version` 1.0.0 的自拟形态）。

    ⚠️ 这是 `ISSUE-057` 的**根判定**：直接拿 JSON Schema 校验产出的清单，
    结构性字段（`manifest_version`／`artifacts` 四件套＋质量门报告／`self_check` 18 项／
    `human_review`／`retention`／`additionalProperties:false`）必须全部到位。
    """
    import jsonschema

    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    mf = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))

    schema = json.loads(
        (CODE_ROOT / "delivery" / "schemas" / "CFG-005_manifest.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(mf)  # 不合契约即抛

    assert mf["manifest_version"] == "1.1.0"
    assert mf["spec_version"] == SPEC_VERSION
    assert set(mf["artifacts"]) >= {
        "shot_prompt_pack", "aigc_meta", "overlay_assets", "compliance_statement"
    }
    assert mf["artifacts"]["aigc_meta"]["present"] is True
    assert mf["artifacts"]["overlay_assets"]["present"] is True
    assert mf["artifacts"]["quality_gate_report"]["present"] is True
    assert mf["retention"]["months"] >= 6
    # ⚠️ 契约 `additionalProperties:false` ⇒ 旧字段（counts/is_preview/files）**必须消失**
    for gone in ("counts", "is_preview", "files", "compliance", "service_truth"):
        assert gone not in mf, f"旧自拟字段 {gone} 仍在清单里（契约不允许）"


def test_self_check_has_18_items_and_never_fabricates_pass(tmp_path: Path) -> None:
    """★ **自检 18 项齐备**，且「拿不到证据」的项**不得**标 `pass`。

    本用例的包是 1 镜单镜单元 ⇒ 多项判据必然不合格；
    第 11 项（系统级去标识入口）与第 18 项（无人工核对台账）必须**如实**非 `pass`。
    """
    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    mf = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))
    sc = {row["no"]: row for row in mf["self_check"]}

    assert sorted(sc) == list(range(1, 19)), "自检必须恰好 18 项"
    # 第 11 项：交付包层面不可机检 ⇒ warn（绝不 pass）
    assert sc[11]["result"] == "warn"
    assert "不可机检" in sc[11]["detail"]
    # 第 18 项：无人核对台账 ⇒ fail（§8.3「无记录视为未做」）
    assert sc[18]["result"] == "fail"
    # 第 3 项：版权未接入（占位）⇒ **2026-11-05 裁决降级 WARN** 档 ⇒ warn（不再是 fail）
    #   ⚠️ 语义不得漂移：「warn」表示**如实呈现「未校验」**，绝不等于「版权已校验通过」。
    assert sc[3]["result"] == "warn"
    assert "copyright" in sc[3]["detail"], "降级后仍须在 detail 里留原始判据码（可回溯）"
    # 第 9 项：声明编号占位 ⇒ warn（未取得），且 detail 说明 8 项要素无机检
    assert sc[9]["result"] == "warn"
    # 每一项都必须带 detail（可回溯到原始判据码或原因）
    assert all(row.get("detail") for row in mf["self_check"])


def test_self_check_map_covers_all_validator_codes() -> None:
    """⚠️ **互锁**：`validate_pack.py` 的每个判据码都必须被 18 项映射覆盖或显式豁免。

    新增判据码却忘了挂到自检项 ⇒ 清单会「18 项全绿但门禁 BLOCK」，
    属**静默漏检**（`PRO-012` 变更三件套：判据增量必须同批更新映射与测试）。
    """
    src = (CODE_ROOT / "delivery" / "validate_pack.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'rep\.add\([A-Z]+, "([a-z0-9_.]+)"', src))
    # `check_schema` 用 f-string 拼码，正则抓不到 ⇒ 手工补（包侧/清单侧各一）
    codes |= {"schema.pack", "schema.manifest"}

    covered = {c for spec in _SELF_CHECK_SPEC for c in spec.get("codes", ())}
    uncovered = codes - covered - set(_MANIFEST_SIDE_CODES)
    assert not uncovered, (
        "以下判据码未挂到自检 18 项（新判据须同批更新 _SELF_CHECK_SPEC）："
        f"{sorted(uncovered)}"
    )


def test_spec_version_matches_norm_document() -> None:
    """⚠️ **互锁**：清单 `spec_version` 与 `SPEC-008` 正文版本必须一致。

    ⚠️ 常量手抄是本工程的高发缺陷族（`ISSUE-019` 活跃引用陈旧／`ISSUE-021` 表头滞后）
    ⇒ 用测试把「清单声明的依据版本」焊死在规范正文上。
    ⚠️ 文件名 `-v2.3` 与正文 `v2.4` 本就不同步（历史遗留，改名属 C 类变更）⇒
    **以正文版本行为准**，不以文件名为准。
    """
    norms = sorted((PROJECT_ROOT / "01-架构设计").glob("SPEC-008_*.md"))
    assert norms, "找不到 SPEC-008 规范正文"
    head = norms[0].read_text(encoding="utf-8")[:4000]
    m = re.search(r"\|\s*版本\s*\|\s*\*\*V([\d.]+)\*\*\s*\|", head)
    assert m, "SPEC-008 未找到版本行"
    assert SPEC_VERSION.endswith(f"v{m.group(1)}"), (
        f"交付清单 spec_version={SPEC_VERSION!r} 与规范正文 V{m.group(1)} 不一致"
    )


def test_self_check_map_is_orderly() -> None:
    """映射表本身的完整性：18 项齐全、编号不乱、`from` 取值合法。"""
    froms = {"pack", "assets", "statement", "adapters", "human_review", "out_of_scope"}
    assert [s["no"] for s in _SELF_CHECK_SPEC] == list(range(1, 19))
    for spec in _SELF_CHECK_SPEC:
        assert spec["from"] in froms, f"第 {spec['no']} 项 from 非法：{spec['from']}"
        if spec["from"] == "pack":
            assert spec.get("codes"), f"第 {spec['no']} 项声明 from=pack 却无 codes"


def test_build_self_check_marks_empty_subject_as_warn() -> None:
    """⚠️ **判定对象为空 ⇒ 没检 ⇒ warn**（不得因为「没报错」就标 pass）。

    这是最容易造假的一处：门禁对空 `shots` 什么都不报，若按「无条目=通过」判，
    就会得出「质量门全通过」的假结论。
    """
    rows = build_self_check(
        [], block_level="BLOCK",
        assets=["assets/overlay_intro_16x9.png", "assets/AST-002_overlay_spec.json"],
        statement_id="{{STATEMENT_ID}}", statement_file="ST.md",
        adapters=[], human_review=[], has_shots=False, has_units=False,
    )
    idx = {r["no"]: r for r in rows}
    assert idx[13]["result"] == "warn" and "未检" in idx[13]["detail"]
    assert idx[16]["result"] == "warn"
    # ⚠️ 第 17 项的判据是**逐镜**遍历 ⇒ 镜头为空时也没检（真机实测抓到过这一处假 pass）
    assert idx[17]["result"] == "warn"
    # 第 8 项只有 1 个 PNG ⇒ 素材包不完整 ⇒ fail（不是 warn，是真不合格）
    assert idx[8]["result"] == "fail"
    assert idx[4]["result"] == "pass"  # Schema 校验必然会跑，无条目即无问题


# ================================================================ ISSUE-055 ①′ 分档门禁


def test_preview_pack_reports_gate_but_still_delivers(tmp_path: Path) -> None:
    """★ **预演包**：门禁照跑、结论如实呈现，但**不拒付**（占位是常态，拒付＝端点长期不可用）。

    `ISSUE-057` 候选① 起清单侧一并校验 ⇒ `scope=pack+manifest`、`manifest_checked=True`。
    """
    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    d = Path(r.pack_dir)

    assert r.is_preview is True
    assert r.gate["checked"] is True, "预演包也必须跑门禁（只呈现不拒付，≠ 不检查）"
    assert r.gate["blocked"] is True
    assert r.gate["scope"] == "pack+manifest", "清单侧须纳入门禁"
    assert r.gate["manifest_checked"] is True
    codes = [b["code"] for b in r.gate["blocks"]]
    # ⚠️ **2026-11-05 裁决**：`compliance.copyright` 降级为 WARN ⇒ **不得**再出现在 blocks 里，
    #    但必须出现在 warnings 里（「不拦」≠「不报」——留痕义务未取消）。
    assert "compliance.copyright" not in codes, f"版权阻断已降级，不应再 BLOCK：{codes}"
    assert "human_review.missing" in codes, f"无人工核对记录未报 BLOCK：{codes}"
    warns = [w["code"] for w in r.gate.get("warns", [])]
    assert "compliance.copyright_pending" in warns, (
        f"版权降级后必须在 warns 留痕（`compliance.copyright_pending`）：{warns}"
    )

    report = d / GATE_REPORT_NAME
    assert report.is_file(), "自检报告必须随包留档"
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["blocked"] is True and saved["is_preview"] is True
    assert saved["manifest_checked"] is True

    # ⚠️ 裁决③：报告**不进**交付清单 `artifacts`（审计附随件，不是交付载荷）
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    flat = [f for art in mf["artifacts"].values() for f in art.get("files", [])]
    assert GATE_REPORT_NAME not in flat
    assert GATE_REPORT_NAME not in (r.files or [])


def _patch_formal(monkeypatch, *, blocked: bool, human_review: list | None = None):
    """把「正式包 ＋ 指定门禁结论」注入（当前 `statement_id` 恒为占位 ⇒ 正式态不可由 API 达成）。"""
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
    if human_review is not None:
        monkeypatch.setattr(ds, "_load_human_review", lambda s, p: human_review, raising=True)

    # ⚠️ 新签名含 `manifest_path` / `pack_items` 关键字 ⇒ lambda 必须吸收
    monkeypatch.setattr(ds, "evaluate_gate", lambda p, m=None, **kw: {
        "checked": True, "blocked": blocked,
        "blocks": ([{"code": "compliance.copyright", "message": "版权未校验"}] if blocked else []),
        "warns": [], "block_count": 1 if blocked else 0, "warn_count": 0,
        "scope": "pack+manifest", "manifest_checked": True, "manifest_note": "test",
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


def test_human_review_ledger_is_the_only_source(tmp_path: Path, monkeypatch) -> None:
    """★ **人工核对记录只能来自台账**（§8.3 第 18 项），模型产物里的不算数。

    ⚠️ 若从 `pack["human_review"]` 读，等于「让模型自己证明自己被人工核对过」＝假合规。
    """
    from app.services import delivery_service as ds

    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({
        "records": [
            {"pack_id": "FR-PK-20261104-ABCD1234", "no": 18,
             "item": "角色一致性 / 跨镜连续性", "result": "pass",
             "checked_at": "2026-11-04T10:00:00+08:00", "operator": "张三"},
            {"pack_id": "OTHER-PK-20261104-00000000", "no": 18,
             "item": "别的包", "result": "fail",
             "checked_at": "2026-11-04T10:00:00+08:00", "operator": "李四"},
        ]
    }, ensure_ascii=False), encoding="utf-8")

    got = ds._load_human_review(Settings(_env_file=None, human_review_ledger=str(ledger)),
                                "FR-PK-20261104-ABCD1234")
    assert len(got) == 1 and got[0]["operator"] == "张三"
    # 未配置 ⇒ 空（不编造）
    assert ds._load_human_review(Settings(_env_file=None, human_review_ledger=""), "X") == []

    # 有台账 ⇒ 自检第 18 项转 pass
    _patch_formal(monkeypatch, blocked=False, human_review=got)
    pack = _fake_pack(pack_id="FR-PK-20261104-ABCD1234", statement_id="ST-001", provider_code="FR")
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(tmp_path / "delivery"), settings=Settings())
    mf = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert mf["human_review"], "台账记录须进清单"
    assert {row["no"]: row for row in mf["self_check"]}[18]["result"] == "pass"


def test_human_review_missing_blocks_and_fail_is_honest(tmp_path: Path) -> None:
    """★ 人工核对台账**缺失即阻断**、**记 fail 即拦住**——两档都不许折算成通过。

    ⚠️ 与 `test_human_review_ledger_is_the_only_source` 互补：那条锁「记录能进清单」，
    本条锁「**没有**或**不合格**的记录时门禁真的拦住」——后者才是防「静默放行」的那一半。
    """
    pack = {"pack_id": "FR-PK-20261111-7C4E9A21", "statement_id": "ST-001", "provider_code": "FR"}

    def _pack_run(tag: str, ledger_path: str):
        r = pack_delivery(
            svc=_svc_with(_fake_pack(**pack)),
            session_id="SESS-TEST-0002",
            out_dir=str(tmp_path / tag),
            settings=Settings(_env_file=None, human_review_ledger=ledger_path),
        )
        mf = json.loads((Path(r.pack_dir) / "manifest.json").read_text(encoding="utf-8"))
        codes = [b.get("code") for b in (r.gate.get("blocks") or [])]
        return r, mf, codes, {row["no"]: row for row in mf["self_check"]}[18]["result"]

    # ① 未配台账 ⇒ 视为「未做人工核对」
    _r1, mf1, codes1, res1 = _pack_run("none", "")
    assert mf1["human_review"] == [], "无台账时清单不得出现任何核对记录"
    assert res1 == "fail", "无台账 ⇒ 第 18 项必须 fail（「没检」不等于「通过」）"
    assert "human_review.missing" in codes1, "无台账 ⇒ 必须如实阻断，不得静默放行"

    # ② 有台账但 result=fail ⇒ 仍 fail（不能因为「有记录」就算过）
    bad = tmp_path / "ledger_fail.json"
    bad.write_text(json.dumps({"records": [{
        "pack_id": pack["pack_id"], "no": 18, "item": "角色一致性 / 跨镜连续性人工核对",
        "result": "fail", "checked_at": "2026-11-11T09:25:00+08:00",
        "operator": "核对人", "detail": "第 7 镜服装与第 3 镜不一致"}]},
        ensure_ascii=False), encoding="utf-8")
    _r2, mf2, _c2, res2 = _pack_run("fail", str(bad))
    assert len(mf2["human_review"]) == 1, "台账记录须如实进清单（含 fail）"
    assert res2 == "fail", "核对未通过 ⇒ 第 18 项必须 fail"

    # ③ 有台账且 pass ⇒ 第 18 项转 pass，且该阻断码消失
    good = tmp_path / "ledger_pass.json"
    good.write_text(json.dumps({"records": [{
        "pack_id": pack["pack_id"], "no": 18, "item": "角色一致性 / 跨镜连续性人工核对",
        "result": "pass", "checked_at": "2026-11-11T09:20:00+08:00",
        "operator": "核对人", "detail": "15 镜逐镜核对，未发现跨镜断裂"}]},
        ensure_ascii=False), encoding="utf-8")
    _r3, _mf3, codes3, res3 = _pack_run("pass", str(good))
    assert res3 == "pass"
    assert "human_review.missing" not in codes3, "台账齐备后该阻断码必须消失（否则填了也没用）"


def test_audit_report_reflects_real_gate_not_boilerplate(tmp_path: Path) -> None:
    """★ 质量门报告 `qa/audit_report.txt` 必须是**真实判定**的投影，不能是模板套话。

    ⚠️ 无镜头时须写「未执行」，**不得**写「通过」——报告缺失比谎称通过安全。
    """
    from app.services.delivery_service import render_audit_report

    empty = render_audit_report([], pack_id="X", block_level="BLOCK")
    assert "未执行" in empty and "全部通过" not in empty

    pack = _fake_pack()
    out = tmp_path / "delivery"
    r = pack_delivery(svc=_svc_with(pack), session_id="SESS-TEST-0001",
                      out_dir=str(out), settings=Settings())
    text = (Path(r.pack_dir) / "qa" / "audit_report.txt").read_text(encoding="utf-8")
    assert r.pack_id in text
    assert "未执行" in text or "未通过" in text or "全部通过" in text
    # 报告内容须与门禁里的 gate.* 条目一致（同源）
    gate_msgs = [w["message"] for w in r.gate["warns"] if w["code"].startswith("gate.")]
    gate_msgs += [b["message"] for b in r.gate["blocks"] if b["code"].startswith("gate.")]
    for msg in gate_msgs:
        assert msg in text, f"质量门报告缺真实条目：{msg}"
