from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_replies_to_text() -> None:
    response = client.post("/chat", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["reply"] == "收到：hello"
    assert body["messages"] == [{"type": "text", "text": "收到：hello"}]


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
    assert body["handled"] is True
    assert body["reply"] == "收到：hello from envelope"
    assert body["messages"][0]["text"] == "收到：hello from envelope"


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
    assert body["reply"] == "收到：latest"
    assert body["messages"][0]["text"] == "收到：latest"


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


def test_bilibili_link_auto_detects_video() -> None:
    response = client.post("/chat", json={"text": "看看 https://www.bilibili.com/video/BV1xx411c7mD"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "BV1xx411c7mD" in body["reply"]
    assert "https://www.bilibili.com/video/BV1xx411c7mD" in body["reply"]


def test_bilibili_short_link_is_detected_without_network_resolution() -> None:
    response = client.post("/chat", json={"text": "https://b23.tv/abc123"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert "b23.tv/abc123" in body["reply"]
    assert "resolution disabled" in body["reply"]
