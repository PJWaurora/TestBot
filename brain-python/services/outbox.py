import os
from typing import Any, Protocol

from schemas import BrainMessage, OutboxEnqueueRequest, OutboxItem


DEFAULT_DATABASE_URL = "postgres://testbot:change-me-local-only@postgres:5432/testbot?sslmode=disable"
SUPPORTED_MESSAGE_TYPES = {"text", "image", "video"}


class OutboxError(Exception):
    pass


class OutboxConfigurationError(OutboxError):
    pass


class OutboxNotFoundError(OutboxError):
    pass


class OutboxValidationError(OutboxError):
    pass


class OutboxStore(Protocol):
    def enqueue(self, request: OutboxEnqueueRequest) -> OutboxItem:
        ...

    def pull(self, limit: int, lease_seconds: int) -> list[OutboxItem]:
        ...

    def ack(self, item_id: int) -> OutboxItem:
        ...

    def fail(self, item_id: int, error: str) -> OutboxItem:
        ...


class PostgresOutboxStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    @classmethod
    def from_env(cls) -> "PostgresOutboxStore":
        return cls(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))

    def enqueue(self, request: OutboxEnqueueRequest) -> OutboxItem:
        message_type = _normalized_target_type(request.message_type)
        user_id = _string_id(request.user_id)
        group_id = _string_id(request.group_id)
        _validate_target(message_type, user_id, group_id)
        _validate_messages(request.messages)

        rows = self._fetch_all(
            """
            INSERT INTO message_outbox (
                message_type,
                user_id,
                group_id,
                messages,
                metadata,
                max_attempts
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                message_type,
                user_id,
                group_id,
                _jsonb([_model_dump(message) for message in request.messages]),
                _jsonb(request.metadata),
                request.max_attempts,
            ),
        )
        return _row_to_item(_single_row(rows, "enqueue"))

    def pull(self, limit: int, lease_seconds: int) -> list[OutboxItem]:
        rows = self._fetch_all(
            """
            WITH picked AS (
                SELECT id
                FROM message_outbox
                WHERE attempts < max_attempts
                  AND (
                    (status = 'pending' AND next_attempt_at <= now())
                    OR (status = 'processing' AND (locked_until IS NULL OR locked_until <= now()))
                  )
                ORDER BY created_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE message_outbox AS outbox
            SET status = 'processing',
                locked_until = now() + (%s * interval '1 second'),
                updated_at = now()
            FROM picked
            WHERE outbox.id = picked.id
            RETURNING outbox.*
            """,
            (limit, lease_seconds),
        )
        return [_row_to_item(row) for row in rows]

    def ack(self, item_id: int) -> OutboxItem:
        rows = self._fetch_all(
            """
            UPDATE message_outbox
            SET status = 'sent',
                locked_until = NULL,
                sent_at = COALESCE(sent_at, now()),
                updated_at = now()
            WHERE id = %s
              AND status IN ('pending', 'processing', 'sent')
            RETURNING *
            """,
            (item_id,),
        )
        return _row_to_item(_single_row(rows, "ack"))

    def fail(self, item_id: int, error: str) -> OutboxItem:
        rows = self._fetch_all(
            """
            UPDATE message_outbox
            SET attempts = attempts + 1,
                status = CASE
                    WHEN attempts + 1 >= max_attempts THEN 'failed'
                    ELSE 'pending'
                END,
                locked_until = NULL,
                last_error = %s,
                next_attempt_at = now(),
                failed_at = CASE
                    WHEN attempts + 1 >= max_attempts THEN COALESCE(failed_at, now())
                    ELSE failed_at
                END,
                updated_at = now()
            WHERE id = %s
              AND status IN ('pending', 'processing')
              AND attempts < max_attempts
            RETURNING *
            """,
            (_trim_error(error), item_id),
        )
        return _row_to_item(_single_row(rows, "fail"))

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self.database_url:
            raise OutboxConfigurationError("DATABASE_URL is not configured")

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised only in misconfigured runtime.
            raise OutboxConfigurationError("psycopg is required for outbox database access") from exc

        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    return list(rows)
        except psycopg.errors.UndefinedTable as exc:
            raise OutboxConfigurationError("message_outbox table is missing; run database migrations") from exc
        except psycopg.Error as exc:
            raise OutboxError(f"outbox database error: {exc}") from exc


def _normalized_target_type(message_type: str) -> str:
    value = message_type.strip().lower()
    if value not in {"group", "private"}:
        raise OutboxValidationError("message_type must be 'group' or 'private'")
    return value


def _validate_target(message_type: str, user_id: str | None, group_id: str | None) -> None:
    if message_type == "group" and not group_id:
        raise OutboxValidationError("group outbox items require group_id")
    if message_type == "private" and not user_id:
        raise OutboxValidationError("private outbox items require user_id")


def _validate_messages(messages: list[BrainMessage]) -> None:
    if not messages:
        raise OutboxValidationError("messages must not be empty")

    for message in messages:
        message_type = message.type.strip().lower()
        if message_type not in SUPPORTED_MESSAGE_TYPES:
            raise OutboxValidationError("outbox messages must be text, image, or video")
        if message_type == "text" and not _message_text(message):
            raise OutboxValidationError("text outbox messages require text or content")
        if message_type in {"image", "video"} and not _message_file(message):
            raise OutboxValidationError(f"{message_type} outbox messages require file, url, or path")


def _message_text(message: BrainMessage) -> str:
    if message.text:
        return message.text
    if message.content:
        return message.content
    return _data_value(message.data, "text", "content") or _data_value(message.metadata, "text", "content")


def _message_file(message: BrainMessage) -> str:
    if message.file:
        return message.file
    if message.url:
        return message.url
    if message.path:
        return message.path
    return _data_value(message.data, "file", "url", "path") or _data_value(
        message.metadata,
        "file",
        "url",
        "path",
    )


def _data_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return ""


def _row_to_item(row: dict[str, Any]) -> OutboxItem:
    payload = dict(row)
    payload["messages"] = [_model_validate(BrainMessage, message) for message in payload.get("messages") or []]
    payload["metadata"] = payload.get("metadata") or {}
    return _model_validate(OutboxItem, payload)


def _single_row(rows: list[dict[str, Any]], operation: str) -> dict[str, Any]:
    if not rows:
        raise OutboxNotFoundError(f"outbox item not found for {operation}")
    return rows[0]


def _string_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _trim_error(error: str) -> str:
    text = error.strip()
    if not text:
        return "gateway_delivery_failed"
    return text[:1000]


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover - exercised only in misconfigured runtime.
        raise OutboxConfigurationError("psycopg is required for outbox database access") from exc

    return Jsonb(value)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _model_validate(model_type: Any, value: Any) -> Any:
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(value)
    return model_type.parse_obj(value)
