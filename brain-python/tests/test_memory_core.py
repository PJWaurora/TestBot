from __future__ import annotations

from typing import Any

import pytest

from schemas import BrainSender, ChatRequest
from services import memory, persistence
from services.memory import MemoryError, MemoryRecord


class FakeMemoryStore:
    def __init__(self) -> None:
        self.enabled = True
        self.active_count = 3
        self.group_enabled = True
        self.records = [
            MemoryRecord(
                id=9,
                scope="group",
                memory_type="fact",
                content="用户喜欢南京天气。",
                confidence=0.8,
                importance=0.7,
                group_id="200",
                user_id="100",
            )
        ]
        self.group_checks: list[str] = []
        self.count_calls: list[str] = []
        self.search_calls: list[tuple[str, str, str, int]] = []
        self.list_user_calls: list[tuple[str, str, int]] = []
        self.set_group_calls: list[tuple[str, bool]] = []
        self.deleted_memory_ids: list[tuple[int, str, bool]] = []
        self.deleted_users: list[tuple[str, str]] = []
        self.deleted_groups: list[str] = []

    def group_memory_enabled(self, group_id: str) -> bool:
        self.group_checks.append(group_id)
        return self.group_enabled

    def set_group_memory_enabled(self, group_id: str, enabled: bool) -> None:
        self.set_group_calls.append((group_id, enabled))
        self.group_enabled = enabled

    def count_active(self, group_id: str) -> int:
        self.count_calls.append(group_id)
        return self.active_count

    def search(self, query: str, *, group_id: str = "", user_id: str = "", limit: int = 10) -> list[MemoryRecord]:
        self.search_calls.append((query, group_id, user_id, limit))
        return self.records

    def recall(self, request: ChatRequest, text: str, *, limit: int = memory.DEFAULT_MEMORY_LIMIT) -> list[MemoryRecord]:
        return self.records[:limit]

    def recent_messages(self, request: ChatRequest, *, limit: int = memory.DEFAULT_RECENT_LIMIT) -> list[dict[str, Any]]:
        return [
            {
                "sender_user_id": "100",
                "sender_nickname": "Alice",
                "sender_card": "",
                "text": "南京今天下雨吗",
                "primary_type": "text",
                "created_at": None,
            }
        ][:limit]

    def list_user(self, group_id: str, user_id: str, *, limit: int = 20) -> list[MemoryRecord]:
        self.list_user_calls.append((group_id, user_id, limit))
        return self.records

    def delete_memory(self, memory_id: int, *, group_id: str = "", allow_global: bool = False) -> bool:
        self.deleted_memory_ids.append((memory_id, group_id, allow_global))
        return memory_id == 9

    def delete_user(self, group_id: str, user_id: str) -> int:
        self.deleted_users.append((group_id, user_id))
        return 2

    def delete_group(self, group_id: str) -> int:
        self.deleted_groups.append(group_id)
        return 5


@pytest.fixture(autouse=True)
def clear_memory_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("MEMORY_ENABLED", raising=False)


def test_handle_memory_command_ignores_non_memory_text() -> None:
    assert memory.handle_memory_command(_request(role="owner"), "hello") is None


def test_memory_admin_command_denies_non_admin_before_store_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        memory.PostgresMemoryStore,
        "from_env",
        staticmethod(lambda: pytest.fail("store should not be loaded for non-admin requests")),
    )

    response = memory.handle_memory_command(_request(role="member"), "/memory status")

    assert response is not None
    assert response.handled is True
    assert response.should_reply is True
    assert response.metadata == {"module": "memory", "error": "permission_denied"}
    assert response.messages[0].text == "需要管理员权限。"


def test_memory_status_uses_admin_role_and_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    store.group_enabled = False
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="owner"), "/memory status")

    assert response is not None
    assert "记忆状态：禁用" in response.reply
    assert response.metadata == {
        "module": "memory",
        "command": "status",
        "count": 3,
        "enabled": False,
    }
    assert store.count_calls == ["200"]
    assert store.group_checks == ["200"]


def test_memory_admin_can_be_configured_by_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    monkeypatch.setenv("MEMORY_ADMIN_USER_IDS", "100, 999")

    response = memory.handle_memory_command(_request(role="member"), "/memory search 南京")

    assert response is not None
    assert "#9 [group/fact]" in response.reply
    assert "用户喜欢南京天气。" in response.reply
    assert store.search_calls == [("南京", "200", "100", 10)]


def test_memory_enable_disable_requires_group_and_updates_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory disable")

    assert response is not None
    assert response.reply == "群记忆已禁用。"
    assert response.metadata == {"module": "memory", "command": "disable", "enabled": False}
    assert store.set_group_calls == [("200", False)]

    private_response = memory.handle_memory_command(
        _request(role="admin", group_id=None, message_type="private"),
        "/memory enable",
    )

    assert private_response is not None
    assert private_response.metadata == {"module": "memory", "error": "group_required"}
    assert store.set_group_calls == [("200", False)]


