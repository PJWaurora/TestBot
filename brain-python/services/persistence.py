from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol

from schemas import BrainMessage, BrainResponse, ChatRequest


class ChatPersistenceRepository(Protocol):
    def save_request(self, request: ChatRequest) -> int | None:
        ...

    def save_response(self, message_id: int, response: BrainResponse) -> None:
        ...

    def recent_group_messages(
        self, *, group_id: str | int | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        ...


def get_default_repository() -> ChatPersistenceRepository | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None

    try:
        import psycopg  # noqa: F401
        from psycopg.types.json import Jsonb  # noqa: F401
    except ImportError:
        return None

    return PostgresChatRepository(database_url)


def get_message_source() -> ChatPersistenceRepository | None:
    return get_default_repository()


class PostgresChatRepository:
    def __init__(self, database_url: str, connect_timeout: int = 2) -> None:
        self.database_url = database_url
        self.connect_timeout = connect_timeout

    def save_request(self, request: ChatRequest) -> int | None:
        from psycopg.types.json import Jsonb

        payload = _dump_model(request)
        message = _request_message(request)
        metadata = _request_metadata(request, message)
        conversation_type, external_conversation_id = _conversation_key(request, message)
        external_message_id = _string_value(
            request.message_id,
            _getattr(message, "message_id"),
            metadata.get("message_id"),
        )
        message_type = _string_value(
            request.message_type,
            _getattr(message, "message_type"),
            metadata.get("message_type"),
            conversation_type,
        )
        post_type = _string_value(metadata.get("post_type"), "message")
        text = _request_text(request, message)
        sender = metadata.get("sender") if isinstance(metadata.get("sender"), dict) else {}

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (conversation_type, external_id, title)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (conversation_type, external_id)
                    DO UPDATE SET
                        title = COALESCE(EXCLUDED.title, conversations.title),
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        conversation_type,
                        external_conversation_id,
                        _string_value(metadata.get("group_name"), metadata.get("title")),
                    ),
                )
                conversation_id = cursor.fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO message_events_raw (
                        external_message_id,
                        post_type,
                        message_type,
                        event
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (external_message_id, post_type, message_type, Jsonb(payload)),
                )
                raw_event_id = cursor.fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO messages (
                        conversation_id,
                        raw_event_id,
                        external_message_id,
                        external_message_seq,
                        external_real_id,
                        external_real_seq,
                        post_type,
                        message_type,
                        sub_type,
                        primary_type,
                        text,
                        raw_message,
                        segments,
                        sender_user_id,
                        sender_nickname,
                        sender_card,
                        sender_role,
                        sent_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        conversation_id,
                        raw_event_id,
                        external_message_id,
                        _string_value(metadata.get("message_seq")),
                        _string_value(metadata.get("real_id")),
                        _string_value(metadata.get("real_seq")),
                        post_type,
                        message_type,
                        _string_value(metadata.get("sub_type")),
                        _primary_type(message, text, metadata),
                        text,
                        _string_value(metadata.get("raw_message"), text),
                        Jsonb(metadata.get("segments") or []),
                        _string_value(
                            request.user_id,
                            _getattr(message, "user_id"),
                            sender.get("user_id"),
                            metadata.get("user_id"),
                        ),
                        _string_value(sender.get("nickname")),
                        _string_value(sender.get("card")),
                        _string_value(sender.get("role")),
                        _sent_at(metadata),
                    ),
                )
                return cursor.fetchone()[0]

    def save_response(self, message_id: int, response: BrainResponse) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bot_responses (
                        message_id,
                        should_reply,
                        reply,
                        actions,
                        model,
                        prompt_version
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        response.should_reply,
                        response.reply or None,
                        Jsonb(_response_actions(response)),
                        _metadata_value(response, "model"),
                        _metadata_value(response, "prompt_version"),
                    ),
                )

    def _connect(self, **kwargs: Any):
        import psycopg

        kwargs.setdefault("connect_timeout", self.connect_timeout)
        return psycopg.connect(self.database_url, **kwargs)

    def recent_group_messages(
        self, *, group_id: str | int | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if group_id is None:
            return []

        from psycopg.rows import dict_row

        with self._connect(row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        m.id,
                        m.text,
                        m.raw_message,
                        m.sender_user_id AS user_id,
                        COALESCE(
                            NULLIF(m.sender_card, ''),
                            NULLIF(m.sender_nickname, ''),
                            NULLIF(m.sender_user_id, ''),
                            '未知用户'
                        ) AS user_name,
                        m.created_at,
                        m.sent_at
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.conversation_type = 'group'
                        AND c.external_id = %s
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    (str(group_id), max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()

        return list(reversed(rows))


def _request_message(request: ChatRequest) -> BrainMessage | None:
    if request.messages:
        return request.messages[-1]
    return request.message


def _request_metadata(request: ChatRequest, message: BrainMessage | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if message is not None:
        metadata.update(message.metadata)
    metadata.update(request.metadata)
    return metadata


def _conversation_key(
    request: ChatRequest,
    message: BrainMessage | None,
) -> tuple[str, str]:
    group_id = _string_value(request.group_id, _getattr(message, "group_id"))
    if group_id:
        return "group", group_id

    message_type = _string_value(request.message_type, _getattr(message, "message_type"))
    conversation_id = _string_value(
        request.conversation_id,
        _getattr(message, "conversation_id"),
    )
    if conversation_id:
        conversation_type = "group" if message_type == "group" else "private"
        return conversation_type, conversation_id

    user_id = _string_value(request.user_id, _getattr(message, "user_id"))
    if user_id:
        return "private", user_id

    return "private", "anonymous"


def _request_text(request: ChatRequest, message: BrainMessage | None) -> str | None:
    candidates = [request.text, request.content]
    if request.message is not None:
        candidates.append(_message_text(request.message))
    candidates.extend(_message_text(candidate) for candidate in request.messages)
    if message is not None:
        candidates.append(_message_text(message))

    for candidate in reversed(candidates):
        text = candidate.strip()
        if text:
            return text
    return None


def _message_text(message: BrainMessage) -> str:
    return message.text or message.content


def _primary_type(
    message: BrainMessage | None,
    text: str | None,
    metadata: dict[str, Any],
) -> str:
    primary_type = _string_value(metadata.get("primary_type"))
    if primary_type:
        return primary_type
    if message is not None and message.type:
        return message.type
    if text:
        return "text"
    return "meta_or_other"


def _response_actions(response: BrainResponse) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for message in response.messages:
        actions.append({"type": "message", "message": _dump_model(message)})
    for tool_call in response.tool_calls:
        actions.append({"type": "tool_call", "tool_call": _dump_model(tool_call)})
    if response.job_id:
        actions.append({"type": "job", "job_id": response.job_id})
    return actions


def _metadata_value(response: BrainResponse, key: str) -> str | None:
    if not response.metadata:
        return None
    return _string_value(response.metadata.get(key))


def _sent_at(metadata: dict[str, Any]) -> datetime | None:
    value = metadata.get("time") or metadata.get("sent_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError):
        return None


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    return model.dict(exclude_none=True, exclude_defaults=True)


def _getattr(value: Any, name: str) -> Any:
    if value is None:
        return None
    return getattr(value, name, None)


def _string_value(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
            continue
        return str(value)
    return None
