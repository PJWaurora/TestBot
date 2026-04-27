from __future__ import annotations

import inspect
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult


DEFAULT_LIMIT = 50
MAX_LIMIT = 200
TOOL_NAME = "summary.recent_group_messages"
USAGE_TEXT = "用法：总结 或 总结 N（N 为要统计的最近消息条数）"
NO_HISTORY_TEXT = "暂无可总结的群聊记录：当前运行环境没有可用的群聊历史来源。"


class SummaryMessageSource(Protocol):
    def recent_group_messages(
        self,
        *,
        group_id: str | int | None = None,
        limit: int = DEFAULT_LIMIT,
        exclude_message_id: int | None = None,
    ) -> Sequence[Any]:
        ...


class SummaryModule:
    name = "summary"

    _COMMAND_PATTERN = re.compile(r"^总结(?:\s+(?P<limit>\S+))?$")
    _RECENT_METHODS = (
        "recent_group_messages",
        "get_recent_group_messages",
        "list_recent_group_messages",
        "fetch_recent_group_messages",
    )
    _WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9_'-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
    _CJK_PATTERN = re.compile(r"^[\u4e00-\u9fff]+$")
    _STOP_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
        "了",
        "也",
        "和",
        "在",
        "我们",
        "你们",
        "他们",
        "这个",
        "那个",
        "一下",
        "不是",
        "就是",
        "总结",
    }

    def __init__(
        self,
        message_source: SummaryMessageSource | None = None,
        default_limit: int = DEFAULT_LIMIT,
        max_limit: int = MAX_LIMIT,
    ) -> None:
        self.message_source = message_source if message_source is not None else self._default_message_source()
        self.default_limit = default_limit
        self.max_limit = max_limit

    def detect(self, text: str) -> bool:
        return self._COMMAND_PATTERN.match(text.strip()) is not None

    def parse(self, text: str) -> ModuleArguments:
        stripped = text.strip()
        match = self._COMMAND_PATTERN.match(stripped)
        if match is None:
            return {"ok": False, "error": "invalid_command", "message": USAGE_TEXT}

        raw_limit = match.group("limit")
        if raw_limit is None:
            return {"ok": True, "limit": self.default_limit, "query": stripped}

        try:
            requested_limit = int(raw_limit)
        except ValueError:
            return {"ok": False, "error": "invalid_limit", "message": USAGE_TEXT, "query": stripped}

        if requested_limit < 1:
            return {"ok": False, "error": "invalid_limit", "message": USAGE_TEXT, "query": stripped}

        return {
            "ok": True,
            "limit": min(requested_limit, self.max_limit),
            "requested_limit": requested_limit,
            "query": stripped,
        }

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        if not arguments.get("ok", True):
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "error": str(arguments.get("error", "invalid_command")),
                "message": str(arguments.get("message", USAGE_TEXT)),
            }

        limit = int(arguments.get("limit", self.default_limit))
        group_id = arguments.get("group_id")
        if not isinstance(group_id, (str, int)):
            group_id = None
        exclude_message_id = self._optional_int(arguments.get("exclude_message_id"))

        if self.message_source is None:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "error": "no_history_source",
                "limit": limit,
                "message": NO_HISTORY_TEXT,
            }

        try:
            messages = self._recent_group_messages(
                self.message_source,
                limit=limit,
                group_id=group_id,
                exclude_message_id=exclude_message_id,
            )
        except Exception as exc:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "error": "history_source_error",
                "limit": limit,
                "message": f"读取群聊记录失败：{exc}",
            }

        summary = self._summarize(messages)
        return {
            "tool_name": TOOL_NAME,
            "ok": True,
            "limit": limit,
            "group_id": group_id,
            "exclude_message_id": exclude_message_id,
            **summary,
        }

    def present(self, result: ModuleResult) -> BrainResponse:
        reply = self._reply_text(result)
        metadata = {
            "module": self.name,
            "tool_name": str(result.get("tool_name", TOOL_NAME)),
            "ok": bool(result.get("ok", False)),
            "limit": int(result.get("limit", self.default_limit)),
            "total_messages": int(result.get("total_messages", 0)),
        }
        if result.get("group_id") is not None:
            metadata["group_id"] = result["group_id"]
        if result.get("error"):
            metadata["error"] = str(result["error"])

        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
            metadata=metadata,
        )

    def _reply_text(self, result: ModuleResult) -> str:
        if not result.get("ok", False):
            return str(result.get("message") or NO_HISTORY_TEXT)

        limit = int(result.get("limit", self.default_limit))
        total_messages = int(result.get("total_messages", 0))
        if total_messages == 0:
            return f"最近 {limit} 条群聊记录为空，暂无可总结内容。"

        active_user_count = int(result.get("active_user_count", 0))
        active_users = self._format_count_pairs(result.get("active_users", []))
        top_words = self._format_count_pairs(result.get("top_words", []))
        return "\n".join(
            [
                f"聊天总结（最近 {limit} 条）",
                f"总消息数：{total_messages}",
                f"活跃用户：{active_user_count}人（{active_users or '无'}）",
                f"高频词：{top_words or '无'}",
            ]
        )

    def _summarize(self, messages: Sequence[Any]) -> dict[str, Any]:
        user_counts: Counter[str] = Counter()
        word_counts: Counter[str] = Counter()

        for message in messages:
            user_counts[self._message_user(message)] += 1
            word_counts.update(self._tokenize(self._message_text(message)))

        return {
            "total_messages": len(messages),
            "active_user_count": len(user_counts),
            "active_users": self._top_counts(user_counts, limit=5),
            "top_words": self._top_counts(word_counts, limit=10),
        }

    def _recent_group_messages(
        self,
        source: Any,
        *,
        limit: int,
        group_id: str | int | None,
        exclude_message_id: int | None,
    ) -> list[Any]:
        for method_name in self._RECENT_METHODS:
            method = getattr(source, method_name, None)
            if callable(method):
                fetch_limit = limit + 1 if exclude_message_id is not None else limit
                messages = self._call_recent_method(
                    method,
                    limit=fetch_limit,
                    group_id=group_id,
                    exclude_message_id=exclude_message_id,
                )
                if exclude_message_id is None:
                    filtered = list(messages or [])
                else:
                    filtered = [
                        message
                        for message in list(messages or [])
                        if self._message_id(message) != exclude_message_id
                    ]
                return filtered[:limit]
        raise AttributeError("message source does not expose recent_group_messages")

    @staticmethod
    def _call_recent_method(
        method: Callable[..., Sequence[Any] | None],
        *,
        limit: int,
        group_id: str | int | None,
        exclude_message_id: int | None,
    ) -> Sequence[Any]:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(group_id=group_id, limit=limit, exclude_message_id=exclude_message_id) or []

        parameters = signature.parameters
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        kwargs: dict[str, Any] = {}
        if accepts_kwargs or "group_id" in parameters:
            kwargs["group_id"] = group_id
        if accepts_kwargs or "limit" in parameters:
            kwargs["limit"] = limit
        if (accepts_kwargs or "exclude_message_id" in parameters) and exclude_message_id is not None:
            kwargs["exclude_message_id"] = exclude_message_id
        if kwargs:
            return method(**kwargs) or []

        positional = [
            parameter
            for parameter in parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional) >= 2:
            return method(group_id, limit) or []
        return method(limit) or []

    @staticmethod
    def _message_id(message: Any) -> int | None:
        value: Any = None
        if isinstance(message, dict):
            value = message.get("id")
        else:
            value = getattr(message, "id", None)
        return SummaryModule._optional_int(value)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _message_text(cls, message: Any) -> str:
        if isinstance(message, BrainMessage):
            return message.text or message.content

        if isinstance(message, dict):
            for key in ("text", "content", "message_content", "raw_message", "message"):
                if key in message:
                    text = cls._text_from_value(message[key])
                    if text:
                        return text
            return ""

        return str(message)

    @classmethod
    def _text_from_value(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = [cls._text_from_value(item) for item in value]
            return " ".join(part for part in parts if part)
        if isinstance(value, dict):
            if value.get("type") == "text" and isinstance(value.get("data"), dict):
                return str(value["data"].get("text", ""))
            for key in ("text", "content", "message_content"):
                if key in value:
                    return cls._text_from_value(value[key])
            return ""
        return str(value)

    @staticmethod
    def _message_user(message: Any) -> str:
        if isinstance(message, BrainMessage):
            return str(message.name or message.user_id or "未知用户")

        if isinstance(message, dict):
            sender = message.get("sender")
            if isinstance(sender, dict):
                for key in ("card", "nickname", "user_name", "name", "user_id"):
                    value = sender.get(key)
                    if value:
                        return str(value)

            for key in ("user_name", "nickname", "sender_name", "name", "user_id", "user"):
                value = message.get(key)
                if value:
                    return str(value)

        return "未知用户"

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        tokens: list[str] = []
        for match in cls._WORD_PATTERN.finditer(text.lower()):
            token = match.group(0).strip("_'-")
            if not token:
                continue
            if cls._CJK_PATTERN.match(token):
                tokens.extend(cls._cjk_tokens(token))
            elif len(token) > 1 and token not in cls._STOP_WORDS:
                tokens.append(token)
        return tokens

    @classmethod
    def _cjk_tokens(cls, token: str) -> list[str]:
        if len(token) <= 1:
            return []
        if len(token) == 2:
            return [] if token in cls._STOP_WORDS else [token]
        return [
            token[index : index + 2]
            for index in range(len(token) - 1)
            if token[index : index + 2] not in cls._STOP_WORDS
        ]

    @staticmethod
    def _top_counts(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
        return [
            {"name": name, "count": count}
            for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    @staticmethod
    def _format_count_pairs(value: Any) -> str:
        if not isinstance(value, list):
            return ""

        parts = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            count = item.get("count")
            if name and isinstance(count, int):
                parts.append(f"{name}({count})")
        return ", ".join(parts)

    @classmethod
    def _default_message_source(cls) -> Any | None:
        try:
            from services import persistence
        except Exception:
            return None

        for attribute in ("message_source", "message_repository", "repository", "persistence_repository"):
            source = getattr(persistence, attribute, None)
            if cls._looks_like_source(source):
                return source

        for factory_name in ("get_message_source", "get_message_repository", "get_repository", "get_default_repository"):
            factory = getattr(persistence, factory_name, None)
            if not callable(factory):
                continue
            try:
                source = factory()
            except Exception:
                continue
            if cls._looks_like_source(source):
                return source

        for class_name in ("MessageRepository", "ChatMessageRepository", "PersistenceRepository"):
            repository_class = getattr(persistence, class_name, None)
            if not callable(repository_class):
                continue
            try:
                source = repository_class()
            except Exception:
                continue
            if cls._looks_like_source(source):
                return source

        return None

    @classmethod
    def _looks_like_source(cls, source: Any) -> bool:
        return source is not None and any(callable(getattr(source, method, None)) for method in cls._RECENT_METHODS)


__all__ = ["SummaryMessageSource", "SummaryModule"]
