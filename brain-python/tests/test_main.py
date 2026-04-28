import logging

from fastapi.testclient import TestClient

from main import QuietAccessLogFilter, app
from modules.tsperson import ChannelInfo, ClientInfo, ServerStatus, TSPersonModule, format_duration


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_access_log_filter_silences_successful_health_and_chat() -> None:
    access_filter = QuietAccessLogFilter()

    assert access_filter.filter(_access_record("GET", "/health", 200)) is False
    assert access_filter.filter(_access_record("POST", "/chat", 200)) is False
    assert access_filter.filter(_access_record("POST", "/chat", 500)) is True


def test_chat_silences_plain_text_without_route() -> None:
    response = client.post("/chat", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert body["metadata"] == {"reason": "no_route"}
    assert "messages" not in body


def test_chat_does_not_reply_to_empty_text() -> None:
    response = client.post("/chat", json={"text": "   "})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["should_reply"] is False
    assert "messages" not in body


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


def test_tools_are_listed() -> None:
    response = client.get("/tools")

    assert response.status_code == 200
    tools = response.json()
    assert tools[0]["name"] == "echo"
    assert "input_schema" in tools[0]


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


def test_chat_deterministic_command_routes_tool_result_through_presenter() -> None:
    response = client.post("/chat", json={"text": "/tool-echo runtime"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["reply"] == "runtime"
    assert body["messages"] == [{"type": "text", "text": "runtime"}]
    assert "tool_calls" not in body
    assert "metadata" not in body


def test_deterministic_command_accepts_dot_prefix() -> None:
    response = client.post("/chat", json={"text": ".tool-echo runtime"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["reply"] == "runtime"


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


def test_fake_planner_accepts_dot_prefix() -> None:
    response = client.post("/chat", json={"text": ".echo runtime"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["reply"] == "runtime"
    assert body["tool_calls"] == [{"name": "echo", "arguments": {"text": "runtime"}}]


def test_bilibili_link_auto_detects_video() -> None:
    response = client.post("/chat", json={"text": "看看 https://www.bilibili.com/video/BV1xx411c7mD"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "BV1xx411c7mD" in body["reply"]
    assert "https://www.bilibili.com/video/BV1xx411c7mD" in body["reply"]


def test_bilibili_command_accepts_dot_prefix() -> None:
    response = client.post("/chat", json={"text": ".bili BV1xx411c7mD"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "BV1xx411c7mD" in body["reply"]


def test_bilibili_command_without_argument_returns_help() -> None:
    response = client.post("/chat", json={"text": "/bili"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert ".bili" in body["reply"]
    assert "b23.tv" in body["reply"]


def test_bilibili_short_link_is_detected_without_network_resolution() -> None:
    response = client.post("/chat", json={"text": "https://b23.tv/abc123"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "b23.tv/abc123" in body["reply"]
    assert "resolution disabled" in body["reply"]


class FakeTSProvider:
    def get_status(self) -> ServerStatus:
        return ServerStatus(
            name="Test TS",
            platform="Linux",
            version="3.13",
            clients_online=2,
            max_clients=32,
            channels_online=3,
            uptime=93780,
            clients=[
                ClientInfo(nickname="Alice", channel_id=1),
                ClientInfo(nickname="Bob", channel_id=2),
            ],
            channels=[ChannelInfo(channel_id=1, name="Lobby", total_clients=2)],
        )


def test_tsperson_module_presents_status_from_provider() -> None:
    module = TSPersonModule(provider=FakeTSProvider())

    response = module.present(module.call(module.parse("ts状态")))

    assert response.handled is True
    assert response.should_reply is True
    assert "TS 服务器：Test TS" in response.reply
    assert "在线人数：2/32" in response.reply
    assert "在线用户：Alice、Bob" in response.reply
    assert response.metadata == {
        "module": "tsperson",
        "tool_name": "tsperson.get_status",
        "ok": True,
    }


def test_tsperson_command_routes_without_fake_planner_when_unconfigured(monkeypatch) -> None:
    for key in (
        "TS3_HOST",
        "TSPERSON_HOST",
        "TS3_QUERY_USER",
        "TSPERSON_QUERY_USER",
        "TS3_QUERY_PASSWORD",
        "TSPERSON_QUERY_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    response = client.post("/chat", json={"text": "查询人数"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["metadata"]["module"] == "tsperson"
    assert body["metadata"]["error"] == "missing_config"
    assert "TS ServerQuery 配置不完整" in body["reply"]
    assert "tool_calls" not in body


def test_tsperson_help_command() -> None:
    response = client.post("/chat", json={"text": "ts帮助"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "查询人数" in body["reply"]


def test_tsperson_help_command_accepts_dot_prefix() -> None:
    response = client.post("/chat", json={"text": ".ts帮助"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "查询人数" in body["reply"]


def test_module_group_blocklist_silences_matching_module(monkeypatch) -> None:
    monkeypatch.setenv("TSPERSON_GROUP_BLOCKLIST", "8")

    response = client.post("/chat", json={"text": "查询人数", "group_id": "8", "message_type": "group"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is False
    assert body["metadata"] == {
        "module": "tsperson",
        "group_policy": "blocked",
        "group_id": "8",
    }


def test_module_group_allowlist_silences_groups_not_in_list(monkeypatch) -> None:
    monkeypatch.setenv("TSPERSON_GROUP_ALLOWLIST", "9")

    response = client.post("/chat", json={"text": "查询人数", "group_id": "8", "message_type": "group"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is False
    assert body["metadata"]["group_policy"] == "blocked"


def test_module_group_allowlist_does_not_block_private_messages(monkeypatch) -> None:
    monkeypatch.setenv("TSPERSON_GROUP_ALLOWLIST", "9")
    for key in (
        "TS3_HOST",
        "TSPERSON_HOST",
        "TS3_QUERY_USER",
        "TSPERSON_QUERY_USER",
        "TS3_QUERY_PASSWORD",
        "TSPERSON_QUERY_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    response = client.post("/chat", json={"text": "查询人数", "message_type": "private"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["metadata"]["module"] == "tsperson"
    assert body["metadata"]["error"] == "missing_config"


def test_module_policy_uses_context_from_selected_message(monkeypatch) -> None:
    monkeypatch.setenv("TSPERSON_GROUP_ALLOWLIST", "9")

    response = client.post(
        "/chat",
        json={
            "group_id": "9",
            "message_type": "group",
            "messages": [
                {"text": "older", "group_id": "9", "message_type": "group"},
                {"text": "ts帮助", "group_id": "8", "message_type": "group"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is False
    assert body["metadata"] == {
        "module": "tsperson",
        "group_policy": "blocked",
        "group_id": "8",
    }


def test_tsperson_tool_is_listed_and_callable_when_unconfigured(monkeypatch) -> None:
    for key in (
        "TS3_HOST",
        "TSPERSON_HOST",
        "TS3_QUERY_USER",
        "TSPERSON_QUERY_USER",
        "TS3_QUERY_PASSWORD",
        "TSPERSON_QUERY_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    tools_response = client.get("/tools")
    tool_names = [tool["name"] for tool in tools_response.json()]
    assert "tsperson.get_status" in tool_names

    call_response = client.post("/tools/call", json={"name": "tsperson.get_status", "arguments": {}})

    assert call_response.status_code == 200
    body = call_response.json()
    assert body["tool_name"] == "tsperson.get_status"
    assert body["ok"] is False
    assert body["error"] == "missing_config"


def test_tsperson_format_duration() -> None:
    assert format_duration(59) == "59秒"
    assert format_duration(3600) == "1小时"
    assert format_duration(90000) == "1天1小时"


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
