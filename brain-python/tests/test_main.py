from fastapi.testclient import TestClient

from main import app
from modules.registry import DeterministicModuleRegistry
from modules.summary import SummaryModule
from schemas import BrainResponse, ChatRequest
from services.chat import reset_chat_repository, set_chat_repository
from services.outbox import PostgresOutboxRepository, reset_outbox_repository, set_outbox_repository
from services.persistence import PostgresChatRepository, _conversation_key, _request_metadata, _request_text


client = TestClient(app)


class FakeSummarySource:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.calls: list[dict[str, object]] = []

    def recent_group_messages(self, *, group_id: str | int | None = None, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append({"group_id": group_id, "limit": limit})
        return self.messages[-limit:]


class ExcludingSummarySource:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.calls: list[dict[str, object]] = []

    def recent_group_messages(
        self,
        *,
        group_id: str | int | None = None,
        limit: int = 50,
        exclude_message_id: int | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append({"group_id": group_id, "limit": limit, "exclude_message_id": exclude_message_id})
        return [
            message
            for message in self.messages[-limit:]
            if message.get("id") != exclude_message_id
        ]


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


class CapturingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._ids = iter([101, 102, 103])

    def __enter__(self) -> "CapturingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> list[int]:
        return [next(self._ids)]


class CapturingConnection:
    def __init__(self, cursor: CapturingCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "CapturingConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> CapturingCursor:
        return self._cursor


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.pulled_limits: list[int] = []
        self.acks: list[dict[str, object]] = []

    def enqueue(
        self,
        *,
        target_type: str,
        target_id: str,
        messages: list[dict[str, object]],
        actions: list[dict[str, object]] | None = None,
        available_at: object | None = None,
    ) -> int:
        return 123

    def pull(self, *, limit: int = 10) -> list[dict[str, object]]:
        self.pulled_limits.append(limit)
        return [
            {
                "id": 123,
                "target_type": "group",
                "target_id": "10001",
                "messages": [{"type": "text", "text": "hello"}],
                "actions": [{"type": "ignored-by-api-contract"}],
            }
        ]

    def ack(self, *, ids: list[int], success: bool, error: str | None = None) -> int:
        self.acks.append({"ids": ids, "success": success, "error": error})
        return len(ids)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_outbox_pull_returns_items_from_repository() -> None:
    repository = FakeOutboxRepository()
    set_outbox_repository(repository)
    try:
        response = client.get("/outbox/pull?limit=5")
    finally:
        reset_outbox_repository()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 123,
            "target_type": "group",
            "target_id": "10001",
            "messages": [{"type": "text", "text": "hello"}],
        }
    ]
    assert repository.pulled_limits == [5]


def test_outbox_ack_passes_success_to_repository() -> None:
    repository = FakeOutboxRepository()
    set_outbox_repository(repository)
    try:
        response = client.post("/outbox/ack", json={"ids": [123], "success": True})
    finally:
        reset_outbox_repository()

    assert response.status_code == 200
    assert response.json() == {"acked": 1}
    assert repository.acks == [{"ids": [123], "success": True, "error": None}]


def test_outbox_ack_passes_failure_error_to_repository() -> None:
    repository = FakeOutboxRepository()
    set_outbox_repository(repository)
    try:
        response = client.post(
            "/outbox/ack",
            json={"ids": [123, 124], "success": False, "error": "send failed"},
        )
    finally:
        reset_outbox_repository()

    assert response.status_code == 200
    assert response.json() == {"acked": 2}
    assert repository.acks == [
        {"ids": [123, 124], "success": False, "error": "send failed"}
    ]


def test_outbox_no_repository_returns_empty_pull_and_unacked_ack() -> None:
    set_outbox_repository(None)
    try:
        pull_response = client.get("/outbox/pull")
        ack_response = client.post("/outbox/ack", json={"ids": [123], "success": True})
    finally:
        reset_outbox_repository()

    assert pull_response.status_code == 200
    assert pull_response.json() == []
    assert ack_response.status_code == 503
    assert ack_response.json()["detail"] == {
        "error": "outbox_ack_incomplete",
        "acked": 0,
        "expected": 1,
    }


class RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 1

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return []


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.cursor_instance = cursor

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance


class RecordingPostgresOutboxRepository(PostgresOutboxRepository):
    def __init__(self, *args: object, cursor: RecordingCursor, **kwargs: object) -> None:
        super().__init__("postgresql://example", *args, **kwargs)
        self.cursor_instance = cursor

    def _connect(self, **kwargs: object) -> RecordingConnection:
        return RecordingConnection(self.cursor_instance)


def test_postgres_outbox_pull_uses_configured_lease_seconds() -> None:
    cursor = RecordingCursor()
    repository = RecordingPostgresOutboxRepository(cursor=cursor, lease_seconds=600)

    assert repository.pull(limit=250) == []

    sql, params = cursor.executions[0]
    assert "interval '1 minute'" not in sql
    assert "locked_at < now() - (%s * interval '1 second')" in sql
    assert params == (600, 100)


def test_postgres_outbox_failure_ack_backs_off_and_marks_terminal_failure() -> None:
    cursor = RecordingCursor()
    repository = RecordingPostgresOutboxRepository(
        cursor=cursor,
        max_attempts=3,
        initial_backoff_seconds=10,
        max_backoff_seconds=40,
    )

    assert repository.ack(ids=[123], success=False, error="send failed") == 1

    sql, params = cursor.executions[0]
    assert "WHEN attempt_count + 1 >= %s THEN 'failed'" in sql
    assert "available_at = CASE" in sql
    assert "status NOT IN ('sent', 'failed')" in sql
    assert params == (3, 3, 10, 40, "send failed", [123])


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


def test_chat_accepts_gateway_envelope_fields() -> None:
    response = client.post(
        "/chat",
        json={
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "primary_type": "text",
            "message_id": "9001",
            "message_seq": "42",
            "real_id": "43",
            "real_seq": "44",
            "user_id": "100",
            "group_id": "200",
            "group_name": "Ops",
            "target_id": "300",
            "sender": {"user_id": "100", "nickname": "Alice", "card": "A", "role": "member"},
            "text_segments": ["hello", " gateway"],
            "images": [{"url": "https://example.test/a.png"}],
            "json_messages": [{"raw": "{\"ok\": true}", "parsed": {"ok": True}}],
            "videos": [{"url": "https://example.test/a.mp4"}],
            "at_user_ids": ["101"],
            "at_all": True,
            "reply_to_message_id": "8000",
            "unknown_types": ["face"],
            "segments": [{"type": "text", "data": {"text": "hello gateway"}}],
            "raw_message": "hello gateway",
            "time": 1710000000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "收到：hello gateway"


def test_persistence_metadata_uses_top_level_gateway_envelope_fields() -> None:
    request = ChatRequest(
        text="top text",
        post_type="message",
        message_type="group",
        sub_type="normal",
        primary_type="text",
        message_id="9001",
        message_seq="42",
        real_id="43",
        real_seq="44",
        user_id="100",
        group_id="200",
        group_name="Ops",
        target_id="300",
        sender={"user_id": "100", "nickname": "Alice", "card": "A", "role": "member"},
        text_segments=["top", " text"],
        images=[{"url": "https://example.test/a.png"}],
        json_messages=[{"raw": "{\"ok\": true}", "parsed": {"ok": True}}],
        videos=[{"url": "https://example.test/a.mp4"}],
        at_user_ids=["101"],
        at_all=True,
        reply_to_message_id="8000",
        unknown_types=["face"],
        segments=[{"type": "text", "data": {"text": "top text"}}],
        raw_message="raw top text",
        time=1710000000,
        metadata={"primary_type": "legacy", "sender": {"user_id": "old"}, "group_name": "Old"},
    )

    metadata = _request_metadata(request, None)

    assert metadata["primary_type"] == "text"
    assert metadata["sender"]["nickname"] == "Alice"
    assert metadata["group_name"] == "Ops"
    assert metadata["segments"] == [{"type": "text", "data": {"text": "top text"}}]
    assert metadata["at_all"] is True
    assert _conversation_key(request, None) == ("group", "200")
    assert _request_text(request, None) == "top text"


def test_postgres_persistence_writes_top_level_gateway_fields() -> None:
    request = ChatRequest(
        text="top text",
        post_type="message",
        message_type="group",
        sub_type="normal",
        primary_type="text",
        message_id="9001",
        message_seq="42",
        real_id="43",
        real_seq="44",
        user_id="100",
        group_id="200",
        group_name="Ops",
        sender={"user_id": "100", "nickname": "Alice", "card": "A", "role": "member"},
        segments=[{"type": "text", "data": {"text": "top text"}}],
        raw_message="raw top text",
        time=1710000000,
        metadata={"group_name": "Old", "primary_type": "legacy", "sender": {"user_id": "old"}},
    )
    cursor = CapturingCursor()
    repository = PostgresChatRepository("postgresql://unused")
    repository._connect = lambda **_: CapturingConnection(cursor)  # type: ignore[method-assign]

    saved_id = repository.save_request(request)

    conversation_params = cursor.calls[0][1]
    raw_params = cursor.calls[1][1]
    message_params = cursor.calls[2][1]
    assert saved_id == 103
    assert conversation_params == ("group", "200", "Ops")
    assert raw_params[:3] == ("9001", "message", "group")
    assert message_params[2:12] == (
        "9001",
        "42",
        "43",
        "44",
        "message",
        "group",
        "normal",
        "text",
        "top text",
        "raw top text",
    )
    assert message_params[12].obj == request.segments
    assert message_params[13:17] == ("100", "Alice", "A", "member")
    assert message_params[17].isoformat() == "2024-03-09T16:00:00+00:00"


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


def test_summary_registry_excludes_current_saved_message() -> None:
    source = ExcludingSummarySource(
        [
            {"id": 10, "user_name": "Alice", "message_content": "deploy release"},
            {"id": 11, "user_name": "Bob", "message_content": "server status"},
            {"id": 12, "user_name": "Caller", "message_content": "总结 2"},
        ]
    )
    registry = DeterministicModuleRegistry([SummaryModule(message_source=source)])
    context = ChatRequest(text="总结 2", group_id="10001", saved_message_id=12)

    response = registry.handle("总结 2", context=context)

    assert response is not None
    assert source.calls == [{"group_id": "10001", "limit": 3, "exclude_message_id": 12}]
    assert "总消息数：2" in response.reply
    assert "Caller" not in response.reply


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
