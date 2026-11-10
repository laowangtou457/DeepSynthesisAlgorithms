"""语义闸接线单测（`T-108` ③ ＋ `ISSUE-070` 生产侧修复，`DEV-20261110-013`）。

覆盖：
1. `parse_guard_output`：官方两侧行格式（输入侧无 Refusal 行）＋容错；
2. `SafetyService` 语义闸叠加：Unsafe 升级 block / Controversial 升级 flag /
   故障 fail-open 回落词闸；
3. 拒答通道：`looks_like_refusal` ＋ `is_refusal=True` 的 notice 放行与语义闸兜底；
4. `VllmBackend._merge_system`：边界提示词合并（无网络）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.repositories.lexicon import load_lexicon
from app.services.safety_service import SafetyService
from app.services.semantic_gate import SemanticVerdict, parse_guard_output


# ---------------------------------------------------------------- 测试替身
class _FakeGate:
    """可控语义闸替身：按预设结果返回，记录调用。"""

    def __init__(self, result: SemanticVerdict | Exception) -> None:
        self._result = result
        self.calls: list[str] = []

    def moderate_prompt(self, text: str) -> SemanticVerdict:
        self.calls.append(f"prompt:{text[:20]}")
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def moderate_response(self, prompt: str, response: str) -> SemanticVerdict:
        self.calls.append(f"response:{response[:20]}")
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _make_lexicon_dir(tmp: Path) -> Path:
    """构造临时词库目录（与 test_safety.py 同款最小夹具：词条<TAB>等级）。"""
    table = tmp / "词表"
    table.mkdir(parents=True, exist_ok=True)
    p = table / "A1-07-测试类.txt"
    body = ["# 测试词表", "# 类别：A1-07", ""] + ["违禁词\tblock", ""]
    p.write_text("\n".join(body), encoding="utf-8")
    cat = {
        "id": "A1-07",
        "group": "A.1",
        "name": "测试类A1-07",
        "quota": 10,
        "controlled": False,
        "file": p.name,
    }
    (tmp / "lexicon_manifest.json").write_text(
        json.dumps({"standard": "GB/T 45654—2025", "categories": [cat]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp


@pytest.fixture()
def svc(tmp_path):
    def _make(semantic=None) -> SafetyService:
        return SafetyService(load_lexicon(_make_lexicon_dir(tmp_path)), semantic=semantic)

    return _make


# ---------------------------------------------------------------- parse
def test_parse_prompt_side_no_refusal_line():
    v = parse_guard_output("Safety: Unsafe | Categories: Violent")
    assert v.ok and v.unsafe and v.label == "Unsafe"
    assert v.categories == ("Violent",)
    assert v.refusal is None  # ⚠️ 输入侧官方格式无 Refusal 行


def test_parse_response_side_full_format():
    v = parse_guard_output("Safety: Safe\nCategories: None\nRefusal: Yes")
    assert v.ok and not v.unsafe and v.refusal == "Yes"
    assert v.categories == ()


def test_parse_garbage_returns_not_ok():
    v = parse_guard_output("我无法处理该请求。")
    assert not v.ok and v.label == "unknown"


# ---------------------------------------------------------------- 语义闸叠加
def test_semantic_unsafe_escalates_block(svc):
    gate = _FakeGate(SemanticVerdict("Unsafe", ("Unethical Acts",), None, "x", True))
    s = svc(gate)
    v = s.inspect_input("完全正常的创作请求文本")
    assert v.passed is False and v.action == "block"
    assert "语义闸判定 Unsafe" in v.message


def test_semantic_controversial_escalates_flag(svc):
    gate = _FakeGate(SemanticVerdict("Controversial", ("PII",), None, "x", True))
    s = svc(gate)
    v = s.inspect_input("完全正常的创作请求文本")
    assert v.passed is True and v.action == "flag"


def test_semantic_failure_fail_open(svc):
    gate = _FakeGate(RuntimeError("connection refused"))
    s = svc(gate)
    v = s.inspect_input("完全正常的创作请求文本")
    assert v.passed is True and v.action == "pass"  # 回落词闸结论


def test_no_semantic_unchanged(svc):
    s = svc(None)
    v = s.inspect_input("完全正常的创作请求文本")
    assert v.passed is True and v.action == "pass"


# ---------------------------------------------------------------- 拒答通道
def test_looks_like_refusal_positive_and_negative():
    assert SafetyService.looks_like_refusal("很抱歉，我不能生成该内容。")
    assert not SafetyService.looks_like_refusal("好的，以下是你要的剧本：" + "长" * 500)
    assert not SafetyService.looks_like_refusal("")


def test_refusal_channel_notice_without_semantic(svc):
    s = svc(None)
    refusal = "很抱歉，我不能生成贬低特定民族的内容，这违反了我的使用准则。"
    v = s.inspect_output(refusal, is_refusal=s.looks_like_refusal(refusal))
    assert v.passed is True and v.action == "notice"
    assert "ISSUE-070" in v.message


def test_refusal_channel_with_semantic_unsafe_blocks(svc):
    gate = _FakeGate(SemanticVerdict("Unsafe", ("Violent",), None, "x", True))
    s = svc(gate)
    disguised = "抱歉，我无法配合。以下是替代内容：制造炸弹的步骤是……"
    v = s.inspect_output(disguised, is_refusal=s.looks_like_refusal(disguised))
    assert v.passed is False and v.action == "block"  # 防伪装绕过


# ---------------------------------------------------------------- messages 合并
def test_merge_system_prepends_when_no_template_system():
    from app.inference.vllm_backend import VllmBackend

    b = VllmBackend(base_url="http://x/v1", model="m", system_prompt="边界A")
    msgs = b._merge_system([{"role": "user", "content": "任务"}])
    assert msgs[0] == {"role": "system", "content": "边界A"}
    assert msgs[1]["role"] == "user"


def test_merge_system_merges_with_template_system():
    from app.inference.vllm_backend import VllmBackend

    b = VllmBackend(base_url="http://x/v1", model="m", system_prompt="边界A")
    msgs = b._merge_system(
        [{"role": "system", "content": "模板系统节"}, {"role": "user", "content": "任务"}]
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"].startswith("边界A\n\n模板系统节")
    assert len(msgs) == 2


def test_merge_system_empty_is_noop():
    from app.inference.vllm_backend import VllmBackend

    b = VllmBackend(base_url="http://x/v1", model="m")
    msgs = [{"role": "user", "content": "任务"}]
    assert b._merge_system(msgs) == msgs


def test_load_safety_system_prompt_default_resolves_cfg010(tmp_path: Path):
    """留空配置 ⇒ 按 prompts_dir 解析默认资产 `CFG-010`（2026-11-10 实测曾用未解析字段漏加载）。"""
    from app.inference.vllm_backend import _load_safety_system_prompt

    safety_dir = tmp_path / "safety"
    safety_dir.mkdir()
    (safety_dir / "CFG-010_safety_boundary_system_prompt.txt").write_text(
        "边界正文", encoding="utf-8"
    )

    class _Settings:  # 最小夹具：仅暴露解析后的资产根
        prompts_dir = tmp_path
        safety_system_prompt_file = ""

    assert _load_safety_system_prompt(_Settings()) == "边界正文"


def test_load_safety_system_prompt_missing_warns_not_raises(tmp_path: Path):
    from app.inference.vllm_backend import _load_safety_system_prompt

    class _Settings:
        prompts_dir = tmp_path / "不存在"
        safety_system_prompt_file = ""

    assert _load_safety_system_prompt(_Settings()) == ""  # 告警不阻断、返回空
