import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from modules.base import parse_command_invocation
from schemas import BrainMessage, BrainResponse, ChatRequest


logger = logging.getLogger(__name__)

ADMIN_ROLES = {"admin", "owner"}
DEFAULT_RECENT_LIMIT = 30
DEFAULT_MEMORY_LIMIT = 8


class MemoryError(Exception):
    pass


class MemoryConfigurationError(MemoryError):
    pass


@dataclass
class MemoryRecord:
    id: int
    scope: str
    memory_type: str
    content: str
    confidence: float
    importance: float
    group_id: str = ""
    user_id: str = ""
    target_user_id: str = ""


class PostgresMemoryStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    @classmethod
    def from_env(cls) -> "PostgresMemoryStore":
        return cls(os.getenv("DATABASE_URL", "").strip())

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def group_memory_enabled(self, group_id: str) -> bool:
        if not self.enabled or not group_id:
            return True
        rows = self._fetch_all(
            """
            SELECT enabled
            FROM memory_settings
            WHERE scope = 'group' AND group_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (group_id,),
        )
        if not rows:
            return True
        return bool(rows[0]["enabled"])

    def set_group_memory_enabled(self, group_id: str, enabled: bool) -> None:
        self._fetch_all(
            """
            INSERT INTO memory_settings (scope, group_id, enabled, updated_at)
            VALUES ('group', %s, %s, now())
            ON CONFLICT (scope, group_id)
            DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()
            RETURNING id
            """,
            (group_id, enabled),
        )

    def count_active(self, group_id: str) -> int:
        rows = self._fetch_all(
            """
            SELECT count(*) AS count
            FROM memory_items
            WHERE status = 'active'
              AND (%s = '' OR group_id = %s OR scope = 'global')
            """,
            (group_id, group_id),
        )
        return int(rows[0]["count"]) if rows else 0

    def search(self, query: str, *, group_id: str = "", user_id: str = "", limit: int = 10) -> list[MemoryRecord]:
        like = f"%{query}%"
        rows = self._fetch_all(
            """
            SELECT *
            FROM memory_items
            WHERE status = 'active'
              AND content ILIKE %s
              AND """ + _memory_scope_filter() + """
            ORDER BY importance DESC, confidence DESC, last_seen_at DESC, id DESC
            LIMIT %s
            """,
            (like, *_memory_scope_params(group_id, user_id), limit),
        )
        return [_row_to_memory(row) for row in rows]

    def recall(self, request: ChatRequest, text: str, *, limit: int = DEFAULT_MEMORY_LIMIT) -> list[MemoryRecord]:
        group_id = _string_id(request.group_id)
        user_id = _string_id(request.user_id)
        keywords = _keywords(text)
        if not keywords:
            rows = self._fetch_all(
                """
                SELECT *
                FROM memory_items
                WHERE status = 'active'
                  AND """ + _memory_scope_filter() + """
                ORDER BY importance DESC, confidence DESC, last_seen_at DESC, id DESC
                LIMIT %s
                """,
                (*_memory_scope_params(group_id, user_id), limit),
            )
            return [_row_to_memory(row) for row in rows]

        clauses = " OR ".join(["content ILIKE %s" for _ in keywords])
        rows = self._fetch_all(
            f"""
            SELECT *
            FROM memory_items
            WHERE status = 'active'
              AND ({clauses})
              AND """ + _memory_scope_filter() + """
            ORDER BY importance DESC, confidence DESC, last_seen_at DESC, id DESC
            LIMIT %s
            """,
            tuple(f"%{keyword}%" for keyword in keywords)
            + (*_memory_scope_params(group_id, user_id), limit),
        )
        return [_row_to_memory(row) for row in rows]

    def recent_messages(self, request: ChatRequest, *, limit: int = DEFAULT_RECENT_LIMIT) -> list[dict[str, Any]]:
        conversation_type, external_id = _conversation_key(request)
        if not conversation_type or not external_id:
            return []
        rows = self._fetch_all(
            """
            SELECT
                messages.sender_user_id,
                messages.sender_nickname,
                messages.sender_card,
                messages.text,
                messages.primary_type,
                messages.created_at
            FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            WHERE conversations.conversation_type = %s
              AND conversations.external_id = %s
              AND COALESCE(messages.text, '') <> ''
            ORDER BY messages.created_at DESC, messages.id DESC
            LIMIT %s
            """,
            (conversation_type, external_id, limit),
        )
        return list(reversed(rows))

    def list_user(self, group_id: str, user_id: str, *, limit: int = 20) -> list[MemoryRecord]:
        rows = self._fetch_all(
            """
            SELECT *
            FROM memory_items
            WHERE status = 'active'
              AND group_id = %s
              AND user_id = %s
            ORDER BY importance DESC, confidence DESC, last_seen_at DESC
            LIMIT %s
            """,
            (group_id, user_id, limit),
        )
        return [_row_to_memory(row) for row in rows]

    def delete_memory(self, memory_id: int, *, group_id: str = "", allow_global: bool = False) -> bool:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET status = 'deleted', updated_at = now()
            WHERE id = %s
              AND status <> 'deleted'
              AND (%s OR group_id = %s)
            RETURNING id
            """,
            (memory_id, allow_global, group_id),
        )
        return bool(rows)

    def delete_user(self, group_id: str, user_id: str) -> int:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET status = 'deleted', updated_at = now()
            WHERE status = 'active'
              AND group_id = %s
              AND user_id = %s
            RETURNING id
            """,
            (group_id, user_id),
        )
        return len(rows)

    def delete_group(self, group_id: str) -> int:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET status = 'deleted', updated_at = now()
            WHERE status = 'active'
              AND group_id = %s
            RETURNING id
            """,
            (group_id,),
        )
        return len(rows)

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self.database_url:
            raise MemoryConfigurationError("DATABASE_URL is not configured")

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise MemoryConfigurationError("psycopg is required for memory") from exc

        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
        except psycopg.errors.UndefinedTable as exc:
            raise MemoryConfigurationError("memory tables are missing; run database migrations") from exc
        except psycopg.Error as exc:
            raise MemoryError(f"memory database error: {exc}") from exc


