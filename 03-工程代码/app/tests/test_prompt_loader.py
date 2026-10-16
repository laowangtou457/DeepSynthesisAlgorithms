"""提示词模板加载器测试（只读性、版本一致性、渲染、阶段映射）。"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.prompts.loader import SECTION_ORDER, STAGE_TEMPLATE, PromptRepository


@pytest.fixture()
def repo() -> PromptRepository:
    return PromptRepository(get_settings().prompts_dir).load()


def test_loads_every_manifest_entry(repo: PromptRepository) -> None:
    """清单里登记多少条，就加载出多少条（不漏读、不多读）。"""
    manifest = yaml.safe_load(repo.manifest_path.read_text(encoding="utf-8"))
    declared = {t["id"] for t in manifest["templates"]}
    assert {t.id for t in repo.list()} == declared


def test_manifest_version_equals_body_version(repo: PromptRepository) -> None:
    """清单版本与模板正文版本必须一致（防「版本引用陈旧」缺陷类）。"""
    for tpl in repo.list():
        raw = yaml.safe_load((repo.root / tpl.file).read_text(encoding="utf-8"))
        assert tpl.version == str(raw["version"]), f"{tpl.id} 版本不一致"


def test_versions_are_semver(repo: PromptRepository) -> None:
    for tpl in repo.list():
        assert re.fullmatch(r"\d+\.\d+\.\d+", tpl.version), f"{tpl.id}={tpl.version}"


def test_stage_mapping_resolves_to_expected_ids(repo: PromptRepository) -> None:
    for stage, tid in STAGE_TEMPLATE.items():
        assert repo.by_stage(stage).id == tid
        assert repo.by_stage(stage).stage == stage


def test_chain_templates_have_five_sections(repo: PromptRepository) -> None:
    """五段链路模板必须具备五节中的前四节（system/task/context/output）。"""
    for stage in ("synopsis", "script", "storyboard", "shot_prompt", "revise"):
        tpl = repo.by_stage(stage)
        for section in SECTION_ORDER[:4]:
            assert tpl.sections.get(section, "").strip(), f"{tpl.id} 缺 {section}"


def test_unknown_template_raises(repo: PromptRepository) -> None:
    with pytest.raises(AppError) as ei:
        repo.get("no_such_template")
    assert ei.value.code is ErrorCode.TEMPLATE_NOT_FOUND


def test_missing_required_variable_is_rejected(repo: PromptRepository) -> None:
    with pytest.raises(AppError) as ei:
        repo.render(repo.get("synopsis_v1"), {})
    assert ei.value.code is ErrorCode.TEMPLATE_VARIABLE_MISSING
    assert "source_input" in ei.value.details["missing"]


def test_render_substitutes_variables_and_clears_placeholders(repo: PromptRepository) -> None:
    tpl = repo.get("synopsis_v1")
    rendered = repo.render(tpl, {"source_input": "一只流浪猫在雨夜被人救起"})
    assert "一只流浪猫在雨夜被人救起" in rendered.task
    # 必填变量已给出 ⇒ 不应残留 `{source_input}` 形式的占位
    assert "{source_input}" not in rendered.as_text()


def test_render_applies_template_defaults(repo: PromptRepository) -> None:
    """模板声明的 default 必须生效（非必填变量缺省时不留空占位）。"""
    tpl = repo.get("synopsis_v1")
    rendered = repo.render(tpl, {"source_input": "x"})
    for section in rendered.sections.values():
        for name in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", section):
            assert name not in tpl.required_variables, f"残留必填占位 {{{name}}}"


def test_loader_is_read_only(repo: PromptRepository) -> None:
    """加载与渲染**不得改写**模板资产（比对渲染前后文件字节数）。"""
    path = repo.root / repo.get("synopsis_v1").file
    before = path.read_bytes()
    repo.render(repo.get("synopsis_v1"), {"source_input": "y"})
    assert path.read_bytes() == before


# ------------------------------------------- 上游注入体积（`ISSUE-037` 回归位）
def test_shot_prompt_injects_each_upstream_exactly_once(repo: PromptRepository) -> None:
    """上游产物的**全文**在渲染结果里只出现一次（`ISSUE-037` 回归）。

    渲染器 `_interpolate` 对 `sections` 中**每一处** `{name}` 都做**全量替换**
    ⇒ 「正文里重复指称同一变量」等价于「把上游全文重复搬运」。原稿把
    `{storyboard_json}` 插 **5** 次、`{script_json}` **3** 次、`{pack_meta}` **4** 次
    ⇒ 上游被放大 **2.44 倍**，`shot_prompt` 段真实输入达 **50,358 tokens**，
    加模板输出 8,192 后 **58,550**，超 Qwen2.5-7B 原生上限 **32768**
    ⇒ 该段在**引擎入口**被拒（`502`；实测于 `T-004` 收尾第 2 轮真跑）。

    本用例用**唯一标记串**做上游内容，直接数它在渲染结果里出现几次
    ——期望 3（＝三份各一次），而非原稿的 12。
    """
    tpl = repo.by_stage("shot_prompt")
    marker = "MARKER-UPSTREAM-7f3a"
    payload = json.dumps({"marker": marker}, ensure_ascii=False)
    rendered = repo.render(
        tpl,
        {"storyboard_json": payload, "script_json": payload, "pack_meta": payload},
    )
    assert rendered.as_text().count(marker) == 3


def test_shot_prompt_sections_reference_upstream_once_each(repo: PromptRepository) -> None:
    """静态形式：`sections` 内每个上游变量**恰好**出现 1 次。

    ⚠️ 「**至少** 1 次」是硬约束——`prompts/validate_templates.py` 对「声明但正文未使用」
    的变量会告警；本用例进一步钉死在「**恰好** 1 次」，使「重复注入」不能经渲染器之外的
    路径悄悄回来（正文里的指称必须写成纯文本，而不是复制占位符）。
    """
    tpl = repo.by_stage("shot_prompt")
    body = "\n".join(tpl.sections.get(k, "") for k in SECTION_ORDER)
    for var in ("storyboard_json", "script_json", "pack_meta"):
        assert len(re.findall(r"\{" + var + r"\}", body)) == 1, f"{var} 出现了多次"
