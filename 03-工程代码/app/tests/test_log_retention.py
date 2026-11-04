"""溯源留存日志测试（`T-090`／官方第 9 项／`SW-016` 五要素）。

覆盖四件事：

1. **配置**：留存默认 180 天、落盘开关默认开（改小即违反官方要求，属受控变更）；
2. **通道**：落盘 → `app.log`／`audit.log` 真的出现；重复 `configure_logging` **不叠行**（幂等）；
3. **五要素**：审计记录含 会话／阶段／模型／模板／时间／结果，且**正文不落明文**（只留摘要）；
4. **自检脚本**：今日无日志 → FAIL；有缺口 → FAIL；留存不足 180 → FAIL（退出码可进 CI）。
"""

from __future__ import annotations

import json

import pytest

from app.core import logging as applog
from app.core.audit import build_trace, emit_trace, trace_transition
from app.core.config import Settings
from app.core.logging import configure_logging, digest


@pytest.fixture()
def clean_loggers():
    """保存/恢复 `app` 与 `app.audit` 的处理器，避免测试间互相污染。"""
    root = applog.logging.getLogger("app")
    audit = applog.logging.getLogger("app.audit")
    saved_root, saved_audit = list(root.handlers), list(audit.handlers)
    saved_level, saved_prop = root.level, root.propagate
    try:
        yield
    finally:
        for h in list(root.handlers) + list(audit.handlers):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
        root.handlers, audit.handlers = saved_root, saved_audit
        root.setLevel(saved_level)
        root.propagate = saved_prop


def _settings(tmp_path, **kw) -> Settings:
    base = dict(log_dir=str(tmp_path), log_to_file=True, log_retention_days=180)
    base.update(kw)
    return Settings(_env_file=None, **base)


# ---------------------------------------------------------------- ① 配置默认值


def test_retention_defaults_meet_regulation() -> None:
    s = Settings(_env_file=None)
    assert s.log_retention_days == 180, "留存默认值不得低于 180 天（6 个月）"
    assert s.log_to_file is True, "生产默认必须落盘，否则官方第 9 项交不了"
    assert s.log_dir == ""


# ---------------------------------------------------------------- ② 通道与幂等


