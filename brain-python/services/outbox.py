from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Protocol, cast


logger = logging.getLogger(__name__)
_DEFAULT_REPOSITORY = object()
_repository_override: OutboxRepository | None | object = _DEFAULT_REPOSITORY


class OutboxRepository(Protocol):
    def enqueue(
        self,
        *,
        target_type: str,
        target_id: str,
        messages: list[dict[str, Any]],
        actions: list[dict[str, Any]] | None = None,
        available_at: datetime | None = None,
    ) -> int:
        ...

    def pull(self, *, limit: int = 10) -> list[dict[str, Any]]:
        ...

    def ack(self, *, ids: list[int], success: bool, error: str | None = None) -> int:
        ...


def set_outbox_repository(repository: OutboxRepository | None) -> None:
    global _repository_override
    _repository_override = repository


def reset_outbox_repository() -> None:
    global _repository_override
    _repository_override = _DEFAULT_REPOSITORY


def get_default_repository() -> OutboxRepository | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None

    try:
        import psycopg  # noqa: F401
        from psycopg.types.json import Jsonb  # noqa: F401
    except ImportError:
        return None

    return PostgresOutboxRepository(database_url)


def enqueue(
    *,
    target_type: str,
    target_id: str,
    messages: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None = None,
    available_at: datetime | None = None,
) -> int | None:
    repository = _outbox_repository()
    if repository is None:
        return None
    try:
        return repository.enqueue(
            target_type=target_type,
            target_id=target_id,
            messages=messages,
            actions=actions,
            available_at=available_at,
        )
    except Exception:
        logger.exception("outbox enqueue failed")
        return None


def pull(*, limit: int = 10) -> list[dict[str, Any]]:
    repository = _outbox_repository()
    if repository is None:
        return []
    try:
        return repository.pull(limit=limit)
    except Exception:
        logger.exception("outbox pull failed")
        return []


def ack(*, ids: list[int], success: bool, error: str | None = None) -> int:
    if not ids:
        return 0

    repository = _outbox_repository()
    if repository is None:
        return len(ids)
    try:
        return repository.ack(ids=ids, success=success, error=error)
    except Exception:
        logger.exception("outbox ack failed")
        return 0


class PostgresOutboxRepository:
    def __init__(self, database_url: str, connect_timeout: int = 2) -> None:
        self.database_url = database_url
        self.connect_timeout = connect_timeout

    def enqueue(
        self,
        *,
        target_type: str,
        target_id: str,
        messages: list[dict[str, Any]],
        actions: list[dict[str, Any]] | None = None,
        available_at: datetime | None = None,
    ) -> int:
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO notification_outbox (
                        target_type,
                        target_id,
                        messages,
                        actions,
                        available_at
                    )
                    VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, now()))
                    RETURNING id
                    """,
                    (
                        target_type,
                        target_id,
                        Jsonb(messages),
                        Jsonb(actions or []),
                        available_at,
                    ),
                )
                return cursor.fetchone()[0]

    def pull(self, *, limit: int = 10) -> list[dict[str, Any]]:
        from psycopg.rows import dict_row

        bounded_limit = max(1, min(int(limit), 100))
        with self._connect(row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH selected AS (
                        SELECT id
                        FROM notification_outbox
                        WHERE status = 'pending'
                            AND available_at <= now()
                            AND (
                                locked_at IS NULL
                                OR locked_at < now() - interval '1 minute'
                            )
                        ORDER BY id
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE notification_outbox outbox
                    SET
                        locked_at = now(),
                        updated_at = now()
                    FROM selected
                    WHERE outbox.id = selected.id
                    RETURNING
                        outbox.id,
                        outbox.target_type,
                        outbox.target_id,
                        outbox.messages,
                        outbox.actions
                    """,
                    (bounded_limit,),
                )
                return list(cursor.fetchall())

    def ack(self, *, ids: list[int], success: bool, error: str | None = None) -> int:
        if not ids:
            return 0

        with self._connect() as connection:
            with connection.cursor() as cursor:
                if success:
                    cursor.execute(
                        """
                        UPDATE notification_outbox
                        SET
                            status = 'sent',
                            locked_at = NULL,
                            sent_at = now(),
                            last_error = NULL,
                            updated_at = now()
                        WHERE id = ANY(%s::bigint[])
                            AND status <> 'sent'
                        """,
                        (ids,),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE notification_outbox
                        SET
                            status = 'pending',
                            attempt_count = attempt_count + 1,
                            locked_at = NULL,
                            last_error = %s,
                            updated_at = now()
                        WHERE id = ANY(%s::bigint[])
                            AND status <> 'sent'
                        """,
                        (error, ids),
                    )
                return cursor.rowcount

    def _connect(self, **kwargs: Any):
        import psycopg

        kwargs.setdefault("connect_timeout", self.connect_timeout)
        return psycopg.connect(self.database_url, **kwargs)


def _outbox_repository() -> OutboxRepository | None:
    if _repository_override is _DEFAULT_REPOSITORY:
        return get_default_repository()
    return cast(OutboxRepository | None, _repository_override)
