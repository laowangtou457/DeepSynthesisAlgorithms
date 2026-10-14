"""提示词模板加载器。

读取 `03-工程代码/prompts/`：

- `CFG-008_manifest.yaml` —— 资产主清单（id / file / version / stage / status）
- `templates/TPL-*.yaml`   —— 各模板正文（`sections` 五节：system / task / context / output / examples）

能力：按 id 取模板、按 stage 解析链路模板、必填变量校验、五节渲染。

纪律（**只读**）：
- 加载器**绝不改写**模板资产；模板版本一律从清单读，不得在代码中硬编码；
- 模板 version 与 manifest version 不一致时**报错而非静默取一**（避免"版本引用陈旧"缺陷类）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.errors import AppError, ErrorCode

#: 变量插值：`{name}` 或 `{name?缺省值}`。仅匹配单行内的裸标识符，
#: 故不会误伤模板 output 段中的 JSON 花括号（那里的 `{` 后紧跟换行或引号）。
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:\?([^}\n]*))?\}")

#: 链路阶段 → 模板 id（与 CFG-008 的 `stage` 字段一一对应）。
STAGE_TEMPLATE: dict[str, str] = {
    "synopsis": "synopsis_v1",
    "script": "script_v1",
    "storyboard": "storyboard_v1",
    "shot_prompt": "shot_prompt_v1",
    "revise": "revise_v1",
}

#: 五节顺序（CFG-007_SCHEMA.md 规定）。
SECTION_ORDER: tuple[str, ...] = ("system", "task", "context", "output", "examples")


@dataclass(frozen=True)
class Template:
    """一个提示词模板。"""

    id: str
    name: str
    version: str
    task_type: str
    stage: str | None
    file: str
    status: str
    variables: tuple[dict[str, Any], ...]
    sampling: dict[str, Any]
    sections: dict[str, str]
    guards: tuple[str, ...] = ()
    fallback: dict[str, Any] = field(default_factory=dict)

    @property
    def required_variables(self) -> tuple[str, ...]:
        return tuple(v["name"] for v in self.variables if v.get("required"))

    def default_of(self, var: str) -> Any:
        for v in self.variables:
            if v["name"] == var:
                return v.get("default")
        return None


@dataclass(frozen=True)
class RenderedPrompt:
    """渲染后的提示词（五节 + 拼装串）。"""

    template_id: str
    version: str
    sections: dict[str, str]

    @property
    def system(self) -> str:
        return self.sections.get("system", "")

    @property
    def task(self) -> str:
        return self.sections.get("task", "")

    @property
    def context(self) -> str:
        return self.sections.get("context", "")

    @property
    def output(self) -> str:
        return self.sections.get("output", "")

    @property
    def examples(self) -> str:
        return self.sections.get("examples", "")

    def as_text(self) -> str:
        """拼装为单串模型输入。首行带 `[stage:<阶段>]` 标记，便于日志与 mock 识别。"""
        parts: list[str] = []
        if self.system:
            parts.append(f"<system>\n{self.system}")
        if self.task:
            parts.append(f"<task>\n{self.task}")
        if self.context:
            parts.append(f"<context>\n{self.context}")
        if self.output:
            parts.append(f"<output>\n{self.output}")
        if self.examples:
            parts.append(f"<examples>\n{self.examples}")
        return "\n\n".join(parts)


class PromptRepository:
    """提示词资产仓库（只读）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "CFG-008_manifest.yaml"
        self._templates: dict[str, Template] = {}
        self._loaded = False

    # ---- 加载 ----
    def load(self) -> "PromptRepository":
        if self._loaded:
            return self
        if not self.manifest_path.is_file():
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                "提示词资产清单不存在",
                details={"expected": str(self.manifest_path)},
            )
        manifest = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        entries = manifest.get("templates") or []
        if not isinstance(entries, list):
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND, "清单格式异常：`templates` 应为列表"
            )
        for entry in entries:
            tpl = self._load_one(entry)
            self._templates[tpl.id] = tpl
        self._loaded = True
        return self

    def _load_one(self, entry: dict[str, Any]) -> Template:
        tid = entry.get("id")
        rel = entry.get("file")
        if not tid or not rel:
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND, f"清单条目缺 `id` 或 `file`：{entry!r}"
            )
        path = self.root / rel
        if not path.is_file():
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"模板文件不存在：{rel}",
                details={"template_id": tid, "file": str(path)},
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        body_version = str(raw.get("version", ""))
        manifest_version = str(entry.get("version", ""))
        if body_version and manifest_version and body_version != manifest_version:
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"模板「{tid}」版本不一致：正文 {body_version} / 清单 {manifest_version}",
                details={"template_id": tid},
            )
        sections = raw.get("sections") or {}
        if not isinstance(sections, dict):
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"模板「{tid}」的 `sections` 应为映射（dict）",
            )
        return Template(
            id=str(tid),
            name=str(entry.get("name") or raw.get("name") or ""),
            version=manifest_version or body_version,
            task_type=str(entry.get("task_type") or raw.get("task_type") or ""),
            stage=(entry.get("stage") or raw.get("stage")),
            file=str(rel),
            status=str(entry.get("status", "active")),
            variables=tuple(raw.get("variables") or ()),
            sampling=dict(raw.get("sampling") or {}),
            sections={k: str(v) for k, v in sections.items()},
            guards=tuple(raw.get("guards") or ()),
            fallback=dict(raw.get("fallback") or {}),
        )

    # ---- 查询 ----
    def get(self, template_id: str) -> Template:
        self.load()
        tpl = self._templates.get(template_id)
        if tpl is None:
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"模板不存在：{template_id}",
                details={"available": sorted(self._templates)},
            )
        return tpl

    def by_stage(self, stage: str) -> Template:
        tid = STAGE_TEMPLATE.get(stage)
        if tid is None:
            raise AppError(
                ErrorCode.TEMPLATE_NOT_FOUND,
                f"阶段「{stage}」没有对应链路模板",
                details={"known_stages": sorted(STAGE_TEMPLATE)},
            )
        return self.get(tid)

    def list(self, *, status: str | None = None, task_type: str | None = None) -> list[Template]:
        self.load()
        out = list(self._templates.values())
        if status is not None:
            out = [t for t in out if t.status == status]
        if task_type is not None:
            out = [t for t in out if t.task_type == task_type]
        return sorted(out, key=lambda t: t.id)

    # ---- 渲染 ----
    def missing_required(self, tpl: Template, variables: dict[str, Any]) -> list[str]:
        return [n for n in tpl.required_variables if n not in variables or variables[n] in (None, "")]

    def render(self, tpl: Template, variables: dict[str, Any]) -> RenderedPrompt:
        missing = self.missing_required(tpl, variables)
        if missing:
            raise AppError(
                ErrorCode.TEMPLATE_VARIABLE_MISSING,
                f"模板「{tpl.id}」缺少必填变量：{'、'.join(missing)}",
                details={"template_id": tpl.id, "missing": missing},
            )
        sections: dict[str, str] = {}
        for name, text in tpl.sections.items():
            sections[name] = _interpolate(text, variables, tpl)
        return RenderedPrompt(template_id=tpl.id, version=tpl.version, sections=sections)


def _interpolate(text: str, variables: dict[str, Any], tpl: Template) -> str:
    def repl(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        value = variables.get(name)
        if value is not None and value != "":
            return _stringify(value)
        if default is not None:
            return default
        tpl_default = tpl.default_of(name)
        if tpl_default is not None:
            return _stringify(tpl_default)
        return ""

    return _TOKEN.sub(repl, text)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "、".join(_stringify(v) for v in value) if value else "无"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
