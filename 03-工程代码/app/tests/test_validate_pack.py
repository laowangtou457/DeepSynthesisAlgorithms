"""交付门禁 `validate_pack.py` 的 **compliance 三态式**判据测试 —— `PRO-007` 第一步＋第二步。

⚠️ **为什么单独立文件**：`prompts/tests/negtest_pack_rules.py` 测的是
   `validate_output.py`（产物侧 `R1`~`R40`）；而**交付门禁**（`validate_pack.py`）
   是**另一套判据**（`schema.pack`／`consistency.*`／`compliance.*`／`vocab.*`），
   **不在 negtest 的覆盖范围** ⇒ 本文件补上这一缺口。

⚠️ **本文件是「新判据有测试保护」的落实**（工程纪律：判据增条必须同批补样本）——
   `PRO-007` 第一步把 `compliance.*` 由否定式改为三态式、第二步又给
   `CFG-006` 增了 `not_available` 档 ⇒ **必须验证三态各自落到正确的级别**：

| 输入 | 期望级别 | 期望规则码 |
| --- | --- | --- |
| 真值（`passed`／`present`／有 `statement_id`） | 不报 | — |
| **未取得**（占位形态／`not_available`） | **WARN** | `compliance.*_pending` |
| 否定真值（`blocked`／`missing`） | **BLOCK** | `compliance.safety`／`compliance.marking` |

⚠️ **关键防线**：`not_available` 虽已是 schema **合法枚举**，但**判据仍须判 WARN**
   —— 否则预演包会被静默当成合规包放行（**谎称合规**，比 BLOCK 更危险）。
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(r"E:\深度合成算法工程材料\03-工程代码")
VALIDATE = ROOT / "delivery" / "validate_pack.py"
DEMO = ROOT / "delivery" / "examples" / "CFG-004_demo_pack.json"


def _run_pack(pack: dict, tmp_path: Path) -> tuple[int, str]:
    """跑交付门禁，返回 (退出码, 输出)。"""
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VALIDATE), str(p)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


@pytest.fixture()
def base_pack() -> dict:
    """正式包样例（`CFG-004_demo_pack.json`）—— 全部合规字段都是真值。"""
    return json.loads(DEMO.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 真值：不应报


def test_truth_values_pass_without_compliance_reports(base_pack: dict, tmp_path: Path) -> None:
    """全真值 ⇒ 不报任何 `compliance.*`（BLOCK 也不报）。"""
    code, out = _run_pack(base_pack, tmp_path)
    assert "compliance." not in out, f"不应报 compliance 项：\n{out}"
    assert "BLOCK compliance" not in out


# ---------------------------------------------------------------- 未取得：WARN


@pytest.mark.parametrize(
    "path,value,expect_code",
    [
        ("meta.compliance.safety_check.input", "not_available", "compliance.safety_pending"),
        ("meta.compliance.safety_check.output", "not_available", "compliance.safety_pending"),
        ("meta.compliance.marking_check.explicit", "not_available", "compliance.marking_pending"),
        ("meta.compliance.marking_check.implicit", "not_available", "compliance.marking_pending"),
        ("meta.compliance.statement_id", "not_available", "compliance.statement_pending"),
    ],
)
def test_not_obtained_is_warn_not_block(
    base_pack: dict, tmp_path: Path, path: str, value: str, expect_code: str
) -> None:
    """⚠️ **未取得 ⇒ WARN**（不是 BLOCK）—— 这是 `PRO-007` 第一步的核心。

    ⚠️ 两种「未取得」表达**都要覆盖**：占位形态（旧包）＋ `not_available`（新包）。
    ⚠️ **不含 `copyright_check`** —— 它的「未取得」按 `SPEC-008` §8.3 第 3 项
    「未校验 → **阻断**」是 **BLOCK**（**级别与另两项不同**，见下一个用例）。
    """
    p = base_pack
    node = p
    parts = path.split(".")
    for k in parts[:-1]:
        node = node[k]
    node[parts[-1]] = value
    code, out = _run_pack(p, tmp_path)
    # ⚠️ 实际输出格式：`[!] WARN  <code>  <消息>`（级别后**两个空格**）
    assert f"WARN  {expect_code}" in out, f"未报 WARN {expect_code}：\n{out}"
    assert f"BLOCK {expect_code}" not in out, f"★ 未取得被误报为 BLOCK：\n{out}"
    # ★ 关键防线：不得出现「未通过」的措辞（「未取得」被读成「未通过」＝ 语义污染）
    assert "未通过" not in out, f"措辞污染（「未取得」被写成「未通过」）：\n{out}"


@pytest.mark.parametrize(
    "path,value,expect_code",
    [
        ("meta.compliance.safety_check.input", "{{PLACEHOLDER}}", "compliance.safety_pending"),
        ("meta.compliance.safety_check.input", "占位", "compliance.safety_pending"),
        ("meta.compliance.statement_id", "{{STATEMENT_ID}}", "compliance.statement_pending"),
    ],
)
def test_placeholder_form_also_yields_pending_warn(
    base_pack: dict, tmp_path: Path, path: str, value: str, expect_code: str
) -> None:
    """⚠️ **占位形态（旧包）同样判「未取得」⇒ WARN**（判据层如实）。

    ⚠️ **两层结论不同，是设计使然、不是缺陷**：
    · **schema 层**：`{{PLACEHOLDER}}` **不在 enum 内**（`CFG-006` v2.2.0 的 enum 是
      `passed`／`blocked`／`not_available`）⇒ 报 `schema.pack` **BLOCK**
      （契约层：占位不是合法取值）；
    · **判据层**：`compliance.*_pending` **WARN**（语义层：「未取得」≠「未通过」）。

    ⇒ 二者**并存**：契约层拦住「占位形态进了正式包」，语义层把「未取得」与「未通过」分开。
    ⇒ 新包（服务层写 `not_available`）**只有 WARN、无 schema BLOCK** ⇒ 预演包可过门禁。
    """
    p = base_pack
    node = p
    parts = path.split(".")
    for k in parts[:-1]:
        node = node[k]
    node[parts[-1]] = value
    code, out = _run_pack(p, tmp_path)
    assert f"WARN  {expect_code}" in out, f"未报 WARN {expect_code}：\n{out}"
    # ⚠️ 语义层不得把「未取得」写成「未通过」
    assert "检测**未通过**" not in out, f"措辞污染：\n{out}"


def test_copyright_not_obtained_is_warn_after_downgrade(base_pack: dict, tmp_path: Path) -> None:
    """⚠️ **`copyright_check` 的「未取得」是 WARN**（2026-11-05 裁决降级；`ISSUE-047`）。

    ⚠️ **本用例口径已随裁决翻转**（原断言 BLOCK）：`SPEC-008` §8.3 第 3 项原文确为
    「未校验 → 阻断」，但本工程 `copyright_check` **恒为「未接入／占位」**（无版权风险源
    检测能力）⇒ 该 BLOCK 表达的是**能力缺口**、不是「检出了问题」。用 BLOCK 表达能力缺口
    会让**每个**交付包都被同一条阻断（`T-101` `shot_prompt` 段被结构性钉死在直出率 0、
    重试无用，已实证）⇒ 项目方裁决**降级为 WARN**，与 `safety_check`／`marking_check`
    的「未取得」同级。

    ⚠️ **防静默放宽的另一道闸**：真正**检出风险**（`risk`）仍是 WARN 且须「提示＋记录」
    （见 `test_copyright_risk_is_warn`）；只有当**能力真正上线**后判「未通过」才应升回
    BLOCK。降级是**明示的、有留痕的**，不是把判据掏空。
    """
    p = base_pack
    p["meta"]["compliance"]["copyright_check"]["status"] = "not_available"
    code, out = _run_pack(p, tmp_path)
    assert "WARN  compliance.copyright_pending" in out, f"未报 WARN copyright_pending：\n{out}"
    assert "BLOCK compliance.copyright" not in out, f"★ 降级后不应仍阻断：\n{out}"


def test_copyright_risk_is_warn(base_pack: dict, tmp_path: Path) -> None:
    """⚠️ `copyright_check.status = risk`（检出来了，有风险）⇒ **WARN**（提示 + 记录）。"""
    p = base_pack
    p["meta"]["compliance"]["copyright_check"]["status"] = "risk"
    code, out = _run_pack(p, tmp_path)
    assert "WARN  compliance.copyright_risk" in out, f"未报 WARN：\n{out}"
    assert "BLOCK compliance.copyright" not in out, f"★ risk 不应阻断：\n{out}"


def test_missing_compliance_keys_are_warn(base_pack: dict, tmp_path: Path) -> None:
    """**键缺失**（整个 `compliance` 块被删）⇒ 未取得。

    ⚠️ **四项同为 WARN**（2026-11-05 起 `copyright_check` 亦降级为 WARN，见
    `test_copyright_not_obtained_is_warn_after_downgrade`）：`safety_check`／
    `marking_check`／`statement_id`／`copyright_check` 缺失 ⇒ 均判「能力未接入」。
    ⚠️ 但 `compliance` 整块缺失仍由 **schema 层**报 `BLOCK schema.pack`
    （`meta.compliance` 是 required）——那是**结构缺失**，与本条分级无关。
    """
    p = base_pack
    del p["meta"]["compliance"]
    code, out = _run_pack(p, tmp_path)
    assert "WARN  compliance." in out, f"未报 WARN：\n{out}"
    assert "WARN  compliance.copyright_pending" in out, f"★ copyright 缺失未报 WARN：\n{out}"
    assert "BLOCK schema.pack" in out, f"★ compliance 整块缺失未由 schema 层阻断：\n{out}"
    assert "BLOCK compliance.safety" not in out, f"★ safety 缺失被误报为 BLOCK：\n{out}"
    assert "BLOCK compliance.marking" not in out, f"★ marking 缺失被误报为 BLOCK：\n{out}"


# ---------------------------------------------------------------- 否定真值：BLOCK


@pytest.mark.parametrize(
    "path,value,expect_code",
    [
        ("meta.compliance.safety_check.input", "blocked", "compliance.safety"),
        ("meta.compliance.safety_check.output", "blocked", "compliance.safety"),
        ("meta.compliance.marking_check.explicit", "missing", "compliance.marking"),
        ("meta.compliance.marking_check.implicit", "missing", "compliance.marking"),
    ],
)
def test_negative_truth_is_still_block(
    base_pack: dict, tmp_path: Path, path: str, value: str, expect_code: str
) -> None:
    """⚠️ **否定真值仍须 BLOCK** —— 三态化**不得**放宽阻断项。

    ⚠️ `missing`（查了、没有）与 `not_available`（没查）**语义不同** ⇒ 必须可分。
    """
    p = base_pack
    node = p
    parts = path.split(".")
    for k in parts[:-1]:
        node = node[k]
    node[parts[-1]] = value
    code, out = _run_pack(p, tmp_path)
    assert f"BLOCK {expect_code}" in out, f"未报 BLOCK {expect_code}：\n{out}"


def test_blocked_message_says_not_passed(base_pack: dict, tmp_path: Path) -> None:
    """⚠️ 阻断项的措辞须是「**检测未通过**」（而非「未取得」）—— 两者不可混。"""
    p = base_pack
    p["meta"]["compliance"]["safety_check"]["input"] = "blocked"
    code, out = _run_pack(p, tmp_path)
    assert "未通过" in out, f"措辞缺「未通过」：\n{out}"


# ---------------------------------------------------------------- 契约侧


def test_schema_accepts_not_available_enum() -> None:
    """⚠️ `CFG-006` v2.2.0：三处 enum 各含 `not_available`（契约变更已落地）。"""
    schema = json.loads(
        (ROOT / "delivery" / "schemas" / "CFG-006_shot_prompt_pack.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    comp = schema["$defs"]["meta"]["properties"]["compliance"]["properties"]
    assert "not_available" in comp["safety_check"]["properties"]["input"]["enum"]
    assert "not_available" in comp["safety_check"]["properties"]["output"]["enum"]
    assert "not_available" in comp["copyright_check"]["properties"]["status"]["enum"]
    assert "not_available" in comp["marking_check"]["properties"]["explicit"]["enum"]
    assert "not_available" in comp["marking_check"]["properties"]["implicit"]["enum"]


def test_schema_pack_id_pattern_accepts_placeholder() -> None:
    """⚠️ `CFG-006` v2.2.0：`pack_id` pattern 接受「正式形态｜占位形态」二选一。"""
    import re

    schema = json.loads(
        (ROOT / "delivery" / "schemas" / "CFG-006_shot_prompt_pack.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    pat = schema["$defs"]["meta"]["properties"]["pack_id"]["pattern"]
    rx = re.compile(pat)
    assert rx.match("FR-PK-20261103-A1B2C3D4"), "正式形态应通过"
    assert rx.match("{{PROVIDER_CODE}}-PK-20261103-A1B2C3D4"), "占位形态应通过"
    assert not rx.match("not-a-pack-id"), "非法形态应被拒"


def test_schema_version_is_2_2_0() -> None:
    """⚠️ 契约升版：`schema_version` const = 2.2.0（示例件须同步）。"""
    schema = json.loads(
        (ROOT / "delivery" / "schemas" / "CFG-006_shot_prompt_pack.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    assert schema["properties"]["schema_version"]["const"] == "2.3.0"
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    assert demo["schema_version"] == "2.3.0", "示例件 schema_version 未同步"


def test_service_layer_writes_not_available_not_placeholder() -> None:
    """⚠️ 服务层 `pack_meta` 写 `not_available`（**合法枚举**）而非占位。

    ⚠️ 写占位 ⇒ schema 判 BLOCK ⇒ 结构上「逼迫填假值」（`PRO-007` 根因 A）。
    """
    sys.path.insert(0, str(ROOT))
    from app.services.pack_meta import build_pack_meta
    from app.core.config import get_settings

    get_settings.cache_clear()
    truth = build_pack_meta(
        session_id="S", stage="shot_prompt",
        templates=[{"id": "t", "version": "1"}],
        model={"name": "m", "backend": "other", "revision": "r"},
        settings=get_settings(), artifacts={},
    )
    comp = truth["compliance"]
    assert comp["copyright_check"]["status"] == "not_available"
    assert comp["marking_check"]["explicit"] == "not_available"
    assert comp["marking_check"]["implicit"] == "not_available"
    # ⚠️ `statement_id` **不在 enum 内**（普通字符串）⇒ 仍写占位（判据侧归「未取得」⇒ WARN）
    assert "{{" in str(comp["statement_id"])


# ================================================================ 覆盖矩阵缺口 C/D/E（2026-11-04，§8.3 第 8/9/10 项）

DEMO_MANIFEST = ROOT / "delivery" / "examples" / "CFG-003_demo_manifest.json"


def _run_pack_with_manifest(pack: dict, manifest: dict, tmp_path: Path) -> tuple[int, str]:
    """包＋清单同目录（清单须名为 CFG-003_demo_manifest.json 才会被门禁拾取）。"""
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    m = tmp_path / "CFG-003_demo_manifest.json"
    m.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(VALIDATE), str(p)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


@pytest.fixture()
def base_manifest() -> dict:
    return json.loads(DEMO_MANIFEST.read_text(encoding="utf-8"))


def test_overlay_assets_complete_not_reported(base_pack: dict, base_manifest: dict, tmp_path: Path) -> None:
    """✔ 4 PNG＋规格文件齐全 ⇒ 不报 `artifact.overlay`（第 8 项正极样本）。"""
    code, out = _run_pack_with_manifest(base_pack, base_manifest, tmp_path)
    assert "artifact.overlay" not in out, f"完整素材包被误报：\n{out}"


def test_overlay_assets_missing_png_blocked(base_pack: dict, base_manifest: dict, tmp_path: Path) -> None:
    """★ 只列 3 个 PNG ⇒ BLOCK `artifact.overlay`（旧门禁对此静默放行）。"""
    m = base_manifest
    m["artifacts"]["overlay_assets"]["files"] = [
        f for f in m["artifacts"]["overlay_assets"]["files"]
        if not f.endswith("9x16.png") or f.endswith("overlay_corner_9x16.png")
    ][:3] + ["assets/AST-002_overlay_spec.json"]
    code, out = _run_pack_with_manifest(base_pack, m, tmp_path)
    assert "BLOCK artifact.overlay" in out, f"缺 PNG 未被阻断：\n{out}"


def test_overlay_assets_missing_spec_blocked(base_pack: dict, base_manifest: dict, tmp_path: Path) -> None:
    """★ 4 个 PNG 但无规格文件 ⇒ BLOCK `artifact.overlay`。"""
    m = base_manifest
    m["artifacts"]["overlay_assets"]["files"] = [
        f for f in m["artifacts"]["overlay_assets"]["files"] if f.endswith(".png")
    ]
    code, out = _run_pack_with_manifest(base_pack, m, tmp_path)
    assert "BLOCK artifact.overlay" in out, f"缺规格文件未被阻断：\n{out}"


def test_statement_placeholder_in_manifest_is_warn(base_pack: dict, base_manifest: dict, tmp_path: Path) -> None:
    """⚠️ 清单 `statement_id` 占位 ⇒ WARN `manifest.statement_pending`（缺口 D，未取得≠未通过）。"""
    m = base_manifest
    m["statement_id"] = "{{STATEMENT_ID}}"
    code, out = _run_pack_with_manifest(base_pack, m, tmp_path)
    assert "WARN  manifest.statement_pending" in out, f"未报 WARN：\n{out}"
    assert "BLOCK manifest.statement_pending" not in out


def test_secret_in_pack_blocked(base_pack: dict, tmp_path: Path) -> None:
    """★ 包内含密钥形态 ⇒ BLOCK `secret.leak`（第 10 项，旧门禁完全未查）。"""
    p = base_pack
    p["shots"][0]["prompt_zh"] += " 配置串 api_key = 'sk-abcdefgh12345678901234' 请忽略"
    code, out = _run_pack(p, tmp_path)
    assert "BLOCK secret.leak" in out, f"包内密钥未被阻断：\n{out}"


def test_url_in_pack_blocked(base_pack: dict, tmp_path: Path) -> None:
    """★ 包内含外部 URL ⇒ BLOCK `offline.dependency`（离线可用义务）。"""
    p = base_pack
    p["shots"][0]["prompt_zh"] += " 参考图见 https://cdn.example.com/ref.png"
    code, out = _run_pack(p, tmp_path)
    assert "BLOCK offline.dependency" in out, f"包内 URL 未被阻断：\n{out}"


def test_secret_in_manifest_blocked(base_pack: dict, base_manifest: dict, tmp_path: Path) -> None:
    """★ 清单 note 内含密钥形态 ⇒ BLOCK `secret.leak`。"""
    m = base_manifest
    m["provider"] = " deployment key: password=SuperSecret99 "
    code, out = _run_pack_with_manifest(base_pack, m, tmp_path)
    assert "BLOCK secret.leak" in out, f"清单内密钥未被阻断：\n{out}"


# ================================================================ T-095：服务层→门禁贯通（2026-11-04）

def test_service_truth_pack_gates_tri_state(tmp_path: Path) -> None:
    """★ **端到端贯通**：服务层真装配的包过门禁 ⇒「未取得」必须落 **WARN**，不得进 `BLOCK`。

    ⚠️ 这是 `T-095` 的核验闭环：`quality_gate._pack_report` 动态加载
    `delivery/validate_pack.py`（继承式，非手抄）⇒ 判据一致性天然成立；
    本测试把「服务层产出形态」与「门禁三态」**焊死在同一断言里**，
    任一侧回归（服务层改回占位 / 判据改回否定式）都会在此当场报警。

    模拟 `pack_delivery` 的 meta 装配：`compliance`/`pack_id`/`generator`/
    `generation_trace` 用服务层真值覆盖，模型可影响字段一字不动。
    """
    sys.path.insert(0, str(ROOT))
    from app.services.pack_meta import build_pack_meta
    from app.core.config import get_settings

    get_settings.cache_clear()
    truth = build_pack_meta(
        session_id="S", stage="shot_prompt",
        templates=[{"id": "t", "version": "1"}],
        model={"name": "m", "backend": "other", "revision": "r"},
        settings=get_settings(), artifacts={},
    )
    pack = json.loads(DEMO.read_text(encoding="utf-8"))
    meta = dict(pack.get("meta") or {})
    for key in ("pack_id", "created_at", "generator", "generation_trace", "compliance"):
        if key in truth:
            meta[key] = truth[key]
    pack["meta"] = meta
    # ⚠️ 镜像 `pack_delivery` 的标识块装配：`ProduceID`/`PropagateID` 与 `pack_id` **同源**（`R30`）。
    pack_id = str(meta["pack_id"])
    aigc = dict((pack.get("aigc_meta") or {}).get("AIGC") or {})
    aigc["ProduceID"] = pack_id
    aigc["PropagateID"] = pack_id
    pack["aigc_meta"] = {"AIGC": aigc}

    code, out = _run_pack(pack, tmp_path)
    # ① 「未取得」WARN 档（`PRO-007` 裁定）：安全判别／标识核验／声明编号 —— 服务层取不到
    #    双闸实测 ⇒ `not_available`／占位，判据归「未取得」⇒ WARN，**不得进 BLOCK**
    assert "WARN  compliance.safety_pending" in out, f"安全判别未取得未报 WARN：\n{out}"
    assert "WARN  compliance.marking_pending" in out, f"标识核验未取得未报 WARN：\n{out}"
    assert "WARN  compliance.statement_pending" in out, f"声明编号占位未报 WARN：\n{out}"
    assert "BLOCK compliance.safety" not in out and "BLOCK compliance.marking" not in out \
        and "BLOCK compliance.statement" not in out, f"未取得项被钉成 BLOCK：\n{out}"
    # ② ⚠️ `copyright` **已于 2026-11-05 由 BLOCK 降级为 WARN**（`ISSUE-047` 裁决）：
    #    理由＝该 check 恒为「未接入」，BLOCK 表达能力缺口会让每个包都被同一条阻断
    #    ⇒ 与 `safety`／`marking` 同级按 WARN 处置，**留痕但不阻断**。
    #    ⚠️ 此处断言**方向已翻转**：若有人把版权校验私自改回 BLOCK（未经裁决），
    #    本断言当场报警 —— 降级是裁决结果，回滚也必须过裁决。
    assert "WARN  compliance.copyright_pending" in out, f"版权未校验未报 WARN：\n{out}"
    assert "BLOCK compliance.copyright" not in out, f"★ 版权威仍未降级：\n{out}"
    # ③ 降级后服务层真装配包应**零 BLOCK**（无任何设计内阻断）
    other_blocks = [ln for ln in out.splitlines() if ln.strip().startswith("[X] BLOCK")]
    assert not other_blocks, f"服务层真装配包出现非预期 BLOCK：\n{other_blocks}"
    assert code == 0, "版权降级为 WARN 后，服务层真装配包应可交付（退出码 0）"


# ---------------------------------------------------------------- `乙`（2026-11-07 裁决）


def test_unit_camera_dup_is_warn_after_demotion(base_pack: dict, tmp_path: Path) -> None:
    """承继层 `unit.camera_dup` 由 BLOCK 降级 **WARN**（裁决乙：camera 一字不得改，
    该约束是分镜层生成期约束；承继层当 BLOCK 会制造不可满足约束对）。"""
    pack = copy.deepcopy(base_pack)
    shots = {s["shot_id"]: s for s in pack["shots"]}
    unit = pack["units"][0]
    sids = unit["shot_ids"][:2]
    # 人为制造单元内运镜重复（模拟承继自分镜层的上游缺陷）
    shots[sids[1]]["camera"]["move"] = shots[sids[0]]["camera"]["move"]
    code, out = _run_pack(pack, tmp_path)
    assert "unit.camera_dup" in out, f"应报 unit.camera_dup：\n{out}"
    assert "BLOCK unit.camera_dup" not in out, f"降级后不得再是 BLOCK：\n{out}"


# ---------------------------------------------------------------- `乙`（2026-11-07 裁决）


def test_unit_camera_dup_is_warn_after_demotion(base_pack: dict, tmp_path: Path) -> None:
    """承继层 `unit.camera_dup` 由 BLOCK 降级 **WARN**（裁决乙：camera 一字不得改，
    该约束是分镜层生成期约束；承继层当 BLOCK 会制造不可满足约束对）。"""
    pack = copy.deepcopy(base_pack)
    shots = {s["shot_id"]: s for s in pack["shots"]}
    unit = pack["units"][0]
    sids = unit["shot_ids"][:2]
    # 人为制造单元内运镜重复（模拟承继自分镜层的上游缺陷）
    shots[sids[1]]["camera"]["move"] = shots[sids[0]]["camera"]["move"]
    code, out = _run_pack(pack, tmp_path)
    assert "unit.camera_dup" in out, f"应报 unit.camera_dup：\n{out}"
    assert "BLOCK unit.camera_dup" not in out, f"降级后不得再是 BLOCK：\n{out}"
