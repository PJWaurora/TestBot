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
        self.search_status_calls: list[str] = []
        self.list_user_calls: list[tuple[str, str, int]] = []
        self.set_group_calls: list[tuple[str, bool]] = []
        self.extract_calls: list[tuple[str, int | None]] = []
        self.deleted_memory_ids: list[tuple[int, str, bool]] = []
        self.deleted_users: list[tuple[str, str]] = []
        self.deleted_groups: list[str] = []
        self.get_calls: list[tuple[int, str, bool]] = []
        self.lifecycle_actions: list[tuple[str, Any]] = []
        self.lifecycle_counts_result = {
            "weak": 1,
            "confirmed": 2,
            "reinforced": 0,
            "stale": 0,
            "contradicted": 0,
            "archived": 0,
        }

    def group_memory_enabled(self, group_id: str) -> bool:
        self.group_checks.append(group_id)
        return self.group_enabled

    def set_group_memory_enabled(self, group_id: str, enabled: bool) -> None:
        self.set_group_calls.append((group_id, enabled))
        self.group_enabled = enabled

    def count_active(self, group_id: str) -> int:
        self.count_calls.append(group_id)
        return self.active_count

    def search(
        self,
        query: str,
        *,
        group_id: str = "",
        user_id: str = "",
        limit: int = 10,
        status: str = "active",
    ) -> list[MemoryRecord]:
        self.search_calls.append((query, group_id, user_id, limit))
        self.search_status_calls.append(status)
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

    def get_memory(self, memory_id: int, *, group_id: str = "", allow_global: bool = False) -> MemoryRecord | None:
        self.get_calls.append((memory_id, group_id, allow_global))
        return self.records[0] if memory_id == 9 else None

    def lifecycle_counts(self, group_id: str = "") -> dict[str, int]:
        self.lifecycle_actions.append(("status", group_id))
        return self.lifecycle_counts_result

    def confirm_memory(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        self.lifecycle_actions.append(("confirm", memory_id, group_id, allow_global, actor_id))
        return memory_id == 9

    def archive_memory(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        self.lifecycle_actions.append(("archive", memory_id, group_id, allow_global, actor_id))
        return memory_id == 9

    def mark_stale(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        self.lifecycle_actions.append(("stale", memory_id, group_id, allow_global, actor_id))
        return memory_id == 9

    def apply_decay(self, *, group_id: str = "", days: int = 0, limit: int = 500) -> dict[str, int]:
        self.lifecycle_actions.append(("decay", group_id, days, limit))
        return {"scanned": 3, "stale": 1, "archived": 1}

    def debug_recall(
        self,
        request: ChatRequest,
        text: str,
        *,
        limit: int = 10,
        include_ineligible: bool = True,
    ) -> list[tuple[MemoryRecord, memory.MemoryScore]]:
        self.lifecycle_actions.append(("debug_recall", text, limit, include_ineligible))
        return [
            (
                self.records[0],
                memory.MemoryScore(
                    total=0.81,
                    keyword_match=1.0,
                    entity_relevance=0.9,
                    scope_relevance=0.75,
                    quality_score=0.5,
                    recency_weight=0.5,
                ),
            )
        ]

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
    monkeypatch.delenv("MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED", raising=False)
    monkeypatch.delenv("MEMORY_EXTRACTOR_ENABLED", raising=False)


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
    assert "#9 [group/fact/confirmed]" in response.reply
    assert "用户喜欢南京天气。" in response.reply
    assert store.search_calls == [("南京", "200", "100", 10)]
    assert store.search_status_calls == ["active"]


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


def test_memory_extract_requires_group(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(
        _request(role="admin", group_id=None, message_type="private"),
        "/memory extract",
    )

    assert response is not None
    assert response.reply == "只有群聊可以抽取记忆。"
    assert response.metadata == {"module": "memory", "error": "group_required"}


def test_memory_extract_reports_disabled_extractor_without_calling_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory extract")

    assert response is not None
    assert response.metadata == {"module": "memory", "command": "extract", "error": "configuration"}
    assert "MEMORY_EXTRACTOR_ENABLED" in response.reply


def test_memory_extract_respects_group_disabled_before_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    store.group_enabled = False
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory extract 100")

    assert response is not None
    assert response.reply == "当前群记忆已禁用。"
    assert response.metadata == {"module": "memory", "command": "extract", "error": "group_disabled"}
    assert store.group_checks == ["200"]


def test_memory_extract_calls_extractor_with_optional_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    started_threads: list[FakeThread] = []

    class FakeThread:
        def __init__(self, *, target: Any, args: tuple[Any, ...], daemon: bool, name: str) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            store.extract_calls.append((self.args[0], self.args[1]))

    from services import memory_extractor

    monkeypatch.setenv("MEMORY_EXTRACTOR_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EXTRACTOR_BASE_URL", "https://llm.example")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MODEL", "memory-model")
    monkeypatch.setattr(
        memory.threading,
        "Thread",
        lambda **kwargs: started_threads.append(FakeThread(**kwargs)) or started_threads[-1],
    )

    response = memory.handle_memory_command(_request(role="admin"), "/记忆 extract 100")

    assert response is not None
    assert response.reply == "记忆抽取已开始，正在处理当前群最近 100 条文本消息。完成后会在群里通知。"
    assert response.job_id == "memory-extract:200:100"
    assert response.metadata == {
        "module": "memory",
        "command": "extract",
        "status": "queued",
        "job_id": "memory-extract:200:100",
        "limit": 100,
        "async": True,
    }
    assert store.extract_calls == [("200", 100)]
    assert started_threads[0].daemon is True
    assert started_threads[0].name == "memory-extract-200"


def test_memory_extract_background_enqueues_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        run_id = 12
        inserted_count = 3
        updated_count = 2
        skipped_count = 1
        input_message_count = 80

    class FakeOutboxStore:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def enqueue(self, request: Any) -> Any:
            self.requests.append(request)
            return object()

    outbox_store = FakeOutboxStore()

    from services import memory_extractor

    monkeypatch.setattr(memory.PostgresMemoryStore, "from_env", staticmethod(lambda: FakeMemoryStore()))
    monkeypatch.setattr(
        memory_extractor,
        "extract_group_memories",
        lambda store, group_id, *, limit=None, config=None: FakeResult(),
    )
    monkeypatch.setattr(memory.PostgresOutboxStore, "from_env", staticmethod(lambda: outbox_store))

    memory._run_extract_background("200", 100, {"batch_size": 100}, "job-1")

    assert len(outbox_store.requests) == 1
    request = outbox_store.requests[0]
    assert request.message_type == "group"
    assert request.group_id == "200"
    assert request.messages[0].text == "记忆抽取完成：run #12，新增 3 条，更新 2 条，跳过 1 条。"
    assert request.metadata == {
        "module": "memory",
        "command": "extract",
        "job_id": "job-1",
        "run_id": 12,
        "status": "succeeded",
    }


def test_memory_extract_rejects_invalid_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory extract 9")

    assert response is not None
    assert response.reply == "数量必须是 10 到 200 之间的整数。"
    assert response.metadata == {"module": "memory", "error": "invalid_limit"}


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
    assert "COALESCE(lifecycle_status, 'confirmed') IN ('confirmed', 'reinforced')" in captured[0][0]
    assert "COALESCE(lifecycle_status, 'confirmed') IN ('confirmed', 'reinforced')" in captured[1][0]


def test_memory_record_lifecycle_defaults_and_quality_helpers() -> None:
    record = MemoryRecord(
        id=1,
        scope="relationship",
        memory_type="relationship",
        memory_class="bad-class",
        content="Alice 经常和 Bob 一起讨论天气。",
        confidence=2.0,
        importance=-0.5,
        lifecycle_status="bad-status",
        source_count="bad-count",
        contradiction_count="bad-count",
        quality_score=3.0,
    )

    assert record.memory_class == "social"
    assert record.lifecycle_status == "confirmed"
    assert record.confidence == 1.0
    assert record.importance == 0.0
    assert record.source_count == 1
    assert record.contradiction_count == 0
    assert record.quality_score == 1.0
    assert memory.initial_lifecycle_status(
        {
            "memory_type": "fact",
            "confidence": 0.6,
            "importance": 0.7,
            "evidence_message_ids": [1],
        }
    ) == "weak"
    assert memory.initial_lifecycle_status(
        {
            "memory_type": "fact",
            "confidence": 0.8,
            "importance": 0.7,
            "evidence_message_ids": [1, 2],
        }
    ) == "confirmed"
    assert memory.compute_quality_score(record) == 0.555


def test_postgres_recall_filters_ineligible_lifecycle_records(monkeypatch: pytest.MonkeyPatch) -> None:
    store = memory.PostgresMemoryStore("postgres://example")
    rows = [
        _memory_row(1, lifecycle_status="weak", content="南京天气偏热。"),
        _memory_row(2, lifecycle_status="confirmed", content="用户喜欢南京天气。"),
    ]

    monkeypatch.setattr(store, "_fetch_all", lambda sql, params: rows)
    request = ChatRequest(text="南京", group_id="200", user_id="100")

    debug_records = store.debug_recall(request, "南京", include_ineligible=True)
    recalled = store.recall(request, "南京")

    assert {record.id for record, _score in debug_records} == {1, 2}
    assert [record.id for record in recalled] == [2]


def test_recall_lifecycle_filter_can_be_disabled_for_rollout(monkeypatch: pytest.MonkeyPatch) -> None:
    weak = MemoryRecord(
        id=1,
        scope="group",
        memory_type="fact",
        content="南京天气偏热。",
        confidence=0.6,
        importance=0.6,
        lifecycle_status="weak",
    )
    archived = MemoryRecord(
        id=2,
        scope="group",
        memory_type="fact",
        content="旧记忆。",
        confidence=0.6,
        importance=0.6,
        lifecycle_status="archived",
    )

    assert memory.recall_eligible(weak) is False

    monkeypatch.setenv("MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED", "false")

    assert memory.recall_eligible(weak) is True
    assert memory.recall_eligible(archived) is False
    assert memory._recall_status_filter() == "status = 'active' AND COALESCE(lifecycle_status, 'confirmed') <> 'archived'"


def test_memory_admin_lifecycle_commands_call_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)
    request = _request(role="admin")

    show_response = memory.handle_memory_command(request, "/memory show 9")
    status_response = memory.handle_memory_command(request, "/memory lifecycle status")
    confirm_response = memory.handle_memory_command(request, "/memory lifecycle confirm 9")
    archive_response = memory.handle_memory_command(request, "/memory archive 9")
    decay_response = memory.handle_memory_command(request, "/memory lifecycle decay 30")

    assert show_response is not None
    assert "记忆 #9" in show_response.reply
    assert show_response.metadata == {"module": "memory", "command": "show", "id": 9, "found": True}
    assert status_response is not None
    assert "weak: 1" in status_response.reply
    assert "confirmed: 2" in status_response.reply
    assert confirm_response is not None
    assert confirm_response.metadata == {
        "module": "memory",
        "command": "lifecycle",
        "action": "confirm",
        "id": 9,
        "changed": True,
    }
    assert archive_response is not None
    assert archive_response.reply == "已归档。"
    assert decay_response is not None
    assert decay_response.metadata == {
        "module": "memory",
        "command": "lifecycle",
        "action": "decay",
        "scanned": 3,
        "stale": 1,
        "archived": 1,
        "days": 30,
    }
    assert store.get_calls == [(9, "200", False)]
    assert ("confirm", 9, "200", False, "100") in store.lifecycle_actions
    assert ("archive", 9, "200", False, "100") in store.lifecycle_actions
    assert ("decay", "200", 30, 500) in store.lifecycle_actions


def test_memory_debug_recall_command_formats_score_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeMemoryStore()
    _install_store(monkeypatch, store)

    response = memory.handle_memory_command(_request(role="admin"), "/memory debug recall 南京")

    assert response is not None
    assert "召回调试：" in response.reply
    assert "#9 score=0.81 eligible=yes lifecycle=confirmed" in response.reply
    assert "keyword=1.00 entity=0.90 scope=0.75 quality=0.50 recency=0.50" in response.reply
    assert response.metadata == {"module": "memory", "command": "debug_recall", "count": 1}
    assert store.lifecycle_actions == [("debug_recall", "南京", 10, True)]


def test_upsert_extracted_memory_marks_conflicting_memory_contradicted(monkeypatch: pytest.MonkeyPatch) -> None:
    store = memory.PostgresMemoryStore("postgres://example")
    captured: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(memory, "_jsonb", lambda value: value)

    def fake_fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        if "SELECT *" in sql:
            return []
        if "INSERT INTO memory_items" in sql:
            return [{"id": 77}]
        return []

    monkeypatch.setattr(store, "_fetch_all", fake_fetch_all)

    memory_id, action = store.upsert_extracted_memory(
        {
            "scope": "user",
            "group_id": "200",
            "user_id": "100",
            "target_user_id": "",
            "memory_type": "preference",
            "memory_class": "procedural",
            "content": "Alice 喜欢短回复。",
            "confidence": 0.8,
            "importance": 0.7,
            "evidence_message_ids": [101, 102],
            "metadata": {
                "conflicts_with_memory_id": 42,
                "conflicts_with": {"content": "Alice 不喜欢短回复。"},
            },
        }
    )

    assert (memory_id, action) == (77, "inserted")
    assert "lifecycle_status = 'contradicted'" in captured[0][0]
    assert "contradiction_count = contradiction_count + 1" in captured[0][0]
    assert "LEAST(contradiction_count + 1, 3)" in captured[0][0]
    assert captured[0][1][1:] == (42, "200")
    assert captured[0][1][0]["last_contradiction"]["evidence_message_ids"] == [101, 102]


def test_postgres_memory_store_reads_group_messages_for_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    store = memory.PostgresMemoryStore("postgres://example")
    captured: list[tuple[str, tuple[Any, ...]]] = []

    def fake_fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        return [{"id": 1, "conversation_id": 2, "text": "hello"}]

    monkeypatch.setattr(store, "_fetch_all", fake_fetch_all)

    rows = store.recent_group_messages_for_extraction("group-a", limit=50)

    assert rows == [{"id": 1, "conversation_id": 2, "text": "hello"}]
    assert "conversations.conversation_type = 'group'" in captured[0][0]
    assert "COALESCE(messages.text, '') <> ''" in captured[0][0]
    assert captured[0][1] == ("group-a", 50)


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


def _memory_row(memory_id: int, *, lifecycle_status: str, content: str) -> dict[str, Any]:
    return {
        "id": memory_id,
        "scope": "group",
        "memory_type": "fact",
        "memory_class": "semantic",
        "content": content,
        "confidence": 0.8,
        "importance": 0.7,
        "group_id": "200",
        "user_id": "100",
        "target_user_id": "",
        "status": "active",
        "lifecycle_status": lifecycle_status,
        "stability": 0.5,
        "decay_score": 1.0,
        "contradiction_count": 0,
        "source_count": 1,
        "quality_score": 0.6,
        "last_confirmed_at": None,
        "archived_at": None,
        "last_seen_at": None,
        "evidence_message_ids": [101],
        "metadata": {},
    }


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
