import json
from typing import Any

from schemas import BrainJSONMessage, BrainMessage, BrainResponse, ChatRequest, ToolCall, ToolCallRequest
from modules.base import ModuleContext, parse_command_invocation
from modules.registry import default_registry
from services.tools import call_tool


def build_chat_response(request: ChatRequest) -> BrainResponse:
    text, context = _request_text_and_context(request)
    module_texts = _request_module_texts(request, text)
    if not text and not module_texts:
        return BrainResponse(handled=False, should_reply=False)

    for module_text in module_texts:
        module_response = default_registry.handle(module_text, context, request)
        if module_response is not None:
            return module_response

    tool_request = _plan_tool_call(text) if text else None
    if tool_request is not None:
        result = call_tool(tool_request, context)
        reply = str(result.data.get("text", "")) if result.ok else ""
        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
            tool_calls=[ToolCall(name=tool_request.name, arguments=tool_request.arguments)],
            metadata={"planner": "fake"},
        )

    return BrainResponse(handled=False, should_reply=False, metadata={"reason": "no_route"})


def _request_module_texts(request: ChatRequest, selected_text: str) -> list[str]:
    candidates = []
    if selected_text:
        candidates.append(selected_text)

    for segment in request.text_segments:
        text = segment.strip()
        if text:
            candidates.append(text)

    for json_message in request.json_messages:
        text = _json_message_text(json_message)
        if text:
            candidates.append(text)

    return _dedupe_texts(candidates)


def _request_text_and_context(request: ChatRequest) -> tuple[str, ModuleContext]:
    top_level_context = _top_level_context(request)
    candidates: list[tuple[str, ModuleContext]] = [
        (request.text, top_level_context),
        (request.content, top_level_context),
    ]
    if request.message is not None:
        candidates.append((_message_text(request.message), _message_context(request.message, top_level_context)))
    candidates.extend((_message_text(message), _message_context(message, top_level_context)) for message in request.messages)

    for candidate, context in reversed(candidates):
        text = candidate.strip()
        if text:
            return text, context
    return "", top_level_context


def _message_text(message: BrainMessage) -> str:
    return message.text or message.content


def _json_message_text(message: BrainJSONMessage) -> str:
    parts = []
    parts.extend(_json_string_values(message.parsed))
    if message.raw:
        try:
            decoded = json.loads(message.raw)
        except json.JSONDecodeError:
            parts.append(message.raw)
        else:
            parts.extend(_json_string_values(decoded))
    return "\n".join(_dedupe_texts(parts))


def _json_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts = []
        for child in value.values():
            parts.extend(_json_string_values(child))
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(_json_string_values(child))
        return parts
    return []


def _dedupe_texts(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _top_level_context(request: ChatRequest) -> ModuleContext:
    return ModuleContext(
        group_id=_string_id(request.group_id),
        user_id=_string_id(request.user_id),
        message_type=request.message_type or "",
    )


def _message_context(message: BrainMessage, fallback: ModuleContext) -> ModuleContext:
    return ModuleContext(
        group_id=_string_id(message.group_id) or fallback.group_id,
        user_id=_string_id(message.user_id) or fallback.user_id,
        message_type=message.message_type or fallback.message_type,
    )


def _string_id(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _plan_tool_call(text: str) -> ToolCallRequest | None:
    invocation = parse_command_invocation(text, ("echo",))
    if invocation is None:
        return None

    return ToolCallRequest(name="echo", arguments={"text": invocation.argument})