def test_memory_destructive_group_commands_require_group(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    request = _request(role="admin", group_id=None, message_type="private")

    for command in ("/memory user 100", "/memory forget-user 100", "/memory forget-group"):
        response = memory.handle_memory_command(request, command)
        assert response is not None
        assert response.metadata == {"module": "memory", "error": "group_required"}

    assert store.list_user_calls == []
    assert store.deleted_users == []
    assert store.deleted_groups == []


def test_memory_delete_commands_call_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    request = _request(role="admin")

    forget_response = memory.handle_memory_command(request, "/memory forget 9")
    forget_user_response = memory.handle_memory_command(request, "/memory forget-user 100")
    forget_group_response = memory.handle_memory_command(request, "/memory forget-group")

    assert forget_response is not None
    assert forget_response.metadata == {"module": "memory", "command": "forget", "deleted": True}
    assert forget_user_response is not None
    assert forget_user_response.metadata == {"module": "memory", "command": "forget-user", "count": 2}
    assert forget_group_response is not None
    assert forget_group_response.metadata == {"module": "memory", "command": "forget-group", "count": 5}
    assert store.deleted_memory_ids == [(9, "200", False)]
    assert store.deleted_users == [("200", "100")]
    assert store.deleted_groups == ["200"]


def test_memory_forget_configured_admin_can_delete_globally(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    monkeypatch.setenv("MEMORY_ADMIN_USER_IDS", "100")

    response = memory.handle_memory_command(
        _request(role="member", group_id=None, message_type="private"),
        "/memory forget 9",
    )

    assert response is not None
    assert response.metadata == {"module": "memory", "command": "forget", "deleted": True}
    assert store.deleted_memory_ids == [(9, "", True)]


def test_memory_search_and_recall_scope_user_memories_to_current_group(monkeypatch: pytest.MonkeyPatch) -> None:
    store = memory.PostgresMemoryStore("postgres://example")
    captured: list[tuple[str, tuple[Any, ...]]] = []

    def fake_fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        return []

    monkeypatch.setattr(store, "_fetch_all", fake_fetch_all)

    store.search("南京", group_id="group-b", user_id="same-user")
    store.recall(ChatRequest(text="南京", group_id="group-b", user_id="same-user"), "南京")

    for sql, params in captured:
        assert "scope = 'user' AND group_id" in sql
        assert "scope = 'relationship'" in sql
        assert "target_user_id" in sql
        assert "OR (%s <> '' AND user_id = %s)" not in sql
        assert "group-b" in params
        assert "same-user" in params


def test_memory_command_reports_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    store.enabled = False
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory status")

    assert response is not None
    assert response.metadata == {"module": "memory", "error": "missing_database_url"}
    assert response.reply == "记忆数据库未配置 DATABASE_URL。"


def test_recall_context_returns_empty_when_disabled_before_store_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setattr(
        memory.PostgresMemoryStore,
        "from_env",
        staticmethod(lambda: pytest.fail("store should not be loaded when memory is disabled")),
    )

    assert memory.recall_context(_request(role="member"), "南京天气") == {"memories": [], "recent_messages": []}


def test_recall_context_catches_group_setting_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingStore(FakeMemoryStore):
        def group_memory_enabled(self, group_id: str) -> bool:
            raise MemoryError("settings failed")

    _install_store(monkeypatch, FailingStore())

    assert memory.recall_context(_request(role="member"), "南京天气") == {"memories": [], "recent_messages": []}


def test_recall_context_formats_memories_and_recent_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    context = memory.recall_context(_request(role="member"), "南京天气")

    assert context["memories"] == [
        {
            "id": 9,
            "scope": "group",
            "memory_type": "fact",
            "content": "用户喜欢南京天气。",
            "confidence": 0.8,
            "importance": 0.7,
            "group_id": "200",
            "user_id": "100",
            "target_user_id": "",
        }
    ]
    assert context["recent_messages"] == [
        {
            "sender": "Alice",
            "user_id": "100",
            "text": "南京今天下雨吗",
            "primary_type": "text",
            "created_at": "",
        }
    ]


def test_persist_incoming_falls_back_to_request_user_id_when_sender_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = persistence.PostgresChatStore("postgres://example")
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(persistence, "_jsonb", lambda value: value)

    def fake_fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        captured.append(params)
        return [{"id": 123}]

    monkeypatch.setattr(store, "_fetch_all", fake_fetch_all)
    request = ChatRequest(
        text="hello",
        content="hello",
        message_type="group",
        group_id="200",
        user_id="100",
        sender=BrainSender(nickname="Alice", card="A", role="member"),
    )

    assert store.persist_incoming(request) == 123
    assert captured[0][15] == "100"
    assert captured[0][16:19] == ("Alice", "A", "member")


def test_safe_persistence_wrappers_do_not_raise_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenStore:
        def persist_incoming(self, request: ChatRequest) -> int | None:
            raise RuntimeError("boom")

        def persist_response(self, message_id: int | None, response: Any) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(persistence.PostgresChatStore, "from_env", staticmethod(lambda: BrokenStore()))

    assert persistence.safe_persist_incoming(_request(role="member")) is None
    persistence.safe_persist_response(1, memory._text_response("ok", {"module": "test"}))


def _install_store(monkeypatch: pytest.MonkeyPatch, store: FakeMemoryStore) -> None:
    monkeypatch.setattr(memory.PostgresMemoryStore, "from_env", staticmethod(lambda: store))


def _request(
    *,
    role: str,
    user_id: str = "100",
    group_id: str | None = "200",
    message_type: str = "group",
) -> ChatRequest:
    return ChatRequest(
        text="/memory status",
        user_id=user_id,
        group_id=group_id,
        message_type=message_type,
        sender=BrainSender(user_id=user_id, nickname="Alice", card="A", role=role),
    )
