"""端到端冒烟：全链路、门控、回退、错误信封与占位接口。

本文件是 T-003 一期的**验收证据**：它逐条对应 REQ-005 的验收标准。
"""

from __future__ import annotations

SESSIONS = "/api/v1/sessions"


def _new_session(client, source: str = "一只流浪猫在雨夜被人救起") -> str:
    r = client.post(SESSIONS, json={"source_input": source, "target_duration": "60-90秒"})
    assert r.status_code == 201, r.text
    return r.json()["data"]["session_id"]


# ------------------------------------------------------------------ 探针
def test_health_and_ready(client) -> None:
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["prompts"].startswith("ok")


def test_openapi_is_served(client) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.")
    for path in ("/api/v1/sessions", "/api/v1/generations", "/api/v1/safety/inspect"):
        assert path in spec["paths"]


# ------------------------------------------------------------------ 请求上下文
def test_request_id_is_echoed_and_traceable(client) -> None:
    r = client.get("/health", headers={"X-Request-ID": "req_custom_001"})
    assert r.headers["X-Request-ID"] == "req_custom_001"


def test_request_id_generated_when_absent(client) -> None:
    r = client.get("/health")
    assert r.headers["X-Request-ID"].startswith("req_")


# ------------------------------------------------------------------ 全链路
def test_full_chain_walks_seven_stages(client) -> None:
    sid = _new_session(client)
    assert client.get(f"{SESSIONS}/{sid}").json()["data"]["stage"] == "draft_synopsis"

    r = client.post(f"{SESSIONS}/{sid}/advance", json={})
    assert r.status_code == 200 and r.json()["data"]["to_stage"] == "synopsis_revising"

    r = client.post(f"{SESSIONS}/{sid}/confirm", json={})
    assert r.json()["data"]["to_stage"] == "synopsis_confirmed"

    for expected in ("draft_script", "draft_storyboard", "draft_shot_prompt", "completed"):
        r = client.post(f"{SESSIONS}/{sid}/advance", json={})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["to_stage"] == expected

    view = client.get(f"{SESSIONS}/{sid}").json()["data"]
    assert view["stage"] == "completed"
    assert set(view["artifacts"]) == {"synopsis", "script", "storyboard", "shot_prompt"}
    assert view["confirmed_snapshot"]["artifact"] == "synopsis"


def test_gate_blocks_unconfirmed_advance(client) -> None:
    """SW-003：未确认梗概就想进剧本阶段 ⇒ 409 CONFIRMATION_REQUIRED。"""
    sid = _new_session(client)
    client.post(f"{SESSIONS}/{sid}/advance", json={})  # 生成梗概 → 梗概修改
    r = client.post(f"{SESSIONS}/{sid}/advance", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert client.get(f"{SESSIONS}/{sid}").json()["data"]["stage"] == "synopsis_revising"


def test_terminal_stage_is_protected(client) -> None:
    sid = _new_session(client)
    client.post(f"{SESSIONS}/{sid}/advance", json={})
    client.post(f"{SESSIONS}/{sid}/confirm", json={})
    for _ in range(4):
        client.post(f"{SESSIONS}/{sid}/advance", json={})
    r = client.post(f"{SESSIONS}/{sid}/advance", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_rollback_to_prior_stage_and_reject_forward(client) -> None:
    sid = _new_session(client)
    client.post(f"{SESSIONS}/{sid}/advance", json={})   # synopsis_revising
    client.post(f"{SESSIONS}/{sid}/confirm", json={})   # synopsis_confirmed
    client.post(f"{SESSIONS}/{sid}/advance", json={})   # draft_script

    bad = client.post(f"{SESSIONS}/{sid}/rollback", json={"target_stage": "draft_storyboard"})
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "ROLLBACK_TARGET_INVALID"

    ok = client.post(f"{SESSIONS}/{sid}/rollback", json={"target_stage": "synopsis_revising"})
    assert ok.status_code == 200 and ok.json()["data"]["to_stage"] == "synopsis_revising"
    # 回退不销毁已确认快照（供对照）
    assert client.get(f"{SESSIONS}/{sid}").json()["data"]["confirmed_snapshot"] is not None


def test_revise_changes_artifact_without_moving_stage(client) -> None:
    """SW-002 对话式修改：改产物、不改阶段。"""
    sid = _new_session(client)
    client.post(f"{SESSIONS}/{sid}/advance", json={})
    before = client.get(f"{SESSIONS}/{sid}").json()["data"]["stage"]
    r = client.post(
        f"{SESSIONS}/{sid}/revise",
        json={"modification_request": "把主角改成女性", "target_stage": before},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["from_stage"] == data["to_stage"] == before


# ------------------------------------------------------------------ 错误信封
def test_missing_session_yields_enveloped_404(client) -> None:
    r = client.get(f"{SESSIONS}/sess_does_not_exist")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "SESSION_NOT_FOUND"
    assert body["error"]["request_id"].startswith("req_")


def test_validation_error_is_enveloped(client) -> None:
    r = client.post(SESSIONS, json={"source_input": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_session_requires_body(client) -> None:
    assert client.post(SESSIONS, json={}).status_code == 400


# ------------------------------------------------------------------ SW-I02 生成
def test_generation_endpoint_with_mock_backend(client) -> None:
    r = client.post(
        "/api/v1/generations",
        json={"stage": "synopsis", "variables": {"source_input": "一句话创意"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["provenance"]["ai_generated"] is True  # 隐式标识载体不可缺
    assert body["model"]["name"] == "mock"


def test_mock_is_deterministic(client) -> None:
    payload = {"stage": "synopsis", "variables": {"source_input": "同一个输入"}}
    a = client.post("/api/v1/generations", json=payload).json()
    b = client.post("/api/v1/generations", json=payload).json()
    assert a["output"]["text"] == b["output"]["text"]


def test_templates_and_backends_listing(client) -> None:
    tpls = client.get("/api/v1/templates").json()["data"]
    assert {t["id"] for t in tpls} >= {
        "synopsis_v1",
        "script_v1",
        "storyboard_v1",
        "shot_prompt_v1",
        "revise_v1",
    }
    backends = client.get("/api/v1/backends").json()["data"]
    assert "mock" in backends


# ------------------------------------------------------------------ 占位接口
def test_unimplemented_endpoints_return_501_not_silent_pass(client) -> None:
    """未接入的接口必须**显式报未接入**，不得静默放行。

    ⚠️ `SW-I03`（`/safety/*`）已于任务 **`T-005`** 从占位改为实现，
    故**移出本用例**；其「不静默放行」改由**另一条更强的纪律**保证——
    词库不可用时返回 `passed=false` 而非「通过」，见 `tests/test_safety.py`。
    """
    cases = [
        ("post", "/api/v1/delivery/pack"),
        ("post", "/api/v1/auth/login"),
        ("post", "/api/v1/auth/verify-identity"),
        ("post", "/api/v1/export/sess_x"),
    ]
    for method, path in cases:
        r = getattr(client, method)(path)
        assert r.status_code == 501, f"{path} 返回 {r.status_code}"
        assert r.json()["error"]["code"] == "NOT_IMPLEMENTED"
