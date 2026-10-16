"""输出契约 schema 的加载与常量一致性（受约束解码的 schema 来源）。

⚠️ 交叉校验的意义：`REQUIRED_TOP_KEYS` 是 `segment.merge_segments` 的告警依据，
而真正的权威是 `CFG-006` schema 的 `required`。两处各写一份**必然漂移**——
本工程已立「同源陈旧」缺陷族（`ISSUE-009`/`018`/`019`/`020`/`021`/`023`），
故此处加一道机器兜底：**常量与真值不一致即测试失败**。
"""

from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.output_schema import (
    ENGINE_UNSUPPORTED_KEYS,
    _load_cached,
    load_engine_schema,
    load_output_schema,
    schema_path_for,
    stripped_paths,
)
from app.services.segment import REQUIRED_TOP_KEYS


def test_shot_prompt_schema_is_loadable() -> None:
    schema = load_output_schema("shot_prompt")
    assert isinstance(schema, dict)
    assert schema["properties"]["schema_version"]["const"] == "2.1.0"


def test_stages_without_delivery_contract_return_none() -> None:
    """只有交付包（`shot_prompt` 层产物）有交付契约 schema。"""
    for stage in ("synopsis", "script", "storyboard", "revise", "no_such_stage"):
        assert load_output_schema(stage) is None


def test_required_keys_constant_matches_actual_schema() -> None:
    schema = load_output_schema("shot_prompt")
    assert tuple(schema["required"]) == REQUIRED_TOP_KEYS, (
        "segment.REQUIRED_TOP_KEYS 与 CFG-006 schema 的 required 不一致——"
        "两处定义已漂移，须同步"
    )


def test_schema_path_points_into_delivery_assets() -> None:
    path = schema_path_for("shot_prompt")
    assert path is not None
    assert path.name == "CFG-006_shot_prompt_pack.v1.schema.json"
    assert path.parent.name == "schemas"


def test_schema_file_actually_exists_on_disk() -> None:
    """资产缺失时服务层必须**报错**，而不是静默放弃约束。"""
    path = schema_path_for("shot_prompt")
    assert path is not None and path.is_file()


