import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from services.memory import VALID_MEMORY_TYPES, MemoryError


DEFAULT_BATCH_SIZE = 80
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_TIMEOUT = 30.0
MIN_BATCH_SIZE = 10
MAX_BATCH_SIZE = 200
MAX_MEMORY_CONTENT_CHARS = 300
ALLOWED_SCOPES = {"group", "user", "relationship"}
ALLOWED_MEMORY_CLASSES = {"episodic", "semantic", "procedural", "affective", "social", "persona"}
MEMORY_CLASS_BY_TYPE = {
    "fact": "semantic",
    "topic": "semantic",
    "summary": "semantic",
    "style": "procedural",
    "preference": "procedural",
    "relationship": "social",
    "warning": "procedural",
}


class MemoryExtractorError(MemoryError):
    pass


class MemoryExtractorConfigurationError(MemoryExtractorError):
    pass


class MemoryExtractorNoMessagesError(MemoryExtractorError):
    pass


class MemoryExtractorUpstreamError(MemoryExtractorError):
    pass


@dataclass
class ExtractionResult:
    run_id: int
    input_message_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    memory_ids: list[int]


def extract_group_memories(
    store: Any,
    group_id: str,
    *,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
) -> ExtractionResult:
    config = config or config_from_env()
    batch_size = _batch_size(limit, config["batch_size"])
    messages = store.recent_group_messages_for_extraction(group_id, limit=batch_size)
    if not messages:
        raise MemoryExtractorNoMessagesError("no text messages available")

    input_message_ids = [_int_id(message.get("id")) for message in messages if _int_id(message.get("id")) is not None]
    conversation_id = _int_id(messages[0].get("conversation_id"))
    run_id = store.create_memory_run(
        group_id=group_id,
        conversation_id=conversation_id,
        input_message_ids=input_message_ids,
        model=config["model"],
        metadata={
            "batch_size": batch_size,
            "max_candidates": config["max_candidates"],
            "version": "memory-extractor-mvp",
        },
    )

    try:
        raw_candidates = _call_extractor_model(config, group_id, messages)
        accepted, skipped = _validate_candidates(raw_candidates, group_id, messages, config["max_candidates"])
        memory_ids: list[int] = []
        inserted_count = 0
        updated_count = 0

        for item in accepted:
            memory_id, action = store.upsert_extracted_memory(item)
            memory_ids.append(memory_id)
            if action == "inserted":
                inserted_count += 1
            elif action == "updated":
                updated_count += 1

        store.finish_memory_run(
            run_id,
            status="succeeded",
            output_memory_ids=memory_ids,
            metadata={
                "inserted": inserted_count,
                "updated": updated_count,
                "skipped": skipped,
                "candidate_count": len(raw_candidates),
            },
        )
        return ExtractionResult(
            run_id=run_id,
            input_message_count=len(messages),
            inserted_count=inserted_count,
            updated_count=updated_count,
            skipped_count=skipped,
            memory_ids=memory_ids,
        )
    except Exception as exc:
        store.finish_memory_run(
            run_id,
            status="failed",
            error=str(exc),
            metadata={"error_type": exc.__class__.__name__},
        )
        if isinstance(exc, MemoryExtractorError):
            raise
        raise MemoryExtractorUpstreamError(str(exc)) from exc


def config_from_env() -> dict[str, Any]:
    if not _env_bool("MEMORY_EXTRACTOR_ENABLED", False):
        raise MemoryExtractorConfigurationError("MEMORY_EXTRACTOR_ENABLED is false")

    base_url = _env_first("MEMORY_EXTRACTOR_BASE_URL", "AI_BASE_URL").rstrip("/")
    api_key = _env_first("MEMORY_EXTRACTOR_API_KEY", "AI_API_KEY")
    model = _env_first("MEMORY_EXTRACTOR_MODEL", "AI_MODEL")
    missing = []
    if not base_url:
        missing.append("MEMORY_EXTRACTOR_BASE_URL or AI_BASE_URL")
    if not model:
        missing.append("MEMORY_EXTRACTOR_MODEL or AI_MODEL")
    if missing:
        raise MemoryExtractorConfigurationError("missing " + ", ".join(missing))

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout": _env_float("MEMORY_EXTRACTOR_TIMEOUT", DEFAULT_TIMEOUT),
        "batch_size": _env_int("MEMORY_EXTRACTOR_BATCH_SIZE", DEFAULT_BATCH_SIZE),
        "max_candidates": max(1, _env_int("MEMORY_EXTRACTOR_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES)),
    }


def _call_extractor_model(config: dict[str, Any], group_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"

    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _input_prompt(group_id, messages, config["max_candidates"])},
        ],
        "temperature": 0.0,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }

    try:
        response = httpx.post(
            _chat_completions_url(config["base_url"]),
            json=payload,
            headers=headers,
            timeout=config["timeout"],
        )
        response.raise_for_status()
        content = _extract_reply(response.json()).strip()
        parsed = json.loads(content)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise MemoryExtractorUpstreamError(str(exc)) from exc

    memories = parsed.get("memories") if isinstance(parsed, dict) else None
    if not isinstance(memories, list):
        raise MemoryExtractorUpstreamError("extractor response must contain a memories array")
    return [item for item in memories if isinstance(item, dict)]