def test_file_channels_created_and_idempotent(tmp_path, clean_loggers) -> None:
    configure_logging(settings=_settings(tmp_path))
    applog.get_logger().info("hello", extra={"extra_fields": {"k": 1}})
    emit_trace(build_trace(session_id="S1", stage="script", artifact={}, action="generate"))

    app_log = tmp_path / "app.log"
    audit_log = tmp_path / "audit.log"
    assert app_log.exists() and audit_log.exists(), "两个通道都必须落盘"

    # 幂等：再配一次不得出现重复文件处理器（否则每行日志写两遍）
    configure_logging(settings=_settings(tmp_path))
    applog.get_logger().info("again", extra={"extra_fields": {"k": 2}})
    lines = [ln for ln in app_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, f"重复初始化导致重复写入：{lines}"

    kinds = [getattr(h, "_wb_kind", "") for h in applog.logging.getLogger("app").handlers]
    assert kinds.count("app_file") == 1


def test_retention_backup_count_equals_configured_days(tmp_path, clean_loggers) -> None:
    configure_logging(settings=_settings(tmp_path, log_retention_days=200))
    handlers = applog.logging.getLogger("app").handlers
    fh = next(h for h in handlers if getattr(h, "_wb_kind", "") == "app_file")
    assert fh.backupCount == 200, "留存天数必须落到 backupCount，否则机制不生效"


def test_log_to_file_false_removes_file_channels(tmp_path, clean_loggers) -> None:
    configure_logging(settings=_settings(tmp_path))
    configure_logging(settings=_settings(tmp_path, log_to_file=False))
    kinds = [getattr(h, "_wb_kind", "") for h in applog.logging.getLogger("app").handlers]
    assert "app_file" not in kinds
    assert applog.logging.getLogger("app.audit").handlers == []


# ---------------------------------------------------------------- ③ 五要素


def test_trace_record_has_five_elements_without_plaintext() -> None:
    text = "第一场·夜·巷口。林晚抬头看见霓虹灯闪烁。"
    artifact = {
        "text": text,
        "template_id": "TPL-008",
        "template_version": "2.1.1",
        "backend": "vllm",
        "model": {"name": "vllm", "version": "Qwen2.5-7B-Instruct"},
        "quality_gate": {"ok": True, "attempts": 1},
    }
    rec = build_trace(session_id="S-9", stage="script", artifact=artifact, action="generate")

    assert rec["session_id"] == "S-9"                      # ① 会话
    assert rec["stage"] == "script"                        # ② 阶段
    assert rec["model"]["name"] == "Qwen2.5-7B-Instruct"   # ③ 模型（语义对调已纠正）
    assert rec["model"]["backend"] == "vllm"
    assert rec["templates"] == [{"id": "TPL-008", "version": "2.1.1"}]  # ④ 模板
    assert rec["ts"].count("T") == 1 and "+" in rec["ts"]  # ⑤ 时间（ISO 8601 带偏移）
    assert rec["result"]["status"] == "ok"
    assert rec["result"]["chars"] == len(text)
    assert rec["result"]["digest"] == digest(text)

    # ⚠️ 正文**不得**出现在审计记录里（只留摘要与长度）
    assert text not in json.dumps(rec, ensure_ascii=False)


def test_trace_transition_only_for_generating_actions() -> None:
    class _Stage:
        value = "script"

    class _Result:
        def __init__(self, action: str) -> None:
            self.action = action
            self.session_id = "S"
            self.to_stage = _Stage()
            self.view = type("V", (), {"artifacts": {"script": {"text": "x", "template_id": "T"}}})()

    assert trace_transition(_Result("confirm")) is None
    assert trace_transition(_Result("rollback")) is None
    assert trace_transition(_Result("generate")) is not None


# ---------------------------------------------------------------- ④ 自检脚本


def _load_tool():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools" / "check_log_retention.py"
    spec = importlib.util.spec_from_file_location("check_log_retention", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_day(log_dir, prefix: str, day: str, n: int = 2) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{prefix}.{day}"
    lines = [
        json.dumps({"ts": f"{day}T10:0{i}:00+08:00", "event": "x", "n": i}, ensure_ascii=False)
        for i in range(n)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_checker_fails_when_today_missing(tmp_path) -> None:
    mod = _load_tool()
    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _write_day(tmp_path, "app.log", yesterday)
    _write_day(tmp_path, "audit.log", yesterday)
    res = mod.check(tmp_path, 180, ("app", "audit"))
    assert res["verdict"] == "FAIL"
    assert any("今日无日志" in r for r in res["reasons"])


def test_checker_fails_on_gap(tmp_path) -> None:
    mod = _load_tool()
    from datetime import date, timedelta

    today = date.today()
    for delta in (0, 1, 3):  # 缺 D-2
        day = (today - timedelta(days=delta)).isoformat()
        _write_day(tmp_path, "app.log", day)
        _write_day(tmp_path, "audit.log", day)
    res = mod.check(tmp_path, 180, ("app", "audit"))
    assert res["verdict"] == "FAIL"
    assert any("缺口" in r for r in res["reasons"])


def test_checker_warns_when_history_shorter_than_retention(tmp_path) -> None:
    mod = _load_tool()
    from datetime import date, timedelta

    for delta in range(0, 5):
        day = (date.today() - timedelta(days=delta)).isoformat()
        _write_day(tmp_path, "app.log", day)
        _write_day(tmp_path, "audit.log", day)
    res = mod.check(tmp_path, 180, ("app", "audit"))
    assert res["verdict"] == "WARN", "历史不足 180 天应如实 WARN（不能声称已验证 6 个月）"
    assert mod.main(["--dir", str(tmp_path)]) == 0


def test_checker_rejects_retention_below_regulation(tmp_path) -> None:
    mod = _load_tool()
    from datetime import date

    _write_day(tmp_path, "app.log", date.today().isoformat())
    _write_day(tmp_path, "audit.log", date.today().isoformat())
    res = mod.check(tmp_path, 90, ("app", "audit"))
    assert res["verdict"] == "FAIL"
    assert any("官方下限" in r for r in res["reasons"])
    assert mod.main(["--dir", str(tmp_path), "--days", "90"]) == 1


# ---------------------------------------------------------------- 互锁：阶段→产物键


def test_artifact_key_rule_matches_service_map() -> None:
    """⚠️ **互锁对拍**：`core.audit.artifact_key_for` 与 `dialogue_service._artifact_key_of`。

    两处是**同一口径的两个来源**（后者用显式映射表 `_GENERATE_ON`，前者用可推导规则）。
    任一侧新增/改名阶段而漏改另一侧，本测试当场报警——
    这正是「同口径两处手写」家族缺陷的防复发机制（`PRO-012` 变更三件套）。
    """
    from app.core.audit import artifact_key_for
    from app.schemas.dialogue import Stage
    from app.services.dialogue_service import _artifact_key_of

    generating = [Stage.SYNOPSIS_REVISING, Stage.DRAFT_SCRIPT,
                  Stage.DRAFT_STORYBOARD, Stage.DRAFT_SHOT_PROMPT]
    for stage in generating:
        assert artifact_key_for(stage.value) == _artifact_key_of(stage), (
            f"{stage.value}：审计侧规则与服务层映射不一致"
        )
