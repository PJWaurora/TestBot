from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from schemas import BrainMessage, BrainResponse, ChatRequest
from services import conversation_state


def test_update_from_message_derives_and_upserts_state(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc) - timedelta(minutes=10)
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def fake_fetch_all(self: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        calls.append((sql, params))
        if "SELECT conversation_id FROM messages WHERE id = %s" in sql:
            return [{"conversation_id": 7}]
        if "FROM messages" in sql and "created_at >= now()" in sql:
            return [
                _message("u4", "AI 计划", now),
                _message("u3", "AI 计划", now),
                _message("u2", "天气 计划", now),
                _message("u1", "天气 AI", now),
                _message("u1", "天气", now),
                _message("u5", "部署 计划", now),
                _message("u6", "部署 AI", now),
                _message("u7", "部署", now),
                _message("u8", "状态", now),
                _message("u9", "状态", now),
                _message("u10", "状态", now),
                _message("u11", "状态", now),
            ]
        if "FROM bot_responses" in sql:
            return [{"last_bot_reply_at": None, "bot_reply_count_1h": 1, "bot_reply_count_24h": 2}]
        if "INSERT INTO conversation_states" in sql:
            return [{"conversation_id": params[0]}]
        raise AssertionError(sql)

    monkeypatch.setattr(conversation_state.PostgresConversationStateStore, "_fetch_all", fake_fetch_all)

    state = conversation_state.PostgresConversationStateStore("postgres://test").update_from_message(99)

    assert state is not None
    assert state.conversation_id == 7
    assert state.mood == "neutral"
    assert state.conversation_velocity == "active"
    assert state.active_topics[:4] == ["ai", "计划", "状态", "天气"]
    assert state.current_speaker_ids[:4] == ["u4", "u3", "u2", "u1"]
    assert state.should_avoid_long_reply is True

    upsert_call = calls[-1]
    assert "INSERT INTO conversation_states" in upsert_call[0]
    assert upsert_call[1][0] == 7
    assert upsert_call[1][2] == "neutral"
    assert upsert_call[1][3] == "active"
    assert upsert_call[1][5:9] == (None, 1, 2, True)


def test_update_from_bot_response_skips_non_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_fetch_all(self: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        raise AssertionError("non-reply response should not update state")

    monkeypatch.setattr(conversation_state.PostgresConversationStateStore, "_fetch_all", fail_fetch_all)
    response = BrainResponse(handled=True, should_reply=False)

    state = conversation_state.PostgresConversationStateStore("postgres://test").update_from_bot_response(10, response)

    assert state is None


def test_update_from_bot_response_refreshes_reply_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    recent_reply = datetime.now(timezone.utc) - timedelta(seconds=30)

    def fake_fetch_all(self: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if "SELECT conversation_id FROM messages WHERE id = %s" in sql:
            return [{"conversation_id": 3}]
        if "FROM messages" in sql and "created_at >= now()" in sql:
            return [_message("u1", "short chat", recent_reply)]
        if "FROM bot_responses" in sql:
            return [{"last_bot_reply_at": recent_reply, "bot_reply_count_1h": 2, "bot_reply_count_24h": 4}]
        if "INSERT INTO conversation_states" in sql:
            return [{"conversation_id": params[0]}]
        raise AssertionError(sql)

    monkeypatch.setattr(conversation_state.PostgresConversationStateStore, "_fetch_all", fake_fetch_all)
    response = BrainResponse(
        handled=True,
        should_reply=True,
        reply="hello",
        messages=[BrainMessage(type="text", text="hello")],
    )

    state = conversation_state.PostgresConversationStateStore("postgres://test").update_from_bot_response(10, response)

    assert state is not None
    assert state.bot_reply_count_1h == 2
    assert state.bot_reply_count_24h == 4
    assert state.last_bot_reply_at == recent_reply
    assert state.should_avoid_long_reply is True


def test_read_for_request_returns_existing_state(monkeypatch: pytest.MonkeyPatch) -> None:
    updated_at = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)

    def fake_fetch_all(self: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        assert params == ("group", "200")
        return [
            {
                "conversation_id": 8,
                "active_topics": ["deploy"],
                "mood": "neutral",
                "conversation_velocity": "quiet",
                "current_speaker_ids": ["42"],
                "last_bot_reply_at": None,
                "bot_reply_count_1h": 0,
                "bot_reply_count_24h": 1,
                "should_avoid_long_reply": False,
                "metadata": {"recent_message_count": 2},
                "updated_at": updated_at,
            }
        ]

    monkeypatch.setattr(conversation_state.PostgresConversationStateStore, "_fetch_all", fake_fetch_all)

    state = conversation_state.PostgresConversationStateStore("postgres://test").read_for_request(
        ChatRequest(message_type="group", group_id=200, user_id=42)
    )

    assert state is not None
    assert state.conversation_id == 8
    assert state.active_topics == ["deploy"]
    assert state.current_speaker_ids == ["42"]
    assert state.updated_at == updated_at


def test_summarize_for_prompt_is_readable_and_bounded() -> None:
    summary = conversation_state.summarize_for_prompt(
        conversation_state.ConversationState(
            conversation_id=3,
            active_topics=["AI", "天气"],
            conversation_velocity="burst",
            current_speaker_ids=["u1", "u2"],
            should_avoid_long_reply=True,
        )
    )

    assert "当前群聊状态：" in summary
    assert "- mood: neutral" in summary
    assert "- velocity: burst" in summary
    assert "- active_topics: AI, 天气" in summary
    assert "- should_avoid_long_reply: true" in summary
    assert "优先短回复" in summary


def test_missing_database_url_returns_none() -> None:
    store = conversation_state.PostgresConversationStateStore("")

    assert store.read_for_request(ChatRequest(message_type="group", group_id="g")) is None
    assert store.update_from_message(1) is None


def test_safe_read_fails_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenStore:
        def read_for_request(self, request: ChatRequest) -> conversation_state.ConversationState:
            raise conversation_state.ConversationStateError("database unavailable")

    monkeypatch.setattr(
        conversation_state.PostgresConversationStateStore,
        "from_env",
        staticmethod(lambda: BrokenStore()),
    )

    state = conversation_state.safe_read_for_request(ChatRequest(message_type="group", group_id="g"))

    assert state is None


def _message(sender_id: str, text: str, created_at: datetime) -> dict[str, Any]:
    return {
        "sender_user_id": sender_id,
        "text": text,
        "created_at": created_at,
    }
