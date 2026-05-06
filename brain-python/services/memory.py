import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from modules.base import parse_command_invocation
from schemas import BrainMessage, BrainResponse, ChatRequest, OutboxEnqueueRequest
from services.outbox import OutboxError, PostgresOutboxStore


logger = logging.getLogger(__name__)

ADMIN_ROLES = {"admin", "owner"}
DEFAULT_RECENT_LIMIT = 30
DEFAULT_MEMORY_LIMIT = 8
VALID_MEMORY_TYPES = {"preference", "fact", "style", "relationship", "topic", "summary", "warning"}
VALID_MEMORY_CLASSES = {"episodic", "semantic", "procedural", "affective", "social", "persona"}
VALID_LIFECYCLE_STATUSES = {"weak", "confirmed", "reinforced", "stale", "contradicted", "archived"}
RECALL_LIFECYCLE_STATUSES = ("confirmed", "reinforced")
DECAY_LIFECYCLE_STATUSES = ("weak", "confirmed", "reinforced")


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
    status: str = "active"
    memory_class: str = ""
    lifecycle_status: str = "confirmed"
    stability: float = 0.5
    decay_score: float = 1.0
    contradiction_count: int = 0
    source_count: int = 1
    quality_score: float = 0.5
    last_confirmed_at: datetime | None = None
    archived_at: datetime | None = None
    last_seen_at: datetime | None = None
    evidence_message_ids: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_class = class_for_type(self.memory_type) if not self.memory_class else self.memory_class
        if self.memory_class not in VALID_MEMORY_CLASSES:
            self.memory_class = class_for_type(self.memory_type)
        if self.lifecycle_status not in VALID_LIFECYCLE_STATUSES:
            self.lifecycle_status = "archived" if self.status == "archived" else "confirmed"
        self.confidence = _clamp(self.confidence)
        self.importance = _clamp(self.importance)
        self.stability = _clamp(self.stability)
        self.decay_score = _clamp(self.decay_score)
        self.quality_score = _clamp(self.quality_score)
        self.contradiction_count = max(0, _int_value(self.contradiction_count, 0))
        self.source_count = max(1, _int_value(self.source_count or len(self.evidence_message_ids) or 1, 1))