def handle_memory_command(request: ChatRequest, text: str) -> BrainResponse | None:
    invocation = parse_command_invocation(text, ("memory", "记忆"))
    if invocation is None:
        return None

    if not _is_memory_admin(request):
        return _text_response("需要管理员权限。", {"module": "memory", "error": "permission_denied"})

    store = PostgresMemoryStore.from_env()
    if not store.enabled:
        return _text_response("记忆数据库未配置 DATABASE_URL。", {"module": "memory", "error": "missing_database_url"})

    try:
        return _handle_admin_command(store, request, invocation.argument)
    except MemoryError as exc:
        logger.warning("memory command failed: %s", exc)
        return _text_response(f"记忆模块不可用：{exc}", {"module": "memory", "error": "memory_unavailable"})


def recall_context(request: ChatRequest, text: str) -> dict[str, Any]:
    if not memory_runtime_enabled():
        return {"memories": [], "recent_messages": []}
    store = PostgresMemoryStore.from_env()
    if not store.enabled:
        return {"memories": [], "recent_messages": []}

    try:
        group_id = _string_id(request.group_id)
        if group_id and not store.group_memory_enabled(group_id):
            return {"memories": [], "recent_messages": []}

        return {
            "memories": [memory_to_dict(item) for item in store.recall(request, text)],
            "recent_messages": [_recent_message_to_dict(row) for row in store.recent_messages(request)],
        }
    except MemoryError as exc:
        logger.warning("memory recall skipped: %s", exc)
        return {"memories": [], "recent_messages": []}


