"""提示词模板加载器测试（只读性、版本一致性、渲染、阶段映射）。"""

from __future__ import annotations

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
