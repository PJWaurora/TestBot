import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from main import QuietAccessLogFilter, app
from schemas import BrainMessage, OutboxEnqueueRequest, OutboxItem
from services.outbox import _validate_messages


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_module_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICE_DEFAULTS", "")
    for key in (
        "BRAIN_MODULE_SERVICES",
        "BRAIN_MODULE_TIMEOUT",
        "BRAIN_GROUP_ALLOWLIST",
        "BRAIN_GROUP_BLOCKLIST",
        "BRAIN_MODULE_BILIBILI_GROUP_ALLOWLIST",
        "BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST",
        "BILIBILI_GROUP_ALLOWLIST",
        "BILIBILI_GROUP_BLOCKLIST",
        "BRAIN_MODULE_TSPERSON_GROUP_ALLOWLIST",
        "BRAIN_MODULE_TSPERSON_GROUP_BLOCKLIST",
        "TSPERSON_GROUP_ALLOWLIST",
        "TSPERSON_GROUP_BLOCKLIST",
        "BRAIN_MODULE_WEATHER_GROUP_ALLOWLIST",
        "BRAIN_MODULE_WEATHER_GROUP_BLOCKLIST",
        "WEATHER_GROUP_ALLOWLIST",
        "WEATHER_GROUP_BLOCKLIST",
        "OUTBOX_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_access_log_filter_silences_successful_health_and_chat() -> None:
    access_filter = QuietAccessLogFilter()

    assert access_filter.filter(_access_record("GET", "/health", 200)) is False
    assert access_filter.filter(_access_record("POST", "/chat", 200)) is False
    assert access_filter.filter(_access_record("POST", "/chat", 500)) is True


def test_no_module_services_plain_text_silent_and_echo_still_works() -> None:
    plain_response = client.post("/chat", json={"text": "hello"})

    assert plain_response.status_code == 200
    plain_body = plain_response.json()
    assert plain_body["handled"] is False
    assert plain_body["should_reply"] is False
    assert plain_body["metadata"] == {"reason": "no_route"}
    assert "messages" not in plain_body

    echo_response = client.post("/chat", json={"text": "/tool-echo runtime"})

    assert echo_response.status_code == 200
    echo_body = echo_response.json()
    assert echo_body["handled"] is True
    assert echo_body["should_reply"] is True
    assert echo_body["reply"] == "runtime"
    assert echo_body["messages"] == [{"type": "text", "text": "runtime"}]


def test_chat_accepts_normalized_message_envelope() -> None:
    response = client.post(
        "/chat",
        json={
            "message": {
                "role": "user",
                "type": "text",
                "content": "hello from envelope",
                "user_id": 9,
                "message_type": "private",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}


def test_chat_uses_latest_normalized_message() -> None:
    response = client.post(
        "/chat",
        json={
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "user", "text": "latest"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}


def test_default_tools_exposes_only_echo() -> None:
    response = client.get("/tools")

    assert response.status_code == 200
    tools = response.json()
    assert [tool["name"] for tool in tools] == ["echo"]
    assert "input_schema" in tools[0]


@pytest.mark.parametrize(
    "text",
    [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "查询人数",
    ],
)
def test_unconfigured_external_module_triggers_stay_silent(text: str) -> None:
    response = client.post("/chat", json={"text": text})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}
    assert "messages" not in body


def test_default_module_services_are_merged_with_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setenv("BRAIN_MODULE_SERVICE_DEFAULTS", "weather=http://module-weather:8013")
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "bilibili=http://module-bilibili:8011")

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        if url == "http://module-weather:8013/handle":
            return FakeResponse(
                {
                    "handled": True,
                    "should_reply": True,
                    "reply": "weather-ok",
                    "messages": [{"type": "text", "text": "weather-ok"}],
                    "metadata": {"module": "weather"},
                }
            )
        raise AssertionError(f"unexpected remote call: {url}")

    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post("/chat", json={"text": "天气 北京"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["reply"] == "weather-ok"
    assert calls == [
        {
            "url": "http://module-weather:8013/handle",
            "json": {
                "self_id": None,
                "post_type": None,
                "primary_type": None,
                "text": "天气 北京",
                "content": "",
                "message": None,
                "messages": [],
                "text_segments": [],
                "json_messages": [],
                "user_id": None,
                "group_id": None,
                "conversation_id": None,
                "message_id": None,
                "message_type": None,
                "metadata": {},
            },
            "timeout": 5.0,
        }
    ]


def test_tool_call_echoes_arguments() -> None:
    response = client.post(
        "/tools/call",
        json={"name": "echo", "arguments": {"text": "runtime"}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tool_name": "echo",
        "ok": True,
        "data": {"text": "runtime"},
    }


def test_outbox_requires_configured_token() -> None:
    response = client.post("/outbox/pull", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "OUTBOX_TOKEN is not configured"


def test_outbox_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTBOX_TOKEN", "secret")

    response = client.post("/outbox/pull", headers={"Authorization": "Bearer wrong"}, json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid outbox token"


def test_outbox_endpoints_use_store_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeOutboxStore()
    monkeypatch.setenv("OUTBOX_TOKEN", "secret")
    monkeypatch.setattr("main.outbox_store", store)

    enqueue_response = client.post(
        "/outbox/enqueue",
        headers={"Authorization": "Bearer secret"},
        json={
            "message_type": "group",
            "group_id": "8",
            "messages": [{"type": "text", "text": "queued"}],
            "metadata": {"source": "test"},
        },
    )
    assert enqueue_response.status_code == 200
    enqueue_body = enqueue_response.json()
    assert enqueue_body["messages"][0]["type"] == "text"
    assert enqueue_body["messages"][0]["text"] == "queued"
    assert store.enqueued is not None
    assert store.enqueued.group_id == "8"

    pull_response = client.post(
        "/outbox/pull",
        headers={"Authorization": "Bearer secret"},
        json={"limit": 3, "lease_seconds": 9},
    )
    assert pull_response.status_code == 200
    assert pull_response.json()["items"][0]["id"] == 42
    assert store.pull_args == (3, 9)

    ack_response = client.post("/outbox/42/ack", headers={"X-Outbox-Token": "secret"})
    assert ack_response.status_code == 200
    assert store.acked == 42

    fail_response = client.post(
        "/outbox/42/fail",
        headers={"Authorization": "Bearer secret"},
        json={"error": "send failed"},
    )
    assert fail_response.status_code == 200
    assert store.failed == (42, "send failed")


def test_outbox_messages_accept_existing_data_shape() -> None:
    _validate_messages(
        [
            BrainMessage(type="text", data={"text": "queued"}),
            BrainMessage(type="image", data={"url": "https://example.test/card.png"}),
            BrainMessage(type="video", data={"file": "http://media.local/video.mp4"}),
        ]
    )


def test_chat_falls_back_to_fake_planner_when_router_misses() -> None:
    response = client.post("/chat", json={"text": "/echo runtime"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["reply"] == "runtime"
    assert body["messages"] == [{"type": "text", "text": "runtime"}]
    assert body["tool_calls"] == [{"name": "echo", "arguments": {"text": "runtime"}}]
    assert body["metadata"] == {"planner": "fake"}


def test_remote_module_handles_bilibili_json_card_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    payload = _json_example_payload()
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "bilibili=http://module-bilibili:8011")

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        assert url == "http://module-bilibili:8011/handle"
        assert timeout == 5.0
        assert json["json_messages"][0]["parsed"] == payload
        assert "https://b23.tv/q576nmx" in json["text"]
        return FakeResponse(
            {
                "handled": True,
                "should_reply": True,
                "reply": "BV1jsonCard1",
                "messages": [{"type": "text", "text": "BV1jsonCard1"}],
                "metadata": {"module": "bilibili"},
            }
        )

    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post(
        "/chat",
        json={
            "primary_type": "json",
            "message_type": "group",
            "group_id": "1",
            "json_messages": [
                {
                    "raw": json.dumps(payload, ensure_ascii=False),
                    "parsed": payload,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["reply"] == "BV1jsonCard1"
    assert body["metadata"] == {"module": "bilibili"}
    assert len(calls) == 1


def test_remote_module_down_silently_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "bilibili=http://module-bilibili:8011")

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        raise httpx.ConnectError("down")

    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post("/chat", json={"text": "https://www.bilibili.com/video/BV1xx411c7mD"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}


def test_group_blocklist_skips_remote_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "bilibili=http://module-bilibili:8011")
    monkeypatch.setenv("BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST", "8")

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        raise AssertionError("remote module should not be called")

    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post(
        "/chat",
        json={
            "text": "https://www.bilibili.com/video/BV1xx411c7mD",
            "group_id": "8",
            "message_type": "group",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}


def test_first_remote_blocked_does_not_prevent_second_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "BRAIN_MODULE_SERVICES",
        "bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012",
    )
    monkeypatch.setenv("BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST", "8")
    calls = []

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append(url)
        assert url == "http://module-tsperson:8012/handle"
        return FakeResponse(
            {
                "handled": True,
                "should_reply": True,
                "reply": "TS online",
                "messages": [{"type": "text", "text": "TS online"}],
                "metadata": {"module": "tsperson"},
            }
        )

    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post(
        "/chat",
        json={
            "text": "查询人数",
            "group_id": "8",
            "message_type": "group",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["reply"] == "TS online"
    assert calls == ["http://module-tsperson:8012/handle"]


def test_blocked_remote_does_not_claim_unrelated_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "bilibili=http://module-bilibili:8011")
    monkeypatch.setenv("BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST", "8")

    response = client.post(
        "/chat",
        json={
            "text": "hello",
            "group_id": "8",
            "message_type": "group",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}


def test_tools_aggregates_remote_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "tsperson=http://module-tsperson:8012")

    def fake_get(url: str, timeout: float) -> FakeResponse:
        assert url == "http://module-tsperson:8012/tools"
        assert timeout == 5.0
        return FakeResponse(
            [
                {
                    "name": "tsperson.get_status",
                    "description": "Get TeamSpeak status.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)

    response = client.get("/tools")

    assert response.status_code == 200
    assert [tool["name"] for tool in response.json()] == ["echo", "tsperson.get_status"]


def test_tools_call_forwards_to_remote_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "tsperson=http://module-tsperson:8012")
    calls = []

    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse(
            [
                {
                    "name": "tsperson.get_status",
                    "description": "Get TeamSpeak status.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "tool_name": "tsperson.get_status",
                "ok": True,
                "data": {"text": "2 users online"},
            }
        )

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)
    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post("/tools/call", json={"name": "tsperson.get_status", "arguments": {}})

    assert response.status_code == 200
    assert response.json() == {
        "tool_name": "tsperson.get_status",
        "ok": True,
        "data": {"text": "2 users online"},
    }
    assert calls == [
        {
            "url": "http://module-tsperson:8012/tools/call",
            "json": {"name": "tsperson.get_status", "arguments": {}},
            "timeout": 5.0,
        }
    ]


def test_tools_call_forwards_top_level_context_to_remote_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "weather=http://module-weather:8013")
    calls = []

    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse(
            [
                {
                    "name": "weather.get_live",
                    "description": "Get weather.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append(json)
        return FakeResponse({"tool_name": "weather.get_live", "ok": True, "data": {"weather": "ok"}})

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)
    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post(
        "/tools/call",
        json={
            "name": "weather.get_live",
            "arguments": {"city": "北京"},
            "message_type": "group",
            "group_id": "613689332",
            "user_id": "42",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == [
        {
            "name": "weather.get_live",
            "arguments": {"city": "北京"},
            "message_type": "group",
            "group_id": "613689332",
            "user_id": "42",
        }
    ]


def test_tools_call_applies_brain_group_policy_before_remote_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "weather=http://module-weather:8013")
    monkeypatch.setenv("BRAIN_MODULE_WEATHER_GROUP_BLOCKLIST", "613689332")

    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse(
            [
                {
                    "name": "weather.get_live",
                    "description": "Get weather.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        raise AssertionError("blocked remote tool should not be called")

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)
    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post(
        "/tools/call",
        json={
            "name": "weather.get_live",
            "arguments": {"city": "北京"},
            "message_type": "group",
            "group_id": "613689332",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "tool_name": "weather.get_live",
        "ok": False,
        "error": "group_policy_denied",
    }


def test_remote_tool_failure_returns_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "tsperson=http://module-tsperson:8012")

    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse(
            [
                {
                    "name": "tsperson.get_status",
                    "description": "Get TeamSpeak status.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)
    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post("/tools/call", json={"name": "tsperson.get_status", "arguments": {}})

    assert response.status_code == 200
    assert response.json() == {
        "tool_name": "tsperson.get_status",
        "ok": False,
        "error": "module_unavailable",
    }


def test_tools_call_does_not_route_undiscovered_prefix_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MODULE_SERVICES", "tsperson=http://module-tsperson:8012")

    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse([])

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        raise AssertionError("undiscovered remote tool should not be called")

    monkeypatch.setattr("modules.remote.httpx.get", fake_get)
    monkeypatch.setattr("modules.remote.httpx.post", fake_post)

    response = client.post("/tools/call", json={"name": "tsperson.hidden", "arguments": {}})

    assert response.status_code == 200
    assert response.json() == {
        "tool_name": "tsperson.hidden",
        "ok": False,
        "error": "unknown tool: tsperson.hidden",
    }


def _access_record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="",
        args=("127.0.0.1:1", method, path, "1.1", status),
        exc_info=None,
    )


def _json_example_payload() -> dict[str, Any]:
    example_path = Path(__file__).resolve().parents[2] / "json_example" / "group" / "json_example.json"
    event = json.loads(example_path.read_text(encoding="utf-8"))
    return json.loads(event["message"][0]["data"]["data"])


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class FakeOutboxStore:
    def __init__(self) -> None:
        self.enqueued: OutboxEnqueueRequest | None = None
        self.pull_args: tuple[int, int] | None = None
        self.acked: int | None = None
        self.failed: tuple[int, str] | None = None

    def enqueue(self, request: OutboxEnqueueRequest) -> OutboxItem:
        self.enqueued = request
        return _outbox_item(status="pending", messages=request.messages, metadata=request.metadata)

    def pull(self, limit: int, lease_seconds: int) -> list[OutboxItem]:
        self.pull_args = (limit, lease_seconds)
        return [_outbox_item(status="processing")]

    def ack(self, item_id: int) -> OutboxItem:
        self.acked = item_id
        return _outbox_item(status="sent")

    def fail(self, item_id: int, error: str) -> OutboxItem:
        self.failed = (item_id, error)
        return _outbox_item(status="pending", attempts=1, last_error=error)


def _outbox_item(
    *,
    status: str,
    messages: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    attempts: int = 0,
    last_error: str | None = None,
) -> OutboxItem:
    now = datetime.now(timezone.utc)
    return OutboxItem(
        id=42,
        message_type="group",
        group_id="8",
        messages=messages or [{"type": "text", "text": "queued"}],
        metadata=metadata or {},
        status=status,
        attempts=attempts,
        max_attempts=5,
        last_error=last_error,
        created_at=now,
        updated_at=now,
    )