def _validate_candidates(
    candidates: list[dict[str, Any]],
    group_id: str,
    messages: list[dict[str, Any]],
    max_candidates: int,
) -> tuple[list[dict[str, Any]], int]:
    message_ids = {_int_id(message.get("id")) for message in messages}
    message_ids.discard(None)
    sender_ids = {_string_id(message.get("sender_user_id")) for message in messages}
    sender_ids.discard("")

    accepted: list[dict[str, Any]] = []
    skipped = 0
    for candidate in candidates[:max_candidates]:
        item = _clean_candidate(candidate, group_id)
        if item is None:
            skipped += 1
            continue

        evidence_ids = item["evidence_message_ids"]
        if not evidence_ids or any(message_id not in message_ids for message_id in evidence_ids):
            skipped += 1
            continue

        if item["scope"] == "user" and item["user_id"] not in sender_ids:
            skipped += 1
            continue

        if item["scope"] == "relationship":
            if item["user_id"] not in sender_ids or item["target_user_id"] not in sender_ids:
                skipped += 1
                continue
            if item["user_id"] == item["target_user_id"]:
                skipped += 1
                continue

        accepted.append(item)

    skipped += max(0, len(candidates) - max_candidates)
    return accepted, skipped


def _clean_candidate(candidate: dict[str, Any], group_id: str) -> dict[str, Any] | None:
    scope = _string_id(candidate.get("scope")).lower()
    memory_type = _string_id(candidate.get("memory_type")).lower()
    content = re.sub(r"\s+", " ", _string_id(candidate.get("content"))).strip()
    user_id = _string_id(candidate.get("user_id"))
    target_user_id = _string_id(candidate.get("target_user_id"))
    candidate_group_id = _string_id(candidate.get("group_id"))

    if scope not in ALLOWED_SCOPES:
        return None
    if memory_type not in VALID_MEMORY_TYPES:
        return None
    memory_class = _memory_class(candidate.get("memory_class"), memory_type)
    if memory_class is None:
        return None
    if candidate_group_id != group_id:
        return None
    if not content or len(content) > MAX_MEMORY_CONTENT_CHARS:
        return None

    evidence_ids = _evidence_ids(candidate.get("evidence_message_ids"))
    confidence = _bounded_score(candidate.get("confidence"))
    importance = _bounded_score(candidate.get("importance"))
    if confidence is None or importance is None:
        return None

    if scope == "group":
        user_id = ""
        target_user_id = ""
    elif scope == "user":
        target_user_id = ""
        if not user_id:
            return None
    elif scope == "relationship":
        if not user_id or not target_user_id:
            return None

    metadata = {"raw_candidate": candidate}
    if "conflicts_with_memory_id" in candidate:
        conflicts_with_memory_id = _int_id(candidate.get("conflicts_with_memory_id"))
        if conflicts_with_memory_id is not None:
            metadata["conflicts_with_memory_id"] = conflicts_with_memory_id
    if "conflicts_with" in candidate:
        metadata["conflicts_with"] = candidate.get("conflicts_with")

    return {
        "scope": scope,
        "memory_type": memory_type,
        "memory_class": memory_class,
        "content": content,
        "confidence": confidence,
        "importance": importance,
        "evidence_message_ids": evidence_ids,
        "group_id": group_id,
        "user_id": user_id,
        "target_user_id": target_user_id,
        "metadata": metadata,
    }


def _system_prompt() -> str:
    return (
        "你是 TestBot 的长期记忆抽取器。只输出严格 JSON 对象，格式为 {\"memories\": [...]}。"
        "只抽取长期有价值的信息：用户偏好、稳定事实、群规/群风格、用户关系、常聊主题、需要避免的 warning。"
        "跳过临时闲聊、一次性请求、猜测、没有证据的信息、密钥/token/密码等敏感内容。"
        "每条 memory 必须能由 evidence_message_ids 指向的消息直接支持。"
    )


def _input_prompt(group_id: str, messages: list[dict[str, Any]], max_candidates: int) -> str:
    lines = [
        f"group_id: {group_id}",
        f"最多输出 {max_candidates} 条 memory。",
        "允许 scope: group, user, relationship。不要输出 global。",
        "允许 memory_type: preference, fact, style, relationship, topic, summary, warning。",
        "允许 memory_class: episodic, semantic, procedural, affective, social, persona。",
        "每条 memory 字段：scope, memory_type, memory_class, content, confidence, importance, evidence_message_ids, group_id, user_id, target_user_id。",
        "messages:",
    ]
    for message in messages:
        sender_name = _string_id(message.get("sender_card")) or _string_id(message.get("sender_nickname"))
        text = _string_id(message.get("text"))
        lines.append(
            json.dumps(
                {
                    "id": _int_id(message.get("id")),
                    "user_id": _string_id(message.get("sender_user_id")),
                    "name": sender_name,
                    "text": text[:500],
                    "created_at": _iso(message.get("created_at")),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def _extract_reply(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            )
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _chat_completions_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def _batch_size(limit: int | None, configured: int) -> int:
    value = limit or configured or DEFAULT_BATCH_SIZE
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, value))


def _evidence_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        parsed = _int_id(item)
        if parsed is not None and parsed not in out:
            out.append(parsed)
    return out


def _bounded_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 1:
        return None
    return score


def _memory_class(value: Any, memory_type: str) -> str | None:
    memory_class = _string_id(value).lower()
    if not memory_class:
        return MEMORY_CLASS_BY_TYPE.get(memory_type)
    if memory_class not in ALLOWED_MEMORY_CLASSES:
        return None
    return memory_class


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_first(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