def memory_runtime_enabled() -> bool:
    raw = os.getenv("MEMORY_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _handle_admin_command(store: PostgresMemoryStore, request: ChatRequest, argument: str) -> BrainResponse:
    group_id = _string_id(request.group_id)
    parts = argument.split()
    command = parts[0].lower() if parts else "status"

    if command == "status":
        count = store.count_active(group_id)
        enabled = store.group_memory_enabled(group_id) if group_id else True
        return _text_response(
            f"记忆状态：{'启用' if enabled else '禁用'}，当前范围 active memory={count}",
            {"module": "memory", "command": "status", "count": count, "enabled": enabled},
        )

    if command == "search" and len(parts) >= 2:
        records = store.search(" ".join(parts[1:]), group_id=group_id, user_id=_string_id(request.user_id))
        return _records_response(records, "搜索结果", {"module": "memory", "command": "search"})

    if command == "user" and len(parts) >= 2:
        if not group_id:
            return _text_response("只有群聊可以查询用户记忆。", {"module": "memory", "error": "group_required"})
        records = store.list_user(group_id, parts[1])
        return _records_response(records, f"用户 {parts[1]} 的记忆", {"module": "memory", "command": "user"})

    if command == "forget" and len(parts) >= 2 and parts[1].isdigit():
        deleted = store.delete_memory(
            int(parts[1]),
            group_id=group_id,
            allow_global=_is_configured_memory_admin(request),
        )
        return _text_response(
            "已删除。" if deleted else "没有找到可删除的记忆。",
            {"module": "memory", "command": "forget", "deleted": deleted},
        )

    if command == "forget-user" and len(parts) >= 2:
        if not group_id:
            return _text_response("只有群聊可以删除用户记忆。", {"module": "memory", "error": "group_required"})
        count = store.delete_user(group_id, parts[1])
        return _text_response(f"已删除 {count} 条用户记忆。", {"module": "memory", "command": "forget-user", "count": count})

    if command == "forget-group":
        if not group_id:
            return _text_response("只有群聊可以删除群记忆。", {"module": "memory", "error": "group_required"})
        count = store.delete_group(group_id)
        return _text_response(f"已删除 {count} 条群记忆。", {"module": "memory", "command": "forget-group", "count": count})

    if command in {"enable", "disable"}:
        if not group_id:
            return _text_response("只有群聊可以启用或禁用群记忆。", {"module": "memory", "error": "group_required"})
        enabled = command == "enable"
        store.set_group_memory_enabled(group_id, enabled)
        return _text_response(
            f"群记忆已{'启用' if enabled else '禁用'}。",
            {"module": "memory", "command": command, "enabled": enabled},
        )

    return _text_response(
        "记忆命令：/memory status | search <关键词> | user <QQ> | forget <id> | forget-user <QQ> | forget-group | enable | disable",
        {"module": "memory", "command": "help"},
    )


def _records_response(records: list[MemoryRecord], title: str, metadata: dict[str, Any]) -> BrainResponse:
    if not records:
        return _text_response(f"{title}：无", {**metadata, "count": 0})
    lines = [f"{title}："]
    for record in records:
        lines.append(
            f"#{record.id} [{record.scope}/{record.memory_type}] "
            f"c={record.confidence:.2f} i={record.importance:.2f} {record.content}"
        )
    return _text_response("\n".join(lines), {**metadata, "count": len(records)})


def _text_response(text: str, metadata: dict[str, Any]) -> BrainResponse:
    return BrainResponse(
        handled=True,
        should_reply=bool(text),
        reply=text,
        messages=[BrainMessage(type="text", text=text)] if text else [],
        metadata=metadata,
    )


def _is_memory_admin(request: ChatRequest) -> bool:
    if _is_configured_memory_admin(request):
        return True
    role = (request.sender.role if request.sender is not None else "").strip().lower()
    return role in ADMIN_ROLES


def _is_configured_memory_admin(request: ChatRequest) -> bool:
    user_id = _string_id(request.user_id)
    admin_ids = _id_set(os.getenv("MEMORY_ADMIN_USER_IDS", ""))
    return bool(user_id and user_id in admin_ids)


def _memory_scope_filter() -> str:
    return """
              (
                scope = 'global'
                OR (%s <> '' AND scope = 'group' AND group_id = %s)
                OR (%s <> '' AND scope = 'user' AND group_id = %s AND %s <> '' AND user_id = %s)
                OR (
                    %s <> ''
                    AND scope = 'relationship'
                    AND group_id = %s
                    AND %s <> ''
                    AND (user_id = %s OR target_user_id = %s)
                )
              )
    """


def _memory_scope_params(group_id: str, user_id: str) -> tuple[str, ...]:
    return (
        group_id,
        group_id,
        group_id,
        group_id,
        user_id,
        user_id,
        group_id,
        group_id,
        user_id,
        user_id,
        user_id,
    )


def _id_set(raw: str) -> set[str]:
    return {part for part in re.split(r"[\s,;]+", raw.strip()) if part}


def _keywords(text: str) -> list[str]:
    values = re.findall(r"[\w\u4e00-\u9fff]{2,}", text)
    return values[:6]


def _conversation_key(request: ChatRequest) -> tuple[str, str]:
    message_type = (request.message_type or "").strip().lower()
    group_id = _string_id(request.group_id)
    user_id = _string_id(request.user_id)
    if message_type == "group" or group_id:
        return "group", group_id
    if message_type == "private" or user_id:
        return "private", user_id
    return "", ""


def _row_to_memory(row: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        id=int(row["id"]),
        scope=str(row["scope"]),
        memory_type=str(row["memory_type"]),
        content=str(row["content"]),
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        group_id=_string_id(row.get("group_id")),
        user_id=_string_id(row.get("user_id")),
        target_user_id=_string_id(row.get("target_user_id")),
    )


def memory_to_dict(record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "scope": record.scope,
        "memory_type": record.memory_type,
        "content": record.content,
        "confidence": record.confidence,
        "importance": record.importance,
        "group_id": record.group_id,
        "user_id": record.user_id,
        "target_user_id": record.target_user_id,
    }


def _recent_message_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    sender = row.get("sender_card") or row.get("sender_nickname") or row.get("sender_user_id") or ""
    return {
        "sender": str(sender),
        "user_id": _string_id(row.get("sender_user_id")),
        "text": str(row.get("text") or ""),
        "primary_type": str(row.get("primary_type") or ""),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") is not None else "",
    }


def _string_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