def test_missing_schema_file_raises_instead_of_degrading(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """指向不存在的目录 ⇒ 显式失败（静默放弃约束＝静默降级）。"""
    monkeypatch.setenv("APP_DELIVERY_SCHEMAS_DIR", str(tmp_path))
    get_settings.cache_clear()
    _load_cached.cache_clear()
    try:
        with pytest.raises(AppError) as ei:
            load_output_schema("shot_prompt")
        assert "schema 不存在" in ei.value.message
    finally:
        get_settings.cache_clear()
        _load_cached.cache_clear()


# --------------------------------------------------------------------------
# 引擎可编译形态（`T-004` 收尾：剥离 xgrammar 不支持的关键字）
#
# 实测依据 `OPS-002` §4.3.1 ①：真实 `CFG-006` 原样传给 vLLM 被**编译期**拒收
# （`Grammar error: Unimplemented keys: ["uniqueItems"]`），逐轮剥离证明**只需剥这一处**。
# 以下四条锁住「剥干净了」＋「其余键没被误伤」＋「契约真值没被污染」。
# --------------------------------------------------------------------------


def _count_key(node: object, key: str) -> int:
    """统计某个键在（嵌套的）JSON 结构中出现的次数。"""
    if isinstance(node, dict):
        return sum(1 for k in node if k == key) + sum(
            _count_key(v, key) for v in node.values()
        )
    if isinstance(node, list):
        return sum(_count_key(v, key) for v in node)
    return 0


def test_engine_schema_has_no_unsupported_keys() -> None:
    """引擎形态不得含任何 `ENGINE_UNSUPPORTED_KEYS`（否则引擎编译期 400）。"""
    engine = load_engine_schema("shot_prompt")
    assert isinstance(engine, dict)
    for key in ENGINE_UNSUPPORTED_KEYS:
        assert _count_key(engine, key) == 0, f"引擎形态仍残留 {key}"


def test_contract_schema_stays_complete() -> None:
    """契约真值**必须**保留 `uniqueItems` —— 应用层校验靠它补回解码期的约束缺口。"""
    full = load_output_schema("shot_prompt")
    assert isinstance(full, dict)
    assert _count_key(full, "uniqueItems") == 1


def test_engine_schema_does_not_pollute_cached_contract_schema() -> None:
    """先取引擎形态、再取契约真值 ⇒ 真值仍是完整的（防 `lru_cache` 对象被原地改坏）。"""
    load_engine_schema("shot_prompt")
    full = load_output_schema("shot_prompt")
    assert _count_key(full, "uniqueItems") == 1, (
        "契约真值被剥离逻辑污染——`_load_cached` 的缓存对象被原地修改"
    )


def test_engine_schema_differs_from_contract_only_by_unsupported_keys() -> None:
    """剥后与完整形态的差异**只**应在 `uniqueItems` 上：其余键逐字保留。"""
    full = load_output_schema("shot_prompt")
    engine = load_engine_schema("shot_prompt")
    assert isinstance(full, dict) and isinstance(engine, dict)

    target_full = full["$defs"]["unit"]["properties"]["shot_ids"]
    target_engine = engine["$defs"]["unit"]["properties"]["shot_ids"]
    assert set(target_full) - set(target_engine) == {"uniqueItems"}
    assert set(target_engine) - set(target_full) == set()
    for key, value in target_engine.items():
        assert value == target_full[key], f"`{key}` 被误改"

    # 抽样验证「其余键未受影响」：实测可通过的键在两侧计数一致
    for key in ("pattern", "enum", "minItems", "maxItems", "$ref", "const"):
        assert _count_key(engine, key) == _count_key(full, key), f"{key} 计数发生变化"
    # 顶层 required 与 schema_version 亦须一致
    assert tuple(engine["required"]) == tuple(full["required"]) == REQUIRED_TOP_KEYS


def test_stripped_paths_report_exact_location() -> None:
    """留痕必须给出**可核查的键路径**，而不是笼统说「剥过了」。"""
    assert stripped_paths("shot_prompt") == (
        "$.$defs.unit.properties.shot_ids.uniqueItems",
    )


def test_midstage_derived_engine_schema_matches_contract_truth() -> None:
    """`ISSUE-042`：中间三段的引擎 schema 由**契约真值投影**而来（不是第二份真值）。

    ⚠️ 本测试**取代**了原先的 `test_stages_without_contract_have_no_engine_schema`
    （它断言三段「没有引擎 schema」）——该断言编码的正是缺陷本身：
    三段 `constrained_decoding` 恒为 `false` ⇒ 模型可自由产出**截断的 JSON**
    （第 3 轮真跑实测），非法产物照常入库并驱动下游。
    """
    from app.services import artifact_contract

    for stage, shape in (
        ("synopsis", "synopsis"),
        ("script", "script"),
        ("storyboard", "storyboard"),
    ):
        engine = load_engine_schema(stage)
        assert isinstance(engine, dict), f"{stage} 应有派生引擎 schema"
        assert engine["type"] == "object"
        assert tuple(engine["required"]) == artifact_contract.REQUIRED_TOP_KEYS[shape]
        assert set(engine["properties"]) == set(engine["required"])
        # 刻意**不封** `additionalProperties`：`synopsis` 的真实产物顶层比 R5 多 3 个键
        # （`covered_points`/`genre`/`logline_parts`），封了会把合法产物当场判死。
        assert "additionalProperties" not in engine


def test_derived_engine_schema_is_not_shared_mutable_state() -> None:
    """派生 schema 每次返回**新对象**：调用方原地改动不得污染下一次调用。"""
    first = load_engine_schema("storyboard")
    assert isinstance(first, dict)
    first["required"].append("__污染__")
    second = load_engine_schema("storyboard")
    assert isinstance(second, dict)
    assert "__污染__" not in second["required"]


def test_engine_schema_source_reports_provenance() -> None:
    """来源可核查：`ISSUE-042` 的教训是「『已约束』与『没约束』在留痕上长得一样」。"""
    from app.services.output_schema import engine_schema_source

    assert engine_schema_source("shot_prompt") == "asset"
    for stage in ("synopsis", "script", "storyboard"):
        assert engine_schema_source(stage) == "derived"
    for stage in ("revise", "no_such_stage"):
        assert engine_schema_source(stage) == "none"


def test_stages_without_shape_contract_have_no_engine_schema() -> None:
    """`revise` 与未知阶段确无形态契约 ⇒ 返回 `None`（非错误）。"""
    for stage in ("revise", "no_such_stage"):
        assert load_engine_schema(stage) is None
        assert stripped_paths(stage) == ()


# --------------------------------------------------------------------------
# mock 样本与形态契约的一致性（`ISSUE-042`）
#
# ⚠️ 形态闸生效后，「产物合不合形态」是**入库硬前提**——mock 后端若回一段
# 不合形态的 JSON，会被闸门正当地拦下，令「离链路无 GPU 可跑通」的 mock 存在理由消失。
# `mock_backend._MOCK_SAMPLES` 刻意**不 import 契约模块**（`inference` 层不反向依赖
# `services` 层），代价是可能悄悄偏离契约 ⇒ 由本测试做**单向断言**兜住：
# 契约一改而样本未随改，此处**当场失败**，不会静默漂移。
# --------------------------------------------------------------------------


def test_mock_samples_satisfy_artifact_contract() -> None:
    """用**真实回包**（含 `_mock` 标记键）验证，而非只验样本常量。"""
    from app.inference.mock_backend import MockBackend
    from app.services import artifact_contract

    backend = MockBackend()
    for stage, shape in artifact_contract.STAGE_TO_SHAPE.items():
        payload = backend._payload(f"[stage:{stage}]\n<system>\nmock", None)
        assert payload.get("_mock") is True, "mock 标记必须保留（防误当作真实产物）"
        verdict = artifact_contract.check_shape(shape, json.dumps(payload, ensure_ascii=False))
        assert verdict.ok, f"mock 回包 `{stage}` 不合形态契约：{verdict.error}"