@dataclass(frozen=True)
class MemoryScore:
    total: float
    keyword_match: float
    entity_relevance: float
    scope_relevance: float
    quality_score: float
    recency_weight: float


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
              AND COALESCE(lifecycle_status, 'confirmed') <> 'archived'
              AND (%s = '' OR group_id = %s OR scope = 'global')
            """,
            (group_id, group_id),
        )
        return int(rows[0]["count"]) if rows else 0

    def search(
        self,
        query: str,
        *,
        group_id: str = "",
        user_id: str = "",
        limit: int = 10,
        status: str = "active",
    ) -> list[MemoryRecord]:
        like = f"%{query}%"
        status_sql, status_params = _memory_status_filter(status)
        rows = self._fetch_all(
            f"""
            SELECT *
            FROM memory_items
            WHERE {status_sql}
              AND content ILIKE %s
              AND {_memory_scope_filter()}
            ORDER BY quality_score DESC, importance DESC, confidence DESC, last_seen_at DESC, id DESC
            LIMIT %s
            """,
            (*status_params, like, *_memory_scope_params(group_id, user_id), limit),
        )
        return [_row_to_memory(row) for row in rows]

    def recall(self, request: ChatRequest, text: str, *, limit: int = DEFAULT_MEMORY_LIMIT) -> list[MemoryRecord]:
        scored = self.debug_recall(request, text, limit=max(limit, 50), include_ineligible=False)
        return [record for record, _score in scored[:limit]]

    def debug_recall(
        self,
        request: ChatRequest,
        text: str,
        *,
        limit: int = 10,
        include_ineligible: bool = True,
    ) -> list[tuple[MemoryRecord, MemoryScore]]:
        group_id = _string_id(request.group_id)
        user_id = _string_id(request.user_id)
        keywords = _keywords(text)
        status_sql = "status <> 'deleted'" if include_ineligible else _recall_status_filter()
        candidate_limit = max(limit, 50)
        if not keywords:
            rows = self._fetch_all(
                f"""
                SELECT *
                FROM memory_items
                WHERE {status_sql}
                  AND {_memory_scope_filter()}
                ORDER BY quality_score DESC, importance DESC, confidence DESC, last_seen_at DESC, id DESC
                LIMIT %s
                """,
                (*_memory_scope_params(group_id, user_id), candidate_limit),
            )
        else:
            clauses = " OR ".join(["content ILIKE %s" for _ in keywords])
            rows = self._fetch_all(
                f"""
                SELECT *
                FROM memory_items
                WHERE {status_sql}
                  AND ({clauses})
                  AND {_memory_scope_filter()}
                ORDER BY quality_score DESC, importance DESC, confidence DESC, last_seen_at DESC, id DESC
                LIMIT %s
                """,
                tuple(f"%{keyword}%" for keyword in keywords)
                + (*_memory_scope_params(group_id, user_id), candidate_limit),
            )

        scored: list[tuple[MemoryRecord, MemoryScore]] = []
        for row in rows:
            record = _row_to_memory(row)
            if include_ineligible or recall_eligible(record):
                scored.append((record, memory_score(record, request, keywords)))
        scored.sort(key=lambda item: (item[1].total, item[0].quality_score, _timestamp(item[0].last_seen_at)), reverse=True)
        return scored[:limit]

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

    def recent_group_messages_for_extraction(self, group_id: str, *, limit: int) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            SELECT
                messages.id,
                messages.conversation_id,
                messages.sender_user_id,
                messages.sender_nickname,
                messages.sender_card,
                messages.text,
                messages.created_at
            FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            WHERE conversations.conversation_type = 'group'
              AND conversations.external_id = %s
              AND COALESCE(messages.text, '') <> ''
            ORDER BY messages.created_at DESC, messages.id DESC
            LIMIT %s
            """,
            (group_id, limit),
        )
        return list(reversed(rows))

    def list_user(self, group_id: str, user_id: str, *, limit: int = 20, status: str = "active") -> list[MemoryRecord]:
        status_sql, status_params = _memory_status_filter(status)
        rows = self._fetch_all(
            f"""
            SELECT *
            FROM memory_items
            WHERE {status_sql}
              AND group_id = %s
              AND user_id = %s
            ORDER BY quality_score DESC, importance DESC, confidence DESC, last_seen_at DESC
            LIMIT %s
            """,
            (*status_params, group_id, user_id, limit),
        )
        return [_row_to_memory(row) for row in rows]

    def get_memory(self, memory_id: int, *, group_id: str = "", allow_global: bool = False) -> MemoryRecord | None:
        rows = self._fetch_all(
            """
            SELECT *
            FROM memory_items
            WHERE id = %s
              AND status <> 'deleted'
              AND (%s OR group_id = %s)
            LIMIT 1
            """,
            (memory_id, allow_global, group_id),
        )
        return _row_to_memory(rows[0]) if rows else None

    def lifecycle_counts(self, group_id: str = "") -> dict[str, int]:
        rows = self._fetch_all(
            """
            SELECT COALESCE(lifecycle_status, 'confirmed') AS lifecycle_status, count(*) AS count
            FROM memory_items
            WHERE status <> 'deleted'
              AND (%s = '' OR group_id = %s OR scope = 'global')
            GROUP BY COALESCE(lifecycle_status, 'confirmed')
            """,
            (group_id, group_id),
        )
        counts = {status: 0 for status in sorted(VALID_LIFECYCLE_STATUSES)}
        for row in rows:
            counts[str(row["lifecycle_status"])] = int(row["count"])
        return counts

    def confirm_memory(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET
                status = 'active',
                lifecycle_status = 'confirmed',
                last_confirmed_at = now(),
                stability = GREATEST(stability, 0.65),
                decay_score = 1.0,
                quality_score = """ + _quality_score_sql(stability_sql="GREATEST(stability, 0.65)", decay_sql="1.0") + """,
                metadata = metadata || %s,
                updated_at = now()
            WHERE id = %s
              AND status <> 'deleted'
              AND (%s OR group_id = %s)
            RETURNING id
            """,
            (_jsonb(_admin_lifecycle_metadata("confirm", actor_id)), memory_id, allow_global, group_id),
        )
        return bool(rows)

    def archive_memory(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET
                status = 'archived',
                lifecycle_status = 'archived',
                archived_at = now(),
                metadata = metadata || %s,
                updated_at = now()
            WHERE id = %s
              AND status <> 'deleted'
              AND (%s OR group_id = %s)
            RETURNING id
            """,
            (_jsonb(_admin_lifecycle_metadata("archive", actor_id)), memory_id, allow_global, group_id),
        )
        return bool(rows)

    def mark_stale(
        self,
        memory_id: int,
        *,
        group_id: str = "",
        allow_global: bool = False,
        actor_id: str = "",
    ) -> bool:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET
                lifecycle_status = 'stale',
                quality_score = """ + _quality_score_sql() + """,
                metadata = metadata || %s,
                updated_at = now()
            WHERE id = %s
              AND status = 'active'
              AND (%s OR group_id = %s)
            RETURNING id
            """,
            (_jsonb(_admin_lifecycle_metadata("stale", actor_id)), memory_id, allow_global, group_id),
        )
        return bool(rows)

    def apply_decay(self, *, group_id: str = "", days: int = 0, limit: int = 500) -> dict[str, int]:
        rows = self._fetch_all(
            """
            SELECT *
            FROM memory_items
            WHERE status = 'active'
              AND COALESCE(lifecycle_status, 'confirmed') IN ('weak', 'confirmed', 'reinforced')
              AND (%s = '' OR group_id = %s OR scope = 'global')
            ORDER BY last_seen_at ASC, id ASC
            LIMIT %s
            """,
            (group_id, group_id, limit),
        )
        now = datetime.now(timezone.utc)
        result = {"scanned": len(rows), "stale": 0, "archived": 0}

        for row in rows:
            record = _row_to_memory(row)
            age_days = _age_days(record.last_seen_at, now) + max(0, days)
            record.decay_score = decay_score_for(record.memory_class, age_days)
            new_status = record.status
            new_lifecycle = record.lifecycle_status
            archived = False

            if record.lifecycle_status == "weak" and age_days > 14:
                new_status = "archived"
                new_lifecycle = "archived"
                archived = True
                result["archived"] += 1
            elif record.lifecycle_status == "confirmed" and record.decay_score < 0.25:
                new_lifecycle = "stale"
                result["stale"] += 1
            elif record.lifecycle_status == "reinforced" and record.decay_score < 0.15:
                new_lifecycle = "stale"
                result["stale"] += 1

            record.status = new_status
            record.lifecycle_status = new_lifecycle
            record.quality_score = compute_quality_score(record)
            self._fetch_all(
                """
                UPDATE memory_items
                SET
                    status = %s,
                    lifecycle_status = %s,
                    decay_score = %s,
                    quality_score = %s,
                    archived_at = CASE WHEN %s THEN COALESCE(archived_at, now()) ELSE archived_at END,
                    updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (
                    record.status,
                    record.lifecycle_status,
                    record.decay_score,
                    record.quality_score,
                    archived,
                    record.id,
                ),
            )

        return result

    def create_memory_run(
        self,
        *,
        group_id: str,
        conversation_id: int | None,
        input_message_ids: list[int],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        rows = self._fetch_all(
            """
            INSERT INTO memory_runs (
                conversation_id,
                group_id,
                status,
                model,
                input_message_ids,
                metadata
            )
            VALUES (%s, %s, 'running', %s, %s, %s)
            RETURNING id
            """,
            (
                conversation_id,
                group_id,
                model,
                _jsonb(input_message_ids),
                _jsonb(metadata or {}),
            ),
        )
        return int(rows[0]["id"])

    def finish_memory_run(
        self,
        run_id: int,
        *,
        status: str,
        output_memory_ids: list[int] | None = None,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._fetch_all(
            """
            UPDATE memory_runs
            SET
                status = %s,
                finished_at = now(),
                output_memory_ids = %s,
                error = NULLIF(%s, ''),
                metadata = metadata || %s
            WHERE id = %s
            RETURNING id
            """,
            (
                status,
                _jsonb(output_memory_ids or []),
                error,
                _jsonb(metadata or {}),
                run_id,
            ),
        )

    def upsert_extracted_memory(self, item: dict[str, Any]) -> tuple[int, str]:
        self._mark_contradicted_memory(item)
        normalized_content = _normalize_memory_content(item["content"])
        memory_class = _memory_class_from_item(item)
        existing = self._find_matching_memory(item, normalized_content)
        metadata = {
            **dict(item.get("metadata") or {}),
            "normalized_content": normalized_content,
            "extractor": "memory-extractor-mvp",
        }

        if existing is not None:
            existing_record = _row_to_memory(existing)
            evidence = _merge_evidence_ids(existing.get("evidence_message_ids"), item["evidence_message_ids"])
            had_new_evidence = len(evidence) > len(_evidence_values(existing.get("evidence_message_ids")))
            existing_metadata = existing.get("metadata")
            if not isinstance(existing_metadata, dict):
                existing_metadata = {}
            confidence = max(existing_record.confidence, _float_value(item.get("confidence"), 0.5))
            stability = existing_record.stability
            last_confirmed_sql = "last_confirmed_at"
            if had_new_evidence:
                confidence = _clamp(confidence + 0.03)
                stability = _clamp(stability + 0.05)
                last_confirmed_sql = "now()"
            importance = max(existing_record.importance, _float_value(item.get("importance"), 0.5))
            lifecycle_status = _reinforced_lifecycle_status(
                existing_record.lifecycle_status,
                memory_type=str(item.get("memory_type") or existing_record.memory_type),
                confidence=confidence,
                importance=importance,
                source_count=len(evidence),
                stability=stability,
            )
            updated_record = MemoryRecord(
                id=existing_record.id,
                scope=existing_record.scope,
                memory_type=existing_record.memory_type,
                memory_class=memory_class,
                content=existing_record.content,
                confidence=confidence,
                importance=importance,
                group_id=existing_record.group_id,
                user_id=existing_record.user_id,
                target_user_id=existing_record.target_user_id,
                status="active",
                lifecycle_status=lifecycle_status,
                stability=stability,
                decay_score=1.0,
                contradiction_count=existing_record.contradiction_count,
                source_count=len(evidence),
                evidence_message_ids=evidence,
            )
            quality_score = compute_quality_score(updated_record)
            rows = self._fetch_all(
                f"""
                UPDATE memory_items
                SET
                    memory_class = %s,
                    confidence = %s,
                    importance = %s,
                    evidence_message_ids = %s,
                    source_count = %s,
                    stability = %s,
                    decay_score = 1.0,
                    lifecycle_status = %s,
                    quality_score = %s,
                    last_confirmed_at = {last_confirmed_sql},
                    metadata = %s,
                    last_seen_at = now(),
                    updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (
                    memory_class,
                    confidence,
                    importance,
                    _jsonb(evidence),
                    len(evidence),
                    stability,
                    lifecycle_status,
                    quality_score,
                    _jsonb({**existing_metadata, **metadata}),
                    int(existing["id"]),
                ),
            )
            return int(rows[0]["id"]), "updated"

        evidence = _evidence_values(item.get("evidence_message_ids"))
        source_count = max(1, len(evidence))
        confidence = _float_value(item.get("confidence"), 0.5)
        importance = _float_value(item.get("importance"), 0.5)
        stability = _float_value(item.get("stability"), 0.5)
        lifecycle_status = initial_lifecycle_status({**item, "memory_class": memory_class})
        record = MemoryRecord(
            id=0,
            scope=str(item["scope"]),
            group_id=_string_id(item.get("group_id")),
            user_id=_string_id(item.get("user_id")),
            target_user_id=_string_id(item.get("target_user_id")),
            memory_class=memory_class,
            memory_type=str(item["memory_type"]),
            content=str(item["content"]),
            confidence=confidence,
            importance=importance,
            lifecycle_status=lifecycle_status,
            stability=stability,
            decay_score=1.0,
            source_count=source_count,
            evidence_message_ids=evidence,
        )
        quality_score = compute_quality_score(record)
        last_confirmed = "now()" if lifecycle_status in RECALL_LIFECYCLE_STATUSES else "NULL"
        rows = self._fetch_all(
            f"""
            INSERT INTO memory_items (
                scope,
                group_id,
                user_id,
                target_user_id,
                memory_class,
                memory_type,
                content,
                confidence,
                importance,
                evidence_message_ids,
                metadata,
                lifecycle_status,
                stability,
                decay_score,
                contradiction_count,
                source_count,
                quality_score,
                last_confirmed_at,
                created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {last_confirmed}, 'extractor')
            RETURNING id
            """,
            (
                item["scope"],
                item["group_id"] or None,
                item["user_id"] or None,
                item["target_user_id"] or None,
                memory_class,
                item["memory_type"],
                item["content"],
                confidence,
                importance,
                _jsonb(evidence),
                _jsonb(metadata),
                lifecycle_status,
                stability,
                1.0,
                0,
                source_count,
                quality_score,
            ),
        )
        return int(rows[0]["id"]), "inserted"

    def _mark_contradicted_memory(self, item: dict[str, Any]) -> None:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        conflict_id = _int_value(metadata.get("conflicts_with_memory_id"), 0)
        group_id = _string_id(item.get("group_id"))
        if conflict_id <= 0 or not group_id:
            return

        contradiction_metadata = {
            "last_contradiction": {
                "candidate_content": str(item.get("content") or ""),
                "evidence_message_ids": _evidence_values(item.get("evidence_message_ids")),
                "conflicts_with": metadata.get("conflicts_with"),
                "at": datetime.now(timezone.utc).isoformat(),
            }
        }
        self._fetch_all(
            f"""
            UPDATE memory_items
            SET
                lifecycle_status = 'contradicted',
                contradiction_count = contradiction_count + 1,
                quality_score = {_quality_score_sql(contradiction_sql="contradiction_count + 1")},
                metadata = metadata || %s,
                updated_at = now()
            WHERE id = %s
              AND status = 'active'
              AND COALESCE(group_id, '') = %s
            RETURNING id
            """,
            (_jsonb(contradiction_metadata), conflict_id, group_id),
        )

    def _find_matching_memory(self, item: dict[str, Any], normalized_content: str) -> dict[str, Any] | None:
        memory_class = _memory_class_from_item(item)
        rows = self._fetch_all(
            """
            SELECT *
            FROM memory_items
            WHERE status = 'active'
              AND scope = %s
              AND COALESCE(group_id, '') = %s
              AND COALESCE(user_id, '') = %s
              AND COALESCE(target_user_id, '') = %s
              AND COALESCE(memory_class, %s) = %s
              AND memory_type = %s
              AND COALESCE(lifecycle_status, 'confirmed') <> 'archived'
            ORDER BY last_seen_at DESC, id DESC
            LIMIT 100
            """,
            (
                item["scope"],
                item["group_id"],
                item["user_id"],
                item["target_user_id"],
                memory_class,
                memory_class,
                item["memory_type"],
            ),
        )
        for row in rows:
            metadata = row.get("metadata")
            metadata_normalized = ""
            if isinstance(metadata, dict):
                metadata_normalized = str(metadata.get("normalized_content") or "")
            if metadata_normalized == normalized_content or _normalize_memory_content(row.get("content")) == normalized_content:
                return row
        return None

    def delete_memory(self, memory_id: int, *, group_id: str = "", allow_global: bool = False) -> bool:
        rows = self._fetch_all(
            """
            UPDATE memory_items
            SET
                status = 'deleted',
                lifecycle_status = 'archived',
                archived_at = COALESCE(archived_at, now()),
                updated_at = now()
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
            SET
                status = 'deleted',
                lifecycle_status = 'archived',
                archived_at = COALESCE(archived_at, now()),
                updated_at = now()
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
            SET
                status = 'deleted',
                lifecycle_status = 'archived',
                archived_at = COALESCE(archived_at, now()),
                updated_at = now()
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
    return _env_bool("MEMORY_ENABLED", True)


def _recall_lifecycle_filter_enabled() -> bool:
    return _env_bool("MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED", True)


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
        parsed = _parse_search_parts(parts[1:])
        if parsed is None:
            return _text_response(
                "用法：/memory search <关键词> [--status weak|confirmed|reinforced|stale|contradicted|archived|all]",
                {"module": "memory", "command": "search", "error": "invalid_args"},
            )
        query, status, explicit_status = parsed
        if explicit_status:
            records = store.search(query, group_id=group_id, user_id=_string_id(request.user_id), status=status)
        else:
            records = store.search(query, group_id=group_id, user_id=_string_id(request.user_id))
        return _records_response(records, "搜索结果", {"module": "memory", "command": "search", "status": status})

    if command == "show" and len(parts) >= 2 and parts[1].isdigit():
        record = store.get_memory(
            int(parts[1]),
            group_id=group_id,
            allow_global=_is_configured_memory_admin(request),
        )
        if record is None:
            return _text_response("没有找到记忆。", {"module": "memory", "command": "show", "found": False})
        return _memory_detail_response(record)

    if command == "debug" and len(parts) >= 3 and parts[1].lower() == "recall":
        return _debug_recall_response(store, request, " ".join(parts[2:]))

    if command == "lifecycle":
        return _handle_lifecycle_command(store, request, parts[1:])

    if command in {"confirm", "archive", "stale", "decay"}:
        return _handle_lifecycle_command(store, request, parts)

    if command == "user" and len(parts) >= 2:
        if not group_id:
            return _text_response("只有群聊可以查询用户记忆。", {"module": "memory", "error": "group_required"})
        records = store.list_user(group_id, parts[1])
        return _records_response(records, f"用户 {parts[1]} 的记忆", {"module": "memory", "command": "user"})

    if command == "extract":
        if not group_id:
            return _text_response("只有群聊可以抽取记忆。", {"module": "memory", "error": "group_required"})
        limit = _extract_limit_arg(parts[1:])
        if limit is None and len(parts) >= 2:
            return _text_response("数量必须是 10 到 200 之间的整数。", {"module": "memory", "error": "invalid_limit"})
        return _handle_extract_command(store, group_id, limit)

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
        "记忆命令：/memory status | show <id> | search <关键词> [--status ...] | user <QQ> | lifecycle status|confirm|archive|stale|decay | debug recall <文本> | extract [数量] | forget <id> | forget-user <QQ> | forget-group | enable | disable",
        {"module": "memory", "command": "help"},
    )


def _handle_lifecycle_command(store: PostgresMemoryStore, request: ChatRequest, parts: list[str]) -> BrainResponse:
    group_id = _string_id(request.group_id)
    actor_id = _string_id(request.user_id)
    allow_global = _is_configured_memory_admin(request)
    command = parts[0].lower() if parts else "status"

    if command == "status":
        counts = store.lifecycle_counts(group_id)
        return _lifecycle_counts_response(counts)

    if command in {"confirm", "archive", "stale"}:
        if len(parts) < 2 or not parts[1].isdigit():
            return _text_response(
                "用法：/memory lifecycle confirm|archive|stale <id>",
                {"module": "memory", "command": "lifecycle", "error": "invalid_id"},
            )
        memory_id = int(parts[1])
        if command == "confirm":
            changed = store.confirm_memory(memory_id, group_id=group_id, allow_global=allow_global, actor_id=actor_id)
            message = "已确认。" if changed else "没有找到可确认的记忆。"
        elif command == "archive":
            changed = store.archive_memory(memory_id, group_id=group_id, allow_global=allow_global, actor_id=actor_id)
            message = "已归档。" if changed else "没有找到可归档的记忆。"
        else:
            changed = store.mark_stale(memory_id, group_id=group_id, allow_global=allow_global, actor_id=actor_id)
            message = "已标记为 stale。" if changed else "没有找到可标记的记忆。"
        return _text_response(
            message,
            {"module": "memory", "command": "lifecycle", "action": command, "id": memory_id, "changed": changed},
        )

    if command == "decay":
        days = 0
        if len(parts) >= 2:
            if not parts[1].isdigit():
                return _text_response("天数必须是非负整数。", {"module": "memory", "command": "lifecycle", "error": "invalid_days"})
            days = int(parts[1])
        result = store.apply_decay(group_id=group_id, days=days)
        return _text_response(
            f"记忆衰减完成：扫描 {result['scanned']} 条，置为 stale {result['stale']} 条，归档 {result['archived']} 条。",
            {"module": "memory", "command": "lifecycle", "action": "decay", **result, "days": days},
        )

    return _text_response(
        "用法：/memory lifecycle status|confirm <id>|archive <id>|stale <id>|decay [days]",
        {"module": "memory", "command": "lifecycle", "error": "unknown_action"},
    )


def _lifecycle_counts_response(counts: dict[str, int]) -> BrainResponse:
    ordered = ["weak", "confirmed", "reinforced", "stale", "contradicted", "archived"]
    lines = ["记忆生命周期："]
    for status in ordered:
        lines.append(f"{status}: {counts.get(status, 0)}")
    return _text_response(
        "\n".join(lines),
        {"module": "memory", "command": "lifecycle", "action": "status", "counts": counts},
    )


def _memory_detail_response(record: MemoryRecord) -> BrainResponse:
    lines = [
        f"记忆 #{record.id}",
        f"scope={record.scope} group={record.group_id or '-'} user={record.user_id or '-'} target={record.target_user_id or '-'}",
        f"class/type={record.memory_class}/{record.memory_type}",
        f"status={record.status} lifecycle={record.lifecycle_status}",
        (
            f"confidence={record.confidence:.2f} importance={record.importance:.2f} "
            f"stability={record.stability:.2f} decay={record.decay_score:.2f} quality={record.quality_score:.2f}"
        ),
        f"sources={record.source_count} contradictions={record.contradiction_count} evidence={record.evidence_message_ids}",
        f"content={record.content}",
    ]
    return _text_response(
        "\n".join(lines),
        {"module": "memory", "command": "show", "id": record.id, "found": True},
    )


def _debug_recall_response(store: PostgresMemoryStore, request: ChatRequest, text: str) -> BrainResponse:
    scored = store.debug_recall(request, text, limit=10, include_ineligible=True)
    if not scored:
        return _text_response("召回调试：无候选", {"module": "memory", "command": "debug_recall", "count": 0})

    lines = ["召回调试："]
    for record, score in scored:
        eligible = "yes" if recall_eligible(record) else "no"
        lines.append(
            f"#{record.id} score={score.total:.2f} eligible={eligible} lifecycle={record.lifecycle_status} "
            f"keyword={score.keyword_match:.2f} entity={score.entity_relevance:.2f} scope={score.scope_relevance:.2f} "
            f"quality={score.quality_score:.2f} recency={score.recency_weight:.2f} {record.content}"
        )
    return _text_response(
        "\n".join(lines),
        {"module": "memory", "command": "debug_recall", "count": len(scored)},
    )


def _handle_extract_command(
    store: PostgresMemoryStore,
    group_id: str,
    limit: int | None,
) -> BrainResponse:
    if not store.group_memory_enabled(group_id):
        return _text_response("当前群记忆已禁用。", {"module": "memory", "command": "extract", "error": "group_disabled"})

    from services import memory_extractor

    try:
        config = memory_extractor.config_from_env()
    except memory_extractor.MemoryExtractorConfigurationError as exc:
        return _text_response(f"记忆抽取配置不可用：{exc}", {"module": "memory", "command": "extract", "error": "configuration"})

    job_id = _memory_extract_job_id(group_id, limit)
    worker = threading.Thread(
        target=_run_extract_background,
        args=(group_id, limit, config, job_id),
        daemon=True,
        name=f"memory-extract-{group_id}",
    )
    worker.start()

    count_text = str(limit) if limit else f"默认 {config['batch_size']}"
    return _text_response(
        f"记忆抽取已开始，正在处理当前群最近 {count_text} 条文本消息。完成后会在群里通知。",
        {
            "module": "memory",
            "command": "extract",
            "status": "queued",
            "job_id": job_id,
            "limit": limit or config["batch_size"],
            "async": True,
        },
        job_id=job_id,
    )


def _run_extract_background(group_id: str, limit: int | None, config: dict[str, Any], job_id: str) -> None:
    from services import memory_extractor

    store = PostgresMemoryStore.from_env()
    try:
        result = memory_extractor.extract_group_memories(store, group_id, limit=limit, config=config)
        text = (
            f"记忆抽取完成：run #{result.run_id}，新增 {result.inserted_count} 条，"
            f"更新 {result.updated_count} 条，跳过 {result.skipped_count} 条。"
        )
        _enqueue_memory_extract_notice(group_id, text, {"job_id": job_id, "run_id": result.run_id, "status": "succeeded"})
    except memory_extractor.MemoryExtractorNoMessagesError:
        _enqueue_memory_extract_notice(group_id, "记忆抽取结束：没有可抽取的群聊文本消息。", {"job_id": job_id, "status": "no_messages"})
    except memory_extractor.MemoryExtractorError as exc:
        logger.warning("memory extraction failed in background: %s", exc)
        _enqueue_memory_extract_notice(group_id, f"记忆抽取失败：{exc}", {"job_id": job_id, "status": "failed"})
    except Exception as exc:  # pragma: no cover - background worker must not crash the app.
        logger.exception("unexpected memory extraction background failure")
        _enqueue_memory_extract_notice(group_id, f"记忆抽取失败：{exc}", {"job_id": job_id, "status": "failed"})


def _enqueue_memory_extract_notice(group_id: str, text: str, metadata: dict[str, Any]) -> None:
    try:
        PostgresOutboxStore.from_env().enqueue(
            OutboxEnqueueRequest(
                message_type="group",
                group_id=group_id,
                messages=[BrainMessage(type="text", text=text)],
                metadata={"module": "memory", "command": "extract", **metadata},
            )
        )
    except OutboxError as exc:
        logger.warning("memory extraction notice enqueue failed: %s", exc)


def _records_response(records: list[MemoryRecord], title: str, metadata: dict[str, Any]) -> BrainResponse:
    if not records:
        return _text_response(f"{title}：无", {**metadata, "count": 0})
    lines = [f"{title}："]
    for record in records:
        lines.append(
            f"#{record.id} [{record.scope}/{record.memory_type}/{record.lifecycle_status}] "
            f"c={record.confidence:.2f} i={record.importance:.2f} q={record.quality_score:.2f} {record.content}"
        )
    return _text_response("\n".join(lines), {**metadata, "count": len(records)})


def _text_response(text: str, metadata: dict[str, Any], *, job_id: str | None = None) -> BrainResponse:
    return BrainResponse(
        handled=True,
        should_reply=bool(text),
        reply=text,
        messages=[BrainMessage(type="text", text=text)] if text else [],
        job_id=job_id,
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


def _parse_search_parts(parts: list[str]) -> tuple[str, str, bool] | None:
    query_parts: list[str] = []
    status = "active"
    explicit_status = False
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--status":
            if index + 1 >= len(parts):
                return None
            status = parts[index + 1].strip().lower()
            explicit_status = True
            if status != "all" and status not in VALID_LIFECYCLE_STATUSES:
                return None
            index += 2
            continue
        query_parts.append(part)
        index += 1

    query = " ".join(query_parts).strip()
    if not query:
        return None
    return query, status, explicit_status


def _extract_limit_arg(parts: list[str]) -> int | None:
    if not parts:
        return 0
    if not parts[0].isdigit():
        return None
    value = int(parts[0])
    if value < 10 or value > 200:
        return None
    return value


def _memory_extract_job_id(group_id: str, limit: int | None) -> str:
    suffix = str(limit) if limit else "default"
    return f"memory-extract:{group_id}:{suffix}"


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


def _memory_status_filter(status: str) -> tuple[str, tuple[Any, ...]]:
    normalized = status.strip().lower() if status else "active"
    if normalized in {"active", "recallable"}:
        return _recall_status_filter(), ()
    if normalized == "all":
        return "status <> 'deleted'", ()
    if normalized == "archived":
        return "status <> 'deleted' AND (status = 'archived' OR COALESCE(lifecycle_status, 'confirmed') = 'archived')", ()
    if normalized in VALID_LIFECYCLE_STATUSES:
        return "status = 'active' AND COALESCE(lifecycle_status, 'confirmed') = %s", (normalized,)
    return _recall_status_filter(), ()


def _recall_status_filter() -> str:
    if not _recall_lifecycle_filter_enabled():
        return "status = 'active' AND COALESCE(lifecycle_status, 'confirmed') <> 'archived'"
    return "status = 'active' AND COALESCE(lifecycle_status, 'confirmed') IN ('confirmed', 'reinforced')"


def class_for_type(memory_type: str) -> str:
    normalized = str(memory_type or "").strip().lower()
    if normalized in {"style", "preference", "warning"}:
        return "procedural"
    if normalized == "relationship":
        return "social"
    return "semantic"


def initial_lifecycle_status(item: dict[str, Any]) -> str:
    explicit = str(item.get("lifecycle_status") or "").strip().lower()
    if explicit in VALID_LIFECYCLE_STATUSES:
        return explicit
    memory_type = str(item.get("memory_type") or "").strip().lower()
    confidence = _float_value(item.get("confidence"), 0.5)
    importance = _float_value(item.get("importance"), 0.5)
    source_count = len(_evidence_values(item.get("evidence_message_ids")))
    if memory_type == "warning" and confidence >= 0.7:
        return "confirmed"
    if confidence >= 0.78 and importance >= 0.55 and source_count >= 2:
        return "confirmed"
    return "weak"


def recall_eligible(record: MemoryRecord) -> bool:
    if record.status != "active":
        return False
    if not _recall_lifecycle_filter_enabled():
        return record.lifecycle_status != "archived"
    return record.lifecycle_status in RECALL_LIFECYCLE_STATUSES


def compute_quality_score(record: MemoryRecord) -> float:
    score = (
        record.confidence * 0.35
        + record.importance * 0.25
        + record.stability * 0.15
        + min(record.source_count, 5) / 5 * 0.15
        + record.decay_score * 0.10
        - min(record.contradiction_count, 3) * 0.10
    )
    return round(_clamp(score), 4)


def memory_score(record: MemoryRecord, request: ChatRequest, keywords: list[str]) -> MemoryScore:
    keyword_match = _keyword_match_score(record.content, keywords)
    entity_relevance = _entity_relevance_score(record, request)
    scope_relevance = _scope_relevance_score(record, request)
    recency_weight = _recency_weight(record.last_seen_at)
    total = _clamp(
        keyword_match * 0.30
        + entity_relevance * 0.20
        + scope_relevance * 0.15
        + record.quality_score * 0.25
        + recency_weight * 0.10
    )
    return MemoryScore(
        total=round(total, 4),
        keyword_match=round(keyword_match, 4),
        entity_relevance=round(entity_relevance, 4),
        scope_relevance=round(scope_relevance, 4),
        quality_score=round(record.quality_score, 4),
        recency_weight=round(recency_weight, 4),
    )


def decay_score_for(memory_class: str, age_days: float) -> float:
    half_life_days = {
        "episodic": 30,
        "semantic": 180,
        "procedural": 365,
        "affective": 180,
        "social": 120,
        "persona": 730,
    }.get(memory_class, 180)
    return round(_clamp(1 - max(0.0, age_days) / half_life_days), 4)


def _reinforced_lifecycle_status(
    existing_status: str,
    *,
    memory_type: str,
    confidence: float,
    importance: float,
    source_count: int,
    stability: float,
) -> str:
    if existing_status == "contradicted":
        return "contradicted"
    if existing_status == "reinforced":
        return "reinforced"
    if existing_status == "archived":
        return "archived"
    candidate_status = initial_lifecycle_status(
        {
            "memory_type": memory_type,
            "confidence": confidence,
            "importance": importance,
            "evidence_message_ids": list(range(source_count)),
        }
    )
    if existing_status == "stale" and candidate_status in RECALL_LIFECYCLE_STATUSES:
        candidate_status = "confirmed"
    elif existing_status == "confirmed":
        candidate_status = "confirmed"
    elif existing_status == "weak" and candidate_status != "confirmed":
        candidate_status = "weak"

    if candidate_status == "confirmed" and (source_count >= 3 or stability >= 0.75):
        return "reinforced"
    return candidate_status


def _memory_class_from_item(item: dict[str, Any]) -> str:
    explicit = str(item.get("memory_class") or "").strip().lower()
    if explicit in VALID_MEMORY_CLASSES:
        return explicit
    return class_for_type(str(item.get("memory_type") or ""))


def _quality_score_sql(
    *,
    stability_sql: str = "stability",
    decay_sql: str = "decay_score",
    contradiction_sql: str = "contradiction_count",
) -> str:
    return (
        "LEAST(1.0, GREATEST(0.0, "
        "confidence * 0.35 + "
        "importance * 0.25 + "
        f"{stability_sql} * 0.15 + "
        "LEAST(source_count, 5) / 5.0 * 0.15 + "
        f"{decay_sql} * 0.10 - "
        f"LEAST({contradiction_sql}, 3) * 0.10"
        "))"
    )


def _admin_lifecycle_metadata(action: str, actor_id: str) -> dict[str, Any]:
    return {
        "last_admin_lifecycle_action": {
            "action": action,
            "actor_id": actor_id,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    }


def _keyword_match_score(content: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    normalized_content = str(content or "").lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in normalized_content)
    return _clamp(hits / len(keywords))


def _entity_relevance_score(record: MemoryRecord, request: ChatRequest) -> float:
    group_id = _string_id(request.group_id)
    user_id = _string_id(request.user_id)
    if record.scope == "global":
        return 0.2
    score = 0.0
    if group_id and record.group_id == group_id:
        score += 0.45
    if user_id and record.user_id == user_id:
        score += 0.45
    if user_id and record.target_user_id == user_id:
        score += 0.35
    return _clamp(score)


def _scope_relevance_score(record: MemoryRecord, request: ChatRequest) -> float:
    user_id = _string_id(request.user_id)
    if record.scope in {"user", "relationship"} and (
        record.user_id == user_id or record.target_user_id == user_id
    ):
        return 1.0
    if record.scope == "group":
        return 0.75
    if record.scope == "global":
        return 0.4
    return 0.5


def _recency_weight(value: datetime | None) -> float:
    if value is None:
        return 0.5
    age_days = _age_days(value, datetime.now(timezone.utc))
    if age_days <= 30:
        return 1.0
    if age_days >= 180:
        return 0.2
    return _clamp(1.0 - ((age_days - 30) / 150) * 0.8)


def _age_days(value: datetime | None, now: datetime) -> float:
    if value is None:
        return 0.0
    return max(0.0, (now - _aware_datetime(value)).total_seconds() / 86400)


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return _aware_datetime(value).timestamp()


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _id_set(raw: str) -> set[str]:
    return {part for part in re.split(r"[\s,;]+", raw.strip()) if part}


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


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
    evidence = _evidence_values(row.get("evidence_message_ids"))
    memory_type = str(row["memory_type"])
    quality_missing = row.get("quality_score") is None
    record = MemoryRecord(
        id=int(row["id"]),
        scope=str(row["scope"]),
        memory_type=memory_type,
        content=str(row["content"]),
        confidence=_float_value(row.get("confidence"), 0.5),
        importance=_float_value(row.get("importance"), 0.5),
        group_id=_string_id(row.get("group_id")),
        user_id=_string_id(row.get("user_id")),
        target_user_id=_string_id(row.get("target_user_id")),
        status=str(row.get("status") or "active"),
        memory_class=str(row.get("memory_class") or class_for_type(memory_type)),
        lifecycle_status=str(row.get("lifecycle_status") or ("archived" if row.get("status") == "archived" else "confirmed")),
        stability=_float_value(row.get("stability"), 0.5),
        decay_score=_float_value(row.get("decay_score"), 1.0),
        contradiction_count=_int_value(row.get("contradiction_count"), 0),
        source_count=_int_value(row.get("source_count"), len(evidence) or 1),
        quality_score=_float_value(row.get("quality_score"), 0.5),
        last_confirmed_at=_datetime_or_none(row.get("last_confirmed_at")),
        archived_at=_datetime_or_none(row.get("archived_at")),
        last_seen_at=_datetime_or_none(row.get("last_seen_at")),
        evidence_message_ids=evidence,
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )
    if quality_missing:
        record.quality_score = compute_quality_score(record)
    return record


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


def _normalize_memory_content(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _merge_evidence_ids(existing: Any, incoming: Any) -> list[int]:
    merged: list[int] = []
    for value in _evidence_values(existing) + _evidence_values(incoming):
        if value not in merged:
            merged.append(value)
    return merged


def _evidence_values(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover
        raise MemoryConfigurationError("psycopg is required for JSONB values") from exc

    return Jsonb(value)
