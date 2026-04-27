from fastapi.testclient import TestClient

from main import app
from modules.registry import DeterministicModuleRegistry
from modules.summary import SummaryModule
from schemas import BrainResponse, ChatRequest
from services.chat import reset_chat_repository, set_chat_repository


client = TestClient(app)


class FakeSummarySource:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.calls: list[dict[str, object]] = []

    def recent_group_messages(self, *, group_id: str | int | None = None, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append({"group_id": group_id, "limit": limit})
        return self.messages[-limit:]


class FakeChatRepository:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def save_request(self, request: ChatRequest) -> int:
        self.events.append(("request", request.text))
        return 7

    def save_response(self, message_id: int, response: BrainResponse) -> None:
        self.events.append(("response", message_id, response.reply))


class FailingChatRepository:
    def save_request(self, request: ChatRequest) -> int:
        raise RuntimeError("database unavailable")

    def save_response(self, message_id: int, response: BrainResponse) -> None:
        raise AssertionError("response should not persist without a saved message")


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


def test_chat_persists_request_and_response_when_repository_is_available() -> None:
    repository = FakeChatRepository()
    set_chat_repository(repository)
    try:
        response = client.post("/chat", json={"text": "persist me"})
    finally:
        reset_chat_repository()

    assert response.status_code == 200
    assert response.json()["reply"] == "收到：persist me"
    assert repository.events == [
        ("request", "persist me"),
        ("response", 7, "收到：persist me"),
    ]


def test_chat_still_replies_when_persistence_fails() -> None:
    set_chat_repository(FailingChatRepository())
    try:
        response = client.post("/chat", json={"text": "hello"})
    finally:
        reset_chat_repository()

    assert response.status_code == 200
    assert response.json()["reply"] == "收到：hello"


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


def test_summary_module_summarizes_in_memory_group_messages() -> None:
    source = FakeSummarySource(
        [
            {"user_name": "Alice", "message_content": "deploy release release"},
            {"user_name": "Bob", "message_content": "deploy plan"},
            {"user_name": "Alice", "message_content": "release notes"},
        ]
    )
    module = SummaryModule(message_source=source)

    response = module.present(module.call(module.parse("总结 3")))

    assert source.calls == [{"group_id": None, "limit": 3}]
    assert response.handled is True
    assert response.should_reply is True
    assert "聊天总结（最近 3 条）" in response.reply
    assert "总消息数：3" in response.reply
    assert "活跃用户：2人（Alice(2), Bob(1)）" in response.reply
    assert "高频词：release(3), deploy(2)" in response.reply
    assert response.metadata == {
        "module": "summary",
        "tool_name": "summary.recent_group_messages",
        "ok": True,
        "limit": 3,
        "total_messages": 3,
    }


def test_summary_registry_passes_group_context_to_module() -> None:
    source = FakeSummarySource(
        [
            {"user_name": "Alice", "message_content": "server status"},
            {"user_name": "Bob", "message_content": "server deploy"},
        ]
    )
    registry = DeterministicModuleRegistry([SummaryModule(message_source=source)])

    response = registry.handle(
        "总结 2",
        context=ChatRequest(text="总结 2", group_id="10001"),
    )

    assert response is not None
    assert source.calls == [{"group_id": "10001", "limit": 2}]
    assert response.metadata["group_id"] == "10001"
    assert "总消息数：2" in response.reply


def test_summary_module_rejects_invalid_limit_without_calling_source() -> None:
    source = FakeSummarySource([{"user_name": "Alice", "message_content": "hello"}])
    module = SummaryModule(message_source=source)

    response = module.present(module.call(module.parse("总结 nope")))

    assert source.calls == []
    assert response.reply == "用法：总结 或 总结 N（N 为要统计的最近消息条数）"
    assert response.metadata["error"] == "invalid_limit"


def test_summary_command_routes_without_fake_planner() -> None:
    response = client.post("/chat", json={"text": "总结"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert body["metadata"]["module"] == "summary"
    assert body["metadata"]["tool_name"] == "summary.recent_group_messages"
    assert "tool_calls" not in body


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


def test_weather_command_routes_without_fake_planner() -> None:
    response = client.post("/chat", json={"text": "南京天气"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["should_reply"] is True
    assert "南京天气预报" in body["reply"]
    assert "metadata" in body
    assert body["metadata"]["tool_name"] == "weather.get_forecast"
    assert body["metadata"]["city"] == "南京"
    assert "tool_calls" not in body


def test_weather_natural_language_still_falls_back_for_later_ai_planner() -> None:
    response = client.post("/chat", json={"text": "明天南京适合出门吗"})

    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is True
    assert body["reply"] == "收到：明天南京适合出门吗"


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
