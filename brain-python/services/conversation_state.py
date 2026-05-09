import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from schemas import BrainResponse, ChatRequest


logger = logging.getLogger(__name__)

RECENT_MESSAGE_LIMIT = 80
TOPIC_LIMIT = 8
SPEAKER_LIMIT = 12
RECENT_WINDOW_SQL = "10 minutes"
BOT_RECENT_REPLY_SECONDS = 180

TOPIC_RE = re.compile(r"[A-Za-z0-9_+#.-]{2,}|[\u4e00-\u9fff]{2,}")
STOPWORDS = {
    "the",
    "and",
    "for",
    "you",
    "with",
    "this",
    "that",
    "http",
    "https",
    "com",
    "www",
    "我",
    "你",
    "他",
    "她",
    "它",
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "一下",
    "什么",
    "可以",
    "还是",
    "就是",
}


class ConversationStateError(Exception):
    pass


@dataclass(frozen=True)
class ConversationState:
    conversation_id: int
    active_topics: list[str] = field(default_factory=list)
    mood: str = "neutral"
    conversation_velocity: str = "quiet"
    current_speaker_ids: list[str] = field(default_factory=list)
    last_bot_reply_at: datetime | None = None
    bot_reply_count_1h: int = 0
    bot_reply_count_24h: int = 0
    should_avoid_long_reply: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime | None = None


class PostgresConversationStateStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    @classmethod
    def from_env(cls) -> "PostgresConversationStateStore":
        return cls(os.getenv("DATABASE_URL", "").strip())

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def update_from_message(self, message_id: int | None) -> ConversationState | None:
        if not self.enabled or message_id is None:
            return None

        rows = self._fetch_all("SELECT conversation_id FROM messages WHERE id = %s", (message_id,))
        if not rows:
            return None
        return self.refresh_conversation(int(rows[0]["conversation_id"]))

    def update_from_bot_response(self, message_id: int | None, response: BrainResponse) -> ConversationState | None:
        if not response.should_reply:
            return None
        if not self.enabled or message_id is None:
            return None

        rows = self._fetch_all("SELECT conversation_id FROM messages WHERE id = %s", (message_id,))
        if not rows:
            return None
        return self.refresh_conversation(int(rows[0]["conversation_id"]))

    def read_for_request(self, request: ChatRequest) -> ConversationState | None:
        if not self.enabled:
            return None

        conversation_type, external_id = _conversation_key(request)
        if not conversation_type or not external_id:
            return None

        rows = self._fetch_all(
            """
            SELECT cs.*
            FROM conversation_states cs
            JOIN conversations c ON c.id = cs.conversation_id
            WHERE c.conversation_type = %s
              AND c.external_id = %s
            """,
            (conversation_type, external_id),
        )
        if not rows:
            return None
        return _state_from_row(rows[0])

    def refresh_conversation(self, conversation_id: int) -> ConversationState:
        recent_rows = self._fetch_all(
            f"""
            SELECT text, sender_user_id, created_at
            FROM messages
            WHERE conversation_id = %s
              AND created_at >= now() - interval '{RECENT_WINDOW_SQL}'
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (conversation_id, RECENT_MESSAGE_LIMIT),
        )
        bot_rows = self._fetch_all(
            """
            SELECT
                count(*) FILTER (WHERE br.created_at >= now() - interval '1 hour') AS bot_reply_count_1h,
                count(*) FILTER (WHERE br.created_at >= now() - interval '24 hours') AS bot_reply_count_24h,
                max(br.created_at) AS last_bot_reply_at
            FROM bot_responses br
            JOIN messages m ON m.id = br.message_id
            WHERE m.conversation_id = %s
              AND br.should_reply = true
              AND br.created_at >= now() - interval '24 hours'
            """,
            (conversation_id,),
        )
        state = derive_state(
            conversation_id=conversation_id,
            recent_messages=recent_rows,
            bot_stats=bot_rows[0] if bot_rows else {},
        )
        self._upsert_state(state)
        return state

    def _upsert_state(self, state: ConversationState) -> None:
        self._fetch_all(
            """
            INSERT INTO conversation_states (
                conversation_id,
                active_topics,
                mood,
                conversation_velocity,
                current_speaker_ids,
                last_bot_reply_at,
                bot_reply_count_1h,
                bot_reply_count_24h,
                should_avoid_long_reply,
                metadata,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (conversation_id)
            DO UPDATE SET
                active_topics = EXCLUDED.active_topics,
                mood = EXCLUDED.mood,
                conversation_velocity = EXCLUDED.conversation_velocity,
                current_speaker_ids = EXCLUDED.current_speaker_ids,
                last_bot_reply_at = EXCLUDED.last_bot_reply_at,
                bot_reply_count_1h = EXCLUDED.bot_reply_count_1h,
                bot_reply_count_24h = EXCLUDED.bot_reply_count_24h,
                should_avoid_long_reply = EXCLUDED.should_avoid_long_reply,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING conversation_id
            """,
            (
                state.conversation_id,
                _jsonb(state.active_topics),
                state.mood,
                state.conversation_velocity,
                _jsonb(state.current_speaker_ids),
                state.last_bot_reply_at,
                state.bot_reply_count_1h,
                state.bot_reply_count_24h,
                state.should_avoid_long_reply,
                _jsonb(state.metadata),
            ),
        )

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise ConversationStateError("psycopg is required for conversation state") from exc

        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
        except psycopg.errors.UndefinedTable as exc:
            raise ConversationStateError("conversation state tables are missing; run database migrations") from exc
        except psycopg.Error as exc:
            raise ConversationStateError(f"conversation state database error: {exc}") from exc


def safe_update_from_message(message_id: int | None) -> ConversationState | None:
    try:
        return PostgresConversationStateStore.from_env().update_from_message(message_id)
    except Exception as exc:  # pragma: no cover - state must never break chat handling.
        logger.warning("conversation state update skipped: %s", exc)
        return None


def safe_update_from_bot_response(message_id: int | None, response: BrainResponse) -> ConversationState | None:
    try:
        return PostgresConversationStateStore.from_env().update_from_bot_response(message_id, response)
    except Exception as exc:  # pragma: no cover - state must never break chat handling.
        logger.warning("conversation state bot update skipped: %s", exc)
        return None


def safe_read_for_request(request: ChatRequest) -> ConversationState | None:
    try:
        return PostgresConversationStateStore.from_env().read_for_request(request)
    except Exception as exc:  # pragma: no cover - prompt context should degrade cleanly.
        logger.warning("conversation state read skipped: %s", exc)
        return None


def derive_state(
    *,
    conversation_id: int,
    recent_messages: list[dict[str, Any]],
    bot_stats: dict[str, Any],
) -> ConversationState:
    message_count = len(recent_messages)
    speakers = _recent_speakers(recent_messages)
    velocity = _velocity(message_count)
    last_bot_reply_at = _datetime_value(bot_stats.get("last_bot_reply_at"))
    bot_reply_count_1h = _int_value(bot_stats.get("bot_reply_count_1h"))
    bot_reply_count_24h = _int_value(bot_stats.get("bot_reply_count_24h"))
    avoid_long_reply = (
        velocity in {"active", "burst"}
        or len(speakers) >= 4
        or bot_reply_count_1h >= 5
        or _recent_datetime(last_bot_reply_at, BOT_RECENT_REPLY_SECONDS)
    )
    return ConversationState(
        conversation_id=conversation_id,
        active_topics=_active_topics(recent_messages),
        mood="neutral",
        conversation_velocity=velocity,
        current_speaker_ids=speakers,
        last_bot_reply_at=last_bot_reply_at,
        bot_reply_count_1h=bot_reply_count_1h,
        bot_reply_count_24h=bot_reply_count_24h,
        should_avoid_long_reply=avoid_long_reply,
        metadata={
            "recent_window": RECENT_WINDOW_SQL,
            "recent_message_count": message_count,
            "speaker_count": len(speakers),
        },
    )


def summarize_for_prompt(state: ConversationState | None) -> str:
    if state is None:
        return ""

    lines = [
        "当前群聊状态：",
        f"- velocity: {state.conversation_velocity}",
        f"- mood: {state.mood}",
        f"- current_speaker_count: {len(state.current_speaker_ids)}",
        f"- bot_reply_count_1h: {state.bot_reply_count_1h}",
        f"- bot_reply_count_24h: {state.bot_reply_count_24h}",
        f"- should_avoid_long_reply: {str(state.should_avoid_long_reply).lower()}",
    ]
    if state.active_topics:
        lines.append(f"- active_topics: {', '.join(state.active_topics[:TOPIC_LIMIT])}")
    if state.should_avoid_long_reply:
        lines.append("- reply_guidance: 当前群聊较快或 bot 最近已回复，优先短回复。")
    return "\n".join(lines)


def _state_from_row(row: dict[str, Any]) -> ConversationState:
    return ConversationState(
        conversation_id=int(row["conversation_id"]),
        active_topics=_string_list(row.get("active_topics")),
        mood=str(row.get("mood") or "neutral"),
        conversation_velocity=str(row.get("conversation_velocity") or "quiet"),
        current_speaker_ids=_string_list(row.get("current_speaker_ids")),
        last_bot_reply_at=_datetime_value(row.get("last_bot_reply_at")),
        bot_reply_count_1h=_int_value(row.get("bot_reply_count_1h")),
        bot_reply_count_24h=_int_value(row.get("bot_reply_count_24h")),
        should_avoid_long_reply=bool(row.get("should_avoid_long_reply")),
        metadata=dict(row.get("metadata") or {}),
        updated_at=_datetime_value(row.get("updated_at")),
    )


def _conversation_key(request: ChatRequest) -> tuple[str, str]:
    message_type = (request.message_type or "").strip().lower()
    group_id = _string_id(request.group_id)
    user_id = _string_id(request.user_id)
    if message_type == "group" or group_id:
        return "group", group_id or ""
    if message_type == "private" or user_id:
        return "private", user_id or ""
    return "", ""


def _active_topics(recent_messages: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, row in enumerate(recent_messages):
        for token in _topic_tokens(row.get("text")):
            counts[token] = counts.get(token, 0) + 1
            first_seen.setdefault(token, index)
    ranked = sorted(counts, key=lambda token: (-counts[token], first_seen[token], token))
    return ranked[:TOPIC_LIMIT]


def _topic_tokens(value: Any) -> list[str]:
    text = str(value or "").lower()
    tokens = []
    seen = set()
    for match in TOPIC_RE.finditer(text):
        token = match.group(0).strip("._-")
        if len(token) < 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _recent_speakers(recent_messages: list[dict[str, Any]]) -> list[str]:
    speakers = []
    seen = set()
    for row in recent_messages:
        speaker = _string_id(row.get("sender_user_id"))
        if not speaker or speaker in seen:
            continue
        seen.add(speaker)
        speakers.append(speaker)
        if len(speakers) >= SPEAKER_LIMIT:
            break
    return speakers


def _velocity(message_count: int) -> str:
    if message_count >= 25:
        return "burst"
    if message_count >= 12:
        return "active"
    if message_count >= 4:
        return "normal"
    return "quiet"


def _recent_datetime(value: datetime | None, seconds: int) -> bool:
    if value is None:
        return False
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
    return 0 <= age.total_seconds() <= seconds


def _datetime_value(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_string_id(item) for item in value if _string_id(item)]


def _string_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover
        raise ConversationStateError("psycopg is required for JSONB values") from exc

    return Jsonb(value)
