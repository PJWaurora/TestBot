import logging
import os
from typing import Any

from schemas import BrainResponse, ChatRequest


logger = logging.getLogger(__name__)


class PersistenceError(Exception):
    pass


class PostgresChatStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    @classmethod
    def from_env(cls) -> "PostgresChatStore":
        return cls(os.getenv("DATABASE_URL", "").strip())

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def persist_incoming(self, request: ChatRequest) -> int | None:
        if not self.enabled:
            return None

        conversation_type, external_id = conversation_key(request)
        if not conversation_type or not external_id:
            return None

        payload = _model_dump(request)
        segments = request.segments or []
        sender = request.sender
        sender_user_id = _string_id(
            sender.user_id if sender is not None and sender.user_id is not None else request.user_id
        )

        rows = self._fetch_all(
            """
            WITH conversation_row AS (
                INSERT INTO conversations (conversation_type, external_id, title, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (conversation_type, external_id)
                DO UPDATE SET title = COALESCE(EXCLUDED.title, conversations.title), updated_at = now()
                RETURNING id
            ),
            raw_row AS (
                INSERT INTO message_events_raw (
                    external_message_id,
                    post_type,
                    message_type,
                    event
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
            )
            INSERT INTO messages (
                conversation_id,
                raw_event_id,
                external_message_id,
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
                sender_role
            )
            SELECT
                conversation_row.id,
                raw_row.id,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            FROM conversation_row, raw_row
            RETURNING id
            """,
            (
                conversation_type,
                external_id,
                request.group_name or None,
                _string_id(request.message_id),
                request.post_type,
                request.message_type,
                _jsonb(payload),
                _string_id(request.message_id),
                request.post_type,
                request.message_type,
                request.sub_type,
                request.primary_type,
                request.text or request.content,
                request.content or request.text,
                _jsonb(segments),
                sender_user_id,
                sender.nickname if sender is not None else "",
                sender.card if sender is not None else "",
                sender.role if sender is not None else "",
            ),
        )
        if not rows:
            return None
        return int(rows[0]["id"])

    def persist_response(self, message_id: int | None, response: BrainResponse) -> None:
        if not self.enabled or message_id is None:
            return

        self._fetch_all(
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
            RETURNING id
            """,
            (
                message_id,
                response.should_reply,
                response.reply,
                _jsonb([_model_dump(message) for message in response.messages]),
                _metadata_value(response, "model"),
                _metadata_value(response, "prompt_version"),
            ),
        )

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise PersistenceError("psycopg is required for chat persistence") from exc

        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
        except psycopg.errors.UndefinedTable as exc:
            raise PersistenceError("chat persistence tables are missing; run database migrations") from exc
        except psycopg.Error as exc:
            raise PersistenceError(f"chat persistence database error: {exc}") from exc


def safe_persist_incoming(request: ChatRequest) -> int | None:
    try:
        return PostgresChatStore.from_env().persist_incoming(request)
    except Exception as exc:  # pragma: no cover - defensive wrapper must never break chat handling.
        logger.warning("chat persistence skipped: %s", exc)
        return None


def safe_persist_response(message_id: int | None, response: BrainResponse) -> None:
    try:
        PostgresChatStore.from_env().persist_response(message_id, response)
    except Exception as exc:  # pragma: no cover - defensive wrapper must never break chat handling.
        logger.warning("bot response persistence skipped: %s", exc)


def conversation_key(request: ChatRequest) -> tuple[str, str]:
    message_type = (request.message_type or "").strip().lower()
    group_id = _string_id(request.group_id)
    user_id = _string_id(request.user_id)
    if message_type == "group" or group_id:
        return "group", group_id or ""
    if message_type == "private" or user_id:
        return "private", user_id or ""
    return "", ""


def _metadata_value(response: BrainResponse, key: str) -> str | None:
    if not response.metadata:
        return None
    value = response.metadata.get(key)
    return str(value) if value is not None else None


def _string_id(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover
        raise PersistenceError("psycopg is required for JSONB values") from exc

    return Jsonb(value)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
